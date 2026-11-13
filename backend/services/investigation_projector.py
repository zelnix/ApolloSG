"""Idempotent, model-free projection of committed Higgins responses into Patrol.

One finding, one patrol record.  The projector takes a completed Magnum DI
investigation and ensures a single authoritative patrol event exists for it.

Indicators (indicator_host, claimed_brand, scenario) come exclusively from:
  1. The case's source_metadata captured at intake, or
  2. The ORIGINAL patrol event linked via client_submission_id.

We never extract metadata from Gemini's prose via regex.  If Apollo did not
record an indicator from actual intake/evidence, Patrol does not manufacture one.
"""
from __future__ import annotations

import re
import uuid

from pymongo import UpdateOne

from core.db import db, now_utc
from core.evidence_model import INVESTIGATION_ADAPTER, server_evidence_source
from core.models import PatrolEvent
from core.redaction import redact_investigation_secrets
from routers.push import push_owner_alert
from services import rulebook
from services.higgins import outcomes
from services.higgins import repository as repo
from services.patrol_status import handled

# The placeholder a case's record carries while its investigation runs: states only that Apollo is looking.
_RUNNING = {
    "headline": "Apollo is investigating this",
    "what_happened": "Higgins has started an investigation. Nothing has been established yet.",
    "why": ("The investigation is still running.",),
    "what_to_do": "Nothing to do right now. Higgins will tell you as soon as the investigation finishes.",
}


# Gate → patrol category. Every gate Apollo can open must map to a category the patrol record
# accepts; an unmapped gate (e.g. "vision") previously failed validation and the case never reached
# the Threats screen at all.
GATE_CATEGORY: dict[str, str] = {
    "text": "message", "message": "message", "vision": "message", "screenshot": "message",
    "email": "email", "call": "call", "app": "app", "file": "file", "account": "account",
    "device": "device", "network": "connection", "connection": "connection",
    "link": "link", "site": "website", "website": "website", "family": "family",
}


def patrol_category(gate: str | None) -> str:
    return GATE_CATEGORY.get(gate or "", "message")


def _dog_state(response) -> str:
    if getattr(response, "technical_failure", False):
        return "resting"  # a failed safety check established nothing either way — never "growling"
    if response.assessment == "no_concern_found_within_scope" and response.attention == "none":
        return "resting"
    if response.attention in ("urgent", "action_needed"):
        return "barking"
    return "growling"


#: What an investigation that couldn't decide either way says to do (frontend luddish/present.ts INCONCLUSIVE_TODO).
NOT_FULLY_CHECKED_TODO = "Nothing found to act on. This isn't confirmation that it's safe."
#: What a failed reputation check says to do — distinct from NOT_FULLY_CHECKED_TODO: nothing was found
#: *because the check itself never answered*, not because the evidence was weighed and came up empty.
TECHNICAL_FAILURE_TODO = "Apollo couldn't finish this investigation. Try again, or check back shortly."
_RANK = {"resting": 0, "sniffing": 1, "ears_up": 2, "growling": 3, "barking": 4, "biting": 5}


def inconclusive(response) -> bool:
    """The investigation couldn't decide either way and left no concrete actionable concern: no urgent or
    action-needed attention, and no decision its briefing (one that passed its Fidelity Check) or Magnum DI's pending
    question asks the person to make. Mirror of frontend caseBriefing.caseResult notFullyChecked.

    A failed reputation check (technical_failure) counts too: Apollo never reached a Finding to weigh."""
    b = response.briefing if response.briefing is not None and response.briefing.fidelity.status == "PASS" else None
    owed = (b.user_action_required and (b.action_reason or "").strip()) if b is not None else (
        response.completion == "waiting_user" and response.question is not None and (response.question.reason_needed or "").strip())
    if owed:
        return False
    if getattr(response, "technical_failure", False):
        return response.attention in ("none", "review")
    return response.outcome in ("unlikely_scam", "unable_to_determine") and response.attention in ("none", "review")


