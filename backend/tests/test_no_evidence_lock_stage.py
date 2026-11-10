"""Regression guard: Evidence Lock is not a separate investigation stage.

Evidence storage, provenance, accepted turn commits and the existing Evidence tab
remain part of ApolloSG. This test guards the routing contract, not UI wording.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_investigation_coordinator_has_no_evidence_lock_stage():
    source = (ROOT / "services/higgins/coordinator.py").read_text(encoding="utf-8")
    assert "await tc_flyby.investigate(" in source
    assert "await _await_case_finding(" in source
    assert "await _commit_slm_finding(" in source
    assert "evidence_lock" not in source.lower()
    assert "evidencelock" not in source.lower()
    assert "Evidence Lock" not in source


def test_existing_evidence_and_findings_persistence_are_retained():
    coordinator = (ROOT / "services/higgins/coordinator.py").read_text(encoding="utf-8")
    repository = (ROOT / "services/higgins/repository.py").read_text(encoding="utf-8")
    assert "await repo.list_evidence(" in coordinator
    assert "async def stage_turn(" in repository
    assert "async def accept_turn(" in repository
    assert "async def accepted_turns(" in repository
