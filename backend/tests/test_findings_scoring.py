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

    def test_nothing_found_nothing_checked_is_not_scam_not_benign(self):
        """ApolloSG Developer Instructions §6 — "Correct Benign Baseline Invocation": an ordinary
        message with nothing to check and nothing wrong must never get the floor merely for lacking
        verification (PRD §2.4's golf-invitation shape) — it is scored on its own calculated merits."""
        plan = _plan()
        breakdown = score_plan(plan, IPDMCChecks())
        assert breakdown.finding == "not_scam"
        assert breakdown.rating == 0
        assert breakdown.benign_baseline_applied is False

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

    def test_a_scam_the_rules_established_is_never_rated_likely(self):
        """Owner, 2026-11-08: a myGov lookalike sender demanding a tax debt read "This is a scam" on the
        Findings Brief while the DI tab's Scoring Breakdown said "83/100 — This is Likely a Scam". The verdict
        comes from the S-rules (S2: fake identity + deceptive purpose); the rating must agree with it."""
        plan = _plan()
        ipdmc = IPDMCChecks(claimed_identity="myGov", identity_is_false=True, purpose_is_deceptive=True,
                            identity_evidence=["mygov-refunds.net carries myGov's name but isn't myGov's domain (my.gov.au)."])
        breakdown = score_plan(plan, ipdmc)
        assert breakdown.finding == "scam"
        assert breakdown.rating >= 85
        assert breakdown.decisive_floor_applied
        assert "rule S2" in (breakdown.decisive_mechanism or "")
        # The breakdown says why, in the rule's own words.
        assert "never scored below 85" in breakdown.narrative
        # An established S-rule that a reliable genuine explanation undermines is not a scam — and isn't floored.
        undermined = IPDMCChecks(claimed_identity="myGov", identity_is_false=True, purpose_is_deceptive=True,
                                 has_contradictions=True, genuine_explanation_supported=True)
        assert not score_plan(plan, undermined).decisive_floor_applied

    def test_positively_verified_identity_and_destination_is_not_scam(self):
        plan = _plan()
        ipdmc = IPDMCChecks(identity_verified="passed", destinations_verified="passed",
                            genuine_explanation_supported=True)
        breakdown = score_plan(plan, ipdmc)
        assert breakdown.finding == "not_scam"
        assert breakdown.rating <= 24
        assert breakdown.legitimacy_credit > 0

    def test_unverified_consequential_request_alone_scores_only_its_own_dimension(self):
        """A consequential ask through an unverified route is concerning (20/100 just from that
        dimension), but on its own — no false identity, no pattern, no corroboration, no genuine
        investigation failure or contradiction — the Benign Baseline no longer applies (Developer
        Instructions §6: absence of verification alone must not invoke it). In the real pipeline this
        shape still always reaches Magnum DI, via decide.py's existing unverified-request "reasoning"
        issue (services.higgins.tc_flyby.decide._all_issues) — this is a unit test of score_plan() in
        isolation, not the end-to-end routing decision."""
        plan = _plan()
        ipdmc = IPDMCChecks(consequential_requests=[{"type": "financial", "quote": "please transfer $50 to my new account"}])
        breakdown = score_plan(plan, ipdmc)
        assert breakdown.benign_baseline_applied is False
        assert breakdown.rating == 20
        assert breakdown.finding == "not_scam"

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
        for key in ("rating", "finding", "dimensions", "baseline", "benignBaselineApplied", "benignBaselineTrigger",
                   "legitimacyCredit", "legitimacyReason", "decisiveFloorApplied", "decisiveMechanism"):
            assert key in wire