def established_threat(event: dict | None) -> bool:
    """A threat established apart from the investigation, which an inconclusive answer never lowers: a verified block,
    or a threat list naming the item's link (LINK-01)."""
    if not event:
        return False
    return bool(event.get("verified_block")) or "LINK-01" in ((event.get("triage_investigation") or {}).get("rulesMet") or [])


def _first_sentence(text: str) -> str:
    """A headline: the overview's first sentence, whole."""
    clean = " ".join((text or "").split())
    return (re.split(r"(?<=[.!?])\s", clean) or [clean])[0]


async def _resolve_intake_metadata(case: dict) -> dict:
    """Resolve indicator metadata from real intake data — NOT from Gemini's prose.

    Priority:
      1. case.source_metadata  (set at investigation creation from the original submission)
      2. The original patrol event (linked via client_submission_id)
      3. Null — don't guess.
    """
    meta: dict = {"indicator_host": None, "claimed_brand": None, "scenario": None}

    # 1. Case-level source_metadata (captured at intake)
    source = case.get("source_metadata") or {}
    if source.get("indicator_host"):
        meta["indicator_host"] = source["indicator_host"]
    if source.get("claimed_brand"):
        meta["claimed_brand"] = source["claimed_brand"]
    if source.get("scenario"):
        meta["scenario"] = source["scenario"]

    # 2. Fall back to the original patrol event that triggered this investigation
    sub_id = case.get("client_submission_id")
    if sub_id and not meta["indicator_host"]:
        original = await db.patrol_events.find_one(
            {"event_id": sub_id, "deleted_at": None},
            {"_id": 0, "indicator_host": 1, "claimed_brand": 1, "scenario": 1},
        )
        if original:
            meta["indicator_host"] = meta["indicator_host"] or original.get("indicator_host")
            meta["claimed_brand"] = meta["claimed_brand"] or original.get("claimed_brand")
            meta["scenario"] = meta["scenario"] or original.get("scenario")

    return meta


_UNPROJECTED = {"deleted": False, "response_revision": {"$gt": 0}, "$expr": {"$gt": ["$response_revision", {"$ifNull": ["$patrol_projected_revision", 0]}]}}
_CASE_FIELDS = {"_id": 0, "owner_id": 1, "case_id": 1, "gates": 1, "status": 1, "response_revision": 1, "accepted_commits": 1,
                "created_at": 1, "updated_at": 1, "client_submission_id": 1, "source_metadata": 1}


async def project_committed_cases(limit: int = 100) -> int:
    rows = await db.investigation_cases.find(_UNPROJECTED, _CASE_FIELDS).limit(limit).to_list(limit)
    return await _project(rows)


async def project_case_now(owner: str, case_id: str) -> int:
    """Project one case straight away. Called just before the server purges a case the device has committed:
    TC Hawkeye often answers in a couple of seconds, so the periodic projection could find the case already gone,
    leaving its Threats record on "Apollo is investigating this" and no history entry."""
    rows = await db.investigation_cases.find({**_UNPROJECTED, "owner_id": owner, "case_id": case_id}, _CASE_FIELDS).to_list(1)
    return await _project(rows)


