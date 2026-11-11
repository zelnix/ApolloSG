from services.higgins.evidence_windows import build_windows, validate_window_coverage
import pytest

def test_complete_long_source_and_multiple_sources():
    sources = [("a", "A" * 25000), ("b", "B" * 4200)]
    inventory = build_windows(sources)
    assert len(inventory.windows) > 10
    assert all(w.text == dict(sources)[w.evidence_id][w.start:w.end] for w in inventory.windows)
    ids = {w.window_id for w in inventory.windows}
    assert validate_window_coverage(sources, inventory, ids)

def test_missing_window_never_counts_complete():
    sources = [("a", "A" * 10000)]
    inventory = build_windows(sources)
    ids = {w.window_id for w in inventory.windows}
    ids.remove(inventory.windows[-1].window_id)
    assert not validate_window_coverage(sources, inventory, ids)

def test_changed_source_never_counts_complete():
    sources = [("a", "A" * 3000)]
    inventory = build_windows(sources)
    assert not validate_window_coverage([("a", "B" * 3000)], inventory,
                                        {w.window_id for w in inventory.windows})

def test_rejects_duplicate_source_id_and_invalid_budget():
    with pytest.raises(ValueError):
        build_windows([("a", "x"), ("a", "y")])
    with pytest.raises(ValueError):
        build_windows([("a", "x")], max_chars=200, overlap=100)
