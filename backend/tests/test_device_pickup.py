"""Owner's rules (2026-11-01): the 24-hour rule applies to the server's copies only, and the server keeps its copy until
the phone confirms it saved and checked its own complete copy — if the phone is offline, the server waits.

Run: cd /app/backend && python -m pytest tests/test_device_pickup.py -q
"""
from __future__ import annotations

import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from core.db import db, now_utc
from routers import investigations as inv_router
from routers import patrol as patrol_router
from services import device_pickup, held_copies, maintenance
from services.higgins import evidence as ev
from services.higgins import repository as repo
from services.higgins.contracts import HigginsResponse, ProviderResult, TurnCommit
from tests.test_owner_fixes_proof import _device_record

SENDER, SUBJECT, RECEIVED = "AusPost <track@auspost-help.co>", "Your parcel is held", now_utc() - timedelta(hours=30)
TEXT = "Your parcel is held. Pay the $2.99 fee at https://auspost-redeliver.top/pay to release it."


class _Request:
    """The two things the endpoints read: the device and the JSON body."""
    def __init__(self, owner: str, body: dict | None = None):
        self.state = SimpleNamespace(device={"device_id": owner})
        self._body = body

    async def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


def _json(response) -> dict:
    return json.loads(response.body)


async def _finished_email_case(owner: str) -> dict:
    """A finished email investigation holding the submitted text and the identifiers recorded at intake — committed
    exactly as the pipeline leaves it (the same steps as test_owner_fixes_proof._committed)."""
    case = await repo.create_case(owner, "email", None)
    await db.investigation_cases.update_one({"case_id": case["case_id"]}, {"$set": {"source_metadata": {
        "type": "text", "sender": SENDER, "subject": SUBJECT, "received_at": RECEIVED, "preview": TEXT, "submitted_at": RECEIVED}}})
    case = await repo.get_case(owner, case["case_id"])
    await ev.ingest_text(owner, case, f"client-{uuid.uuid4().hex[:6]}", TEXT, origin="user_submission", label="checked message")
    case = await repo.get_case(owner, case["case_id"])
    turn_id = str(uuid.uuid4())
    job = await repo.create_job(owner, case, turn_id, repo.digest("key"), repo.digest("payload"), "turn", {"message": "q", "turnId": turn_id})
    await repo.cas(owner, case["case_id"], {"revision": case["revision"]}, {"$set": {"active_job_id": job["job_id"], "active_turn_id": turn_id}})
    job = await repo.acquire_lease(owner, job["job_id"])
    case = await repo.cas(owner, case["case_id"], {"active_job_id": job["job_id"]}, {"$set": {"lease_fence": job["fence"]}}, bump=False)
    response = HigginsResponse(revision=1, overview="This email is likely a scam.", explanationMarkdown="x", assessment="concern_found", outcome="likely_scam",
                               attention="review", findings=[], uncertainties=[], scope="submitted email", sourceIds=[], remainingEvidenceIds=[],
                               actions=[], completion="complete")
    commit = TurnCommit(turnId=turn_id, caseId=case["case_id"], inputRevision=1, committedRevision=1, question="q", response=response,
                        provider=ProviderResult(model="pinned-test-model", finishReason="STOP", providerComplete=True), committedAt=now_utc())
    commit_id = await repo.stage_turn(owner, commit, job, repo.utc(case["expires_at"]))
    assert await repo.accept_turn(owner, case, job, commit, commit_id, "complete", "none", None)
    return case


async def _cleanup(owner: str) -> None:
    for name in ("investigation_cases", "investigation_evidence", "investigation_content_chunks", "investigation_jobs",
                 "investigation_turn_commits", "investigation_events", device_pickup.COLLECTION, "investigation_cleanup"):
        await db[name].delete_many({"owner_id": owner})
    await db.patrol_events.delete_many({"device_id": owner})


async def test_a_finished_investigation_keeps_the_phones_copy_with_its_text_and_headers():
    owner = f"pickup-{uuid.uuid4().hex[:8]}"
    try:
        case = await _finished_email_case(owner)
        held = await device_pickup.get(owner, case["case_id"])
        assert held, "the copy is kept the moment the investigation finishes"
        assert [o["body"] for o in held["originals"]] == [TEXT]
        assert held["source"]["sender"] == SENDER and held["source"]["subject"] == SUBJECT
        assert held["source"]["received_at"].startswith(RECEIVED.isoformat()[:19]), "the received time as recorded, in ISO"
        assert "preview" not in held["source"], "only identifiers travel as headers; the text travels as the original"
        assert held["case"]["response"]["outcome"] == "likely_scam"
        served = _json(await inv_router.device_pickup_copy(case["case_id"], _Request(owner)))
        assert served["held"] is True and served["originals"][0]["body"] == TEXT
    finally:
        await _cleanup(owner)


