"""Free Knowledge Base phases 3–5 and the device clean-up: the Official Organisation Directory (verdicts, admin editor,
official-contacts lookup), ApolloSG observed patterns, the cross-source record in Magnum DI's brief, Google test phones,
the real-phones Devices view and the preview-data purge."""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from core.db import now_utc

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE = os.environ.get("APOLLO_API", "http://localhost:8001/api")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
PHONE = {"platform": "android", "adapter_mode": "native", "app_version": "9.9.9", "tz_offset_minutes": 0, "locale": "en-US",
         "manufacturer": "OnePlus", "model": "OnePlus8Pro", "os_name": "Android", "os_version": "11", "country": "US"}
ADMIN_KEY = os.environ.get("APOLLO_ADMIN_KEY", "")


@pytest.fixture()
def admin_cookie():
    token = f"test-{uuid.uuid4().hex}"
    DB.admin_sessions.insert_one({"token": token, "email": "phase35-test@apollo.test", "expires_at": now_utc() + timedelta(minutes=5)})
    yield {"apollo_admin": token}
    DB.admin_sessions.delete_one({"token": token})


def _register(**extra) -> tuple[str, dict]:
    r = httpx.post(f"{BASE}/devices/register", json={**PHONE, **extra}, timeout=20)
    assert r.status_code == 201, r.text
    body = r.json()
    return body["device_id"], {"Authorization": f"Bearer {body['device_token']}"}


# ── Google test phones and the real-phones view ─────────────────────────────────────────────────

def test_a_google_test_phone_is_labelled_when_it_signs_up_and_is_not_a_real_phone(admin_cookie):
    robot, _ = _register(test_lab=True)
    real, _ = _register()
    try:
        assert DB.devices.find_one({"device_id": robot})["test_device"] == "google_test_lab"
        assert DB.devices.find_one({"device_id": real}).get("test_device") is None
        page = httpx.get(f"{BASE}/admin/device-list", cookies=admin_cookie, timeout=30).text
        assert "Real phones" in page and 'data-testid="device-view-all"' in page
        assert f"title='{real}'" in page and f"title='{robot}'" not in page
        everything = httpx.get(f"{BASE}/admin/device-list?view=all&platform=android", cookies=admin_cookie, timeout=30).text
        assert f"title='{robot}'" in everything and "Google test phone" in everything
    finally:
        DB.devices.delete_many({"device_id": {"$in": [robot, real]}})


def test_a_heartbeat_from_a_test_phone_labels_an_existing_record_and_an_ordinary_one_never_clears_it():
    device_id, auth = _register()
    try:
        assert httpx.post(f"{BASE}/devices/heartbeat", json={**PHONE, "test_lab": True}, headers=auth, timeout=20).status_code == 200
        assert httpx.post(f"{BASE}/devices/heartbeat", json=PHONE, headers=auth, timeout=20).status_code == 200
        assert DB.devices.find_one({"device_id": device_id})["test_device"] == "google_test_lab"
    finally:
        DB.devices.delete_one({"device_id": device_id})


def test_record_types_and_the_real_phone_rule():
    from services.device_stats import REAL_PHONES, record_type
    assert record_type({"platform": "android", "adapter_mode": "native"}) == "Phone"
    assert record_type({"platform": "android", "adapter_mode": "native", "test_device": "google_test_lab"}) == "Google test phone"
    assert record_type({"platform": "web", "adapter_mode": "mock"}) == "Test or script"
    assert record_type({"platform": "android", "adapter_mode": "standard"}) == "Test or script"
    assert REAL_PHONES["test_device"] is None


@pytest.mark.skipif(not ADMIN_KEY, reason="APOLLO_ADMIN_KEY not configured")
def test_an_admin_can_mark_and_unmark_a_test_phone():
    device_id, _ = _register()
    headers = {"X-Admin-Key": ADMIN_KEY}
    try:
        r = httpx.post(f"{BASE}/admin/devices/{device_id}/test-device", json={"reason": "Play pre-launch report"}, headers=headers, timeout=20)
        assert r.status_code == 200 and DB.devices.find_one({"device_id": device_id})["test_device"] == "google_test_lab"
        listed = httpx.get(f"{BASE}/admin/devices/{device_id}", headers=headers, timeout=20)
        assert listed.status_code == 200 and listed.json()["test_device"] == "google_test_lab"
        httpx.post(f"{BASE}/admin/devices/{device_id}/test-device", json={"test_device": False}, headers=headers, timeout=20)
        assert DB.devices.find_one({"device_id": device_id})["test_device"] is None
        assert httpx.post(f"{BASE}/admin/devices/nope/test-device", json={}, headers=headers, timeout=20).status_code == 404
        assert httpx.post(f"{BASE}/admin/devices/{device_id}/test-device", json={}, timeout=20).status_code in (401, 403)
    finally:
        DB.devices.delete_one({"device_id": device_id})


