"""Provider contract tests use mocked HTTP, never live credentials or paid requests."""
import json

import httpx
import pytest

from services.business_provider_adapters import (
    ProviderUnavailable, fetch_abn_lookup, fetch_brandfetch, fetch_twilio_lookup,
)


@pytest.mark.asyncio
async def test_brandfetch_returns_untrusted_logo_candidates(monkeypatch):
    monkeypatch.setenv("BRANDFETCH_API_KEY", "test-key")
    def handler(request):
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"name": "Example", "logos": [
            {"type": "logo", "formats": [{"format": "png", "src": "https://cdn.example/logo.png"}]}
        ]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_brandfetch("example.com", client=client)
    assert result["logo_candidates"] == ["https://cdn.example/logo.png"]
    assert "verified" not in result


@pytest.mark.asyncio
async def test_abn_active_status_requires_matching_abn(monkeypatch):
    monkeypatch.setenv("ABN_LOOKUP_GUID", "test-guid")
    def handler(request):
        assert request.url.params["guid"] == "test-guid"
        return httpx.Response(200, text='apolloCallback(' + json.dumps({
            "Abn": "51824753556", "AbnStatus": "Active", "EntityName": "Example Pty Ltd"
        }) + ');')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_abn_lookup("51824753556", client=client)
    assert result["registration_confirmed"]


@pytest.mark.asyncio
async def test_twilio_defaults_to_free_basic_lookup(monkeypatch):
    monkeypatch.setenv("TWILIO_API_KEY", "test-sid")
    monkeypatch.setenv("TWILIO_API_SECRET", "test-secret")
    monkeypatch.delenv("TWILIO_LOOKUP_FIELDS", raising=False)
    def handler(request):
        assert "Fields" not in request.url.params
        assert request.url.params["CountryCode"] == "AU"
        assert request.headers.get("authorization", "").startswith("Basic ")
        return httpx.Response(200, json={"valid": True, "phone_number": "+611300123456", "country_code": "AU"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_twilio_lookup("1300 123 456", client=client)
    assert result["paid_fields_requested"] == []
    assert result["caller_authenticated"] is False


@pytest.mark.asyncio
async def test_twilio_rejects_unapproved_paid_fields(monkeypatch):
    monkeypatch.setenv("TWILIO_API_KEY", "test-sid")
    monkeypatch.setenv("TWILIO_API_SECRET", "test-secret")
    monkeypatch.setenv("TWILIO_LOOKUP_FIELDS", "caller_name")
    with pytest.raises(ValueError, match="unapproved"):
        await fetch_twilio_lookup("1300 123 456")


@pytest.mark.asyncio
async def test_unconfigured_brandfetch_fails_closed(monkeypatch):
    monkeypatch.delenv("BRANDFETCH_API_KEY", raising=False)
    with pytest.raises(ProviderUnavailable):
        await fetch_brandfetch("example.com")