class TestBenignBaselineRequiresAnEvidenceBackedTrigger:
    """ApolloSG Developer Instructions — "Correct Benign Baseline Invocation and Mandatory Magnum DI
    Escalation": the 28-point floor fires on exactly two approved criteria — a genuine investigation
    failure, or an unresolved material contradiction — never merely because a message falls short of
    full legitimacy proof, and never merely because nothing was positively verified either way."""

    def test_checked_and_clean_evidence_does_not_get_bumped_to_the_floor(self):
        """The "ABC newsletter" shape: a check actually ran (a link/domain lookup) and came back
        clean (neutral/clear signals only) with a low but non-zero calculated baseline (e.g. a mild
        urgency cue). This must stay at its calculated score, not jump to 28."""
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
        assert breakdown.benign_baseline_applied is False, "checked-and-clean evidence must not trigger the floor"
        assert breakdown.rating == 6, "the calculated score must be retained, not bumped to 28"
        assert breakdown.finding == "not_scam"

    def test_ordinary_message_with_nothing_to_check_does_not_get_the_floor(self):
        """Developer Instructions §6's own example ("Hi David, are we still meeting for golf tomorrow
        at 10 AM?"): nothing was submitted that needed checking, and nothing failed. This is NOT a
        genuine investigation failure or an unresolved contradiction, so the floor must not fire —
        reversing the previous (incorrect) behaviour where an informational vacuum alone triggered it."""
        plan = _plan()  # checks=[] — nothing was ever checked, nothing is wrong
        breakdown = score_plan(plan, IPDMCChecks())
        assert breakdown.benign_baseline_applied is False
        assert breakdown.rating == 0
        assert breakdown.finding == "not_scam"

    # ── Criterion 1: Investigation Failure ────────────────────────────────

    def test_an_unavailable_check_is_a_genuine_investigation_failure_and_gets_the_floor(self):
        """A required check TC Hawkeye planned stayed "unavailable" (e.g. a timed-out API, an
        unreachable registry) — a genuine Criterion 1 failure, distinct from a successful lookup that
        simply found nothing."""
        from services.higgins.tc_flyby.triage import Check

        link_check = Check(id="c1", kind="link", subject="example.org", urls=["https://example.org/"])
        link_check.status = "unavailable"
        plan = _plan(checks=[link_check])

        breakdown = score_plan(plan, IPDMCChecks())
        assert breakdown.benign_baseline_applied is True
        assert breakdown.rating == 28
        assert breakdown.finding == "unlikely_scam"
        assert "could not be completed" in breakdown.benign_baseline_trigger

    def test_a_provider_timeout_with_nothing_else_resolving_it_gets_the_floor(self):
        """A reputation-check provider (e.g. IPQualityScore) failed/timed out after retrying, with
        nothing else already established for that check — decide.technical_issue()'s own test,
        reused here as a Criterion 1 trigger."""
        from services.higgins.tc_flyby.triage import Check

        link_check = Check(id="c1", kind="link", subject="fresh-deals.shop", urls=["https://fresh-deals.shop/"])
        link_check.provider_failures = ["ipqs"]
        plan = _plan(checks=[link_check])

        breakdown = score_plan(plan, IPDMCChecks())
        assert breakdown.benign_baseline_applied is True
        assert breakdown.rating == 28

    def test_unprocessable_evidence_is_an_investigation_failure_and_gets_the_floor(self):
        """Submitted evidence that could not be extracted/decoded/parsed/analysed reliably (a scanned
        page with no text layer, a corrupted attachment) — a Criterion 1 evidence-processing failure."""
        plan = _plan(gaps=[{"evidenceId": "e1", "item": "page 2 of the statement", "magnum": True,
                            "what": "a scanned page with no text layer, so its text couldn't be extracted"}])
        breakdown = score_plan(plan, IPDMCChecks())
        assert breakdown.benign_baseline_applied is True
        assert breakdown.rating == 28
        assert "could not be reliably processed" in breakdown.benign_baseline_trigger

    def test_a_successful_lookup_that_found_nothing_is_not_a_failure(self):
        """A check genuinely ran and came back "not_found" (no record either way) — this is a
        successfully completed investigative operation, not a failure, so it must not invoke Benign
        on its own (Developer Instructions §2/§6)."""
        from services.higgins.tc_flyby.triage import Check

        not_found_fact = {"text": "TC Hawkeye's search found no record for 0412 345 678.", "signal": "missing",
                          "decisive": False, "class": "live_evidence", "topic": None, "source": None}
        phone_check = Check(id="c1", kind="phone", subject="0412 345 678")
        phone_check.facts.append(not_found_fact)
        phone_check.status = "not_found"
        plan = _plan(checks=[phone_check])

        breakdown = score_plan(plan, IPDMCChecks())
        assert breakdown.benign_baseline_applied is False
        assert breakdown.finding == "not_scam"

    def test_an_unrelated_optional_service_failure_with_no_bearing_does_not_get_the_floor(self):
        """A provider failure on a check whose subject was already independently established (clear or
        concern) by something else has no effect on investigative reliability, so it must not
        automatically invoke Benign (Developer Instructions §2: "An optional or redundant service
        failure that has no effect on investigative reliability must not automatically invoke
        Benign.") — the same `_unresolved()` test decide.technical_issue() already applies."""
        from services.higgins.tc_flyby.triage import Check

        clear_fact = {"text": "Google Safe Browsing lists example.org as safe.", "signal": "clear",
                     "decisive": False, "class": "live_evidence", "topic": "listing", "source": None}
        link_check = Check(id="c1", kind="link", subject="example.org", urls=["https://example.org/"])
        link_check.facts.append(clear_fact)
        link_check.provider_failures = ["ipqs"]   # a different, redundant provider failed — irrelevant
        plan = _plan(checks=[link_check])

        breakdown = score_plan(plan, IPDMCChecks())
        assert breakdown.benign_baseline_applied is False

    def test_a_consequential_request_through_an_unverified_destination_alone_no_longer_floors(self):
        """Developer Instructions §6 correction: an unverified destination, by itself, is an absence
        of verification — not a genuine investigation failure or contradiction — so it no longer
        invokes Benign on its own (see TestScorePlanMechanics for the full rationale, including why
        the real pipeline still reaches Magnum DI for this shape regardless, via decide.py's existing
        unverified-request issue)."""
        from services.higgins.tc_flyby.triage import Check

        clean_fact = {"text": "auspost.com.au is Australia Post's own, official domain.", "signal": "clear",
                      "decisive": False, "class": "live_evidence", "topic": "official_domains", "source": None}
        link_check = Check(id="c1", kind="link", subject="auspost.com.au", urls=["https://auspost.com.au/"])
        link_check.facts.append(clean_fact)
        plan = _plan(checks=[link_check])
        ipdmc = IPDMCChecks(consequential_requests=[{"type": "financial", "quote": "pay the $2.50 redelivery fee by PayID to 0412 345 678"}],
                            unverified_destinations=["0412 345 678"])

        breakdown = score_plan(plan, ipdmc)
        assert breakdown.benign_baseline_applied is False
        assert breakdown.rating == 20

    # ── Criterion 2: Conflicting Investigative Results ────────────────────

    def test_an_unresolved_register_conflict_gets_the_floor(self):
        """A register entry under a related-but-different name — gather_ipdmc's own "Conflict"
        open_issue — is a materially contradictory result TC Hawkeye could not reconcile."""
        ipdmc = IPDMCChecks(has_contradictions=True,
                            contradiction_details=["Conflict: ABN 12 345 678 901 is registered to a related but different "
                                                   "name than Example Pty Ltd, the name in the material."])
        breakdown = score_plan(_plan(), ipdmc)
        assert breakdown.benign_baseline_applied is True
        assert breakdown.rating == 28
        assert "contradictory" in breakdown.benign_baseline_trigger

    def test_a_reconciled_contradiction_does_not_get_the_floor(self):
        """Once TC Hawkeye reconciles a contradiction (gather_ipdmc never set has_contradictions, or a
        later check cleared it), there is nothing left to float to the floor for."""
        ipdmc = IPDMCChecks(has_contradictions=False, contradiction_details=[])
        breakdown = score_plan(_plan(), ipdmc)
        assert breakdown.benign_baseline_applied is False

    def test_a_pattern_match_explained_by_the_organisations_own_official_routes_does_not_get_the_floor(self):
        """Developer Instructions §8 test 6 — "contradictory findings are successfully reconciled by TC
        Hawkeye": a message matches a scam pattern, but every route in it is the named organisation's own
        — gather_ipdmc's own `genuine_explanation_supported` (identity and destinations both positively
        verified, nothing else concerning). This was reconciled, not left materially unresolved."""
        ipdmc = IPDMCChecks(has_contradictions=True, genuine_explanation_supported=True,
                            contradiction_details=["The material matches a scam pattern but the links belong to the named organisation."])
        breakdown = score_plan(_plan(), ipdmc)
        assert breakdown.benign_baseline_applied is False

    def test_a_contradiction_that_itself_establishes_deception_is_never_diluted_by_benign(self):
        """Developer Instructions §2: "Where a contradiction itself establishes deception, retain that
        evidence for normal scam scoring. Do not use Benign to dilute an established threat." A false
        identity used deceptively already floors the score at 85 — the benign floor (28) never lowers
        it, and `benign_baseline_applied` correctly stays False since it was never needed."""
        ipdmc = IPDMCChecks(claimed_identity="myGov", identity_is_false=True, purpose_is_deceptive=True,
                            has_contradictions=True, contradiction_details=["Conflict: some unresolved detail."])
        breakdown = score_plan(_plan(), ipdmc)
        assert breakdown.rating >= 85
        assert breakdown.finding == "scam"
        assert breakdown.benign_baseline_applied is False, "the floor was never needed — established evidence already outranks it"

    def test_higher_established_evidence_is_never_reduced_by_the_floor(self):
        """A false identity alone is already "likely a scam" (>= 65) — far above the 28-point floor,
        which only ever raises a lower score, never lowers one."""
        ipdmc = IPDMCChecks(identity_is_false=True, has_contradictions=True,
                            contradiction_details=["Conflict: some unresolved detail."])
        breakdown = score_plan(_plan(), ipdmc)
        assert breakdown.rating >= 65
        assert breakdown.benign_baseline_applied is False

    def test_the_four_finding_labels_and_thresholds_are_unaffected(self):
        """The correction only narrows when the floor fires — it changes no classification boundary."""
        assert classify_finding(24) == "not_scam"
        assert classify_finding(25) == "unlikely_scam"
        assert classify_finding(59) == "unlikely_scam"
        assert classify_finding(60) == "likely_scam"
        assert classify_finding(84) == "likely_scam"
        assert classify_finding(85) == "scam"


