# Hardening Gate step 3 — backend failure contracts.
# "Unknown never becomes safe": every degraded source path (timeout, auth error, malformed answer, stale cache) must end
# in an honest `unavailable` / `unknown` — never in `clear` / `clean`. Unit tests import services.intel directly and stub httpx;
# the stale-cache test goes through the live API (with the conftest auth shim) after planting an expired cache row.
import asyncio, os, sys, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx, pytest, requests
from dotenv import load_dotenv
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from services import intel as server  # noqa: E402  (the module that owns the Safe Browsing lookup)

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://tc-flyby-2fa--0hiznn9n.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
S = server.IntelSource


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Resp:
    def __init__(self, status=200, body="{}", json_exc=None):
        self.status_code, self._body, self._json_exc = status, body, json_exc
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=httpx.Request("POST", "x"), response=httpx.Response(self.status_code))
    def json(self):
        if self._json_exc:
            raise self._json_exc
        return self._body


class _Client:
    """Stand-in for httpx.AsyncClient: returns a canned response or raises."""
    def __init__(self, *_, **__):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        return False
    async def post(self, *_, **__):
        if isinstance(_Client.next, Exception):
            raise _Client.next
        return _Client.next
    next = None


@pytest.fixture
def sb(monkeypatch):
    monkeypatch.setattr(server, "SAFE_BROWSING_API_KEY", "test-key")
    monkeypatch.setattr(server.httpx, "AsyncClient", _Client)
    server._sb_probe.update(status=None, checked_at=None, detail="")
    def set_next(v):
        _Client.next = v
    return set_next


class TestCombine:
    def test_all_clear_is_clean_full(self):
        assert server.combine([S(name="a", status="clear", detail=""), S(name="b", status="clear", detail="")]) == ("clean", [], "full")

    def test_any_unavailable_source_forbids_clean(self):
        v, _, cov = server.combine([S(name="a", status="clear", detail=""), S(name="b", status="unavailable", detail="")])
        assert (v, cov) == ("unknown", "partial")

    def test_everything_down_is_unknown_none(self):
        v, _, cov = server.combine([S(name="a", status="unavailable", detail=""), S(name="b", status="not_configured", detail="")])
        assert (v, cov) == ("unknown", "none")

    def test_match_survives_a_degraded_source(self):
        v, threats, cov = server.combine([S(name="a", status="match", detail="", threat_types=["MALWARE"]), S(name="b", status="unavailable", detail="")])
        assert (v, threats, cov) == ("malicious", ["MALWARE"], "partial")


class TestSafeBrowsingDegradation:
    def test_timeout_is_unavailable(self, sb):
        sb(httpx.ReadTimeout("slow"))
        src, exp = run(server.safe_browsing_lookup("https://example.org/"))
        assert src.status == "unavailable" and exp is None and server._sb_probe["status"] == "unreachable"

    def test_auth_error_is_unavailable_and_short_circuits(self, sb):
        sb(_Resp(401))
        assert run(server.safe_browsing_lookup("https://example.org/"))[0].status == "unavailable"
        sb(_Resp(200, {"matches": []}))  # would be "clear" — but the key is known-bad for 10 minutes, so still unavailable
        assert run(server.safe_browsing_lookup("https://example.org/"))[0].status == "unavailable"

    def test_unreadable_json_is_unavailable(self, sb):
        sb(_Resp(200, json_exc=ValueError("not json")))
        assert run(server.safe_browsing_lookup("https://example.org/"))[0].status == "unavailable"

    @pytest.mark.parametrize("body", [[], "ok", {"matches": "yes"}, 42])
    def test_wrong_shape_is_unavailable_not_clear(self, sb, body):
        sb(_Resp(200, body))
        assert run(server.safe_browsing_lookup("https://example.org/"))[0].status == "unavailable"

    def test_5xx_is_unavailable(self, sb):
        sb(_Resp(503))
        assert run(server.safe_browsing_lookup("https://example.org/"))[0].status == "unavailable"

    def test_garbage_inside_matches_does_not_crash(self, sb):
        sb(_Resp(200, {"matches": ["junk", {"threatType": "MALWARE", "cacheDuration": "abc"}]}))
        src, exp = run(server.safe_browsing_lookup("https://example.org/"))
        assert src.status == "match" and src.threat_types == ["MALWARE"] and exp is not None

    def test_well_formed_clear_is_clear(self, sb):
        sb(_Resp(200, {"matches": []}))
        assert run(server.safe_browsing_lookup("https://example.org/"))[0].status == "clear"


class TestStaleCacheNeverServedAsFresh:
    def test_expired_cache_row_is_ignored(self):
        url = f"https://stale-{uuid.uuid4().hex[:10]}.example.org/"
        dg = server.digest(server.sanitize_url(url)[0])
        mongo = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        mongo.reputation_cache.replace_one({"indicator_digest": dg}, {"indicator_digest": dg, "verdict": "clean", "threat_types": [], "sources": [{"name": "apollo_blocklist", "status": "clear", "detail": "", "threat_types": []}],
                                                                        "coverage": "full", "checked_at": old, "expires_at": old + timedelta(minutes=5)}, upsert=True)
        r = requests.post(f"{API}/intel/check", json={"indicator_type": "url", "value": url, "device_id": "stale-cache-tester"}, headers={"User-Agent": "apollo-tests"})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["cached"] is False, "an expired cache row was served as a fresh verdict"
        assert datetime.fromisoformat(j["checked_at"].replace("Z", "+00:00")) > old + timedelta(hours=1)
        mongo.reputation_cache.delete_one({"indicator_digest": dg})


class TestHttpFailureClasses:
    def test_malformed_request_is_a_4xx_not_a_5xx(self):
        r = requests.post(f"{API}/intel/check", json={"indicator_type": "url", "value": 12, "device_id": "failure-tester"}, headers={"User-Agent": "apollo-tests"})
        assert r.status_code == 422

    def test_public_health_needs_no_credential(self):
        r = requests.get(f"{API}/health", headers={"User-Agent": "apollo-tests", "X-Apollo-Raw": "1"})
        assert r.status_code == 200 and r.json()["status"] == "ok"