# ── Preview data copied into production ──────────────────────────────────────────────────────────

def test_the_purge_removes_only_copied_records_and_keeps_production_and_content(monkeypatch):
    """Against a throwaway database."""
    from services import preview_purge
    from services.higgins import provider

    async def run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        scratch = client[f"purge_test_{uuid.uuid4().hex[:8]}"]
        monkeypatch.setattr(preview_purge, "db", scratch)
        cutoff = datetime(2026, 9, 22, 1, 5, tzinfo=timezone.utc)
        before, after = cutoff - timedelta(days=3), cutoff + timedelta(days=30)
        try:
            await scratch.devices.insert_many([{"device_id": "copied1", "platform": "web", "created_at": before},
                                               {"device_id": "copied2", "platform": "android", "created_at": cutoff},
                                               {"device_id": "prod1", "platform": "android", "created_at": after}])
            await scratch.patrol_events.insert_many([{"e": 1, "created_at": before}, {"e": 2, "created_at": after},
                                                     {"e": 3, "created_at": "2026-09-01"}])          # a string time never matches
            await scratch.admin_audit.insert_many([{"a": 1, "timestamp": before}, {"a": 2, "at": after}])
            await scratch.evidence_receipts.insert_many([{"device_id": "copied1"}, {"device_id": "prod1"}])
            await scratch.intel_reuse_metrics.insert_many([{"day": "2026-09-21"}, {"day": "2026-09-22"}])
            await scratch.higgins_knowledge.insert_one({"kind": "official_organisation", "created_at": before})
            await scratch.threat_indicators.insert_one({"source": "phishtank", "created_at": before})

            found = await preview_purge.scan(cutoff)
            assert found["devices"] == 2 and found["productionDevicesKept"] == 1
            assert found["toDelete"] == {"admin_audit": 1, "devices": 2, "evidence_receipts": 1, "intel_reuse_metrics": 1, "patrol_events": 1}
            assert found["devicesByPlatform"] == {"web": 1, "android": 1}

            monkeypatch.setattr(provider, "preview_environment", lambda: True)
            assert (await preview_purge.start(cutoff, (2, 2)))["started"] is False      # never on the preview server
            monkeypatch.setattr(provider, "preview_environment", lambda: False)
            assert (await preview_purge.start(cutoff, (5, 9)))["reason"] == "device count outside the expected range"
            assert await scratch.devices.count_documents({}) == 3

            started = await preview_purge.start(cutoff, (1, 3))
            assert started["started"] is True
            for _ in range(50):
                status = await preview_purge.status(started["run_id"])
                if status["state"] != "running":
                    break
                await asyncio.sleep(0.1)
            assert status["state"] == "done" and status["removed"]["devices"] == 2
            assert [d["device_id"] async for d in scratch.devices.find({})] == ["prod1"]
            assert sorted([e["e"] async for e in scratch.patrol_events.find({})]) == [2, 3]
            assert [r["device_id"] async for r in scratch.evidence_receipts.find({})] == ["prod1"]
            assert [r["day"] async for r in scratch.intel_reuse_metrics.find({})] == ["2026-09-22"]
            assert await scratch.higgins_knowledge.count_documents({}) == 1 and await scratch.threat_indicators.count_documents({}) == 1
        finally:
            await client.drop_database(scratch.name)
            client.close()

    asyncio.run(run())


def test_a_cutoff_must_be_a_past_time():
    from services.preview_purge import parse_cutoff
    assert parse_cutoff("2026-09-22T01:05:00Z").tzinfo is not None
    for bad in ("2025-01-01T00:00:00Z", "2099-01-01T00:00:00Z", "not a time"):
        with pytest.raises(ValueError):
            parse_cutoff(bad)


@pytest.mark.skipif(not ADMIN_KEY, reason="APOLLO_ADMIN_KEY not configured")
def test_the_purge_route_needs_the_typed_confirmation_and_refuses_on_the_preview():
    headers = {"X-Admin-Key": ADMIN_KEY}
    body = {"cutoff": "2026-09-22T01:05:00Z", "expected_devices_min": 0, "expected_devices_max": 100000}
    assert httpx.post(f"{BASE}/admin/preview-data/purge", json={**body, "confirm": "yes"}, headers=headers, timeout=60).status_code == 422
    r = httpx.post(f"{BASE}/admin/preview-data/purge", json={**body, "confirm": "DELETE PREVIEW DATA"}, headers=headers, timeout=120)
    assert r.status_code == 200 and r.json()["started"] is False and "preview server" in r.json()["reason"]
    assert httpx.get(f"{BASE}/admin/preview-data/scan?cutoff=2099-01-01", headers=headers, timeout=20).status_code == 422


