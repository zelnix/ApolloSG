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

SLMRole = Literal["higgins_triage", "tc_hawkeye", "magnum_di", "luddish"]
SLMOperation = Literal["investigation_readiness", "evidence_reasoning", "explanation"]


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


class SLMReasoningAnswer(Wire):
    observations: list[SLMObservation] = Field(max_length=24)
    contradictions: list[SLMObservation] = Field(max_length=24)
    alternative_explanations: list[SLMObservation] = Field(max_length=24)
    verification_suggestions: list[SLMObservation] = Field(max_length=24)
    draft_explanation: str | None = Field(default=None, max_length=3000)


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
    for group in (
        result.answer.observations,
        result.answer.contradictions,
        result.answer.alternative_explanations,
        result.answer.verification_suggestions,
    ):
        for observation in group:
            if len(set(observation.evidence_ids)) != len(observation.evidence_ids):
                raise ValueError("duplicate_slm_citation")
            if any(evidence_id not in permitted for evidence_id in observation.evidence_ids):
                raise ValueError("unrecognised_slm_evidence")
    return result.answer
