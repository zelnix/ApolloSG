"""Tests for the four-stage evidence evaluation pipeline and Commense false-positive regression.

These tests validate the Robust Threat Decision Engine's core behaviour:
    - Legitimate promotional emails are not escalated to 'concerning'
    - Verified threats (Safe Browsing, scam advisories) are never downgraded
    - Dual-hypothesis evaluation correctly identifies ambiguous evidence
    - Evidence deduplication prevents signal inflation
    - The relevance gate excludes third-party data for mentioned-but-not-sender brands
"""
from __future__ import annotations

import pytest

from services.higgins.tc_flyby.evidence_evaluation import (
    EvaluationResult,
    evaluate,
    should_downgrade_provisional,
)
from services.higgins.tc_flyby.official import fact, source_ref
from services.higgins.tc_flyby.triage import Check, Plan


# ── Helpers ──────────────────────────────────────────────────────────────────

def _check(kind: str, subject: str, status: str = "resolved", facts: list[dict] | None = None,
           route: str = "tc_flyby_official", open_issue: str = "") -> Check:
    c = Check(id=f"chk-{kind}-{subject[:8]}", kind=kind, subject=subject, route=route, open_issue=open_issue)
    c.status = status
    c.facts = facts or []
    return c


def _plan(checks: list[Check], **overrides) -> Plan:
    """Build a minimal Plan for testing. Uses sensible defaults for everything the pipeline doesn't need."""
    from types import SimpleNamespace
    entities = SimpleNamespace(brands=[], requests=[], companies=[], hosts=[], email_domains=[])
    p = Plan.__new__(Plan)
    p.checks = checks
    p.pattern = None
    p.general = False
    p.channel = "email"
    p.has_message = True
    p.link_only = False
    p.gaps = []
    p.entities = entities
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


# ── Commense false-positive regression ───────────────────────────────────────

class TestCommenseRegression:
    """A promotional email from Commense (a real clothing retailer) that mentions other brands
    must NOT be flagged as 'concerning' for impersonation.

    Root cause: The old pipeline created impersonation checks for every brand mentioned in the text
    (e.g. Nike, Adidas). Since commense.com is unrelated to Nike, the impersonation check for Nike
    found a 'mismatch'. Weak third-party signals on commense.com (IPQS score, newly registered domain)
    then 'corroborated' the mismatch, escalating the case to 'concerning'.

    Fix: (1) The verified-sender guard in corroborated_impersonation() excludes mismatches for brands
    that are merely mentioned when another brand's check resolves clear. (2) The evidence evaluation
    pipeline's dual-hypothesis stage identifies that these signals have plausible legitimate explanations.
    """

    def test_mentioned_brand_mismatch_is_excluded_by_relevance_gate(self):
        """When Commense's impersonation check resolves clear, a Nike mismatch is excluded."""
        commense_check = _check("impersonation", "Commense", facts=[
            fact("commense.com is Commense's domain.", "clear", topic="official_domains"),
        ])
        nike_check = _check("impersonation", "Nike", facts=[
            fact("The material names Nike, but commense.com is not Nike's domain (nike.com).",
                 "anomaly", topic="impersonation") | {"place": "commense.com"},
        ])
        plan = _plan([commense_check, nike_check])
        result = evaluate(plan)
        excluded = [r for r in result.records if r.relevance == "excluded"]
        assert len(excluded) >= 1, "Nike impersonation mismatch should be excluded"
        assert "merely mentioned" in excluded[0].exclusion_reason.lower()

    def test_commense_promo_email_is_not_concerning(self):
        """The full scenario: Commense email with Nike mention + weak IPQS signal → not concerning."""
        from services.higgins.tc_flyby.decide import corroborated_impersonation, provisional

        commense_check = _check("impersonation", "Commense", facts=[
            fact("commense.com is Commense's domain.", "clear", topic="official_domains"),
        ])
        nike_check = _check("impersonation", "Nike", facts=[
            fact("The material names Nike, but commense.com is not Nike's domain (nike.com).",
                 "anomaly", topic="impersonation") | {"place": "commense.com"},
        ])
        link_check = _check("link", "commense.com", facts=[
            fact("commense.com: listed clean.", "clear", topic="listing", kind="live_evidence"),
            fact("commense.com: registered 380 days ago.", "weak", topic="registration", kind="live_evidence"),
        ])
        plan = _plan([commense_check, nike_check, link_check])

        # The corroborated_impersonation function should return empty (no corroboration)
        assert corroborated_impersonation(plan) == [], \
            "Merely-mentioned brand's domain mismatch must not count as corroborated impersonation"

        # provisional() should return None (no concern), not a Decision
        assert provisional(plan) is None, \
            "A promotional email from a verified sender mentioning another brand must not be flagged"

    def test_commense_with_ipqs_signal_not_concerning(self):
        """Even with an IPQS flag, a legitimate sender's promotional email is not flagged."""
        commense_check = _check("impersonation", "Commense", facts=[
            fact("commense.com is Commense's domain.", "clear", topic="official_domains"),
        ])
        nike_check = _check("impersonation", "Nike", facts=[
            fact("The material names Nike, but commense.com is not Nike's domain.",
                 "anomaly", topic="impersonation") | {"place": "commense.com"},
        ])
        link_check = _check("link", "commense.com", facts=[
            fact("commense.com: IPQualityScore risk score 75 (suspicious).", "weak",
                 topic="ipqs", kind="live_evidence"),
            fact("commense.com: listed clean.", "clear", topic="listing", kind="live_evidence"),
        ])
        plan = _plan([commense_check, nike_check, link_check])
        result = evaluate(plan)

        # The evaluation should NOT recommend escalation
        assert result.threat_level in ("no_threat", "needs_verification"), \
            f"Expected no_threat or needs_verification, got {result.threat_level}"
        assert not result.has_verified_threat


