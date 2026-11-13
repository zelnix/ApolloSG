"""Number facts and missing ownership must not authenticate an incoming caller."""
from services.phone_identity import (
    PhoneIdentityResult, PrefixIntelligenceTier, _unknown_caller_guidance, _refresh_unknown_guidance)


def test_unknown_landline_does_not_recommend_callback_to_unverified_caller_id():
    guidance = " ".join(_unknown_caller_guidance(
        "+61299363990", {"number_type": "Landline", "country_code": "AU"}, None, None))
    assert "official website" in guidance
    assert "Do not use the incoming caller ID as a trusted callback number" in guidance
    assert "Caller ID can be spoofed for landlines and mobiles" in guidance
    assert "harder to spoof" not in guidance
    assert "try calling the number back" not in guidance


def test_number_block_match_does_not_authenticate_the_exact_number_or_caller():
    block = PrefixIntelligenceTier(
        tier="number_block", description="Range association", entity="Example Organisation",
        qualifier="possible association", confidence="low", prefix="+61299", detail=None)
    guidance = " ".join(_unknown_caller_guidance(
        "+61299363990", {"number_type": "Landline", "country_code": "AU"}, None, block))
    assert "does not verify the owner of this exact number or authenticate the caller" in guidance
    assert "legitimate call" not in guidance


def test_cached_result_gets_current_advice_without_changing_evidence_or_freshness():
    result = PhoneIdentityResult(
        canonical="+61299363990", original="0299363990", valid=True,
        association_confidence="unknown", checked_at="2026-11-13T11:17:00Z", freshness="cached",
        prefix_intelligence=[PrefixIntelligenceTier(
            tier="caller", description="Recorded owner not identified", entity=None, qualifier="unknown",
            confidence="low", prefix="+61299363990", detail="Recorded lookup checked two sources.",
            business_units=["You can try calling the number back", "Landlines are harder to spoof"],
        )])
    before = result.model_dump()
    _refresh_unknown_guidance(result)
    after = result.model_dump()
    assert "official website" in " ".join(result.prefix_intelligence[0].business_units)
    assert "try calling the number back" not in " ".join(result.prefix_intelligence[0].business_units)
    # Advice is presentation, not a new check or a change to the recorded facts.
    before["prefix_intelligence"][0]["business_units"] = after["prefix_intelligence"][0]["business_units"]
    assert after == before
