"""Phase 4 Wright semantic contract. Pure, advisory, evidence-cited; not a verdict.
No endpoint, model invocation, persistence, or new investigator is created.
"""
from __future__ import annotations
from typing import Literal
from pydantic import Field, ConfigDict, model_validator
from services.higgins.contracts import Wire

Exposure = Literal["CONFIRMED", "NOT_CONFIRMED", "UNKNOWN"]


class WrightExposure(Wire):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    payment: Exposure
    credentials: Exposure
    identity: Exposure
    remote_access: Exposure


class WrightSemanticResult(Wire):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    version: Literal["wright.semantic.v1"]
    classification: Literal["scam_indicators", "legitimate_context", "ambiguous", "insufficient_evidence"]
    scam_types: list[str] = Field(max_length=6)
    intent: str = Field(min_length=1, max_length=400)
    coercion: Literal["present", "absent", "uncertain"]
    exposure: WrightExposure
    narrative: str = Field(min_length=1, max_length=1200)
    uncertainty: str | None = Field(default=None, max_length=600)
    supporting_evidence_ids: list[str] = Field(max_length=32)

    @model_validator(mode="after")
    def check_shape(self):
        if any(not s.strip() or len(s) > 60 for s in self.scam_types):
            raise ValueError("invalid_scam_type")
        if len(set(self.scam_types)) != len(self.scam_types):
            raise ValueError("duplicate_scam_type")
        if len(set(self.supporting_evidence_ids)) != len(self.supporting_evidence_ids):
            raise ValueError("duplicate_semantic_citation")
        if (self.classification in ("scam_indicators", "legitimate_context")
                or self.coercion == "present"
                or "CONFIRMED" in (self.exposure.payment, self.exposure.credentials,
                                    self.exposure.identity, self.exposure.remote_access)):
            if not self.supporting_evidence_ids:
                raise ValueError("uncited_semantic_assertion")
        return self


def validate_wright_semantic(value: dict, allowed_evidence_ids: set[str]) -> WrightSemanticResult:
    result = WrightSemanticResult.model_validate(value)
    if not set(result.supporting_evidence_ids).issubset(allowed_evidence_ids):
        raise ValueError("unrecognised_wright_evidence")
    return result
