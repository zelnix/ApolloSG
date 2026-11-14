from types import SimpleNamespace
import pytest
from services.higgins import chat_context

@pytest.mark.anyio
async def test_retrieval_is_bounded_and_preserves_provenance(monkeypatch):
    async def search(question, limit):
        assert limit <= 6
        return [{"title": "Scam guidance", "body": "Never share a security code.", "url": "https://example.gov.au/guide", "kind": "official", "provenance": {"published_at": "2026-01-01"}, "status": "historical"}]
    monkeypatch.setattr(chat_context.knowledge, "search", search)
    body = SimpleNamespace(message="How do scam security codes work?", selected_patrol_record_id=None, device_snapshot=None, conversation_id="conversation-A", turn_id="turn-A")
    packet = await chat_context.retrieve("device-A", body)
    assert packet["kind"] == "grounded_chat"
    assert len(packet["passages"]) <= 6
    assert packet["passages"][-1]["publishedAt"] == "2026-01-01"
    assert packet["passages"][-1]["freshness"] == "historical"
    assert "answer" not in packet and packet["caseFindings"] == []

@pytest.mark.anyio
async def test_only_selected_owner_record_is_supplied(monkeypatch):
    async def search(*args, **kwargs): return []
    async def execute(owner, tool):
        assert owner == "device-A"
        return {"items": [{"recordId": "selected"}, {"recordId": "another"}]}
    monkeypatch.setattr(chat_context.knowledge, "search", search)
    monkeypatch.setattr(chat_context.context_tools, "execute", execute)
    body = SimpleNamespace(message="Explain my recorded finding", selected_patrol_record_id="selected", device_snapshot=None, conversation_id="conversation-A", turn_id="turn-A")
    packet = await chat_context.retrieve("device-A", body)
    assert packet["caseFindings"] == [{"recordId": "selected"}]
