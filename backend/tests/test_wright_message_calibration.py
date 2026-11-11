"""Paired benign/scam cases for calibrated Wright message rules."""
import pytest
from services.triage.contract import RuleResult
from services.triage.engine import _message_rules

@pytest.mark.parametrize("rule_id,signals,extra,expected", [
    ("MSG-06", {"remote_access": True}, {}, RuleResult.NOT_MET),
    ("MSG-06", {"remote_access": True, "login_request": True}, {}, RuleResult.MET),
    ("MSG-07", {"install_request": True}, {}, RuleResult.NOT_MET),
    ("MSG-07", {"install_request": True, "code_request": True}, {}, RuleResult.MET),
    ("MSG-16", {"job_offer": True, "payment_request": True}, {}, RuleResult.NOT_MET),
    ("MSG-16", {"job_offer": True, "identity_request": True}, {}, RuleResult.MET),
    ("MSG-19", {"platform_switch": True, "job_offer": True}, {}, RuleResult.NOT_MET),
    ("MSG-19", {"platform_switch": True, "code_request": True}, {}, RuleResult.MET),
    ("PAY-01", {"instant_payment": True, "claimed_brand": "Example"}, {}, RuleResult.NOT_MET),
    ("PAY-01", {"instant_payment": True, "claimed_brand": "Example"}, {"brand_mismatch": True}, RuleResult.MET),
    ("PAY-02", {"instant_payment": True, "urgency": True, "unknown_sender": True}, {}, RuleResult.NOT_MET),
    ("PAY-02", {"instant_payment": True, "urgency": True, "unknown_sender": True},
     {"deceptive_destination": True}, RuleResult.MET),
    ("MSG-22", {"payment_request": True, "urgency": True, "unknown_sender": True}, {}, RuleResult.NOT_MET),
    ("MSG-22", {"payment_request": True, "urgency": True, "unknown_sender": True},
     {"brand_mismatch": True}, RuleResult.MET),
])
def test_calibrated_message_rules(rule_id, signals, extra, expected):
    result = _message_rules()[rule_id]({"signals": signals, **extra})
    assert result[0] is expected
