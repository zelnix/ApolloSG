"""Behavioral regression tests for the reviewed lifecycle and evidence boundaries.

Use an isolated Mongo database. No provider requests or native inference.
"""
import ast
import hashlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from core.db import db
from routers import investigations
from services import account_deletion, device_pickup, observed_intel, work_dedupe
from services.higgins import coordinator, evidence, hawkeye_record, jobs, repository as repo, validation
from services.higgins.ai_request import AIResult, ProviderFailure


@pytest.fixture
async def owner():
    owner = "repair-" + uuid.uuid4().hex
    await db.devices.insert_one({"device_id": owner, "platform": "android", "adapter_mode": "android", "revoked_at": None})
    await repo.ensure_indexes()
    await device_pickup.ensure_indexes()
    yield owner
    for name in await db.list_collection_names():
        await db[name].delete_many({"$or": [{"owner_id": owner}, {"device_id": owner}, {"owner": owner}]})


def test_all_backend_sources_parse():
    for path in Path(__file__).parents[1].rglob("*.py"):
        compile(ast.parse(path.read_text(), filename=str(path)), str(path), "exec")


async def test_app_import_health_and_protected_route():
    import server
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
        assert (await client.get("/health")).json() == {"status": "ok"}
        assert (await client.get("/api/investigations/slm/pending")).status_code == 401


async def test_capabilities_use_current_policy_without_provider_probe(monkeypatch):
    monkeypatch.setattr(investigations.ai_settings, "selection", AsyncMock(return_value={"provider": "gemini", "model": "gemini-3.1-flash-lite"}))
    response = await investigations.capabilities()
    assert json.loads(response.body)["bounds"]["lifetimeSeconds"]["value"] > 0


def finding_payload():
    return {"overview": "Proposed result", "explanationMarkdown": "Explanation", "assessment": "no_concern_found_within_scope",
            "outcome": "not_scam", "attention": "none", "findings": [{"text": "A claim", "basis": "inference", "confidence": "medium",
            "evidenceIds": ["E1"], "sourceIds": [], "supersedesFindingIds": []}], "uncertainties": [], "scope": "Submitted material",
            "sourceIds": [], "remainingEvidenceIds": [], "actions": [], "recommendedActionIndex": None, "question": None, "completion": "complete"}


def test_established_threat_veto_is_enforced_by_actual_validator():
    response, errors = validation.validate(finding_payload(), revision=1, evidence_ids={"E1"}, source_ids=set(), capability_ids=set(),
                                          pending_question=None, provider_complete=True, floor={"outcome": "scam", "established": True})
    assert response is None
    assert any("established threat" in error for error in errors)


def test_missing_original_prevents_a_clear_finding():
    row = {"evidence_id": "E1", "origin": "user_submission", "availability": "unavailable",
           "kind": "attachment", "coverage": {"status": "not_started"}}
    gaps = coordinator._material_gaps([row])
    assert gaps == {"E1"}
    response, errors = validation.validate(finding_payload(), revision=1, evidence_ids={"E1"}, source_ids=set(), capability_ids=set(),
                                          pending_question=None, provider_complete=True, material_gaps=gaps)
    assert response is None and any("coverage gaps" in error for error in errors)


def test_wright_interpretation_focuses_checks_without_creating_facts():
    from services.higgins.slm_advisory import prioritise_existing_checks
    first = SimpleNamespace(subject="bank domain", question="verify identity", status="open", facts=[])
    second = SimpleNamespace(subject="password reset", question="verify request", status="open", facts=[])
    checks = [first, second]
    prioritise_existing_checks(checks, {"wrightSemantic": {"intent": "A password reset request", "narrative": "Check the password reset route"}})
    assert checks == [second, first]
    assert all(check.status == "open" and check.facts == [] for check in checks)


async def test_chat_and_background_cases_resolve_only_their_registered_device(owner):
    case = await repo.create_case(owner, "text", None, initiator="higgins_user_request")
    assert repo.device_profile(case)["evidenceOrigin"] == "native"
    assert repo.device_profile(case)["platform"] == "android"
    assert await repo.registered_device_profile("another-device") is None