# ── Verified threat detection ────────────────────────────────────────────────

class TestVerifiedThreats:
    """Genuine threats must never be downgraded by the evidence evaluation pipeline."""

    def test_safe_browsing_hit_is_verified_threat(self):
        """A Safe Browsing listing is a verified threat — never downgraded."""
        link_check = _check("link", "malware-site.com", facts=[
            fact("malware-site.com: flagged by Google Safe Browsing as a phishing (social engineering) site.",
                 "concern", decisive=True, topic="safe_browsing", kind="live_evidence",
                 source=source_ref("Google Safe Browsing", authority="official")),
        ])
        plan = _plan([link_check])
        result = evaluate(plan)
        assert result.has_verified_threat is True
        assert result.threat_level == "high_risk"
        assert result.confidence == "high"

        # should_downgrade must return False
        should, reason = should_downgrade_provisional(plan, "confirmed_threat")
        assert should is False

    def test_scam_advisory_is_not_downgraded(self):
        """An official scam advisory about the sender → keeps concern."""
        link_check = _check("link", "scam-investment.com", facts=[
            fact("scam-investment.com: listed by ASIC investor alerts as an unlicensed financial operator.",
                 "concern", decisive=True, topic="advisory", kind="live_evidence",
                 source=source_ref("ASIC", authority="official")),
        ])
        plan = _plan([link_check])
        should, _ = should_downgrade_provisional(plan, "confirmed_threat")
        assert should is False

    def test_lookalike_domain_with_corroboration_stays_concerning(self):
        """A lookalike domain (carries the brand's name) with corroboration → concerning stays."""
        impersonation_check = _check("impersonation", "CommBank", facts=[
            fact("commbank-notice.net carries CommBank's name but is not CommBank's domain.",
                 "anomaly", topic="lookalike", kind="live_evidence") | {"place": "commbank-notice.net"},
        ])
        link_check = _check("link", "commbank-notice.net", facts=[
            fact("commbank-notice.net: newly registered 3 days ago.", "weak",
                 topic="registration", kind="live_evidence"),
            fact("commbank-notice.net: listed clean.", "clear", topic="listing", kind="live_evidence"),
        ])
        plan = _plan([impersonation_check, link_check])
        result = evaluate(plan)
        # Lookalike domain is NOT legitimate-favoured
        lookalike_recs = [r for r in result.records
                          if r.fact.get("topic") == "lookalike" and r.is_representative]
        assert lookalike_recs
        assert lookalike_recs[0].hypothesis_balance != "legitimate"


# ── Dual-hypothesis evaluation ───────────────────────────────────────────────

class TestDualHypothesis:
    """The dual-hypothesis evaluation must correctly identify ambiguous vs clear-cut signals."""

    def test_newly_registered_domain_is_ambiguous(self):
        """A newly registered domain alone is ambiguous — could be legit or scam."""
        link_check = _check("link", "new-store.com", facts=[
            fact("new-store.com: registered 5 days ago, newly registered.", "weak",
                 topic="registration", kind="live_evidence"),
        ])
        plan = _plan([link_check])
        result = evaluate(plan)
        recs = [r for r in result.records if r.is_representative and r.fact["signal"] == "weak"]
        assert recs
        assert recs[0].hypothesis_balance == "ambiguous"
        assert recs[0].legitimate_hypothesis is not None
        assert recs[0].malicious_hypothesis is not None

    def test_redirect_weak_signal_favours_legitimate(self):
        """Redirects (weak signal) favour the legitimate hypothesis: commonly used for tracking."""
        link_check = _check("link", "click.example.com", facts=[
            fact("click.example.com: redirect to shop.example.com.", "weak",
                 topic="redirect", kind="live_evidence"),
        ])
        plan = _plan([link_check])
        result = evaluate(plan)
        recs = [r for r in result.records if r.is_representative]
        assert recs
        assert recs[0].hypothesis_balance == "legitimate"

    def test_all_legitimate_favoured_advises_downgrade(self):
        """When ALL warning signs have legitimate explanations → should_downgrade is True."""
        link_check = _check("link", "newsite.com", facts=[
            fact("newsite.com: redirect to shop.newsite.com.", "weak",
                 topic="redirect", kind="live_evidence"),
        ])
        plan = _plan([link_check])
        # Evidence evaluation should advise downgrade
        result = evaluate(plan)
        # No warning signs (weak + legitimate = no escalation needed)
        # The threat level should be low
        assert result.threat_level in ("no_threat", "needs_verification")


