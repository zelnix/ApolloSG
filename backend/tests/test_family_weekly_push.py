# Sunday check-in push — scheduling window, dedupe, opt-out, preview text, tz on register.
import os, uuid
from datetime import datetime, timedelta, timezone
import pytest, requests

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://case-source-preview--3ijise2t.preview.emergentagent.com").rstrip("/")


@pytest.fixture
def api():
    s = requests.Session(); s.headers.update({"Content-Type": "application/json", "User-Agent": "apollo-tests"}); return s


def _pair(api, protected, guardian, owner="Mum"):
    code = api.post(f"{BASE_URL}/api/family/pair", json={"device_id": protected, "owner_name": owner}).json()["code"]
    assert api.post(f"{BASE_URL}/api/family/link", json={"device_id": guardian, "code": code}).status_code == 200


class TestWeeklyCheckinApi:
    def test_register_stores_tz_offset(self, api):
        d = f"dev{uuid.uuid4().hex[:12]}"
        r = api.post(f"{BASE_URL}/api/devices/register", json={"device_id": d, "platform": "web", "adapter_mode": "mock", "app_version": "1.0.0", "tz_offset_minutes": 600})
        assert r.status_code == 201
        assert api.post(f"{BASE_URL}/api/devices/register", json={"device_id": d, "platform": "web", "adapter_mode": "mock", "app_version": "1.0.0", "tz_offset_minutes": 900}).status_code == 422  # out of range

    def test_pref_default_on_and_toggle(self, api):
        g = f"guard{uuid.uuid4().hex[:12]}"
        p = api.get(f"{BASE_URL}/api/family/weekly/notify", params={"device_id": g}).json()
        assert p["enabled"] is True and p["last_sent_at"] is None and "Sunday" in p["window"]
        assert api.put(f"{BASE_URL}/api/family/weekly/notify", json={"device_id": g, "enabled": False}).json() == {"enabled": False}
        assert api.get(f"{BASE_URL}/api/family/weekly/notify", params={"device_id": g}).json()["enabled"] is False

    def test_preview_text_matches_screen_wording(self, api):
        protected, guardian = f"prot{uuid.uuid4().hex[:12]}", f"guard{uuid.uuid4().hex[:12]}"
        api.post(f"{BASE_URL}/api/devices/register", json={"device_id": protected, "platform": "web", "adapter_mode": "mock"})
        assert api.post(f"{BASE_URL}/api/family/weekly/send-now", json={"device_id": guardian, "preview_only": True}).json() == {"sent": False, "reason": "no_links"}
        _pair(api, protected, guardian)
        r = api.post(f"{BASE_URL}/api/family/weekly/send-now", json={"device_id": guardian, "preview_only": True}).json()
        assert r["preview"] is True and r["title"] == "Higgins: your Sunday check-in"
        assert r["message"] == "A quiet week for Mum. Nothing came up that needed a look."
        # an open alert changes the wording
        ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        api.post(f"{BASE_URL}/api/patrol/events", json={"event_id": uuid.uuid4().hex[:16], "device_id": protected, "category": "link", "state": "barking", "status": "active", "headline": "x", "what_happened": "x", "why": [], "what_to_do": "x", "adapter_label": "mock", "occurred_at": ts})
        r = api.post(f"{BASE_URL}/api/family/weekly/send-now", json={"device_id": guardian, "preview_only": True}).json()
        assert r["message"] == "Mum has 1 alert still open this week. I would suggest a call to walk through it."

    def test_send_now_without_relay_is_friendly_error(self, api):
        protected, guardian = f"prot{uuid.uuid4().hex[:12]}", f"guard{uuid.uuid4().hex[:12]}"
        _pair(api, protected, guardian)
        r = api.post(f"{BASE_URL}/api/family/weekly/send-now", json={"device_id": guardian})
        # Without the owner's Expo push credentials the adapter answers a typed 503 with a readable detail, never a stack trace.
        assert r.status_code in (200, 503), r.text
        if r.status_code != 200:
            assert isinstance(r.json()["detail"], str)


