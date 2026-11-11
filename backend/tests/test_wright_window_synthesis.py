from services.higgins.window_synthesis import synthesise_window_interpretations

def item(wid, label, ref):
    return {"windowId": wid, "result": {"classification": label, "supportingEvidenceIds": [ref], "uncertainty": None}}

def test_conflicting_windows_preserved():
    result = synthesise_window_interpretations(
        [item("a", "scam_indicators", "e1"), item("b", "legitimate_context", "e2")],
        {"a", "b"}, {"e1", "e2"})
    assert result.status == "conflicting"
    assert result.contradictory
    assert result.evidence_ids == ("e1", "e2")

def test_missing_window_is_limited():
    result = synthesise_window_interpretations([item("a", "ambiguous", "e1")], {"a", "b"}, {"e1"})
    assert result.status == "limited"

def test_cross_device_citation_is_rejected():
    result = synthesise_window_interpretations([item("a", "scam_indicators", "foreign")], {"a"}, {"e1"})
    assert result.status == "limited"

def test_duplicate_window_is_rejected():
    result = synthesise_window_interpretations([item("a", "ambiguous", "e1"), item("a", "ambiguous", "e1")], {"a"}, {"e1"})
    assert result.status == "limited"
