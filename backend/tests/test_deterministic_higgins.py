"""Higgins presents what Apollo already knows — zero Gemini calls.

Owner directive "Remove Unnecessary Gemini Calls": scam alerts / official advisories, finished Magnum DI
results and their follow-ups (even when the follow-up brings a new link, email or number), Patrol finding
explanations, the current device / Apollo state, the Higgins health check and plain-English formatting are
all answered from established records. The only Gemini call Higgins keeps is the one for a general
scam-safety question nothing in Apollo answers.
"""
import ast
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from core.db import now_utc
from routers import investigations
from services import system_health_jobs
from services.higgins import chat, health_check, presenter, provider
from services.higgins import repository as repo

BACKEND = Path(__file__).resolve().parents[1]

RESPONSE = {
    "revision": 1, "overview": "The text claiming to be from Australia Post is a delivery scam.",
    "explanationMarkdown": "", "assessment": "concern_found", "attention": "action_needed",
    "attentionReason": "The link leads to a look-alike site.",
    "findings": [{"id": "f1", "text": "The link domain is not auspost.com.au.", "basis": "observation", "confidence": "high",
                  "evidenceIds": ["e1"], "sourceIds": []}],
    "uncertainties": ["Who sent it could not be traced."], "scope": "The message text and its link.",
    "sourceIds": [], "remainingEvidenceIds": [],
    "actions": [{"id": "a1", "kind": "instruction", "label": "Delete the message", "instruction": "Delete it and don't tap the link.",
                 "capabilityId": None, "executionDescriptorId": None, "requiresUserGesture": False, "sourceIds": [],
                 "desiredField": None, "desiredValue": None}],
    "recommendedActionId": "a1", "question": None, "completion": "complete",
}


@pytest.fixture
def no_gemini(monkeypatch):
    """Any Gemini call — chat's fallback, an investigation or a pipeline submission — fails the test."""
    gemini = AsyncMock(side_effect=AssertionError("Gemini must not be called"))
    monkeypatch.setattr(provider, "generate", gemini)
    monkeypatch.setattr(chat.pipeline_submit, "submit_to_investigation_pipeline", AsyncMock(side_effect=AssertionError("no new investigation")))
    monkeypatch.setattr(chat.memory, "add_chat_exchange", AsyncMock(return_value=now_utc() + timedelta(minutes=5)))
    monkeypatch.setattr(chat.knowledge, "search", AsyncMock(return_value=[]))
    return gemini


async def ask(message: str, **kwargs):
    return await chat.reply("owner-deterministic", "conversation-1", "turn-00000001", message, [], **kwargs)


# ── Finished Magnum DI results and their follow-ups ─────────────────────────────────────────────

@pytest.mark.parametrize("question, label", [
    ("Is this link safe too? https://auspost-redelivery.top/track", "a link"),
    ("They also emailed me from support@auspost-help.com — is that them?", "an email address"),
    ("A number called me after, 0412 345 678, is that the same scam?", "a phone number"),
])
def test_follow_up_with_something_new_is_answered_from_the_record(question, label):
    result = presenter.investigation_follow_up(RESPONSE, [], question)
    assert result["answer"].startswith(f"You've mentioned something new ({label}) that wasn't part of this investigation.")
    assert "nothing new has been checked" in result["answer"] and "start a new check" in result["answer"]
    assert label in result["newItems"]


def test_follow_up_without_new_items_does_not_mention_them():
    result = presenter.investigation_follow_up(RESPONSE, [], "What should I do?")
    assert result["newItems"] == [] and "You've mentioned" not in result["answer"]
    assert "Delete the message: Delete it and don't tap the link." in result["answer"]


def test_recheck_after_an_action_never_reassesses():
    result = presenter.investigation_follow_up(RESPONSE, [], 'I did "Delete the message". Please re-check using the fresh observation Apollo just recorded.')
    assert result["intent"] == "recheck" and "isn't re-assessed" in result["answer"]
    assert RESPONSE["overview"] in result["answer"]


def test_unanswered_follow_up_no_longer_promises_magnum_di_will_investigate():
    result = presenter.investigation_follow_up(RESPONSE, [], "Tell the bank for me")
    assert result["intent"] == "unanswered" and "Magnum DI will investigate" not in result["answer"]


def test_only_finished_results_are_answered_deterministically():
    assert presenter.is_finished(RESPONSE)
    assert presenter.is_finished({**RESPONSE, "completion": "partial"})
    assert not presenter.is_finished({**RESPONSE, "completion": "waiting_user", "question": {"id": "q1"}})
    assert not presenter.is_finished(None)


def _request(owner: str = "owner-turns") -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/api/investigations/case-1/turns", "headers": []})
    request.state.device = {"device_id": owner}
    return request


def _case(response: dict) -> dict:
    return {"case_id": "case-finished-1", "owner_id": "owner-turns", "revision": 7, "active_job_id": None, "status": "complete",
            "response_ciphertext": repo.enc_json(response)}


