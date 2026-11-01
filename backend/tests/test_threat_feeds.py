"""Free threat feeds (services/threat_feeds.py): parsing each free list into ApolloSG's own stores, freshness, lookups,
delisting, the shrink guard, and the admin "Refresh now".

Run: cd /app/backend && python -m pytest tests/test_threat_feeds.py -q
"""
from __future__ import annotations

import gzip
import json
import os
import uuid
from datetime import timedelta

import httpx
import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from core.db import now_utc
from services import threat_feeds as tf

BASE = os.environ.get("APOLLO_API", "http://localhost:8001/api")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]


@pytest.fixture()
async def scratch(monkeypatch):
    """A throwaway database, so the preview's real lists are untouched."""
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[f"threat_feeds_{uuid.uuid4().hex[:8]}"]
    monkeypatch.setattr(tf, "db", db)
    tf._fresh_cache.clear()
    yield db
    tf._fresh_cache.clear()
    await client.drop_database(db.name)
    client.close()


async def _fresh(db, *feed_ids):
    for feed_id in feed_ids:
        await db.learning_feed_state.insert_one({"feed_id": feed_id, "status": "fresh", "last_success_at": now_utc(), "last_checked_at": now_utc()})
    tf._fresh_cache.clear()


# ── Parsing ────────────────────────────────────────────────────────────────────

def test_phishtank_keeps_only_verified_pages_that_are_online():
    data = json.dumps([
        {"phish_id": 1, "url": "https://www.evil-login.example/path/?q=1", "verified": "yes", "online": "yes", "target": "PayPal",
         "phish_detail_url": "https://phishtank.org/phish_detail.php?phish_id=1", "submission_time": "2026-10-01T00:00:00+00:00"},
        {"phish_id": 2, "url": "https://unverified.example/", "verified": "no", "online": "yes"},
        {"phish_id": 3, "url": "https://offline.example/", "verified": "yes", "online": "no"},
    ]).encode()
    rows = tf.parse_phishtank([data])
    assert len(rows) == 1
    row = rows[0]
    assert (row["scope"], row["key"], row["hostname"]) == ("url", "evil-login.example/path?q=1", "evil-login.example"), "the query is part of the page"
    assert row["listed_url"] == "https://www.evil-login.example/path/?q=1"
    assert row["source_reference"] == "1" and "targeting PayPal" in row["original_evidence"] and row["whole_site"] is False


def test_openphish_lines_become_exact_pages():
    rows = tf.parse_openphish([b"https://a.example/x\n\nnot a url\nhttp://b.example/\n"])
    assert [r["key"] for r in rows] == ["a.example/x", "b.example/"], "a listed home page is a page, never the website"
    assert all(r["threat_type"] == "SOCIAL_ENGINEERING" and not r["whole_site"] for r in rows)
    assert tf.page_keys("https://www.a.example/x?id=2#top") == ["a.example/x?id=2", "a.example/x"]
    assert tf.page_keys("https://b.example") == ["b.example/"]


def test_a_phishing_listing_never_names_a_whole_platform_or_an_organisations_own_site():
    lines = ["https://google.com/?q=evil", "https://www.google.com/url?q=https://evil.example", "https://facebook.com/",
             "https://docs.google.com/forms/d/e/abc/viewform?usp=sf_link", "https://www.google.com/amp/s/evil.example",
             "https://fake-login.weebly.com/", "https://weebly.com/", "https://auspost.com.au/?track=1"]
    rows = tf.parse_openphish(["\n".join(lines).encode()])
    assert [r["key"] for r in rows] == ["docs.google.com/forms/d/e/abc/viewform?usp=sf_link", "google.com/amp/s/evil.example", "fake-login.weebly.com/"]
    assert not any(r["whole_site"] for r in rows), "a phishing list names pages only"
    assert tf.restricted("google.com") and tf.restricted("weebly.com") and not tf.restricted("fake-login.weebly.com")


