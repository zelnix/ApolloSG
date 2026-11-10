"""Regression tests for Higgins Triage evidence sufficiency (not scam classification)."""
from services.higgins.triage_readiness import background_text_ready


def test_benign_social_message_not_ready():
    result = background_text_ready("Dinner at 6 tonight", sender="Mum")
    assert not result.ready


def test_sender_alone_is_not_evidence():
    assert not background_text_ready("Hello", sender="+61400000000").ready


def test_empty_message_not_ready():
    assert not background_text_ready("  ").ready


def test_link_is_investigable_even_without_prior_threat_verdict():
    assert background_text_ready("Please check https://example.com/login").ready


def test_actionable_credentials_request_is_investigable():
    assert background_text_ready("Reply with the 6-digit verification code to unlock your account").ready


def test_payment_request_is_investigable():
    assert background_text_ready("Please send payment to our new bank account").ready


def test_truncated_message_retains_investigable_evidence():
    assert background_text_ready("Visit https://example.com now", content_complete=False).ready


def test_unrelated_short_message_not_ready():
    assert not background_text_ready("See you soon").ready
