# Family Reassurance Note — guardian posts a short note onto a shared incident; both sides can read it.
import os, uuid
import pytest, requests

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://case-source-preview--3ijise2t.preview.emergentagent.com").rstrip("/")


@pytest.fixture
def api():
    s = requests.Session(); s.headers.update({"Content-Type": "application/json"}); return s


def _setup(api):
    protected, guardian, scent = f"prot{uuid.uuid4().hex[:12]}", f"guard{uuid.uuid4().hex[:12]}", f"sc{uuid.uuid4().hex[:8]}"
    code = api.post(f"{BASE_URL}/api/family/pair", json={"device_id": protected, "owner_name": "Mum"}).json()["code"]
    assert api.post(f"{BASE_URL}/api/family/link", json={"device_id": guardian, "code": code}).status_code == 200
    r = api.post(f"{BASE_URL}/api/family/incidents/share", json={"device_id": protected, "scent_id": scent, "headline": "CommBank impersonation", "state": "barking",
        "events": [{"event_id": "e1", "category": "message", "state": "growling", "headline": "Message: CommBank SMS", "occurred_at": "2026-06-01T00:00:00Z", "status": "active"}],
        "steps": [{"id": "s0", "text": "Deny the prompt"}], "done": []})
    assert r.json()["shared_with"] == 1
    return protected, guardian, scent


class TestFamilyNotes:
    def test_preset_and_custom_notes_visible_to_both(self, api):
        protected, guardian, scent = _setup(api)
        r = api.post(f"{BASE_URL}/api/family/incidents/{scent}/notes", json={"device_id": guardian, "kind": "here", "from_name": "Sam"})
        assert r.status_code == 201, r.text
        n = r.json()
        assert n["text"] == "I'm here — call me when you're ready." and n["guardian_label"] == "Sam" and n["kind"] == "here"
        r2 = api.post(f"{BASE_URL}/api/family/incidents/{scent}/notes", json={"device_id": guardian, "kind": "custom", "text": "  Popping over at 6  "})
        assert r2.status_code == 201 and r2.json()["text"] == "Popping over at 6"
        assert r2.json()["guardian_label"] == "Sam"  # name remembered on the link
        for who in (protected, guardian):
            lst = api.get(f"{BASE_URL}/api/family/incidents/{scent}/notes", params={"device_id": who}).json()
            assert [x["kind"] for x in lst] == ["here", "custom"], lst
        # a stranger sees nothing
        assert api.get(f"{BASE_URL}/api/family/incidents/{scent}/notes", params={"device_id": f"str{uuid.uuid4().hex[:10]}"}).json() == []

    def test_validation(self, api):
        protected, guardian, scent = _setup(api)
        assert api.post(f"{BASE_URL}/api/family/incidents/{scent}/notes", json={"device_id": guardian, "kind": "custom", "text": "   "}).status_code == 422
        assert api.post(f"{BASE_URL}/api/family/incidents/{scent}/notes", json={"device_id": guardian, "kind": "shout"}).status_code == 422
        assert api.post(f"{BASE_URL}/api/family/incidents/{scent}/notes", json={"device_id": guardian, "kind": "custom", "text": "x" * 141}).status_code == 422
        # not a guardian of this incident -> 404
        assert api.post(f"{BASE_URL}/api/family/incidents/{scent}/notes", json={"device_id": protected, "kind": "here"}).status_code == 404
        assert api.post(f"{BASE_URL}/api/family/incidents/nope{uuid.uuid4().hex[:6]}/notes", json={"device_id": guardian, "kind": "here"}).status_code == 404
