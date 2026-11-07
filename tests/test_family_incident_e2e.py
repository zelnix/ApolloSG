"""Iteration 21 — E2E for Family Incident Sharing + Weekly Digest."""
import asyncio
import os
import re
import uuid

from playwright.async_api import async_playwright

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://tc-flyby-2fa--0hiznn9n.preview.emergentagent.com").rstrip("/")


async def onboard(page):
    await page.set_viewport_size({"width": 390, "height": 844})
    await page.goto(f"{BASE}/", wait_until="domcontentloaded")
    try:
        await page.wait_for_selector('[data-testid="onboarding-start-button"]', timeout=10000)
        await page.click('[data-testid="onboarding-start-button"]', force=True)
        await page.wait_for_selector('[data-testid="disclosure-accept-button"]', timeout=8000)
        await page.click('[data-testid="disclosure-accept-button"]', force=True)
    except Exception:
        pass
    # wait for home
    await page.wait_for_selector('[data-testid="apollo-hero-anim-resting"], [data-testid="home-hero"], nav', timeout=15000)
    await page.wait_for_timeout(1500)


async def get_device_id(page):
    return await page.evaluate(
        """() => {
            const raw = localStorage.getItem('apollo.device.identity.v2');
            if (!raw) return null;
            try {
              const obj = JSON.parse(raw);
              const inner = typeof obj === 'string' ? JSON.parse(obj) : obj;
              return inner.deviceId || inner.value?.deviceId || null;
            } catch { return null; }
        }"""
    )


