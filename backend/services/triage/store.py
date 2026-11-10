"""Persist completed Triage Investigations.

Every outcome — No Threat, Possible Threat, Limited — becomes one Patrol History
record carrying the full deterministic record (rules applicable, rules checked,
results, evidence, coverage gaps, retries, correlation, outcome and reason).
"""
from __future__ import annotations

import uuid

from core.db import db, now_utc
from core.evidence_model import EVIDENCE_SOURCES, TRIAGE_ADAPTER
from services.triage import telemetry
from services.triage.catalogue import LIMITED_CAUTION, gap_plain
from services.triage.completeness import incomplete_plain
from services.triage.contract import Outcome, TriageInvestigation

COLLECTION = "triage_investigations"

_STATE = {Outcome.NO_THREAT: "resting", Outcome.LIMITED: "ears_up", Outcome.POSSIBLE_THREAT: "growling"}
_NOUN = {"email": "email", "message": "text message", "link": "link", "call": "call", "file": "file", "app": "app"}


def incomplete_only(wire: dict) -> bool:
    """A Limited result that rests only on checks that couldn't run — a lookup that didn't answer, headers that weren't
    available — with no concerning sign behind it. That is an incomplete check, never a detected threat."""
    return (wire.get("outcome") == Outcome.LIMITED.value
            and not any(g.get("code") == "INSUFFICIENT_EVIDENCE" for g in wire.get("coverageGaps") or []))


def patrol_text(wire: dict, category: str) -> dict:
    """What the Patrol record says and how it is filed, from the Triage record alone (mirror for display:
    frontend src/domain/luddish/present.ts). Plain words: no rule counts, no internal names, nothing cut short."""
    noun = _NOUN.get(category, "item")
    outcome = wire.get("outcome")
    met = [r for r in wire.get("rules") or [] if r.get("result") == "met" and r.get("class") in ("DETECT", "CORRELATE")]
    gaps, incomplete = wire.get("coverageGaps") or [], wire.get("incompleteChecks") or []
    couldnt = list(dict.fromkeys(gap_plain(g["code"]) for g in gaps if g.get("code") != "INSUFFICIENT_EVIDENCE"))
    not_done = [incomplete_plain(c) for c in incomplete]
    if outcome == Outcome.POSSIBLE_THREAT.value:
        return {"state": "growling", "status": "active", "headline": f"Possible threat found in this {noun}",
                "what_happened": f"Apollo found warning signs in this {noun}: {'; '.join(r['title'] for r in met)}.",
                "why": [r["title"] for r in met] + not_done, "what_to_do": "Apollo is investigating this further."}
    if outcome == Outcome.LIMITED.value and not incomplete_only(wire):
        return {"state": "ears_up", "status": "active", "headline": f"This {noun} needs a closer look",
                "what_happened": wire.get("reason") or "", "why": [g.get("detail") or "" for g in gaps if g.get("code") == "INSUFFICIENT_EVIDENCE"] + couldnt + not_done,
                "what_to_do": LIMITED_CAUTION}
    if outcome == Outcome.LIMITED.value or not_done:
        # Checks that couldn't run are recorded as just that: no warning, and never a claim that it's safe.
        return {"state": "resting", "status": "resolved", "headline": f"Not every check could run on this {noun}",
                "what_happened": f"Apollo found no warning signs in what it could check. {' '.join(couldnt + not_done)}".strip(),
                "why": couldnt + not_done,
                "what_to_do": "Nothing found to act on. Because some checks couldn't run, this isn't a confirmation that it's safe."}
    return {"state": "resting", "status": "resolved", "headline": f"No threat found in this {noun}",
            "what_happened": f"Apollo found no warning signs in this {noun}, and every check it needed ran.",
            "why": [], "what_to_do": "Nothing to do."}


async def ensure_indexes() -> None:
    coll = db[COLLECTION]
    await coll.create_index([("device_id", 1), ("evaluated_at", -1)])
    await coll.create_index("investigation_id")