async def active_job(owner):
    case = await repo.create_case(owner, "text", None)
    job = await repo.create_job(owner, case, str(uuid.uuid4()), uuid.uuid4().hex, "payload", "turn", {"message": "Check evidence"})
    await repo.cas(owner, case["case_id"], {"active_job_id": None}, {"$set": {"active_job_id": job["job_id"], "status": "queued"}})
    return case, job


async def leased_job(owner):
    case, job = await active_job(owner)
    job = await repo.acquire_lease(owner, job["job_id"])
    case = await repo.cas(owner, case["case_id"], {"active_job_id": job["job_id"]},
                          {"$set": {"lease_fence": job["fence"], "status": "investigating"}}, bump=False)
    item = await evidence.ingest_text(owner, case, "source", "Please verify this source claim")
    return case, job, item


async def test_pending_slm_inbox_is_recoverable_and_owner_scoped(owner):
    from routers import slm_handoff
    case, job, item = await leased_job(owner)
    issued = await slm_handoff.issue_stage_request(owner, case["case_id"], job["job_id"], case["revision"], "wright_triage")
    assert issued["request"]["evidence"][0]["evidenceId"] == item.id
    own = SimpleNamespace(state=SimpleNamespace(device={"device_id": owner}))
    other = SimpleNamespace(state=SimpleNamespace(device={"device_id": "other-device"}))
    assert len(json.loads((await slm_handoff.pending_advisories(own)).body)["items"]) == 1
    assert json.loads((await slm_handoff.pending_advisories(other)).body)["items"] == []
    await db.investigation_cases.update_one({"owner_id": owner, "case_id": case["case_id"]}, {"$set": {"work_epoch": "cancelled", "active_job_id": None}})
    assert json.loads((await slm_handoff.pending_advisories(own)).body)["items"] == []


async def test_native_failure_code_is_retained_as_diagnostics_not_evidence(owner):
    from routers import slm_handoff
    case, job, item = await leased_job(owner)
    issued = await slm_handoff.issue_stage_request(owner, case["case_id"], job["job_id"], case["revision"], "wright_triage")
    body = slm_handoff.AdvisoryFailure(caseId=case["case_id"], caseRevision=case["revision"], requestId=issued["request"]["requestId"],
                                     status="unavailable", reason="on_device_inference_failed:preflight:context_budget_exceeded")
    request = SimpleNamespace(state=SimpleNamespace(device={"device_id": owner}))
    await slm_handoff.advisory_failure(case["case_id"], body, request)
    assert await coordinator._wait_for_slm(owner, case, job, "wright_triage", issued) is None
    assert job["slm_failure"]["reason"] == body.reason
    assert len(await repo.list_evidence(owner, case["case_id"])) == 1
    assert json.loads((await slm_handoff.pending_advisories(request)).body)["items"] == []


@pytest.mark.parametrize("nonstop", [False, True])
async def test_magnum_retains_provider_failure_details_without_claiming_examination(owner, monkeypatch, nonstop):
    case, job, item = await leased_job(owner)
    if nonstop:
        generate = AsyncMock(return_value=AIResult(text="unfinished response", finish_reason="MAX_TOKENS", usage={}, grounding=None, model=job["provider_model"]))
    else:
        generate = AsyncMock(side_effect=ProviderFailure("rate_limited", http_status=429, original_message="quota exceeded"))
    monkeypatch.setattr(coordinator.provider, "generate", generate)
    assert not await coordinator._magnum_external_evidence(owner, case, job, "Check source", await repo.list_evidence(owner, case["case_id"]), AsyncMock())
    generate.assert_awaited_once()
    rows = await repo.list_evidence(owner, case["case_id"])
    limitation = next(row for row in rows if row["client_item_id"] == "magnum-di-provider-limitation")
    details = json.loads(await repo.read_bytes(owner, case["case_id"], limitation["evidence_id"]))
    if nonstop:
        assert details["responseText"] == "unfinished response" and details["finishReason"] == "MAX_TOKENS"
    else:
        assert details["httpStatus"] == 429 and details["originalMessage"] == "quota exceeded"
    assert (await repo.get_evidence(owner, case["case_id"], item.id))["coverage"]["status"] == "not_started"