# ── Official Organisation Directory ──────────────────────────────────────────────────────────────

FAKE = {"key": "testbank", "name": "Testbank", "sector": "bank", "aliases": ["test bank"], "origin": "admin",
        "domains": [{"domain": "testbank.com.au", "status": "curated"}],
        "phones": [{"number": "13 99 99", "national": "139999", "label": "General enquiries", "status": "confirmed",
                    "source_url": "https://www.testbank.com.au/contact"}],
        "emails": [{"address": "hoax@testbank.com.au", "label": "Report a scam", "status": "confirmed",
                    "source_url": "https://www.testbank.com.au/contact"}],
        "sources": [{"url": "https://www.testbank.com.au/contact", "status": "read"}]}


@pytest.fixture()
def fake_directory(monkeypatch):
    from services import org_directory
    from services.higgins import brand_domains, indicators
    now = now_utc()
    org = {**FAKE, "phones": [{**p, "confirmed_at": now} for p in FAKE["phones"]],
           "emails": [{**e, "confirmed_at": now} for e in FAKE["emails"]]}
    monkeypatch.setitem(indicators.BRANDS, "testbank", ("Testbank", "testbank.com.au"))
    saved = (dict(org_directory._VIEW), dict(org_directory._SOURCES), dict(brand_domains.DIRECTORY))
    org_directory._apply([org])
    yield org_directory
    org_directory._VIEW.clear(), org_directory._VIEW.update(saved[0])
    org_directory._SOURCES.clear(), org_directory._SOURCES.update(saved[1])
    brand_domains.DIRECTORY.clear(), brand_domains.DIRECTORY.update(saved[2])


def test_published_contacts_and_the_not_the_official_contact_warning(fake_directory):
    d = fake_directory
    assert d.number_verdict("+61 13 99 99")["status"] == "published"
    warn = d.number_verdict("0412 345 678", "Test Bank")
    assert warn["status"] == "not_published" and warn["use_instead"][0]["value"] == "13 99 99"
    assert d.number_verdict("0412 345 678") is None                               # nobody named: nothing to compare
    assert d.email_verdict("HOAX@testbank.com.au")["status"] == "published"
    assert d.email_verdict("support@gmail.com", "Testbank")["status"] == "not_published"
    assert d.email_verdict("alerts@testbank.com.au", "Testbank") is None          # its own domain
    assert d.site_verdict("www.testbank.com.au")["status"] == "official"
    assert d.site_verdict("testbank-verify.net")["status"] == "lookalike"
    unrelated = d.site_verdict("secure-login.xyz", "testbank")
    assert unrelated["status"] == "not_official" and unrelated["official_domain"] == "testbank.com.au"
    assert d.site_verdict("scamwatch.gov.au", "Testbank") is None                 # a government website never is
    assert d.host_of("https://a.example.com/x?y") == "a.example.com" and d.host_of("x@b.example") == "b.example"
    assert d.host_of("testbank.com.au/login") == "testbank.com.au"
    found = d.verdicts("Testbank", ["https://secure-login.xyz/a", "https://secure-login.xyz/a"], ["0412 345 678"], [])
    assert [(v["kind"], v["status"]) for v in found] == [("site", "not_official"), ("phone", "not_published")]


def test_every_warning_carries_the_organisations_main_published_number_to_call(fake_directory):
    d = fake_directory
    main = {"value": "13 99 99", "label": "General enquiries", "source_url": "https://www.testbank.com.au/contact"}
    assert d.number_verdict("0412 345 678", "Testbank")["call"] == main
    assert d.email_verdict("support@gmail.com", "Testbank")["call"] == main
    assert d.site_verdict("testbank-verify.net")["call"] == main
    assert d.site_verdict("secure-login.xyz", "Testbank")["call"] == main
    assert "call" not in d.number_verdict("13 99 99") and "call" not in d.site_verdict("testbank.com.au")   # its own: no warning