class TestBreakdownSaysNothingTwice:
    """Owner, 2026-11-08 (DI Scoring Breakdown): an unavailable check was listed under "Checks performed" and
    again under "Missing evidence", and the Evidence Corroboration row repeated the check and evidence lines
    Scam Mechanism and Identity & Destination had already shown. Each line appears once in a breakdown."""

    def _lookalike_plan(self):
        from services.higgins.tc_flyby.triage import Check

        lookalike = {"text": "commbank-cancel.co carries CommBank's name, but it is not CommBank's domain (commbank.com.au).",
                     "signal": "concern", "decisive": False, "class": "live_evidence", "topic": "brand_domain", "source": None}
        link_check = Check(id="c1", kind="link", subject="commbank-cancel.co", urls=["https://commbank-cancel.co/stop"])
        link_check.facts.append(lookalike)
        link_check.status = "unavailable"
        imp_check = Check(id="c2", kind="impersonation", subject="CommBank")
        imp_check.status = "not_needed"
        return _plan(checks=[link_check, imp_check]), lookalike["text"]

    def test_an_unavailable_check_is_listed_once_under_missing_evidence(self):
        plan, _ = self._lookalike_plan()
        breakdown = score_plan(plan, IPDMCChecks(identity_is_false=True, unverified_destinations=["commbank-cancel.co"]))
        by_key = {d.key: d for d in breakdown.dimensions}
        mech = by_key["scam_mechanism"]
        assert mech.missing == ["link check on commbank-cancel.co: unavailable"]
        assert all(c["status"] != "unavailable" for c in mech.checks), "an unavailable check belongs under missing evidence only"
        assert {"kind": "impersonation", "subject": "CommBank", "status": "not_needed"} in mech.checks

    def test_evidence_corroboration_repeats_nothing_the_rows_above_showed(self):
        plan, lookalike_text = self._lookalike_plan()
        breakdown = score_plan(plan, IPDMCChecks(identity_is_false=True, unverified_destinations=["commbank-cancel.co"],
                                                 identity_evidence=[lookalike_text], mechanism_evidence=[lookalike_text]))
        dims = breakdown.dimensions
        corroboration = next(d for d in dims if d.key == "evidence_corroboration")
        above = [d for d in dims if d.key != "evidence_corroboration"]
        shown_evidence = {e for d in above for e in d.evidence}
        shown_checks = {(c["kind"], c["subject"]) for d in above for c in d.checks}
        shown_missing = {m for d in above for m in d.missing}
        assert lookalike_text in shown_evidence, "Scam Mechanism / Identity & Destination show the lookalike line"
        assert not set(corroboration.evidence) & shown_evidence
        assert not {(c["kind"], c["subject"]) for c in corroboration.checks} & shown_checks
        assert not set(corroboration.missing) & shown_missing
        # Its points and reason are untouched: the one concern signal is still counted.
        assert corroboration.points == 3
