"""AI Map and ApolloSG Settings: each feature that calls the AI provider, its calls and cost this week, and the one
place the AI investigation provider and model are chosen."""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from core.db import now_utc
from routers import admin_portal

BASE = os.environ.get("APOLLO_API", "http://localhost:8001/api")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]


@pytest.fixture()
def admin_cookie():
    token = f"test-{uuid.uuid4().hex}"
    DB.admin_sessions.insert_one({"token": token, "email": "gemini-map-test@apollo.test", "expires_at": now_utc() + timedelta(minutes=5)})
    yield {"apollo_admin": token}
    DB.admin_sessions.delete_one({"token": token})


def test_the_week_starts_monday_midnight_in_the_admins_zone():
    start = admin_portal._week_start(600)
    local = start.astimezone(timezone(timedelta(minutes=600)))
    assert (local.weekday(), local.hour, local.minute) == (0, 0, 0)
    assert timedelta(0) <= now_utc() - start < timedelta(days=7)


def test_each_record_is_counted_under_the_feature_that_made_it(monkeypatch):
    """Against a throwaway database, so the preview's own usage is untouched."""
    async def run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        scratch = client[f"gemini_map_{uuid.uuid4().hex[:8]}"]
        monkeypatch.setattr(admin_portal, "db", scratch)
        now = now_utc()
        rec = lambda purpose, cid, cost=0.01, ok=True, ts=now: {"purpose": purpose, "correlation_id": cid, "estimated_cost_usd": cost,  # noqa: E731
                                                               "success": ok, "search_queries": 1, "timestamp": ts}
        try:
            await scratch.gemini_usage.insert_many([
                rec("investigation", "case-1"), rec("investigation", "case-1", ok=False), rec("tc_flyby_search", "case-1"),
                rec("ordinary_chat", "chat-abc"), rec("ordinary_chat", "protection-x"), rec("investigation", "page-crawl"),
                rec("investigation", "case-2", ts=now - timedelta(days=9)),
            ])
            usage = await admin_portal.gemini_usage_by_feature(now - timedelta(days=1))
            assert usage["magnum_di"]["calls"] == 2 and usage["magnum_di"]["failed"] == 1
            assert usage["tc_flyby"]["calls"] == 1 and usage["ask_higgins"]["calls"] == 1
            assert usage["protection"]["calls"] == 1 and usage["page_crawl"]["calls"] == 1
            assert round(sum(v["cost"] for v in usage.values()), 4) == 0.06
        finally:
            await client.drop_database(scratch.name)
            client.close()

    asyncio.run(run())


def test_the_page_lists_every_feature_with_this_weeks_numbers(admin_cookie):
    r = httpx.get(f"{BASE}/admin/gemini-map?tz=600", cookies=admin_cookie, timeout=20)
    assert r.status_code == 200
    page = r.text
    assert 'href="/api/admin/gemini-map"' in page and "since Monday 00:00 UTC+10:00" in page
    for key in ("magnum_di", "tc_flyby"):
        assert f"data-testid='gemini-feature-{key}'" in page
        assert f"data-testid='gemini-trend-{key}'" in page
    assert "data-testid='gemini-feature-ask_higgins'" not in page, "Ask Higgins makes no AI call"
    assert "data-testid='gemini-trend-other'" in page and "data-testid='gemini-trend-total'" in page
    assert page.count("Week of<br>") == 3 and "This week so far<br>" in page
    for gone in ("page_extract", "page_crawl()", "protection_explanations.py"):
        assert gone not in page
    assert "AI calls this week" in page and "Estimated cost this week" in page
    # The map shows the selection, read-only, and sends the admin to the one place it is changed.
    assert 'data-testid="gemini-map-selection"' in page and "/api/admin/apollosg-settings" in page
    assert "<select" not in page and "gemini-map/model" not in page


def test_each_weeks_cost_is_compared_with_the_week_before():
    assert admin_portal._change_html(2.0, 1.0) == " <span class='trend up'>▲ 100%</span>"
    assert admin_portal._change_html(0.5, 1.0) == " <span class='trend down'>▼ 50%</span>"
    assert admin_portal._change_html(1.0, 0.0) == " <span class='trend up'>new</span>"
    assert admin_portal._change_html(0.0, 0.0) == ""
    assert admin_portal._change_html(1.001, 1.0) == " <span class='trend'>±0%</span>"


