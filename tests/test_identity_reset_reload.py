"""Iteration 31 — RETEST HIGH bug from iter 30: after 401 identity-reset, a page reload must NOT
silently POST /api/devices/register. The identity-reset-card must persist across reloads until the user
taps identity-reset-register. Also fresh-install regression: brand new context still auto-registers.
"""
import asyncio
import json
import os
import httpx
from playwright.async_api import async_playwright

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL", "https://tc-flyby-2fa--0hiznn9n.preview.emergentagent.com")
BASE = BASE.rstrip("/")
API = f"{BASE}/api"
HDR = {"User-Agent": "apollo-e2e-iter31", "Content-Type": "application/json"}
RESULTS = {"passed": [], "failed": []}


def ok(name):
    print(f"PASS {name}")
    RESULTS["passed"].append(name)


def fail(name, detail=""):
    print(f"FAIL {name} — {detail}")
    RESULTS["failed"].append(f"{name}: {detail}")


async def onboard(ctx, label, register_hits, all_calls):
    page = await ctx.new_page()
    page.on("console", lambda m: print(f"[{label}] CONSOLE {m.type}: {m.text}") if m.type in ("error",) else None)
    await page.set_viewport_size({"width": 390, "height": 844})
    page.on("request", lambda r: (
        register_hits.append((r.method, r.url)) if r.url.endswith("/api/devices/register") and r.method == "POST" else None,
        all_calls.append((r.method, r.url)) if "/api/" in r.url else None,
    ))
    await page.goto(BASE + "/", wait_until="domcontentloaded")
    await page.wait_for_selector('[data-testid="onboarding-start-button"]', timeout=20000)
    await page.click('[data-testid="onboarding-start-button"]', force=True)
    await page.wait_for_selector('[data-testid="disclosure-accept-button"]', timeout=10000)
    await page.click('[data-testid="disclosure-accept-button"]', force=True)
    await page.wait_for_selector('[data-testid="apollo-state-label"]', timeout=20000)
    identity_raw = await page.evaluate("() => window.localStorage.getItem('apollo.device.identity.v2')")
    if not identity_raw:
        raise RuntimeError(f"[{label}] no identity in localStorage")
    identity = json.loads(identity_raw)
    if isinstance(identity, str):
        identity = json.loads(identity)
    print(f"[{label}] onboarded deviceId={identity['deviceId'][:10]}… onboarding registers={len(register_hits)}")
    return page, identity


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()

        # ---------- Fresh context: onboarding (regression) ----------
        ctxA = await browser.new_context()
        reg_hits = []
        api_calls = []
        pageA, idA = await onboard(ctxA, "A", reg_hits, api_calls)
        # Fresh install regression: exactly one register call during onboarding
        (ok if len(reg_hits) == 1 else fail)("fresh-install onboarding: exactly 1 POST /api/devices/register", f"got {len(reg_hits)}")

        # ---------- Rotate token via API (simulate server-side rotation) ----------
        r = httpx.post(f"{API}/devices/token/rotate", headers={**HDR, "Authorization": f"Bearer {idA['token']}"}, timeout=15.0)
        (ok if r.status_code == 200 else fail)("rotate A token 200", f"got {r.status_code}")

        # ---------- Trigger an app API call → 401 → identity-reset (card only renders on Home) ----------
        await pageA.goto(f"{BASE}/family", wait_until="domcontentloaded")
        await pageA.wait_for_timeout(4000)
        await pageA.goto(f"{BASE}/", wait_until="domcontentloaded")
        try:
            await pageA.wait_for_selector('[data-testid="identity-reset-card"]', timeout=15000)
            ok("identity-reset-card appears after 401")
        except Exception as e:
            fail("identity-reset-card appears after 401", str(e))
            await pageA.screenshot(path="/tmp/iter31_no_card.png", quality=40, full_page=False)

        why_visible = await pageA.is_visible('[data-testid="identity-reset-why"]')
        btn_visible = await pageA.is_visible('[data-testid="identity-reset-register"]')
        (ok if why_visible and btn_visible else fail)("identity-reset-why + register button present", f"why={why_visible} btn={btn_visible}")

        stored = await pageA.evaluate("() => window.localStorage.getItem('apollo.device.identity.v2')")
        (ok if stored in (None, "null", "") else fail)("localStorage identity cleared after 401", f"got {stored!r}")

        marker = await pageA.evaluate("() => window.localStorage.getItem('apollo.device.identity.reset.v1')")
        (ok if marker not in (None, "null", "") else fail)("reset marker apollo.device.identity.reset.v1 persisted", f"got {marker!r}")

        # ---------- Snapshot register-count BEFORE reload ----------
        reg_hits_before_reload = len(reg_hits)

        # ---------- FULL PAGE RELOAD — the actual bug retest ----------
        await pageA.reload(wait_until="domcontentloaded")
        # Wait for #root to have text (app rendered)
        await pageA.wait_for_selector('#root', timeout=15000)
        await pageA.wait_for_timeout(3000)  # let boot effect run

        # Card must still be visible
        try:
            await pageA.wait_for_selector('[data-testid="identity-reset-card"]', timeout=8000)
            ok("identity-reset-card STILL visible after full reload")
        except Exception as e:
            fail("identity-reset-card STILL visible after full reload", str(e))
            await pageA.screenshot(path="/tmp/iter31_reload_card_gone.png", quality=40, full_page=False)

        # No silent POST /devices/register fired during reload
        auto_regs_during_reload = len(reg_hits) - reg_hits_before_reload
        (ok if auto_regs_during_reload == 0 else fail)("NO silent POST /devices/register during reload", f"got {auto_regs_during_reload} auto POSTs")

        # localStorage identity still null
        stored2 = await pageA.evaluate("() => window.localStorage.getItem('apollo.device.identity.v2')")
        (ok if stored2 in (None, "null", "") else fail)("localStorage identity still null after reload", f"got {stored2!r}")

        # Marker still present
        marker2 = await pageA.evaluate("() => window.localStorage.getItem('apollo.device.identity.reset.v1')")
        (ok if marker2 not in (None, "null", "") else fail)("reset marker still present after reload", f"got {marker2!r}")

        # ---------- Navigate to /guard, /family and back to / — card persists ----------
        for path in ["/guard", "/family", "/"]:
            reg_hits_before_nav = len(reg_hits)
            await pageA.goto(f"{BASE}{path}", wait_until="domcontentloaded")
            await pageA.wait_for_timeout(2000)
            # Card should still be on Home; on other tabs may not render but marker should persist
            marker_nav = await pageA.evaluate("() => window.localStorage.getItem('apollo.device.identity.reset.v1')")
            (ok if marker_nav not in (None, "null", "") else fail)(f"marker persists after nav to {path}", f"got {marker_nav!r}")
            auto_reg_nav = len(reg_hits) - reg_hits_before_nav
            (ok if auto_reg_nav == 0 else fail)(f"no silent POST /devices/register during nav to {path}", f"got {auto_reg_nav}")

        # Ensure on Home again the card is visible
        try:
            await pageA.wait_for_selector('[data-testid="identity-reset-card"]', timeout=8000)
            ok("identity-reset-card visible on Home after nav cycle")
        except Exception as e:
            fail("identity-reset-card visible on Home after nav cycle", str(e))

        # ---------- Tap identity-reset-register → exactly one register call → new deviceId ----------
        reg_hits_before_tap = len(reg_hits)
        await pageA.click('[data-testid="identity-reset-register"]', force=True)
        await pageA.wait_for_timeout(3500)
        reg_after_tap = len(reg_hits) - reg_hits_before_tap
        (ok if reg_after_tap == 1 else fail)("tap identity-reset-register → exactly 1 POST /api/devices/register", f"got {reg_after_tap}")

        stored3 = await pageA.evaluate("() => window.localStorage.getItem('apollo.device.identity.v2')")
        if stored3 and stored3 not in ("null", ""):
            new_id = json.loads(stored3)
            if isinstance(new_id, str):
                new_id = json.loads(new_id)
            (ok if new_id["deviceId"] != idA["deviceId"] else fail)("re-register produces NEW deviceId", f"old={idA['deviceId'][:8]} new={new_id['deviceId'][:8]}")
        else:
            fail("re-register produces NEW deviceId", f"identity missing: {stored3!r}")

        marker3 = await pageA.evaluate("() => window.localStorage.getItem('apollo.device.identity.reset.v1')")
        (ok if marker3 in (None, "null", "") else fail)("reset marker removed after successful re-register", f"got {marker3!r}")

        # Card should be gone
        card_gone = not await pageA.is_visible('[data-testid="identity-reset-card"]')
        (ok if card_gone else fail)("identity-reset-card gone after re-register", "still visible")

        # ---------- Reload once more — no card, no extra register, identity persists ----------
        reg_hits_before_final_reload = len(reg_hits)
        await pageA.reload(wait_until="domcontentloaded")
        await pageA.wait_for_timeout(3000)
        final_reload_regs = len(reg_hits) - reg_hits_before_final_reload
        (ok if final_reload_regs == 0 else fail)("final reload: no extra POST /devices/register", f"got {final_reload_regs}")
        card_gone_final = not await pageA.is_visible('[data-testid="identity-reset-card"]')
        (ok if card_gone_final else fail)("final reload: card not shown", "card still visible")
        stored4 = await pageA.evaluate("() => window.localStorage.getItem('apollo.device.identity.v2')")
        (ok if stored4 and stored4 not in ("null", "") else fail)("final reload: identity persists", f"got {stored4!r}")

        await ctxA.close()

        # ---------- Fresh-install regression: brand new context still auto-registers ----------
        ctxB = await browser.new_context()
        reg_hits_B = []
        api_calls_B = []
        pageB, idB = await onboard(ctxB, "B-fresh", reg_hits_B, api_calls_B)
        (ok if len(reg_hits_B) == 1 else fail)("brand-new context: exactly 1 POST /api/devices/register on onboarding", f"got {len(reg_hits_B)}")
        marker_B = await pageB.evaluate("() => window.localStorage.getItem('apollo.device.identity.reset.v1')")
        (ok if marker_B in (None, "null", "") else fail)("brand-new context: no reset marker (fresh install)", f"got {marker_B!r}")
        await ctxB.close()

        await browser.close()

    print("\n===== SUMMARY =====")
    print(f"PASSED: {len(RESULTS['passed'])}")
    print(f"FAILED: {len(RESULTS['failed'])}")
    for f in RESULTS["failed"]:
        print(f"  - {f}")
    return len(RESULTS["failed"]) == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
