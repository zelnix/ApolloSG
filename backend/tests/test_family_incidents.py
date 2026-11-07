# Family Incident Sharing — share / progress / list / get.
import os, uuid
import pytest, requests

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://tc-flyby-2fa--0hiznn9n.preview.emergentagent.com").rstrip("/")


@pytest.fixture
def api():
    s = requests.Session(); s.headers.update({"Content-Type": "application/json"}); return s


def _pair(api, protected, guardian):
    code = api.post(f"{BASE_URL}/api/family/pair", json={"device_id": protected, "owner_name": "Mum"}).json()["code"]
    r = api.post(f"{BASE_URL}/api/family/link", json={"device_id": guardian, "code": code})
    assert r.status_code == 200, r.text


def _share(api, protected, scent, done=None):
    return api.post(f"{BASE_URL}/api/family/incidents/share", json={"device_id": protected, "scent_id": scent, "headline": "CommBank impersonation — message → account alert", "state": "barking",
        "events": [{"event_id": "e1", "category": "message", "state": "growling", "headline": "Message: CommBank SMS", "occurred_at": "2026-06-01T00:00:00Z", "status": "resolved"}, {"event_id": "e2", "category": "account", "state": "barking", "headline": "Account: Login prompt", "occurred_at": "2026-06-01T00:01:00Z", "status": "active"}],
        "steps": [{"id": "s0", "text": "Deny the prompt"}, {"id": "s1", "text": "Change the password"}], "done": done or []})


class TestFamilyIncidents:
    def test_share_without_links_is_zero(self, api):
        r = _share(api, f"nolink{uuid.uuid4().hex[:10]}", "scentX")
        assert r.status_code == 200 and r.json()["shared_with"] == 0

    def test_share_progress_list_get(self, api):
        protected, guardian, scent = f"prot{uuid.uuid4().hex[:12]}", f"guard{uuid.uuid4().hex[:12]}", f"sc{uuid.uuid4().hex[:8]}"
        _pair(api, protected, guardian)
        assert _share(api, protected, scent).json()["shared_with"] == 1
        lst = api.get(f"{BASE_URL}/api/family/incidents", params={"device_id": guardian}).json()
        assert any(i["scent_id"] == scent and i["from_label"] == "Mum" and i["done"] == [] for i in lst)
        p = api.patch(f"{BASE_URL}/api/family/incidents/{scent}/progress", json={"device_id": protected, "done": ["s0"], "resolved": False})
        assert p.status_code == 200 and p.json()["updated"] == 1
        one = api.get(f"{BASE_URL}/api/family/incidents/{scent}", params={"device_id": guardian}).json()
        assert one["done"] == ["s0"] and one["resolved"] is False and len(one["events"]) == 2 and len(one["steps"]) == 2
        api.patch(f"{BASE_URL}/api/family/incidents/{scent}/progress", json={"device_id": protected, "done": ["s0", "s1"], "resolved": True})
        assert api.get(f"{BASE_URL}/api/family/incidents/{scent}", params={"device_id": guardian}).json()["resolved"] is True
        # a stranger can't read it
        assert api.get(f"{BASE_URL}/api/family/incidents/{scent}", params={"device_id": f"other{uuid.uuid4().hex[:10]}"}).status_code == 404

    def test_validation(self, api):
        r = api.post(f"{BASE_URL}/api/family/incidents/share", json={"device_id": "short", "scent_id": "x", "headline": "h", "state": "barking", "events": [], "steps": []})
        assert r.status_code == 422
