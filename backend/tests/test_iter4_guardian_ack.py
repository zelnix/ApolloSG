"""Apollo V1 iteration-4 backend tests: Guardian Reply (ack) flow."""
import os
import time
import uuid
from datetime import datetime, timezone

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE_URL = "https://tc-flyby-2fa--0hiznn9n.preview.emergentagent.com"
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")

# 16-char device IDs (min_length=8 respected)
DEV_P = f"dev-P-{uuid.uuid4().hex[:10]}"   # protected
DEV_G = f"dev-G-{uuid.uuid4().hex[:10]}"   # guardian


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    yield sess
    try:
        import asyncio
        async def _clean():
            c = AsyncIOMotorClient(MONGO_URL)
            db = c[DB_NAME]
            await db.pair_codes.delete_many({"protected_device_id": {"$in": [DEV_P, DEV_G]}})
            await db.family_links.delete_many({"$or": [
                {"protected_device_id": {"$in": [DEV_P, DEV_G]}},
                {"guardian_device_id": {"$in": [DEV_P, DEV_G]}},
            ]})
            await db.shared_events.delete_many({"guardian_device_id": {"$in": [DEV_P, DEV_G]}})
            await db.family_acks.delete_many({"$or": [
                {"protected_device_id": {"$in": [DEV_P, DEV_G]}},
                {"guardian_device_id": {"$in": [DEV_P, DEV_G]}},
            ]})
            await db.patrol_events.delete_many({"device_id": {"$in": [DEV_P, DEV_G]}})
            c.close()
        asyncio.run(_clean())
    except Exception as e:
        print(f"cleanup err: {e}")


class TestGuardianReplyFlow:
    """End-to-end: pair → link → patrol event → guardian ack."""

    state = {}

    def test_01_pair(self, s):
        r = s.post(f"{API}/family/pair", json={"device_id": DEV_P, "owner_name": "Nan"})
        assert r.status_code == 200, r.text
        code = r.json()["code"]
        assert len(code) == 6
        TestGuardianReplyFlow.state["code"] = code

    def test_02_link(self, s):
        r = s.post(f"{API}/family/link", json={
            "device_id": DEV_G, "code": TestGuardianReplyFlow.state["code"],
            "guardian_label": "Guardian",
        })
        # guardian_label may not be part of schema; retry without if 422
        if r.status_code == 422:
            r = s.post(f"{API}/family/link", json={
                "device_id": DEV_G, "code": TestGuardianReplyFlow.state["code"],
            })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["linked"] is True
        assert body.get("owner_name") == "Nan"

    def test_03_post_patrol_event(self, s):
        event_id = f"evt-{uuid.uuid4().hex[:12]}"
        TestGuardianReplyFlow.state["event_id"] = event_id
        payload = {
            "event_id": event_id, "device_id": DEV_P, "category": "known_threat",
            "state": "barking", "status": "active",
            "headline": "Dog is barking",
            "what_happened": "A blocklisted host was contacted.",
            "why": ["blocklisted"], "what_to_do": "Investigate.",
            "indicator_host": "bad.example", "adapter_label": "test",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        r = s.post(f"{API}/patrol/events", json=payload)
        assert r.status_code == 200, r.text

    def test_04_fanout_visible_to_guardian(self, s):
        # wait for async fanout
        for _ in range(6):
            time.sleep(1.0)
            r = s.get(f"{API}/family/shared-events", params={"device_id": DEV_G})
            assert r.status_code == 200
            events = r.json()
            if any(e["event_id"] == TestGuardianReplyFlow.state["event_id"] for e in events):
                return
        assert False, f"shared event not visible to guardian after 6s: {events}"

    def test_05_ack_called(self, s):
        eid = TestGuardianReplyFlow.state["event_id"]
        r = s.post(f"{API}/family/shared-events/{eid}/ack", json={
            "device_id": DEV_G, "reply": "called"
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["acknowledged"] is True
        assert body["ack_label"] == "I called them"

    def test_06_shared_events_shows_ack(self, s):
        eid = TestGuardianReplyFlow.state["event_id"]
        r = s.get(f"{API}/family/shared-events", params={"device_id": DEV_G})
        assert r.status_code == 200
        events = r.json()
        match = [e for e in events if e["event_id"] == eid]
        assert len(match) == 1
        assert match[0].get("ack_label") == "I called them"
        assert match[0].get("acknowledged_at"), "acknowledged_at missing"

    def test_07_protected_sees_ack_in_acks(self, s):
        eid = TestGuardianReplyFlow.state["event_id"]
        r = s.get(f"{API}/family/acks", params={"device_id": DEV_P})
        assert r.status_code == 200, r.text
        docs = r.json()
        match = [d for d in docs if d["event_id"] == eid]
        assert len(match) == 1, f"protected should see ack: {docs}"
        assert match[0]["ack_label"] == "I called them"
        assert match[0]["headline"] == "Apollo checked a known threat and found a problem that needs your attention"
        assert "Dog is barking" not in match[0]["headline"]  # raw local narrative never leaves Patrol

    def test_08_ack_wrong_guardian_404(self, s):
        eid = TestGuardianReplyFlow.state["event_id"]
        bogus_dev = f"dev-X-{uuid.uuid4().hex[:10]}"
        r = s.post(f"{API}/family/shared-events/{eid}/ack", json={
            "device_id": bogus_dev, "reply": "called"
        })
        assert r.status_code == 404, r.text

    def test_09_ack_bogus_reply_422(self, s):
        eid = TestGuardianReplyFlow.state["event_id"]
        r = s.post(f"{API}/family/shared-events/{eid}/ack", json={
            "device_id": DEV_G, "reply": "bogus"
        })
        assert r.status_code == 422, r.text

    def test_10_ack_messaged_updates_label(self, s):
        eid = TestGuardianReplyFlow.state["event_id"]
        r = s.post(f"{API}/family/shared-events/{eid}/ack", json={
            "device_id": DEV_G, "reply": "messaged"
        })
        assert r.status_code == 200
        assert r.json()["ack_label"] == "I messaged them"
        # verify shared-events reflects update
        r2 = s.get(f"{API}/family/shared-events", params={"device_id": DEV_G})
        match = [e for e in r2.json() if e["event_id"] == eid]
        assert match[0]["ack_label"] == "I messaged them"