async def _project(rows: list[dict]) -> int:
    projected = 0
    for case in rows:
        turns = await repo.accepted_turns(case["owner_id"], case)
        if not turns:
            continue
        latest = max(turns, key=lambda turn: turn.committed_at)
        response = latest.response
        fields = {"_id": 0, "event_id": 1, "state": 1, "status": 1, "resolved_at": 1, "verified_block": 1, "triage_investigation": 1,
                  "why": 1, "what_to_do": 1}
        existing = await db.patrol_events.find_one({"device_id": case["owner_id"], "investigation_case_id": case["case_id"], "deleted_at": None}, fields)
        if not existing and case.get("client_submission_id"):
            # One record per check: the device filed its own patrol event for this material before
            # (or just after) the case opened. Update THAT event rather than filing a server twin.
            existing = await db.patrol_events.find_one(
                {"device_id": case["owner_id"], "event_id": case["client_submission_id"], "deleted_at": None}, fields)
        # An investigation that couldn't decide, with no concrete actionable concern left, is not fully checked: no
        # warning and no alert. A threat established apart from it (a verified block, a listed link) is never lowered.
        not_fully_checked = inconclusive(response) and not established_threat(existing)
        state = "resting" if not_fully_checked else _dog_state(response)
        kept_raised = established_threat(existing) and _RANK.get(existing.get("state"), 0) > _RANK[state]
        if kept_raised:
            state = existing["state"]
        # Not synced yet (TC Hawkeye often answers before the device's copy of its record reaches the server):
        # file under the device's own event id, so when that copy arrives it is the same record, never a twin.
        event_id = (existing["event_id"] if existing else case.get("client_submission_id")
                    or str(uuid.uuid5(uuid.NAMESPACE_URL, f"apollo-patrol:{case['owner_id']}:{case['case_id']}")))
        category = patrol_category((case.get("gates") or ["text"])[0])
        findings = [redact_investigation_secrets(finding.text) for finding in response.findings[:6]]
        action = response.actions[0].instruction if response.actions else "Review the investigation details in Patrol."
        overview = redact_investigation_secrets(response.overview)
        briefing = response.briefing if response.briefing is not None and response.briefing.fidelity.status == "PASS" else None
        headline = redact_investigation_secrets(briefing.headline) if briefing else _first_sentence(overview)
        if not_fully_checked:
            # Kept in history, with what couldn't be established, and never called safe.
            findings = [redact_investigation_secrets(u) for u in response.uncertainties] or findings
            action = TECHNICAL_FAILURE_TODO if getattr(response, "technical_failure", False) else NOT_FULLY_CHECKED_TODO
        elif kept_raised:
            # The threat established apart from the investigation is what the record is about: its own reasons and,
            # when the investigation proposed no step, its own step.
            findings = findings or list(existing.get("why") or [])
            if not response.actions:
                action = existing.get("what_to_do") or _CONCERN_TODO

        # Resolve indicators from actual intake data — never from Gemini's prose
        indicators = await _resolve_intake_metadata(case)

        history_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"apollo-history:{case['owner_id']}:{case['case_id']}"))
        await db.higgins_investigation_history.update_one(
            {"owner_id": case["owner_id"], "history_id": history_id},
            {"$set": {"owner_id": case["owner_id"], "history_id": history_id, "case_id": case["case_id"], "case_start": case["created_at"],
                      "last_update": latest.committed_at, "status": "completed" if case.get("status") == "complete" else case.get("status", "active"),
                      "gates": case.get("gates", []), "attention": response.attention, "conclusion": overview, "deleted": False,
                      "updated_at": now_utc()}, "$setOnInsert": {"created_at": now_utc()}}, upsert=True,
        )
        document = {
            "event_id": event_id, "device_id": case["owner_id"], "category": category, "state": state,
            "status": "resolved" if state == "resting" else "active", "headline": headline,
            # What it found, never how it was checked: the scope is not a reason, and Home and alerts name the first reason.
            "what_happened": overview, "why": findings,
            "what_to_do": redact_investigation_secrets(action),
            "investigation_outcome": response.outcome,
            # Real intake metadata only — never manufactured from Gemini's prose
            "indicator_host": indicators["indicator_host"],
            "indicator_digest": None,
            "local_indicator": None,
            "verified_block": False,
            "adapter_label": INVESTIGATION_ADAPTER,
            "occurred_at": latest.committed_at, "resolved_at": latest.committed_at if state == "resting" else None,
            "trust_allowed": False,
            "claimed_brand": indicators["claimed_brand"],
            "scenario": indicators["scenario"],
            "scent_id": None,
            "background": True, "investigation_case_id": case["case_id"],
            # The investigation has answered: this case is no longer "being investigated".
            "investigation_completed_at": latest.committed_at,
            "client_submission_id": case.get("client_submission_id"),
            # The record now holds the investigation's own result, worked from a privacy-protected copy.
            "evidence_representation": "privacy_protected_copy",
            # Actual recorded source metadata from intake — NOT Gemini-inferred
            "source_metadata": case.get("source_metadata"),
            # Pipeline initiator for telemetry
            "initiator": case.get("initiator", "unknown"),
            "deleted_at": None, "created_at": now_utc(), "updated_at": now_utc(),
        }
        created_at = document.pop("created_at")
        if existing and handled(existing):
            # The person handled or trusted this record: an investigation's answer never reopens it.
            document.pop("status")
            document.pop("resolved_at")
        # Where the evidence came from, and where it was processed, are written only when the server files the record
        # itself: an investigation never changes what this device recorded (server processing is not a source).
        on_insert = {"created_at": created_at, "evidence_provenance": server_evidence_source(case.get("source_metadata")),
                     "processing_source": "apollosg_servers"}
        upsert = await db.patrol_events.update_one({"device_id": case["owner_id"], "event_id": event_id}, {"$set": document, "$setOnInsert": on_insert}, upsert=True)
        if upsert.upserted_id and state != "resting":
            await push_owner_alert(PatrolEvent.from_mongo({**document, **on_insert}), briefing=briefing, source=case.get("source_metadata"))
        changed = await db.investigation_cases.update_one(
            {"owner_id": case["owner_id"], "case_id": case["case_id"], "response_revision": case["response_revision"],
             "$or": [{"patrol_projected_revision": {"$exists": False}}, {"patrol_projected_revision": {"$lt": case["response_revision"]}}]},
            {"$set": {"patrol_projected_revision": case["response_revision"], "patrol_projected_at": now_utc()}},
        )
        projected += changed.modified_count
    return projected


