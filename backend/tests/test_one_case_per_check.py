import uuid
import pytest
from core.db import db, now_utc
from services.higgins import repository as repo
from services.investigation_projector import project_case_started, project_committed_cases

pytestmark = pytest.mark.anyio


async def _device_event(owner: str, event_id: str) -> dict:
    """The patrol record a Gate check files on the device for its own check."""
    document = {
        "event_id": event_id, "device_id": owner, "category": "email", "state": "growling",
        "status": "active", "headline": "Email: claims to be CommBank",
        "what_happened": "Apollo found a lookalike sender domain.", "why": ["Lookalike domain"],
        "what_to_do": "Do not use the link.", "indicator_host": "commbank-alerts.co",
        "indicator_digest": None, "local_indicator": None, "verified_block": False,
        "adapter_label": "preview", "occurred_at": now_utc(), "resolved_at": None,
        "trust_allowed": False, "claimed_brand": "CommBank", "scenario": "E01",
        "evidence_provenance": "local_device", "deleted_at": None,
        "created_at": now_utc(), "updated_at": now_utc(),
    }
    await db.patrol_events.insert_one(dict(document))
    return document


async def test_case_named_by_the_device_never_gets_a_second_record():
    """One check, one record: a case that names the device's own patrol event must never cause a
    second, server-owned event for the same material — before OR after Magnum DI answers."""
    owner = f"onecase-{uuid.uuid4().hex[:8]}"
    event_id = str(uuid.uuid4())
    case = await repo.create_case(owner, "email", None, client_submission_id=event_id, initiator="user_check")

    # Nothing is filed while the investigation runs: the device already has the record.
    assert await project_case_started({**case, "owner_id": owner}) is False
    assert await db.patrol_events.count_documents({"device_id": owner}) == 0

    await _device_event(owner, event_id)
    # A projection pass over a case that has not answered yet must still leave exactly one record.
    await project_committed_cases()
    events = await db.patrol_events.find({"device_id": owner}).to_list(10)
    assert len(events) == 1
    assert events[0]["event_id"] == event_id
    assert events[0]["evidence_provenance"] == "local_device"


async def test_case_without_a_device_record_is_still_filed():
    """Apollo's own server-side investigations (Gmail monitoring, Ask Higgins) have no device record,
    so they must still be given one — the fix must not hide them."""
    owner = f"serveronly-{uuid.uuid4().hex[:8]}"
    case = await repo.create_case(owner, "email", None, initiator="apollo_automatic")
    assert await project_case_started({**case, "owner_id": owner}) is True
    events = await db.patrol_events.find({"device_id": owner}).to_list(10)
    assert len(events) == 1
    assert events[0]["investigation_case_id"] == case["case_id"]


async def test_a_case_answered_before_the_device_record_arrives_is_filed_under_that_record():
    """TC FlyBy often answers before the device's own patrol record reaches the server. The answer must be
    filed under the device's event id, so when the device's copy arrives it is the same record — not a twin."""
    from services.higgins.contracts import HigginsResponse, ProviderResult, TurnCommit
    owner = f"fastcase-{uuid.uuid4().hex[:8]}"
    event_id = str(uuid.uuid4())
    case = await repo.create_case(owner, "text", None, client_submission_id=event_id, initiator="user_check")
    turn_id = str(uuid.uuid4())
    job = await repo.create_job(owner, case, turn_id, repo.digest("key"), repo.digest("payload"), "turn", {"message": "q", "turnId": turn_id})
    await repo.cas(owner, case["case_id"], {"revision": 0}, {"$set": {"active_job_id": job["job_id"], "active_turn_id": turn_id}})
    job = await repo.acquire_lease(owner, job["job_id"])
    case = await repo.cas(owner, case["case_id"], {"active_job_id": job["job_id"]}, {"$set": {"lease_fence": job["fence"]}}, bump=False)
    response = HigginsResponse(revision=1, overview="This matches a known scam", explanationMarkdown="Explanation", assessment="concern_found",
                               attention="action_needed", findings=[], uncertainties=[], scope="submitted message", sourceIds=[],
                               remainingEvidenceIds=[], actions=[], completion="complete")
    commit = TurnCommit(turnId=turn_id, caseId=case["case_id"], inputRevision=1, committedRevision=1, question="q", response=response,
                        provider=ProviderResult(model="tc-flyby", finishReason="STOP", providerComplete=True), committedAt=now_utc())
    commit_id = await repo.stage_turn(owner, commit, job, repo.utc(case["expires_at"]))
    assert await repo.accept_turn(owner, case, job, commit, commit_id, "complete", "none", None)

    await project_committed_cases()          # the device's record hasn't arrived yet
    events = await db.patrol_events.find({"device_id": owner}).to_list(10)
    assert [e["event_id"] for e in events] == [event_id], "filed under the device's own record id"
    await db.patrol_events.update_one({"device_id": owner, "event_id": event_id}, {"$set": {"evidence_provenance": "local_device"}})  # the device's copy arrives
    assert await db.patrol_events.count_documents({"device_id": owner}) == 1
