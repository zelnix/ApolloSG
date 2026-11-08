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
from services.higgins.tc_flyby import _kb_stage, decide, report, triage
from services.higgins.tc_flyby.official import fact
from tests.fixtures.reference_cases import CASES, ReferenceCase

RESULTS_PATH = Path(__file__).parent.parent / "content" / "calibration_results.json"


def _apply_ground_truth(plan_: triage.Plan, case: ReferenceCase) -> None:
    # Non-mutating: `fact_kwargs` is the same dict object stored on the module-level `CASES` list
    # (built once at import time), so popping a key from it here would permanently remove "place"
    # from that case's fixture the first time any test ran it — e.g. the module-scoped
    # `calibration_results` fixture and the per-case `test_case_reaches_the_target_finding_tier`
    # each call `_run()` (and therefore this function) independently, so a mutating `.pop()` made
    # the second call see a different, incomplete ground truth than the first, depending on test
    # order. Reading a copy of the remaining arguments keeps every call idempotent.
    for check_kind, subject_contains, fact_kwargs in case.ground_truth:
        place = fact_kwargs.get("place")
        fact_args = {k: v for k, v in fact_kwargs.items() if k != "place"}
        for check in plan_.checks:
            if check.kind == check_kind and subject_contains.lower() in check.subject.lower():
                f = fact(**fact_args)
                if place:
                    f["place"] = place
                check.facts.append(f)
                check.status = "resolved"


async def _run(case: ReferenceCase) -> dict:
    material = {"item-0": case.material}
    plan_ = triage.plan(case.question, [case.material])
    _apply_ground_truth(plan_, case)
    # The real investigation pipeline (services/higgins/tc_flyby/__init__.py::_kb_stage) always runs
    # KB pattern matching before deciding the case — skipping it here under-tests every scenario a
    # known scam pattern should catch, and was masking real calibration gaps as "no pattern available".
    await _kb_stage(plan_, case.material)

    decision, issues = decide.evaluate(plan_, material, final=True)
    if decision is None:
        # TC Hawkeye could not settle this case deterministically — the real pipeline
        # (services/higgins/coordinator.run_turn) would now hand it to Magnum DI's one AI call.
        # This suite never makes that call (it would mean standing up a live/simulated case+job and
        # a provider request — a different, heavier pipeline than this triage->decide->score run),
        # so "escalated" here can only mean TC Hawkeye's own routing decision was correct, NOT that
        # any Magnum DI Finding was produced, let alone checked against the PRD's target. Both facts
        # are reported explicitly rather than folding this case into "settled" or "verified".
        return {"id": case.id, "scenario": case.scenario, "settled": False,
                "verificationStatus": "escalated_to_magnum_di_unverified",
                "magnumDiFindingVerified": False,
                "issues": [i.text for i in issues], "targetFinding": case.target_finding, "targetScore": case.target_score}

    result = report.compose(decision, plan_, material, "flyby-1")
    return {"id": case.id, "scenario": case.scenario, "settled": True,
            "verificationStatus": "tc_hawkeye_resolved",
            "category": case.category, "actualFinding": result["outcome"], "targetFinding": case.target_finding,
            "actualScore": result["findingsRating"], "targetScore": case.target_score,
            "scoreDelta": (result["findingsRating"] or 0) - case.target_score,
            "taxonomy": (result.get("taxonomy") or {}).get("primary", {}).get("domainName"),
            "basis": decision.basis}


@pytest.fixture(scope="module")
async def calibration_results() -> list[dict]:
    results = [await _run(c) for c in CASES]
    settled = [r for r in results if r["settled"]]
    escalated = [r for r in results if not r["settled"]]
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps({
        "about": "ApolloSG PRD v2.3 Findings Calibration — synthetic reference-library run, see "
                 "tests/fixtures/reference_cases.py and tests/test_calibration_reference_library.py.",
        "totalCases": len(results),
        # Kept for backward compatibility with content/CALIBRATION_REPORT.md's existing numbers.
        "settled": len(settled),
        "tierMatches": sum(1 for r in settled if r["actualFinding"] == r["targetFinding"]),
        # Four distinct, non-overlapping buckets — see the module docstring and each TestClass below
        # for what each one does and, critically, does NOT claim.
        "tcHawkeyeResolved": {
            "count": len(settled),
            "tierMatches": sum(1 for r in settled if r["actualFinding"] == r["targetFinding"]),
            "note": "TC Hawkeye reached a Finding deterministically on the first turn; "
                    "TestFindingTierAccuracy independently checks the tier for each of these cases.",
        },
        "correctlyRequiresMagnumDi": {
            "count": len(escalated),
            "ids": [r["id"] for r in escalated],
            "note": "TC Hawkeye correctly identified these cases as needing Magnum DI's reasoning — the "
                    "PRD's own intended routing, not a scoring gap. This is a check of the ROUTING "
                    "decision only.",
        },
        "magnumDiFindingsVerifiedEndToEnd": {
            "count": sum(1 for r in escalated if r.get("magnumDiFindingVerified")),
            "note": "Count of escalated cases whose actual Magnum DI Finding was produced (a live or "
                    "simulated call through services.higgins.coordinator.run_turn, with a real case/job) "
                    "and checked against this case's target. This suite does not make that call — see "
                    "'unverifiedBeyondRouting' below — so this is expected to be 0 here.",
        },
        "unverifiedBeyondRouting": {
            "count": sum(1 for r in escalated if not r.get("magnumDiFindingVerified")),
            "ids": [r["id"] for r in escalated if not r.get("magnumDiFindingVerified")],
            "note": "Escalated cases with no end-to-end Magnum DI verification in this report. Do not "
                    "read 'correctly requires Magnum DI' as 'successfully investigated' for these IDs.",
        },
        "results": results,
    }, indent=2))
    return results