def test_spamhaus_drop_networks_carry_their_address_range():
    data = b'{"cidr":"1.2.3.0/24","sblid":"SBL1","rir":"apnic"}\n{"type":"metadata","timestamp":1}\n{"cidr":"2001:db8::/32","sblid":"SBL2"}\n'
    rows = tf.parse_spamhaus_drop([data])
    assert [(r["scope"], r["key"], r["ip_version"]) for r in rows] == [("netblock", "1.2.3.0/24", 4), ("netblock", "2001:db8::/32", 6)]
    v4 = rows[0]
    assert v4["net_start"] == f"{int.from_bytes(bytes([1, 2, 3, 0]), 'big'):032x}" and v4["net_end"].endswith("010203ff")


def test_asic_names_websites_emails_and_phones_but_never_a_whole_platform():
    data = json.dumps([{
        "uniqueIdentifier": "A1", "nameMandatory": "Fake Invest Pty", "investorAlertCategoryMandatory": "Imposter",
        "dateAdded": "2026-01-01", "dateUpdated": "2026-02-01",
        "websites": ["https://www.fake-invest-example.com/", "https://www.facebook.com/fakeinvest", "facebook.com",
                     "www. spaced-example .com (no longer works)", "not a site at all"],
        "emails": ["Contact: Info@Fake-Invest-Example.com"], "phones": ["+61 2 9999 0000", "Fax: +61 2 9999 0001", "12"],
    }]).encode()
    rows = tf.parse_asic([data])
    sites = [(r["key"], r["whole_site"]) for r in rows if r["scope"] == "url"]
    assert sites == [("fake-invest-example.com", True), ("facebook.com/fakeinvest", False), ("spaced-example.com", True)]
    emails = [r for r in rows if r["scope"] == "email"]
    phones = [r for r in rows if r["scope"] == "phone"]
    assert len(emails) == 1 and emails[0]["key"].startswith("email:") and "fake-invest" not in emails[0]["key"].lower(), "kept as a one-way code"
    assert len(phones) == 1 and phones[0]["key"].startswith("phone:")
    assert all(r["threat_type"] == "IMPOSTER_FINANCIAL_SERVICE" and r["source_reference"] == "A1" for r in rows)


def test_acma_lists_gambling_websites_but_not_shared_platforms():
    rows = tf.parse_acma([json.dumps(["Bad-Casino-Example.com", "t.me", "nodot"]).encode()])
    assert [(r["key"], r["whole_site"], r["threat_type"]) for r in rows] == [("bad-casino-example.com", True, "ILLEGAL_GAMBLING")]


def test_kev_nvd_and_attack_become_technical_knowledge_with_provenance():
    kev = tf.parse_kev([json.dumps({"vulnerabilities": [
        {"cveID": "CVE-2024-3400", "vendorProject": "Palo Alto Networks", "product": "PAN-OS", "vulnerabilityName": "Command Injection",
         "dateAdded": "2024-04-12", "shortDescription": "A command injection.", "requiredAction": "Apply updates.",
         "knownRansomwareCampaignUse": "Known"},
        {"cveID": "not-a-cve"}]}).encode()])
    assert len(kev) == 1 and kev[0]["key"] == "CVE-2024-3400" and kev[0]["kind"] == "exploited_vulnerability"
    assert "ransomware" in kev[0]["body"] and "What to do: Apply updates." in kev[0]["body"] and kev[0]["extra"]["source_reference"] == "CVE-2024-3400"
    nvd = tf.parse_nvd([json.dumps({"vulnerabilities": [{"cve": {"id": "CVE-2024-3400", "metrics": {"cvssMetricV31": [
        {"cvssData": {"baseScore": 10.0, "baseSeverity": "CRITICAL", "version": "3.1"}}]}, "descriptions": [{"lang": "en", "value": "x"}]}}]}).encode()])
    assert tf.nvd_line(nvd[0]["nvd"]) == "Severity (NVD): CRITICAL, 10.0/10 on CVSS 3.1."
    attack = tf._attack("mobile")([json.dumps({"objects": [
        {"type": "attack-pattern", "name": "Input Injection", "description": "Text (Citation: Ref) with [a link](https://x).",
         "external_references": [{"source_name": "mitre-attack", "external_id": "T1516", "url": "https://attack.mitre.org/techniques/T1516"}],
         "kill_chain_phases": [{"phase_name": "defense-evasion"}], "x_mitre_platforms": ["Android"]},
        {"type": "attack-pattern", "name": "Old", "x_mitre_deprecated": True,
         "external_references": [{"source_name": "mitre-attack", "external_id": "T1000"}]},
        {"type": "malware", "name": "not a technique"}]}).encode()])
    assert [(r["key"], r["historical"]) for r in attack] == [("mobile:T1516", False), ("mobile:T1000", True)]
    assert attack[0]["body"].startswith("Text with a link.") and "Tactics: Defense Evasion." in attack[0]["body"]


