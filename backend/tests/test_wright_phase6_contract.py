"""Phase 6 contract checks: semantic assessment cannot masquerade as a verdict."""
import pytest
from services.higgins.slm_contract import SLMReasoningRequest, SLMReasoningResult, accept_advisory_reasoning

def request():
    return SLMReasoningRequest.model_validate({
        "caseId": "case-1234", "caseRevision": 1, "requestId": "req-1234",
        "role": "wright_triage", "operation": "wright_semantic",
        "question": "Interpret evidence", "evidence": [{"evidenceId": "src1", "text": "Invoice due."}],
    })

def result():
    return {
        "caseId": "case-1234", "caseRevision": 1, "requestId": "req-1234",
        "execution": "on_device", "modelId": "local-test",
        "answer": {
            "observations": [], "contradictions": [], "alternativeExplanations": [],
            "verificationSuggestions": [], "draftExplanation": None,
            "wrightSemantic": {
                "version": "wright.semantic.v1", "classification": "ambiguous",
                "scamTypes": [], "intent": "Requests payment", "coercion": "uncertain",
                "exposure": {"payment": "UNKNOWN", "credentials": "UNKNOWN",
                             "identity": "UNKNOWN", "remoteAccess": "UNKNOWN"},
                "narrative": "Payment request alone is not proof of a scam.",
                "uncertainty": "Sender unverified", "supportingEvidenceIds": ["src1"],
            },
        },
    }

def test_accept_grounded_semantic():
    answer = accept_advisory_reasoning(request(), SLMReasoningResult.model_validate(result()))
    assert answer.wright_semantic.classification == "ambiguous"

def test_reject_unknown_citation():
    body = result()
    body["answer"]["wrightSemantic"]["supportingEvidenceIds"] = ["foreign-device"]
    with pytest.raises(ValueError):
        accept_advisory_reasoning(request(), SLMReasoningResult.model_validate(body))

def test_reject_verdict_in_semantic_stage():
    body = result()
    body["answer"]["caseFinding"] = {
        "outcome": "not_scam", "explanation": "Safe", "reasons": [
            {"text": "Safe", "evidenceIds": ["src1"]}],
        "uncertainty": None, "advice": None,
    }
    with pytest.raises(ValueError):
        accept_advisory_reasoning(request(), SLMReasoningResult.model_validate(body))

def test_missing_semantic_is_not_accepted():
    body = result()
    del body["answer"]["wrightSemantic"]
    with pytest.raises(ValueError):
        accept_advisory_reasoning(request(), SLMReasoningResult.model_validate(body))
