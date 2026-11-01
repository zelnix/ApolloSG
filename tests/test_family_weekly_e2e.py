"""Iteration 23 — E2E for Family Weekly Check-In + Guardian Call-Back Number.

Three browser contexts:
  A = protected user (has an OPEN growling/barking alert this week)
  B = guardian (paired with A + a quiet C; also sends a note with phone)
  C = protected user (quiet, no events)

Reuses the iteration-22 flow to build an incident on A.
"""
import asyncio
import json
import os
import urllib.request

from playwright.async_api import async_playwright

BASE = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://case-source-preview--3ijise2t.preview.emergentagent.com",
).rstrip("/")


def api_post(path, body):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "apollo-e2e/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


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
    await page.wait_for_timeout(2500)


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
    await page.goto(f"{BASE}/message", wait_until="domcontentloaded")
    await page.wait_for_selector('[data-testid="message-text"]', timeout=10000)
    try:
        await page.fill('[data-testid="message-sender"]', "CommBank")
    except Exception:
        pass
    await page.fill(
        '[data-testid="message-text"]',
        "CommBank: your account is locked. Verify now at https://commbank-secure-verify.top/login",
    )
    await page.click('[data-testid="message-check"]', force=True)
    await page.wait_for_selector('[data-testid="message-check-account"]', timeout=25000)
    await page.click('[data-testid="message-check-account"]', force=True)
    await page.wait_for_selector('[data-testid="account-kind-mfa_prompt"]', timeout=10000)
    await page.click('[data-testid="account-kind-mfa_prompt"]', force=True)
    await page.click('[data-testid="account-provider-bank"]', force=True)
    await page.click('[data-testid="account-initiated-no"]', force=True)
    await page.click('[data-testid="account-run"]', force=True)
    await page.wait_for_selector('[data-testid="account-result"]', timeout=25000)
    await page.wait_for_timeout(1500)
    await page.goto(f"{BASE}/home", wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)
    scent_el = await page.query_selector('[data-testid^="home-scent-"]')
    assert scent_el, "No home-scent card"
    tid = await scent_el.get_attribute("data-testid")
    return tid.replace("home-scent-", "")


