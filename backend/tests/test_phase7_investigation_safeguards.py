"""Phase 7 regression tests for the existing authoritative investigation chain."""
from types import SimpleNamespace
from services.higgins.coordinator import decision_requires_independent_review

def test_unresolved_hawkeye_cannot_be_downgraded_to_local():
    assert decision_requires_independent_review(SimpleNamespace(resolved=False))

def test_resolved_hawkeye_does_not_force_magnum():
    assert not decision_requires_independent_review(SimpleNamespace(resolved=True))

def test_missing_hawkeye_resolution_fails_conservatively():
    assert decision_requires_independent_review(SimpleNamespace())
