# Hardening Gate step 2 — device authentication. The backend never trusts a caller-supplied device_id.
import os, uuid
import pytest, requests

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://case-source-preview--3ijise2t.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


class Dev:
    """An authenticated device: registers on creation, sends its own bearer on every call."""
    def __init__(self):
        r = requests.post(f"{API}/devices/register", json={"platform": "web", "adapter_mode": "mock"}, headers={"User-Agent": "apollo-tests"})
        assert r.status_code == 201, r.text
        j = r.json()
        self.id, self.token = j["device_id"], j["device_token"]
        assert len(self.token) >= 40 and "token_hash" not in j
        self.s = requests.Session(); self.s.headers.update({"Content-Type": "application/json", "User-Agent": "apollo-tests", "X-Apollo-Raw": "1", "Authorization": f"Bearer {self.token}"})
    def get(self, p, **kw): return self.s.get(f"{API}{p}", **kw)
    def post(self, p, **kw): return self.s.post(f"{API}{p}", **kw)
    def put(self, p, **kw): return self.s.put(f"{API}{p}", **kw)
    def patch(self, p, **kw): return self.s.patch(f"{API}{p}", **kw)


# X-Apollo-Raw opts out of the conftest auth shim: these requests must reach the API exactly as written.
anon = requests.Session(); anon.headers.update({"Content-Type": "application/json", "User-Agent": "apollo-tests", "X-Apollo-Raw": "1"})