async def test_magnum_success_preserves_sources_simulation_and_coverage(owner, monkeypatch):
    case, job, item = await leased_job(owner)
    result = AIResult(text=json.dumps({"observations": [{"text": "A claim was found", "source": "registered source", "confidence": "medium"}],
                                     "uncertainties": ["Identity unverified"], "investigationScope": "Submitted source"}),
                      finish_reason="STOP", usage={}, model=job["provider_model"], simulated=True,
                      grounding={"grounding_chunks": [{"web": {"uri": "https://example.org/reference", "title": "Reference"}}]})
    monkeypatch.setattr(coordinator.provider, "generate", AsyncMock(return_value=result))
    assert await coordinator._magnum_external_evidence(owner, case, job, "Check source", await repo.list_evidence(owner, case["case_id"]), AsyncMock())
    assert (await repo.get_evidence(owner, case["case_id"], item.id))["coverage"]["status"] == "examined"
    sources = await repo.sources(owner, case["case_id"])
    assert sources[0]["url"] == "https://example.org/reference"
    commit = AsyncMock(return_value=coordinator.Outcome("committed"))
    monkeypatch.setattr(coordinator, "_commit", commit)
    await coordinator._commit_slm_finding(owner, case, job, {"message": "q"}, {
        "modelId": "local", "caseFinding": {"outcome": "unlikely_scam", "explanation": "Uncertain result", "uncertainty": "Identity unverified",
                                               "reasons": [{"text": "Claim needs verification", "evidenceIds": [item.id]}], "advice": None}}, set())
    response, provider = commit.await_args.args[4:6]
    assert provider.simulated is True
    assert response.source_ids == [sources[0]["id"]]


def test_historical_imports_are_the_same_engine_and_modules():
    from services.higgins import tc_flyby, tc_hawkeye
    from services.higgins.tc_flyby import scoring as old_scoring
    from services.higgins.tc_hawkeye import scoring
    assert tc_flyby is tc_hawkeye and old_scoring is scoring


async def test_unavailable_slm_preserves_original_failure(owner, monkeypatch):
    case, job = await active_job(owner)
    monkeypatch.setattr(coordinator, "run_turn", AsyncMock(return_value=coordinator.Outcome("device_unavailable", errors=["Native inference exceeded its context budget."])))
    await jobs.run(owner, case["case_id"], job["job_id"])
    saved = await repo.get_job(owner, case["case_id"], job["job_id"])
    assert saved["failure"]["code"] == "device_unavailable"
    assert "context budget" in saved["failure"]["message"]
    assert "TypeError" not in saved["failure"]["message"]


async def test_cancelled_worker_cannot_claim_or_complete_a_window(owner):
    case, job = await active_job(owner)
    job = await repo.acquire_lease(owner, job["job_id"])
    await repo.cas(owner, case["case_id"], {"active_job_id": job["job_id"]}, {"$set": {"lease_fence": job["fence"], "status": "investigating"}}, bump=False)
    assert await repo.claim_magnum_window(owner, case["case_id"], job["job_id"], 0, "digest")
    assert await repo.magnum_call_used(owner, case["case_id"])
    await db.investigation_cases.update_one({"owner_id": owner, "case_id": case["case_id"]}, {"$set": {"work_epoch": "cancelled", "active_job_id": None}})
    assert not await repo.claim_magnum_window(owner, case["case_id"], job["job_id"], 1, "digest-2")
    assert not await repo.complete_magnum_window(owner, case["case_id"], job["job_id"], 0, "digest", {"private": "response"})


async def test_cancellation_during_checkpoint_retains_the_irreversible_call_claim(owner, monkeypatch):
    case, job, item = await leased_job(owner)
    assert await repo.claim_magnum_window(owner, case["case_id"], job["job_id"], 0, "digest")
    monkeypatch.setattr(repo, "job_is_current", AsyncMock(side_effect=[True, False]))
    assert not await repo.complete_magnum_window(owner, case["case_id"], job["job_id"], 0, "digest", {"private": "late response"})
    marker = await db.magnum_di_window_calls.find_one({"owner_id": owner, "case_id": case["case_id"]})
    assert marker["status"] == "abandoned" and "result_ciphertext" not in marker
    assert await repo.magnum_call_used(owner, case["case_id"])


