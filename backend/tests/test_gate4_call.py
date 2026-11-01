# Gate 4 — Phone Call Protection backend test.
# Verifies POST /api/patrol/events accepts category "call" and persists it.
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

def _base_url() -> str:
    base = os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    if not base:
        env_file = Path(__file__).resolve().parents[2] / "frontend" / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                    base = line.split("=", 1)[1].strip()
                    break
                if line.startswith("EXPO_BACKEND_URL="):
                    base = line.split("=", 1)[1].strip()
                    break
    if not base:
        raise RuntimeError("EXPO_PUBLIC_BACKEND_URL (or EXPO_BACKEND_URL) is required")
    return base.rstrip("/")


BASE_URL = _base_url()


@pytest.fixture
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture
def device_id():
    return f"gate4dev{uuid.uuid4().hex[:16]}"


def _mk_event(device_id: str, event_id: str, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "device_id": device_id,
        "category": "call",
        "state": "barking",
        "status": "active",
        "headline": "\u201cSafe account\u201d transfer",
        "what_happened": "Caller claiming to be your bank asked you to transfer money to a safe account.",
        "why": [
            "A caller telling you to move money into a new \u201csafe\u201d account is a major scam warning sign.",
            "Banks never move your money by phone instruction \u2014 they can freeze it themselves.",
        ],
        "what_to_do": "Hang up and contact your bank independently using its official app or the number on your card.",
        "verified_block": False,
        "adapter_label": "Call Risk Engine",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "background": False,
        "claimed_brand": None,
        "scenario": "C02",
    }
    payload.update(overrides)
    return payload


class TestPatrolCallEvents:
    def test_create_call_event_returns_200(self, api_client, device_id):
        event_id = f"call{uuid.uuid4().hex[:16]}"
        body = _mk_event(device_id, event_id)
        r = api_client.post(f"{BASE_URL}/api/patrol/events", json=body)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["category"] == "call"
        assert data["event_id"] == event_id
        assert data["state"] == "barking"
        assert data["scenario"] == "C02"

    def test_call_event_persists_and_listed(self, api_client, device_id):
        event_id = f"call{uuid.uuid4().hex[:16]}"
        api_client.post(f"{BASE_URL}/api/patrol/events", json=_mk_event(device_id, event_id))
        r = api_client.get(f"{BASE_URL}/api/patrol/events", params={"device_id": device_id})
        assert r.status_code == 200
        items = r.json()
        assert any(x["event_id"] == event_id and x["category"] == "call" for x in items)

    def test_call_event_upsert_updates(self, api_client, device_id):
        event_id = f"call{uuid.uuid4().hex[:16]}"
        api_client.post(f"{BASE_URL}/api/patrol/events", json=_mk_event(device_id, event_id))
        updated = _mk_event(device_id, event_id, headline="Verification code request", scenario="C03")
        r = api_client.post(f"{BASE_URL}/api/patrol/events", json=updated)
        assert r.status_code == 200
        assert r.json()["headline"] == "Apollo checked a phone call and found a problem that needs your attention"
        assert r.json()["scenario"] == "C03"

    def test_call_event_with_claimed_brand(self, api_client, device_id):
        event_id = f"call{uuid.uuid4().hex[:16]}"
        body = _mk_event(device_id, event_id, claimed_brand="CommBank", scent_id="scent_commbank")
        r = api_client.post(f"{BASE_URL}/api/patrol/events", json=body)
        assert r.status_code == 200
        d = r.json()
        assert d["claimed_brand"] in (None, "CommBank")
        assert d["scent_id"] == "scent_commbank"

    def test_call_event_rejects_bad_state(self, api_client, device_id):
        body = _mk_event(device_id, f"call{uuid.uuid4().hex[:16]}", state="notreal")
        r = api_client.post(f"{BASE_URL}/api/patrol/events", json=body)
        assert r.status_code == 422
