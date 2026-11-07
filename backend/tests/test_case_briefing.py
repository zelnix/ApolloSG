"""Subject → Finding → Result survives every step, and the Higgins Case Briefing every surface shows.

The Stoko acceptance case: an email from hello@stoko.com, checked. The user-facing explanation keeps "stoko.com",
"hello@stoko.com", that no scam warning was found for "stoko.com", that hello@stoko.com is a published Stoko
contact, and the actual unresolved reason — and it never says "Needs you" without a decision the person owes.

Run: cd /app/backend && python -m pytest tests/test_case_briefing.py -q
"""
from dataclasses import replace

import pytest

from services.higgins import explain
from services.higgins.contracts import ActionProposal, Finding, HigginsResponse, ModelFinding, Question
from services.higgins.explain import facts as facts_mod
from services.higgins.explain import fidelity, render
from services.higgins.validation import deduplicate_findings

UNRESOLVED = "Apollo can't confirm who actually sent this."


def stoko(**over) -> HigginsResponse:
    """The Stoko case as Magnum DI answered it: the website's warning check names no subject of its own."""
    base = dict(
        revision=1,
        overview="The email comes from hello@stoko.com, a published Stoko customer-service address, and nothing in it raises a concern.",
        explanation_markdown=("**What was found**\n- hello@stoko.com is a published Stoko customer-service address.\n"
                              "- No scam warning was found for the website.\n\n**What it means**\n"
                              "The sender's address is one Stoko publishes, and no safety source warns about the website."),
        assessment="no_concern_found_within_scope", outcome="no_scam_indicators", attention="none", attention_reason=None,
        findings=[Finding(id="f1", text="hello@stoko.com is a published Stoko customer-service address.", basis="observation",
                          confidence="high", evidence_ids=["e1"], source_ids=["s1"]),
                  Finding(id="f2", text="No scam warning was found for the website.", basis="observation", confidence="medium",
                          evidence_ids=["e1"])],
        uncertainties=[UNRESOLVED], scope="Magnum DI examined the submitted email.", source_ids=["s1"],
        actions=[], recommended_action_id=None, completion="complete")
    base.update(over)
    return HigginsResponse(**base)


SOURCES = [{"id": "s1", "url": "https://stoko.com/contact", "title": "Contact Stoko", "authority": "self_claimed", "retrieval": "fetched"}]


def _case(response=None):
    return explain.explain_case(response or stoko(), answered_by="magnum_di", routing={}, sources=SOURCES, gates=["email"])


def test_every_finding_keeps_subject_check_and_result():
    f = facts_mod.build(stoko(), answered_by="magnum_di", routing={}, sources=SOURCES, gates=["email"])
    shaped = {x["id"]: x for x in f.structure()["findings"]}
    assert shaped["f1"] | {} == {**shaped["f1"], "subject": "hello@stoko.com", "subject_type": "email", "organisation": "Stoko",
                                  "check": "official_contact", "result": "OFFICIAL",
                                  "finding": "hello@stoko.com is a published Stoko customer-service address."}
    # A finding that names its subject only as "the website" is tied to the one website the result names.
    assert shaped["f2"]["subject"] == "stoko.com" and shaped["f2"]["check"] == "reputation" and shaped["f2"]["result"] == "NOT_LISTED"
    assert shaped["f2"]["finding"] == 'No scam warning was found for "stoko.com".'
    assert shaped["f1"]["evidence"] == {"evidence_ids": ["e1"], "source_ids": ["s1"]}
    assert {x["materiality"] for x in shaped.values()} == {"material"}
    assert f.structure()["subject"] == {"value": "hello@stoko.com", "type": "email", "organisation": "Stoko", "organisation_claimed": False}