class TestCredentialLifecycle:
    def test_register_is_server_issued_and_unique(self):
        a, b = Dev(), Dev()
        assert a.id != b.id and a.token != b.token and len(a.id) == 32
        assert a.get("/devices/me").json()["device_id"] == a.id

    def test_missing_or_malformed_credentials_fail_closed_401(self):
        d = Dev()
        tampered = d.token[:-1] + ("0" if d.token[-1] != "0" else "1")
        for headers in ({}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer short"}, {"Authorization": "Bearer " + "x" * 200}, {"Authorization": f"Bearer {tampered}"}):
            r = anon.get(f"{API}/patrol/events", params={"device_id": d.id}, headers=headers)
            assert r.status_code == 401, (headers, r.status_code)
            assert r.headers.get("www-authenticate") == "Bearer"

    def test_rotation_is_atomic_and_old_token_dies(self):
        d = Dev()
        old = d.token
        r = d.post("/devices/token/rotate"); assert r.status_code == 200
        new = r.json()["device_token"]; assert new != old and r.json()["device_id"] == d.id
        assert anon.get(f"{API}/devices/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401
        assert anon.get(f"{API}/devices/me", headers={"Authorization": f"Bearer {new}"}).status_code == 200
        # second rotation with the dead token must fail closed
        assert anon.post(f"{API}/devices/token/rotate", headers={"Authorization": f"Bearer {old}"}).status_code == 401

    def test_revocation(self):
        d = Dev()
        assert d.post("/devices/revoke").status_code == 204
        assert d.get("/devices/me").status_code == 401
        assert d.post("/devices/heartbeat", json={"platform": "web", "adapter_mode": "mock"}).status_code == 401

    def test_public_paths_stay_public(self):
        assert anon.get(f"{API}/health").status_code == 200
        assert anon.get(f"{API}/intel/status").status_code == 200
        # AR-15: /voice was owner-scoped audio; route removed — nonexistent routes return 404
        assert anon.get(f"{API}/voice/doesnotexist.wav").status_code in (401, 404)


class TestOwnershipEnforcement:
    def test_device_id_in_query_path_and_body_must_match_token(self):
        me, other = Dev(), Dev()
        assert me.get("/patrol/events", params={"device_id": me.id}).status_code == 200
        assert me.get("/patrol/events", params={"device_id": other.id}).status_code == 403
        assert me.get(f"/devices/{other.id}/settings").status_code == 403
        assert me.get(f"/devices/{me.id}/settings").status_code == 200
        assert me.post("/family/pair", json={"device_id": other.id, "owner_name": "x"}).status_code == 403
        assert me.post("/family/pair", json={"device_id": me.id, "owner_name": "x"}).status_code == 200
        # push registration keys on user_id — same rule
        assert me.post("/register-push", json={"user_id": other.id, "platform": "ios", "device_token": "ExponentPushToken[x]"}).status_code == 403

    def test_family_flow_with_two_authenticated_devices(self):
        protected, guardian, stranger = Dev(), Dev(), Dev()
        code = protected.post("/family/pair", json={"device_id": protected.id, "owner_name": "Mum"}).json()["code"]
        assert guardian.post("/family/link", json={"device_id": guardian.id, "code": code}).status_code == 200
        scent = f"sc{uuid.uuid4().hex[:8]}"
        r = protected.post("/family/incidents/share", json={"device_id": protected.id, "scent_id": scent, "headline": "h", "state": "barking", "events": [], "steps": [{"id": "s0", "text": "t"}], "done": []})
        assert r.json()["shared_with"] == 1
        # guardian reads with their own identity; a stranger with a valid token but no link gets nothing / 404
        assert guardian.get(f"/family/incidents/{scent}", params={"device_id": guardian.id}).status_code == 200
        assert stranger.get(f"/family/incidents/{scent}", params={"device_id": stranger.id}).status_code == 404
        # guardian cannot impersonate the protected person to post progress
        assert guardian.patch(f"/family/incidents/{scent}/progress", json={"device_id": protected.id, "done": ["s0"], "resolved": False}).status_code == 403
        # note + weekly still work for the real guardian
        assert guardian.post(f"/family/incidents/{scent}/notes", json={"device_id": guardian.id, "kind": "here", "from_name": "Sam"}).status_code == 201
        assert guardian.get("/family/weekly", params={"device_id": guardian.id}).json()[0]["owner_name"] == "Mum"
        assert stranger.get("/family/weekly", params={"device_id": stranger.id}).json() == []

    def test_legacy_device_ids_cannot_be_claimed(self):
        # Registration no longer accepts a device_id; supplying one is ignored and a server id is issued instead.
        r = anon.post(f"{API}/devices/register", json={"device_id": "legacy-device-0001", "platform": "web", "adapter_mode": "mock"})
        assert r.status_code == 201 and r.json()["device_id"] != "legacy-device-0001"


def _db(coro_factory):
    """Run a DB operation against the live database (test-only state manipulation, e.g. forcing expiry).
    Uses a fresh motor client per call so successive asyncio.run() loops don't share a closed client."""
    import asyncio, os, sys
    sys.path.insert(0, "/app/backend")
    from datetime import timedelta
    from core import db as core_db
    from motor.motor_asyncio import AsyncIOMotorClient
    async def main():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            ns = type("NS", (), {"db": client[core_db.db.name], "now_utc": core_db.now_utc, "timedelta": timedelta})
            return await coro_factory(ns)
        finally:
            client.close()
    return asyncio.run(main())


class TestTokenLifecycle:
    def test_expired_token_is_rejected_and_recovery_is_a_new_identity(self):
        # Force expiry directly in Mongo (test-only), then confirm 401 and that recovery = fresh registration (new id).
        d = Dev()
        _db(lambda server: server.db.devices.update_one({"device_id": d.id}, {"$set": {"token_expires_at": server.now_utc() - server.timedelta(seconds=1)}}))
        assert d.get("/devices/me").status_code == 401
        fresh = Dev(); assert fresh.id != d.id
        # the expired device's data is NOT reachable from the new identity
        assert fresh.get("/patrol/events", params={"device_id": d.id}).status_code == 403

    def test_concurrent_rotation_only_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        d = Dev()
        with ThreadPoolExecutor(max_workers=4) as ex:
            results = list(ex.map(lambda _: anon.post(f"{API}/devices/token/rotate", headers={"Authorization": f"Bearer {d.token}"}).status_code, range(4)))
        assert results.count(200) == 1 and results.count(401) == 3, results

    def test_revoked_device_never_regains_access(self):
        d = Dev(); other = Dev()
        d.post("/family/pair", json={"device_id": d.id, "owner_name": "Mum"})
        assert d.post("/devices/revoke").status_code == 204
        assert d.post("/devices/token/rotate").status_code == 401  # cannot rotate back to life
        assert d.get("/family/links", params={"device_id": d.id}).status_code == 401
        assert other.get("/family/links", params={"device_id": d.id}).status_code == 403  # nor can anyone else read it
