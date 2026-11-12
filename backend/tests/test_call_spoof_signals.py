from services.call_spoof_signals import assess_spoof_signals


def test_business_association_is_not_caller_authentication():
    result = assess_spoof_signals(calling_number="+61132200", business_number_associated=True)
    assert not result.caller_authenticated
    assert not result.suppress_business_logo


def test_conflicting_business_identity_suppresses_logo():
    result = assess_spoof_signals(calling_number="+61132200", business_identity_conflict=True)
    assert result.suppress_business_logo
    assert result.signals[0].code == "business_identity_conflict"


def test_carrier_failure_is_high_risk_not_confirmed_fraud():
    result = assess_spoof_signals(calling_number="+61412345678", network_attestation="failed")
    assert result.suppress_business_logo
    assert result.signals[0].code == "carrier_verification_failed"
    assert not result.caller_authenticated


def test_passed_attestation_does_not_authenticate_business():
    result = assess_spoof_signals(calling_number="+61412345678", network_attestation="passed")
    assert not result.caller_authenticated
    assert not result.suppress_business_logo


def test_invalid_number_is_flagged_without_blocking():
    result = assess_spoof_signals(calling_number="123", number_valid=False)
    assert result.suppress_business_logo
    assert result.signals[0].code == "invalid_number"