def test_the_four_weeks_are_counted_separately(monkeypatch):
    async def run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        scratch = client[f"gemini_trend_{uuid.uuid4().hex[:8]}"]
        monkeypatch.setattr(admin_portal, "db", scratch)
        start = admin_portal._week_start(0)
        try:
            await scratch.gemini_usage.insert_many([
                {"purpose": "tc_flyby_search", "correlation_id": "case-1", "estimated_cost_usd": 0.02, "success": True, "timestamp": start - timedelta(days=3)},
                {"purpose": "tc_flyby_search", "correlation_id": "case-2", "estimated_cost_usd": 0.01, "success": True, "timestamp": start + timedelta(minutes=1)},
            ])
            last_week = await admin_portal.gemini_usage_by_feature(start - timedelta(weeks=1), start)
            this_week = await admin_portal.gemini_usage_by_feature(start)
            assert last_week["tc_flyby"]["calls"] == 1 and round(last_week["tc_flyby"]["cost"], 2) == 0.02
            assert this_week["tc_flyby"]["calls"] == 1 and round(this_week["tc_flyby"]["cost"], 2) == 0.01
        finally:
            await client.drop_database(scratch.name)
            client.close()

    asyncio.run(run())


def test_signed_out_visitors_are_sent_to_login():
    r = httpx.get(f"{BASE}/admin/gemini-map", timeout=20, follow_redirects=False)
    assert r.status_code == 303


# ── ApolloSG Settings → AI Provider & Model ───────────────────────────────────
from services.higgins import ai_settings  # noqa: E402


def test_only_approved_models_that_can_investigate_are_available():
    opts = {p["id"]: p for p in ai_settings.options()}
    assert [opts[k]["label"] for k in ("gemini", "anthropic", "openai")] == ["Google Gemini", "Anthropic Claude", "OpenAI"]
    gemini = {m["id"]: m for m in opts["gemini"]["models"]}
    assert not gemini["gemini-3.1-flash-lite"]["reasons"]
    assert "can't search the web with sources" in gemini["gemini-2.5-flash-lite"]["reasons"], "no web search, so it can't investigate"
    assert "can't read images sent as evidence" in gemini["gemini-2.5-flash-lite"]["reasons"]
    available = [m["id"] for m in opts["gemini"]["models"] if not m["reasons"]]
    assert all(ai_settings.capabilities(m) >= {"json", "vision", "search"} for m in available)
    priced = [m for m in available if m in admin_portal.MODEL_PRICING]
    assert [admin_portal.MODEL_PRICING[m]["input"] for m in priced] == sorted(admin_portal.MODEL_PRICING[m]["input"] for m in priced)
    # Claude and OpenAI are connected; each of their approved models can investigate once its provider's key is set.
    for pid in ("anthropic", "openai"):
        assert opts[pid]["connected"] and opts[pid]["models"]
        for m in opts[pid]["models"]:
            assert ai_settings.capabilities(m["id"]) >= {"json", "vision", "search"}
            assert m["reasons"] == ([] if ai_settings.key_configured(pid) else [f"no {ai_settings.label(pid)} API key is set on the server"])
    assert ai_settings.unavailable("anthropic", "claude-anything") == ["isn't an ApolloSG-approved model"]


def test_one_selection_for_magnum_di_and_tc_flyby_saved_with_who_and_when(monkeypatch):
    async def run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        scratch = client[f"ai_settings_{uuid.uuid4().hex[:8]}"]
        monkeypatch.setattr(ai_settings, "db", scratch)
        try:
            first = await ai_settings.selection()
            assert (first["provider"], first["model"], first["default"]) == ("gemini", "gemini-3.1-flash-lite", True)
            before = await ai_settings.choose("gemini", "gemini-2.5-flash", "a@apollo.test")
            assert before["model"] == "gemini-3.1-flash-lite"
            assert await ai_settings.investigation_model() == "gemini-2.5-flash"
            saved = await ai_settings.selection()
            assert saved["changed_by"] == "a@apollo.test" and saved["changed_at"] and saved["default"] is False
            for chosen_provider, model in (("gemini", "gemini-2.5-flash-lite"), ("anthropic", "gemini-2.5-flash"), ("openai", "gpt-4"), ("gemini", "")):
                with pytest.raises(ValueError):
                    await ai_settings.choose(chosen_provider, model, "a@apollo.test")
            assert await ai_settings.investigation_model() == "gemini-2.5-flash", "a refused change changes nothing"
            # A stored model that can no longer be used is still the one called: the call fails and says so, never switched.
            await scratch[ai_settings.COLLECTION].update_one({"setting": ai_settings.SETTING}, {"$set": {"model": "retired-model"}})
            assert await ai_settings.investigation_model() == "retired-model"
        finally:
            await client.drop_database(scratch.name)
            client.close()

    asyncio.run(run())