async def main():
    R = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        ctx_a = await browser.new_context(viewport={"width": 390, "height": 844})
        page_a = await ctx_a.new_page()
        page_a.on("pageerror", lambda e: print(f"[A pageerror] {e}"))

        ctx_b = None
        ctx_c = None
        try:
            # ==================== Context A ====================
            await onboard(page_a)
            device_a = await get_device_id(page_a)
            print(f"[A] device_id={device_a}")
            assert device_a
            scent_id = await build_incident(page_a)
            print(f"[A] scent_id={scent_id}")

            # Home regression smoke
            await page_a.goto(f"{BASE}/home", wait_until="domcontentloaded")
            await page_a.wait_for_timeout(1500)
            R["home_hero_present"] = bool(await page_a.query_selector('[data-testid="apollo-hero"]'))
            R["home_state_label_present"] = bool(await page_a.query_selector('[data-testid="apollo-state-label"]'))

            # tick step 0 (regression)
            await page_a.click(f'[data-testid="home-scent-{scent_id}"]', force=True)
            await page_a.wait_for_selector('[data-testid="incident-summary"]', timeout=10000)
            await page_a.click('[data-testid="incident-step-0"]', force=True)
            await page_a.wait_for_timeout(500)
            prog = await page_a.text_content('[data-testid="incident-progress"]')
            R["incident_progress_after_tick0"] = prog
            print(f"[A] progress: {prog}")

            # ==================== Context B (guardian) ====================
            ctx_b = await browser.new_context(viewport={"width": 390, "height": 844})
            page_b = await ctx_b.new_page()
            page_b.on("pageerror", lambda e: print(f"[B pageerror] {e}"))
            await onboard(page_b)
            device_b = await get_device_id(page_b)
            print(f"[B] device_id={device_b}")
            assert device_b

            # Pair A→B via API — with phone attached (so weekly Call button appears)
            code = api_post(
                "/api/family/pair",
                {"device_id": device_a, "owner_name": "Mum", "phone": "+61400000000"},
            )["code"]
            link = api_post("/api/family/link", {"device_id": device_b, "code": code})
            print(f"[api] A→B pair={code} link={link}")
            R["api_link_ok_A"] = bool(link.get("linked"))

            # A: share incident with guardian
            await page_a.goto(f"{BASE}/patrol/scent/{scent_id}", wait_until="domcontentloaded")
            await page_a.wait_for_selector('[data-testid="incident-share-family"]', timeout=10000)
            await page_a.click('[data-testid="incident-share-family"]', force=True)
            await page_a.wait_for_timeout(2500)
            body_a = await page_a.text_content("body")
            R["A_shared_toast"] = "shared with 1" in body_a.lower()

            # ==================== Context C (quiet protected) ====================
            ctx_c = await browser.new_context(viewport={"width": 390, "height": 844})
            page_c = await ctx_c.new_page()
            await onboard(page_c)
            device_c = await get_device_id(page_c)
            print(f"[C] device_id={device_c}")
            assert device_c

            # Pair C→B via API with owner 'Dad', no phone
            code_c = api_post(
                "/api/family/pair", {"device_id": device_c, "owner_name": "Dad"}
            )["code"]
            link_c = api_post("/api/family/link", {"device_id": device_b, "code": code_c})
            print(f"[api] C→B pair={code_c} link={link_c}")
            R["api_link_ok_C"] = bool(link_c.get("linked"))

            # ==================== B: /family — Weekly check-in ====================
            await page_b.goto(f"{BASE}/family", wait_until="domcontentloaded")
            await page_b.wait_for_timeout(3500)

            weekly = await page_b.query_selector('[data-testid="family-weekly"]')
            R["B_family_weekly_section_present"] = bool(weekly)
            print(f"[B] family-weekly section: {bool(weekly)}")

            # --- Mum row (A) ---
            row_a = await page_b.query_selector(f'[data-testid="family-weekly-{device_a}"]')
            R["B_weekly_row_A_present"] = bool(row_a)
            if row_a:
                tone_el = await page_b.query_selector(f'[data-testid="family-weekly-tone-{device_a}"]')
                headline_el = await page_b.query_selector(f'[data-testid="family-weekly-headline-{device_a}"]')
                details_el = await page_b.query_selector(f'[data-testid="family-weekly-details-{device_a}"]')
                call_btn = await page_b.query_selector(f'[data-testid="family-weekly-call-{device_a}"]')
                tone_text = (await tone_el.text_content()) if tone_el else ""
                headline_text = (await headline_el.text_content()) if headline_el else ""
                details_text = (await details_el.text_content()) if details_el else ""
                row_text = await row_a.text_content()
                call_label = (await call_btn.text_content()) if call_btn else ""
                R["B_weekly_A_tone"] = tone_text
                R["B_weekly_A_headline"] = headline_text
                R["B_weekly_A_details"] = details_text
                R["B_weekly_A_call_label"] = call_label
                R["B_weekly_A_says_still_open"] = "still open" in headline_text
                R["B_weekly_A_mentions_mum"] = "Mum" in headline_text
                R["B_weekly_A_tone_needs_call"] = "Needs a call" in tone_text
                R["B_weekly_A_active_line"] = "Their Apollo was" in row_text
                R["B_weekly_A_call_button_present"] = bool(call_btn)
                R["B_weekly_A_call_label_correct"] = "Call Mum" in call_label
                print(f"[B] A tone={tone_text!r} headline={headline_text!r}")
                print(f"[B] A details={details_text!r} call={call_label!r}")

            # --- Dad row (C, quiet) ---
            row_c = await page_b.query_selector(f'[data-testid="family-weekly-{device_c}"]')
            R["B_weekly_row_C_present"] = bool(row_c)
            if row_c:
                tone_c = await page_b.query_selector(f'[data-testid="family-weekly-tone-{device_c}"]')
                headline_c = await page_b.query_selector(f'[data-testid="family-weekly-headline-{device_c}"]')
                call_c = await page_b.query_selector(f'[data-testid="family-weekly-call-{device_c}"]')
                tone_c_text = (await tone_c.text_content()) if tone_c else ""
                headline_c_text = (await headline_c.text_content()) if headline_c else ""
                R["B_weekly_C_tone"] = tone_c_text
                R["B_weekly_C_headline"] = headline_c_text
                R["B_weekly_C_tone_calm"] = "Calm week" in tone_c_text
                R["B_weekly_C_quiet_headline_ok"] = (
                    "A quiet week for Dad" in headline_c_text
                    and "Nothing came up that needed a look" in headline_c_text
                )
                R["B_weekly_C_no_call_btn"] = not bool(call_c)
                print(f"[B] C tone={tone_c_text!r} headline={headline_c_text!r}")

            # ==================== B: incident note with call-back phone ====================
            fam_open = await page_b.query_selector(f'[data-testid="family-incident-open-{scent_id}"]')
            assert fam_open, "family-incident-open-<scent> missing"
            await fam_open.click(force=True)
            await page_b.wait_for_selector('[data-testid="family-note-card"]', timeout=10000)
            R["B_note_card_present"] = True

            # phone field present
            phone_el = await page_b.query_selector('[data-testid="family-note-phone"]')
            R["B_note_phone_field_present"] = bool(phone_el)

            await page_b.fill('[data-testid="family-note-name"]', "Sam")
            await page_b.fill('[data-testid="family-note-phone"]', "+61 411 222 333")
            # default kind = here — send
            await page_b.click('[data-testid="family-note-send"]', force=True)
            await page_b.wait_for_timeout(3500)
            body_b = await page_b.text_content("body")
            R["B_note_toast"] = "Note sent" in body_b

            sent0 = await page_b.query_selector('[data-testid="family-note-sent-0"]')
            R["B_family_note_sent_0_present"] = bool(sent0)
            if sent0:
                sent0_text = await sent0.text_content()
                R["B_family_note_sent_0_text"] = sent0_text
                R["B_note_sent_has_callback"] = "call back +61 411 222 333" in sent0_text
                print(f"[B] sent-0: {sent0_text!r}")

            # ==================== A: incident timeline — call back button ====================
            await page_a.goto(f"{BASE}/home", wait_until="domcontentloaded")
            await page_a.wait_for_timeout(2000)
            await page_a.click(f'[data-testid="home-scent-{scent_id}"]', force=True)
            await page_a.wait_for_selector('[data-testid="incident-summary"]', timeout=10000)
            # Poll for notes card
            for _ in range(25):
                card = await page_a.query_selector('[data-testid="incident-family-notes"]')
                if card:
                    break
                await page_a.wait_for_timeout(1000)
            card = await page_a.query_selector('[data-testid="incident-family-notes"]')
            R["A_incident_family_notes_card"] = bool(card)

            n0 = await page_a.query_selector('[data-testid="incident-family-note-0"]')
            R["A_note0_present"] = bool(n0)
            if n0:
                t0 = await n0.text_content()
                R["A_note0_text"] = t0
                R["A_note0_matches_spec"] = (
                    "Sam" in t0 and "I'm here" in t0 and "call me when you're ready" in t0
                )

            call_btn_a = await page_a.query_selector('[data-testid="incident-family-note-call-0"]')
            R["A_note0_call_btn_present"] = bool(call_btn_a)
            if call_btn_a:
                call_label_a = await call_btn_a.text_content()
                R["A_note0_call_btn_label"] = call_label_a
                R["A_note0_call_btn_label_ok"] = "Call Sam back" in call_label_a
                print(f"[A] call-btn label: {call_label_a!r}")

        except Exception as e:
            print(f"[FATAL] {e}")
            R["fatal"] = str(e)
            try:
                await page_a.screenshot(path="/tmp/apollo23_fatal_a.png", quality=40, full_page=False)
            except Exception:
                pass
        finally:
            await browser.close()

    print("\n=== RESULTS ===")
    for k, v in R.items():
        print(f"  {k}: {v}")

    required = [
        "home_hero_present", "home_state_label_present", "incident_progress_after_tick0",
        "api_link_ok_A", "api_link_ok_C",
        "A_shared_toast",
        "B_family_weekly_section_present", "B_weekly_row_A_present",
        "B_weekly_A_says_still_open", "B_weekly_A_mentions_mum",
        "B_weekly_A_tone_needs_call", "B_weekly_A_active_line",
        "B_weekly_A_call_button_present", "B_weekly_A_call_label_correct",
        "B_weekly_row_C_present", "B_weekly_C_tone_calm",
        "B_weekly_C_quiet_headline_ok", "B_weekly_C_no_call_btn",
        "B_note_card_present", "B_note_phone_field_present",
        "B_note_toast", "B_family_note_sent_0_present", "B_note_sent_has_callback",
        "A_incident_family_notes_card", "A_note0_present", "A_note0_matches_spec",
        "A_note0_call_btn_present", "A_note0_call_btn_label_ok",
    ]
    missing = [k for k in required if not R.get(k)]
    print(f"\nPASS: {not missing and 'fatal' not in R}. Missing: {missing}")


asyncio.run(main())
