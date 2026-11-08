"""Unified Evidence Classification & Six-Dimension Findings Rating PRD (v1.0, 8 Nov 2026) — direct
unit coverage of the reconciliation step itself (scoring.reconcile()/evidence_verdict()), plus the
PRD's own named acceptance scenarios run end-to-end. The evidence verdict (finding_rules.
evaluate_rules()'s S1-S4/N1-N4/L1-L3/U waterfall) is always final; the six-dimension score is shown
unless it falls outside that verdict's band, in which case it's nudged to the nearest edge and never
further — this file locks that contract in so it can never silently regress back to the old "score
alone decides, two disconnected verdict paths" behaviour (see finding_rules.py's evaluate(),
report.py's compose() and decide.py's provisional() for the three call sites)."""
from services.higgins.tc_flyby import decide, finding_rules, report, scoring, triage
from services.higgins.tc_flyby.finding_rules import FindingRulesResult
from services.higgins.tc_flyby.scoring import BANDS, ScoreBreakdown


def _breakdown(raw_rating: int) -> ScoreBreakdown:
    b = ScoreBreakdown()
    b.rating = raw_rating
    b.raw_rating = raw_rating
    b.finding = scoring.classify_finding(raw_rating)
    b.calculation_trace = [{"step": "Final rating (0-100)", "detail": b.finding, "value": raw_rating}]
    b.narrative = f"Higgins rated this {raw_rating}/100 — placeholder."
    return b


def _rules_result(finding: str, deciding_rules: list[str] | None = None) -> FindingRulesResult:
    return FindingRulesResult(finding=finding, deciding_rules=deciding_rules or [])


# ── evidence_verdict(): U is an internal state, never a fifth verdict (PRD §4) ──────────────────

def test_evidence_verdict_maps_unable_to_determine_to_unlikely_scam():
    assert scoring.evidence_verdict("unable_to_determine") == "unlikely_scam"


def test_evidence_verdict_passes_through_the_four_approved_verdicts():
    for finding in ("scam", "likely_scam", "unlikely_scam", "not_scam"):
        assert scoring.evidence_verdict(finding) == finding


# ── reconcile(): no adjustment when the calculated score already lands in the evidence's band ───

def test_reconcile_leaves_rating_unchanged_when_already_in_band():
    breakdown = scoring.reconcile(_rules_result("likely_scam", ["L2"]), _breakdown(70))
    assert breakdown.rating == 70 and breakdown.raw_rating == 70
    assert breakdown.finding == "likely_scam" and breakdown.adjustment_reason == ""


# ── reconcile(): PRD §5.1's own worked examples ──────────────────────────────────────────────────

def test_s2_established_with_low_raw_score_is_floored_up_into_the_scam_band():
    """PRD §5.1: "S2 with raw 72 -> Scam, aligned >=85"."""
    breakdown = scoring.reconcile(_rules_result("scam", ["S2"]), _breakdown(72))
    assert breakdown.finding == "scam" and breakdown.rating == BANDS["scam"][0] == 85
    assert breakdown.raw_rating == 72
    assert "aligned" in breakdown.adjustment_reason.lower() or "This is a Scam" in breakdown.adjustment_reason


def test_l2_with_no_established_s_is_capped_into_the_likely_band_never_auto_promoted():
    """PRD §5.1/§7.3 acceptance test: "L2 full pattern without independent S corroboration -> Likely;
    no automatic S promotion" / "High score without verified S -> Not automatically Scam"."""
    breakdown = scoring.reconcile(_rules_result("likely_scam", ["L2"]), _breakdown(91))
    assert breakdown.finding == "likely_scam" and breakdown.rating == BANDS["likely_scam"][1] == 84
    assert breakdown.raw_rating == 91
    assert breakdown.adjustment_reason


def test_positively_verified_not_scam_with_high_raw_score_is_capped_down():
    """PRD §5.1: "a positively verified N with raw 30 -> Not a Scam, aligned <=24"."""
    breakdown = scoring.reconcile(_rules_result("not_scam", ["N1", "N2", "N3", "N4"]), _breakdown(30))
    assert breakdown.finding == "not_scam" and breakdown.rating == BANDS["not_scam"][1] == 24
    assert breakdown.raw_rating == 30


def test_ordinary_neutral_message_with_nothing_established_reads_unlikely_never_a_false_not_scam():
    """PRD §5.1: an ordinary message with nothing established settles as "Unlikely a Scam", raised
    to the band's floor rather than left reading as a false "not a scam" at 0."""
    breakdown = scoring.reconcile(_rules_result("unable_to_determine"), _breakdown(0))
    assert breakdown.finding == "unlikely_scam" and breakdown.rating == BANDS["unlikely_scam"][0] == 25
    assert breakdown.raw_rating == 0
    assert breakdown.verdict_rule_ids == []


def test_adjustment_reason_and_raw_rating_stay_visible_for_the_di_tab():
    """FR-07 — the DI tab's wire format must expose both numbers and why, never just the aligned one."""
    breakdown = scoring.reconcile(_rules_result("not_scam", ["N1", "N2"]), _breakdown(40))
    wire = breakdown.wire()
    assert wire["rating"] == 24 and wire["rawRating"] == 40
    assert wire["adjustmentReason"] and wire["verdictRuleIds"] == ["N1", "N2"]
    assert any(step["step"] == "Evidence-verdict alignment" for step in wire["calculationTrace"])


def test_reconcile_never_rewrites_the_dimension_points_or_evidence():
    """PRD §5.1 — only the number and finding move; the six dimensions, evidence and baseline sum
    are never rewritten."""
    original = _breakdown(91)
    original.dimensions = [scoring.DimensionScore("scam_mechanism", "Scam mechanism", 25, 25, "why", [], [], [])]
    original.baseline = 91
    breakdown = scoring.reconcile(_rules_result("likely_scam", ["L2"]), original)
    assert breakdown.dimensions == original.dimensions and breakdown.baseline == 91


# ── One shared resolver (FR-01): finding_rules.evaluate() never overrides the evidence verdict ──

def test_finding_rules_evaluate_never_silently_overrides_the_evidence_verdict():
    """The exact bug this PRD named: finding_rules.evaluate() used to replace its own S/N/L/U
    waterfall result with whatever band the score alone landed in. It must not any more — an
    ordinary message with nothing to check must read "unlikely_scam", never "not_scam"."""
    plan = triage.plan("Is this real?", ["Hi, see you Saturday for golf?"])
    result = finding_rules.evaluate(plan)
    assert result.finding == "unlikely_scam"
    assert result.rating == BANDS["unlikely_scam"][0]


def test_decide_and_report_agree_on_the_same_resolved_rating():
    """FR-01 — decide.py's routed outcome and report.compose()'s Findings Rating must always name
    the same Finding; there is no second, disconnected route to a verdict."""
    material = {"item-0": "Hi, see you Saturday for golf?"}
    plan = triage.plan("Is this real?", [material["item-0"]])
    decision, issues = decide.evaluate(plan, material, final=True)
    assert issues == [] and decision is not None
    result = report.compose(decision, plan, material, "flyby-1")
    assert result["outcome"] == decision.outcome == "unlikely_scam"
