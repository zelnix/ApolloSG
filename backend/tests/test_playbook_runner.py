"""ApolloSG PRD v2.3 §7.5 — Verification Playbook evidence-classification correction.

Direct unit coverage for `services.higgins.tc_flyby.playbook_runner`: each resolver's `status` and
`evidenceSource` must accurately reflect what evidence was actually found, never the resolver's own
type. Built with real `Plan`/`Check`/`fact()` structures (the same ones `official.py` and
`tests/test_calibration_reference_library.py` already use) — no new evidence structures.
"""
from __future__ import annotations

from services.higgins.tc_flyby import playbook_runner as pr
from services.higgins.tc_flyby.finding_rules import gather_ipdmc
from services.higgins.tc_flyby.official import fact
from services.higgins.tc_flyby.triage import Check, Entities, Plan


def _plan(checks: list[Check], **entity_kwargs) -> Plan:
    return Plan(Entities(**entity_kwargs), "message", checks, True, False, False, [])


def _link_check(facts: list[dict], *, status: str = "resolved") -> Check:
    return Check(id="c1", kind="link", subject="example-test.com", status=status, facts=facts)


class TestRegistryLikeSignalClassification:
    """`_registry_like()` backs company/link/contact/licence/person — every one of these resolvers
    shares this one function, so testing it directly covers all five."""

    def test_a_clear_fact_is_verified(self):
        plan_ = _plan([_link_check([fact("example-test.com is Example's official domain.", "clear")])])
        status, evidence = pr._link_reputation(plan_, gather_ipdmc(plan_))
        assert status == "verified"
        assert "official domain" in evidence

    def test_a_concern_fact_is_verified_not_cleared(self):
        """A verified concern is still `verified` (the check completed and produced a real answer) —
        never downgraded, and never reworded to sound reassuring."""
        plan_ = _plan([_link_check([fact("Google Safe Browsing lists example-test.com as a phishing site.", "concern", decisive=True)])])
        status, evidence = pr._link_reputation(plan_, gather_ipdmc(plan_))
        assert status == "verified"
        assert "phishing" in evidence  # the concerning text itself is preserved, not softened

    def test_an_anomaly_fact_is_verified(self):
        plan_ = _plan([_link_check([fact("example-test.com carries Example's name, but it is not Example's domain.", "anomaly")])])
        status, evidence = pr._link_reputation(plan_, gather_ipdmc(plan_))
        assert status == "verified"

    def test_a_neutral_fact_is_verified(self):
        """`neutral` is still a real, completed determination (e.g. an ABN that passes the check-digit
        test) — distinct from `weak`, which official.py's own vocabulary says never stands alone."""
        plan_ = _plan([_link_check([fact("example-test.com was registered 900 days ago.", "neutral")])])
        status, evidence = pr._link_reputation(plan_, gather_ipdmc(plan_))
        assert status == "verified"

    def test_a_weak_only_fact_is_not_promoted_to_verified(self):
        """Regression target: previously ANY live_evidence fact — including a bare `weak` signal —
        was reported as `verified`. A weak signal alone must now be `inconclusive`."""
        plan_ = _plan([_link_check([fact("example-test.com was registered 4 days ago.", "weak")])])
        status, evidence = pr._link_reputation(plan_, gather_ipdmc(plan_))
        assert status == "inconclusive"
        assert "4 days ago" in evidence  # surfaced for transparency, just not mislabelled

    def test_a_missing_only_fact_is_not_promoted_to_verified(self):
        """Regression target: a `missing` signal ("looked up, not established") must not read as a
        completed verification either."""
        plan_ = _plan([_link_check([fact("Google Safe Browsing could not be checked for example-test.com.", "missing")])])
        status, evidence = pr._link_reputation(plan_, gather_ipdmc(plan_))
        assert status == "inconclusive"
        assert "could not be checked" in evidence

    def test_unavailable_check_with_no_facts_stays_unavailable(self):
        plan_ = _plan([_link_check([], status="unavailable")])
        status, evidence = pr._link_reputation(plan_, gather_ipdmc(plan_))
        assert status == "unavailable"
        assert evidence is None

    def test_no_checks_of_this_kind_is_not_applicable(self):
        plan_ = _plan([])
        status, evidence = pr._link_reputation(plan_, gather_ipdmc(plan_))
        assert status == "not_applicable"
        assert evidence is None

    def test_resolved_check_with_no_facts_at_all_is_inconclusive(self):
        plan_ = _plan([_link_check([], status="resolved")])
        status, evidence = pr._link_reputation(plan_, gather_ipdmc(plan_))
        assert status == "inconclusive"

    def test_mixed_meaningful_and_weak_evidence_keeps_both_visible(self):
        """Mixed evidence must not let the weak signal get silently dropped once a meaningful fact
        already settles the status."""
        facts = [fact("example-test.com is not listed by Google Safe Browsing.", "clear"),
                 fact("example-test.com was registered 4 days ago.", "weak")]
        plan_ = _plan([_link_check(facts)])
        status, evidence = pr._link_reputation(plan_, gather_ipdmc(plan_))
        assert status == "verified"
        assert "not listed" in evidence and "4 days ago" in evidence

    def test_genuine_contradiction_across_checks_is_not_discarded(self):
        """One link check says `clear`, a second (different) link says `concern` — a real
        authoritative contradiction. Both must remain visible, not collapsed to the reassuring one."""
        clear_check = Check(id="c1", kind="link", subject="good-example.com", status="resolved",
                            facts=[fact("good-example.com is not listed by Google Safe Browsing.", "clear")])
        concern_check = Check(id="c2", kind="link", subject="bad-example.com", status="resolved",
                              facts=[fact("Google Safe Browsing lists bad-example.com as malicious.", "concern", decisive=True)])
        plan_ = _plan([clear_check, concern_check])
        status, evidence = pr._link_reputation(plan_, gather_ipdmc(plan_))
        assert status == "verified"
        assert "not listed" in evidence and "malicious" in evidence


