"""Australian Call Gate number checks must not equate number association with authentication."""
from datetime import datetime, timezone
from services.verified_businesses import (
    VerifiedBusiness, _digits, is_au_13_1300_1800, business_caller_presentation,
)
from services.call_spoof_signals import assess_spoof_signals


def test_au_number_formats_normalize_to_same_key():
    assert _digits("0412 345 678") == _digits("+61 412 345 678")
    assert _digits("13 22 00") == _digits("+61 13 22 00")


def test_special_service_numbers_are_not_automatically_spoofed():
    for number in ("13 22 00", "+61 13 22 00", "1300 123 456", "1800 123 456"):
        assert is_au_13_1300_1800(number)
        assessment = assess_spoof_signals(calling_number=number)
        assert not assessment.suppress_business_logo
        assert not any(signal.severity == "high" for signal in assessment.signals)


def test_reviewed_cli_restriction_is_caution_not_proof():
    assessment = assess_spoof_signals(calling_number="+61132200", cli_presentation_restricted=True)
    assert assessment.signals[0].code == "restricted_cli_presentation"
    assert assessment.signals[0].severity == "caution"


def test_business_callback_is_never_inferred_from_displayed_cli():
    business = VerifiedBusiness(
        business_id="test", legal_name="Example Pty Ltd", official_domain="example.com",
        published_numbers=["13 22 00"], official_contact_url="https://example.com/contact",
        last_reviewed_at=datetime.now(timezone.utc),
    )
    presented = business_caller_presentation(business, "+61132200")
    assert presented.number_published_by_business
    assert presented.official_contact_url == "https://example.com/contact"
    assert presented.independently_verified_callback_number is None
    assert not presented.caller_authenticated
