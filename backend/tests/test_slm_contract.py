"""Tests for Luddish's advisory-only backend contract (no database required)."""
import pytest
from pydantic import ValidationError

from services.higgins.slm_contract import (
    SLMReasoningRequest, SLMReasoningResult, accept_advisory_reasoning,
)


def request():
    return SLMReasoningRequest.model_validate({
        "caseId": "case-A", "caseRevision": 7, "requestId": "req-A",
        "role": "tc_hawkeye", "operation": "evidence_reasoning",
        "question": "What warrants verification?",
        "evidence": [{"evidenceId": "E-1", "text": "Guaranteed monthly return"}],
    })


def result(**changes):
    data = {
        "caseId": "case-A", "caseRevision": 7, "requestId": "req-A",
        "execution": "on_device", "modelId": "qwen-test",
        "answer": {
            "observations": [{"text": "The message claims a guaranteed return", "evidenceIds": ["E-1"]}],
            "contradictions": [], "alternativeExplanations": [],
            "verificationSuggestions": [{"text": "Verify the claim independently", "evidenceIds": ["E-1"]}],
            "draftExplanation": None,
        },
    }
    data.update(changes)
    return SLMReasoningResult.model_validate(data)


def test_accepts_correlated_advisory_observations():
    accepted = accept_advisory_reasoning(request(), result())
    assert accepted.observations[0].evidence_ids == ["E-1"]
    assert "verdict" not in accepted.wire()
    assert "score" not in accepted.wire()


@pytest.mark.parametrize("field,value", [
    ("caseId", "case-B"), ("caseRevision", 8), ("requestId", "req-B"),
])
def test_rejects_stale_or_other_case_response(field, value):
    with pytest.raises(ValueError, match="slm_request_mismatch"):
        accept_advisory_reasoning(request(), result(**{field: value}))


def test_rejects_invented_evidence_citations():
    suspicious = result(answer={
        "observations": [{"text": "Other case claims", "evidenceIds": ["E-2"]}],
        "contradictions": [], "alternativeExplanations": [],
        "verificationSuggestions": [], "draftExplanation": None,
    })
    with pytest.raises(ValueError, match="unrecognised_slm_evidence"):
        accept_advisory_reasoning(request(), suspicious)


def test_rejects_model_authored_verdict_and_score():
    with pytest.raises(ValidationError):
        result(answer={
            "observations": [], "contradictions": [], "alternativeExplanations": [],
            "verificationSuggestions": [], "draftExplanation": None,
            "verdict": "This is a Scam", "score": 99,
        })


def test_rejects_invalid_request_limits_and_duplicate_ids():
    with pytest.raises(ValidationError):
        SLMReasoningRequest.model_validate({
            **request().wire(), "evidence": [
                {"evidenceId": "E-1", "text": "a"},
                {"evidenceId": "E-1", "text": "b"},
            ]
        })
    with pytest.raises(ValidationError):
        SLMReasoningRequest.model_validate({
            **request().wire(), "evidence": [{"evidenceId": "E-1", "text": "x" * 120001}],
        })


def test_unavailable_is_not_a_fake_success_and_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        result(execution="cloud")
    with pytest.raises(ValidationError):
        result(simulated=True)