class TestEvidenceSourceReflectsActualOutcome:
    """`evidenceSource` must come from the step's own result, never from the resolver's family."""

    def test_verified_step_reports_external_verification(self):
        plan_ = _plan([_link_check([fact("example-test.com is Example's official domain.", "clear")])])
        step = _fake_step("link_reputation")
        result = pr.run_step(step, plan_, gather_ipdmc(plan_))
        assert result["status"] == "verified"
        assert result["evidenceSource"] == "external_verification"

    def test_weak_only_step_reports_no_evidence_source(self):
        """Regression target: a step that found only a weak signal used to be stamped
        `external_verification` regardless — it must now say `none`, since nothing was verified."""
        plan_ = _plan([_link_check([fact("example-test.com was registered 4 days ago.", "weak")])])
        step = _fake_step("link_reputation")
        result = pr.run_step(step, plan_, gather_ipdmc(plan_))
        assert result["status"] == "inconclusive"
        assert result["evidenceSource"] == "none"

    def test_not_applicable_step_reports_no_evidence_source(self):
        plan_ = _plan([])
        step = _fake_step("link_reputation")
        result = pr.run_step(step, plan_, gather_ipdmc(plan_))
        assert result["status"] == "not_applicable"
        assert result["evidenceSource"] == "none"

    def test_inferred_step_reports_internal_detection(self):
        plan_ = _plan([], requests=[{"type": "credentials", "quote": "reply with your one-time code", "targets": []}])
        step = _fake_step("otp_request_check")
        result = pr.run_step(step, plan_, gather_ipdmc(plan_))
        assert result["status"] == "inferred"
        assert result["evidenceSource"] == "internal_detection"

    def test_no_internal_detection_hit_reports_no_evidence_source(self):
        plan_ = _plan([])
        step = _fake_step("otp_request_check")
        result = pr.run_step(step, plan_, gather_ipdmc(plan_))
        assert result["status"] == "not_applicable"
        assert result["evidenceSource"] == "none"

    def test_unavailable_source_step_reports_no_evidence_source(self):
        plan_ = _plan([])
        step = _fake_step("unavailable_source")
        result = pr.run_step(step, plan_, gather_ipdmc(plan_))
        assert result["status"] == "unavailable"
        assert result["evidenceSource"] == "none"


class _FakeStep:
    def __init__(self, resolver: str):
        self.order, self.description, self.source_ids, self.resolver = 1, "test step", ("SRC-1",), resolver


def _fake_step(resolver: str) -> _FakeStep:
    return _FakeStep(resolver)