def test_the_old_gemini_map_choice_for_magnum_di_stays_in_force_until_changed(monkeypatch):
    async def run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        scratch = client[f"ai_settings_{uuid.uuid4().hex[:8]}"]
        monkeypatch.setattr(ai_settings, "db", scratch)
        try:
            await scratch[ai_settings.LEGACY_COLLECTION].insert_many([
                {"feature": "magnum_di", "model": "gemini-2.5-flash", "changed_by": "old@apollo.test", "changed_at": now_utc()},
                {"feature": "ask_higgins", "model": "gemini-2.5-flash-lite"}])
            sel = await ai_settings.selection()
            assert (sel["provider"], sel["model"], sel["changed_by"], sel["default"]) == ("gemini", "gemini-2.5-flash", "old@apollo.test", False)
        finally:
            await client.drop_database(scratch.name)
            client.close()

    asyncio.run(run())


@pytest.fixture()
def restore_selection():
    saved = list(DB[ai_settings.COLLECTION].find({}, {"_id": 0}))
    yield
    DB[ai_settings.COLLECTION].delete_many({})
    if saved:
        DB[ai_settings.COLLECTION].insert_many(saved)


def test_the_settings_page_saves_the_selection_and_audits_it(admin_cookie, restore_selection):
    page = httpx.get(f"{BASE}/admin/apollosg-settings", cookies=admin_cookie, timeout=20).text
    for testid in ("ai-current-value", "ai-provider-select", "ai-model-select", "ai-model-save", "ai-model-warning"):
        assert f'data-testid="{testid}"' in page
    assert "affects future investigations only" in page and "ApolloSG Settings" in page
    assert "<option value='anthropic'>Anthropic Claude</option>" in page and "<option value='openai'>OpenAI</option>" in page
    assert "AIza" not in page and "GEMINI_API_KEY" not in page, "keys are never shown"
    current = DB[ai_settings.COLLECTION].find_one({"setting": ai_settings.SETTING}) or {}
    pick = "gemini-2.5-flash" if current.get("model") != "gemini-2.5-flash" else "gemini-3.1-flash-lite"
    untested = httpx.post(f"{BASE}/admin/apollosg-settings/ai-model", data={"provider": "gemini", "model": pick},
                          cookies=admin_cookie, timeout=20, follow_redirects=False)
    assert untested.status_code == 400 and f"test {pick} first" in untested.text, "a new model is saved only after it passes the test"
    tested = httpx.post(f"{BASE}/admin/apollosg-settings/ai-model/test", data={"provider": "gemini", "model": pick},
                        cookies=admin_cookie, timeout=120).json()
    assert tested["ok"] is True and tested["simulated"] is True, tested  # the preview simulator stands in for the provider
    assert [c["label"] for c in tested["checks"]] == ["Ready to use", "Answered", "Accepted web search", "Fixed answer shape"]
    r = httpx.post(f"{BASE}/admin/apollosg-settings/ai-model", data={"provider": "gemini", "model": pick},
                   cookies=admin_cookie, timeout=20, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/api/admin/apollosg-settings?saved=1"
    page = httpx.get(f"{BASE}/admin/apollosg-settings?saved=1", cookies=admin_cookie, timeout=20).text
    assert "data-testid='ai-model-saved'" in page and f"Google Gemini · {pick}" in page
    assert "Changed by gemini-map-test@apollo.test" in page and f"<option value='{pick}' selected>" in page
    audit = DB.admin_audit.find_one({"email": "gemini-map-test@apollo.test", "action": "ai_model_change"}, sort=[("timestamp", -1)])
    assert audit and audit["detail"].endswith(f"→ Google Gemini · {pick}")
    DB.admin_audit.delete_many({"email": "gemini-map-test@apollo.test"})
    refused = httpx.post(f"{BASE}/admin/apollosg-settings/ai-model", data={"provider": "gemini", "model": "gemini-2.5-flash-lite"},
                         cookies=admin_cookie, timeout=20, follow_redirects=False)
    assert refused.status_code == 400 and "Nothing was changed" in refused.text
    claude = httpx.post(f"{BASE}/admin/apollosg-settings/ai-model", data={"provider": "anthropic", "model": "claude-sonnet"},
                        cookies=admin_cookie, timeout=20, follow_redirects=False)
    assert claude.status_code == 400
    assert (DB[ai_settings.COLLECTION].find_one({"setting": ai_settings.SETTING}) or {}).get("model") == pick


def test_testing_a_model_without_its_key_sends_nothing_and_says_so(admin_cookie, restore_selection):
    if ai_settings.key_configured("anthropic"):
        pytest.skip("an Anthropic key is set on this server")
    page = httpx.get(f"{BASE}/admin/apollosg-settings", cookies=admin_cookie, timeout=20).text
    for testid in ("ai-model-test", "ai-model-test-result", "ai-model-save-hint"):
        assert f'data-testid="{testid}"' in page
    assert "claude-sonnet-5-5" in page, "every approved model is listed, with why it can't be used"
    before = DB.gemini_usage.count_documents({})
    r = httpx.post(f"{BASE}/admin/apollosg-settings/ai-model/test", data={"provider": "anthropic", "model": "claude-sonnet-5-5"},
                   cookies=admin_cookie, timeout=20).json()
    assert r["ok"] is False and r["message"].startswith("No Anthropic Claude API key is set on the server") and "Nothing was sent" in r["message"]
    assert r["checks"] == [{"label": "Ready to use", "ok": False, "detail": "no Anthropic Claude API key is set on the server"}]
    assert DB.gemini_usage.count_documents({}) == before, "no AI call was made"
    saved = httpx.post(f"{BASE}/admin/apollosg-settings/ai-model", data={"provider": "anthropic", "model": "claude-sonnet-5-5"},
                       cookies=admin_cookie, timeout=20, follow_redirects=False)
    assert saved.status_code == 400 and "no Anthropic Claude API key is set on the server" in saved.text
    assert httpx.post(f"{BASE}/admin/apollosg-settings/ai-model/test", data={"provider": "gemini", "model": "gemini-2.5-flash"},
                      timeout=20).status_code == 401, "signed-out visitors can't run a test"


def test_signed_out_visitors_cannot_see_or_change_the_selection():
    assert httpx.get(f"{BASE}/admin/apollosg-settings", timeout=20, follow_redirects=False).status_code == 303
    r = httpx.post(f"{BASE}/admin/apollosg-settings/ai-model", data={"provider": "gemini", "model": "gemini-2.5-flash"}, timeout=20, follow_redirects=False)
    assert r.status_code == 303 and "login" in r.headers["location"]
    assert httpx.post(f"{BASE}/admin/gemini-map/model", data={"feature": "magnum_di", "model": "gemini-2.5-flash"},
                      timeout=20, follow_redirects=False).status_code in (404, 405), "the Gemini Map no longer changes models"


def test_admin_pages_show_the_one_selection(admin_cookie):
    system = httpx.get(f"{BASE}/admin/system", cookies=admin_cookie, timeout=30).text
    assert "AI investigation provider &amp; model (Magnum DI and TC Hawkeye)" in system and "Ask Higgins model" not in system
    assert "Vision Model" not in system
    triage = httpx.get(f"{BASE}/admin/triage", cookies=admin_cookie, timeout=30).text
    assert "Triage Model" not in triage and "Input Price" not in triage
    releases = httpx.get(f"{BASE}/admin/releases", cookies=admin_cookie, timeout=30).text
    assert "AI investigation provider &amp; model" in releases
    nav = [label for label, *_ in admin_portal.NAV]
    assert "ApolloSG Settings" in nav and "AI Map" in nav and "Gemini Map" not in nav
