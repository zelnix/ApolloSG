"""Iteration 30 — Device Auth Hardening Gate step 2 — Playwright E2E on web preview.
Focus: (1) onboarding stores identity in apollo.device.identity.v2, (2) every /api/* request from the app
carries Authorization: Bearer, (3) token rotation from API → next app call 401 → Home shows identity-reset-card
with identity-reset-register button and does NOT silently re-register, (4) tap identity-reset-register → new
identity registered → deviceId differs, (5) regression: Guard tab renders 'guarding what he can', /family loads.
Also performs API-level 401/403 checks in parallel via httpx.
"""
import asyncio
import json
import os
import httpx
from playwright.async_api import async_playwright

BASE = os.environ.get("EXPO_BACKEND_URL", "https://case-source-preview--3ijise2t.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
HDR = {"User-Agent": "apollo-e2e", "Content-Type": "application/json"}


def register():
    r = httpx.post(f"{API}/devices/register", json={"platform": "web", "adapter_mode": "mock"}, headers=HDR, timeout=15.0)
    r.raise_for_status()
    return r.json()


async def onboard(ctx, label):
    page = await ctx.new_page()
    page.on("console", lambda m: print(f"[{label}] CONSOLE {m.type}: {m.text}") if m.type in ("error", "warning") else None)
    await page.set_viewport_size({"width": 390, "height": 844})
    api_calls = []
    page.on("request", lambda r: api_calls.append((r.method, r.url, r.headers.get("authorization"))) if "/api/" in r.url else None)
    responses = []
    page.on("response", lambda r: responses.append((r.status, r.url)) if "/api/" in r.url else None)
    await page.goto(BASE, wait_until="domcontentloaded")
    await page.wait_for_selector('[data-testid="onboarding-start-button"]', timeout=20000)
    await page.click('[data-testid="onboarding-start-button"]', force=True)
    await page.wait_for_selector('[data-testid="disclosure-accept-button"]', timeout=10000)
    await page.click('[data-testid="disclosure-accept-button"]', force=True)
    await page.wait_for_selector('[data-testid="apollo-state-label"]', timeout=20000)
    identity_raw = await page.evaluate("() => window.localStorage.getItem('apollo.device.identity.v2')")
    if not identity_raw:
        raise RuntimeError(f"[{label}] identity not in localStorage")
    identity = json.loads(identity_raw)
    if isinstance(identity, str):
        identity = json.loads(identity)
    print(f"[{label}] identity: deviceId={identity['deviceId'][:8]}… tokenLen={len(identity['token'])} expiresAt={identity.get('expiresAt')}")
    return page, identity, api_calls, responses


async def main():
    results = {"passed": [], "failed": [], "notes": []}

    def ok(name):
        print(f"PASS {name}")
        results["passed"].append(name)

    def fail(name, detail=""):
        print(f"FAIL {name} — {detail}")
        results["failed"].append(f"{name}: {detail}")

    async with async_playwright() as p:
        browser = await p.chromium.launch()

        # ---- A onboard ----
        ctxA = await browser.new_context()
        pageA, idA, callsA, respA = await onboard(ctxA, "A")

        # Verify every /api/* call from app carries Authorization (except public register/heartbeat POST)
        missing = [c for c in callsA if not c[2] and "/devices/register" not in c[1]]
        if missing:
            fail("A/every-call-has-bearer", f"{len(missing)} calls without Authorization: {missing[:3]}")
        else:
            ok("A/every-call-has-bearer")

        bad = [r for r in respA if r[0] in (401, 403)]
        if bad:
            fail("A/no-401-403-during-normal-use", f"{bad[:5]}")
        else:
            ok("A/no-401-403-during-normal-use")

        # ---- Cross-device 403 substitution via API ----
        B = register()
        tokA, tokB = idA["token"], B["device_token"]
        idB_id = B["device_id"]

        r = httpx.get(f"{API}/patrol/events", params={"device_id": idA["deviceId"]}, headers={**HDR, "Authorization": f"Bearer {tokB}"}, timeout=10.0)
        (ok if r.status_code == 403 else fail)("B-token uses A's device_id (patrol/events) → 403", f"got {r.status_code}")
        r = httpx.patch(f"{API}/family/incidents/none/progress", json={"device_id": idA["deviceId"], "done": [], "resolved": False}, headers={**HDR, "Authorization": f"Bearer {tokB}"}, timeout=10.0)
        (ok if r.status_code == 403 else fail)("B-token PATCH family incident with A id → 403", f"got {r.status_code}")
        r = httpx.post(f"{API}/register-push", json={"user_id": idA["deviceId"], "platform": "ios", "device_token": "ExponentPushToken[x]"}, headers={**HDR, "Authorization": f"Bearer {tokB}"}, timeout=10.0)
        (ok if r.status_code == 403 else fail)("B-token register-push with A id → 403", f"got {r.status_code}")
        r = httpx.get(f"{API}/patrol/events", params={"device_id": idA["deviceId"]}, headers=HDR, timeout=10.0)
        (ok if r.status_code == 401 and r.headers.get("www-authenticate") == "Bearer" else fail)("No auth → 401 with WWW-Authenticate: Bearer", f"status={r.status_code} www={r.headers.get('www-authenticate')}")

        # ---- Public paths still work ----
        r = httpx.get(f"{API}/health", headers=HDR, timeout=10.0)
        (ok if r.status_code == 200 else fail)("public /api/health 200", f"{r.status_code}")
        r = httpx.get(f"{API}/intel/status", headers=HDR, timeout=10.0)
        (ok if r.status_code == 200 else fail)("public /api/intel/status 200", f"{r.status_code}")
        r = httpx.post(f"{API}/devices/register", json={"platform": "web", "adapter_mode": "mock"}, headers=HDR, timeout=10.0)
        (ok if r.status_code == 201 else fail)("public POST /api/devices/register 201", f"{r.status_code}")

        # ---- TOKEN ROTATION MID-SESSION on A ----
        # Rotate A's token via API. Do NOT update localStorage. Then trigger a navigation → next API call → 401.
        r = httpx.post(f"{API}/devices/token/rotate", headers={**HDR, "Authorization": f"Bearer {tokA}"}, timeout=10.0)
        (ok if r.status_code == 200 else fail)("rotate A token 200", f"{r.status_code}")

        # Force a fresh /api call from the app (navigate to /family which fetches /family/links)
        await pageA.goto(f"{BASE}/family", wait_until="domcontentloaded")
        # Wait for identity-reset-card
        try:
            await pageA.wait_for_selector('[data-testid="identity-reset-card"]', timeout=15000)
            ok("identity-reset-card appears on 401")
        except Exception as e:
            fail("identity-reset-card appears on 401", str(e))
            await pageA.screenshot(path="/tmp/e2e_rotation_fail.png", quality=40, full_page=False)

        # Verify why text + register button
        why_visible = await pageA.is_visible('[data-testid="identity-reset-why"]')
        btn_visible = await pageA.is_visible('[data-testid="identity-reset-register"]')
        (ok if why_visible and btn_visible else fail)("identity-reset-why + register button present", f"why={why_visible} btn={btn_visible}")

        # Verify localStorage identity is cleared (or null) and NO auto POST to /devices/register happened
        stored = await pageA.evaluate("() => window.localStorage.getItem('apollo.device.identity.v2')")
        (ok if stored in (None, "null", "") else fail)("localStorage identity cleared after 401", f"got {stored!r}")

        # Snapshot register-count BEFORE tap
        reg_calls_before = 0
        pageA.on("request", lambda r: None)  # keep noop; we'll count via a fresh listener
        register_hits = []
        pageA.on("request", lambda r: register_hits.append(r.url) if r.url.endswith("/api/devices/register") and r.method == "POST" else None)
        # Wait briefly to confirm no auto-registration
        await pageA.wait_for_timeout(2000)
        auto_regs = len(register_hits)
        (ok if auto_regs == 0 else fail)("app does NOT silently re-register (no POST /devices/register)", f"got {auto_regs} auto POSTs")

        # Tap identity-reset-register
        await pageA.click('[data-testid="identity-reset-register"]', force=True)
        await pageA.wait_for_timeout(3000)
        stored2 = await pageA.evaluate("() => window.localStorage.getItem('apollo.device.identity.v2')")
        if stored2:
            new_id = json.loads(stored2)
            if isinstance(new_id, str):
                new_id = json.loads(new_id)
            (ok if new_id["deviceId"] != idA["deviceId"] else fail)("re-register creates NEW deviceId", f"old={idA['deviceId'][:8]} new={new_id['deviceId'][:8]}")
        else:
            fail("re-register creates NEW deviceId", "no identity stored after tap")

        # ---- Regression: Guard tab renders + Settings ----
        await pageA.goto(f"{BASE}/guard", wait_until="domcontentloaded")
        await pageA.wait_for_timeout(2500)
        body = await pageA.evaluate("() => document.body.innerText")
        (ok if "guarding what he can" in body else fail)("Guard tab regression 'guarding what he can'", body[:120])

        await pageA.goto(f"{BASE}/settings", wait_until="domcontentloaded")
        await pageA.wait_for_timeout(2000)
        settings_body = await pageA.evaluate("() => document.body.innerText")
        (ok if len(settings_body) > 20 else fail)("Settings screen renders", settings_body[:60])

        # ---- REVOCATION on a fresh device C ----
        C = register()
        tokC = C["device_token"]
        r = httpx.post(f"{API}/devices/revoke", headers={**HDR, "Authorization": f"Bearer {tokC}"}, timeout=10.0)
        (ok if r.status_code == 204 else fail)("C revoke → 204", f"{r.status_code}")
        r = httpx.get(f"{API}/devices/me", headers={**HDR, "Authorization": f"Bearer {tokC}"}, timeout=10.0)
        (ok if r.status_code == 401 else fail)("C after revoke /devices/me → 401", f"{r.status_code}")
        r = httpx.post(f"{API}/devices/token/rotate", headers={**HDR, "Authorization": f"Bearer {tokC}"}, timeout=10.0)
        (ok if r.status_code == 401 else fail)("C after revoke rotate → 401", f"{r.status_code}")

        await browser.close()

    print("\n===== SUMMARY =====")
    print(f"PASSED: {len(results['passed'])}")
    print(f"FAILED: {len(results['failed'])}")
    for f in results["failed"]:
        print(f"  - {f}")
    return len(results["failed"]) == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    exit(0 if ok else 1)
