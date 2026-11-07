"""Device telemetry, the admin Devices list, Reset Stats, and the Family Help two-phone test page."""
import asyncio
import os
import uuid
from datetime import timedelta

import httpx
import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from core.db import now_utc
from routers.admin_portal import FAMILY_HELP_TEST_GUIDE

BASE = os.environ.get("APOLLO_API", "http://localhost:8001/api")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
PHONE = {"platform": "android", "adapter_mode": "native", "app_version": "9.9.9", "tz_offset_minutes": 600, "locale": "en-AU",
         "manufacturer": "Samsung", "model": "SM-TEST1", "os_name": "Android", "os_version": "14", "country": "AU",
         "installed_at": "2026-10-01T09:30:00Z"}


@pytest.fixture()
def admin_cookie():
    token = f"test-{uuid.uuid4().hex}"
    DB.admin_sessions.insert_one({"token": token, "email": "devices-test@apollo.test", "expires_at": now_utc() + timedelta(minutes=5)})
    yield {"apollo_admin": token}
    DB.admin_sessions.delete_one({"token": token})


@pytest.fixture()
def phone():
    r = httpx.post(f"{BASE}/devices/register", json=PHONE, timeout=20)
    assert r.status_code == 201
    body = r.json()
    yield body["device_id"], {"Authorization": f"Bearer {body['device_token']}"}
    DB.devices.delete_one({"device_id": body["device_id"]})


def test_registration_keeps_what_the_phone_is(phone):
    device_id, _ = phone
    doc = DB.devices.find_one({"device_id": device_id})
    assert (doc["manufacturer"], doc["model"], doc["os_name"], doc["os_version"], doc["country"]) == ("Samsung", "SM-TEST1", "Android", "14", "AU")
    assert doc["installed_at"].isoformat().startswith("2026-10-01T09:30")


def test_heartbeat_updates_it_and_an_older_app_leaves_it_alone(phone):
    device_id, auth = phone
    r = httpx.post(f"{BASE}/devices/heartbeat", json={**PHONE, "os_version": "15"}, headers=auth, timeout=20)
    assert r.status_code == 200 and DB.devices.find_one({"device_id": device_id})["os_version"] == "15"
    old_app = {k: PHONE[k] for k in ("platform", "adapter_mode", "app_version", "tz_offset_minutes", "locale")}
    assert httpx.post(f"{BASE}/devices/heartbeat", json=old_app, headers=auth, timeout=20).status_code == 200
    assert DB.devices.find_one({"device_id": device_id})["model"] == "SM-TEST1"


def test_a_numeric_region_is_refused():
    assert httpx.post(f"{BASE}/devices/register", json={**PHONE, "country": "419"}, timeout=20).status_code == 422


def test_reads_count_different_articles_and_alerts_once_each(phone):
    device_id, auth = phone
    post = lambda body: httpx.post(f"{BASE}/devices/activity", json=body, headers=auth, timeout=20)  # noqa: E731
    for body in ({"kind": "device_check"}, {"kind": "device_check"}, {"kind": "learn_read", "item": "romance-scams"},
                 {"kind": "learn_read", "item": "romance-scams"}, {"kind": "learn_read", "item": "parcel-scams"},
                 {"kind": "scam_alert_read", "item": "https://www.scamwatch.gov.au/a"}):
        assert post(body).status_code == 204
    assert post({"kind": "learn_read"}).status_code == 422
    assert httpx.post(f"{BASE}/devices/activity", json={"kind": "device_check"}, timeout=20).status_code == 401
    stats = DB.devices.find_one({"device_id": device_id})["stats"]
    assert stats["device_checks"] == 2 and len(stats["learn_read"]) == 2 and len(stats["scam_alerts_read"]) == 1
    assert "romance-scams" not in str(stats)


