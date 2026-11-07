"""Findings Rating — classify_finding() boundary tests (Apollo PRD v2.2 §2.1 / §2.5.10).

The four Findings are decided by the rating's exact score boundary: 85-100 scam, 60-84 likely_scam,
25-59 unlikely_scam, 0-24 not_scam — but the 0-24 band also requires verification_established=True
to read "not_scam" (Developer Instructions: "Clarification of Scoring and Findings Requirements");
otherwise it reads "unlikely_scam", the same real score under an honest Finding. Every boundary value
the PRD calls out by name (24, 25, 59, 60, 84, 85) is tested explicitly here, plus the out-of-range
guard and a scoring-engine smoke test per dimension.
"""
import pytest

from services.higgins.tc_flyby.finding_rules import IPDMCChecks
from services.higgins.tc_flyby.scoring import classify_finding, score_plan
from services.higgins.tc_flyby.triage import Entities, Plan


class TestClassifyFindingBoundaries:
    """Exact, inclusive boundaries — PRD's own six mandatory boundary values."""

    def test_24_is_not_scam(self):
        assert classify_finding(24) == "not_scam"

    def test_25_is_unlikely_scam(self):
        assert classify_finding(25) == "unlikely_scam"

    def test_59_is_unlikely_scam(self):
        assert classify_finding(59) == "unlikely_scam"

    def test_60_is_likely_scam(self):
        assert classify_finding(60) == "likely_scam"

    def test_84_is_likely_scam(self):
        assert classify_finding(84) == "likely_scam"

    def test_85_is_scam(self):
        assert classify_finding(85) == "scam"

    def test_0_is_not_scam(self):
        assert classify_finding(0) == "not_scam"

    def test_100_is_scam(self):
        assert classify_finding(100) == "scam"

    @pytest.mark.parametrize("bad", [-1, 101, 150, -50])
    def test_out_of_range_raises(self, bad):
        with pytest.raises(ValueError):
            classify_finding(bad)

    def test_24_is_unlikely_scam_when_verification_was_not_established(self):
        """Developer Instructions correction: a 0-24 score only reads "Not a Scam" when verification
        was actually established — otherwise it reads "Unlikely a Scam", the same real number under
        an honest Finding."""
        assert classify_finding(24, verification_established=False) == "unlikely_scam"

    def test_0_is_unlikely_scam_when_verification_was_not_established(self):
        assert classify_finding(0, verification_established=False) == "unlikely_scam"

    def test_25_and_above_are_unaffected_by_verification_status(self):
        """Every boundary at 25 and above is identical whether or not verification was established —
        missing verification never raises the score, so it can't change anything already above the
        not_scam/unlikely_scam line."""
        for score in (25, 59, 60, 84, 85, 100):
            assert classify_finding(score, verification_established=True) == classify_finding(score, verification_established=False)


def _plan(**over) -> Plan:
    base = dict(checks=[], has_message=True, link_only=False, general=False, gaps=[], advisories=[],
               pattern=None, channel="sms", entities=Entities(), message_type="general")
    base.update(over)
    return Plan(**base)


