from datetime import datetime, timezone

from services.verified_businesses import (
    BusinessSource,
    VerifiedBusiness,
    approved_logo_for_number,
    business_caller_presentation,
    is_au_13_1300_1800,
)

NOW = datetime.now(timezone.utc)


def record(*, official_number=True, brand=True):
    sources = [
        BusinessSource(provider="abn_lookup", reference="ABN record", checked_at=NOW, supports="registration"),
        BusinessSource(provider="official_business_site", reference="https://example.com/contact", checked_at=NOW, supports="number_association"),
    ]
    if brand:
        sources.append(BusinessSource(provider="brandfetch", reference="example.com", checked_at=NOW, supports="brand_asset"))
    return VerifiedBusiness(
        business_id="example", legal_name="Example Pty Ltd", abn="12345678901",
        abn_registration_confirmed=True, official_domain="example.com",
        published_numbers=["1300 123 456"] if official_number else [],
        logo_url="https://cdn.example.com/logo.png", logo_domain_confirmed=True,
        sources=sources, last_reviewed_at=NOW,
    )


def test_logo_requires_published_number_and_brand_provenance():
    assert approved_logo_for_number(record(), "1300 123 456")
    assert approved_logo_for_number(record(), "1300 999 999") is None
    assert approved_logo_for_number(record(brand=False), "1300 123 456") is None


def test_logo_requires_registration_confirmation():
    business = record()
    business.abn_registration_confirmed = False
    assert approved_logo_for_number(business, "1300 123 456") is None


def test_special_service_numbers_do_not_prove_caller_identity():
    assert is_au_13_1300_1800("13 12 34")
    assert is_au_13_1300_1800("1300 123 456")
    assert is_au_13_1300_1800("1800 123 456")
    result = business_caller_presentation(record(), "1300 123 456")
    assert result.special_service_number
    assert result.number_published_by_business
    assert not result.caller_authenticated
    assert result.spoofing_possible


def test_logo_rejected_for_different_calling_number():
    business = record()
    assert approved_logo_for_number(business, "1300 987 654") is None


def test_logo_is_display_only_even_for_matching_number():
    presentation = business_caller_presentation(record(), "1300 123 456")
    assert presentation.logo_url is not None
    assert presentation.caller_authenticated is False
    assert presentation.spoofing_possible is True