async def finished_pickup(owner):
    case = await repo.create_case(owner, "text", None)
    item = await evidence.ingest_text(owner, case, "original", "Evidence retained exactly")
    await db.investigation_cases.update_one({"owner_id": owner, "case_id": case["case_id"]}, {"$set": {"status": "complete"}})
    assert await device_pickup.hold(owner, case["case_id"])
    return case, item, await device_pickup.get(owner, case["case_id"])


async def test_pickup_bytes_survive_working_copy_cleanup_and_are_owner_scoped(owner):
    case, item, held = await finished_pickup(owner)
    original = b"Evidence retained exactly"
    assert await device_pickup.content(owner, case["case_id"], held["snapshotId"], item.id) == original
    with pytest.raises(HTTPException):
        await device_pickup.content("other-device", case["case_id"], held["snapshotId"], item.id)
    await repo.revoke(owner, case["case_id"], "expired")
    assert await repo.run_cleanup(owner, case["case_id"]) == "complete"
    assert await device_pickup.content(owner, case["case_id"], held["snapshotId"], item.id) == original
    manifest = held["evidenceContent"]
    assert manifest[0]["sha256"] == hashlib.sha256(original).hexdigest()
    assert device_pickup.missing(held, {"text": True, "snapshotId": held["snapshotId"]})
    saved = {"text": True, "result": False, "link": False, "headers": [], "snapshotId": held["snapshotId"],
             "evidenceDigests": {entry["evidenceId"]: entry["sha256"] for entry in manifest}}
    assert not device_pickup.missing(held, saved)
    request = SimpleNamespace(state=SimpleNamespace(device={"device_id": owner}), json=AsyncMock(return_value={"saved": saved}))
    assert json.loads((await investigations.confirm_commit(case["case_id"], request)).body)["purged"]
    assert await db[device_pickup.CHUNKS].count_documents({"owner_id": owner}) == 0
    assert json.loads((await investigations.confirm_commit(case["case_id"], request)).body)["purged"]


async def test_corrupt_pickup_never_certifies_bytes(owner):
    case, item, held = await finished_pickup(owner)
    await db[device_pickup.CHUNKS].update_one({"owner_id": owner}, {"$set": {"content_ciphertext": repo.encrypt(b"changed")}})
    with pytest.raises(HTTPException, match="integrity"):
        await device_pickup.content(owner, case["case_id"], held["snapshotId"], item.id)
    assert await device_pickup.get(owner, case["case_id"])


def pickup_confirmation(owner, held):
    saved = {"text": True, "link": False, "result": False, "headers": [], "snapshotId": held["snapshotId"],
             "evidenceDigests": {item["evidenceId"]: item["sha256"] for item in held["evidenceContent"]}}
    return SimpleNamespace(state=SimpleNamespace(device={"device_id": owner}), json=AsyncMock(return_value={"saved": saved}))


async def test_confirmation_cannot_delete_a_revision_started_during_projection(owner, monkeypatch):
    case, item, held = await finished_pickup(owner)

    async def start_new_revision(*_args):
        await db.investigation_cases.update_one({"owner_id": owner, "case_id": case["case_id"]},
                                                {"$inc": {"revision": 1}, "$set": {"active_job_id": "new-job", "status": "queued"}})

    monkeypatch.setattr(investigations, "project_case_now", start_new_revision)
    with pytest.raises(HTTPException) as conflict:
        await investigations.confirm_commit(case["case_id"], pickup_confirmation(owner, held))
    assert conflict.value.status_code == 409
    current = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case["case_id"]})
    assert not current["deleted"] and current["active_job_id"] == "new-job"
    assert await repo.read_bytes(owner, case["case_id"], item.id) == b"Evidence retained exactly"
    assert await device_pickup.get(owner, case["case_id"])


