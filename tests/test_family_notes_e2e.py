"""Iteration 22 — E2E for Family Reassurance Note.
Two browser contexts: A = protected user, B = guardian.
Depends on iteration 21 flow to build an incident and pair via API.
"""
import asyncio
import json
import os
import urllib.request
import uuid

from playwright.async_api import async_playwright

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://case-source-preview--3ijise2t.preview.emergentagent.com").rstrip("/")


def api_post(path, body):
    req = urllib.request.Request(f"{BASE}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "apollo-e2e/1.0"},
                                 method="POST")
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
    await page.fill('[data-testid="message-text"]',
                    "CommBank: your account is locked. Verify now at https://commbank-secure-verify.top/login")
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

        # ============ Context A (protected) ============
        ctx_a = await browser.new_context(viewport={"width": 390, "height": 844})
        page_a = await ctx_a.new_page()
        page_a.on("pageerror", lambda e: print(f"[A pageerror] {e}"))
        try:
            await onboard(page_a)
            device_a = await get_device_id(page_a)
            print(f"[A] device_id={device_a}")
            assert device_a
            scent_id = await build_incident(page_a)
            print(f"[A] scent_id={scent_id}")

            # Open incident
            await page_a.click(f'[data-testid="home-scent-{scent_id}"]', force=True)
            await page_a.wait_for_selector('[data-testid="incident-summary"]', timeout=10000)
            # tick step 0 for regression progress
            await page_a.click('[data-testid="incident-step-0"]', force=True)
            await page_a.wait_for_timeout(500)
            prog = await page_a.text_content('[data-testid="incident-progress"]')
            R["incident_progress_after_tick0"] = prog
            print(f"[A] progress: {prog}")

            # Smoke: apollo-hero + state label present on home
            await page_a.goto(f"{BASE}/home", wait_until="domcontentloaded")
            await page_a.wait_for_timeout(1500)
            hero = await page_a.query_selector('[data-testid="apollo-hero"]')
            state_label = await page_a.query_selector('[data-testid="apollo-state-label"]')
            R["home_hero_present"] = bool(hero)
            R["home_state_label_present"] = bool(state_label)
            print(f"[A] apollo-hero: {bool(hero)}, apollo-state-label: {bool(state_label)}")

            # ============ Context B (guardian) ============
            ctx_b = await browser.new_context(viewport={"width": 390, "height": 844})
            page_b = await ctx_b.new_page()
            page_b.on("pageerror", lambda e: print(f"[B pageerror] {e}"))
            await onboard(page_b)
            device_b = await get_device_id(page_b)
            print(f"[B] device_id={device_b}")
            assert device_b

            # Pair via API
            code = api_post("/api/family/pair", {"device_id": device_a, "owner_name": "Mum"})["code"]
            link = api_post("/api/family/link", {"device_id": device_b, "code": code})
            print(f"[api] pair code={code} link={link}")
            R["api_pair_code"] = code
            R["api_link_ok"] = bool(link.get("linked"))

            # A: share
            await page_a.goto(f"{BASE}/patrol/scent/{scent_id}", wait_until="domcontentloaded")
            await page_a.wait_for_selector('[data-testid="incident-share-family"]', timeout=10000)
            await page_a.click('[data-testid="incident-share-family"]', force=True)
            await page_a.wait_for_timeout(2500)
            body_a = await page_a.text_content("body")
            R["A_shared_toast"] = "Shared with 1" in body_a or "shared with 1" in body_a.lower()
            note_ind = await page_a.query_selector('[data-testid="incident-shared-note"]')
            R["A_incident_shared_note"] = bool(note_ind)
            print(f"[A] shared toast: {R['A_shared_toast']}  note: {R['A_incident_shared_note']}")

            # B: navigate to /family and open incident
            await page_b.goto(f"{BASE}/family", wait_until="domcontentloaded")
            await page_b.wait_for_timeout(3000)
            fam_open = await page_b.query_selector(f'[data-testid="family-incident-open-{scent_id}"]')
            assert fam_open, "family-incident-open-<scent> missing"
            await fam_open.click(force=True)
            await page_b.wait_for_selector('[data-testid="family-note-card"]', timeout=10000)
            R["B_note_card_present"] = True
            print("[B] family-note-card visible")

            # Assert all preset chips + custom exist
            chips_present = {}
            for k in ("here", "calling", "on_way", "together", "custom"):
                el = await page_b.query_selector(f'[data-testid="family-note-kind-{k}"]')
                chips_present[k] = bool(el)
            R["B_chips_present"] = chips_present
            print(f"[B] chips: {chips_present}")
            assert all(chips_present.values()), f"missing chip(s): {chips_present}"

            # name input + send button present
            name_input = await page_b.query_selector('[data-testid="family-note-name"]')
            send_btn = await page_b.query_selector('[data-testid="family-note-send"]')
            R["B_name_input_present"] = bool(name_input)
            R["B_send_button_present"] = bool(send_btn)

            # Default 'here' selected — send with name 'Sam'
            await page_b.fill('[data-testid="family-note-name"]', "Sam")
            # ensure default kind is 'here' (state) — click it explicitly to be safe
            await page_b.click('[data-testid="family-note-kind-here"]', force=True)
            await page_b.wait_for_timeout(400)
            await page_b.click('[data-testid="family-note-send"]', force=True)
            # wait for toast + card refresh
            await page_b.wait_for_timeout(3500)
            body_b = await page_b.text_content("body")
            R["B_note_toast"] = "Note sent" in body_b
            print(f"[B] note toast: {R['B_note_toast']}")

            # family-note-sent-0 shows preset text
            sent0 = await page_b.query_selector('[data-testid="family-note-sent-0"]')
            R["B_family_note_sent_0_present"] = bool(sent0)
            if sent0:
                sent0_text = await sent0.text_content()
                print(f"[B] family-note-sent-0: {sent0_text!r}")
                R["B_family_note_sent_0_text"] = sent0_text
                assert "I'm here" in sent0_text and "call me when you're ready" in sent0_text, sent0_text

            # Custom note flow
            await page_b.click('[data-testid="family-note-kind-custom"]', force=True)
            await page_b.wait_for_timeout(400)
            text_input = await page_b.query_selector('[data-testid="family-note-text"]')
            R["B_custom_textinput_present"] = bool(text_input)
            # send disabled while empty
            disabled_empty = await page_b.get_attribute('[data-testid="family-note-send"]', "aria-disabled")
            # also check if clicking does nothing → we check aria-disabled or a real "disabled" prop
            R["B_send_aria_disabled_when_empty"] = disabled_empty
            print(f"[B] send aria-disabled when empty: {disabled_empty}")

            await page_b.fill('[data-testid="family-note-text"]', "Popping over at 6")
            await page_b.wait_for_timeout(300)
            disabled_after = await page_b.get_attribute('[data-testid="family-note-send"]', "aria-disabled")
            R["B_send_aria_disabled_after_type"] = disabled_after
            print(f"[B] send aria-disabled after type: {disabled_after}")
            await page_b.click('[data-testid="family-note-send"]', force=True)
            await page_b.wait_for_timeout(3500)
            sent1 = await page_b.query_selector('[data-testid="family-note-sent-1"]')
            R["B_family_note_sent_1_present"] = bool(sent1)
            if sent1:
                sent1_text = await sent1.text_content()
                print(f"[B] family-note-sent-1: {sent1_text!r}")
                R["B_family_note_sent_1_text"] = sent1_text
                assert "Popping over at 6" in sent1_text

            # ============ Context A: verify notes on incident timeline ============
            await page_a.goto(f"{BASE}/home", wait_until="domcontentloaded")
            await page_a.wait_for_timeout(2000)
            await page_a.click(f'[data-testid="home-scent-{scent_id}"]', force=True)
            await page_a.wait_for_selector('[data-testid="incident-summary"]', timeout=10000)
            # Wait for polling to fetch notes (up to 20s)
            for _ in range(20):
                card = await page_a.query_selector('[data-testid="incident-family-notes"]')
                if card:
                    break
                await page_a.wait_for_timeout(1000)
            card = await page_a.query_selector('[data-testid="incident-family-notes"]')
            R["A_incident_family_notes_card"] = bool(card)
            print(f"[A] incident-family-notes card: {bool(card)}")

            n0 = await page_a.query_selector('[data-testid="incident-family-note-0"]')
            n1 = await page_a.query_selector('[data-testid="incident-family-note-1"]')
            R["A_note0_present"] = bool(n0)
            R["A_note1_present"] = bool(n1)
            if n0:
                t0 = await n0.text_content()
                R["A_note0_text"] = t0
                print(f"[A] incident-family-note-0: {t0!r}")
                assert "Sam" in t0 and "I'm here" in t0, t0
            if n1:
                t1 = await n1.text_content()
                R["A_note1_text"] = t1
                print(f"[A] incident-family-note-1: {t1!r}")
                assert "Sam" in t1 and "Popping over at 6" in t1, t1

        except Exception as e:
            print(f"[FATAL] {e}")
            try:
                await page_a.screenshot(path="/tmp/apollo22_fatal_a.png", quality=40, full_page=False)
            except Exception:
                pass
            R["fatal"] = str(e)
        finally:
            await browser.close()

    print("\n=== RESULTS ===")
    for k, v in R.items():
        print(f"  {k}: {v}")

    # summarize pass/fail
    required = [
        "incident_progress_after_tick0", "home_hero_present", "home_state_label_present",
        "api_link_ok", "A_shared_toast", "A_incident_shared_note",
        "B_note_card_present", "B_note_toast",
        "B_family_note_sent_0_present", "B_family_note_sent_1_present",
        "A_incident_family_notes_card", "A_note0_present", "A_note1_present",
    ]
    missing = [k for k in required if not R.get(k)]
    print(f"\nPASS: {not missing and 'fatal' not in R}. Missing: {missing}")


asyncio.run(main())
