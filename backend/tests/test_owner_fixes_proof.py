"""Proof for the owner's fixes (2026-11): an investigation that can't decide is never a warning or an alert and never
lowers another threat; a closed record is never reopened; ApolloSG's held copies go after 24 hours; Safe Browsing's
answer counts only for the exact address.

Run: cd /app/backend && python -m pytest tests/test_owner_fixes_proof.py -q
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from core.db import db, now_utc
from core.evidence_model import TRIAGE_ADAPTER
from services import correlation, held_copies, investigation_projector as projector, maintenance
from services.higgins import repository as repo
from services.higgins.contracts import HigginsResponse, ProviderResult, TurnCommit
from services.triage.rejudge import _patrol_records


async def _committed(owner: str, *, outcome: str, assessment: str, attention: str, submission: str | None = None) -> dict:
    """A case whose investigation answer is committed, exactly as the pipeline leaves it for the projector."""
    case = await repo.create_case(owner, "text", None, client_submission_id=submission)
    turn_id = str(uuid.uuid4())
    job = await repo.create_job(owner, case, turn_id, repo.digest("key"), repo.digest("payload"), "turn", {"message": "q", "turnId": turn_id})
    await repo.cas(owner, case["case_id"], {"revision": 0}, {"$set": {"active_job_id": job["job_id"], "active_turn_id": turn_id}})
    job = await repo.acquire_lease(owner, job["job_id"])
    case = await repo.cas(owner, case["case_id"], {"active_job_id": job["job_id"]}, {"$set": {"lease_fence": job["fence"]}}, bump=False)
    response = HigginsResponse(revision=1, overview="The checks couldn't settle whether this text is genuine.", explanationMarkdown="x",
                               assessment=assessment, outcome=outcome, attention=attention, findings=[],
                               uncertainties=["Whether the sender's number belongs to the company couldn't be verified."],
                               scope="submitted message", sourceIds=[], remainingEvidenceIds=[], actions=[], completion="complete")
    commit = TurnCommit(turnId=turn_id, caseId=case["case_id"], inputRevision=1, committedRevision=1, question="q", response=response,
                        provider=ProviderResult(model="pinned-test-model", finishReason="STOP", providerComplete=True), committedAt=now_utc())
    commit_id = await repo.stage_turn(owner, commit, job, repo.utc(case["expires_at"]))
    assert await repo.accept_turn(owner, case, job, commit, commit_id, "complete", "none", None)
    return case


async def _project(owner: str, case: dict) -> tuple[dict, AsyncMock]:
    push = AsyncMock()
    with patch.object(projector, "push_owner_alert", push):
        assert await projector.project_case_now(owner, case["case_id"]) == 1
    event = await db.patrol_events.find_one({"device_id": owner, "investigation_case_id": case["case_id"]}, {"_id": 0})
    return event, push


def _device_record(owner: str, event_id: str, **over) -> dict:
    now = now_utc()
    return {"event_id": event_id, "device_id": owner, "category": "message", "state": "growling", "status": "active",
            "headline": "x", "what_happened": "x", "why": [], "what_to_do": "x", "indicator_host": None, "indicator_digest": None,
            "verified_block": False, "adapter_label": "Apollo", "occurred_at": now, "resolved_at": None, "deleted_at": None,
            "investigation_case_id": None, "created_at": now, "updated_at": now, **over}


# ── Fix 3 / requirement 1(a): an inconclusive investigation is not a warning, and never suppresses another threat ──

async def test_an_inconclusive_investigation_is_filed_as_not_fully_checked_with_no_alert():
    owner = f"proof-{uuid.uuid4().hex[:8]}"
    event, push = await _project(owner, await _committed(owner, outcome="unable_to_determine", assessment="uncertain", attention="review"))
    assert event["state"] == "resting" and event["status"] == "resolved", "never Growling or Barking"
    assert event["investigation_outcome"] == "unable_to_determine"
    assert event["what_to_do"] == projector.NOT_FULLY_CHECKED_TODO == "Nothing found to act on. This isn't confirmation that it's safe."
    assert event["why"] == ["Whether the sender's number belongs to the company couldn't be verified."], "what couldn't be established is kept"
    push.assert_not_called()


async def test_a_concerning_investigation_still_warns_and_alerts():
    owner = f"proof-{uuid.uuid4().hex[:8]}"
    event, push = await _project(owner, await _committed(owner, outcome="concerning", assessment="concern_found", attention="review"))
    assert event["state"] == "growling" and event["status"] == "active"
    push.assert_awaited_once()


async def test_an_inconclusive_investigation_never_lowers_a_threat_list_match():
    owner, submission = f"proof-{uuid.uuid4().hex[:8]}", f"sub-{uuid.uuid4().hex[:12]}"
    await db.patrol_events.insert_one(_device_record(owner, submission, state="barking", why=["PhishTank lists this exact address."],
                                                     what_to_do="Don't open the link.",
                                                     triage_investigation={"outcome": "POSSIBLE_THREAT_IDENTIFIED", "rulesMet": ["LINK-01"]}))
    case = await _committed(owner, outcome="unable_to_determine", assessment="uncertain", attention="review", submission=submission)
    event, _ = await _project(owner, case)
    assert event["event_id"] == submission, "one record per check"
    assert event["state"] == "barking" and event["status"] == "active", "the listed link keeps the case raised"
    assert event["why"] == ["PhishTank lists this exact address."] and event["what_to_do"] == "Don't open the link.", \
        "it keeps the reason it is raised, never how the investigation checked it"


async def test_a_record_never_gives_how_it_was_checked_as_its_reason():
    owner = f"proof-{uuid.uuid4().hex[:8]}"
    event, _ = await _project(owner, await _committed(owner, outcome="concerning", assessment="concern_found", attention="review"))
    assert event["why"] == [], "the scope ('submitted message') is not a finding"


def test_the_privacy_summary_of_an_undecided_investigation_never_says_nothing_unusual():
    from services.patrol_policy import SUMMARY_ADAPTER, refresh_summary
    shown = refresh_summary({"adapter_label": SUMMARY_ADAPTER, "category": "message", "state": "resting", "verified_block": False,
                             "investigation_outcome": "unable_to_determine"})
    assert shown["headline"] == "Apollo checked a text message but couldn\u2019t settle it"
    assert "nothing unusual" not in shown["headline"] + shown["what_happened"]
    assert shown["what_to_do"] == projector.NOT_FULLY_CHECKED_TODO
    plain = refresh_summary({"adapter_label": SUMMARY_ADAPTER, "category": "message", "state": "resting", "verified_block": False})
    assert plain["headline"] == "Apollo checked a text message and found nothing unusual"


def test_an_investigation_ended_without_deciding_is_not_fully_checked():
    view = projector.ended_view({"status": "expired", "routing": {"tc_flyby": {"outcome": "unable_to_determine"}}})
    assert view["outcome"] == "unable_to_determine"
    assert view["state"] == "resting" and view["status"] == "resolved", "never 'ears up' or active"
    assert view["what_to_do"] == projector.NOT_FULLY_CHECKED_TODO
    concern = projector.ended_view({"status": "expired", "routing": {"tc_flyby": {"outcome": "concerning"}}})
    assert concern["state"] == "growling" and concern["status"] == "active"


# ── Fix 6: nothing reopens a closed record ──

async def test_an_investigation_answer_never_reopens_a_record_the_person_handled():
    owner, submission = f"proof-{uuid.uuid4().hex[:8]}", f"sub-{uuid.uuid4().hex[:12]}"
    handled_at = now_utc() - timedelta(hours=1)
    await db.patrol_events.insert_one(_device_record(owner, submission, status="resolved", resolved_at=handled_at))
    case = await _committed(owner, outcome="concerning", assessment="concern_found", attention="review", submission=submission)
    event, push = await _project(owner, case)
    assert event["status"] == "resolved" and event["resolved_at"] is not None, "handled stays handled"
    push.assert_not_called()


async def test_a_rejudge_never_reopens_a_closed_triage_record():
    owner = f"proof-{uuid.uuid4().hex[:8]}"
    closed_at = now_utc() - timedelta(days=2)
    wire = {"outcome": "LIMITED_UNABLE_TO_DETERMINE", "rules": [], "incompleteChecks": [],
            "coverageGaps": [{"code": "INSUFFICIENT_EVIDENCE", "detail": "Not enough to decide."}]}
    open_wire = {**wire}
    await db.patrol_events.insert_many([
        _device_record(owner, f"closed-{uuid.uuid4().hex[:8]}", adapter_label=TRIAGE_ADAPTER, state="ears_up", status="resolved",
                       resolved_at=closed_at, triage_investigation=wire),
        _device_record(owner, f"open-{uuid.uuid4().hex[:8]}", adapter_label=TRIAGE_ADAPTER, state="ears_up", status="active",
                       triage_investigation=open_wire)])
    await _patrol_records()
    rows = {r["event_id"].split("-")[0]: r for r in await db.patrol_events.find({"device_id": owner}, {"_id": 0}).to_list(5)}
    try:
        assert rows["closed"]["status"] == "resolved", "a re-judge changes words, never reopens"
        assert abs((rows["closed"]["resolved_at"].replace(tzinfo=None) - closed_at.replace(tzinfo=None)).total_seconds()) < 1, "its closing time stays"
        assert rows["open"]["status"] == "active", "an open record is still filed as the rules say"
    finally:
        await db.patrol_events.delete_many({"device_id": owner})


# ── Requirement 2(a): ApolloSG's held copies are deleted 24 hours after they were made ──

async def test_held_copies_older_than_24_hours_are_deleted_and_identifiers_kept():
    owner, now = f"proof-{uuid.uuid4().hex[:8]}", now_utc()
    old, fresh = now - timedelta(hours=24, minutes=1), now - timedelta(hours=23)
    meta = lambda at: {"sender": "+61 448 221 905", "subject": "Parcel", "preview": "Your parcel is waiting, pay the fee now", "submitted_at": at}  # noqa: E731
    await db.patrol_events.insert_many([_device_record(owner, "held-old", source_metadata=meta(old)),
                                        _device_record(owner, "held-new", source_metadata=meta(fresh)),
                                        _device_record(owner, "held-notime", occurred_at=old, source_metadata={**meta(None), "submitted_at": None})])
    case_id = f"held-{uuid.uuid4().hex[:8]}"
    await db.investigation_cases.insert_one({"owner_id": owner, "case_id": case_id, "created_at": old, "deleted": True,
                                             "source_metadata": {"sender": "a@b.co", "preview": "text"}})
    try:
        await held_copies.sweep(now)
        rows = {r["event_id"]: r["source_metadata"] for r in await db.patrol_events.find({"device_id": owner}, {"_id": 0}).to_list(5)}
        assert "preview" not in rows["held-old"] and "preview" not in rows["held-notime"]
        assert rows["held-new"]["preview"] == "Your parcel is waiting, pay the fee now", "inside 24 hours it stays"
        assert rows["held-old"]["sender"] == "+61 448 221 905" and rows["held-old"]["subject"] == "Parcel", "identifiers are kept"
        case = await db.investigation_cases.find_one({"case_id": case_id}, {"_id": 0})
        assert "preview" not in case["source_metadata"] and case["source_metadata"]["sender"] == "a@b.co"
        again = await held_copies.sweep(now)
        assert await db.patrol_events.count_documents({"device_id": owner, "source_metadata.preview": {"$exists": True}}) == 1, "idempotent"
        assert set(again) == {"patrol_events", "investigation_cases"}
    finally:
        await db.patrol_events.delete_many({"device_id": owner})
        await db.investigation_cases.delete_one({"case_id": case_id})


def test_the_24_hour_sweep_runs_with_every_maintenance_cycle():
    assert held_copies.HELD_COPY_SECONDS == 24 * 3600
    assert ("held_copies_24h", held_copies.sweep) in maintenance.maintenance_steps()


# ── Fix 7: an answer for one address is never an answer for another ──

def test_safe_browsing_counts_only_for_the_exact_address():
    pg = {"safe_browsing": {"https://evil.example.com.attacker.net/login": {"verdict": "malicious", "threat_types": ["SOCIAL_ENGINEERING"]}}}
    assert correlation._safe_browsing(pg, "evil.example.com", ["https://evil.example.com/login"]) == [], \
        "an address that merely contains the website's name is a different address"
    pg["safe_browsing"]["https://evil.example.com/login"] = {"verdict": "malicious", "threat_types": ["SOCIAL_ENGINEERING"]}
    rows = correlation._safe_browsing(pg, "evil.example.com", ["https://evil.example.com/login"])
    assert len(rows) == 1 and rows[0]["status"] == "listed"
