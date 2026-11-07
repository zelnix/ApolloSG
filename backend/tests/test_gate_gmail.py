# Gmail read-only connection (Gate 1 add-on) — backend tests.
# Covers: /gmail/status (unconnected), /gmail/connect (authorization_url shape + open-redirect
# protection), /gmail/oauth/callback (bogus state), /gmail/scan (no connection), /gmail/connection DELETE
# (idempotent). Real Google OAuth consent CANNOT be automated here (requires human login) — that boundary
# is explicitly out of scope per review request.
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE_URL = (
    os.environ.get("EXPO_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "https://tc-flyby-2fa--0hiznn9n.preview.emergentagent.com"
).rstrip("/")
GMAIL_REDIRECT_BASE = os.environ["PUBLIC_API_BASE"].rstrip("/")


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def device_id():
    return f"TEST_gmail_{uuid.uuid4().hex[:12]}"


class TestGmailStatus:
    def test_status_before_connection(self, api, device_id):
        r = api.get(f"{BASE_URL}/api/gmail/status", params={"device_id": device_id}, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["connected"] is False
        assert data["configured"] is True
        assert data["oauth_redirect_uri"] == f"{GMAIL_REDIRECT_BASE}/api/gmail/oauth/callback"


class TestGmailConnect:
    def test_connect_returns_valid_authorization_url(self, api, device_id):
        r = api.get(
            f"{BASE_URL}/api/gmail/connect",
            params={"device_id": device_id, "app_redirect": "apollo://email"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        url = data["authorization_url"]
        assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        assert qs.get("client_id"), "client_id missing"
        assert qs["redirect_uri"][0] == f"{GMAIL_REDIRECT_BASE}/api/gmail/oauth/callback"
        assert qs["scope"][0] == "https://www.googleapis.com/auth/gmail.readonly"
        assert qs["access_type"][0] == "offline"
        assert "state" in qs and len(qs["state"][0]) > 10

    @pytest.mark.parametrize("bad_redirect", ["javascript://evil", "ftp://x", "evil://x"])
    def test_connect_rejects_invalid_redirect_scheme(self, api, device_id, bad_redirect):
        r = api.get(
            f"{BASE_URL}/api/gmail/connect",
            params={"device_id": device_id, "app_redirect": bad_redirect},
            timeout=15,
        )
        assert r.status_code == 400, f"expected 400 for {bad_redirect}, got {r.status_code}: {r.text}"

    def test_connect_missing_device_id_is_422(self, api):
        r = api.get(f"{BASE_URL}/api/gmail/connect", params={"app_redirect": "apollo://email"}, timeout=15)
        assert r.status_code == 422


class TestGmailCallback:
    def test_callback_bogus_state_returns_400_not_crash(self, api):
        r = api.get(
            f"{BASE_URL}/api/gmail/oauth/callback",
            params={"code": "x", "state": "doesnotexist"},
            timeout=15,
            allow_redirects=False,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"

    def test_callback_no_state_at_all_returns_400(self, api):
        r = api.get(f"{BASE_URL}/api/gmail/oauth/callback", params={"code": "x"}, timeout=15, allow_redirects=False)
        assert r.status_code == 400


class TestGmailScan:
    def test_scan_without_connection_returns_404(self, api, device_id):
        r = api.post(f"{BASE_URL}/api/gmail/scan", json={"device_id": device_id}, timeout=20)
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text}"
        assert "not connected" in r.json().get("detail", "").lower()


class TestGmailDisconnect:
    def test_disconnect_with_no_existing_connection_succeeds(self, api, device_id):
        r = api.delete(f"{BASE_URL}/api/gmail/connection", params={"device_id": device_id}, timeout=15)
        assert r.status_code == 204, f"expected 204, got {r.status_code}: {r.text}"
        assert r.content in (b"", None)

    def test_status_still_disconnected_after_delete(self, api, device_id):
        r = api.get(f"{BASE_URL}/api/gmail/status", params={"device_id": device_id}, timeout=15)
        assert r.status_code == 200
        assert r.json()["connected"] is False