def test_every_feed_is_free_attributed_and_named():
    for feed in tf.FEEDS:
        assert feed.licence and feed.terms.startswith("https://") and feed.publisher
        assert feed.url.startswith("https://") and feed.hosts
    assert set(tf.LISTINGS) == {"phishtank", "openphish", "spamhaus_drop", "asic_investor_alerts", "acma_blocked_gambling"}
    assert tf.LISTINGS["spamhaus_drop"][1] == ("spamhaus-drop-v4", "spamhaus-drop-v6")
    order = [f.feed_id for f in tf.FEEDS]
    assert order.index("cisa-kev") < order.index("nvd-kev"), "NVD's severity is added to KEV entries already held"


def test_a_feed_is_due_daily_and_retried_after_a_failure():
    now = now_utc()
    assert tf.due({}, now)
    assert not tf.due({"status": "fresh", "last_success_at": now - timedelta(hours=23), "last_checked_at": now - timedelta(hours=23)}, now)
    assert tf.due({"status": "fresh", "last_success_at": now - timedelta(hours=25), "last_checked_at": now - timedelta(hours=25)}, now)
    failed = {"status": "unavailable", "last_success_at": now - timedelta(hours=30), "last_checked_at": now - timedelta(hours=1)}
    assert not tf.due(failed, now)
    assert tf.due({**failed, "last_checked_at": now - timedelta(hours=2, minutes=1)}, now)


# ── Lookups ────────────────────────────────────────────────────────────────────

def _doc(feed_id: str, row: dict, **over) -> dict:
    feed = tf.BY_ID[feed_id]
    return {**row, "indicator_id": tf._indicator_id(feed, row), "source": feed_id, "status": "active",
            "last_verified_at": now_utc(), "evidence_expiry_deadline": now_utc() + timedelta(days=1), **over}


