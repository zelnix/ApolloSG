"""Family Sharing: pairing with a 6-digit code, linking, shared events."""
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

DEVICE_A = f"dev-A-{uuid.uuid4().hex[:8]}"
DEVICE_B = f"dev-B-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    yield sess
    # cleanup
    try:
        import asyncio
        async def _clean():
            c = AsyncIOMotorClient(MONGO_URL)
            db = c[DB_NAME]
            await db.pair_codes.delete_many({"protected_device_id": {"$in": [DEVICE_A, DEVICE_B]}})
            await db.family_links.delete_many({"protected_device_id": {"$in": [DEVICE_A, DEVICE_B]}})
            await db.shared_events.delete_many({"guardian_device_id": {"$in": [DEVICE_A, DEVICE_B]}})
            await db.patrol_events.delete_many({"device_id": {"$in": [DEVICE_A, DEVICE_B]}})
            c.close()
        asyncio.run(_clean())
    except Exception as e:
        print(f"cleanup err: {e}")


# --- Pairing / linking ---
class TestPairing:
    code = None

    def test_create_pair(self, s):
        r = s.post(f"{API}/family/pair", json={"device_id": DEVICE_A, "owner_name": "Alex"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"].isdigit() and len(body["code"]) == 6
        assert body["expires_in_minutes"] == 15
        expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        assert 14 * 60 < (expires - datetime.now(timezone.utc)).total_seconds() <= 15 * 60
        TestPairing.code = body["code"]

    def test_link_device(self, s):
        r = s.post(f"{API}/family/link", json={"device_id": DEVICE_B, "code": TestPairing.code})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["linked"] is True
        assert body["owner_name"] == "Alex"

    def test_reuse_code_404(self, s):
        r = s.post(f"{API}/family/link", json={"device_id": DEVICE_B, "code": TestPairing.code})
        assert r.status_code == 404, r.text

    def test_link_own_device_400(self, s):
        r = s.post(f"{API}/family/pair", json={"device_id": DEVICE_A, "owner_name": "Alex"})
        c2 = r.json()["code"]
        r2 = s.post(f"{API}/family/link", json={"device_id": DEVICE_A, "code": c2})
        assert r2.status_code == 400, r2.text

    def test_links_i_watch(self, s):
        r = s.get(f"{API}/family/links", params={"device_id": DEVICE_B})
        assert r.status_code == 200
        body = r.json()
        assert any(l.get("owner_name") == "Alex" for l in body["i_watch"])

    def test_links_watching_me(self, s):
        r = s.get(f"{API}/family/links", params={"device_id": DEVICE_A})
        assert r.status_code == 200
        assert r.json()["watching_me"] >= 1


# --- Shared events (patrol fanout) ---
class TestSharedEvents:
    @pytest.fixture(autouse=True)
    def _paired(self, s):
        # Self-sufficient under xdist --dist loadscope (classes of one module may land on different workers):
        # ensure A → B pairing exists before relying on the fan-out. Idempotent (link upsert).
        links = s.get(f"{API}/family/links", params={"device_id": DEVICE_B}).json()
        if not any(l["protected_device_id"] == DEVICE_A for l in links.get("i_watch", [])):
            code = s.post(f"{API}/family/pair", json={"device_id": DEVICE_A, "owner_name": "Alex"}).json()["code"]
            assert s.post(f"{API}/family/link", json={"device_id": DEVICE_B, "code": code}).status_code == 200
    def test_barking_event_shared(self, s):
        event_id = f"evt-{uuid.uuid4().hex[:12]}"
        payload = {
            "event_id": event_id, "device_id": DEVICE_A, "category": "known_threat",
            "state": "barking", "status": "active",
            "headline": "Threat detected", "what_happened": "A link was flagged.",
            "why": ["blocklisted"], "what_to_do": "Ignore.",
            "indicator_host": "phish.example", "adapter_label": "MOCK",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        r = s.post(f"{API}/patrol/events", json=payload)
        assert r.status_code == 200, r.text
        # Wait for async fanout
        time.sleep(2.5)
        r2 = s.get(f"{API}/family/shared-events", params={"device_id": DEVICE_B})
        assert r2.status_code == 200
        events = r2.json()
        match = [e for e in events if e["event_id"] == event_id]
        assert len(match) == 1, f"expected shared event, got {events}"
        assert match[0]["headline"] == "Apollo checked a known threat and found a problem that needs your attention"
        assert "Threat detected" not in match[0]["headline"]
        assert match[0]["from_label"] == "Alex"

    def test_resting_event_not_shared(self, s):
        event_id = f"evt-{uuid.uuid4().hex[:12]}"
        payload = {
            "event_id": event_id, "device_id": DEVICE_A, "category": "known_threat",
            "state": "resting", "status": "resolved",
            "headline": "All clear", "what_happened": "Nothing here.",
            "why": ["ok"], "what_to_do": "Nothing.",
            "indicator_host": "clean.example", "adapter_label": "MOCK",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        r = s.post(f"{API}/patrol/events", json=payload)
        assert r.status_code == 200
        time.sleep(2.0)
        r2 = s.get(f"{API}/family/shared-events", params={"device_id": DEVICE_B})
        events = r2.json()
        assert not any(e["event_id"] == event_id for e in events), "resting event should NOT be shared"
