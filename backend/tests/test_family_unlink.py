# Unlink Device — either side of a pairing can end it; the other phone stops receiving fan-outs immediately.
import os, time, uuid
from datetime import datetime, timezone

import requests

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://tc-flyby-2fa--0hiznn9n.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


class Dev:
    def __init__(self):
        j = requests.post(f"{API}/devices/register", json={"platform": "web", "adapter_mode": "mock"}, headers={"User-Agent": "apollo-tests"}).json()
        self.id = j["device_id"]
        self.s = requests.Session(); self.s.headers.update({"Content-Type": "application/json", "User-Agent": "apollo-tests", "X-Apollo-Raw": "1", "Authorization": f"Bearer {j['device_token']}"})
    def get(self, p, **kw): return self.s.get(f"{API}{p}", **kw)
    def post(self, p, **kw): return self.s.post(f"{API}{p}", **kw)
    def delete(self, p, **kw): return self.s.delete(f"{API}{p}", **kw)


def pair(protected: Dev, guardian: Dev):
    code = protected.post("/family/pair", json={"device_id": protected.id, "owner_name": "Mum"}).json()["code"]
    assert guardian.post("/family/link", json={"device_id": guardian.id, "code": code}).status_code == 200


def event(dev: Dev):
    eid = f"evt-{uuid.uuid4().hex[:10]}"
    r = dev.post("/patrol/events", json={"event_id": eid, "device_id": dev.id, "category": "known_threat", "state": "barking", "status": "active", "headline": "Threat", "what_happened": "x", "why": ["y"], "what_to_do": "z", "indicator_host": "phish.example", "adapter_label": "MOCK", "occurred_at": datetime.now(timezone.utc).isoformat()})
    assert r.status_code == 200, r.text
    return eid


class TestUnlinkDevice:
    def test_protected_person_removes_a_watcher(self):
        p, g = Dev(), Dev()
        pair(p, g)
        links = p.get("/family/links", params={"device_id": p.id}).json()
        assert links["watching_me"] == 1 and len(links["watchers"]) == 1
        w = links["watchers"][0]
        assert set(w) == {"link_id", "guardian_label", "since", "last_checkin_at"} and "device" not in " ".join(k for k in w)  # no guardian device id leaks
        e1 = event(p); time.sleep(2.5)
        assert any(e["event_id"] == e1 for e in g.get("/family/shared-events", params={"device_id": g.id}).json())
        assert p.delete(f"/family/links/{w['link_id']}", params={"device_id": p.id}).status_code == 204
        assert p.get("/family/links", params={"device_id": p.id}).json()["watching_me"] == 0
        assert g.get("/family/links", params={"device_id": g.id}).json()["i_watch"] == []
        e2 = event(p); time.sleep(2.5)
        assert not any(e["event_id"] == e2 for e in g.get("/family/shared-events", params={"device_id": g.id}).json()), "unlinked watcher still received a fan-out"
        assert g.get("/family/weekly", params={"device_id": g.id}).json() == []
        assert p.delete(f"/family/links/{w['link_id']}", params={"device_id": p.id}).status_code == 404  # already gone

    def test_guardian_can_stop_watching_and_strangers_cannot_touch_a_link(self):
        p, g, stranger = Dev(), Dev(), Dev()
        pair(p, g)
        link_id = g.get("/family/links", params={"device_id": g.id}).json()["i_watch"][0]["link_id"]
        assert stranger.delete(f"/family/links/{link_id}", params={"device_id": stranger.id}).status_code == 404
        assert stranger.delete(f"/family/links/{link_id}", params={"device_id": p.id}).status_code == 403  # claimed id ≠ token
        assert g.delete("/family/links/not-an-id", params={"device_id": g.id}).status_code == 404
        assert g.delete(f"/family/links/{link_id}", params={"device_id": g.id}).status_code == 204
        assert p.get("/family/links", params={"device_id": p.id}).json()["watchers"] == []

    def test_repair_after_unlink_creates_a_fresh_link(self):
        p, g = Dev(), Dev()
        pair(p, g)
        link_id = g.get("/family/links", params={"device_id": g.id}).json()["i_watch"][0]["link_id"]
        assert g.delete(f"/family/links/{link_id}", params={"device_id": g.id}).status_code == 204
        pair(p, g)
        links = p.get("/family/links", params={"device_id": p.id}).json()
        assert links["watching_me"] == 1


class TestWatcherNames:
    def test_guardian_name_travels_with_the_pairing_and_can_be_changed(self):
        p, g = Dev(), Dev()
        code = p.post("/family/pair", json={"device_id": p.id, "owner_name": "Mum"}).json()["code"]
        assert g.post("/family/link", json={"device_id": g.id, "code": code, "guardian_name": "Sarah"}).status_code == 200
        watchers = p.get("/family/links", params={"device_id": p.id}).json()["watchers"]
        assert watchers[0]["guardian_label"] == "Sarah"
        mine = g.get("/family/links", params={"device_id": g.id}).json()["i_watch"][0]
        assert mine["my_label"] == "Sarah"
        r = g.s.put(f"{API}/family/links/{mine['link_id']}/name", json={"device_id": g.id, "name": "Sarah (daughter)"})
        assert r.status_code == 200 and r.json()["name"] == "Sarah (daughter)"
        assert p.get("/family/links", params={"device_id": p.id}).json()["watchers"][0]["guardian_label"] == "Sarah (daughter)"
        # only the guardian side may rename; the protected person and strangers get 404
        assert p.s.put(f"{API}/family/links/{mine['link_id']}/name", json={"device_id": p.id, "name": "x"}).status_code == 404
        assert g.s.put(f"{API}/family/links/{mine['link_id']}/name", json={"device_id": g.id, "name": ""}).status_code == 422

    def test_pairing_without_a_name_keeps_the_neutral_label(self):
        p, g = Dev(), Dev()
        pair(p, g)
        assert p.get("/family/links", params={"device_id": p.id}).json()["watchers"][0]["guardian_label"] == "A family member"
