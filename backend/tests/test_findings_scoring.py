"""Findings Rating — classify_finding() boundary tests (Apollo PRD v2.2 §2.1 / §2.5.10).

The four Findings are decided purely by the rating's exact score boundary: 85-100 scam, 60-84
likely_scam, 25-59 unlikely_scam, 0-24 not_scam. Every boundary value the PRD calls out by name
(24, 25, 59, 60, 84, 85) is tested explicitly here, plus the out-of-range guard and a scoring-engine
smoke test per dimension.
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


def _plan(**over) -> Plan:
    base = dict(checks=[], has_message=True, link_only=False, general=False, gaps=[], advisories=[],
               pattern=None, channel="sms", entities=Entities(), message_type="general")
    base.update(over)
    return Plan(**base)


class TestScorePlanMechanics:
    """score_plan() over directly-constructed evidence — the engine's own contract, independent of
    what any particular free-text message happens to extract (that's Higgins Triage's job)."""

    def test_nothing_found_nothing_verified_is_unlikely_scam_at_the_benign_baseline(self):
        plan = _plan()
        breakdown = score_plan(plan, IPDMCChecks())
        assert breakdown.finding == "unlikely_scam"
        assert breakdown.rating == 28
        assert breakdown.benign_baseline_applied is True

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
        dimension), but on its own — no false identity, no pattern, no corroboration — it still isn't
        enough to cross into "likely a scam"; it should never read as "not a scam" either."""
        plan = _plan()
        ipdmc = IPDMCChecks(consequential_requests=[{"type": "financial", "quote": "please transfer $50 to my new account"}])
        breakdown = score_plan(plan, ipdmc)
        assert breakdown.finding == "unlikely_scam"
        assert 25 <= breakdown.rating <= 59

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
        for key in ("rating", "finding", "dimensions", "baseline", "benignBaselineApplied",
                   "legitimacyCredit", "legitimacyReason", "decisiveFloorApplied", "decisiveMechanism"):
            assert key in wire
