"""The retained PRD classification survives the mandatory local Finding stage."""
import json
from unittest.mock import AsyncMock

import pytest

from core.db import db
from routers import slm_handoff
from services.higgins import coordinator, repository as repo, tc_hawkeye
from services.higgins.validation import validate
from tests.test_review_repairs import owner, leased_job
from tests.test_magnum_floor_resolver import _base_response, _finding, EVIDENCE, SOURCES, CAPS


def local_finding(evidence_id, outcome="unlikely_scam"):
    return {"modelId": "local-test", "caseFinding": {
        "outcome": outcome, "explanation": "The supplied evidence does not establish a scam.",
        "uncertainty": "No positive identity verification was supplied.", "advice": None,
        "reasons": [{"text": "Nothing establishes a consequential scam request.", "evidenceIds": [evidence_id]}],
    }}


async def classified_case(owner):
    case, job, item = await leased_job(owner)
    result = await tc_hawkeye.investigate(owner, case, job, "Is this real?",
                                         await repo.list_evidence(owner, case["case_id"]), AsyncMock())
    assert result.resolved and result.response["outcome"] == "unlikely_scam"
    return case, job, item, result.response


async def test_local_finding_keeps_the_rule_verdict_and_full_score_audit(owner, monkeypatch):
    case, job, item, retained = await classified_case(owner)
    commit = AsyncMock(return_value=coordinator.Outcome("committed"))
    monkeypatch.setattr(coordinator, "_commit", commit)
    result = await coordinator._commit_slm_finding(owner, case, job, {"message": "q"}, local_finding(item.id), set())
    assert result.kind == "committed"
    response = commit.await_args.args[4]
    assert response.outcome == retained["outcome"]
    assert response.findings_rating == retained["findingsRating"]
    assert response.findings_rating_breakdown == retained["findingsRatingBreakdown"]
    assert response.findings_rating_breakdown["rawRating"] == 0
    assert response.findings_rating_breakdown["rating"] == 25
    assert response.findings_rating_breakdown["adjustmentReason"]


@pytest.mark.parametrize("outcome", ["not_scam", "scam"])
async def test_local_model_cannot_replace_a_resolved_evidence_verdict(owner, monkeypatch, outcome):
    case, job, item, retained = await classified_case(owner)
    commit = AsyncMock()
    monkeypatch.setattr(coordinator, "_commit", commit)
    assert await coordinator._commit_slm_finding(owner, case, job, {"message": "q"}, local_finding(item.id, outcome), set()) is None
    commit.assert_not_awaited()


async def test_local_stage_receives_the_retained_classification_as_a_labelled_projection(owner):
    case, job, item, retained = await classified_case(owner)
    rows = await repo.list_evidence(owner, case["case_id"])
    row = next(row for row in rows if row["client_item_id"] == "tc-hawkeye-classification")
    assert row["origin"] == "apollo_inference"
    material = await slm_handoff._source_evidence(owner, case["case_id"], include_checks=True)
    data = json.loads(next(reference.text for reference in material if reference.evidence_id == row["evidence_id"]))
    assert data["representation"] == "deterministic_evidence_classification_not_new_source_facts"
    assert data["outcome"] == retained["outcome"]
    assert data["findingsRatingBreakdown"] == retained["findingsRatingBreakdown"]


async def test_independent_investigation_does_not_present_the_old_local_score_as_its_rating(owner, monkeypatch):
    case, job, item, retained = await classified_case(owner)
    await db.investigation_cases.update_one({"owner_id": owner, "case_id": case["case_id"]},
                                           {"$set": {"routing.magnum": {"status": "completed", "simulated": False}}})
    commit = AsyncMock(return_value=coordinator.Outcome("committed"))
    monkeypatch.setattr(coordinator, "_commit", commit)
    assert await coordinator._commit_slm_finding(owner, case, job, {"message": "q"}, local_finding(item.id), set())
    response = commit.await_args.args[4]
    assert response.findings_rating is None and response.findings_rating_breakdown is None


def test_a_substantive_finding_is_not_hidden_by_a_second_low_confidence_finding():
    data = _base_response(outcome="likely_scam", findings=[_finding("uncertain", confidence="low"), _finding("corroborated", confidence="high")])
    response, errors = validate(data, revision=1, evidence_ids=EVIDENCE, source_ids=SOURCES, capability_ids=CAPS,
                                pending_question=None, provider_complete=True)
    assert response is not None, errors
