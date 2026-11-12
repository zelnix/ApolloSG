from datetime import datetime, timedelta, timezone

import pytest

from services.business_registry_weekly import refresh_one
from services.verified_businesses import BusinessSource, VerifiedBusiness, approved_logo_for_number

NOW = datetime.now(timezone.utc)


def fixture():
    return VerifiedBusiness(
        business_id="example", legal_name="Example Pty Ltd", abn="51824753556",
        abn_registration_confirmed=True, official_domain="example.com",
        published_numbers=["1300 123 456"], logo_url="https://cdn.example/logo.png",
        logo_domain_confirmed=True, last_reviewed_at=NOW,
        sources=[
            BusinessSource(provider="abn_lookup", reference="ABR", checked_at=NOW, supports="registration"),
            BusinessSource(provider="brandfetch", reference="example.com", checked_at=NOW, supports="brand_asset"),
            BusinessSource(provider="official_business_site", reference="https://example.com/contact", checked_at=NOW, supports="number_association"),
        ],
    )


@pytest.mark.asyncio
async def test_weekly_refresh_requires_all_provider_checks(monkeypatch):
    import services.business_registry_weekly as worker

    async def abn(_):
        return {"registration_confirmed": True, "entity_name": "Example Pty Ltd"}
    async def brand(_):
        return {"domain_queried": "example.com", "logo_candidates": ["https://cdn.example/logo.png"]}
    async def phone(_):
        return {"valid": True}
    monkeypatch.setattr(worker, "fetch_abn_lookup", abn)
    monkeypatch.setattr(worker, "fetch_brandfetch", brand)
    monkeypatch.setattr(worker, "fetch_twilio_lookup", phone)
    assert await refresh_one(fixture().model_dump())
    async def invalid(_):
        return {"valid": False}
    monkeypatch.setattr(worker, "fetch_twilio_lookup", invalid)
    assert not await refresh_one(fixture().model_dump())


def test_expired_logo_is_not_displayed():
    business = fixture()
    business.last_reviewed_at = NOW - timedelta(days=8)
    assert approved_logo_for_number(business, "1300 123 456") is None