class TestScorePlanMechanics:
    """score_plan() over directly-constructed evidence — the engine's own contract, independent of
    what any particular free-text message happens to extract (that's Higgins Triage's job)."""

    def test_nothing_found_nothing_verified_is_unlikely_scam_at_a_real_zero_score(self):
        """PRD's own golf-invitation example (Developer Instructions correction): no scam
        indicators, nothing to check — the score is the real, unmodified dimension sum (0), never
        an invented floor. Verification completeness alone gates the Finding."""
        plan = _plan()
        breakdown = score_plan(plan, IPDMCChecks())
        assert breakdown.finding == "unlikely_scam"
        assert breakdown.rating == 0
        assert breakdown.baseline == 0
        assert breakdown.verification_established is False
        assert breakdown.verification_note, "verification context must always be populated, even when it doesn't change the score"

    def test_decisive_otp_ask_floors_at_85_regardless_of_other_evidence(self):
        plan = _plan()
        ipdmc = IPDMCChecks(consequential_requests=[
            {"type": "credentials", "quote": "reply with the one-time code we just sent you to release your refund"},
        ])
        breakdown = score_plan(plan, ipdmc)
        assert breakdown.finding == "scam"
        assert breakdown.rating >= 85
        assert breakdown.decisive_floor_applied is True

    def test_decisive_wallet_seed_phrase_ask_floors_at_85(self):
        plan = _plan()
        ipdmc = IPDMCChecks(consequential_requests=[
            {"type": "credentials", "quote": "approve the wallet transaction and enter your recovery phrase"},
        ])
        breakdown = score_plan(plan, ipdmc)
        assert breakdown.finding == "scam" and breakdown.rating >= 85

    def test_decisive_extortion_demand_floors_at_85(self):
        plan = _plan()
        ipdmc = IPDMCChecks(consequential_requests=[
            {"type": "financial", "quote": "pay us in bitcoin or we will release the video"},
        ])
        breakdown = score_plan(plan, ipdmc)
        assert breakdown.finding == "scam" and breakdown.rating >= 85

    def test_false_identity_alone_is_at_least_likely_scam(self):
        plan = _plan()
        ipdmc = IPDMCChecks(identity_is_false=True)
        breakdown = score_plan(plan, ipdmc)
        assert breakdown.finding == "likely_scam"
        assert breakdown.rating >= 65

    def test_positively_verified_identity_and_destination_is_not_scam(self):
        plan = _plan()
        ipdmc = IPDMCChecks(identity_verified="passed", destinations_verified="passed",
                            genuine_explanation_supported=True)
        breakdown = score_plan(plan, ipdmc)
        assert breakdown.finding == "not_scam"
        assert breakdown.rating <= 24
        assert breakdown.legitimacy_credit > 0

    def test_unverified_consequential_request_alone_is_unlikely_scam_not_clean(self):
        """A consequential ask through an unverified route is concerning (20/100 just from that
        dimension, real and evidence-based) — not enough alone to cross into "likely a scam", but
        it must never read as "not a scam" either, because verification was never established."""
        plan = _plan()
        ipdmc = IPDMCChecks(consequential_requests=[{"type": "financial", "quote": "please transfer $50 to my new account"}])
        breakdown = score_plan(plan, ipdmc)
        assert breakdown.finding == "unlikely_scam"
        assert breakdown.rating == 20, "the real dimension score (requested_action alone) is retained, not pushed into a 25-59 band artificially"
        assert breakdown.verification_established is False

    def test_full_kb_pattern_match_with_a_request_is_likely_scam_or_higher(self):
        plan = _plan(pattern={"name": "Hi Mum", "stage": "full", "impersonatesOrganisation": False})
        ipdmc = IPDMCChecks(consequential_requests=[{"type": "financial", "quote": "transfer $300 to this account today"}])
        breakdown = score_plan(plan, ipdmc)
        assert breakdown.finding in ("likely_scam", "scam")
        assert breakdown.rating >= 60

    def test_rating_is_always_bounded_0_to_100(self):
        plan = _plan()
        ipdmc = IPDMCChecks(identity_is_false=True, purpose_is_deceptive=True,
                            consequential_requests=[{"type": "credentials", "quote": "send your otp code now"}])
        breakdown = score_plan(plan, ipdmc)
        assert 0 <= breakdown.rating <= 100

    def test_breakdown_dimensions_sum_matches_reported_baseline(self):
        plan = _plan()
        ipdmc = IPDMCChecks(consequential_requests=[{"type": "financial", "quote": "pay now"}])
        breakdown = score_plan(plan, ipdmc)
        assert sum(d.points for d in breakdown.dimensions) == breakdown.baseline
        assert all(0 <= d.points <= d.maximum for d in breakdown.dimensions)

    def test_wire_shape_has_every_field_the_frontend_needs(self):
        plan = _plan()
        breakdown = score_plan(plan, IPDMCChecks())
        wire = breakdown.wire()
        for key in ("rating", "finding", "dimensions", "baseline", "verificationEstablished", "verificationNote",
                   "legitimacyCredit", "legitimacyReason", "decisiveFloorApplied", "decisiveMechanism"):
            assert key in wire


