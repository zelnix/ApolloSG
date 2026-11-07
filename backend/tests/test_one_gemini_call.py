"""One correlated case = at most one Magnum DI call, and no retries.

Every test drives the real durable job (`jobs.run`) with the gateway replaced, and counts the calls:
- a successful investigation makes exactly ONE call — no tool rounds, no nested research, no second
  "presentation" call;
- a failed call or an invalid answer is never retried: the investigation stops, says why, and keeps what
  TC Hawkeye established;
- a second job, a recovered job, a duplicate worker, a follow-up, a Resubmit tap or a restart can make no further call;
- a case TC Hawkeye settles makes none.

Run: cd /app/backend && python -m pytest tests/test_one_gemini_call.py -q -n 0
"""
import json
import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from core.db import db
from services.higgins import coordinator, jobs, provider
from services.higgins import evidence as ev
from services.higgins import repository as repo
from services.higgins.contracts import SubmitTurn
from services.higgins.preview.preview_simulator import evidence_blocks, simulated_text
from services.higgins.provider import AIResult, ProviderFailure, Purpose


def _gateway(monkeypatch, *script):
    """Replace the AI gateway. Each call consumes the next scripted step: "ok", "invalid" or a ProviderFailure."""
    calls: list[dict] = []

    async def fake(system, contents, **kwargs):
        calls.append({"system": system, "kwargs": kwargs})
        step = script[min(len(calls), len(script)) - 1]
        if isinstance(step, ProviderFailure):
            raise step
        text = "not json at all" if step == "invalid" else simulated_text(Purpose.INVESTIGATION, True, evidence_blocks(contents))
        return AIResult(text=text, finish_reason="STOP",
                            usage={"prompt_token_count": 1, "candidates_token_count": 1, "total_token_count": 2}, grounding=None,
                            model=kwargs.get("model") or "gemini-3.1-flash-lite")

    monkeypatch.setattr(provider, "generate", fake)
    return calls


async def _job(owner: str, case: dict, message: str = "Is this real?") -> str:
    case = await repo.get_case(owner, case["case_id"])
    turn_id = str(uuid.uuid4())
    job = await repo.create_job(owner, case, turn_id, repo.digest(turn_id), repo.digest("p" + turn_id), "turn", {"message": message, "turnId": turn_id})
    await repo.cas(owner, case["case_id"], {"revision": case["revision"]}, {"$set": {"active_job_id": job["job_id"], "active_turn_id": turn_id, "status": "queued"}})
    return job["job_id"]


async def _investigation():
    owner = f"one-call-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "text", None)
    # A request to send money through a route nothing TC Hawkeye established, and no Higgins Triage rule flags: Magnum DI's
    # analysis could change what to do, so it reaches Magnum DI's one call.
    await ev.ingest_text(owner, case, "message-text", "Hi, it's Sarah from accounts. Please pay invoice 4471 "
                         "($1,240) to account 1234 5678 today.", kind="text", origin="user_submission", label="Submitted message text")
    return owner, case["case_id"], await _job(owner, case)


async def _event_types(owner: str, job_id: str) -> list[str]:
    return [e["type"] for e in await repo.events_after(owner, job_id, 0)]


async def test_successful_investigation_makes_exactly_one_call(monkeypatch):
    calls = _gateway(monkeypatch, "ok")
    owner, case_id, job_id = await _investigation()
    await jobs.run(owner, case_id, job_id)
    assert len(calls) == 1
    assert calls[0]["kwargs"]["purpose"] == Purpose.INVESTIGATION
    assert calls[0]["kwargs"]["device_id"] == owner and calls[0]["kwargs"]["job_id"] == job_id, "usage is attributed to device and job"
    job = await repo.get_job(owner, case_id, job_id)
    assert job["status"] in ("complete", "partial", "waiting_user")
    assert await repo.magnum_call_used(owner, case_id)
    assert "completed" in await _event_types(owner, job_id)


@pytest.mark.parametrize("step", [ProviderFailure("rate_limited", retryable=True), ProviderFailure("provider_unavailable", retryable=True), "invalid"],
                         ids=["rate_limited", "unavailable", "invalid"])
