"""The Magnum DI request contains exactly three things: the person's question, the case evidence it needs
(the submitted material in full, plus TC FlyBy's brief, each labelled with id and kind), and the response
schema. No system prompt, no framework, no summarised or duplicated representation of the material.

Runs against the preview simulator: the request below is the real one; only the external call is
replaced. Run: cd /app/backend && python -m pytest tests/test_gemini_request_shape.py -q
"""
import uuid

import pytest

from core.db import db
from services.higgins import coordinator
from services.higgins import evidence as ev
from services.higgins import repository as repo
from services.higgins.preview.preview_simulator import simulated_text
from services.higgins.provider import AIResult, Purpose
from services.higgins.response_schema import RESPONSE_SCHEMA

pytestmark = pytest.mark.anyio


async def _progress(*_args):
    return None


async def test_request_is_question_plus_complete_evidence_plus_schema():
    owner = f"req-shape-{uuid.uuid4().hex[:8]}"
    case = await repo.create_case(owner, "text", None)
    long_text = "Invoice 4471 must be paid to account 063-000-1234 today. " * 200  # > the old 2000-char cut
    await ev.ingest_text(owner, case, "item-1", long_text, kind="text", origin="user_submission", label="the message")
    # Apollo's pre-gathered specialist intelligence, stored exactly as triage produced it.
    await db.investigation_cases.update_one(
        {"owner_id": owner, "case_id": case["case_id"]},
        {"$set": {"triage_provider_evidence": {"safe_browsing": {"verdict": "malicious", "threat": "SOCIAL_ENGINEERING"}}}})

    job = await repo.create_job(owner, await repo.get_case(owner, case["case_id"]), str(uuid.uuid4()),
                                repo.digest("ledger"), repo.digest("payload"), "turn", {"message": "Is this invoice a scam?"})

    # The bounded suite forbids provider calls, so the gateway is replaced with the SAME fixed
    # response the preview simulator returns — the request built above is the real one.
    captured: dict = {}
    original = coordinator.provider.generate

    async def capture(system, contents, **kwargs):
        captured["system"], captured["contents"], captured["kwargs"] = system, contents, kwargs
        text = simulated_text(Purpose.INVESTIGATION, True)
        return AIResult(text=text, finish_reason="STOP", usage={"prompt_token_count": 1, "candidates_token_count": 1,
                                                          "total_token_count": 2}, grounding=None,
                            model=kwargs.get("model") or "gemini-3.8-flash")

    coordinator.provider.generate = capture
    try:
        outcome = await coordinator.run_turn(owner, await repo.get_case(owner, case["case_id"]),
                                             await repo.get_job(owner, case["case_id"], job["job_id"]), _progress)
    finally:
        coordinator.provider.generate = original

    # 1. No system prompt, and the response shape comes from the schema alone — limited to the ids
    #    registered for this case (none yet, so every sourceIds list must stay empty) and to the
    #    evidence actually supplied (Gemini otherwise puts search citations like "1.1.4" in evidenceIds).
    assert captured["system"] == ""
    sent_schema = captured["kwargs"]["response_schema"]
    assert set(sent_schema["properties"]) == set(RESPONSE_SCHEMA["properties"])
    assert sent_schema["properties"]["sourceIds"]["maxItems"] == 0
    finding = sent_schema["properties"]["findings"]["items"]["properties"]
    assert finding["sourceIds"]["maxItems"] == 0
    # Magnum DI may cite only what it was sent: the material and TC FlyBy's brief. The raw lookups TC FlyBy
    # already read, and TC FlyBy's full check record, stay registered for the case but are not resent.
    supplied = {row["evidence_id"] for row in await repo.list_evidence(owner, case["case_id"])
                if row["client_item_id"] not in ("apollo-triage-intelligence", "tc-flyby-di-checks")}
    allowed = finding["evidenceIds"]["items"].get("enum") or []
    assert allowed and set(allowed) == supplied
    assert sent_schema["properties"]["remainingEvidenceIds"]["items"]["enum"] == allowed
    assert captured["kwargs"]["json_output"] is True
    # Nothing in this case needs an external fact TC FlyBy couldn't establish, so Google Search is off.
    assert captured["kwargs"].get("web_search", False) is False

    parts = captured["contents"][0].parts
    texts = [p.text for p in parts if getattr(p, "text", None)]

    # 2. The question is sent once, first.
    assert parts[0].text == "Is this invoice a scam?"
    assert sum(1 for t in texts if t == "Is this invoice a scam?") == 1

    # 3. Evidence follows, each item labelled with its id and kind, and nothing else.
    evidence_texts = texts[1:]
    assert evidence_texts, "the evidence was not sent"
    assert all(t.startswith("[evidence ") for t in evidence_texts)
    assert not any("INVESTIGATION BRIEF" in t or "evidenceInventory" in t for t in texts)
    assert not any("previousTurns" in t or "deviceProfile" in t for t in texts)

    # 4. Evidence is complete — the full text, not a 2000-character slice or a summary.
    message_part = next(t for t in evidence_texts if "Invoice 4471" in t)
    assert long_text in message_part
    assert "only the first 2000" not in message_part

    # 5. Pre-gathered results TC FlyBy has no reader for are passed on verbatim inside its brief, never
    #    summarised away; the raw item itself is not sent a second time.
    assert any("safe_browsing" in t and "SOCIAL_ENGINEERING" in t for t in evidence_texts)
    assert not any("Higgins triage specialist intelligence" in t for t in evidence_texts)

    # 6. The schema-shaped response passes the real validator and is staged as a turn.
    #    (This job was never claimed by the worker, so the final case CAS reports "superseded";
    #     what matters here is that validation produced no errors and nothing was reshaped.)
    assert outcome.kind != "invalid", outcome.errors
    assert outcome.errors == []