def test_an_unconfirmed_number_never_counts(fake_directory):
    d = fake_directory
    stale = {**FAKE, "phones": [{**FAKE["phones"][0], "confirmed_at": now_utc() - d.CONFIRM_WINDOW - timedelta(days=1)}], "emails": []}
    d._apply([stale])
    assert d.number_verdict("13 99 99") is None and d.number_verdict("0412 345 678", "Testbank") is None


def test_the_official_contacts_lookup_answers_a_device_and_keeps_nothing(fake_directory):
    _, auth = _register(platform="web", adapter_mode="mock")
    r = httpx.post(f"{BASE}/official/contacts", json={"claimed_org": "CommBank", "phones": ["13 22 21", "0412 345 678"],
                                                      "sites": ["https://commbank-alerts.net/login"], "emails": []}, headers=auth, timeout=20)
    assert r.status_code == 200
    kinds = {(v["kind"], v["value"]): v for v in r.json()["verdicts"]}
    assert kinds[("site", "https://commbank-alerts.net/login")]["status"] == "lookalike"
    phone = kinds.get(("phone", "0412 345 678"))
    if phone:                                    # only once CommBank's published numbers are confirmed on its pages
        assert phone["status"] == "not_published" and phone["use_instead"]
    assert httpx.post(f"{BASE}/official/contacts", json={"phones": ["1"] * 21}, headers=auth, timeout=20).status_code == 422
    assert httpx.post(f"{BASE}/official/contacts", json={"phones": []}, timeout=20).status_code == 401
    names = httpx.get(f"{BASE}/official/names", headers=auth, timeout=20).json()["organisations"]
    commbank = next(o for o in names if o["name"] == "CommBank")
    assert "commonwealth bank" in commbank["aliases"]


def test_an_admin_entry_needs_a_name_domains_and_an_official_source_page():
    from services.org_directory import parse_form
    record, problems = parse_form({"name": "Example Credit Union", "sector": "bank", "domains": "examplecu.com.au",
                                   "phones": "13 11 11 | General enquiries\nabc", "emails": "help@examplecu.com.au",
                                   "sources": "https://www.examplecu.com.au/contact http://www.examplecu.com.au/x https://evil.example/contact"})
    assert record["phones"][0] == {"number": "13 11 11", "label": "General enquiries"}
    assert "abc isn't a phone number." in problems
    assert any(p.startswith("http://www.examplecu.com.au/x isn't") for p in problems)
    assert any(p.startswith("https://evil.example/contact isn't") for p in problems)
    _, missing = parse_form({"name": "", "sector": "nope", "domains": "", "sources": ""})
    assert {"Give the organisation's name.", "Pick a sector.", "Add at least one of the organisation's own domains.",
            "Add at least one official source page."} <= set(missing)
    record, ok = parse_form({"name": "Example CU", "sector": "bank", "domains": "examplecu.com.au", "sources": "https://www.scamwatch.gov.au/x"})
    assert not ok, "an official authority's page counts as a source"


def test_admins_add_edit_and_remove_an_organisation_in_the_portal(admin_cookie):
    from services import org_directory
    key = f"apollo-test-org-{uuid.uuid4().hex[:6]}"
    form = {"key": key, "name": f"Apollo Test Org {key[-6:]}", "sector": "telco", "aliases": "", "domains": "apollo-test-org.example",
            "phones": "1300 000 000 | Support", "emails": "", "sources": "https://www.scamwatch.gov.au/"}
    try:
        page = httpx.get(f"{BASE}/admin/org-directory", cookies=admin_cookie, timeout=30)
        assert page.status_code == 200 and 'data-testid="org-form"' in page.text and "data-testid='org-row-commbank'" in page.text
        assert 'data-testid="observed-heading"' in page.text
        bad = httpx.post(f"{BASE}/admin/org-directory/save", data={**form, "sources": ""}, cookies=admin_cookie, timeout=30)
        assert bad.status_code == 400 and "Add at least one official source page." in bad.text
        saved = httpx.post(f"{BASE}/admin/org-directory/save", data=form, cookies=admin_cookie, timeout=30, follow_redirects=False)
        assert saved.status_code == 303 and "done=saved" in saved.headers["location"]
        doc = DB.higgins_knowledge.find_one({"kind": org_directory.KIND, "key": key})
        assert doc["origin"] == "admin" and doc["phones"][0]["label"] == "Support" and doc["sources"][0]["url"] == "https://www.scamwatch.gov.au/"
        edit = httpx.get(f"{BASE}/admin/org-directory?edit={key}", cookies=admin_cookie, timeout=30).text
        assert "1300 000 000 | Support" in edit and "data-testid='org-archive'" in edit
        assert DB.admin_audit.find_one({"action": "org_directory_save", "detail": {"$regex": key}}) or \
            DB.admin_audit.find_one({"action": "org_directory_save"})
        removed = httpx.post(f"{BASE}/admin/org-directory/archive", data={"key": key}, cookies=admin_cookie, timeout=30, follow_redirects=False)
        assert removed.status_code == 303
        assert DB.higgins_knowledge.find_one({"kind": org_directory.KIND, "key": key})["status"] == "archived"
        assert httpx.get(f"{BASE}/admin/org-directory", timeout=20, follow_redirects=False).status_code == 303
    finally:
        DB.higgins_knowledge.delete_many({"kind": org_directory.KIND, "key": key})