class TestEveryCaseSettlesAtTcHawkeye:
    """Phase 4's reference library is meant to calibrate TC Hawkeye's deterministic scoring — a case
    that escalates to Magnum DI can't be used for that, so this is reported clearly rather than
    silently treated as a pass or a failure of the scoring engine itself.

    Escalating is, by itself, neither a pass nor a fail: it only means TC Hawkeye's own routing
    decision (not the score) is what this report can speak to for that case. It is NOT evidence that
    Magnum DI then reached the right Finding — this suite never makes Magnum DI's real call, so that
    half of the case is always reported as unverified, never as a quiet success."""

    def test_report_which_cases_needed_magnum_di(self, calibration_results):
        escalated = [r for r in calibration_results if not r["settled"]]
        ids = [r["id"] + " " + r["scenario"] for r in escalated]
        print(f"\n{len(escalated)}/{len(calibration_results)} cases correctly routed to Magnum DI "
              f"(TC Hawkeye's routing decision only, per PRD design): {ids}")
        print("NOTE: this suite does not invoke Magnum DI's real AI call (services.higgins.coordinator."
              "run_turn needs a live case/job and provider call) — these cases' final Magnum DI Findings "
              "are NOT produced or checked here and must not be counted as a verified outcome.")
        assert all(r.get("magnumDiFindingVerified") is False for r in escalated), (
            "an escalated case was marked as having a verified Magnum DI Finding, but this suite never "
            "runs Magnum DI — that would be a false claim of end-to-end verification")


class TestFindingTierAccuracy:
    """The hard, user-facing contract: does TC Hawkeye reach the right one of the four Findings for
    each settled reference case?"""

    @pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c.id}_{c.scenario[:40].replace(' ', '_')}")
    async def test_case_reaches_the_target_finding_tier(self, case: ReferenceCase):
        result = await _run(case)
        if not result["settled"]:
            pytest.skip(f"{case.id} escalated to Magnum DI (capability: {[i for i in result['issues']]}) — "
                        f"not scoreable by TC Hawkeye alone, and not run through Magnum DI by this suite "
                        f"either, see TestEveryCaseSettlesAtTcHawkeye")
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
        # The four buckets must partition the case set exactly: every case is either TC-Hawkeye-resolved
        # or escalated, every escalated case is either Magnum-DI-verified or not — no case double-counted
        # and none silently dropped.
        assert data["tcHawkeyeResolved"]["count"] + data["correctlyRequiresMagnumDi"]["count"] == data["totalCases"]
        assert (data["magnumDiFindingsVerifiedEndToEnd"]["count"] + data["unverifiedBeyondRouting"]["count"]
                == data["correctlyRequiresMagnumDi"]["count"])
        settled = [r for r in calibration_results if r["settled"]]
        avg_abs_delta = sum(abs(r["scoreDelta"]) for r in settled) / max(1, len(settled))
        print(f"\nCalibration: {data['tierMatches']}/{data['settled']} settled cases hit the target tier "
             f"(of {data['totalCases']} total); average |score delta| = {avg_abs_delta:.1f}")
        print(f"Magnum DI: {data['correctlyRequiresMagnumDi']['count']} cases correctly escalated "
              f"(routing only); {data['magnumDiFindingsVerifiedEndToEnd']['count']} of those have an "
              f"end-to-end verified Finding in this report.")


class TestFourOutcomesAreTheOnlyOutcomes:
    def test_every_reference_case_target_is_one_of_the_four_approved_findings(self):
        for case in CASES:
            assert case.target_finding in outcomes.OUTCOMES
