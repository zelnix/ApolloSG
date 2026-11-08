"""Unified Evidence Classification & Six-Dimension Findings Rating PRD (v1.0, 8 Nov 2026) §7.4 —
Phase 2: the actual Magnum DI completion pathway, traced and locked in with direct tests.

Investigation finding: a `finding_rules.evaluate_for_magnum()` placeholder existed, claiming to "map
a Magnum DI outcome to the new finding codes using the same rules", but its reconciliation branch was
an empty `pass` and it was never called anywhere in the pipeline — confirmed dead code, removed.

The real, working mechanism for "Magnum DI's result re-enters the same evidence resolver, no
model-confidence-only overrides" (FR-06) is exercised on every Magnum DI turn and had zero direct
test coverage before this file: `decide.floor()` turns TC Hawkeye's own provisional/established
Decision into a `{outcome, established, minimum, findings}` contract (also carried into Magnum DI's
own brief via report.magnum_brief(), so the model is told what it can't go below), and
`validation.floor_errors()` enforces it — an answer that tries to go below the floor, or that claims
"scam"/"likely_scam" backed by only low-confidence findings, is rejected outright, never silently
accepted. This is deliberately a different shape from finding_rules.py's S/N/L waterfall +
scoring.reconcile(): Magnum's output is a qualitative AI judgement with no six-dimension rating
attached (response_schema.py's findingsRating/findingsRatingBreakdown are explicitly TC-Hawkeye-only
and always null on a Magnum-answered response — the model is told "the model never sets this").
"""
from types import SimpleNamespace

from services.higgins.tc_flyby import decide, finding_rules, triage
from services.higgins.validation import floor_errors, validate

EVIDENCE = {"ev-1"}
SOURCES = {"src-1"}
CAPS: set[str] = set()


def _base_response(**overrides):
    base = {
        "overview": "Test overview.", "explanationMarkdown": "# Explanation\nDetails.",
        "assessment": "concern_found", "attention": "review", "attentionReason": None,
        "findings": [], "uncertainties": [], "scope": "Tested the submitted evidence.",
        "sourceIds": [], "remainingEvidenceIds": [], "actions": [], "recommendedActionIndex": None,
        "question": None, "completion": "complete",
    }
    base.update(overrides)
    return base


def _finding(outcome_id: str, *, supersedes: list[str] | None = None, confidence: str = "high") -> dict:
    return {"text": f"Resolves {outcome_id}.", "basis": "observation", "confidence": confidence,
            "evidenceIds": ["ev-1"], "sourceIds": [], "supersedesFindingIds": supersedes or []}


# ── evaluate_for_magnum() is gone; the real mechanism is decide.floor()/validation.floor_errors() ──

def test_evaluate_for_magnum_placeholder_was_removed():
    assert not hasattr(finding_rules, "evaluate_for_magnum")


# ── decide.floor(): what TC Hawkeye's own Decision becomes as a floor contract ──────────────────

def test_floor_is_none_with_no_decision_and_no_credential_ask():
    plan = triage.plan("Is this real?", ["Hi, see you Saturday for golf?"])
    assert decide.floor(plan, None) is None


def test_floor_is_minimum_likely_scam_when_material_asks_for_a_secret():
    """A request for a password, PIN, one-time code or card details is established threat evidence
    in itself — Magnum's outcome can never go below "likely_scam", even with no Decision yet."""
    plan = triage.plan("Is this real?", ["Reply with the OTP we just texted you to confirm your refund."])
    f = decide.floor(plan, None)
    assert f is not None and f["minimum"] == "likely_scam" and f["established"] is False


def test_floor_is_established_for_a_threat_based_decision():
    plan = triage.plan("Is this real?", ["Hi, see you Saturday for golf?"])
    found = decide.Decision("tc_flyby_official", "scam", "threat")
    f = decide.floor(plan, found)
    assert f["outcome"] == "scam" and f["established"] is True


def test_floor_is_provisional_for_a_pattern_based_decision():
    plan = triage.plan("Is this real?", ["Hi, see you Saturday for golf?"])
    plan.pattern = {"name": "Test pattern", "stage": "full", "found": [("matches a known scam pattern", "golf")], "ask": None}
    found = decide.Decision("tc_flyby_kb", "likely_scam", "pattern")
    f = decide.floor(plan, found)
    assert f["outcome"] == "likely_scam" and f["established"] is False


# ── validation.floor_errors(): the actual ratchet enforced on every Magnum DI answer ────────────

def test_established_floor_can_never_be_lowered():
    floor = {"outcome": "scam", "established": True, "minimum": None, "findings": []}
    model = SimpleNamespace(outcome="unlikely_scam", findings=[])
    errors = floor_errors(model, floor)
    assert errors and "contradicts established threat evidence" in errors[0]


def test_established_floor_matched_or_exceeded_is_fine():
    floor = {"outcome": "scam", "established": True, "minimum": None, "findings": []}
    assert floor_errors(SimpleNamespace(outcome="scam", findings=[]), floor) == []