class TestVerificationCompletenessIsSeparateFromScore:
    """Developer Instructions — "Clarification of Scoring and Findings Requirements": the six-
    dimension score reflects only real, evidence-based scam indicators and approved evidence-based
    adjustments (legitimacy credit, impersonation/decisive floors). Verification completeness is a
    separate axis (`verification_established` / `verification_note`) that gates whether a genuinely
    low 0-24 score reads "Not a Scam" (verification actually established) or "Unlikely a Scam" (no
    scam indicators found, but authenticity also not independently established) — it never adds a
    single point to `rating` itself."""

    def test_an_ordinary_message_with_nothing_to_check_scores_zero_not_an_invented_floor(self):
        plan = _plan()
        breakdown = score_plan(plan, IPDMCChecks())
        assert breakdown.rating == 0, "no artificial benign-baseline adjustment may be added to the score"
        assert breakdown.baseline == 0
        assert breakdown.finding == "unlikely_scam"
        assert breakdown.verification_established is False

    def test_checked_and_clean_evidence_keeps_its_own_real_score(self):
        """A check actually ran and came back clean, alongside an unrelated, real urgency cue (6
        points). The score must stay exactly 6 — never bumped, never zeroed, never re-interpreted."""
        from services.higgins.tc_flyby.triage import Entities, Check

        clean_fact = {"text": "example.org is registered to a long-established organisation.", "signal": "neutral",
                      "decisive": False, "class": "live_evidence", "topic": "registration", "source": None}
        link_check = Check(id="c1", kind="link", subject="example.org", urls=["https://example.org/"])
        link_check.facts.append(clean_fact)
        link_check.status = "resolved"
        ent = Entities()
        ent.urgency = ["please reply by tomorrow"]
        plan = _plan(checks=[link_check], entities=ent)

        breakdown = score_plan(plan, IPDMCChecks())
        assert breakdown.baseline == 6, "manipulation_behaviour alone should score 6 for one urgency cue"
        assert breakdown.rating == 6, "a real, evidence-based score must never be replaced by an artificial floor"
        assert breakdown.finding == "unlikely_scam"

    def test_positively_verified_identity_reads_not_scam_at_a_genuinely_low_score(self):
        plan = _plan()
        ipdmc = IPDMCChecks(identity_verified="passed", destinations_verified="passed", genuine_explanation_supported=True)
        breakdown = score_plan(plan, ipdmc)
        assert breakdown.verification_established is True
        assert breakdown.finding == "not_scam"
        assert breakdown.rating <= 24

    def test_unavailable_check_leaves_the_score_at_its_real_value(self):
        """An "unavailable external verification service" (signal="missing") is an evidence
        limitation, never a reason to raise the score."""
        from services.higgins.tc_flyby.triage import Check

        missing_fact = {"text": "Google Safe Browsing could not be checked for example.org.", "signal": "missing",
                        "decisive": False, "class": "live_evidence", "topic": "listing", "source": None}
        link_check = Check(id="c1", kind="link", subject="example.org", urls=["https://example.org/"])
        link_check.facts.append(missing_fact)
        plan = _plan(checks=[link_check])

        breakdown = score_plan(plan, IPDMCChecks())
        assert breakdown.rating == 0
        assert breakdown.finding == "unlikely_scam"
        assert breakdown.verification_established is False

    def test_unresolved_consequential_request_scores_on_its_own_real_evidence(self):
        """PRD's delivery-toll shape: a consequential request through an unverified destination
        scores 20 on its own real evidence (requested_action) — no artificial floor is needed even
        though a *different* link elsewhere in the message checked out clean."""
        from services.higgins.tc_flyby.triage import Check

        clean_fact = {"text": "auspost.com.au is Australia Post's own, official domain.", "signal": "clear",
                      "decisive": False, "class": "live_evidence", "topic": "official_domains", "source": None}
        link_check = Check(id="c1", kind="link", subject="auspost.com.au", urls=["https://auspost.com.au/"])
        link_check.facts.append(clean_fact)
        plan = _plan(checks=[link_check])
        ipdmc = IPDMCChecks(consequential_requests=[{"type": "financial", "quote": "pay the $2.50 redelivery fee by PayID to 0412 345 678"}],
                            unverified_destinations=["0412 345 678"])

        breakdown = score_plan(plan, ipdmc)
        assert breakdown.rating == 20
        assert breakdown.verification_established is False
        assert breakdown.finding == "unlikely_scam"

    def test_verification_note_is_always_populated(self):
        """The DI tab must always be able to show verification context beside the score — never a
        contradictory-looking gap between the two (Developer Instructions requirement)."""
        for ipdmc in (IPDMCChecks(), IPDMCChecks(identity_verified="passed", destinations_verified="passed", genuine_explanation_supported=True)):
            breakdown = score_plan(_plan(), ipdmc)
            assert breakdown.verification_note and isinstance(breakdown.verification_note, str)