async def test_evidence_appears_once_per_item():
    owner = f"req-once-{uuid.uuid4().hex[:8]}"
    case = await repo.create_case(owner, "text", None)
    await ev.ingest_text(owner, case, "item-1", "https://commbank-cancel.co/stop", kind="url", label="the link")
    rows = await repo.list_evidence(owner, case["case_id"])
    parts, _marks, _words = await ev.model_parts(owner, await repo.get_case(owner, case["case_id"]), rows)
    ids = [row["evidence_id"] for row in rows]
    for evidence_id in ids:
        mentions = sum(1 for p in parts if getattr(p, "text", None) and evidence_id in p.text)
        assert mentions == 1, f"evidence {evidence_id} was sent {mentions} times"


async def test_evidence_over_the_word_limit_is_not_sent():
    """Over 10,000 words of written evidence: Apollo sends nothing, shortens nothing, and Higgins
    explains the limit and points to the person's own AI assistant."""
    from services.higgins.evidence import EVIDENCE_WORD_LIMIT
    from services.higgins.jobs import evidence_too_large_message

    owner = f"req-big-{uuid.uuid4().hex[:8]}"
    case = await repo.create_case(owner, "text", None)
    # Two documents that are each within the limit but together exceed it.
    await ev.ingest_text(owner, case, "doc-1", "word " * 6000, kind="text", origin="user_submission", label="contract part 1")
    await ev.ingest_text(owner, case, "doc-2", "word " * 5000, kind="text", origin="user_submission", label="contract part 2")
    job = await repo.create_job(owner, await repo.get_case(owner, case["case_id"]), str(uuid.uuid4()),
                                repo.digest("ledger"), repo.digest("payload"), "turn", {"message": "Is this contract genuine?"})

    called = False

    async def must_not_be_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("Gemini must not be called when the evidence exceeds the word limit")

    original = coordinator.provider.generate
    coordinator.provider.generate = must_not_be_called
    try:
        outcome = await coordinator.run_turn(owner, await repo.get_case(owner, case["case_id"]),
                                             await repo.get_job(owner, case["case_id"], job["job_id"]), _progress)
    finally:
        coordinator.provider.generate = original

    assert called is False
    assert outcome.kind == "evidence_too_large"
    assert outcome.evidence_words == 11000
    assert outcome.evidence_words > EVIDENCE_WORD_LIMIT

    # Nothing was marked as examined — the evidence was not read, shortened or sampled.
    for row in await repo.list_evidence(owner, case["case_id"]):
        assert row["coverage"].get("status") in (None, "not_started"), row["coverage"]

    message = evidence_too_large_message(outcome.evidence_words)
    assert "11,000 words" in message and "10,000 words" in message
    assert "haven't sent any of it" in message
    assert "AI assistant on your own device" in message
    for brand in ("Gemini", "Google", "Claude", "Copilot"):
        assert brand not in message


