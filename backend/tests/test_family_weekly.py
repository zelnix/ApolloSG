# Family Weekly Check-In (GET /api/family/weekly) + call-back phone on reassurance notes.
import os, uuid
from datetime import datetime, timedelta, timezone
import pytest, requests

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://tc-flyby-2fa--0hiznn9n.preview.emergentagent.com").rstrip("/")


@pytest.fixture
def api():
    s = requests.Session(); s.headers.update({"Content-Type": "application/json", "User-Agent": "apollo-tests"}); return s


def _pair(api, protected, guardian):
    api.post(f"{BASE_URL}/api/devices/register", json={"device_id": protected, "platform": "web", "adapter_mode": "mock", "app_version": "1.0.0"})
    code = api.post(f"{BASE_URL}/api/family/pair", json={"device_id": protected, "owner_name": "Mum"}).json()["code"]
    assert api.post(f"{BASE_URL}/api/family/link", json={"device_id": guardian, "code": code}).status_code == 200
    # The family member saves Mum's number themselves (from any of her alerts); pairing never asks for it.
    assert api.post(f"{BASE_URL}/api/family/links/phone", json={"device_id": guardian, "protected_device_id": protected, "phone": "+61 400 000 000"}).status_code == 200


def _event(api, device, state, status, days_ago=1, category="link", evidence=None):
    eid = uuid.uuid4().hex[:16]
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    if evidence:
        evidence = {**evidence, "observed_at": ts}
    r = api.post(f"{BASE_URL}/api/patrol/events", json={"event_id": eid, "device_id": device, "category": category, "state": state, "status": status, "headline": "x", "what_happened": "x", "why": [], "what_to_do": "x", "adapter_label": "mock", "occurred_at": ts, "enforcement_evidence": evidence})
    assert r.status_code in (200, 201), r.text
    return eid


def _valid_evidence():
    # state="biting" is gated server-side (see backend/routers/patrol.py::_derive_verified_block,
    # the cross-platform correctness pass's Biting invariant) — it can only be persisted with
    # validated enforcement_evidence. This digest test cares about the weekly counts/redaction
    # behaviour, not evidence validation itself (that's covered by
    # tests/test_enforcement_evidence_gate.py), so it supplies fully valid evidence just to
    # legitimately reach "biting". device_id is deliberately omitted: the conftest.py auth shim
    # only rewrites the top-level device_id key to the real server-issued id, not a nested one
    # inside enforcement_evidence, so naming it here would create a false mismatch.
    return {
        "evidence_id": f"ev-{uuid.uuid4().hex[:12]}", "event_id": None, "device_id": None, "platform": "android",
        "os_version": None, "sdk_version": None, "observed_at": datetime.now(timezone.utc).isoformat(),
        "mechanism": "dns_filter", "direction": "outbound", "protocol": "dns",
        "destination_ip": None, "destination_domain": "evil.example", "destination_port": 53,
        "app_id": None, "process_name": None, "attribution_confidence": "unavailable",
        "matched_rule_id": "evil.example", "threat_id": None, "requested_action": "block", "enforced_action": "blocked",
        "result": "verified", "rule_source": "local_blocklist", "confidence": "high", "correlation_id": None,
    }


class TestFamilyWeekly:
    def test_quiet_week_counts_zero(self, api):
        protected, guardian = f"prot{uuid.uuid4().hex[:12]}", f"guard{uuid.uuid4().hex[:12]}"
        _pair(api, protected, guardian)
        w = api.get(f"{BASE_URL}/api/family/weekly", params={"device_id": guardian}).json()
        assert len(w) == 1 and w[0]["owner_name"] == "Mum" and w[0]["total"] == 0 and w[0]["alerts"] == 0 and w[0]["phone"] == "+61 400 000 000"
        assert w[0]["last_seen_at"] is not None  # device registered → truthful last-seen

    def test_counts_only_never_headlines(self, api):
        protected, guardian = f"prot{uuid.uuid4().hex[:12]}", f"guard{uuid.uuid4().hex[:12]}"
        _pair(api, protected, guardian)
        _event(api, protected, "resting", "resolved", days_ago=1)
        _event(api, protected, "resting", "resolved", days_ago=2)
        _event(api, protected, "growling", "active", days_ago=1)
        _event(api, protected, "barking", "resolved", days_ago=3)
        _event(api, protected, "biting", "resolved", days_ago=3, evidence=_valid_evidence())
        _event(api, protected, "barking", "active", days_ago=10)  # outside the week
        w = api.get(f"{BASE_URL}/api/family/weekly", params={"device_id": guardian}).json()[0]
        assert w["total"] == 5 and w["alerts"] == 3 and w["open_alerts"] == 1 and w["handled_alerts"] == 2 and w["blocked"] == 1
        assert w["active_days"] == 3 and w["by_state"]["resting"] == 2
        assert "headline" not in w and "events" not in w
        # stranger sees nothing
        assert api.get(f"{BASE_URL}/api/family/weekly", params={"device_id": f"str{uuid.uuid4().hex[:10]}"}).json() == []


class TestNoteCallBack:
    def test_phone_on_note_and_remembered(self, api):
        protected, guardian, scent = f"prot{uuid.uuid4().hex[:12]}", f"guard{uuid.uuid4().hex[:12]}", f"sc{uuid.uuid4().hex[:8]}"
        _pair(api, protected, guardian)
        r = api.post(f"{BASE_URL}/api/family/incidents/share", json={"device_id": protected, "scent_id": scent, "headline": "h", "state": "barking", "events": [], "steps": [], "done": []})
        assert r.json()["shared_with"] == 1
        n1 = api.post(f"{BASE_URL}/api/family/incidents/{scent}/notes", json={"device_id": guardian, "kind": "here", "from_name": "Sam", "phone": "+61 (4) 11-222 333"}).json()
        assert n1["phone"] == "+61 4 11222 333"  # punctuation scrubbed, digits/plus/spaces kept
        n2 = api.post(f"{BASE_URL}/api/family/incidents/{scent}/notes", json={"device_id": guardian, "kind": "calling"}).json()
        assert n2["phone"] == "+61 4 11222 333" and n2["guardian_label"] == "Sam"  # remembered on the link
        lst = api.get(f"{BASE_URL}/api/family/incidents/{scent}/notes", params={"device_id": protected}).json()
        assert [x["phone"] for x in lst] == ["+61 4 11222 333"] * 2