async def test_confirmation_retries_failed_cleanup_before_releasing_pickup(owner, monkeypatch):
    case, item, held = await finished_pickup(owner)
    request = pickup_confirmation(owner, held)
    cleanup = repo.run_cleanup
    monkeypatch.setattr(investigations, "project_case_now", AsyncMock())
    failure = AsyncMock(return_value="failed")
    monkeypatch.setattr(repo, "run_cleanup", failure)
    first = json.loads((await investigations.confirm_commit(case["case_id"], request)).body)
    assert first == {"purged": False, "status": "failed", "removedAt": None}
    assert await device_pickup.get(owner, case["case_id"])
    retry = json.loads((await investigations.confirm_commit(case["case_id"], request)).body)
    assert retry["purged"] is False and failure.await_count == 2
    assert await db.investigation_evidence.count_documents({"owner_id": owner}) == 1
    monkeypatch.setattr(repo, "run_cleanup", cleanup)
    done = json.loads((await investigations.confirm_commit(case["case_id"], request)).body)
    assert done["purged"] and done["removedAt"]
    assert await db.investigation_evidence.count_documents({"owner_id": owner}) == 0
    assert await device_pickup.get(owner, case["case_id"]) is None


async def test_deletion_covers_continuation_and_pickup_content(owner):
    case, item, held = await finished_pickup(owner)
    await db.magnum_di_window_calls.insert_one({"owner_id": owner, "case_id": case["case_id"], "result_ciphertext": repo.enc_json({"private": True})})
    await account_deletion.purge_device(owner)
    assert await db.magnum_di_window_calls.count_documents({"owner_id": owner}) == 0
    assert await db[device_pickup.CHUNKS].count_documents({"owner_id": owner}) == 0
    assert await db[device_pickup.COLLECTION].count_documents({"owner_id": owner}) == 0


async def test_case_expiry_removes_processing_payload_but_keeps_verified_pickup(owner):
    case, item, held = await finished_pickup(owner)
    await db.di_transactions.insert_one({"owner": owner, "investigation_id": case["case_id"], "request": "private processing payload"})
    await repo.revoke(owner, case["case_id"], "expired")
    await repo.run_cleanup(owner, case["case_id"])
    assert await db.di_transactions.count_documents({"owner": owner}) == 0
    assert await device_pickup.content(owner, case["case_id"], held["snapshotId"], item.id) == b"Evidence retained exactly"


@pytest.mark.parametrize("state", ["active", "deleted", "late"])
async def test_di_record_writer_fences_payloads_to_live_cases(owner, monkeypatch, state):
    from services.higgins import di_record
    case = await repo.create_case(owner, "text", None)
    assert di_record.estimate_cost({"prompt_token_count": 1000, "candidates_token_count": 100})["amountUsd"] > 0
    monkeypatch.setattr(di_record, "db", SimpleNamespace(
        investigation_cases=SimpleNamespace(find_one=AsyncMock(side_effect={
            "active": [{"_id": 1}, {"_id": 1}], "deleted": [None], "late": [{"_id": 1}, None],
        }[state])),
        di_transactions=db.di_transactions,
    ))
    await di_record.save_di_record(correlation_id=repo.correlation_id(case["case_id"]), owner=owner,
                                  investigation_id=case["case_id"], model="test", purpose="magnum_di",
                                  simulated=False, environment="test", status="complete", request={"private": "payload"},
                                  response_text="private response", finish_reason="STOP", usage={}, duration_ms=1, retries=0, calls=1)
    assert await db.di_transactions.count_documents({"owner": owner}) == (1 if state == "active" else 0)


def test_legacy_hawkeye_record_and_new_record_share_one_accessor():
    value = repo.enc_json({"floor": {"established": True, "outcome": "scam"}})
    assert hawkeye_record.read({"tc_hawkeye_ciphertext": value}) == hawkeye_record.read({"tc_flyby_ciphertext": value})


def test_dedupe_preserves_case_sensitive_source_identity():
    assert work_dedupe.digest("device", "url:https://example.org/Invoice") != work_dedupe.digest("device", "url:https://example.org/invoice")
    assert work_dedupe.digest("device-a", "text:same") != work_dedupe.digest("device-b", "text:same")
