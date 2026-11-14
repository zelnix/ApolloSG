"""Wright admits readable source evidence only; it has no Finding authority."""
from typing import Literal
from pydantic import ConfigDict, Field, model_validator
from services.higgins.contracts import Wire


class WrightReadinessItem(Wire):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    evidence_id: str = Field(min_length=1, max_length=80)
    availability: Literal["readable", "unreadable", "inventory_only"]


class WrightReadinessResult(Wire):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    version: Literal["wright.readiness.v1"]
    evidence: list[WrightReadinessItem] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def unique_items(self):
        ids = [item.evidence_id for item in self.evidence]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate_readiness_evidence")
        return self

    @property
    def has_readable_evidence(self) -> bool:
        return any(item.availability == "readable" for item in self.evidence)


def validate_wright_readiness(value: dict, representations: dict[str, str]) -> WrightReadinessResult:
    result = WrightReadinessResult.model_validate(value)
    if {item.evidence_id for item in result.evidence} != set(representations):
        raise ValueError("readiness_evidence_inventory_mismatch")
    for item in result.evidence:
        inventory_only = representations[item.evidence_id] == "inventory_only"
        if inventory_only != (item.availability == "inventory_only"):
            raise ValueError("readiness_representation_mismatch")
    return result