@pytest.mark.asyncio
async def test_turn_on_a_finished_case_returns_a_follow_up_and_starts_no_job(monkeypatch):
    monkeypatch.setattr(investigations.repo, "get_case", AsyncMock(return_value=_case(RESPONSE)))
    monkeypatch.setattr(investigations.repo, "sources", AsyncMock(return_value=[]))
    monkeypatch.setattr(investigations, "_submit_turn", AsyncMock(side_effect=AssertionError("no Magnum DI job")))
    monkeypatch.setattr(investigations.jobs, "launch", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no launch")))
    body = investigations.SubmitTurn(expected_revision=7, turn_id="00000000-0000-4000-8000-0000000000a1",
                                     message="What about www.auspost-help.net?", answer_to_question_id=None, evidence_ids=[])
    response = await investigations.submit_turn("case-finished-1", body, _request(), idempotency_key="follow-up-key-0001")
    data = json.loads(response.body)
    assert response.status_code == 200 and data["job"] is None and data["caseRevision"] == 7
    assert data["followUp"]["answer"].startswith("You've mentioned something new (a link)") and data["followUp"]["answeredBy"] == "apollo"


@pytest.mark.asyncio
async def test_an_answer_to_magnum_dis_own_question_is_answered_from_the_record_too(monkeypatch):
    """One Magnum DI call per correlated case: even an answer to its own question doesn't reopen the investigation."""
    monkeypatch.setattr(investigations.repo, "sources", AsyncMock(return_value=[]))
    waiting = {**RESPONSE, "completion": "waiting_user", "question": {"id": "q1", "text": "Did you tap it?", "reasonNeeded": "",
                                                                       "answerType": "yes_no", "choices": []}}
    case = _case(waiting)
    body = investigations.SubmitTurn(expected_revision=7, turn_id="00000000-0000-4000-8000-0000000000a2",
                                     message="No", answer_to_question_id="q1", evidence_ids=[])
    answer = await investigations._follow_up("owner-turns", case, body)
    assert answer and answer["answeredBy"] == "apollo" and answer["answer"]


# ── Scam alerts, advisories and Learn articles ──────────────────────────────────────────────────

CARD = ("I just read this scam alert and I want to understand it:\n• Title: Fake toll notices\n• Source: Scamwatch\n"
        "• What the source says: Texts claim you owe an unpaid toll.\n• Official source: https://www.scamwatch.gov.au/fake-toll\n\n"
        "Can you explain what this scam is, how it works, and how I stay safe from it?")


@pytest.mark.asyncio
async def test_scam_alert_not_in_the_cache_is_presented_from_its_card(monkeypatch, no_gemini):
    monkeypatch.setattr(chat.government_alerts, "alert_by_url", AsyncMock(return_value=None))
    reply = await ask(CARD)
    assert "“Fake toll notices” — Scamwatch." in reply.answer and "Texts claim you owe an unpaid toll." in reply.answer
    assert reply.sources[0].url == "https://www.scamwatch.gov.au/fake-toll"
    no_gemini.assert_not_awaited()


@pytest.mark.asyncio
async def test_learn_article_explanation_uses_the_articles_own_words(monkeypatch, no_gemini):
    article = {"slug": "toll-scams", "title": "Toll scams", "summary": "How fake toll texts work.",
               "sections": [{"heading": "Spot it", "paragraphs": ["Real toll operators don't text links."], "bullets": ["Check the app"]}],
               "citations": [{"label": "Scamwatch", "url": "https://www.scamwatch.gov.au"}]}
    monkeypatch.setattr(chat.learning, "article_by_title", AsyncMock(return_value=article))
    reply = await ask("Please explain the learning article: Toll scams")
    # No metadata preamble — just the article content
    assert "How fake toll texts work." in reply.answer
    assert "Real toll operators don't text links." in reply.answer and "• Check the app" in reply.answer
    assert "From the Learn with Higgins article" not in reply.answer
    monkeypatch.setattr(chat.learning, "article_by_title", AsyncMock(return_value=None))
    missing = await ask("Please explain the learning article: Not a real article")
    assert "couldn't find" in missing.answer
    no_gemini.assert_not_awaited()


# ── Patrol findings ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_selected_patrol_finding_is_explained_from_its_own_record(monkeypatch, no_gemini):
    items = [{"recordId": "r-other", "headline": "Other", "effectiveState": "resting"},
             {"recordId": "r-1", "headline": "Look-alike bank site", "effectiveState": "barking", "summary": "The page copied CommBank's login.",
              "evidence_availability": "full", "structuredFacts": {"indicatorHost": "commbank-login.top"}, "observedBlockReference": {"id": "b1"}}]
    monkeypatch.setattr(chat.context_tools, "execute", AsyncMock(return_value={"items": items}))
    reply = await ask("Why did Apollo flag this?", selected_patrol_record_id="r-1")
    assert "Look-alike bank site — significant concern." in reply.answer and "commbank-login.top" in reply.answer
    assert "Apollo confirmed it blocked this." in reply.answer and "Other" not in reply.answer
    no_gemini.assert_not_awaited()


# ── Current device / Apollo state ───────────────────────────────────────────────────────────────

SNAPSHOT = chat.DeviceSnapshot.model_validate({
    "platform": "android", "checkedAt": "2026-06-02T09:00:00.000Z", "protectionOn": True,
    "gates": [{"id": "site", "title": "Site protection", "status": "Needs attention", "tone": "growling", "automatic": True, "coverage": "full"}],
    "permissions": [], "threatCounts": [], "openThreats": [], "deviceProtections": [], "notes": [],
    "capabilities": ["Screen lock: Managed by your device (per Android)"], "recommendedSettings": [],
})


@pytest.mark.parametrize("prompt, expected", [
    ("Help me fix my Site protection protection. Status: Needs attention. Apollo can't confirm it.", "Site protection: Needs attention"),
    ("Can you explain “Screen lock” on my phone? Apollo says its status is “Managed by your device”. What does that mean for me?",
     "Screen lock: Managed by your device (per Android)"),
    ("My device security review says: 2 checks need attention. What should I do first?", "Apollo protection is switched on."),
])
@pytest.mark.asyncio
async def test_device_state_prompts_from_apollo_screens_make_no_call(prompt, expected, no_gemini):
    reply = await ask(prompt, device_snapshot=SNAPSHOT)
    assert reply.answer.startswith("Here's what Apollo reads on this phone right now") and expected in reply.answer
    no_gemini.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_general_question_nothing_trusted_answers_makes_no_ai_call(monkeypatch, no_gemini):
    """Ask Higgins has no general AI fallback: when nothing trusted answers, Higgins says so."""
    monkeypatch.setattr(chat.knowledge, "search", AsyncMock(return_value=[]))
    reply = await ask("Why do scammers ask for gift cards?")
    assert reply.answered_by == "apollo" and reply.answer == presenter.NOT_IN_TRUSTED_KNOWLEDGE
    assert [n.route for n in reply.navigation] == ["/higgins/learning"]
    no_gemini.assert_not_awaited()


def test_chat_makes_no_ai_call():
    source = (BACKEND / "services/higgins/chat.py").read_text()
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr in ("generate", "generate_json", "generate_text")]
    assert calls == [] and "provider" not in {getattr(n, "id", "") for n in ast.walk(tree) if isinstance(n, ast.Name)}