def test_stoko_acceptance_the_explanation_keeps_every_subject_and_the_unresolved_reason():
    plain, briefing = _case()
    assert plain.mode == "plain" and plain.fidelity.status == "PASS", plain.fidelity.failures
    shown = " ".join([plain.subject, plain.result, *(i.text for i in plain.established), *plain.uncertain])
    assert "hello@stoko.com" in shown and "stoko.com" in shown.replace("hello@stoko.com", "")
    assert 'No scam warning was found for "stoko.com".' in [i.text for i in plain.established]
    assert "hello@stoko.com is a published Stoko customer-service address." in [i.text for i in plain.established]
    assert plain.uncertain == ["Apollo can't confirm who actually sent this."]
    assert plain.subject == "What it is: the Stoko email address hello@stoko.com."
    # The briefing every surface shows.
    assert briefing.fidelity.status == "PASS", briefing.fidelity.failures
    assert briefing.headline == "Stoko email checked"
    assert briefing.summary == ('"hello@stoko.com" is a published Stoko contact. No scam warning was found for "stoko.com". '
                                "Still unresolved: Apollo can't confirm who actually sent this.")
    assert briefing.subject.value == "hello@stoko.com" and briefing.subject.organisation == "Stoko"
    assert briefing.supporting == ["f1", "f2"] and briefing.contrary == []
    assert briefing.unresolved == ["Apollo can't confirm who actually sent this."]
    # No decision the person owes: never "Needs you".
    assert briefing.user_action_required is False and briefing.action_reason is None
    assert briefing.status == "This is not a scam" and briefing.status_code == "no_scam_indicators"


def test_needs_you_only_with_a_concrete_reason():
    reason = "Anything typed into that link goes to whoever runs st0ko-login.co, not Stoko."
    concern = stoko(outcome="concerning", assessment="concern_found", attention="action_needed", attention_reason=reason,
                    findings=[Finding(id="f1", text="The material names Stoko, but st0ko-login.co is not Stoko's domain (stoko.com).",
                                      basis="observation", confidence="high", evidence_ids=["e1"])],
                    actions=[ActionProposal(id="a1", kind="instruction", label="Don't use the link", instruction="Do not open st0ko-login.co.")],
                    recommended_action_id="a1", overview="This uses Stoko's name, but its link goes to st0ko-login.co.")
    _, briefing = _case(concern)
    assert briefing.user_action_required and briefing.action_reason == reason
    # Stoko is only named: st0ko-login.co is never called Stoko's.
    assert briefing.headline == "Email using Stoko's name checked"
    assert explain.explain_case(concern, answered_by="magnum_di", routing={}, sources=SOURCES, gates=["link"])[1].headline == "Link using Stoko's name checked"
    assert briefing.subject.organisation == "Stoko" and briefing.subject.organisation_claimed is True
    assert _case(concern)[0].subject == "What it is: the website st0ko-login.co, which isn't Stoko's."
    assert briefing.recommended_action == {"label": "Don't use the link", "instruction": "Don't open st0ko-login.co."}
    assert briefing.status_reason == reason and briefing.supporting == ["f1"]
    # A review is a careful look, never a decision owed.
    _, review = _case(concern.model_copy(update={"attention": "review", "outcome": "unable_to_determine", "assessment": "uncertain"}))
    assert review.user_action_required is False
    # The question Magnum DI is waiting on is a decision owed, with its own reason.
    waiting = concern.model_copy(update={"attention": "review", "completion": "waiting_user", "question": Question(
        id="q1", text="Did you click the link?", reason_needed="Whether you opened it decides what to do next.")})
    assert _case(waiting)[1].action_reason == "Whether you opened it decides what to do next."