def test_the_devices_page_lists_each_phone_with_its_counts(admin_cookie, phone):
    device_id, auth = phone
    httpx.post(f"{BASE}/devices/activity", json={"kind": "device_check"}, headers=auth, timeout=20)
    r = httpx.get(f"{BASE}/admin/device-list?platform=android", cookies=admin_cookie, timeout=30)
    assert r.status_code == 200
    page = r.text
    for heading in ("Manufacturer", "Model", "OS version", "Country", "Date installed", "App version", "TC Hawkeye", "Magnum DI",
                    "Ask Higgins", "Device checks", "Learn with Higgins read", "Scam alerts read"):
        assert f"<th>{heading}</th>" in page
    assert f"title='{device_id}'" in page and "SM-TEST1" in page and "<td>AU</td>" in page
    assert 'href="/api/admin/device-list"' in page and 'data-testid="reset-stats-button"' in page


def test_reset_needs_the_typed_confirmation(admin_cookie):
    r = httpx.post(f"{BASE}/admin/reset-stats", data={"confirm": "yes"}, cookies=admin_cookie, timeout=20, follow_redirects=False)
    assert r.status_code == 400
    assert httpx.post(f"{BASE}/admin/reset-stats", data={"confirm": "RESET"}, timeout=20, follow_redirects=False).status_code == 303


def test_reset_deletes_usage_and_cost_records_and_zeroes_counts_but_keeps_devices(monkeypatch):
    """Against a throwaway database, so the preview's own records are untouched."""
    from services import stats_reset

    async def run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        scratch = client[f"reset_test_{uuid.uuid4().hex[:8]}"]
        monkeypatch.setattr(stats_reset, "db", scratch)
        now = now_utc()
        try:
            for name in stats_reset.USAGE_COLLECTIONS:
                await scratch[name].insert_many([{"n": 1}, {"n": 2}])
            await scratch.investigation_cases.insert_many([{"case_id": "old", "expires_at": now - timedelta(hours=1)},
                                                           {"case_id": "open", "expires_at": now + timedelta(minutes=10)}])
            await scratch.higgins_knowledge.insert_one({"kind": "alert", "hits": 7})
            await scratch.reusable_intelligence.insert_one({"cache_id": "c", "hits": 3})
            await scratch.devices.insert_one({"device_id": "d1", "stats": {"ask_higgins": 4, "learn_read": ["a"]}})
            await scratch.family_links.insert_one({"link": 1})
            done = await stats_reset.reset_stats()
            assert done["gemini_usage"] == 2 and done["investigation_cases"] == 1 and done["device_counts"] == 1
            for name in stats_reset.USAGE_COLLECTIONS:
                assert await scratch[name].count_documents({}) == 0
            assert [c["case_id"] async for c in scratch.investigation_cases.find({})] == ["open"]
            assert (await scratch.higgins_knowledge.find_one({}))["hits"] == 0
            assert (await scratch.reusable_intelligence.find_one({}))["hits"] == 0
            device = await scratch.devices.find_one({"device_id": "d1"})
            assert device and "stats" not in device
            assert await scratch.family_links.count_documents({}) == 1
        finally:
            await client.drop_database(scratch.name)
            client.close()

    asyncio.run(run())


def test_the_family_help_test_page_shows_the_checklist_readiness_and_sessions(admin_cookie):
    r = httpx.get(f"{BASE}/admin/family-help-test", cookies=admin_cookie, timeout=20)
    assert r.status_code == 200
    page = r.text
    assert 'href="/api/admin/family-help-test"' in page and 'data-testid="family-help-test-guide"' in page
    assert ("Server ready" in page) or ("Server not ready" in page)
    headings = [line[3:].strip() for line in FAMILY_HELP_TEST_GUIDE.read_text().splitlines() if line.startswith("## ")]
    for h in headings:
        assert f"<summary><h2>{h.replace('&', '&amp;')}</h2></summary>" in page
    assert 'type="checkbox"' in page and "Recent Family Help sessions" in page
    pdf = httpx.get(f"{BASE}/admin/reports/family-help-test/pdf", cookies=admin_cookie, timeout=60)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_signed_out_visitors_are_sent_to_login():
    for path in ("/admin/device-list", "/admin/family-help-test"):
        r = httpx.get(f"{BASE}{path}", timeout=20, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].endswith("/api/admin/login")
