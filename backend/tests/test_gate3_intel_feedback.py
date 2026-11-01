"""Gate 3 - Website & Browser Protection backend tests.

Covers:
- POST /api/intel/check with expand=true/false for shortener (bit.ly) and non-redirecting URL.
- POST /api/intel/check malicious URL expansion.
- POST /api/feedback validation.
"""
import os
import uuid

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") if os.environ.get("EXPO_PUBLIC_BACKEND_URL") else os.environ.get("EXPO_BACKEND_URL", "https://case-source-preview--3ijise2t.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


class TestIntelCheckExpand:
    """Redirect expansion / final destination judging (W04/W05)."""

    def test_shortener_expand_true(self, s):
        body = {"indicator_type": "url", "value": "https://bit.ly/3xyzabc", "expand": True}
        r = s.post(f"{API}/intel/check", json=body, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data.get("redirect_chain"), list)
        assert len(data["redirect_chain"]) >= 2, f"expected >=2 hosts, got {data['redirect_chain']}"
        assert data["redirect_chain"][0] == "bit.ly", data["redirect_chain"]
        assert data.get("final_url"), "final_url must be set when redirects occurred"
        assert data.get("verdict") == "clean", data.get("verdict")

    def test_shortener_expand_false(self, s):
        body = {"indicator_type": "url", "value": "https://bit.ly/3xyzabc", "expand": False}
        r = s.post(f"{API}/intel/check", json=body, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("redirect_chain") == []
        assert data.get("final_url") is None

    def test_known_malicious_expand_true(self, s):
        body = {"indicator_type": "url", "value": "http://testsafebrowsing.appspot.com/s/phishing.html", "expand": True}
        r = s.post(f"{API}/intel/check", json=body, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("verdict") == "malicious", data

    def test_non_redirecting_expand_true(self, s):
        body = {"indicator_type": "url", "value": "https://www.abc.net.au", "expand": True}
        r = s.post(f"{API}/intel/check", json=body, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        # No hop or a single-hop landing → redirect_chain empty and final_url null.
        assert data.get("redirect_chain") == [], data.get("redirect_chain")
        assert data.get("final_url") is None


class TestFeedback:
    def test_valid_feedback_created(self, s):
        body = {
            "device_id": "gate3test0001",
            "event_id": f"evt-{uuid.uuid4().hex[:10]}",
            "kind": "false_positive",
            "state": "barking",
            "host": "example.test",
            "sources": ["google_safe_browsing"],
            "note": "",
        }
        r = s.post(f"{API}/feedback", json=body, timeout=15)
        assert r.status_code == 201, r.text
        assert r.json() == {"received": True}

    def test_invalid_kind_422(self, s):
        body = {
            "device_id": "gate3test0001",
            "event_id": f"evt-{uuid.uuid4().hex[:10]}",
            "kind": "bogus",
            "state": "barking",
        }
        r = s.post(f"{API}/feedback", json=body, timeout=15)
        assert r.status_code == 422, r.text

    def test_missing_event_id_422(self, s):
        body = {"device_id": "gate3test0001", "kind": "false_positive", "state": "barking"}
        r = s.post(f"{API}/feedback", json=body, timeout=15)
        assert r.status_code == 422, r.text