async def project_open_cases(limit: int = 100) -> int:
    """Give every investigation a patrol record as soon as it starts.

    An investigation started from Ask Higgins is a case the person should be able to find, follow and
    come back to — not something that only appears once Magnum DI has answered. This writes the same
    deterministic patrol event the committed projection later updates (same event_id), so there is one
    record per case throughout, never two.

    The placeholder states only what is true: Apollo is investigating. It carries no findings, no
    assessment and no conclusion — those exist only once a response has been validated and committed.
    """
    query = {"deleted": False, "$or": [{"response_revision": {"$exists": False}}, {"response_revision": 0}]}
    rows = await db.investigation_cases.find(query, {"_id": 0, "owner_id": 1, "case_id": 1, "gates": 1, "status": 1,
                                                 "created_at": 1, "updated_at": 1, "client_submission_id": 1,
                                                 "source_metadata": 1, "initiator": 1}).limit(limit).to_list(limit)
    projected = 0
    for case in rows:
        projected += 1 if await project_case_started(case) else 0
    return projected


async def project_case_started(case: dict) -> bool:
    """Write the "investigating" patrol record for one case. Idempotent; safe to call at creation."""
    # An investigation that began from an existing patrol event already has its record.
    if case.get("client_submission_id"):
        return False
    if case.get("response_revision"):
        return False
    existing = await db.patrol_events.find_one(
        {"device_id": case["owner_id"], "investigation_case_id": case["case_id"], "deleted_at": None},
        {"_id": 0, "event_id": 1})
    if existing:
        return False
    category = patrol_category((case.get("gates") or ["text"])[0])
    indicators = await _resolve_intake_metadata(case)
    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"apollo-patrol:{case['owner_id']}:{case['case_id']}"))
    document = {
        "event_id": event_id, "device_id": case["owner_id"], "category": category,
        # "sniffing": Apollo is looking. Not a finding, not an assessment.
        "state": "sniffing", "status": "active",
        "headline": _RUNNING["headline"], "what_happened": _RUNNING["what_happened"],
        "why": list(_RUNNING["why"]), "what_to_do": _RUNNING["what_to_do"],
        "indicator_host": indicators["indicator_host"], "indicator_digest": None, "local_indicator": None,
        "verified_block": False, "adapter_label": INVESTIGATION_ADAPTER,
        "occurred_at": case.get("created_at") or now_utc(), "resolved_at": None, "trust_allowed": False,
        "claimed_brand": indicators["claimed_brand"], "scenario": indicators["scenario"], "scent_id": None,
        "background": True, "investigation_case_id": case["case_id"], "client_submission_id": None,
        "investigation_completed_at": None,
        "evidence_representation": "privacy_protected_copy", "source_metadata": case.get("source_metadata"),
        "initiator": case.get("initiator", "unknown"), "deleted_at": None, "updated_at": now_utc(),
    }
    on_insert = {"created_at": now_utc(), "evidence_provenance": server_evidence_source(case.get("source_metadata")),
                 "processing_source": "apollosg_servers"}
    await db.patrol_events.update_one(
        {"device_id": case["owner_id"], "event_id": event_id},
        {"$set": document, "$setOnInsert": on_insert}, upsert=True)
    return True