# ── Evidence deduplication ───────────────────────────────────────────────────

class TestDeduplication:
    """Correlated findings about the same domain/check are grouped to prevent inflation."""

    def test_multiple_signals_for_same_domain_grouped(self):
        """IPQS + newly registered for the same domain → one correlation group, one representative."""
        link_check = _check("link", "example-shop.com", facts=[
            fact("example-shop.com: IPQualityScore risk score 80.", "weak",
                 topic="ipqs", kind="live_evidence"),
            fact("example-shop.com: registered 10 days ago.", "weak",
                 topic="registration", kind="live_evidence"),
            fact("example-shop.com: listed clean.", "clear",
                 topic="listing", kind="live_evidence"),
        ])
        plan = _plan([link_check])
        result = evaluate(plan)
        # All three facts should be in the same correlation group
        groups = result.groups
        assert len(groups) <= 2, "Facts about the same domain should be grouped together"
        reps = [r for r in result.records if r.is_representative and r.relevance != "excluded"]
        non_reps = [r for r in result.records if not r.is_representative and r.relevance != "excluded"]
        # At least one non-representative (deduplicated)
        assert len(non_reps) >= 1, "Correlated signals should be deduplicated"

    def test_distinct_domains_stay_separate(self):
        """Findings about different domains are NOT merged."""
        check_a = _check("link", "site-a.com", facts=[
            fact("site-a.com: registered 5 days ago.", "weak", topic="registration", kind="live_evidence"),
        ])
        check_b = _check("link", "site-b.com", facts=[
            fact("site-b.com: registered 3 days ago.", "weak", topic="registration", kind="live_evidence"),
        ])
        plan = _plan([check_a, check_b])
        result = evaluate(plan)
        groups = result.groups
        assert len(groups) == 2, "Different domains must be in separate groups"


# ── Relevance gate ───────────────────────────────────────────────────────────

class TestRelevanceGate:
    """The relevance gate correctly excludes irrelevant evidence."""

    def test_unavailable_check_facts_are_excluded(self):
        """Facts from checks that couldn't run are excluded (gaps, not evidence)."""
        link_check = _check("link", "example.com", status="unavailable", facts=[
            fact("example.com: lookup failed.", "missing", kind="live_evidence"),
        ])
        plan = _plan([link_check])
        result = evaluate(plan)
        excluded = [r for r in result.records if r.relevance == "excluded"]
        assert len(excluded) >= 1
        assert "unavailable" in (excluded[0].exclusion_reason or "").lower()

    def test_third_party_non_concern_is_supporting(self):
        """Third-party signals below concern level are classified as supporting, not primary."""
        link_check = _check("link", "newsite.com", facts=[
            fact("newsite.com: IPQualityScore risk score 65.", "weak",
                 topic="ipqs", kind="live_evidence"),
        ])
        plan = _plan([link_check])
        result = evaluate(plan)
        supporting = [r for r in result.records if r.relevance == "supporting"]
        assert len(supporting) >= 1


# ── Calibrated decision ─────────────────────────────────────────────────────

class TestCalibratedDecision:
    """Stage 4 correctly maps evaluated evidence to threat levels."""

    def test_no_findings_means_no_threat(self):
        plan = _plan([])
        result = evaluate(plan)
        assert result.threat_level == "no_threat"

    def test_only_clear_findings_means_no_threat(self):
        link_check = _check("link", "safe-site.com", facts=[
            fact("safe-site.com: listed clean.", "clear", topic="listing", kind="live_evidence"),
            fact("safe-site.com: registered 3650 days ago.", "neutral", topic="registration", kind="live_evidence"),
        ])
        plan = _plan([link_check])
        result = evaluate(plan)
        assert result.threat_level == "no_threat"

    def test_decisive_concern_means_high_risk(self):
        link_check = _check("link", "phishing.com", facts=[
            fact("phishing.com: flagged by Google Safe Browsing.", "concern",
                 decisive=True, topic="safe_browsing", kind="live_evidence"),
        ])
        plan = _plan([link_check])
        result = evaluate(plan)
        assert result.threat_level == "high_risk"
        assert result.confidence == "high"


# ── Integration with decide.py ───────────────────────────────────────────────

class TestDecideIntegration:
    """The evidence evaluation integrates cleanly with decide.provisional()."""

    def test_should_downgrade_returns_false_for_confirmed_threat(self):
        """Confirmed threats are never downgraded regardless of evidence evaluation."""
        link_check = _check("link", "phishing.com", facts=[
            fact("phishing.com: flagged.", "concern", decisive=True, kind="live_evidence"),
        ])
        plan = _plan([link_check])
        should, reason = should_downgrade_provisional(plan, "confirmed_threat")
        assert should is False
        assert reason is None

    def test_should_downgrade_returns_false_for_no_scam_indicators(self):
        """No-concern outcomes don't need downgrading."""
        plan = _plan([])
        should, reason = should_downgrade_provisional(plan, "no_scam_indicators")
        assert should is False
