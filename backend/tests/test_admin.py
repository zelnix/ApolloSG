# External admin console — separate trust boundary (X-Admin-Key shared secret), never mixed with device bearer auth.
import os, uuid
from pathlib import Path

import pytest, requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://case-source-preview--3ijise2t.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
KEY = os.environ.get("APOLLO_ADMIN_KEY", "")
H = {"User-Agent": "apollo-tests", "X-Apollo-Raw": "1"}
ADMIN = {**H, "X-Admin-Key": KEY}

pytestmark = pytest.mark.skipif(not KEY, reason="APOLLO_ADMIN_KEY not configured")


def _device():
    r = requests.post(f"{API}/devices/register", json={"platform": "web", "adapter_mode": "mock"}, headers=H)
    return r.json()["device_id"], r.json()["device_token"]


class TestAdminKeyBoundary:
    def test_missing_and_wrong_key_are_generic_401(self):
        assert requests.get(f"{API}/admin/ping", headers=H).status_code == 401
        r = requests.get(f"{API}/admin/ping", headers={**H, "X-Admin-Key": KEY[:-1] + ("x" if KEY[-1] != "x" else "y")})
        assert r.status_code == 401 and r.json()["detail"] == "Invalid admin credentials."
        assert requests.get(f"{API}/admin/ping", headers={**H, "X-Admin-Key": ""}).status_code == 401

    def test_right_key_works(self):
        r = requests.get(f"{API}/admin/ping", headers=ADMIN)
        assert r.status_code == 200 and r.json()["ok"] is True

    def test_device_bearer_cannot_open_admin(self):
        _, tok = _device()
        assert requests.get(f"{API}/admin/ping", headers={**H, "Authorization": f"Bearer {tok}"}).status_code == 401

    def test_admin_key_cannot_open_device_routes(self):
        assert requests.get(f"{API}/devices/me", headers=ADMIN).status_code == 401
        assert requests.get(f"{API}/patrol/events?device_id=abcdefgh12345678", headers=ADMIN).status_code == 401


class TestAdminOperations:
    def test_stats_shape(self):
        j = requests.get(f"{API}/admin/stats", headers=ADMIN).json()
        assert {"devices", "events_7d", "blocklist", "feedback", "family", "intel"} <= set(j)
        assert j["devices"]["total"] >= j["devices"]["active_credentials"]

    def test_devices_listing_never_leaks_token_hashes(self):
        did, _ = _device()
        rows = requests.get(f"{API}/admin/devices?limit=500", headers=ADMIN).json()
        assert all("token_hash" not in r for r in rows)
        one = requests.get(f"{API}/admin/devices/{did}", headers=ADMIN).json()
        assert one["device_id"] == did and "token_hash" not in one and one["patrol_events"] == 0

    def test_revoke_from_console_kills_the_device_credential(self):
        did, tok = _device()
        dev = {**H, "Authorization": f"Bearer {tok}"}
        assert requests.get(f"{API}/devices/me", headers=dev).status_code == 200
        assert requests.post(f"{API}/admin/devices/{did}/revoke", headers=ADMIN).status_code == 204
        r = requests.get(f"{API}/devices/me", headers=dev)
        assert r.status_code == 401 and "WWW-Authenticate" in r.headers  # app enters the explicit re-register state
        assert requests.post(f"{API}/admin/devices/{did}/revoke", headers=ADMIN).status_code == 404
        assert requests.post(f"{API}/admin/devices/no-such-device/revoke", headers=ADMIN).status_code == 404

    def test_blocklist_add_changes_verdicts_immediately_and_remove_restores(self):
        host = f"console-{uuid.uuid4().hex[:8]}.apollo.test"
        did, tok = _device()
        dev = {**H, "Authorization": f"Bearer {tok}"}
        check = lambda: requests.post(f"{API}/intel/check", json={"indicator_type": "url", "value": f"https://{host}/login", "device_id": did}, headers=dev).json()  # noqa: E731
        assert check()["verdict"] != "malicious"
        r = requests.post(f"{API}/admin/blocklist", json={"host": host, "threat_type": "SOCIAL_ENGINEERING", "reason": "console test"}, headers=ADMIN)
        assert r.status_code == 201 and r.json()["host"] == host
        assert any(e["host"] == host for e in requests.get(f"{API}/admin/blocklist", headers=ADMIN).json())
        j = check()
        assert j["verdict"] == "malicious" and j["cached"] is False
        assert requests.delete(f"{API}/admin/blocklist/{host}", headers=ADMIN).status_code == 204
        assert check()["verdict"] != "malicious"
        assert requests.delete(f"{API}/admin/blocklist/{host}", headers=ADMIN).status_code == 404

    def test_blocklist_rejects_non_domains(self):
        for bad in ["not a host", "http://x.y", "localhost", "a..b"]:
            assert requests.post(f"{API}/admin/blocklist", json={"host": bad, "reason": "bad input"}, headers=ADMIN).status_code == 422

    def test_feedback_listing(self):
        r = requests.get(f"{API}/admin/feedback?limit=5", headers=ADMIN)
        assert r.status_code == 200 and isinstance(r.json(), list)