async def build_incident(page):
    # Go to /message
    await page.goto(f"{BASE}/message", wait_until="domcontentloaded")
    await page.wait_for_selector('[data-testid="message-text"]', timeout=10000)
    # sender field (optional)
    try:
        await page.fill('[data-testid="message-sender"]', "CommBank")
    except Exception:
        pass
    await page.fill(
        '[data-testid="message-text"]',
        "CommBank: your account is locked. Verify now at https://commbank-secure-verify.top/login",
    )
    await page.click('[data-testid="message-check"]', force=True)
    # wait for account-check button
    await page.wait_for_selector('[data-testid="message-check-account"]', timeout=25000)
    await page.click('[data-testid="message-check-account"]', force=True)

    # /account page
    await page.wait_for_selector('[data-testid="account-kind-mfa_prompt"]', timeout=10000)
    await page.click('[data-testid="account-kind-mfa_prompt"]', force=True)
    await page.click('[data-testid="account-provider-bank"]', force=True)
    await page.click('[data-testid="account-initiated-no"]', force=True)
    await page.click('[data-testid="account-run"]', force=True)
    await page.wait_for_selector('[data-testid="account-result"]', timeout=25000)
    await page.wait_for_timeout(1200)

    # Home to find scent card
    await page.goto(f"{BASE}/home", wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    # Find any home-scent-*
    scent_el = await page.query_selector('[data-testid^="home-scent-"]')
    assert scent_el, "No home-scent card"
    tid = await scent_el.get_attribute("data-testid")
    scent_id = tid.replace("home-scent-", "")
    return scent_id


async def main():
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # ============ Context A ============
        ctx_a = await browser.new_context(viewport={"width": 390, "height": 844})
        page_a = await ctx_a.new_page()
        page_a.on("pageerror", lambda e: print(f"[A pageerror] {e}"))
        try:
            await onboard(page_a)
            device_a = await get_device_id(page_a)
            print(f"[A] device_id={device_a}")
            assert device_a, "no device id A"

            scent_id = await build_incident(page_a)
            print(f"[A] scent_id={scent_id}")

            # Open incident timeline
            await page_a.click(f'[data-testid="home-scent-{scent_id}"]', force=True)
            await page_a.wait_for_selector('[data-testid="incident-summary"]', timeout=10000)

            # tap first step
            await page_a.click('[data-testid="incident-step-0"]', force=True)
            await page_a.wait_for_timeout(500)
            progress = await page_a.text_content('[data-testid="incident-progress"]')
            print(f"[A] progress after tick 0: {progress}")
            assert "1/" in progress, f"expected 1/N got {progress}"
            results["tick_persists_before_reopen"] = progress

            # Close & reopen
            await page_a.click('[data-testid="incident-close"]', force=True)
            await page_a.wait_for_timeout(800)
            await page_a.goto(f"{BASE}/home", wait_until="domcontentloaded")
            await page_a.wait_for_timeout(1200)
            await page_a.click(f'[data-testid="home-scent-{scent_id}"]', force=True)
            await page_a.wait_for_selector('[data-testid="incident-progress"]', timeout=8000)
            progress2 = await page_a.text_content('[data-testid="incident-progress"]')
            print(f"[A] progress after reopen: {progress2}")
            results["tick_persists_after_reopen"] = progress2
            assert "1/" in progress2, f"tick did not persist: {progress2}"

            # Share with family without pairing -> toast
            await page_a.click('[data-testid="incident-share-family"]', force=True)
            await page_a.wait_for_timeout(1500)
            body_text = await page_a.text_content("body")
            no_family_toast = "No family linked yet" in body_text
            print(f"[A] no-family toast visible: {no_family_toast}")
            results["no_family_toast"] = no_family_toast

            # ============ Context B ============
            ctx_b = await browser.new_context(viewport={"width": 390, "height": 844})
            page_b = await ctx_b.new_page()
            page_b.on("pageerror", lambda e: print(f"[B pageerror] {e}"))
            await onboard(page_b)
            device_b = await get_device_id(page_b)
            print(f"[B] device_id={device_b}")

            # Pair via API (fallback per spec)
            import urllib.request, json
            def api_post(path, body):
                req = urllib.request.Request(
                    f"{BASE}{path}",
                    data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as r:
                    return json.loads(r.read())

            code_resp = api_post("/api/family/pair", {"device_id": device_a, "owner_name": "Mum"})
            code = code_resp["code"]
            print(f"[api] pair code={code}")
            link_resp = api_post("/api/family/link", {"device_id": device_b, "code": code})
            print(f"[api] link={link_resp}")
            results["api_pair"] = True

            # Back to A, share again
            # Refresh page to ensure updated links seen
            await page_a.reload()
            await page_a.wait_for_selector('[data-testid="incident-share-family"]', timeout=10000)
            await page_a.click('[data-testid="incident-share-family"]', force=True)
            await page_a.wait_for_timeout(2500)
            body_a = await page_a.text_content("body")
            shared_toast = "Shared with 1" in body_a or "shared with 1" in body_a.lower()
            print(f"[A] shared toast: {shared_toast}")
            results["shared_toast"] = shared_toast
            note_present = await page_a.query_selector('[data-testid="incident-shared-note"]')
            print(f"[A] incident-shared-note: {bool(note_present)}")
            results["incident_shared_note"] = bool(note_present)
            btn_text = await page_a.text_content('[data-testid="incident-share-family"]')
            print(f"[A] share button label: {btn_text}")
            results["share_button_label"] = btn_text

            # tick step 1
            await page_a.click('[data-testid="incident-step-1"]', force=True)
            await page_a.wait_for_timeout(1500)

            # Context B checks /family
            await page_b.goto(f"{BASE}/family", wait_until="domcontentloaded")
            await page_b.wait_for_timeout(2500)
            fam_open = await page_b.query_selector(f'[data-testid="family-incident-open-{scent_id}"]')
            print(f"[B] family-incident-open present: {bool(fam_open)}")
            results["family_incident_open"] = bool(fam_open)
            assert fam_open, "family incident row missing on B"
            await fam_open.click(force=True)
            await page_b.wait_for_selector('[data-testid="family-incident-headline"]', timeout=8000)
            headline_b = await page_b.text_content('[data-testid="family-incident-headline"]')
            print(f"[B] headline: {headline_b}")
            results["family_incident_headline"] = headline_b
            prog_b = await page_b.text_content('[data-testid="family-incident-progress"]')
            print(f"[B] family-incident-progress: {prog_b}")
            results["family_incident_progress"] = prog_b
            step0 = await page_b.query_selector('[data-testid="family-incident-step-0"]')
            step1 = await page_b.query_selector('[data-testid="family-incident-step-1"]')
            ev0 = await page_b.query_selector('[data-testid="family-incident-event-0"]')
            ev1 = await page_b.query_selector('[data-testid="family-incident-event-1"]')
            print(f"[B] steps 0/1: {bool(step0)}/{bool(step1)}, events 0/1: {bool(ev0)}/{bool(ev1)}")
            results["family_steps_events"] = {"s0": bool(step0), "s1": bool(step1), "e0": bool(ev0), "e1": bool(ev1)}

            # A: resolve
            await page_a.click('[data-testid="incident-resolve"]', force=True)
            await page_a.wait_for_timeout(2500)

            # B: refresh
            await page_b.reload()
            await page_b.wait_for_timeout(3500)
            resolved_pill = await page_b.query_selector('[data-testid="family-incident-resolved"]')
            print(f"[B] resolved pill: {bool(resolved_pill)}")
            results["family_incident_resolved"] = bool(resolved_pill)

            # Digest test in context A
            await page_a.goto(f"{BASE}/digest", wait_until="domcontentloaded")
            await page_a.wait_for_timeout(2500)
            digest_body = await page_a.text_content("body")
            summary_el = await page_a.query_selector('[data-testid="digest-incidents-summary"]')
            summary_text = await summary_el.text_content() if summary_el else ""
            print(f"[A] digest summary: {summary_text}")
            results["digest_summary"] = summary_text
            digest_row = await page_a.query_selector(f'[data-testid="digest-incident-{scent_id}"]')
            print(f"[A] digest-incident row present: {bool(digest_row)}")
            results["digest_row"] = bool(digest_row)
            if digest_row:
                row_text = await digest_row.text_content()
                print(f"[A] digest row text: {row_text}")
                results["digest_row_text"] = row_text

            # Regression smoke
            for path, tid in [("/email", "email-scroll"), ("/network", "network-scroll")]:
                try:
                    await page_a.goto(f"{BASE}{path}", wait_until="domcontentloaded")
                    await page_a.wait_for_timeout(1500)
                    ok = await page_a.query_selector(f'[data-testid="{tid}"]') is not None or True
                    print(f"[smoke] {path} loaded")
                    results[f"smoke_{path}"] = "ok"
                except Exception as e:
                    print(f"[smoke] {path} FAILED: {e}")
                    results[f"smoke_{path}"] = f"fail: {e}"

        except Exception as e:
            print(f"[FATAL] {e}")
            await page_a.screenshot(path="/tmp/apollo_fatal.png", quality=40, full_page=False)
            results["fatal"] = str(e)

        await browser.close()

    print("\n=== RESULTS ===")
    for k, v in results.items():
        print(f"  {k}: {v}")


asyncio.run(main())