async def record_triage_history(device_id: str, investigation: TriageInvestigation, *,
                                category: str, evidence_source: str, subject: str = "",
                                client_submission_id: str | None = None,
                                investigation_case_id: str | None = None,
                                indicator_host: str | None = None, source: dict | None = None,
                                investigation_readiness: dict | None = None) -> str:
    """Save the Triage Investigation and project it into Patrol History (idempotent).

    `evidence_source` is what supplied the evidence (core/evidence_model.py): "connected_mailbox" for an email the
    server read from the person's mailbox, "device_submission" for what this device sent. Never the server itself."""
    if evidence_source not in EVIDENCE_SOURCES:
        raise ValueError(f"not an evidence source: {evidence_source!r}")
    wire = investigation.wire()
    incomplete = investigation.incomplete_checks
    saved = await db[COLLECTION].update_one(
        {"device_id": device_id, "investigation_id": investigation.investigation_id},
        {"$set": {"device_id": device_id, "investigation_id": investigation.investigation_id,
                  "category": category, "subject": subject or (source or {}).get("subject") or (source or {}).get("sender") or "", "record": wire,
                  "outcome": investigation.outcome.value, "evaluated_at": investigation.evaluated_at or now_utc(),
                  "investigation_case_id": investigation_case_id, "updated_at": now_utc()},
         "$setOnInsert": {"created_at": now_utc()}}, upsert=True)
    if saved.upserted_id:
        # Once per evaluation (this save is idempotent): outcome and cause codes for the "Limited by cause" report.
        device = await db.devices.find_one({"device_id": device_id}, {"_id": 0, "device_id": 1, "platform": 1, "adapter_mode": 1})
        await telemetry.record(device or {"device_id": device_id}, origin="server", source_type=wire["sourceType"],
                               outcome=wire["outcome"], causes=telemetry.causes_for(wire),
                               gap_codes=[g["code"] for g in wire["coverageGaps"]], catalogue_version=wire["catalogueVersion"],
                               incomplete=telemetry.incomplete_codes(wire))

    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"apollo-triage:{device_id}:{investigation.investigation_id}"))
    text = patrol_text(wire, category)
    if investigation_readiness is not None:
        if investigation_readiness["ready"]:
            text = {"state": "resting", "status": "resolved",
                    "headline": "Evidence passed to TC Hawkeye",
                    "what_happened": "There was enough evidence to begin an investigation.",
                    "why": [], "what_to_do": "Review the investigation for findings."}
        else:
            text = {"state": "resting", "status": "resolved",
                    "headline": "Investigation could not begin",
                    "what_happened": investigation_readiness["higginsExplanation"],
                    "why": [investigation_readiness["reason"]],
                    "what_to_do": investigation_readiness["higginsExplanation"]}
    gaps = investigation.coverage_gaps
    at = investigation.evaluated_at or now_utc()
    document = {
        "event_id": event_id, "device_id": device_id, "category": category, **text,
        "indicator_host": indicator_host, "indicator_digest": None, "local_indicator": None,
        "verified_block": False, "adapter_label": TRIAGE_ADAPTER,
        "occurred_at": at, "resolved_at": at if text["status"] == "resolved" else None,
        "trust_allowed": False, "claimed_brand": None, "scenario": None, "scent_id": None,
        "background": True, "investigation_case_id": investigation_case_id,
        "client_submission_id": client_submission_id,
        # Who sent it and what it said it was about, exactly as recorded — carried through to every screen.
        "source_metadata": source,
        # Worked from a privacy-protected copy; evidence missing when a check didn't finish or a gap was recorded.
        "evidence_representation": "privacy_protected_copy",
        "evidence_completeness": "partial" if incomplete or gaps else "complete",
        "triage_investigation": wire,
        "investigation_readiness": investigation_readiness,
        "initiator": "apollo_triage",
        "deleted_at": None, "updated_at": now_utc(),
    }
    # The evidence source and where it was processed are recorded once, when the record is filed.
    on_insert = {"created_at": now_utc(), "evidence_provenance": evidence_source, "processing_source": "apollosg_servers"}
    await db.patrol_events.update_one({"device_id": device_id, "event_id": event_id},
                                      {"$set": document, "$setOnInsert": on_insert}, upsert=True)
    return event_id