# ── An investigation that ended without its result reaching Patrol ─────────────────────────────────
_ENDED = {"expired", "deleted", "cancelled", "failed"}
_OUTCOME_STATE = {
    # Current four Findings
    "not_scam": "resting", "likely_scam": "barking", "scam": "barking", "unlikely_scam": "resting",
    # Legacy codes (backward compat)
    "no_scam_indicators": "resting", "concerning": "growling", "confirmed_threat": "barking", "unable_to_determine": "resting",
}
_OUTCOME_ATTENTION = {
    # Current four Findings
    "not_scam": "none", "likely_scam": "action_needed", "scam": "urgent", "unlikely_scam": "review",
    # Legacy codes
    "no_scam_indicators": "none", "concerning": "review", "confirmed_threat": "urgent", "unable_to_determine": "review",
}
_OUTCOME_TODO = {
    "not_scam": "Nothing more to do. If anything about it feels off, contact the person or organisation using details you already have.",
    "no_scam_indicators": "Nothing more to do. If anything about it feels off, contact the person or organisation using details you already have.",
    "unlikely_scam": NOT_FULLY_CHECKED_TODO,
    "unable_to_determine": NOT_FULLY_CHECKED_TODO,
}
_CONCERN_TODO = "Don't reply, call back or follow its instructions. Contact the organisation using details you already have."
_AGAIN = "Run the check again if you still need an answer."


def ended_view(case: dict | None) -> dict:
    """What a record says once its investigation has ended — from the case's own record only, never a verdict it
    doesn't hold: the outcome its routing recorded and the rule that settled it; else that it finished but its
    result isn't kept; else that it ended without a result."""
    routing = (case or {}).get("routing") or {}
    outcome = routing.get("outcome") or (routing.get("tc_hawkeye") or routing.get("tc_flyby") or {}).get("outcome")
    headline = outcomes.label(outcome)
    if headline:
        # Normalize legacy codes to current codes for state/attention mapping
        display_outcome = outcomes.normalize(outcome) or outcome
        reason = rulebook.settled_reason(routing)
        return {"outcome": outcome, "headline": headline,
                "what_happened": reason["sentence"] if reason else f"{headline}.", "why": [],
                "what_to_do": _OUTCOME_TODO.get(outcome, _OUTCOME_TODO.get(display_outcome, _CONCERN_TODO)),
                "state": _OUTCOME_STATE.get(outcome, _OUTCOME_STATE.get(display_outcome, "resting")),
                "status": "resolved" if _OUTCOME_STATE.get(outcome, _OUTCOME_STATE.get(display_outcome, "resting")) == "resting" else "active"}
    if not case:
        said = "This investigation is no longer on Apollo's servers, and its result isn't part of this record."
        return {"outcome": None, "headline": "Investigation no longer available", "what_happened": said, "why": [], "what_to_do": _AGAIN}
    if (case.get("response_revision") or 0) > 0:
        return {"outcome": None, "headline": "Investigation finished", "why": [], "what_to_do": _AGAIN,
                "what_happened": "This investigation finished, but its result wasn't added to this record before Apollo's servers removed their copy."}
    how = {"cancelled": "was cancelled", "deleted": "was deleted", "failed": "couldn't finish"}.get(case.get("status"), "expired")
    return {"outcome": None, "headline": "Investigation ended without a result", "why": [], "what_to_do": _AGAIN,
            "what_happened": f"This investigation {how} before it reached a result, so nothing was established."}