def test_the_fidelity_check_catches_a_lost_subject_a_changed_result_and_mixed_up_results():
    f = facts_mod.build(stoko(), answered_by="magnum_di", routing={}, sources=SOURCES, gates=["email"])
    draft = render.render(f)
    assert fidelity.check(f, draft).status == "PASS"

    def finding(i, text, **over):
        established = list(draft.established)
        established[i] = replace(established[i], text=text, **over)
        return replace(draft, established=established)

    codes = lambda d: {x.code for x in fidelity.check(f, d).failures}  # noqa: E731
    assert "SUBJECT_DROPPED" in codes(finding(1, "No scam warning was found for the website."))
    assert "SUBJECT_DROPPED" in codes(finding(1, "No scam warning was found."))
    assert "RESULT_CHANGED" in codes(finding(1, 'A scam warning names "stoko.com".'))
    assert "RESULT_KIND_CHANGED" in codes(finding(1, 'The scam warning check couldn\'t be checked for "stoko.com".'))
    assert "STANCE_CHANGED" in codes(finding(0, draft.established[0].text, stance="contrary"))
    assert "UNRESOLVED_DROPPED" in codes(replace(draft, uncertain=[]))
    assert "SUBJECT_DROPPED" in codes(replace(draft, subject=replace(draft.subject, text="What it is: an email.")))


def test_the_reason_for_the_status_and_a_cause_are_never_lost():
    reason = "Acting on it before checking is how people lose money, because the link isn't Stoko's."
    f = facts_mod.build(stoko(attention="review", attention_reason=reason), answered_by="magnum_di", routing={}, sources=SOURCES)
    draft = render.render(f)
    assert fidelity.check(f, draft).status == "PASS"
    assert "DECISION_REASON_DROPPED" in {x.code for x in fidelity.check(f, replace(draft, matters=[])).failures}
    no_cause = replace(draft, matters=[replace(draft.matters[0], text="Acting on it before checking is how people lose money, and the link isn't Stoko's.")])
    assert "CAUSAL_DROPPED" in {x.code for x in fidelity.check(f, no_cause).failures}


def test_unavailable_failed_no_match_and_not_applicable_stay_distinct():
    kinds = facts_mod.result_kinds
    assert kinds("Google Safe Browsing could not be checked for stoko.com.") == {"unavailable"}
    assert kinds("ABN 51 824 753 556 fails the check-digit test.") == {"failed"}
    assert kinds("No scam warning was found for stoko.com.") == {"no_match"}
    assert kinds("This check doesn't apply on a phone.") == {"not_applicable"}
    assert facts_mod.classify("Google Safe Browsing could not be checked for stoko.com.") == ("reputation", "UNAVAILABLE")
    assert facts_mod.classify("stoko.com is not listed by Google Safe Browsing or Apollo's blocklist.") == ("reputation", "NOT_LISTED")


def test_similar_sentences_about_different_subjects_are_never_merged():
    a = ModelFinding(text="No scam warning was found for stoko.com in any safety list Apollo checked.", basis="inference", confidence="medium")
    b = ModelFinding(text="No scam warning was found for st0ko.com in any safety list Apollo checked.", basis="inference", confidence="medium")
    assert len(deduplicate_findings([a, b])) == 2
    listed = ModelFinding(text="A scam warning was found for stoko.com in a safety list Apollo checked.", basis="inference", confidence="medium")
    assert len(deduplicate_findings([a, listed])) == 2, "the same subject with a different result is a different finding"
    again = ModelFinding(text="No scam warning was found for www.stoko.com in any safety list Apollo checked.", basis="observation",
                         confidence="high", evidence_ids=["e1"])
    assert [x.text for x in deduplicate_findings([a, again])] == [again.text], "the same identity, said twice, is one finding"


def test_the_renderer_never_merges_lookalike_sentences_with_different_identifiers():
    response = stoko(uncertainties=["No record was found for support@stoko.com in Apollo's knowledge base or a web search.",
                                    "No record was found for hello@stoko.com in Apollo's knowledge base or a web search."])
    plain, _ = _case(response)
    assert len(plain.uncertain) == 2 and plain.fidelity.status == "PASS"


@pytest.mark.parametrize("gates, headline", [(["email"], "Stoko email checked"), ([], "Stoko email checked"), (["link"], "Stoko link checked")])
def test_the_headline_names_the_organisation_and_what_was_checked(gates, headline):
    assert explain.explain_case(stoko(), answered_by="magnum_di", routing={}, sources=SOURCES, gates=gates)[1].headline == headline
