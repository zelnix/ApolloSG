# Test-only auth shim (Hardening Gate step 2).
# The API now requires a server-issued bearer token and rejects caller-supplied device_ids that don't match it.
# The older suites were written against the pre-auth API and use arbitrary device_id strings. Rather than rewrite
# ~20 files at once, this conftest transparently: (1) registers a real device the first time a legacy id is seen,
# (2) rewrites that id to the real one in path/query/body, (3) attaches the right bearer token, and (4) maps real
# ids back to the legacy ones in response bodies so the tests' equality checks still hold.
# Authentication itself is tested WITHOUT this shim in test_device_auth.py (it uses requests.post directly with
# explicit headers and its own ids, which are never rewritten because they are real server ids).
import asyncio, fcntl, json, os, re, tempfile, time
from pathlib import Path

import pytest, requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
os.environ["APOLLO_FORBID_PROVIDER_CALLS"] = "1"
BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
# One map per pytest run (all xdist workers of a run share PYTEST_XDIST_TESTRUNUID).
_SHARED_MAP = os.path.join(tempfile.gettempdir(), f"apollo_shim_ids_{os.environ.get('PYTEST_XDIST_TESTRUNUID') or os.getppid()}.json")
ID_KEYS = ("device_id", "user_id", "protected_device_id", "guardian_device_id")
_real_by_legacy: dict[str, tuple[str, str]] = {}  # legacy id -> (real id, token)
_legacy_by_real: dict[str, str] = {}
_orig_request = requests.Session.request
_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "credentialed_integration: requires an explicitly enabled owner-key/provider integration run",
    )


def pytest_collection_modifyitems(config, items):
    del config
    if os.getenv("APOLLO_RUN_CREDENTIALED_INTEGRATION") == "1":
        return
    skip = pytest.mark.skip(reason="credentialed integration; run with APOLLO_RUN_CREDENTIALED_INTEGRATION=1")
    for item in items:
        if "credentialed_integration" in item.keywords:
            item.add_marker(skip)


def _real(legacy: str) -> tuple[str, str]:
    if legacy in _real_by_legacy:
        return _real_by_legacy[legacy]
    if _ID_RE.match(legacy) and legacy in _legacy_by_real.values():
        return next(v for k, v in _real_by_legacy.items() if v[0] == legacy)
    # xdist runs classes of one module on different workers (loadscope). Their legacy→real maps must agree, or a
    # pairing made in one class is invisible to the next (DEVICE_A would be two different real devices). The map is
    # therefore shared through a per-run file under an exclusive lock.
    with open(_SHARED_MAP, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        try:
            shared = json.loads(fh.read() or "{}")
        except ValueError:
            shared = {}
        if legacy not in shared:
            r = None
            for attempt in range(3):
                try:
                    r = _orig_request(requests.Session(), "POST", f"{BASE_URL}/api/devices/register",
                        json={"platform": "web", "adapter_mode": "mock"}, headers={"User-Agent": "apollo-tests"}, timeout=30)
                    if r.status_code not in (502, 503, 504):
                        break
                except requests.RequestException:
                    if attempt == 2:
                        raise
                time.sleep(0.5 * (attempt + 1))
            assert r is not None
            r.raise_for_status()
            j = r.json()
            shared[legacy] = [j["device_id"], j["device_token"]]
            fh.seek(0); fh.truncate(); fh.write(json.dumps(shared))
        real, tok = shared[legacy]
    _real_by_legacy[legacy] = (real, tok); _legacy_by_real[real] = legacy
    return _real_by_legacy[legacy]


def _shimmed_request(self, method, url, **kw):
    hdrs = {**self.headers, **(kw.get("headers") or {})}
    if "/api/" not in url or url.endswith("/devices/register") or "Authorization" in hdrs or "X-Apollo-Raw" in hdrs:
        return _orig_request(self, method, url, **kw)
    caller = None
    body = kw.get("json")
    if isinstance(body, dict):
        for k in ID_KEYS:
            if isinstance(body.get(k), str):
                real, tok = _real(body[k]); body[k] = real
                if k in ("device_id", "user_id"): caller = tok
    params = kw.get("params")
    if isinstance(params, dict):
        for k in ID_KEYS:
            if isinstance(params.get(k), str):
                real, tok = _real(params[k]); params[k] = real
                if k == "device_id": caller = tok
    m = re.search(r"/api/devices/([^/]+)/settings", url)
    if m:
        real, tok = _real(m.group(1)); url = url.replace(m.group(1), real); caller = tok
    if caller is None:  # authenticated call with no id → any real device will do
        caller = _real("__anonymous_caller__")[1]
    if caller:
        kw["headers"] = {**(kw.get("headers") or {}), "Authorization": f"Bearer {caller}"}
    resp = _orig_request(self, method, url, **kw)
    if resp.content and _legacy_by_real:
        text = resp.content.decode("utf-8", "ignore")
        for real, legacy in _legacy_by_real.items():
            text = text.replace(real, legacy)
        resp._content = text.encode("utf-8")
    return resp


@pytest.fixture(autouse=True, scope="session")
def _install_auth_shim():
    requests.Session.request = _shimmed_request
    yield
    requests.Session.request = _orig_request


@pytest.fixture(autouse=True)
def _forbid_live_gemini(monkeypatch):
    """Fail inside the test process before a broken fixture can call Gemini.

    Preview deployment: the preview dispatch answers generate(), so let it through — tests need to
    verify the full preview path. Otherwise block every call to prevent accidental billing.
    """
    from services.higgins import provider

    if provider.get_provider_mode() == "preview":
        # Preview mode: the preview dispatch handles generate() calls.
        # Don't block it — tests need to verify the full preview path works.
        return

    async def blocked(*_args, **_kwargs):
        raise AssertionError("Live Gemini/provider calls are prohibited in bounded tests")

    monkeypatch.setattr(provider, "generate", blocked)
    monkeypatch.setattr(provider, "generate_json", blocked)


@pytest.fixture(autouse=True)
def _flyby_offline(monkeypatch):
    """TC Hawkeye's direct-source lookups (Google Web Risk, RDAP, advisories) and its targeted Google Search reach the
    network. Bounded tests run them offline: every lookup reports unavailable, so investigations reach Magnum DI
    exactly as before. TC Hawkeye's own tests replace these with fixed results."""
    from services.higgins.tc_hawkeye import official, search

    async def unavailable(*_args, **_kwargs):
        return None

    async def no_advisories(*_args, **_kwargs):
        return []

    async def search_unavailable(checks, **_kwargs):
        return {"answers": {c.id: {"status": "UNAVAILABLE", "fact": "", "sources": []} for c in checks if c.question},
                "calls": 0, "queries": 0, "cacheHits": 0, "tokens": {"input": 0, "output": 0}, "simulated": False,
                "model": None, "status": "unavailable"}

    monkeypatch.setattr(official, "lookup_url", unavailable)
    monkeypatch.setattr(official, "lookup_domain", unavailable)
    monkeypatch.setattr(official, "advisories", no_advisories)
    monkeypatch.setattr(search, "run", search_unavailable)



# Motor event-loop compatibility: asyncio_default_fixture_loop_scope = session in pytest.ini
# keeps one loop per xdist worker for the whole test session, so Motor's AsyncIOMotorClient
# never hits "Event loop is closed" on subsequent tests.