async def project_ended_cases(limit: int = 300) -> int:
    """Every Patrol record still waiting on an investigation that has ended gets its final state.

    A result is projected while its case is live (above). A record whose case ended without that — purged before
    the projection ran, expired before it answered, cancelled or deleted — would otherwise say "Apollo is
    investigating this" forever. A device that holds the full result still applies it over this."""
    events = await db.patrol_events.find(
        {"deleted_at": None, "investigation_case_id": {"$ne": None}, "investigation_completed_at": None, "occurred_at": {"$type": "date"}},
        {"_id": 0, "event_id": 1, "device_id": 1, "investigation_case_id": 1, "state": 1, "status": 1, "headline": 1,
         "what_happened": 1, "why": 1, "what_to_do": 1, "verified_block": 1, "triage_investigation": 1}).sort("occurred_at", 1).limit(limit).to_list(limit)
    if not events:
        return 0
    cases = {c["case_id"]: c for c in await db.investigation_cases.find(
        {"case_id": {"$in": list({e["investigation_case_id"] for e in events})}},
        {"_id": 0, "case_id": 1, "owner_id": 1, "status": 1, "response_revision": 1, "routing": 1, "gates": 1,
         "created_at": 1, "updated_at": 1}).to_list(None)}
    now = now_utc()
    event_ops, history_ops = [], []
    for event in events:
        case = cases.get(event["investigation_case_id"])
        if case and case.get("status") not in _ENDED:
            continue  # still running: its result is projected when it answers
        view = ended_view(case)
        ended_at = (case or {}).get("updated_at") or now
        patch: dict = {"investigation_completed_at": ended_at, "updated_at": now}
        if view["outcome"]:
            patch.update({k: view[k] for k in ("headline", "what_happened", "why", "what_to_do", "state", "status")})
            patch["investigation_outcome"] = view["outcome"]
            if established_threat(event) and _RANK.get(event.get("state"), 0) > _RANK[view["state"]]:
                # An answer that doesn't settle it never lowers a threat established apart from it.
                patch.update(state=event["state"], status="active", what_to_do=_CONCERN_TODO)
            if handled(event):
                # The person handled or trusted this record: it is never reopened.
                patch.pop("status")
            elif patch["status"] == "resolved":
                patch["resolved_at"] = ended_at
            history_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"apollo-history:{case['owner_id']}:{case['case_id']}"))
            history_ops.append(UpdateOne({"owner_id": case["owner_id"], "history_id": history_id}, {"$setOnInsert": {
                "owner_id": case["owner_id"], "history_id": history_id, "case_id": case["case_id"], "case_start": case.get("created_at") or ended_at,
                "last_update": ended_at, "status": "completed", "gates": case.get("gates", []), "attention": _OUTCOME_ATTENTION[view["outcome"]],
                "conclusion": view["what_happened"], "deleted": False, "created_at": now, "updated_at": now}}, upsert=True))
        else:
            # Only the "still running" wording is replaced; anything else the record says stays.
            patch.update({k: view[k] for k in ("headline", "what_happened", "what_to_do") if event.get(k) == _RUNNING[k]})
            if event.get("why") == list(_RUNNING["why"]):
                patch["why"] = view["why"]
            if event.get("state") == "sniffing":
                patch["state"] = "ears_up"
        event_ops.append(UpdateOne({"event_id": event["event_id"], "device_id": event["device_id"], "investigation_completed_at": None}, {"$set": patch}))
    if event_ops:
        await db.patrol_events.bulk_write(event_ops, ordered=False)
    if history_ops:
        await db.higgins_investigation_history.bulk_write(history_ops, ordered=False)
    return len(event_ops)
