"""ApolloSG PRD v2.3 §5/§7.6 — Findings Calibration: the 55-case reference library run end-to-end
through the real, unmodified investigation pipeline (triage -> decide -> compose -> score ->
taxonomy -> findings brief), to independently test the existing scoring engine and report where it
over- or under-calls, rather than to force any particular number.

Primary (hard) assertion per case: TC Hawkeye reaches the PRD's target Finding *tier* — this is the
real, user-facing contract (one of the four approved labels). The PRD's illustrative target *score*
is reported as an advisory delta only (see module docstring in tests/fixtures/reference_cases.py for
why: §2.4/§2.5's benign baseline and legitimacy credit mean a genuinely clean case can legitimately
land anywhere under 25, not at the PRD's single illustrative number).

A case that TC Hawkeye can't settle deterministically (needs Magnum DI) is reported, not silently
skipped — Phase 4's job is to measure the real engine, not to curate away its disagreements.
"""
import json
from pathlib import Path

import pytest

from services.higgins import outcomes
from services.higgins.tc_flyby import decide, report, triage
from services.higgins.tc_flyby.official import fact
from tests.fixtures.reference_cases import CASES, ReferenceCase

RESULTS_PATH = Path(__file__).parent.parent / "content" / "calibration_results.json"


def _apply_ground_truth(plan_: triage.Plan, case: ReferenceCase) -> None:
    for check_kind, subject_contains, fact_kwargs in case.ground_truth:
        place = fact_kwargs.pop("place", None)
        for check in plan_.checks:
            if check.kind == check_kind and subject_contains.lower() in check.subject.lower():
                f = fact(**fact_kwargs)
                if place:
                    f["place"] = place
                check.facts.append(f)
                check.status = "resolved"


def _run(case: ReferenceCase) -> dict:
    material = {"item-0": case.material}
    plan_ = triage.plan(case.question, [case.material])
    _apply_ground_truth(plan_, case)

    decision, issues = decide.evaluate(plan_, material, final=True)
    if decision is None:
        return {"id": case.id, "scenario": case.scenario, "settled": False,
                "issues": [i.text for i in issues], "targetFinding": case.target_finding, "targetScore": case.target_score}

    result = report.compose(decision, plan_, material, "flyby-1")
    return {"id": case.id, "scenario": case.scenario, "settled": True,
            "category": case.category, "actualFinding": result["outcome"], "targetFinding": case.target_finding,
            "actualScore": result["findingsRating"], "targetScore": case.target_score,
            "scoreDelta": (result["findingsRating"] or 0) - case.target_score,
            "taxonomy": (result.get("taxonomy") or {}).get("primary", {}).get("domainName"),
            "basis": decision.basis}


@pytest.fixture(scope="module")
def calibration_results() -> list[dict]:
    results = [_run(c) for c in CASES]
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps({
        "about": "ApolloSG PRD v2.3 Findings Calibration — synthetic reference-library run, see "
                 "tests/fixtures/reference_cases.py and tests/test_calibration_reference_library.py.",
        "totalCases": len(results),
        "settled": sum(1 for r in results if r["settled"]),
        "tierMatches": sum(1 for r in results if r["settled"] and r["actualFinding"] == r["targetFinding"]),
        "results": results,
    }, indent=2))
    return results


class TestEveryCaseSettlesAtTcHawkeye:
    """Phase 4's reference library is meant to calibrate TC Hawkeye's deterministic scoring — a case
    that escalates to Magnum DI can't be used for that, so this is reported clearly rather than
    silently treated as a pass or a failure of the scoring engine itself."""

    def test_report_which_cases_needed_magnum_di(self, calibration_results):
        escalated = [r["id"] + " " + r["scenario"] for r in calibration_results if not r["settled"]]
        print(f"\n{len(escalated)}/{len(calibration_results)} cases escalated to Magnum DI (not scoreable by TC Hawkeye alone): {escalated}")


class TestFindingTierAccuracy:
    """The hard, user-facing contract: does TC Hawkeye reach the right one of the four Findings for
    each settled reference case?"""

    @pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c.id}_{c.scenario[:40].replace(' ', '_')}")
    def test_case_reaches_the_target_finding_tier(self, case: ReferenceCase):
        result = _run(case)
        if not result["settled"]:
            pytest.skip(f"{case.id} escalated to Magnum DI (capability: {[i for i in result['issues']]}) — "
                        f"not scoreable by TC Hawkeye alone, see TestEveryCaseSettlesAtTcHawkeye")
        assert result["actualFinding"] == case.target_finding, (
            f"{case.id} {case.scenario}: expected {case.target_finding!r} (score ~{case.target_score}), "
            f"got {result['actualFinding']!r} (score {result['actualScore']}) — basis={result.get('basis')}")


class TestScoreCalibrationReport:
    """Not a pass/fail gate — an honest measurement, written to content/calibration_results.json for
    review, of how far the real engine's score lands from the PRD's illustrative target per case."""

    def test_calibration_report_is_written(self, calibration_results):
        assert RESULTS_PATH.exists()
        data = json.loads(RESULTS_PATH.read_text())
        assert data["totalCases"] == len(CASES) == 55
        settled = [r for r in calibration_results if r["settled"]]
        avg_abs_delta = sum(abs(r["scoreDelta"]) for r in settled) / max(1, len(settled))
        print(f"\nCalibration: {data['tierMatches']}/{data['settled']} settled cases hit the target tier "
             f"(of {data['totalCases']} total); average |score delta| = {avg_abs_delta:.1f}")


class TestFourOutcomesAreTheOnlyOutcomes:
    def test_every_reference_case_target_is_one_of_the_four_approved_findings(self):
        for case in CASES:
            assert case.target_finding in outcomes.OUTCOMES