async def test_evidence_within_the_limit_still_runs():
    owner = f"req-ok-{uuid.uuid4().hex[:8]}"
    case = await repo.create_case(owner, "text", None)
    await ev.ingest_text(owner, case, "doc-1", "word " * 9999, kind="text", origin="user_submission", label="long letter")
    rows = await repo.list_evidence(owner, case["case_id"])
    parts, _marks, words = await ev.model_parts(owner, await repo.get_case(owner, case["case_id"]), rows)
    assert words == 9999
    assert parts and "word" in parts[0].text


SMS = ("From +61 448 221 905:\n"
       "CommBank: A payment of $920.00 to CRYPTO EXCHANGE LTD is pending. If this wasn't you, cancel it "
       "now at http://commbank-cancel.co/stop and confirm your NetBank password.")


async def test_derived_clues_workflow_metadata_and_empty_triage_are_not_sent():
    """The SMS is the evidence. The phone and link clues extracted from it are the same information
    again, so they stay in Apollo but are not retransmitted. Workflow metadata and an empty triage
    envelope are not evidence at all."""
    owner = f"req-dupe-{uuid.uuid4().hex[:8]}"
    case = await repo.create_case(owner, "text", None)
    await ev.ingest_text(owner, case, "sms-1", SMS, kind="text", origin="user_submission", label="messages calls")
    await ev.ingest_text(owner, case, "apollo-finding-0", "User-initiated check via Ask Higgins: messages calls",
                         origin="apollo_inference", label="Apollo initial finding")
    await ev.ingest_text(owner, case, "intel-0", '{"_summary": {"providers_consulted": [], "total_lookups": 0}}',
                         origin="apollo_inference", label="Pre-gathered specialist intelligence")

    rows = await repo.list_evidence(owner, case["case_id"])
    # Apollo still holds the clue records for specialist lookups and evidence relationships.
    assert any(row["label"] == "phone clue" for row in rows)
    assert any(str(row["label"]).startswith("link clue") for row in rows)

    parts, _marks, words = await ev.model_parts(owner, await repo.get_case(owner, case["case_id"]), rows)
    texts = [p.text for p in parts if getattr(p, "text", None)]

    assert len(texts) == 1, texts                      # the SMS, and nothing else
    assert "messages calls" in texts[0] and "CommBank" in texts[0]
    assert "User-initiated check" not in texts[0]
    assert "providers_consulted" not in " ".join(texts)
    assert words == len(SMS.split())


async def test_a_clue_with_its_own_lookup_result_is_still_sent():
    """Withholding applies only to verbatim duplicates. A child item carrying new information — a page
    snapshot taken from the link — is evidence in its own right and is sent."""
    owner = f"req-child-{uuid.uuid4().hex[:8]}"
    case = await repo.create_case(owner, "text", None)
    parent = await ev.ingest_text(owner, case, "sms-1", SMS, kind="text", origin="user_submission", label="messages calls")
    await ev.ingest_text(owner, case, "sms-1.source", "Page title: Verify your NetBank details. Form fields: password.",
                         kind="source_snapshot", origin="external_source", parent_id=parent.id, label="page snapshot")

    rows = await repo.list_evidence(owner, case["case_id"])
    parts, _marks, _words = await ev.model_parts(owner, await repo.get_case(owner, case["case_id"]), rows)
    texts = [p.text for p in parts if getattr(p, "text", None)]
    assert any("Page title" in t for t in texts), texts


async def test_empty_triage_envelope_is_never_registered_as_evidence():
    owner = f"req-empty-{uuid.uuid4().hex[:8]}"
    case = await repo.create_case(owner, "text", None)
    await db.investigation_cases.update_one(
        {"owner_id": owner, "case_id": case["case_id"]},
        {"$set": {"triage_provider_evidence": {"_summary": {"providers_consulted": [], "total_lookups": 0}}}})
    await coordinator._register_triage_evidence(owner, await repo.get_case(owner, case["case_id"]))
    rows = await repo.list_evidence(owner, case["case_id"])
    assert not any(row.get("client_item_id") == coordinator.TRIAGE_EVIDENCE_ITEM_ID for row in rows)