# ── Observed patterns and the cross-source record ────────────────────────────────────────────────

def test_a_pattern_counts_separate_devices_and_never_the_one_checking(monkeypatch):
    from services import observed_intel

    async def run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        scratch = client[f"observed_test_{uuid.uuid4().hex[:8]}"]
        monkeypatch.setattr(observed_intel, "db", scratch)
        try:
            key, name = observed_intel.subject("domain", "https://login.scam-example-parcel.top/pay")
            assert key.startswith("domain:") and name == "scam-example-parcel.top"
            now = now_utc()
            for device in ("device-alpha", "device-bravo", "device-alpha"):
                await observed_intel._add("observed", key, device, now, {"subject_kind": "domain", "readable": name})
            doc = await scratch.threat_indicators.find_one({"key": key})
            assert doc["devices_30d"] == 2 and doc["hostname"] == "" and "device-alpha" not in str(doc)
            await observed_intel._add("observed", key, "device-charlie", now, {"subject_kind": "domain", "readable": name})
            assert (await scratch.threat_indicators.find_one({"key": key}))["hostname"] == name    # shown once 3 devices saw it
            assert (await observed_intel.assertion("domain", "scam-example-parcel.top"))["level"] == "known_malicious"
            assert (await observed_intel.assertion("domain", "scam-example-parcel.top", exclude="device-charlie"))["level"] == "suspected_malicious"
        finally:
            await client.drop_database(scratch.name)
            client.close()

    asyncio.run(run())


def test_official_and_shared_addresses_are_never_recorded():
    from services.observed_intel import subject
    assert subject("domain", "https://www.commbank.com.au/x") is None
    assert subject("domain", "https://docs.google.com/forms/x") is None
    assert subject("email", "someone@commbank.com.au") is None
    assert subject("email", "scammer@gmail.com") is not None                     # one person's free mail account may be
    key, readable = subject("phone", "0412 345 678")
    assert readable is None and "0412" not in key


def test_magnum_di_gets_the_cross_source_record_as_context():
    from services.correlation import brief_lines
    from services.higgins.tc_flyby import report
    record = [{"kind": "website", "subject": "bad.example", "agreement": "1 of 3 sources that answered list it",
               "sources": [{"source": "PhishTank", "status": "listed", "reference": "8812", "lastConfirmed": "2026-10-26T01:00:00+00:00",
                            "expires": "2026-10-29T01:00:00+00:00"},
                           {"source": "OpenPhish", "status": "not listed"}, {"source": "Spamhaus DROP", "status": "not checked (list out of date)"}]}]
    lines = brief_lines(record)
    assert "website bad.example: 1 of 3 sources that answered list it." in lines
    assert "PhishTank: listed (ref 8812, last confirmed 2026-10-26, counts until 2026-10-29)" in lines
    brief = report.magnum_brief([], [], {}, None, None, record)
    assert "Cross-source record" in brief and "context, not new findings" in brief
    assert "Cross-source record" not in report.magnum_brief([], [], {}, None, None, [])


def test_the_rule_book_states_the_directory_and_pattern_rules():
    from services import observed_intel, org_directory
    book = (Path(__file__).resolve().parents[1] / "content" / "rulebook.md").read_text()
    assert f"within the last {org_directory.CONFIRM_WINDOW.days} days" in book
    assert f"once {observed_intel.THRESHOLD} independent devices support it" in book
    assert f"{observed_intel.THRESHOLD} or more independent supporting findings from other devices, unanimous: \"{observed_intel.SAID['known_malicious']}\"" in book
    assert f"{observed_intel.MEDIUM}, unanimous: \"{observed_intel.SAID['suspected_malicious']}\"" in book
    assert f"at least {observed_intel.THRESHOLD} together: \"{observed_intel.SAID['mixed']}\"" in book
    assert f"marks older than {observed_intel.WINDOW.days} days are dropped" in book
    assert "Every check result" in book and "Google's test phones" in book
