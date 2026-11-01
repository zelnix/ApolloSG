"""Gmail multi-account per device — HTTP endpoint layer tests.

Covers:
- GET /api/gmail/status: `connected`, `configured`, `accounts[]` + back-compat top-level fields.
- Compound unique index (device_id, email): two accounts per device persist and surface.
- POST /api/gmail/monitoring: device-wide enable/disable flips every row (update_many).
- DELETE /api/gmail/connection: single-account vs device-wide; both return 204.
- Regression: GET /api/health schema.

Google OAuth cannot be exercised (project in Testing mode -> 403), so we seed
`gmail_connections` directly in Mongo with `refresh_token_enc=""` so disconnect()
does not attempt a Google token revocation. All seeded rows are cleaned up.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = (
    os.environ.get("EXPO_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "https://case-source-preview--3ijise2t.preview.emergentagent.com"
).rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

EMAIL_A = "TEST_apollo_multi_a@example.com"
EMAIL_B = "TEST_apollo_multi_b@example.com"


# ----------------------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def device():
    """Register a real device so we have a valid bearer credential for /api/gmail routes."""
    r = requests.post(
        f"{BASE_URL}/api/devices/register",
        json={"platform": "ios", "adapter_mode": "test", "app_version": "1.0.0"},
        timeout=15,
    )
    assert r.status_code == 201, f"device register failed: {r.status_code} {r.text}"
    data = r.json()
    assert "device_id" in data and "device_token" in data
    return data


@pytest.fixture(scope="module")
def auth_session(device):
    s = requests.Session()
    s.headers.update(
        {
            "Authorization": f"Bearer {device['device_token']}",
            "Content-Type": "application/json",
        }
    )
    return s


def _seed_connection(mongo, device_id: str, email: str, monitoring_enabled: bool = False) -> None:
    now = datetime.now(timezone.utc)
    mongo.gmail_connections.update_one(
        {"device_id": device_id, "email": email},
        {
            "$set": {
                "device_id": device_id,
                "email": email,
                "refresh_token_enc": "",  # empty so disconnect() won't call Google
                "monitoring_enabled": monitoring_enabled,
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


@pytest.fixture(autouse=True)
def _cleanup_connections(mongo, device):
    """Ensure a clean slate before each test and remove rows after."""
    mongo.gmail_connections.delete_many({"device_id": device["device_id"]})
    yield
    mongo.gmail_connections.delete_many({"device_id": device["device_id"]})


# ----------------------------------------------------------------------------- /api/health regression
class TestHealthRegression:
    def test_health_schema(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["schemaVersion"] == 1
        assert body["status"] == "ok"
        assert body["service"] == "apollo-v1"
        assert isinstance(body["checkedAt"], str) and body["checkedAt"]


# ----------------------------------------------------------------------------- /api/gmail/status (empty + multi)
class TestGmailStatus:
    def test_status_unconnected_shape(self, auth_session, device):
        r = auth_session.get(
            f"{BASE_URL}/api/gmail/status",
            params={"device_id": device["device_id"]},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["connected"] is False
        assert isinstance(body["configured"], bool)
        assert body["accounts"] == []
        # Back-compat top-level fields still present (mirror disconnected / off state).
        assert body["monitoring_enabled"] is False
        assert body["monitor_state"] == "disconnected"
        assert "cursor_pending" in body

    def test_status_two_accounts_persist_and_report(self, auth_session, device, mongo):
        _seed_connection(mongo, device["device_id"], EMAIL_A, monitoring_enabled=False)
        _seed_connection(mongo, device["device_id"], EMAIL_B, monitoring_enabled=False)

        # Both rows actually persist in Mongo (compound unique index on device_id+email).
        assert mongo.gmail_connections.count_documents({"device_id": device["device_id"]}) == 2

        r = auth_session.get(
            f"{BASE_URL}/api/gmail/status",
            params={"device_id": device["device_id"]},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["connected"] is True
        accounts = body["accounts"]
        assert isinstance(accounts, list) and len(accounts) == 2

        emails = sorted(a["email"] for a in accounts)
        assert emails == sorted([EMAIL_A, EMAIL_B])

        allowed_states = {"disconnected", "off", "checking", "needs_attention", "ready"}
        for acc in accounts:
            assert "email" in acc
            assert "monitoring_enabled" in acc and isinstance(acc["monitoring_enabled"], bool)
            assert acc["monitor_state"] in allowed_states, acc

        # Back-compat single-account fields still present (mirror the first account).
        assert "monitoring_enabled" in body
        assert body["monitor_state"] in allowed_states


# ----------------------------------------------------------------------------- /api/gmail/monitoring device-wide
class TestGmailMonitoringToggle:
    def test_monitoring_enable_flips_all_accounts(self, auth_session, device, mongo):
        _seed_connection(mongo, device["device_id"], EMAIL_A, monitoring_enabled=False)
        _seed_connection(mongo, device["device_id"], EMAIL_B, monitoring_enabled=False)

        r = auth_session.post(
            f"{BASE_URL}/api/gmail/monitoring",
            json={"device_id": device["device_id"], "enabled": True},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"monitoring_enabled": True}

        # Verify every row for this device flipped (update_many).
        rows = list(mongo.gmail_connections.find({"device_id": device["device_id"]}))
        assert len(rows) == 2
        assert all(row["monitoring_enabled"] is True for row in rows), rows

        # /status also reflects this per-account.
        status = auth_session.get(
            f"{BASE_URL}/api/gmail/status",
            params={"device_id": device["device_id"]},
            timeout=15,
        ).json()
        assert all(acc["monitoring_enabled"] is True for acc in status["accounts"])

    def test_monitoring_disable_flips_all_accounts(self, auth_session, device, mongo):
        _seed_connection(mongo, device["device_id"], EMAIL_A, monitoring_enabled=True)
        _seed_connection(mongo, device["device_id"], EMAIL_B, monitoring_enabled=True)

        r = auth_session.post(
            f"{BASE_URL}/api/gmail/monitoring",
            json={"device_id": device["device_id"], "enabled": False},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"monitoring_enabled": False}
        rows = list(mongo.gmail_connections.find({"device_id": device["device_id"]}))
        assert all(row["monitoring_enabled"] is False for row in rows)

    def test_monitoring_404_when_no_connections(self, auth_session, device):
        r = auth_session.post(
            f"{BASE_URL}/api/gmail/monitoring",
            json={"device_id": device["device_id"], "enabled": True},
            timeout=15,
        )
        assert r.status_code == 404, r.text


# ----------------------------------------------------------------------------- /api/gmail/connection DELETE
class TestGmailDisconnect:
    def test_delete_single_account_removes_only_that_account(self, auth_session, device, mongo):
        _seed_connection(mongo, device["device_id"], EMAIL_A)
        _seed_connection(mongo, device["device_id"], EMAIL_B)

        r = auth_session.delete(
            f"{BASE_URL}/api/gmail/connection",
            params={"device_id": device["device_id"], "email": EMAIL_A},
            timeout=15,
        )
        assert r.status_code == 204, f"expected 204, got {r.status_code}: {r.text}"
        assert r.content in (b"", None)

        remaining = list(mongo.gmail_connections.find({"device_id": device["device_id"]}))
        assert len(remaining) == 1
        assert remaining[0]["email"] == EMAIL_B

        status = auth_session.get(
            f"{BASE_URL}/api/gmail/status",
            params={"device_id": device["device_id"]},
            timeout=15,
        ).json()
        assert status["connected"] is True
        assert len(status["accounts"]) == 1
        assert status["accounts"][0]["email"] == EMAIL_B

    def test_delete_without_email_removes_all_accounts(self, auth_session, device, mongo):
        _seed_connection(mongo, device["device_id"], EMAIL_A)
        _seed_connection(mongo, device["device_id"], EMAIL_B)

        r = auth_session.delete(
            f"{BASE_URL}/api/gmail/connection",
            params={"device_id": device["device_id"]},
            timeout=15,
        )
        assert r.status_code == 204, f"expected 204, got {r.status_code}: {r.text}"

        remaining = mongo.gmail_connections.count_documents({"device_id": device["device_id"]})
        assert remaining == 0

        status = auth_session.get(
            f"{BASE_URL}/api/gmail/status",
            params={"device_id": device["device_id"]},
            timeout=15,
        ).json()
        assert status["connected"] is False
        assert status["accounts"] == []

    def test_delete_idempotent_when_no_rows(self, auth_session, device):
        r = auth_session.delete(
            f"{BASE_URL}/api/gmail/connection",
            params={"device_id": device["device_id"]},
            timeout=15,
        )
        assert r.status_code == 204


# ----------------------------------------------------------------------------- compound-index enforcement
class TestCompoundIndex:
    def test_compound_unique_index_exists(self, mongo):
        info = mongo.gmail_connections.index_information()
        # Legacy device_id-only unique index must be gone (or be the compound one).
        legacy = info.get("device_id_1")
        if legacy is not None:
            assert legacy.get("key") == [("device_id", 1), ("email", 1)], (
                f"legacy single-field unique index still present: {legacy}"
            )
        # A compound index on (device_id, email) must exist and be unique.
        compound = [
            (name, defn)
            for name, defn in info.items()
            if defn.get("key") == [("device_id", 1), ("email", 1)]
        ]
        assert compound, f"compound (device_id,email) index missing: {info}"
        assert any(defn.get("unique") for _n, defn in compound), (
            f"compound (device_id,email) index exists but is not unique: {compound}"
        )

    def test_same_device_different_email_both_persist(self, mongo, device):
        _seed_connection(mongo, device["device_id"], EMAIL_A)
        _seed_connection(mongo, device["device_id"], EMAIL_B)
        count = mongo.gmail_connections.count_documents({"device_id": device["device_id"]})
        assert count == 2
