"""Regression checks for legitimate and deceptive email indicators in Wright Triage."""
from services.triage.contract import RuleResult
from services.triage.engine import _email_rules


def result(rule_id, **evidence):
    return _email_rules()[rule_id](evidence)[0]


def test_forwarded_invoice_auth_failure_not_threat_by_itself():
    assert result("EMAIL-11", auth_results={"spf": "fail"},
                  consequential_action=True) == RuleResult.NOT_MET


def test_failed_auth_plus_verified_impersonation_still_flags():
    assert result("EMAIL-11", auth_results={"spf": "fail"},
                  consequential_action=True, sender_domain_mismatch=True) == RuleResult.MET


def test_freemail_sender_requires_verified_organisation_mismatch():
    evidence = {"sender_domain": "gmail.com", "claimed_brand": "Local Club",
                "consequential_action": True}
    assert result("EMAIL-02", **evidence) == RuleResult.NOT_MET
    assert result("EMAIL-02", **evidence, sender_domain_mismatch=True) == RuleResult.MET


def test_email_anomalies_without_deception_do_not_form_scam_pattern():
    evidence = {"auth_results": {"spf": "fail"}, "reply_to_mismatch": True,
                "consequential_action": True}
    assert result("EMAIL-13", **evidence) == RuleResult.NOT_MET


def test_verified_deception_and_independent_anomaly_still_flags():
    evidence = {"auth_results": {"spf": "fail"}, "sender_domain_mismatch": True,
                "consequential_action": True}
    assert result("EMAIL-13", **evidence) == RuleResult.MET


def test_security_alert_same_display_and_actual_host_is_not_mismatch():
    evidence = {"security_alert": True, "claimed_brand": "Example",
                "displayed_host": "example.com", "actual_host": "example.com"}
    assert result("EMAIL-03", **evidence) == RuleResult.NOT_MET