async def test_a_failed_call_or_invalid_answer_is_never_retried(monkeypatch, step):
    calls = _gateway(monkeypatch, step, "ok", "ok")
    owner, case_id, job_id = await _investigation()
    await jobs.run(owner, case_id, job_id)
    assert len(calls) == 1, "no automatic retry"
    job = await repo.get_job(owner, case_id, job_id)
    failure = job["failure"]
    assert job["status"] == "failed" and failure["retryable"] is False and job.get("resubmit_at") is None
    assert failure["code"] == ("response_invalid" if step == "invalid" else step.code)
    assert "No conclusion has been made up" in failure["message"] and "isn't tried again for this case" in failure["message"]
    reason = "didn't pass Apollo's checks" if step == "invalid" else ("too busy" if step.code == "rate_limited" else "didn't answer in time")
    assert reason in failure["message"], "the failure reason is shown"
    kinds = await _event_types(owner, job_id)
    assert "retry_scheduled" not in kinds and kinds[-1] == "failed"


async def test_configuration_failure_is_never_retried(monkeypatch):
    calls = _gateway(monkeypatch, ProviderFailure("provider_configuration", http_status=403), "ok")
    owner, case_id, job_id = await _investigation()
    await jobs.run(owner, case_id, job_id)
    assert len(calls) == 1
    job = await repo.get_job(owner, case_id, job_id)
    assert job["failure"]["code"] == "provider_configuration" and job["failure"]["retryable"] is False
    assert "retry_scheduled" not in await _event_types(owner, job_id)


@pytest.mark.parametrize("first", ["ok", "failed"])
async def test_no_new_job_recovery_or_restart_makes_a_second_call_for_the_case(monkeypatch, first):
    """A second job on the same case (a recovered job, a duplicate worker, a restart) is refused before anything is sent."""
    calls = _gateway(monkeypatch, "ok" if first == "ok" else ProviderFailure("provider_unavailable", retryable=True), "ok")
    owner, case_id, job_id = await _investigation()
    await jobs.run(owner, case_id, job_id)
    case = await repo.get_case(owner, case_id)
    await repo.cas(owner, case_id, {"revision": case["revision"]}, {"$set": {"active_job_id": None, "response_revision": 0, "response_ciphertext": None}})
    second = await _job(owner, case)
    await jobs.run(owner, case_id, second)
    assert len(calls) == 1, "one Magnum DI call per correlated case"
    job = await repo.get_job(owner, case_id, second)
    assert job["status"] == "failed" and "already had its one Magnum DI call" in job["failure"]["message"]
    assert job["failure"]["retryable"] is False


async def test_the_case_claim_is_atomic():
    owner, case_id, job_id = await _investigation()
    import asyncio
    claims = await asyncio.gather(*(repo.claim_magnum_call(owner, case_id, job_id) for _ in range(6)))
    assert sorted(claims) == [False] * 5 + [True]
    assert await db.magnum_di_calls.count_documents({"correlation_id": f"case-{case_id}"}) == 1


def _request(owner: str) -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.device = {"device_id": owner}
    return request


async def test_resubmit_never_makes_a_second_call(monkeypatch):
    from routers import investigations as inv
    from services.higgins.contracts import ExpectedRevision
    _gateway(monkeypatch, ProviderFailure("provider_unavailable", retryable=True), "ok")
    owner, case_id, job_id = await _investigation()
    await jobs.run(owner, case_id, job_id)
    launched: list[str] = []
    monkeypatch.setattr(inv.jobs, "launch", lambda _o, _c, j: launched.append(j))
    case = await repo.get_case(owner, case_id)
    with pytest.raises(HTTPException) as refused:
        await inv.resume_job(case_id, job_id, ExpectedRevision(expected_revision=case["revision"]), _request(owner), str(uuid.uuid4()))
    assert refused.value.status_code == 409 and "one call" in refused.value.detail["error"]["message"]
    assert launched == []


