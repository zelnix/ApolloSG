"""Service failures identify the function and recorded target, without altering technical records."""
from copy import deepcopy
import pytest
from services.triage.completeness import incomplete_plain, service_function, plain_service_text


@pytest.mark.parametrize("source,check,expected", [
    ("spamhaus_drop", "reputation", "Internet address validation"),
    ("Spamhaus DROP", "reputation", "Internet address validation"),
    ("google_web_risk", "reputation", "Website threat checking"),
    ("IPQualityScore", "number_reputation", "Phone number validation"),
    (None, "sender_authentication", "Email sender authentication"),
])
def test_service_function_names(source, check, expected):
    assert service_function(source, check) == expected


def test_recorded_failure_function_and_target_are_projected_without_mutation():
    record = {"check": "reputation", "status": "unavailable", "failure": "quota_exhausted",
              "source": "spamhaus_drop", "subject": "https://one.example/path?token=private", "detail": "Raw diagnostic"}
    before = deepcopy(record)
    text = incomplete_plain(record)
    assert "Internet address validation for one.example" in text
    assert "allowance is used up" in text
    assert "Spamhaus" not in text and "token=private" not in text
    assert record == before


def test_source_brand_names_are_not_globally_rewritten():
    assert plain_service_text("Google security alert: Spamhaus DROP couldn't find its IP address.") == (
        "Google security alert: Internet address validation couldn't find its internet address.")
