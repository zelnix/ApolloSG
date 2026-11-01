# Check-In Reply — guardian taps "All good, spoke to Mum"; protected user sees who checked in.
import os, uuid
import pytest, requests

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://case-source-preview--3ijise2t.preview.emergentagent.com").rstrip("/")


@pytest.fixture
def api():
    s = requests.Session(); s.headers.update({"Content-Type": "application/json", "User-Agent": "apollo-tests"}); return s


def _pair(api, protected, guardian, owner="Mum"):
    code = api.post(f"{BASE_URL}/api/family/pair", json={"device_id": protected, "owner_name": owner}).json()["code"]
    assert api.post(f"{BASE_URL}/api/family/link", json={"device_id": guardian, "code": code}).status_code == 200


class TestCheckinReply:
    def test_reply_visible_to_both_and_upserts_per_week(self, api):
        protected, guardian = f"prot{uuid.uuid4().hex[:12]}", f"guard{uuid.uuid4().hex[:12]}"
        _pair(api, protected, guardian)
        r = api.post(f"{BASE_URL}/api/family/weekly/checkin", json={"device_id": guardian, "protected_device_id": protected, "reply": "spoke", "from_name": "Sam"})
        assert r.status_code == 200, r.text
        assert r.json()["label"] == "All good, spoke to them" and r.json()["guardian_label"] == "Sam"
        # re-tap with a different reply in the same week → updates, not duplicates
        r2 = api.post(f"{BASE_URL}/api/family/weekly/checkin", json={"device_id": guardian, "protected_device_id": protected, "reply": "messaged"})
        assert r2.json()["label"] == "Messaged them, all good" and r2.json()["guardian_label"] == "Sam"
        for who in (protected, guardian):
            lst = api.get(f"{BASE_URL}/api/family/weekly/checkins", params={"device_id": who}).json()
            mine = [c for c in lst if c["protected_device_id"] == protected]
            assert len(mine) == 1 and mine[0]["reply"] == "messaged" and mine[0]["guardian_label"] == "Sam"
        assert api.get(f"{BASE_URL}/api/family/weekly/checkins", params={"device_id": f"str{uuid.uuid4().hex[:10]}"}).json() == []

    def test_validation(self, api):
        protected, guardian = f"prot{uuid.uuid4().hex[:12]}", f"guard{uuid.uuid4().hex[:12]}"
        # not paired → 404
        assert api.post(f"{BASE_URL}/api/family/weekly/checkin", json={"device_id": guardian, "protected_device_id": protected}).status_code == 404
        _pair(api, protected, guardian)
        assert api.post(f"{BASE_URL}/api/family/weekly/checkin", json={"device_id": guardian, "protected_device_id": protected, "reply": "hug"}).status_code == 422
        # the protected person can't check in on themselves via a reversed pair
        assert api.post(f"{BASE_URL}/api/family/weekly/checkin", json={"device_id": protected, "protected_device_id": guardian}).status_code == 404
