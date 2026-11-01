# Gate 1 — Email Patrol: iteration 17
# Verify that POST /api/patrol/events accepts category='email' and scenario 'E01'.
import os
import time
import uuid
from pathlib import Path

import requests
import pytest
from dotenv import load_dotenv

# Match the loading/fallback pattern used by test_admin.py and conftest.py so this test
# does not depend on shell-exported env vars that are only ever defined in frontend/.env.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE_URL = (
    os.environ.get("EXPO_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "https://case-source-preview--3ijise2t.preview.emergentagent.com"
).rstrip("/")


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def device_id():
    return f"TEST_dev_{uuid.uuid4().hex[:10]}"


class TestEmailPatrol:
    def test_health(self, api):
        r = api.get(f"{BASE_URL}/api/health", timeout=15)
        assert r.status_code == 200

    def test_patrol_event_email_e01(self, api, device_id):
        event_id = f"TEST_email_{uuid.uuid4().hex[:10]}"
        payload = {
            "event_id": event_id,
            "device_id": device_id,
            "category": "email",
            "state": "barking",
            "status": "active",
            "headline": "Email: Email impersonating CommBank",
            "what_happened": "This email says it's from CommBank, but it wasn't sent from CommBank.",
            "why": ["It was sent from cb-alerts-secure.top, which isn't CommBank's domain."],
            "what_to_do": "Delete it.",
            "indicator_host": "cb-alerts-secure.top",
            "indicator_digest": None,
            "local_indicator": "Your NetBank access has been restricted",
            "verified_block": False,
            "adapter_label": "mock",
            "occurred_at": "2026-01-01T00:00:00Z",
            "resolved_at": None,
            "trust_allowed": False,
            "claimed_brand": "CommBank",
            "scenario": "E01",
        }
        r = api.post(f"{BASE_URL}/api/patrol/events", json=payload, timeout=20)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("category") == "email"
        assert data.get("scenario") == "E01"
        assert data.get("event_id") == event_id

        # Verify persisted via GET /api/patrol
        time.sleep(0.5)
        rg = api.get(f"{BASE_URL}/api/patrol/events", params={"device_id": device_id}, timeout=15)
        assert rg.status_code == 200
        items = rg.json()
        assert any(e.get("event_id") == event_id and e.get("category") == "email" for e in items), \
            f"event not found in listing: {items}"

    def test_message_analyse_used_by_email(self, api, device_id):
        # Sanity: email flow calls /api/message/analyse with claimed_brand + scenario extras.
        payload = {
            "device_id": device_id,
            "sender": "CommBank <security@cb-alerts-secure.top>",
            "text": "Your NetBank access has been restricted\nhttps://netbank-commbank-verify.top/login",
            "urls": ["https://netbank-commbank-verify.top/login"],
            "local_state": "barking",
            "scenario": "E01",
            "signals": ["Claims to be CommBank", "Sender domain isn't the brand's"],
            "claimed_brand": "CommBank",
            "second_opinion": False,
        }
        r = api.post(f"{BASE_URL}/api/message/analyse", json=payload, timeout=45)
        assert r.status_code == 200, f"{r.status_code}: {r.text}"
        data = r.json()
        assert "urls" in data
