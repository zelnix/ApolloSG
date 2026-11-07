"""Apollo V1 backend regression tests.
Covers: health, intel status/check, device register, patrol events, trust, ask history.
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone

import pytest
import requests

BASE_URL = "https://tc-flyby-2fa--0hiznn9n.preview.emergentagent.com"
API = f"{BASE_URL}/api"

DEVICE_ID = f"testdev-{uuid.uuid4().hex[:12]}"


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def credentialed_ask_client():
    registration = requests.post(
        f"{API}/devices/register",
        json={"platform": "web", "adapter_mode": "mock", "app_version": "1.0.0", "locale": "en-AU"},
        headers={"User-Agent": "apollo-tests"},
        timeout=30,
    )
    registration.raise_for_status()
    body = registration.json()
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {body['device_token']}"})
    return session, body["device_id"]


# --- health ---
def test_health(api_client):
    r = api_client.get(f"{API}/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "apollo-v1"


# --- intel/status ---
def test_intel_status(api_client):
    r = api_client.get(f"{API}/intel/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "safe_browsing" in body
    assert body["safe_browsing"]["status"] in ("auth_error", "unreachable", "ok", "not_configured")
    assert body["blocklist"]["entries"] >= 4, f"expected >=4 blocklist entries, got {body['blocklist']}"


def _sb_ok(api_client) -> bool:
    return api_client.get(f"{API}/intel/status").json()["safe_browsing"]["status"] == "ok"


# --- device register ---
def test_device_register(api_client):
    payload = {"device_id": DEVICE_ID, "platform": "web", "adapter_mode": "mock", "app_version": "1.0.0"}
    # Registration is server-issued: the caller's device_id is ignored, a new id + one-time token come back (201).
    r = api_client.post(f"{API}/devices/register", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["device_id"] != DEVICE_ID and len(body["device_id"]) == 32
    assert len(body["device_token"]) >= 40 and body["registered"] is True
    # a second registration is a second identity, never "the same device again"
    r2 = api_client.post(f"{API}/devices/register", json=payload)
    assert r2.status_code == 201 and r2.json()["device_id"] != body["device_id"]


# --- intel/check malicious ---
def test_intel_check_malicious(api_client):
    body = {"indicator_type": "url", "value": "http://testsafebrowsing.appspot.com/s/phishing.html", "device_id": DEVICE_ID}
    r = api_client.post(f"{API}/intel/check", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["verdict"] == "malicious", data
    names = {s["name"]: s for s in data["sources"]}
    assert names["apollo_blocklist"]["status"] == "match"
    assert isinstance(data["cached"], bool)  # may be True on re-runs (cache persists in Mongo)


def test_intel_check_cached(api_client):
    body = {"indicator_type": "url", "value": "http://testsafebrowsing.appspot.com/s/phishing.html", "device_id": DEVICE_ID}
    r = api_client.post(f"{API}/intel/check", json=body)
    assert r.status_code == 200
    assert r.json()["cached"] is True


def test_intel_check_unknown(api_client):
    body = {"indicator_type": "url", "value": "https://www.abc.net.au", "device_id": DEVICE_ID}
    r = api_client.post(f"{API}/intel/check", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    # SB ok + blocklist clear -> clean/full; SB unavailable -> unknown/partial (truthful)
    if _sb_ok(api_client):
        assert data["verdict"] == "clean", data
        assert data["coverage"] == "full"
    else:
        assert data["verdict"] == "unknown", data
        assert data["coverage"] == "partial"


def test_intel_check_invalid_scheme(api_client):
    body = {"indicator_type": "url", "value": "javascript:alert(1)"}
    r = api_client.post(f"{API}/intel/check", json=body)
    assert r.status_code == 422, r.text


# --- patrol events ---
EVT_ID = f"evt-{uuid.uuid4().hex[:12]}"


def _patrol_payload(event_id=None, status="active", state="barking"):
    return {
        "event_id": event_id or EVT_ID,
        "device_id": DEVICE_ID,
        "category": "link",
        "state": state,
        "status": status,
        "headline": "Don't open testsafebrowsing.appspot.com",
        "what_happened": "You checked a link Apollo recognises as unsafe.",
        "why": ["On Apollo's managed threat list"],
        "what_to_do": "Delete the message and don't tap the link.",
        "indicator_host": "testsafebrowsing.appspot.com",
        "adapter_label": "MOCK adapter — simulated",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }


def test_patrol_upsert_and_idempotent(api_client):
    r1 = api_client.post(f"{API}/patrol/events", json=_patrol_payload())
    assert r1.status_code == 200, r1.text
    r2 = api_client.post(f"{API}/patrol/events", json=_patrol_payload())
    assert r2.status_code == 200
    # list should have exactly 1 with this event_id
    lst = api_client.get(f"{API}/patrol/events", params={"device_id": DEVICE_ID}).json()
    matching = [e for e in lst if e["event_id"] == EVT_ID]
    assert len(matching) == 1, f"expected 1, got {len(matching)}"


def test_patrol_patch(api_client):
    r = api_client.patch(
        f"{API}/patrol/events/{EVT_ID}",
        params={"device_id": DEVICE_ID},
        json={"status": "resolved", "state": "resting"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved"


def test_patrol_soft_delete(api_client):
    r = api_client.delete(f"{API}/patrol/events", params={"device_id": DEVICE_ID})
    assert r.status_code == 200, r.text
    lst = api_client.get(f"{API}/patrol/events", params={"device_id": DEVICE_ID}).json()
    assert lst == [], f"expected empty after soft delete, got {lst}"


# --- trust ---
TRUST_ID = f"trust-{uuid.uuid4().hex[:12]}"


def test_trust_add_list_revoke(api_client):
    payload = {
        "device_id": DEVICE_ID,
        "indicator_type": "url",
        "indicator_digest": "a" * 32,
        "indicator_host": "commbank-secure-login-verify.xyz",
        "trust_id": TRUST_ID,
    }
    r = api_client.post(f"{API}/trust", json=payload)
    assert r.status_code == 200, r.text
    lst = api_client.get(f"{API}/trust", params={"device_id": DEVICE_ID}).json()
    assert any(t["trust_id"] == TRUST_ID for t in lst)
    d = api_client.delete(f"{API}/trust/{TRUST_ID}", params={"device_id": DEVICE_ID})
    assert d.status_code == 200
    assert d.json()["revoked"] is True
    lst2 = api_client.get(f"{API}/trust", params={"device_id": DEVICE_ID}).json()
    assert not any(t["trust_id"] == TRUST_ID for t in lst2)


# --- ask stream (SSE) ---
@pytest.mark.credentialed_integration
def test_ask_stream_sse(credentialed_ask_client):
    ask_client, ask_device_id = credentialed_ask_client
    # clear history first
    ask_client.delete(f"{API}/ask/history", params={"device_id": ask_device_id})
    body = {"message": "What is phishing in one sentence?"}
    r = ask_client.post(f"{API}/ask/stream", json=body, stream=True, timeout=45)
    assert r.status_code == 200, r.text[:400]
    got_delta = False
    got_done = False
    got_error = False
    started = time.time()
    for line in r.iter_lines(decode_unicode=True):
        if not line:
            continue
        if line.startswith("data:"):
            payload = json.loads(line[5:].strip())
            if "delta" in payload:
                got_delta = True
            if payload.get("done"):
                got_done = True
                break
            if "error" in payload:
                got_error = True
                break
        if time.time() - started > 40:
            break
    r.close()
    assert not got_error, "Ask stream returned error event"
    assert got_delta, "No delta events received from SSE"
    assert got_done, "No done event received from SSE"


@pytest.mark.credentialed_integration
def test_ask_history(credentialed_ask_client):
    ask_client, ask_device_id = credentialed_ask_client
    r = ask_client.get(f"{API}/ask/history", params={"device_id": ask_device_id})
    assert r.status_code == 200
    hist = r.json()
    roles = {m["role"] for m in hist}
    assert "user" in roles, hist
    assert "higgins" in roles, hist
    # Regression: response_model_by_alias=False must be set so messages expose `id`
    # (not mongo `_id`), otherwise React FlatList/.map() key warnings appear on the Ask screen.
    for m in hist:
        assert "id" in m and m["id"], f"message missing usable 'id' field: {m}"
        assert "_id" not in m, f"raw mongo _id leaked into response: {m}"


# --- intel/check-batch (iteration 2) ---
def test_intel_check_batch_mixed(api_client):
    body = {
        "indicator_type": "url",
        "values": [
            "http://testsafebrowsing.appspot.com/s/phishing.html",  # blocklisted -> malicious
            "https://www.abc.net.au",                                 # unknown (partial)
            "javascript:alert(1)",                                    # invalid -> error
        ],
    }
    r = api_client.post(f"{API}/intel/check-batch", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list) and len(data) == 3, data
    by_val = {item["value"]: item for item in data}
    # blocklisted
    m = by_val["http://testsafebrowsing.appspot.com/s/phishing.html"]
    assert m["result"] is not None and m["result"]["verdict"] == "malicious", m
    assert not m.get("error")
    # clean when Safe Browsing is live, unknown when unavailable
    u = by_val["https://www.abc.net.au"]
    assert u["result"] is not None and u["result"]["verdict"] == ("clean" if _sb_ok(api_client) else "unknown"), u
    # invalid -> error field set, result None
    inv = by_val["javascript:alert(1)"]
    assert inv["result"] is None and inv["error"], inv
