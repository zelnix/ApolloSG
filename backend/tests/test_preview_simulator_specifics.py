"""The preview simulator must say something specific about the evidence it was given."""
import json

from services.higgins.ai_request import Message, Part

from services.higgins.llm_boundary import Purpose
from services.higgins.preview.preview_simulator import evidence_blocks, simulated_text

BANK_TEXT = ("CommBank: A payment of $920.00 to CRYPTO EXCHANGE LTD is pending. If this wasn't you, cancel it now "
             "at http://commbank-cancel.co/stop and confirm your NetBank password.")


def _contents(*texts: str) -> list[Message]:
    parts = [Part(text="Is this a scam?")]
    for i, text in enumerate(texts, start=1):
        parts.append(Part(text=f"[evidence EV-{i} · kind=text · message]\n{text}"))
    return [Message("user", parts)]


def _result(*texts: str) -> dict:
    return json.loads(simulated_text(Purpose.INVESTIGATION, True, evidence_blocks(_contents(*texts))))


def test_evidence_is_read_back_with_its_registered_ids():
    blocks = evidence_blocks(_contents(BANK_TEXT))
    assert [b.evidence_id for b in blocks] == [None, "EV-1"]
    assert blocks[1].text.startswith("CommBank:")
    assert blocks[1].kind == "text"


def test_bank_impersonation_names_the_brand_link_amount_and_request():
    out = _result(BANK_TEXT)
    text = json.dumps(out)
    assert "commbank-cancel.co" in text
    assert "commbank.com.au" in text
    assert "$920.00" in text
    assert "NetBank password" in text
    assert out["assessment"] == "concern_found"
    assert out["attention"] == "action_needed"
    assert out["attentionReason"]
    assert out["actions"] and out["recommendedActionIndex"] == 0
    # Observation findings must cite the evidence they rest on.
    for finding in out["findings"]:
        if finding["basis"] == "observation":
            assert finding["evidenceIds"] == ["EV-1"]


def test_a_plain_notice_is_not_dressed_up_as_a_threat():
    out = _result("Your parcel AP88213 was delivered to your front door at 2:14pm.")
    assert out["assessment"] == "no_concern_found_within_scope"
    assert out["attention"] == "none"
    assert out["attentionReason"] is None
    assert out["actions"] == []
    assert "AP88213" not in out["overview"]  # nothing invented about it either
    assert "needs action" not in out["overview"], "the same wording rules as production: no all-clear beyond what was checked"


def test_impersonation_says_what_was_established_about_the_link():
    text = json.dumps(_result(BANK_TEXT))
    assert "no reason to send you" not in text
    assert "the link isn't commbank.com.au, CommBank's published domain" in text


def test_an_unattributed_link_is_reported_as_unverified_not_as_a_scam():
    out = _result("Have a look at this when you get a chance: https://some-shop-7712.xyz/offer")
    assert out["assessment"] == "uncertain"
    assert out["attention"] == "review"
    assert "some-shop-7712.xyz" in json.dumps(out)


def test_gift_card_demand_is_treated_as_a_concern():
    out = _result("Final notice: pay your $65 fine today with an iTunes gift card or legal action will follow.")
    assert out["assessment"] == "concern_found"
    assert "gift card" in json.dumps(out).lower()
    assert "$65" in json.dumps(out)


def test_scope_states_what_was_and_was_not_done():
    out = _result(BANK_TEXT)
    assert "EV-1" in out["scope"]
    assert "No website was opened" in out["scope"]
    assert out["uncertainties"]


def test_no_section_is_a_copy_of_another():
    """Each section says something different: conclusion, consequence, evidence, reasoning."""
    out = _result(BANK_TEXT)
    finding_texts = [f["text"] for f in out["findings"]]
    assert out["overview"] not in finding_texts
    assert out["attentionReason"] not in finding_texts
    assert out["attentionReason"] not in out["overview"]
    for text in finding_texts:
        assert text not in out["overview"]
        assert text not in out["explanationMarkdown"]
    # The briefing is reasoning, not a reprint of the uncertainties, scope or actions.
    for line in out["uncertainties"] + [a["instruction"] for a in out["actions"]] + [out["scope"]]:
        assert line not in out["explanationMarkdown"]


def test_the_brand_article_agrees_with_the_name():
    out = _result("ING: confirm your account at https://abc.net.au/ing")
    assert "an ING" in out["overview"]
    assert " a ING" not in out["overview"]


# ── Apollo's knowledge base as the simulator's information base ─────────────

from services.higgins.knowledge import related_share, terms  # noqa: E402
from services.higgins.preview.preview_simulator import query_text  # noqa: E402

KB_ENTRY = {"kb_id": "kb-1", "kind": "researched", "title": "Romance scams", "publisher": "Scamwatch",
            "url": "https://www.scamwatch.gov.au/types-of-scams/romance-scams", "authority_tier": "tier_1_authoritative",
            "jurisdiction": "AU", "provenance": {},
            "body": "Romance scammers create fake profiles on dating sites and social media.\n\n"
                    "They build trust quickly, then ask for money for an emergency or travel.\n\nNever send money to someone you haven't met."}


async def test_tc_flybys_simulated_search_lines_carry_no_preview_wording(monkeypatch):
    """The search stand-in answers in Google Search grounding's own line format; the case is tagged instead."""
    from services.higgins import knowledge
    from services.higgins.preview import preview_simulator as sim

    async def none(*_a, **_k):
        return []
    monkeypatch.setattr(knowledge, "search", none)
    monkeypatch.setattr(knowledge, "related", none)
    prompt = "Q1 [statuses: ANSWER, NOT_FOUND] [subject: 0412 345 678] Who uses 0412 345 678?"
    text, grounding = await sim.flyby_lookup([sim.EvidenceBlock(None, "question", "q", prompt)])
    assert text == "Q1 | NOT_FOUND | ApolloSG's knowledge base has nothing on 0412 345 678."
    assert "Simulated" not in text and "preview" not in text.lower() and grounding["grounding_chunks"] == []


def test_an_investigation_adds_knowledge_as_general_knowledge_never_as_a_finding():
    result = json.loads(simulated_text(Purpose.INVESTIGATION, True, evidence_blocks(_contents(BANK_TEXT)), kb=[KB_ENTRY]))
    assert "**From ApolloSG's knowledge base** (general knowledge, not a finding about what you sent)" in result["explanationMarkdown"]
    assert "Scamwatch: “Romance scams”" in result["explanationMarkdown"]
    assert all("Romance" not in f["text"] for f in result["findings"])
    assert result["sourceIds"] == []


def test_the_lookup_uses_the_evidence_for_an_investigation_and_the_question_otherwise():
    assert query_text("investigation", evidence_blocks(_contents(BANK_TEXT))).startswith("CommBank:")
    assert query_text("ordinary_chat", evidence_blocks([Message("user", [
        Part(text=json.dumps({"message": "is this a romance scam\n\nApollo context: ..."}))])])) == "is this a romance scam"


def test_only_sourced_entries_on_the_same_subject_count():
    question = terms("how do romance scams work")
    assert related_share(KB_ENTRY, question) == 1.0
    assert related_share(KB_ENTRY, terms("how do investment scams work")) == 0.0
    assert related_share({**KB_ENTRY, "kind": "gemini_answer"}, question) == 0.0, "saved AI answers are not sourced knowledge"
    evidence = terms(BANK_TEXT)
    assert related_share({**KB_ENTRY, "title": "CommBank NetBank password scam"}, evidence) > 0
    assert related_share({**KB_ENTRY, "title": "Toll road text message scam"}, evidence) == 0.0
