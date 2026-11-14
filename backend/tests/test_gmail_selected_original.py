"""Selected Gmail originals are transient, device-scoped transport, not reconstructed evidence."""
import base64
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import Response

from routers import gmail as routes
from services import gmail

RAW = b"From: Google <no-reply@accounts.google.com>\r\nSubject: Example\r\n\r\nExact original\x80\xff\r\n"
ENCODED = base64.urlsafe_b64encode(RAW).decode().rstrip("=")


def result(data, status=200):
    return httpx.Response(status, json=data, request=httpx.Request("GET", gmail.GMAIL_API + "/messages/message-a"))


@pytest.mark.asyncio
async def test_exact_provider_bytes_are_returned_without_reconstruction():
    client = SimpleNamespace(get=AsyncMock(return_value=result({"id": "message-a", "raw": ENCODED})))
    encoded, reason = await gmail.selected_message_original(client, {"Authorization": "Bearer test-only"}, "message-a")
    assert reason is None
    assert base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)) == RAW
    client.get.assert_awaited_once_with(f"{gmail.GMAIL_API}/messages/message-a", params={"format": "raw"}, headers={"Authorization": "Bearer test-only"})


@pytest.mark.parametrize("data,reason", [
    ({"id": "other-message", "raw": ENCODED}, "original_message_mismatch"),
    ({"id": "message-a"}, "original_unreadable"),
    ({"id": "message-a", "raw": "a"}, "original_unreadable"),
    ({"id": "message-a", "raw": "not base64!"}, "original_unreadable"),
])
@pytest.mark.asyncio
async def test_unavailable_or_mismatched_original_is_never_synthesized(data, reason):
    encoded, failure = await gmail.selected_message_original(SimpleNamespace(get=AsyncMock(return_value=result(data))), {}, "message-a")
    assert encoded is None and failure == reason


@pytest.mark.asyncio
async def test_large_original_is_not_downloaded_and_provider_errors_remain_explicit():
    client = SimpleNamespace(get=AsyncMock())
    assert await gmail.selected_message_original(client, {}, "message-a", gmail.MAX_ORIGINAL_BYTES + 1) == (None, "original_too_large")
    client.get.assert_not_awaited()
    client.get.return_value = result({}, 403)
    assert await gmail.selected_message_original(client, {}, "message-a") == (None, "original_unavailable")
    client.get.side_effect = httpx.ReadTimeout("synthetic timeout")
    assert await gmail.selected_message_original(client, {}, "message-a") == (None, "original_unavailable")


@pytest.mark.parametrize("include_original", [True, False])
@pytest.mark.asyncio
async def test_selected_detail_opt_in_account_binding_and_no_store(monkeypatch, include_original):
    full = {"id": "message-a", "sizeEstimate": len(RAW), "payload": {"mimeType": "text/plain", "headers": [
        {"name": "From", "value": "Google <no-reply@accounts.google.com>"}, {"name": "Subject", "value": "Example"}],
        "body": {"data": base64.urlsafe_b64encode(b"Example body").decode()}}}
    get = AsyncMock(side_effect=[result(full), result({"id": "message-a", "raw": ENCODED})])
    class Client:
        def __init__(self, **_kwargs): pass
        async def __aenter__(self): return SimpleNamespace(get=get)
        async def __aexit__(self, *_args): pass
    token = AsyncMock(return_value="test-only-token")
    monkeypatch.setattr(gmail, "_access_token_for", token)
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    response = Response()
    detail = await routes.gmail_message_detail("message-a", response, device_id="device-a", email="account-a@example.test", include_original=include_original)
    token.assert_awaited_once_with("device-a", "account-a@example.test")
    assert detail.account == "account-a@example.test"
    assert detail.raw_base64url == (ENCODED if include_original else None)
    assert detail.body == "Example body"
    assert get.await_count == (2 if include_original else 1)
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Vary"] == "Authorization"


@pytest.mark.asyncio
async def test_original_transport_is_authenticated_and_rejects_other_device(monkeypatch):
    import server
    from core.auth import _issue
    from core.db import db
    owner = "gmail-original-" + uuid.uuid4().hex
    token, credential = _issue(owner)
    await db.devices.insert_one({"device_id": owner, **credential})
    provider = AsyncMock()
    monkeypatch.setattr(gmail, "_access_token_for", provider)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            path = "/api/gmail/message/message-a?include_original=true&device_id=other-device"
            assert (await client.get(path)).status_code == 401
            assert (await client.get(path, headers={"Authorization": f"Bearer {token}"})).status_code == 403
        provider.assert_not_awaited()
    finally:
        await db.devices.delete_one({"device_id": owner})
