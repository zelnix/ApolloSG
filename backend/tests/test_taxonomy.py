"""Master Scam Taxonomy — services.higgins.tc_flyby.taxonomy (Apollo PRD v2.2 Phase 2).

Covers: the eight master domains and their exact Operational Variant Code ranges, KB pattern ->
domain mapping, decisive-mechanism -> domain mapping, consequential-request-type fallback
classification, cross-domain (secondary domain) tagging, and the "nothing to classify" case.
"""
from services.higgins.tc_flyby import taxonomy
from services.higgins.tc_flyby.finding_rules import IPDMCChecks
from services.higgins.tc_flyby.triage import Entities, Plan


def _plan(**over) -> Plan:
    base = dict(checks=[], has_message=True, link_only=False, general=False, gaps=[], advisories=[],
               pattern=None, channel="sms", entities=Entities(), message_type="general")
    base.update(over)
    return Plan(**base)


class TestMasterDomains:
    """The eight approved master domains, with their exact PRD v2.2 code ranges, in order."""

    def test_exactly_eight_domains(self):
        assert len(taxonomy.MASTER_DOMAINS) == 8

    def test_ranges_are_exactly_as_specified_and_cover_001_to_1000_with_no_gaps_or_overlaps(self):
        expected = [
            (1, "Account Takeover & Authentication Exploitation", 1, 125),
            (2, "Brand & Corporate Impersonation", 126, 275),
            (3, "Financial, Investment & Cryptocurrency Fraud", 276, 425),
            (4, "Social Engineering & Relationship Exploitation", 426, 575),
            (5, "Retail, E-Commerce & Employment", 576, 725),
            (6, "Cyber Extortion & Threats", 726, 825),
            (7, "Government, Tax & Legal Impersonation", 826, 925),
            (8, "Real Estate, Rental & Credit Fraud", 926, 1000),
        ]
        for domain, (code, name, start, end) in zip(taxonomy.MASTER_DOMAINS, expected):
            assert domain["code"] == code
            assert domain["name"] == name
            assert domain["range"] == [start, end]

    def test_no_two_named_kb_patterns_share_a_variant_code(self):
        codes = [v[0]["variantCode"] for v in taxonomy._PATTERN_MAP.values()]
        assert len(codes) == len(set(codes))

    def test_pattern_and_mechanism_variant_codes_stay_within_their_domains_range(self):
        by_code = {d["code"]: d["range"] for d in taxonomy.MASTER_DOMAINS}
        for variant, _ in taxonomy._PATTERN_MAP.values():
            start, end = by_code[variant["domainCode"]]
            assert start <= int(variant["variantCode"]) <= end
        for _, variant, _ in taxonomy._MECHANISM_MAP:
            start, end = by_code[variant["domainCode"]]
            assert start <= int(variant["variantCode"]) <= end


class TestPatternBasedClassification:
    """Existing KB scam patterns map into the eight domains as subcategories, preserving the
    pattern's own identity (nothing about the KB record itself changes)."""

    def test_otp_bypass_pattern_classifies_as_account_takeover(self):
        plan = _plan(pattern={"key": "otp_bypass", "stage": "full"})
        result = taxonomy.classify(plan, IPDMCChecks(), None)
        assert result["primary"]["domainCode"] == 1
        assert result["primary"]["domainName"] == "Account Takeover & Authentication Exploitation"

    def test_government_threat_pattern_classifies_as_government_impersonation(self):
        plan = _plan(pattern={"key": "government_threat", "stage": "full"})
        result = taxonomy.classify(plan, IPDMCChecks(), None)
        assert result["primary"]["domainCode"] == 7

    def test_investment_returns_pattern_classifies_as_financial_fraud(self):
        plan = _plan(pattern={"key": "investment_returns", "stage": "full"})
        result = taxonomy.classify(plan, IPDMCChecks(), None)
        assert result["primary"]["domainCode"] == 3

    def test_family_new_number_pattern_classifies_as_social_engineering(self):
        plan = _plan(pattern={"key": "family_new_number", "stage": "opening"})
        result = taxonomy.classify(plan, IPDMCChecks(), None)
        assert result["primary"]["domainCode"] == 4

    def test_job_task_pattern_classifies_as_retail_ecommerce_employment(self):
        plan = _plan(pattern={"key": "job_task", "stage": "full"})
        result = taxonomy.classify(plan, IPDMCChecks(), None)
        assert result["primary"]["domainCode"] == 5

    def test_bank_code_call_pattern_tags_brand_impersonation_as_secondary(self):
        plan = _plan(pattern={"key": "bank_code_call", "stage": "full"})
        result = taxonomy.classify(plan, IPDMCChecks(), None)
        assert result["primary"]["domainCode"] == 1
        assert {d["domainCode"] for d in result["secondaryDomains"]} == {2}

    def test_unknown_pattern_key_falls_through_to_other_classification(self):
        plan = _plan(pattern={"key": "some_future_pattern", "stage": "full"})
        result = taxonomy.classify(plan, IPDMCChecks(identity_is_false=True), None)
        # Falls through the (unmapped) pattern branch to the identity_is_false fallback.
        assert result["primary"]["domainCode"] == 2


