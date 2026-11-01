# "Delete My Apollo Data" — device-scoped inventory + complete purge.
import os
import requests

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://case-source-preview--3ijise2t.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


class Dev:
    def __init__(self):
        r = requests.post(f"{API}/devices/register", json={"platform": "web", "adapter_mode": "mock"}, headers={"User-Agent": "apollo-tests"})
        assert r.status_code == 201, r.text
        j = r.json(); self.id, self.token = j["device_id"], j["device_token"]
        self.s = requests.Session(); self.s.headers.update({"Content-Type": "application/json", "User-Agent": "apollo-tests", "X-Apollo-Raw": "1", "Authorization": f"Bearer {self.token}"})
    def get(self, p, **kw): return self.s.get(f"{API}{p}", **kw)
    def post(self, p, **kw): return self.s.post(f"{API}{p}", **kw)


def _cat(inv, key):
    return next((c["count"] for c in inv["categories"] if c["key"] == key), None)


class TestDeleteMyData:
    def test_inventory_counts_this_device_only(self):
        d = Dev()
        inv = d.get("/devices/data-inventory").json()
        assert inv["device_id"] == d.id
        assert inv["total"] == 0 and _cat(inv, "family") == 0
        # Seed a family pairing — lands in the "family" category.
        assert d.post("/family/pair", json={"device_id": d.id, "owner_name": "Mum"}).status_code == 200
        inv2 = d.get("/devices/data-inventory").json()
        assert _cat(inv2, "family") >= 1 and inv2["total"] >= 1

    def test_delete_erases_everything_and_kills_the_identity(self):
        d = Dev()
        d.post("/family/pair", json={"device_id": d.id, "owner_name": "Mum"})
        res = d.post("/devices/delete-data"); assert res.status_code == 200, res.text
        body = res.json()
        assert body["device_id"] == d.id and body["total"] >= 1 and body["removed"]["family"] >= 1
        # The identity is gone — the same token now fails closed.
        assert d.get("/devices/me").status_code == 401
        assert d.get("/devices/data-inventory").status_code == 401

    def test_delete_does_not_touch_another_device(self):
        victim, bystander = Dev(), Dev()
        bystander.post("/family/pair", json={"device_id": bystander.id, "owner_name": "Dad"})
        victim.post("/family/pair", json={"device_id": victim.id, "owner_name": "Mum"})
        assert victim.post("/devices/delete-data").status_code == 200
        # The bystander is unaffected: still authenticated and still has their family data.
        inv = bystander.get("/devices/data-inventory").json()
        assert _cat(inv, "family") >= 1
