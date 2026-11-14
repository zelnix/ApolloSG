"""Wright readiness-only stage contracts: no threat judgement or missing inventory."""
import pytest
from services.higgins.slm_contract import SLMReasoningRequest, SLMReasoningResult, accept_advisory_reasoning
from services.higgins.wright_readiness_contract import validate_wright_readiness
from services.higgins import coordinator
from types import SimpleNamespace
from unittest.mock import AsyncMock

def request(**changes):
    return SLMReasoningRequest.model_validate({
        "caseId": "case-1234", "caseRevision": 1, "requestId": "req-1234",
        "role": "wright_triage", "operation": "investigation_readiness",
        "question": "Check source availability", "evidence": [{"evidenceId": "src1", "text": "0299363990"}],
        **changes,
    })

def result():
    return {
        "caseId": "case-1234", "caseRevision": 1, "requestId": "req-1234",
        "execution": "on_device", "modelId": "local-test",
        "answer": {"observations": [], "contradictions": [], "alternativeExplanations": [],
                   "verificationSuggestions": [], "draftExplanation": None,
                   "wrightReadiness": {"version": "wright.readiness.v1",
                       "evidence": [{"evidenceId": "src1", "availability": "readable"}]}},
    }

def accept(body=None, issued=None):
    return accept_advisory_reasoning(issued or request(), SLMReasoningResult.model_validate(body or result()))

def test_number_only_evidence_is_available_without_a_scam_or_identity_decision():
    answer = accept()
    assert answer.wright_readiness.has_readable_evidence
    assert answer.case_finding is None and answer.escalation_assessment is None

@pytest.mark.parametrize("field", ["classification", "scamTypes", "intent", "coercion", "exposure", "narrative",
                                    "outcome", "risk", "score", "advice", "caseFinding", "escalationAssessment"])
def test_readiness_rejects_finding_fields_at_every_level(field):
    for path in ("record", "item"):
        body = result()
        target = body["answer"]["wrightReadiness"]
        if path == "item":
            target = target["evidence"][0]
        target[field] = "finding-like claim"
        with pytest.raises(ValueError):
            accept(body)

@pytest.mark.parametrize("key,value", [
    ("observations", [{"text": "Scam", "evidenceIds": ["src1"]}]),
    ("verificationSuggestions", [{"text": "Investigate fraud", "evidenceIds": ["src1"]}]),
    ("draftExplanation", "Likely a scam"),
    ("caseFinding", {"outcome": "not_scam", "explanation": "Safe", "reasons": [{"text": "Safe", "evidenceIds": ["src1"]}], "uncertainty": None, "advice": None}),
    ("escalationAssessment", {"decision": "escalate", "rationale": "Fraud", "evidenceIds": ["src1"], "materialGaps": []}),
])
def test_wright_cannot_smuggle_findings_through_generic_slm_fields(key, value):
    body = result()
    body["answer"][key] = value
    with pytest.raises(ValueError):
        accept(body)

@pytest.mark.parametrize("evidence", [[], [{"evidenceId": "foreign-device", "availability": "readable"}],
                                      [{"evidenceId": "src1", "availability": "readable"}] * 2])
def test_exact_owner_scoped_inventory_is_required(evidence):
    body = result()
    body["answer"]["wrightReadiness"]["evidence"] = evidence
    with pytest.raises(ValueError):
        accept(body)

def test_missing_item_cannot_be_silently_omitted():
    issued = request(evidence=[{"evidenceId": "src1", "text": "text"}, {"evidenceId": "src2", "text": "text"}])
    with pytest.raises(ValueError, match="inventory_mismatch"):
        accept(issued=issued)

def test_binary_metadata_cannot_be_claimed_as_readable_original_content():
    issued = request(evidence=[{"evidenceId": "src1", "text": "image inventory", "representation": "inventory_only"}])
    with pytest.raises(ValueError, match="representation_mismatch"):
        accept(issued=issued)

def test_derived_text_can_proceed_while_original_inventory_remains_unexamined():
    value = {"version": "wright.readiness.v1", "evidence": [
        {"evidenceId": "image", "availability": "inventory_only"},
        {"evidenceId": "ocr", "availability": "readable"}]}
    readiness = validate_wright_readiness(value, {"image": "inventory_only", "ocr": "derived_text"})
    assert readiness.has_readable_evidence

def test_unreadable_is_a_readiness_problem_not_a_scam_verdict():
    body = result()
    body["answer"]["wrightReadiness"]["evidence"][0]["availability"] = "unreadable"
    assert not accept(body).wright_readiness.has_readable_evidence

@pytest.mark.parametrize("operation", ["wright_semantic", "case_finding", "escalation_assessment", "evidence_reasoning"])
def test_wright_role_cannot_request_other_decision_operations(operation):
    with pytest.raises(ValueError):
        accept(issued=request(operation=operation))

def test_deprecated_semantic_advice_is_rejected_on_live_requests():
    body = result()
    body["answer"]["wrightSemantic"] = {
        "version": "wright.semantic.v1", "classification": "ambiguous", "scamTypes": [], "intent": "A claim",
        "coercion": "uncertain", "exposure": {"payment": "UNKNOWN", "credentials": "UNKNOWN", "identity": "UNKNOWN", "remoteAccess": "UNKNOWN"},
        "narrative": "Legacy assessment", "uncertainty": None, "supportingEvidenceIds": []}
    with pytest.raises(ValueError, match="obsolete_wright_output"):
        accept(body)


@pytest.mark.parametrize("readable", [False, True])
async def test_readiness_only_admits_evidence_to_hawkeye_and_cannot_settle_a_case(monkeypatch, readable):
    rows = [{"evidence_id": "src1", "kind": "text", "availability": "available"}]
    monkeypatch.setattr(coordinator.repo, "dec_json", lambda value: {"message": "0299363990"})
    monkeypatch.setattr(coordinator.repo, "device_profile", lambda case: {})
    monkeypatch.setattr(coordinator.repo, "list_evidence", AsyncMock(return_value=rows))
    monkeypatch.setattr(coordinator, "_register_triage_evidence", AsyncMock())
    readiness = result()["answer"]["wrightReadiness"]
    readiness["evidence"][0]["availability"] = "readable" if readable else "unreadable"
    monkeypatch.setattr(coordinator, "_slm_stage", AsyncMock(return_value={"wrightReadiness": readiness}))
    hawkeye = AsyncMock(return_value=SimpleNamespace(resolved=True))
    monkeypatch.setattr(coordinator.tc_hawkeye, "investigate", hawkeye)
    # Readiness alone never skips the required Higgins assessment/final Finding.
    monkeypatch.setattr(coordinator, "_await_escalation_assessment", AsyncMock(return_value=None))
    outcome = await coordinator.run_turn("owner-1", {"case_id": "case-1234"}, {"payload_ciphertext": "encrypted"}, AsyncMock())
    if readable:
        hawkeye.assert_awaited_once()
        assert hawkeye.await_args.args[4] is rows
        assert not hawkeye.await_args.kwargs, "Wright assessments must not enter the investigation merits/check order"
        assert outcome.kind == "device_unavailable", "Higgins assessment remains mandatory"
    else:
        hawkeye.assert_not_awaited()
        assert outcome.kind == "evidence_unavailable"
    assert outcome.commit is None