class TestDecisiveMechanismClassification:
    """scoring._decisive_mechanism()'s established critical exploit mechanisms map to a domain even
    when there's no KB pattern match at all."""

    def test_otp_credential_harvesting_mechanism_is_account_takeover_with_brand_secondary(self):
        plan = _plan()
        mechanism = "OTP, password or account-credential harvesting through a falsified identity or domain"
        result = taxonomy.classify(plan, IPDMCChecks(), mechanism)
        assert result["primary"]["domainCode"] == 1
        assert {d["domainCode"] for d in result["secondaryDomains"]} == {2}

    def test_wallet_exploitation_mechanism_is_financial_crypto_fraud_with_account_takeover_secondary(self):
        plan = _plan()
        result = taxonomy.classify(plan, IPDMCChecks(), "Wallet or recovery-phrase exploitation")
        assert result["primary"]["domainCode"] == 3
        assert {d["domainCode"] for d in result["secondaryDomains"]} == {1}

    def test_extortion_mechanism_is_cyber_extortion_and_threats(self):
        plan = _plan()
        result = taxonomy.classify(plan, IPDMCChecks(), "Extortion or ransomware demand")
        assert result["primary"]["domainCode"] == 6
        assert result["secondaryDomains"] == []


class TestRequestTypeFallbackClassification:
    """With no pattern and no decisive mechanism, a consequential request's own type still places
    the case in the right domain (the CONSEQUENTIAL request-type vocabulary, triage.CONSEQUENTIAL)."""

    def test_credentials_request_alone_classifies_as_account_takeover(self):
        plan = _plan()
        ipdmc = IPDMCChecks(consequential_requests=[{"type": "credentials", "quote": "verify your account"}])
        result = taxonomy.classify(plan, ipdmc, None)
        assert result["primary"]["domainCode"] == 1

    def test_gift_cards_crypto_request_classifies_as_financial_fraud(self):
        plan = _plan()
        ipdmc = IPDMCChecks(consequential_requests=[{"type": "gift_cards_crypto", "quote": "buy a $200 gift card"}])
        result = taxonomy.classify(plan, ipdmc, None)
        assert result["primary"]["domainCode"] == 3

    def test_payment_request_with_impersonation_tags_brand_as_secondary(self):
        plan = _plan()
        ipdmc = IPDMCChecks(consequential_requests=[{"type": "payment", "quote": "pay the toll fee"}], has_impersonation=True)
        result = taxonomy.classify(plan, ipdmc, None)
        assert result["primary"]["domainCode"] == 3
        assert {d["domainCode"] for d in result["secondaryDomains"]} == {2}

    def test_unrecognised_request_type_does_not_classify_by_request(self):
        plan = _plan()
        ipdmc = IPDMCChecks(consequential_requests=[{"type": "call_back", "quote": "call us now"}])
        assert taxonomy.classify(plan, ipdmc, None) is None


class TestFallbacksAndNoClassification:
    def test_impersonation_alone_classifies_as_brand_impersonation(self):
        plan = _plan()
        result = taxonomy.classify(plan, IPDMCChecks(has_impersonation=True), None)
        assert result["primary"]["domainCode"] == 2
        assert result["secondaryDomains"] == []

    def test_nothing_established_returns_none(self):
        plan = _plan()
        assert taxonomy.classify(plan, IPDMCChecks(), None) is None
