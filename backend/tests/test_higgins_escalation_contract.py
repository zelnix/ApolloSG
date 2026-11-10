"""Standalone contract checks for the Higgins Escalation Assessment boundary.

Runs without the integration-suite conftest; no database or provider required.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_escalation_not_decided_by_hawkeye():
    source = (ROOT / "services/higgins/coordinator.py").read_text()
    assert 'assessment = await _await_escalation_assessment(' in source
    assert 'decision = assessment["decision"]' in source
    assert 'if decision == "escalate":' in source
    assert 'if not fly_by.resolved:' not in source


def test_unavailable_assessment_does_not_trigger_cloud():
    source = (ROOT / "services/higgins/coordinator.py").read_text()
    start = source.index('assessment = await _await_escalation_assessment(')
    unavailable = source.index('if assessment is None:', start)
    cloud = source.index('if decision == "escalate":', unavailable)
    assert 'return Outcome("device_unavailable"' in source[unavailable:cloud]


def test_magnum_unavailability_retains_local_finding_path():
    source = (ROOT / "services/higgins/coordinator.py").read_text()
    start = source.index('if decision == "escalate":')
    end = source.index('slm_finding = await _await_case_finding(', start)
    assert 'magnum_available = await _magnum_external_evidence(' in source[start:end]
    assert 'if not magnum_available:' in source[start:end]


def test_assessment_contract_requires_cited_evidence():
    source = (ROOT / "services/higgins/slm_contract.py").read_text()
    assert 'class SLMEscalationAssessment(Wire):' in source
    assert 'evidence_ids: list[str] = Field(min_length=1' in source
    assert 'if assessment is None or any(eid not in permitted' in source