class TestWeeklyCheckinScheduler:
    """Exercise the tick in-process so we can control the clock. Push relay is a placeholder → send failures are swallowed
    per guardian, so we assert on the window logic and the dedupe record via the helper's return values."""

    @pytest.fixture(autouse=True)
    def _env(self):
        import sys; sys.path.insert(0, "/app/backend")

    def test_window_and_week_key(self):
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        from routers import family_weekly as server
        # Sunday 2026-06-14 18:30 local (UTC+10 → 08:30Z) is inside the window; Saturday is not; Sunday 12:00 is not.
        assert server._week_key(datetime(2026, 6, 14, 18, 30)) == "2026-W24"
        assert 17 in server.WEEKLY_WINDOW and 20 in server.WEEKLY_WINDOW and 21 not in server.WEEKLY_WINDOW and 16 not in server.WEEKLY_WINDOW

        async def run():
            # A fresh Motor client bound to THIS event loop, swapped in for the module's shared
            # singleton for the duration of this call: asyncio.run() below creates/closes its own
            # loop, and re-using a client whose internals were created under a PREVIOUS (now-closed)
            # loop — e.g. by test_family_nudge.py's identical pattern running earlier in the same
            # worker — raises "Event loop is closed". Restored/closed in finally so nothing leaks.
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            orig_db = server.db
            server.db = client[orig_db.name]
            try:
                g = f"guard{uuid.uuid4().hex[:12]}"; p = f"prot{uuid.uuid4().hex[:12]}"
                await server.db.devices.insert_one({"device_id": g, "platform": "web", "adapter_mode": "mock", "app_version": "1", "tz_offset_minutes": 600, "created_at": server.now_utc(), "last_seen_at": server.now_utc()})
                await server.db.devices.insert_one({"device_id": p, "platform": "web", "adapter_mode": "mock", "app_version": "1", "created_at": server.now_utc(), "last_seen_at": server.now_utc()})
                await server.db.family_links.insert_one({"protected_device_id": p, "guardian_device_id": g, "owner_name": "Mum", "created_at": server.now_utc(), "deleted_at": None})
                # Saturday 08:30Z (= Sat 18:30 local) → nothing
                assert await server.weekly_checkin_tick(datetime(2026, 6, 13, 8, 30, tzinfo=timezone.utc)) == 0
                # Sunday 02:00Z (= Sun 12:00 local) → outside window
                assert await server.weekly_checkin_tick(datetime(2026, 6, 14, 2, 0, tzinfo=timezone.utc)) == 0
                # opted out → skipped even inside the window
                await server.db.devices.update_one({"device_id": g}, {"$set": {"weekly_checkin_enabled": False}})
                r = await server.send_weekly_checkin(g, "2026-W24")
                assert r == {"sent": False, "reason": "opted_out"}
                await server.db.devices.update_one({"device_id": g}, {"$set": {"weekly_checkin_enabled": True}})
                # dedupe: pretend this week was already sent
                await server.db.weekly_checkin_sends.insert_one({"guardian_device_id": g, "week_key": "2026-W24", "sent_at": server.now_utc()})
                assert await server.send_weekly_checkin(g, "2026-W24") == {"sent": False, "reason": "already_sent"}
                # sentence helper
                w = (await server._weekly_rollup(g))[0]
                assert server.weekly_sentence(w) == "A quiet week for Mum. Nothing came up that needed a look."
                w2 = {**w, "total": 3, "alerts": 2, "open_alerts": 0, "handled_alerts": 2}
                assert server.weekly_sentence(w2) == "Mum had 2 alerts this week and handled them all. Quite so."
                w3 = {**w, "total": 0, "last_seen_at": None}
                assert server.weekly_sentence(w3).startswith("ApolloSG hasn't heard from Mum's phone")
            finally:
                server.db = orig_db
                client.close()
        asyncio.run(run())
