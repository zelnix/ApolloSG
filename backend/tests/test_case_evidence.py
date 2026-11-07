"""The case's Evidence record (services/higgins/case_evidence.py): each material fact once, with the stage that found it
first and the later stages that established it too; what points the other way kept and marked; lookups that found
nothing, ApolloSG's knowledge base and bare conclusions never listed as evidence.

Run: cd /app/backend && python -m pytest tests/test_case_evidence.py -q
"""
import pytest

from services.higgins import case_evidence
from services.higgins.contracts import HigginsResponse
from tests.test_tc_flyby_routing import _case, _gateway, _lookups

pytestmark = pytest.mark.anyio


def _response(findings: list[dict], outcome: str = "concerning") -> HigginsResponse:
    assessment = {"concerning": "concern_found", "likely_scam": "concern_found", "confirmed_threat": "concern_found",
                  "no_scam_indicators": "no_concern_found_within_scope", "unable_to_determine": "uncertain"}[outcome]
    return HigginsResponse.model_validate({
        "revision": 1, "overview": "o", "explanationMarkdown": "", "assessment": assessment, "outcome": outcome, "attention": "review",
        "findings": [{"id": f"f{n}", "basis": "observation", "confidence": "medium", "evidenceIds": ["EV-1"], **f} for n, f in enumerate(findings, 1)],
        "completion": "complete"})


def _fact(text: str, signal: str, **extra) -> dict:
    return {"text": text, "signal": signal, "decisive": False, "class": "live_evidence", "source": None, "topic": None, **extra}


def _record(*checks: tuple[str, list[dict]]) -> dict:
    return {"ranAt": "2026-10-28T01:00:00+00:00", "items": {"checks": "EV-CHECKS"},
            "checks": [{"id": f"c{n}", "kind": kind, "facts": facts} for n, (kind, facts) in enumerate(checks, 1)]}


TRIAGE = ("It claims a government rebate (“Energy Bill Relief rebate”), puts a deadline on it to hurry you "
          "(“before rebates drop next week”) and asks you to reply (“Reply YES”).")


def test_the_first_stage_keeps_the_fact_and_a_later_stage_in_its_own_words_confirms_it():
    record = _record(("triage_rules", [_fact(TRIAGE, "concern", ruleId="MSG-24")]))
    response = _response([{"text": "It asks you to reply: “Reply YES”."}, {"text": TRIAGE}], "likely_scam")
    facts = case_evidence.build(response, record, answered_by="tc_flyby_kb", simulated=False)
    assert len(facts) == 1, "the same fact is listed once"
    assert facts[0].text == TRIAGE and facts[0].discovered_by == "higgins_triage"
    assert facts[0].corroborated_by == ["tc_flyby"], "TC Hawkeye reached it in its own words; repeating Triage's words confirms nothing"
    assert facts[0].rule_id == "MSG-24" and facts[0].finding_ids == ["f1", "f2"] and facts[0].stance == "supporting"


def test_magnum_di_confirming_tc_flybys_fact_about_the_same_subject():
    record = _record(("impersonation", [_fact("commbank-notice.net isn't one of CommBank's published domains.", "anomaly")]))
    response = _response([{"text": "The link goes to commbank-notice.net, which is not CommBank's own domain.", "confidence": "high"}])
    [fact] = case_evidence.build(response, record, answered_by="magnum_di", simulated=False)
    assert fact.discovered_by == "tc_flyby" and fact.corroborated_by == ["magnum_di"]
    assert fact.text == "commbank-notice.net isn't one of CommBank's published domains.", "the first finder's own words"
    assert fact.confidence == "high" and fact.finding_ids == ["f1"]


def test_what_points_the_other_way_is_kept_and_marked():
    record = _record(("link", [_fact("Google Safe Browsing doesn't list commbank-notice.net.", "clear"),
                               _fact("commbank-notice.net was registered on 2026-06-01.", "weak")]))
    facts = {f.text: f for f in case_evidence.build(_response([]), record, answered_by="tc_flyby_official", simulated=False)}
    assert facts["Google Safe Browsing doesn't list commbank-notice.net."].stance == "contrary"
    weak = facts["commbank-notice.net was registered on 2026-06-01."]
    assert weak.stance == "supporting" and weak.weak
    clear = case_evidence.build(_response([], "no_scam_indicators"), record, answered_by="tc_flyby_official", simulated=False)
    assert [f.stance for f in clear] == ["supporting", "contrary"], "sides follow the outcome"
    unsure = case_evidence.build(_response([], "unable_to_determine"), record, answered_by="tc_flyby_official", simulated=False)
    assert {f.stance for f in unsure} == {"neutral"}, "an uncertain outcome points neither way"