async def test_no_clock_removes_the_phones_copy_while_the_phone_is_offline():
    owner = f"pickup-{uuid.uuid4().hex[:8]}"
    try:
        case = await _finished_email_case(owner)
        # Days pass: the 15-minute working copy expires, the 24 hours run out, every maintenance step runs.
        past = now_utc() - timedelta(days=3)
        await db.investigation_cases.update_one({"case_id": case["case_id"]}, {"$set": {"expires_at": past, "content_delete_by": past, "created_at": past}})
        await repo.sweep()
        await held_copies.sweep(now_utc())
        gone = await db.investigation_cases.find_one({"case_id": case["case_id"]}, {"_id": 0})
        assert gone["deleted"] is True, "the server's working copy still goes on its own clock"
        assert gone["source_metadata"].get("preview") == TEXT, "the case's copy of the text waits for the phone"
        served = _json(await inv_router.device_pickup_copy(case["case_id"], _Request(owner)))
        assert served["held"] is True and served["originals"][0]["body"] == TEXT and served["source"]["subject"] == SUBJECT, \
            "the phone's copy is still there when it comes back online"
    finally:
        await _cleanup(owner)


async def test_the_server_deletes_only_after_the_phone_confirms_a_complete_copy():
    owner = f"pickup-{uuid.uuid4().hex[:8]}"
    try:
        case = await _finished_email_case(owner)
        case_id = case["case_id"]
        with pytest.raises(HTTPException) as refused:
            await inv_router.confirm_commit(case_id, _Request(owner, {"saved": {"text": True, "link": False, "result": True, "headers": ["From"]}}))
        assert refused.value.status_code == 409
        assert refused.value.detail["error"]["missingEvidenceIds"] == ["Subject", "Received"], "a copy missing headers is not complete"
        assert await device_pickup.get(owner, case_id), "nothing was deleted"
        saved = {"text": True, "link": False, "result": True, "headers": ["From", "Subject", "Received", "Mailbox"]}
        done = _json(await inv_router.confirm_commit(case_id, _Request(owner, {"saved": saved})))
        assert done["purged"] is True and done["removedAt"]
        assert await device_pickup.get(owner, case_id) is None, "confirmed: the server's copy for the phone is released"
        row = await db.investigation_cases.find_one({"case_id": case_id}, {"_id": 0})
        assert row["device_saved_at"], "the 24-hour rule may now run for the case's copy of the text"
        again = _json(await inv_router.confirm_commit(case_id, _Request(owner, {"saved": saved})))
        assert again["status"] == "already_clean", "idempotent"
        with pytest.raises(HTTPException) as bad:
            await inv_router.confirm_commit(case_id, _Request(owner, {"saved": {"text": "yes"}}))
        assert bad.value.status_code == 422
    finally:
        await _cleanup(owner)


async def test_deleting_the_check_releases_the_phones_copy():
    owner = f"pickup-{uuid.uuid4().hex[:8]}"
    try:
        case = await _finished_email_case(owner)
        await inv_router.delete_case(case["case_id"], _Request(owner))
        assert await device_pickup.get(owner, case["case_id"]) is None
    finally:
        await _cleanup(owner)


async def test_a_threats_records_text_waits_for_the_phone_then_goes_at_24_hours():
    owner, now = f"pickup-{uuid.uuid4().hex[:8]}", now_utc()
    old = now - timedelta(hours=25)
    meta = {"sender": "+61 448 221 905", "preview": "Your parcel is waiting, pay the fee now", "submitted_at": old}
    await db.patrol_events.insert_many([_device_record(owner, "offline", source_metadata=dict(meta)),
                                        _device_record(owner, "saved", source_metadata=dict(meta))])
    try:
        await held_copies.sweep(now)
        rows = {r["event_id"]: r["source_metadata"] for r in await db.patrol_events.find({"device_id": owner}, {"_id": 0}).to_list(5)}
        assert rows["offline"]["preview"] and rows["saved"]["preview"], "nothing goes before the phone confirms"
        out = await patrol_router.saved_on_device(patrol_router.SavedOnDeviceIn(eventIds=["saved", "unknown"]), _Request(owner))
        assert out == {"confirmed": 1}
        await held_copies.sweep(now)
        rows = {r["event_id"]: r["source_metadata"] for r in await db.patrol_events.find({"device_id": owner}, {"_id": 0}).to_list(5)}
        assert "preview" not in rows["saved"] and rows["saved"]["sender"] == "+61 448 221 905", "confirmed and past 24 hours: the text goes, identifiers stay"
        assert rows["offline"]["preview"], "the phone that hasn't confirmed keeps the server's copy waiting"
    finally:
        await db.patrol_events.delete_many({"device_id": owner})


def test_the_held_copy_sweep_still_runs_every_cycle_and_needs_the_phones_confirmation():
    assert ("held_copies_24h", held_copies.sweep) in maintenance.maintenance_steps()
    assert held_copies.due_filter("occurred_at", now_utc())["device_saved_at"] == {"$type": "date"}
    assert ("investigation_device_pickups", ["owner_id"]) in __import__("services.account_deletion", fromlist=["CATEGORIES"]).CATEGORIES["investigations"]["collections"]
