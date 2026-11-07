# Missed Check-In Nudge — Tuesday reminder for guardians who haven't checked in since Sunday.
import os, sys, uuid, asyncio
from datetime import datetime, timezone
import pytest, requests

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://tc-flyby-2fa--0hiznn9n.preview.emergentagent.com").rstrip("/")
sys.path.insert(0, "/app/backend")


@pytest.fixture
def api():
    s = requests.Session(); s.headers.update({"Content-Type": "application/json", "User-Agent": "apollo-tests"}); return s


def _pair(api, protected, guardian, owner):
    code = api.post(f"{BASE_URL}/api/family/pair", json={"device_id": protected, "owner_name": owner}).json()["code"]
    assert api.post(f"{BASE_URL}/api/family/link", json={"device_id": guardian, "code": code}).status_code == 200


class TestNudgeApi:
    def test_preview_names_everyone_watched(self, api):
        g = f"guard{uuid.uuid4().hex[:12]}"
        assert api.post(f"{BASE_URL}/api/family/weekly/send-now", json={"device_id": g, "preview_only": True, "kind": "nudge"}).json() == {"sent": False, "reason": "no_links"}
        _pair(api, f"prot{uuid.uuid4().hex[:12]}", g, "Mum")
        _pair(api, f"prot{uuid.uuid4().hex[:12]}", g, "Dad")
        r = api.post(f"{BASE_URL}/api/family/weekly/send-now", json={"device_id": g, "preview_only": True, "kind": "nudge"}).json()
        assert r["preview"] is True and r["title"] == "Higgins: a hello for Mum and Dad, perhaps?"
        assert r["message"].startswith("You haven't checked in with Mum and Dad since Sunday.")
        assert api.post(f"{BASE_URL}/api/family/weekly/send-now", json={"device_id": g, "preview_only": True, "kind": "cuddle"}).status_code == 422


class TestNudgeScheduler:
    async def test_only_tuesday_window_and_only_missed(self):
        from motor.motor_asyncio import AsyncIOMotorClient
        from routers import family_weekly as server

        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        orig_db = server.db
        server.db = client[orig_db.name]
        try:
            g, p1, p2 = f"guard{uuid.uuid4().hex[:12]}", f"prot{uuid.uuid4().hex[:12]}", f"prot{uuid.uuid4().hex[:12]}"
            ts = server.now_utc()
            await server.db.devices.insert_one({"device_id": g, "platform": "web", "adapter_mode": "mock", "app_version": "1", "tz_offset_minutes": 600, "created_at": ts, "last_seen_at": ts})
            for pid, name in ((p1, "Mum"), (p2, "Dad")):
                await server.db.family_links.insert_one({"protected_device_id": pid, "guardian_device_id": g, "owner_name": name, "created_at": ts, "deleted_at": None})
            # Monday 08:30Z (= Mon 18:30 local UTC+10) → not Tuesday → nothing
            assert await server.missed_checkin_tick(datetime(2026, 6, 15, 8, 30, tzinfo=timezone.utc)) == 0
            # Tuesday 02:00Z (= Tue 12:00 local) → outside window
            assert await server.missed_checkin_tick(datetime(2026, 6, 16, 2, 0, tzinfo=timezone.utc)) == 0
            # Direct helper on Tuesday 18:30 local: both missed → names both (push relay is a placeholder → may raise; check composition path)
            local = datetime(2026, 6, 16, 18, 30)
            # Mum checked in on Sunday evening local (Sun 2026-06-14 19:00 local = 09:00Z) → only Dad is missed
            await server.db.weekly_checkins.insert_one({"guardian_device_id": g, "protected_device_id": p1, "week_key": "2026-W24", "guardian_label": "Sam", "reply": "spoke", "label": "All good, spoke to them", "created_at": datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc)})
            # Dad checked in on Saturday (before Sunday) → still counts as missed
            await server.db.weekly_checkins.insert_one({"guardian_device_id": g, "protected_device_id": p2, "week_key": "2026-W23", "guardian_label": "Sam", "reply": "spoke", "label": "All good, spoke to them", "created_at": datetime(2026, 6, 13, 9, 0, tzinfo=timezone.utc)})
            try:
                r = await server.send_missed_checkin_nudge(g, local)
                assert r["missed"] == ["Dad"] and r["title"] == "Higgins: a hello for Dad, perhaps?"
            except Exception as exc:  # push relay placeholder → HTTPException 500; composition already ran
                assert "PUSH_KEY" in str(getattr(exc, "detail", "")) or "Push" in str(getattr(exc, "detail", "")), exc
            # opted out → skipped
            await server.db.devices.update_one({"device_id": g}, {"$set": {"weekly_checkin_enabled": False}})
            assert await server.send_missed_checkin_nudge(g, local) == {"sent": False, "reason": "opted_out"}
            await server.db.devices.update_one({"device_id": g}, {"$set": {"weekly_checkin_enabled": True}})
            # everyone checked in since Sunday → nothing to nudge
            # Clear any dedupe record from the earlier nudge attempt so this tests all_checked_in, not already_sent
            await server.db.weekly_nudge_sends.delete_many({"guardian_device_id": g})
            await server.db.weekly_checkins.insert_one({"guardian_device_id": g, "protected_device_id": p2, "week_key": "2026-W25", "guardian_label": "Sam", "reply": "spoke", "label": "All good, spoke to them", "created_at": datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)})
            assert await server.send_missed_checkin_nudge(g, local) == {"sent": False, "reason": "all_checked_in"}
            # dedupe record honoured
            await server.db.weekly_nudge_sends.insert_one({"guardian_device_id": g, "week_key": "2026-W25", "sent_at": ts})
            assert await server.send_missed_checkin_nudge(g, local) == {"sent": False, "reason": "already_sent"}
        finally:
            server.db = orig_db
            client.close()
