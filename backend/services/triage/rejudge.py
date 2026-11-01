"""Past cases, judged again under the current rules — once per rule catalogue version, at startup (idempotent).

What changed and what it means for records already filed:
  - An email rule never reads Apollo's own observations as evidence. A rule recorded as met on an observation
    ("email finding: …") is withdrawn and the outcome worked out again from the rules that remain.
  - Missing email headers are a check that couldn't run, never a coverage gap: such a rule is "not applicable" and
    the missing sender authentication is recorded as an incomplete check.
  - A Limited result resting only on checks that couldn't run is filed as that, not as an ongoing warning.
  - Every Triage record carries who sent it and its subject, from the case's recorded source where there is one.
  - A threat list's page listing names exactly that page and its query, never the whole website and never the same
    page with another query: listings stored under the earlier page key are re-keyed, and reputation answers reached
    under the earlier matching are cleared (again under ":3", when a listing without a query stopped covering one).
A record that opened an investigation keeps its state and status: that case's own result is what every screen shows.
A record already closed (handled, trusted or resolved) stays closed: a re-judge changes its words, never reopens it.
"""
from __future__ import annotations

import logging

from core.db import db, now_utc
from core.evidence_model import TRIAGE_ADAPTER
from services.triage.catalogue import VERSION, gap_plain
from services.triage.completeness import AVAILABLE_CHECKS, incomplete_check, incomplete_plain
from services.triage.contract import Outcome
from services.triage.store import patrol_text
from services.patrol_status import closed

log = logging.getLogger("apollo.triage")
MARKER = f"triage_rejudge:{VERSION}:3"
_HEADER_GAP = "EMAIL_HEADERS_UNAVAILABLE"
_WITHDRAWN = "Withdrawn: this matched Apollo's own observation about the email, which is never evidence of it."


def rejudged(wire: dict) -> dict:
    """The Triage record as the current rules judge it, from what it recorded. Pure."""
    rules, changed = [], False
    for r in wire.get("rules") or []:
        r = dict(r)
        if r.get("result") == "met" and any(str(e).startswith("email finding:") for e in r.get("evidence") or []):
            r.update(result="not_met", evidence=[_WITHDRAWN], checked=True)
            changed = True
        elif r.get("result") == "coverage_gap" and r.get("coverageGap") == _HEADER_GAP:
            r.update(result="not_applicable", applicable=False, checked=False, coverageGap=None,
                     evidence=["Not applicable here: the email's technical sender information wasn't available."])
            changed = True
        rules.append(r)
    if not changed:
        return wire
    gaps = [g for g in wire.get("coverageGaps") or [] if g.get("code") != _HEADER_GAP]
    incomplete = list(wire.get("incompleteChecks") or [])
    if any(g.get("code") == _HEADER_GAP for g in wire.get("coverageGaps") or []) and not any(c.get("check") == "sender_authentication" for c in incomplete):
        incomplete.append(incomplete_check("sender_authentication", "not_recorded"))
    met = [r for r in rules if r.get("result") == "met" and r.get("class") in ("DETECT", "CORRELATE")]
    if met:
        outcome = Outcome.POSSIBLE_THREAT.value
        reason = met[0]["title"] + (f" (+{len(met) - 1} more deterministic rule(s) met)" if len(met) > 1 else "")
    elif gaps:
        outcome = Outcome.LIMITED.value
        reason = wire.get("reason") if wire.get("outcome") == Outcome.LIMITED.value else \
            "ApolloSG couldn't obtain enough evidence to decide. " + " ".join(gap_plain(g["code"]) for g in gaps)
    elif incomplete:
        outcome, reason = Outcome.NO_THREAT.value, f"{AVAILABLE_CHECKS}. Not completed: " + " ".join(incomplete_plain(c) for c in incomplete)
    else:
        outcome, reason = Outcome.NO_THREAT.value, "No deterministic threat rule was met and every applicable check completed."
    return {**wire, "rules": rules, "coverageGaps": gaps, "incompleteChecks": incomplete, "outcome": outcome, "reason": reason,
            "rejudgedUnder": VERSION}


async def _source_of(doc: dict) -> dict | None:
    """Who sent it and its subject: the record's own, else what its case recorded from the source."""
    if doc.get("source_metadata"):
        return doc["source_metadata"]
    if doc.get("investigation_case_id"):
        case = await db.investigation_cases.find_one({"owner_id": doc["device_id"], "case_id": doc["investigation_case_id"]},
                                                     {"_id": 0, "source_metadata": 1})
        if case and case.get("source_metadata"):
            return case["source_metadata"]
    return None


async def _patrol_records() -> int:
    changed = 0
    async for doc in db.patrol_events.find({"adapter_label": TRIAGE_ADAPTER, "triage_investigation": {"$ne": None}}, {"_id": 1, "device_id": 1,
                                           "category": 1, "investigation_case_id": 1, "triage_investigation": 1, "source_metadata": 1,
                                           "occurred_at": 1, "status": 1, "resolved_at": 1}):
        wire = rejudged(doc["triage_investigation"])
        update: dict = {"triage_investigation": wire, "source_metadata": await _source_of(doc), "updated_at": now_utc()}
        text = patrol_text(wire, doc.get("category") or "")
        if doc.get("investigation_case_id"):
            # The case's own result is what the screens show; only the words of this record change.
            text = {k: v for k, v in text.items() if k not in ("state", "status")}
        elif closed(doc):
            # A record already closed — handled or trusted by the person, or resolved — stays closed: a re-judge never
            # reopens it and never clears when it was closed.
            text = {k: v for k, v in text.items() if k != "status"}
        else:
            update["resolved_at"] = doc.get("occurred_at") if text["status"] == "resolved" else None
        update.update(text)
        await db.patrol_events.update_one({"_id": doc["_id"]}, {"$set": update})
        if wire is not doc["triage_investigation"]:
            await db.triage_investigations.update_one({"device_id": doc["device_id"], "investigation_id": wire.get("investigationId")},
                                                      {"$set": {"record": wire, "outcome": wire["outcome"], "updated_at": now_utc()}})
        changed += 1
    return changed


async def _threat_lists() -> int:
    """Listings stored before a page key always carried its path: the home page becomes "host/"."""
    from services.threat_feeds import BY_ID
    result = await db.threat_indicators.update_many(
        {"source": {"$in": list(BY_ID)}, "scope": "url", "whole_site": {"$ne": True}, "key": {"$not": {"$regex": "/"}}},
        [{"$set": {"key": {"$concat": ["$key", "/"]}}}])
    return result.modified_count


async def migrate() -> dict:
    if await db.app_migrations.find_one({"_id": MARKER}):
        return {"skipped": True}
    counts = {"patrol_records": await _patrol_records(), "listings_rekeyed": await _threat_lists(),
              "reputation_answers_cleared": (await db.reputation_cache.delete_many({})).deleted_count,
              "triage_results_cleared": (await db.triage_results.delete_many({"record_type": {"$ne": "decision"}})).deleted_count}
    await db.app_migrations.update_one({"_id": MARKER}, {"$set": {"ran_at": now_utc(), **counts}}, upsert=True)
    log.info("triage_rejudge %s", counts)
    return counts