async def test_a_stop_before_magnum_di_can_be_resubmitted(monkeypatch):
    """The spending limit refused the call before anything was sent: the case's call wasn't used, so Resubmit may run."""
    from routers import investigations as inv
    from services.higgins.contracts import ExpectedRevision
    calls = _gateway(monkeypatch, ProviderFailure("budget_limit", original_message="over the limit"))
    owner, case_id, job_id = await _investigation()
    await jobs.run(owner, case_id, job_id)
    job = await repo.get_job(owner, case_id, job_id)
    assert len(calls) == 1 and job["failure"]["code"] == "budget_limit" and job["failure"]["retryable"] is True
    assert "spending limit" in job["failure"]["message"] and "before Magnum DI's call was made" in job["failure"]["message"]
    assert not await repo.magnum_call_used(owner, case_id), "nothing was sent, so nothing is counted"
    launched: list[str] = []
    monkeypatch.setattr(inv.jobs, "launch", lambda _o, _c, j: launched.append(j))
    case = await repo.get_case(owner, case_id)
    response = await inv.resume_job(case_id, job_id, ExpectedRevision(expected_revision=case["revision"]), _request(owner), str(uuid.uuid4()))
    assert response.status_code == 202 and launched == [job_id]
    assert json.loads(response.body)["job"]["status"] == "queued"


@pytest.mark.parametrize("answer_to_question", [False, True])
async def test_follow_ups_are_answered_from_the_locked_findings_with_no_call(monkeypatch, answer_to_question):
    from routers import investigations as inv
    calls = _gateway(monkeypatch, "ok")
    owner, case_id, job_id = await _investigation()
    await jobs.run(owner, case_id, job_id)
    case = await repo.get_case(owner, case_id)
    body = SubmitTurn(expected_revision=case["revision"], turn_id=str(uuid.uuid4()), message="Why is this a concern? Also check https://other.example/x",
                      answer_to_question_id="q-1" if answer_to_question else None)
    answer = await inv._follow_up(owner, case, body)
    assert answer and answer["answeredBy"] == "apollo" and answer["answer"]
    assert len(calls) == 1, "a follow-up never reaches Magnum DI"
    assert await db.investigation_jobs.count_documents({"owner_id": owner, "case_id": case_id}) == 1, "no new job"


async def test_a_follow_up_after_a_failed_magnum_call_gets_the_reason_and_tc_flybys_findings(monkeypatch):
    from routers import investigations as inv
    calls = _gateway(monkeypatch, "invalid")
    owner, case_id, job_id = await _investigation()
    await jobs.run(owner, case_id, job_id)
    case = await repo.get_case(owner, case_id)
    answer = await inv._follow_up(owner, case, SubmitTurn(expected_revision=case["revision"], turn_id=str(uuid.uuid4()), message="So is it a scam?"))
    assert answer and "didn't pass Apollo's checks" in answer["answer"] and answer["limitation"] is True
    assert len(calls) == 1


async def test_settings_plan_makes_no_gemini_call(monkeypatch):
    from routers import investigations as inv
    from services.higgins.contracts import DeviceProfile, SettingsPlanRequest
    calls = _gateway(monkeypatch, "ok")
    owner, case_id, _job_id = await _investigation()
    case = await repo.get_case(owner, case_id)
    device = DeviceProfile(platform="android", manufacturer="Example", model="Phone", os_version="14", form_factor="phone", locale="en-AU",
                           evidence_origin="native", capability_ids=[])
    body = SettingsPlanRequest(expected_revision=case["revision"], target="Turn on Play Protect. Open Settings, then Security.", device=device,
                               capability_id=None, expected_field="state", expected_value=None)
    response = json.loads((await inv.settings_plan(case_id, body, _request(owner))).body)
    assert calls == []
    assert response["plan"]["instructions"] == ["Turn on Play Protect.", "Open Settings, then Security."]


def test_investigation_code_has_no_other_gemini_call_path():
    import inspect
    from services.higgins import tools
    assert "provider" not in inspect.getsource(tools), "observation tools must not reach the Gemini gateway"
    assert inspect.getsource(coordinator).count("provider.generate(") == 1
    assert coordinator.MAX_MAGNUM_CALLS == 1
    assert "retry_once" not in inspect.getsource(jobs) and "asyncio.sleep(delay)" not in inspect.getsource(jobs), "no automatic retry"
    from routers import analysis
    source = inspect.getsource(analysis.vision_investigate)
    assert "generate_json" not in source and "generate(" not in source, "the Vision Gate must not pre-analyse with Gemini"
