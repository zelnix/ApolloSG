"""Conservative Call Gate spoofing signals. No carrier-origin inference from metadata.

This module does not score, block, or authenticate calls. It supplies transparent
evidence to the existing caller identity pipeline and Higgins presentation.
"""
from __future__ import annotations

import re
from typing import Literal
from pydantic import BaseModel, Field

Attestation = Literal["passed", "failed", "not_verified", "unavailable"]


class SpoofSignal(BaseModel):
    code: str
    severity: Literal["information", "caution", "high"]
    explanation: str


class SpoofAssessment(BaseModel):
    signals: list[SpoofSignal] = Field(default_factory=list)
    caller_authenticated: bool = False
    suppress_business_logo: bool = False
    network_attestation: Attestation = "unavailable"


def assess_spoof_signals(
    *, calling_number: str, number_valid: bool | None = None,
    business_number_associated: bool = False,
    business_identity_conflict: bool = False,
    network_attestation: Attestation = "unavailable",
    own_number: str | None = None,
) -> SpoofAssessment:
    signals: list[SpoofSignal] = []
    digits = re.sub(r"\D", "", calling_number)
    if number_valid is False:
        signals.append(SpoofSignal(
            code="invalid_number", severity="high",
            explanation="The displayed number failed structural validation; its origin cannot be established."
        ))
    if business_identity_conflict:
        signals.append(SpoofSignal(
            code="business_identity_conflict", severity="high",
            explanation="The displayed number's reviewed business association conflicts with other caller identity information."
        ))
    if own_number and digits and digits == re.sub(r"\D", "", own_number):
        signals.append(SpoofSignal(
            code="self_number", severity="high",
            explanation="The displayed calling number matches your own number. Caller ID may have been manipulated."
        ))
    if network_attestation == "failed":
        signals.append(SpoofSignal(
            code="carrier_verification_failed", severity="high",
            explanation="Android reports that carrier calling-number verification failed; this is a spoofing warning, not proof of fraud."
        ))
    elif network_attestation == "passed":
        signals.append(SpoofSignal(
            code="carrier_verification_passed", severity="information",
            explanation="Android reports calling-number verification passed; this does not authenticate the business or person."
        ))
    if business_number_associated and not signals:
        signals.append(SpoofSignal(
            code="published_business_number", severity="information",
            explanation="The number is associated with a business, but this call's origin is not authenticated."
        ))
    return SpoofAssessment(
        signals=signals,
        network_attestation=network_attestation,
        suppress_business_logo=any(s.severity == "high" for s in signals),
    )
