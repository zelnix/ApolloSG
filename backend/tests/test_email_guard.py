"""Email Guard feature backend tests.

Covers:
- POST /api/message/analyse now returns redirect_chain/final_url/domain_info per URL (new).
- POST /api/intel/check (expand=true/false) regression -- must behave identically to before the
  assess_indicator() refactor.
- services.gmail._extract_content() pure-function unit test for anchor extraction (text vs href
  mismatch source data).
"""
import base64
import os

import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL", "https://tc-flyby-2fa--0hiznn9n.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


# --- /api/message/analyse enrichment ------------------------------------------
class TestMessageAnalyseEnrichment:
    def test_google_redirect_has_domain_info_and_chain_fields_present(self, s):
        body = {
            "device_id": "emailguard0001",
            "text": "check this link please",
            "urls": ["https://google.com"],
            "local_state": "resting",
            "second_opinion": False,
        }
        r = s.post(f"{API}/message/analyse", json=body, timeout=45)
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["urls"]) == 1
        u0 = data["urls"][0]
        # New fields must be present in the shape (even if empty/None for a non-redirecting case)
        for k in ("redirect_chain", "final_url", "domain_info"):
            assert k in u0, f"missing new field {k} in {u0}"
        assert isinstance(u0["redirect_chain"], list)
        # domain_info should be populated (RDAP lookup for google.com)
        assert u0["domain_info"] is not None, "domain_info should be populated for google.com"
        assert "registrar" in u0["domain_info"]

    def test_known_malicious_url_still_flagged_with_new_fields(self, s):
        body = {
            "device_id": "emailguard0001",
            "text": "check this",
            "urls": ["http://testsafebrowsing.appspot.com/s/phishing.html"],
            "local_state": "growling",
            "second_opinion": False,
        }
        r = s.post(f"{API}/message/analyse", json=body, timeout=45)
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["urls"]) == 1
        u0 = data["urls"][0]
        assert u0["verdict"] == "malicious"
        assert "redirect_chain" in u0 and "domain_info" in u0

    def test_multiple_urls_concurrent_ok(self, s):
        body = {
            "device_id": "emailguard0001",
            "text": "two links",
            "urls": ["https://google.com", "https://www.abc.net.au"],
            "local_state": "resting",
            "second_opinion": False,
        }
        r = s.post(f"{API}/message/analyse", json=body, timeout=45)
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["urls"]) == 2
        hosts = {u["host"] for u in data["urls"]}
        assert "google.com" in hosts
        assert "www.abc.net.au" in hosts


# --- /api/intel/check regression (assess_indicator refactor) -------------------
class TestIntelCheckRegression:
    def test_clean_domain_expand_false(self, s):
        body = {"indicator_type": "url", "value": "https://www.abc.net.au", "expand": False}
        r = s.post(f"{API}/intel/check", json=body, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["verdict"] in ("clean", "unknown")
        assert data["redirect_chain"] == []
        assert data["final_url"] is None
        assert isinstance(data["sources"], list) and len(data["sources"]) >= 1

    def test_clean_domain_expand_true_with_domain_info(self, s):
        body = {"indicator_type": "url", "value": "https://google.com", "expand": True}
        r = s.post(f"{API}/intel/check", json=body, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["verdict"] == "clean"
        assert data.get("domain_info") is not None
        assert "registrar" in data["domain_info"]

    def test_malicious_domain_expand_true(self, s):
        body = {"indicator_type": "url", "value": "http://testsafebrowsing.appspot.com/s/phishing.html", "expand": True}
        r = s.post(f"{API}/intel/check", json=body, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["verdict"] == "malicious"

    def test_domain_indicator_type_expand_ignored(self, s):
        body = {"indicator_type": "domain", "value": "google.com", "expand": True}
        r = s.post(f"{API}/intel/check", json=body, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["redirect_chain"] == []
        assert data["final_url"] is None


# --- services.gmail._extract_content() pure function ---------------------------
class TestGmailExtractContent:
    def test_anchor_mismatch_extracted_from_synthetic_message(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from services.gmail import _extract_content

        html = (
            "<html><body><p>Hello,</p>"
            "<p>Please confirm your account at "
            "<a href='https://evil-domain.ru/x'>paypal.com</a></p>"
            "</body></html>"
        )
        encoded = base64.urlsafe_b64encode(html.encode()).decode().rstrip("=")
        message = {
            "payload": {
                "mimeType": "text/html",
                "headers": [{"name": "Subject", "value": "Test"}],
                "body": {"data": encoded},
            }
        }
        text, anchors = _extract_content(message)
        assert isinstance(text, str)
        assert len(anchors) == 1, anchors
        assert anchors[0]["text"] == "paypal.com"
        assert anchors[0]["href"] == "https://evil-domain.ru/x"

    def test_multipart_message_with_plain_and_html(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from services.gmail import _extract_content

        plain = "Please confirm your account."
        html = "<html><body><a href='https://legit.com/path'>legit.com</a></body></html>"
        plain_b64 = base64.urlsafe_b64encode(plain.encode()).decode().rstrip("=")
        html_b64 = base64.urlsafe_b64encode(html.encode()).decode().rstrip("=")
        message = {
            "payload": {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": plain_b64}},
                    {"mimeType": "text/html", "body": {"data": html_b64}},
                ],
            }
        }
        text, anchors = _extract_content(message)
        assert "confirm your account" in text
        assert len(anchors) == 1
        assert anchors[0]["href"] == "https://legit.com/path"
        assert anchors[0]["text"] == "legit.com"

    def test_no_html_part_no_anchors(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from services.gmail import _extract_content

        plain = "Just plain text, no links here."
        plain_b64 = base64.urlsafe_b64encode(plain.encode()).decode().rstrip("=")
        message = {"payload": {"mimeType": "text/plain", "body": {"data": plain_b64}}}
        text, anchors = _extract_content(message)
        assert "plain text" in text
        assert anchors == []