async def test_link_checks_report_each_list_as_match_clear_or_not_checked(scratch):
    await scratch.threat_indicators.insert_many([
        _doc("phishtank", tf._indicator("url", "phish.example/login", "phish.example", "9", "Verified phishing page", "SOCIAL_ENGINEERING")),
        _doc("acma-blocked-gambling", tf._indicator("url", "casino.example", "casino.example", None, "Blocked gambling", "ILLEGAL_GAMBLING", whole_site=True)),
        _doc("openphish", tf._indicator("url", "gone.example/x", "gone.example", None, "Old", "SOCIAL_ENGINEERING"), status="expired"),
        _doc("spamhaus-drop-v4", {**tf.parse_spamhaus_drop([b'{"cidr":"203.0.113.0/24","sblid":"SBL9"}'])[0]}),
    ])
    await _fresh(scratch, "phishtank", "openphish", "acma-blocked-gambling", "asic-investor-alerts", "spamhaus-drop-v4")

    by_name = lambda sources: {s.name: s for s in sources}  # noqa: E731
    page = by_name(await tf.listing_sources("www.phish.example", "https://www.phish.example/login?x=1"))
    assert page["phishtank"].status == "match" and "PhishTank" in page["phishtank"].detail
    assert page["openphish"].status == "clear" and page["acma_blocked_gambling"].status == "clear"
    assert page["spamhaus_drop"].status in ("clear", "unavailable")  # depends on this host's DNS; never a match

    other_page = by_name(await tf.listing_sources("phish.example", "https://phish.example/elsewhere"))
    assert other_page["phishtank"].status == "clear", "an exact page listing never names the whole site"
    assert "this exact address" in page["phishtank"].detail and "whole website" not in page["phishtank"].detail

    await scratch.threat_indicators.insert_one(_doc("openphish", tf._indicator("url", "shop.example/page.php?id=1", "shop.example", None, "Phishing page detected by OpenPhish",
                                                                             "SOCIAL_ENGINEERING", listed_url="https://shop.example/page.php?id=1")))
    assert by_name(await tf.listing_sources("shop.example", "https://shop.example/page.php?id=1"))["openphish"].status == "match"
    assert by_name(await tf.listing_sources("shop.example", "https://shop.example/page.php?id=2"))["openphish"].status == "clear", "the query is part of the listed page"
    assert by_name(await tf.listing_sources("shop.example", "https://shop.example/"))["openphish"].status == "clear"

    site = by_name(await tf.listing_sources("shop.casino.example", "https://shop.casino.example/anything"))
    assert site["acma_blocked_gambling"].status == "match" and site["acma_blocked_gambling"].threat_types == ["ILLEGAL_GAMBLING"]

    assert by_name(await tf.listing_sources("gone.example", "https://gone.example/x"))["openphish"].status == "clear", "expired entries stop counting"

    ip = by_name(await tf.listing_sources("203.0.113.7"))
    assert ip["spamhaus_drop"].status == "match" and ip["spamhaus_drop"].threat_types == ["CRIMINAL_NETWORK"]

    await scratch.learning_feed_state.update_one({"feed_id": "openphish"}, {"$set": {"last_success_at": now_utc() - timedelta(days=4)}})
    tf._fresh_cache.clear()
    stale = by_name(await tf.listing_sources("phish.example"))
    assert stale["openphish"].status == "unavailable" and stale["openphish"].failure == "list_out_of_date", "an out-of-date list is never clear"


async def test_asic_names_an_exact_email_address_or_phone_number(scratch):
    rows = tf.parse_asic([json.dumps([{"uniqueIdentifier": "A7", "nameMandatory": "Scam Co", "investorAlertCategoryMandatory": "Unlicensed",
                                        "emails": ["help@scamco-example.com"], "phones": ["+61 3 9000 1234"]}]).encode()])
    await scratch.threat_indicators.insert_many([_doc("asic-investor-alerts", row, publisher="ASIC", entity="Scam Co", category="Unlicensed") for row in rows])
    email = await tf.listed("email", "HELP@scamco-example.com ")
    assert len(email) == 1 and email[0]["entity"] == "Scam Co"
    assert await tf.listed("phone", "+61 3 9000 1234")
    assert await tf.listed("email", "someone@else-example.com") == []


# ── Refreshing ─────────────────────────────────────────────────────────────────