def test_magnum_can_escalate_above_an_established_floor_with_new_evidence():
    """Upward movement is never blocked — Magnum DI's own web search can still confirm a stronger
    verdict than TC Hawkeye's floor; only going BELOW it is rejected (FR-06: new verified evidence
    re-enters the same resolver, it never gets diluted downward by mere model confidence)."""
    floor = {"outcome": "likely_scam", "established": True, "minimum": None, "findings": []}
    assert floor_errors(SimpleNamespace(outcome="scam", findings=[]), floor) == []


def test_provisional_floor_rejected_without_a_superseding_finding():
    floor = {"outcome": "likely_scam", "established": False, "minimum": None,
            "findings": [{"id": "P1", "text": "Full pattern match."}]}
    model = SimpleNamespace(outcome="unlikely_scam", findings=[])
    errors = floor_errors(model, floor)
    assert errors and "TC Hawkeye's provisional" in errors[0]


def test_provisional_floor_lowered_only_with_a_cited_superseding_finding():
    floor = {"outcome": "likely_scam", "established": False, "minimum": None,
            "findings": [{"id": "P1", "text": "Full pattern match."}]}
    # Claims to supersede P1 but cites no evidence/source at all — still rejected.
    uncited = SimpleNamespace(outcome="unlikely_scam",
                              findings=[SimpleNamespace(supersedes_finding_ids=["P1"], evidence_ids=[], source_ids=[])])
    assert floor_errors(uncited, floor) != []
    # Supersedes P1 and cites resolving evidence — accepted.
    cited = SimpleNamespace(outcome="unlikely_scam",
                            findings=[SimpleNamespace(supersedes_finding_ids=["P1"], evidence_ids=["ev-1"], source_ids=[])])
    assert floor_errors(cited, floor) == []


def test_credential_ask_minimum_blocks_a_below_likely_outcome_even_without_a_decision():
    floor = {"outcome": None, "established": False, "minimum": "likely_scam", "findings": []}
    assert floor_errors(SimpleNamespace(outcome="unlikely_scam", findings=[]), floor) != []
    assert floor_errors(SimpleNamespace(outcome="likely_scam", findings=[]), floor) == []


def test_no_floor_means_no_errors():
    assert floor_errors(SimpleNamespace(outcome="scam", findings=[]), None) == []
    assert floor_errors(SimpleNamespace(outcome=None, findings=[]), {"outcome": "scam", "established": True}) == []


# ── The same ratchet enforced end-to-end through validate(), as Magnum DI's answer actually is ──

def test_validate_rejects_a_magnum_answer_below_the_established_floor():
    floor = {"outcome": "scam", "established": True, "minimum": None, "findings": []}
    data = _base_response(outcome="unlikely_scam", assessment="no_concern_found_within_scope", attention="none")
    response, errors = validate(data, revision=1, evidence_ids=EVIDENCE, source_ids=SOURCES, capability_ids=CAPS,
                                pending_question=None, provider_complete=True, floor=floor)
    assert response is None and any("contradicts established threat evidence" in e for e in errors)


def test_validate_accepts_a_magnum_answer_that_meets_the_floor():
    floor = {"outcome": "scam", "established": True, "minimum": None, "findings": []}
    data = _base_response(outcome="scam", findings=[_finding("scam")], assessment="concern_found", attention="urgent",
                          attentionReason="Confirmed scam.",
                          actions=[{"kind": "instruction", "label": "Stop", "instruction": "Stop and don't reply.",
                                    "capabilityId": None, "sourceIds": [], "desiredField": None, "desiredValue": None}],
                          recommendedActionIndex=0)
    response, errors = validate(data, revision=1, evidence_ids=EVIDENCE, source_ids=SOURCES, capability_ids=CAPS,
                                pending_question=None, provider_complete=True, floor=floor)
    assert response is not None, f"Valid, floor-meeting response rejected: {errors}"


def test_validate_rejects_scam_outcome_backed_only_by_low_confidence_findings():
    """FR-06's "no model-confidence-only overrides": a concern outcome needs at least one
    medium/high-confidence finding — the model can't assert "scam" purely on its own low-confidence
    judgement."""
    data = _base_response(outcome="scam", assessment="concern_found", attention="urgent",
                          attentionReason="Looks like a scam.", findings=[_finding("scam", confidence="low")],
                          actions=[{"kind": "instruction", "label": "Stop", "instruction": "Stop and don't reply.",
                                    "capabilityId": None, "sourceIds": [], "desiredField": None, "desiredValue": None}],
                          recommendedActionIndex=0)
    response, errors = validate(data, revision=1, evidence_ids=EVIDENCE, source_ids=SOURCES, capability_ids=CAPS,
                                pending_question=None, provider_complete=True)
    assert response is None and any("low' confidence" in e for e in errors)


def test_findings_rating_is_explicitly_tc_hawkeye_only_and_null_for_magnum():
    """TC Hawkeye's six-dimension rating is never asked of, or accepted from, the model directly —
    it's attached to report.compose()'s own dict before validation; a Magnum-answered response (no
    findingsRating in its JSON at all) validates with it left null, never fabricated."""
    data = _base_response(outcome="likely_scam", findings=[_finding("likely_scam")])
    response, errors = validate(data, revision=1, evidence_ids=EVIDENCE, source_ids=SOURCES, capability_ids=CAPS,
                                pending_question=None, provider_complete=True)
    assert response is not None, f"rejected: {errors}"
    assert response.findings_rating is None and response.findings_rating_breakdown is None
