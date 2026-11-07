"""Acceptance: the UNIﬁed Energy SMS through the server's Higgins Triage (mirror of the phone's), and TC Hawkeye's
method lines kept out of what isn't certain."""
import pytest

from services.triage import Outcome, evaluate
from services.triage_engine import _rule_evidence, disguised_words, organisation_named

SMS = ("Good morning! It's UNI\ufb01ed Energy here. Lock in higher STC savings before rebates drop next week and secure "
       "installation before year-end.\n\nReply YES and your preferred call time:\n1) 10am-12:30pm")


def _triage(text: str):
    return evaluate(_rule_evidence({"source_type": "text", "text_preview": text}, [], {}))


def test_the_server_reads_the_same_signs_as_the_phone():
    assert organisation_named(SMS) == "UNI\ufb01ed Energy"
    assert disguised_words(SMS) == ["UNI\ufb01ed"]
    result = _triage(SMS)
    assert result.outcome is Outcome.POSSIBLE_THREAT
    assert [r.rule_id for r in result.met_rules] == ["MSG-23", "MSG-24"]
    assert [r.rule_id for r in _triage(SMS.replace("\ufb01", "fi")).met_rules] == ["MSG-24"]


def test_never_a_threat_on_their_own():
    assert organisation_named("Hi Mum it's Sarah here, call me") is None
    for text in ("Hi Mum it's Sarah here, call me when you can", "Bright Solar: your install is booked for Tuesday. Reply STOP to opt out.",
                 "Government battery rebates are available. Visit your state government's website for details."):
        assert _triage(text).outcome is Outcome.NO_THREAT, text


@pytest.mark.anyio
async def test_tc_flyby_settles_what_triage_flagged_as_concerning_never_as_no_scam_indicators(monkeypatch):
    """Apollo detects → Higgins Triage flags it → TC Hawkeye finds nothing more → settled as Concerning, with the message's
    own words as the findings. Magnum DI isn't called: it couldn't change what to do."""
    from tests.test_tc_flyby_routing import _case, _gateway, _lookups
    calls = _gateway(monkeypatch)
    _lookups(monkeypatch)
    _owner, case, response, _ = await _case([("text", SMS)], message="Investigate this captured text-message notification.")
    assert calls == [], "Magnum DI's deeper analysis couldn't change the outcome or what to do"
    assert response["outcome"] == "likely_scam" and response["assessment"] == "concern_found"
    assert response["attention"] == "review" and response["completion"] == "complete"
    flyby = case["routing"]["tc_flyby"]
    assert flyby["resolved"] is True and flyby["basis"] == "signals" and flyby["answeredBy"] == "tc_flyby_official"
    assert {"kind": "triage_rules", "status": "resolved", "route": "triage_rules"} in flyby["checks"]
    texts = [f["text"] for f in response["findings"]]
    assert texts[0] == "It writes “UNI\ufb01ed Energy” with “\ufb01” in place of ordinary letters. A real business has no reason to do that."
    assert texts[1] == ("It claims a government rebate (“STC savings”), puts a deadline on it to hurry you (“before rebates drop next week”) "
                        "and asks you to reply (“Reply YES”).")
    assert response["overview"].startswith("What you sent raises a concern: It writes “UNI\ufb01ed Energy”")
    assert "No scam indicators" not in response["overview"]
    assert "Higgins Triage's message rules" in response["scope"]


@pytest.mark.anyio
async def test_a_message_triage_does_not_flag_is_still_settled_by_tc_flyby_alone(monkeypatch):
    from tests.test_tc_flyby_routing import _case, _gateway
    calls = _gateway(monkeypatch)
    _owner, case, response, _ = await _case([("text", SMS.replace("\ufb01", "fi").replace("Reply YES", "Call us"))])
    assert calls == [] and response["outcome"] != "concerning"
    assert not any(c["kind"] == "triage_rules" for c in case["routing"]["tc_flyby"]["checks"])


def test_tc_flyby_method_lines_are_said_under_how_apollo_checked_not_what_isnt_certain():
    from services.higgins.tc_flyby.report import _method, _not_found

    class C:  # a check that found nothing, and one left open
        def __init__(self, status, facts, open_issue=None):
            self.status, self.facts, self.open_issue, self.subject = status, facts, open_issue, "UNI\ufb01ed Energy"
    checks = [C("not_found", [{"text": "TC Hawkeye's search found no record for UNI\ufb01ed Energy", "signal": "missing"}]),
              C("not_needed", [], "Impersonation: whether the material genuinely comes from UNI\ufb01ed Energy.")]
    assert _not_found(checks) == ["TC Hawkeye's search found no record for UNI\ufb01ed Energy."]
    how = _method("TC Hawkeye checked the submitted material. Magnum DI's deeper analysis wasn't needed.", checks, not_taken=True)
    assert how.endswith("So these weren't taken further: impersonation (whether the material genuinely comes from UNI\ufb01ed Energy). "
                        "TC Hawkeye's search found no record for UNI\ufb01ed Energy.")