# ── Higgins health check ────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_status_comes_from_saved_records_only(monkeypatch):
    monkeypatch.setattr(provider, "generate", AsyncMock(side_effect=AssertionError("no test call")))
    last = {"timestamp": now_utc(), "success": False, "failure_code": "provider_configuration", "purpose": "investigation"}
    monkeypatch.setattr(health_check, "db", SimpleNamespace(gemini_usage=SimpleNamespace(find_one=AsyncMock(return_value=last))))
    async def _selected():
        return {"provider": "gemini", "model": "gemini-3.1-flash-lite"}
    monkeypatch.setattr(health_check.ai_settings, "selection", _selected)
    monkeypatch.setattr(health_check.ai_settings, "key_configured", lambda provider: True)
    status = await health_check.provider_status()
    assert status["keyConfigured"] is True and status["provider"] == "gemini" and status["model"] == "gemini-3.1-flash-lite"
    assert status["lastCall"]["worked"] is False and status["lastCall"]["failureCode"] == "provider_configuration"
    monkeypatch.setattr(health_check, "db", SimpleNamespace(gemini_usage=SimpleNamespace(find_one=AsyncMock(return_value=None))))
    monkeypatch.setattr(health_check.ai_settings, "key_configured", lambda provider: False)
    assert await health_check.provider_status() == {"keyConfigured": False, "provider": "gemini", "model": "gemini-3.1-flash-lite", "lastCall": None}


def test_public_health_result_carries_the_provider_status():
    doc = {"check_id": "00000000-0000-4000-8000-000000000009", "state": "failed", "started_at": now_utc(), "expires_at": now_utc(),
           "provider_status": {"keyConfigured": True, "lastCall": None}}
    assert system_health_jobs.public(doc)["investigation"]["provider"] == {"keyConfigured": True, "lastCall": None}


def test_a_follow_up_credits_whichever_investigator_settled_the_result():
    assert presenter.investigation_follow_up(RESPONSE, [], "What should I do?", "tc_flyby_kb")["answer"].startswith("What TC Hawkeye recommends")
    assert presenter.investigation_follow_up(RESPONSE, [], "What should I do?", "magnum_di")["answer"].startswith("What Magnum DI recommends")
    assert presenter.investigation_follow_up(RESPONSE, [], "What should I do?")["answer"].startswith("What Magnum DI recommends"), "older results were Magnum DI's"
