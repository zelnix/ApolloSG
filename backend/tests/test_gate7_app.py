# Gate 7 — Apps & Device Protection backend tests.
# POST /api/app/analyse (reputation hints, SDK-host intel and the shared Higgins assessment) and
# POST /api/patrol/events accepting categories "app" / "device".
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://tc-flyby-2fa--0hiznn9n.preview.emergentagent.com").rstrip("/")


@pytest.fixture
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture
def device_id():
    return f"gate7dev{uuid.uuid4().hex[:16]}"


def _analyse(api_client, device_id, **over):
    body = {"device_id": device_id, "name": "Tiny Notes", "developer": None, "source": "play_store", "purpose": "other", "permissions": [], "hosts": [],
            "local_state": "resting", "scenario": "A18", "second_opinion": False}
    body.update(over)
    return api_client.post(f"{BASE_URL}/api/app/analyse", json=body, timeout=120)


class TestAppAnalyse:
    def test_remote_access_tool_flagged(self, api_client, device_id):
        r = _analyse(api_client, device_id, name="AnyDesk Remote Desktop", source="browser", purpose="remote_support", permissions=["screen_share"], local_state="barking", scenario="A01")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["reputation"]["remote_access_tool"] == "Anydesk"
        assert d["reputation"]["official_store"] is False
        assert "scammers" in d["reputation"]["note"]
        assert d["assessment"] is None
        assert d["gemini_used"] is False

    def test_brand_impersonation_off_store(self, api_client, device_id):
        d = _analyse(api_client, device_id, name="CommBank Security Update", source="browser", purpose="update", local_state="barking", scenario="A03").json()
        assert d["reputation"]["impersonates_brand"] == "Commbank"

    def test_brand_from_official_store_not_impersonation(self, api_client, device_id):
        d = _analyse(api_client, device_id, name="CommBank app", source="app_store", purpose="banking").json()
        assert d["reputation"]["impersonates_brand"] is None
        assert d["reputation"]["official_store"] is True
        assert "not proof of safety" in d["reputation"]["note"]

    def test_security_vendor_recognised(self, api_client, device_id):
        d = _analyse(api_client, device_id, name="Microsoft Authenticator", source="app_store", purpose="security", scenario="A13").json()
        assert d["reputation"]["known_security_vendor"] == "Microsoft Authenticator"
        assert d["reputation"]["impersonates_brand"] is None

    def test_hosts_checked_against_intel(self, api_client, device_id):
        d = _analyse(api_client, device_id, hosts=["phishing.apollo.test", "example.com"]).json()
        by_host = {h["host"]: h for h in d["hosts"]}
        assert by_host["phishing.apollo.test"]["verdict"] == "malicious"
        assert by_host["example.com"]["verdict"] in ("clean", "unknown")

    def test_validation_rejects_empty_name(self, api_client, device_id):
        r = _analyse(api_client, device_id, name="")
        assert r.status_code == 422

    def test_second_opinion_flag_cannot_start_legacy_investigator(self, api_client, device_id):
        r = _analyse(api_client, device_id, name="Fast Utility", permissions=["accessibility", "overlay", "notifications"], local_state="growling", scenario="A05", second_opinion=True)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["explanation"] is None
        assert d["assessment"] is None
        assert d["gemini_used"] is False


class TestPatrolAppDeviceEvents:
    @pytest.mark.parametrize("category,scenario", [("app", "A01"), ("device", "D02")])
    def test_create_event(self, api_client, device_id, category, scenario):
        event_id = f"{category}{uuid.uuid4().hex[:16]}"
        body = {"event_id": event_id, "device_id": device_id, "category": category, "state": "barking", "status": "active", "headline": f"{category} test",
                "what_happened": "x", "why": ["y"], "what_to_do": "z", "verified_block": False, "adapter_label": "App & Device Engine",
                "occurred_at": datetime.now(timezone.utc).isoformat(), "background": False, "claimed_brand": None, "scenario": scenario, "scent_id": event_id}
        r = api_client.post(f"{BASE_URL}/api/patrol/events", json=body)
        assert r.status_code == 200, r.text
        assert r.json()["category"] == category
        listed = api_client.get(f"{BASE_URL}/api/patrol/events", params={"device_id": device_id}).json()
        assert any(e["event_id"] == event_id for e in listed)