class TestAuditTrail:
    def test_every_console_action_is_logged_with_actor_and_visible_in_stats(self):
        host = f"audit-{uuid.uuid4().hex[:8]}.apollo.test"
        did, _ = _device()
        op = {**ADMIN, "X-Admin-Actor": "ops@hwg"}
        assert requests.post(f"{API}/admin/blocklist", json={"host": host, "reason": "audit test"}, headers=op).status_code == 201
        assert requests.delete(f"{API}/admin/blocklist/{host}", headers=op).status_code == 204
        assert requests.post(f"{API}/admin/devices/{did}/revoke", headers=ADMIN).status_code == 204  # no actor header → "console"
        log = requests.get(f"{API}/admin/audit?limit=50", headers=ADMIN).json()
        mine = [r for r in log if r["target"] in (host, did)]
        assert [r["action"] for r in sorted(mine, key=lambda r: r["at"])] == ["blocklist.add", "blocklist.remove", "device.revoke"]
        add = next(r for r in mine if r["action"] == "blocklist.add")
        assert add["actor"] == "ops@hwg" and add["detail"] == {"threat_type": "SOCIAL_ENGINEERING", "reason": "audit test"} and add["audit_id"] and add["at"]
        assert next(r for r in mine if r["action"] == "device.revoke")["actor"] == "console"
        # filters
        assert all(r["action"] == "device.revoke" for r in requests.get(f"{API}/admin/audit?action=device.revoke", headers=ADMIN).json())
        assert any(r["target"] == host for r in requests.get(f"{API}/admin/audit?actor=ops@hwg&target={host}", headers=ADMIN).json())
        stats = requests.get(f"{API}/admin/stats", headers=ADMIN).json()["audit"]
        assert stats["total"] >= 3 and stats["last_7d"] >= 3 and stats["by_action_7d"].get("device.revoke", 0) >= 1
        assert stats["recent"][0]["action"] == "device.revoke" and stats["recent"][0]["target"] == did

    def test_audit_needs_the_admin_key_and_failed_attempts_write_nothing(self):
        before = requests.get(f"{API}/admin/stats", headers=ADMIN).json()["audit"]["total"]
        assert requests.get(f"{API}/admin/audit", headers=H).status_code == 401
        assert requests.post(f"{API}/admin/blocklist", json={"host": "x.apollo.test", "reason": "nope"}, headers=H).status_code == 401
        assert requests.post(f"{API}/admin/devices/no-such/revoke", headers=ADMIN).status_code == 404  # failed action → not logged
        assert requests.get(f"{API}/admin/stats", headers=ADMIN).json()["audit"]["total"] == before