async def test_a_refresh_stores_delists_and_refuses_a_shrunken_download(scratch, monkeypatch):
    feed = tf.BY_ID["openphish"]
    body = {"lines": "\n".join(f"https://p{i}.example/x" for i in range(200))}
    async def download(_feed):
        return [body["lines"].encode()]
    monkeypatch.setattr(tf, "_download", download)

    first = await tf.refresh(feed, "manual")
    assert first["status"] == "success" and first["added"] == 200
    doc = await scratch.threat_indicators.find_one({"key": "p0.example/x"})
    assert doc["source"] == "openphish" and doc["publisher"] == "OpenPhish" and doc["first_seen_at"] and tf._aware(doc["evidence_expiry_deadline"]) > now_utc()

    body["lines"] = "\n".join(f"https://p{i}.example/x" for i in range(1, 190))
    second = await tf.refresh(feed, "manual")
    assert second["status"] == "success" and second["added"] == 0 and second["removed"] == 11
    gone = await scratch.threat_indicators.find_one({"key": "p0.example/x"})
    assert gone["status"] == "expired" and gone["withdrawal_reason"] == "source_delisted"

    body["lines"] = "https://p1.example/x\n"
    third = await tf.refresh(feed, "manual")
    assert third["status"] == "failed"
    state = await scratch.learning_feed_state.find_one({"feed_id": "openphish"})
    assert state["status"] == "unavailable" and state["error_detail"] == "feed shrank unexpectedly" and state["item_count"] == 189
    assert await scratch.threat_indicators.count_documents({"source": "openphish", "status": "active"}) == 189, "the existing list is kept"
    runs = await scratch.learning_feed_runs.count_documents({"feed_id": "openphish", "pipeline": "threat_feeds"})
    assert runs == 3


def test_gzip_bombs_are_refused():
    from services.outbound import OutboundBlocked, gunzip
    packed = gzip.compress(b"0" * 10_000)
    assert gunzip(packed, 20_000) == b"0" * 10_000
    with pytest.raises(OutboundBlocked):
        gunzip(packed, 5_000)


# ── Admin ──────────────────────────────────────────────────────────────────────

@pytest.fixture()
def admin_cookie():
    token = f"test-{uuid.uuid4().hex}"
    DB.admin_sessions.insert_one({"token": token, "email": "threat-feeds-test@apollo.test", "expires_at": now_utc() + timedelta(minutes=5)})
    yield {"apollo_admin": token}
    DB.admin_sessions.delete_one({"token": token})


def test_admins_see_feed_health_and_can_refresh_now(admin_cookie):
    assert httpx.post(f"{BASE}/admin/threat-feeds/refresh", timeout=20, follow_redirects=False).headers["location"] == "/api/admin/login"
    page = httpx.get(f"{BASE}/admin/knowledge", cookies=admin_cookie, timeout=30).text
    assert 'data-testid="threat-feeds-table"' in page and 'data-testid="threat-feeds-refresh-all"' in page
    for feed in tf.FEEDS:
        assert f"threat-feed-row-{feed.feed_id}" in page and f"threat-feed-refresh-{feed.feed_id}" in page
    unknown = httpx.post(f"{BASE}/admin/threat-feeds/refresh", data={"feed_id": "nope"}, cookies=admin_cookie, timeout=20, follow_redirects=False)
    assert unknown.status_code == 303 and "feeds=" not in unknown.headers["location"], "an unknown feed starts nothing"
    r = httpx.post(f"{BASE}/admin/threat-feeds/refresh", data={"feed_id": "openphish"}, cookies=admin_cookie, timeout=20, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].split("#")[0] in ("/api/admin/knowledge?feeds=started", "/api/admin/knowledge?feeds=busy")
    if r.headers["location"].startswith("/api/admin/knowledge?feeds=started"):
        assert DB.admin_audit.find_one({"email": "threat-feeds-test@apollo.test", "action": "threat_feeds_refresh", "detail": "manual refresh: openphish"})
    notice = httpx.get(f"{BASE.removesuffix('/api')}{r.headers['location']}", cookies=admin_cookie, timeout=30).text
    assert "threat-feeds-started" in notice or "threat-feeds-busy" in notice
    report = httpx.get(f"{BASE}/feeds/health", timeout=20)
    if report.status_code == 200:
        ids = {row["feedId"] for row in report.json()["feeds"]}
        assert {feed.feed_id for feed in tf.FEEDS} <= ids, "the free feeds are on Feed Health"
