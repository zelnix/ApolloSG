"""Regression checks for Wright Triage's corroboration-gated message rules.

These tests exercise the existing rule evaluator directly; they do not replace
end-to-end device, specialist-provider or SLM acceptance testing.
"""
from services.triage.engine import _message_rules
from services.triage.contract import RuleResult


def _result(rule_id, evidence):
    return _message_rules()[rule_id](evidence)[0]


def test_ordinary_invoice_deadline_unknown_sender_does_not_form_scam_pattern():
    evidence = {"signals": {
        "payment_request": True, "urgency": True, "unknown_sender": True,
    }}
    assert _result("MSG-22", evidence) == RuleResult.NOT_MET


def test_ordinary_job_recruitment_payment_reference_does_not_form_scam_pattern():
    evidence = {"signals": {
        "job_offer": True, "payment_request": True,
        "platform_switch": True, "unknown_sender": True,
    }}
    assert _result("MSG-22", evidence) == RuleResult.NOT_MET


def test_correlated_deceptive_payment_lure_still_matches():
    evidence = {
        "signals": {"payment_request": True, "urgency": True, "unknown_sender": True},
        "brand_mismatch": True,
    }
    assert _result("MSG-22", evidence) == RuleResult.MET


def test_identity_request_with_unknown_sender_only_is_not_impersonation():
    evidence = {"signals": {"identity_request": True, "unknown_sender": True}}
    assert _result("MSG-18", evidence) == RuleResult.NOT_MET


def test_identity_request_with_verified_deceptive_destination_matches():
    evidence = {
        "signals": {"identity_request": True},
        "deceptive_destination": True,
    }
    assert _result("MSG-18", evidence) == RuleResult.MET