def test_lookups_that_found_nothing_knowledge_and_bare_conclusions_are_never_evidence():
    record = _record(("link", [_fact("TC Hawkeye's search found no record for brightline-docs.net.", "missing")]),
                     ("scam_pattern", [_fact("Scamwatch (ACCC): “Investment scams”", "context", **{"class": "apollo_knowledge"})]))
    response = _response([{"text": "This message is likely a scam impersonating Brightline."},
                          {"text": "The sender's number couldn't be checked."},
                          {"text": "It asks you to pay invoice 4471 to account 1234 5678 today."}], "concerning")
    facts = case_evidence.build(response, record, answered_by="magnum_di", simulated=True)
    assert [f.text for f in facts] == ["It asks you to pay invoice 4471 to account 1234 5678 today."]
    assert facts[0].discovered_by == "magnum_di" and facts[0].corroborated_by == [] and facts[0].simulated


def test_different_facts_about_one_subject_stay_apart():
    record = _record(("link", [_fact("commbank-notice.net was registered on 2026-06-01.", "weak"),
                               _fact("commbank-notice.net isn't one of CommBank's published domains.", "anomaly")]))
    assert len(case_evidence.build(_response([]), record, answered_by="tc_flyby_official", simulated=False)) == 2


def test_a_message_rules_name_is_its_conclusion_not_evidence():
    name = "Multiple moderate scam indicators form a coherent scam pattern."
    record = _record(("triage_rules", [_fact(name, "concern", ruleId="MSG-22")]))
    response = _response([{"text": name}, {"text": "It asks for money: “Can you transfer $300”."}], "likely_scam")
    [fact] = case_evidence.build(response, record, answered_by="tc_flyby_kb", simulated=False)
    assert fact.text == "It asks for money: “Can you transfer $300”." and fact.discovered_by == "tc_flyby"
    assert fact.stance == "supporting", "a reason the result gives for its outcome supports it"


# ── Through the real job ─────────────────────────────────────────────────────
async def test_a_case_tc_flyby_settles_records_its_evidence_once_each(monkeypatch):
    _gateway(monkeypatch)
    _lookups(monkeypatch, age_days=6)
    _owner, _case_doc, response, _ = await _case([("text", "CommBank: please read the notice about your account changes at https://commbank-notice.net/info")])
    evidence = response["evidence"]
    assert evidence, "the Evidence record is committed with the result"
    texts = [f["text"] for f in evidence]
    assert len(texts) == len(set(texts))
    assert all(f["discoveredBy"] in ("higgins_triage", "tc_flyby") for f in evidence)
    assert any("not CommBank's domain" in t for t in texts)
    safe_browsing = next(f for f in evidence if "not listed by Google Safe Browsing" in f["text"])
    assert safe_browsing["stance"] == "contrary", "a clean listing points the other way in a Concerning case"
    assert not any("found no record" in t or "returned no sourced answer" in t for t in texts), "nothing found is not evidence"
    # Every finding of the result is either evidence or a conclusion — none is lost or listed twice.
    listed = [i for f in evidence for i in f["findingIds"]]
    assert len(listed) == len(set(listed))


async def test_a_case_magnum_di_answers_keeps_tc_flybys_facts_first(monkeypatch):
    from tests.test_tc_flyby_routing import INVOICE
    _gateway(monkeypatch)
    _lookups(monkeypatch)
    _owner, case_doc, response, _ = await _case([("text", INVOICE)])
    assert case_doc["routing"]["answeredBy"] == "magnum_di"
    evidence = response["evidence"]
    assert evidence is not None
    assert {f["discoveredBy"] for f in evidence} <= {"higgins_triage", "tc_flyby", "magnum_di"}
    assert all(f["stance"] in ("supporting", "contrary", "neutral") for f in evidence)
