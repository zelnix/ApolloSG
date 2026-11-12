"""Evidence-gated business identity registry for Call Gate.

Brandfetch supplies branding, ABN Lookup supplies Australian entity-registration facts,
Twilio Lookup v2 supplies number metadata and optional risk signals. None authenticates
the person placing an incoming call. Provider calls/credentials belong in server-side
adapters; this module deliberately does not guess endpoints or fabricate provider results.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl

Provider = Literal["abn_lookup", "official_business_site", "brandfetch", "twilio_lookup_v2", "acma_rule"]


class BusinessSource(BaseModel):
    provider: Provider
    reference: str = Field(min_length=1)
    checked_at: datetime
    supports: Literal["registration", "number_association", "brand_asset", "number_metadata", "risk_signal"]


class VerifiedBusiness(BaseModel):
    """Curated registry record. A record is not proof of an individual caller's identity."""
    business_id: str
    legal_name: str
    abn: Optional[str] = None
    abn_registration_confirmed: bool = False
    trading_name: Optional[str] = None
    official_domain: Optional[str] = None
    published_numbers: list[str] = Field(default_factory=list)
    logo_url: Optional[HttpUrl] = None
    logo_domain_confirmed: bool = False
    sources: list[BusinessSource] = Field(default_factory=list)
    last_reviewed_at: datetime


def _digits(number: str) -> str:
    return re.sub(r"\D", "", number)


def is_au_13_1300_1800(number: str) -> bool:
    """AU special-service number classification only; NOT a spoofing determination."""
    digits = _digits(number)
    if digits.startswith("61"):
        digits = "0" + digits[2:]
    return bool(re.fullmatch(r"13\d{4}|1300\d{6}|1800\d{6}", digits))


def approved_logo_for_number(business: VerifiedBusiness, number: str) -> Optional[str]:
    """Never expose a logo merely because a company exists or a provider returned artwork."""
    if not (business.abn_registration_confirmed and business.logo_domain_confirmed):
        return None
    source_types = {(s.provider, s.supports) for s in business.sources}
    if ("abn_lookup", "registration") not in source_types:
        return None
    if ("brandfetch", "brand_asset") not in source_types:
        return None
    if ("official_business_site", "number_association") not in source_types:
        return None
    if not business.official_domain or not business.logo_url:
        return None
    if _digits(number) not in {_digits(n) for n in business.published_numbers}:
        return None
    return str(business.logo_url)


class BusinessCallerPresentation(BaseModel):
    business_name: Optional[str] = None
    logo_url: Optional[str] = None
    number_published_by_business: bool = False
    caller_authenticated: bool = False
    spoofing_possible: bool = True
    special_service_number: bool = False


def business_caller_presentation(business: VerifiedBusiness, number: str) -> BusinessCallerPresentation:
    logo = approved_logo_for_number(business, number)
    associated = _digits(number) in {_digits(n) for n in business.published_numbers}
    return BusinessCallerPresentation(
        business_name=business.trading_name or business.legal_name if associated else None,
        logo_url=logo,
        number_published_by_business=associated,
        special_service_number=is_au_13_1300_1800(number),
    )
