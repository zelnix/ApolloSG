"""Advisory Luddish SLM wire contract for the existing device-request workflow.

This file is deliberately side-effect free. No new endpoint, database collection,
provider route or verdict engine is created here. Device computation remains
untrusted until the existing authenticated, case-scoped owner/job/revision gates
have accepted it. Even accepted observations are hypotheses, not case evidence.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from services.higgins.contracts import Wire
from services.higgins.wright_semantic_contract import WrightSemanticResult, validate_wright_semantic

SLMRole = Literal["wright_triage", "higgins_triage", "tc_hawkeye", "magnum_di", "luddish", "ask_higgins", "case_finding", "higgins_escalation_assessment"]
SLMOperation = Literal["wright_semantic", "investigation_readiness", "evidence_reasoning", "explanation", "chat_explanation", "case_finding", "escalation_assessment"]


class SLMReference(Wire):
    evidence_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=120000)


class SLMReasoningRequest(Wire):
    case_id: str = Field(min_length=4, max_length=80)
    case_revision: int = Field(ge=0)
    request_id: str = Field(min_length=4, max_length=80)
    role: SLMRole
    operation: SLMOperation
    evidence: list[SLMReference] = Field(max_length=64)
    question: str = Field(max_length=3000)

    @model_validator(mode="after")
    def check_references(self):
        ids = [e.evidence_id for e in self.evidence]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate_evidence_reference")
        if sum(len(e.text) for e in self.evidence) > 120000:
            raise ValueError("evidence_size_limit")
        return self


class SLMObservation(Wire):
    text: str = Field(min_length=1, max_length=3000)
    evidence_ids: list[str] = Field(max_length=64)


class SLMCaseFinding(Wire):
    outcome: Literal["scam", "likely_scam", "unlikely_scam", "not_scam"]
    explanation: str = Field(min_length=1, max_length=3000)
    reasons: list[SLMObservation] = Field(min_length=1, max_length=12)
    uncertainty: str | None = Field(default=None, max_length=1500)
    advice: str | None = Field(default=None, max_length=1500)


class SLMEscalationAssessment(Wire):
    decision: Literal["proceed_local", "escalate", "additional_evidence_required"]
    rationale: str = Field(min_length=1, max_length=3000)
    evidence_ids: list[str] = Field(min_length=1, max_length=64)
    material_gaps: list[str] = Field(max_length=12)


class SLMReasoningAnswer(Wire):
    observations: list[SLMObservation] = Field(max_length=24)
    contradictions: list[SLMObservation] = Field(max_length=24)
    alternative_explanations: list[SLMObservation] = Field(max_length=24)
    verification_suggestions: list[SLMObservation] = Field(max_length=24)
    draft_explanation: str | None = Field(default=None, max_length=3000)
    case_finding: SLMCaseFinding | None = None
    escalation_assessment: SLMEscalationAssessment | None = None
    wright_semantic: WrightSemanticResult | None = None


class SLMReasoningResult(Wire):
    case_id: str = Field(min_length=4, max_length=80)
    case_revision: int = Field(ge=0)
    request_id: str = Field(min_length=4, max_length=80)
    execution: Literal["on_device"]
    model_id: str = Field(min_length=1, max_length=160)
    answer: SLMReasoningAnswer


def accept_advisory_reasoning(
    request: SLMReasoningRequest, result: SLMReasoningResult
) -> SLMReasoningAnswer:
    """Validate correlation and citations; never create case evidence or a verdict.

    Caller MUST separately authenticate the owner, enforce the actual case/job
    revision, verify the outstanding device request/expiry, and establish the
    model's on-device provenance. Client-supplied 'on_device' alone is not proof.
    """
    if (request.case_id, request.case_revision, request.request_id) != (
        result.case_id, result.case_revision, result.request_id
    ):
        raise ValueError("slm_request_mismatch")
    permitted = {row.evidence_id for row in request.evidence}
    if request.operation != "case_finding" and result.answer.case_finding is not None:
        raise ValueError("unexpected_case_finding")
    if request.operation != "escalation_assessment" and result.answer.escalation_assessment is not None:
        raise ValueError("unexpected_escalation_assessment")
    for group in (
        result.answer.observations,
        result.answer.contradictions,
        result.answer.alternative_explanations,
        result.answer.verification_suggestions,
        result.answer.case_finding.reasons if result.answer.case_finding else [],
    ):
        for observation in group:
            if len(set(observation.evidence_ids)) != len(observation.evidence_ids):
                raise ValueError("duplicate_slm_citation")
            if any(evidence_id not in permitted for evidence_id in observation.evidence_ids):
                raise ValueError("unrecognised_slm_evidence")
    if request.operation == "wright_semantic":
        if request.role != "wright_triage" or result.answer.wright_semantic is None:
            raise ValueError("missing_wright_semantic")
        if any((result.answer.observations, result.answer.contradictions,
                result.answer.alternative_explanations, result.answer.verification_suggestions)) or result.answer.case_finding or result.answer.escalation_assessment:
            raise ValueError("wright_semantic_must_not_author_verdict")
        validate_wright_semantic(result.answer.wright_semantic.model_dump(by_alias=False), permitted)
    if request.operation == "escalation_assessment":
        assessment = result.answer.escalation_assessment
        if assessment is None or any(eid not in permitted for eid in assessment.evidence_ids):
            raise ValueError("invalid_escalation_assessment")
        if assessment.decision == "proceed_local" and assessment.material_gaps:
            raise ValueError("unresolved_material_gaps")
    if request.operation == "case_finding" and result.answer.case_finding is None:
        raise ValueError("missing_case_finding")
    if request.operation == "case_finding" and any(
        not reason.evidence_ids for reason in result.answer.case_finding.reasons
    ):
        raise ValueError("uncited_case_finding_reason")
    return result.answer
