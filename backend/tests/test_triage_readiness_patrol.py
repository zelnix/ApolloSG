"""Background Higgins Triage is an evidence-admission check, not a scam verdict."""
from services.triage.store import readiness_patrol_text


def test_ready_is_handoff_not_safe_verdict():
    item = readiness_patrol_text({"ready": True, "reason": "investigable_identifier"})
    assert item["headline"] == "Evidence passed to TC Hawkeye"
    assert "no threat" not in str(item).lower()
    assert "safe" not in str(item).lower()


def test_not_ready_explains_missing_evidence_without_threat_label():
    explanation = "I can’t begin an investigation from this information alone. Please share the message."
    item = readiness_patrol_text({"ready": False, "reason": "no_investigable_subject",
                                  "higginsExplanation": explanation})
    assert item["headline"] == "Investigation could not begin"
    assert item["what_happened"] == explanation
    assert item["what_to_do"] == explanation
    assert "scam" not in str(item).lower()
