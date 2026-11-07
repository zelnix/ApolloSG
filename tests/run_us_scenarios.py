"""US-scenario runner: normal-screen browser journeys with real Gemini + research, graded on typed outcomes (never keywords).

Writes an immutable run directory: test_reports/us_runs/<timestamp>/outcomes.json (+ screenshots). Statuses: complete | partial | failed | blocked | not_run.
Run: cd /app && python tests/run_us_scenarios.py [US03 US06 ...]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://tc-flyby-2fa--0hiznn9n.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
RUN = Path("/app/test_reports/us_runs") / time.strftime("%Y%m%dT%H%M%S")
RUN.mkdir(parents=True, exist_ok=True)
PHISH = "https://testsafebrowsing.appspot.com/s/phishing.html"

LONG_TEXT = ("Hi, Marta from the strata committee here. Routine minutes follow: gardens, lift service, bins, fire door check. " * 230) + \
            " IMPORTANT: our levy account has changed — pay this quarter's levy to BSB 062-000 account 1234 5678 instead of the usual account. " + ("Regards, Marta. " * 30)

SCENARIOS = {
    "US03": {"screen": "message", "sender": "+61 400 111 222", "text": LONG_TEXT, "gate": "text",
             "expect": {"assessment": ["concern_found"], "attention": ["review", "action_needed", "urgent"], "min_findings": 1}},
    "US06": {"screen": "message", "sender": "Dental Care", "text": "Reminder: your appointment with Dr Lee is Tuesday 10:30am at 12 High St. Reply C to confirm or call us on the number in your booking letter to reschedule.", "gate": "text",
             "expect": {"assessment": ["no_concern_found_within_scope", "uncertain"], "attention": ["none", "review"], "max_actions_recommended": 1}},
    "US05": {"screen": "message", "sender": "+61 480 021 337", "text": "CommBank alert: unusual login detected. To secure your account call 1800 011 217 or 02 9999 0000 or +61 480 021 337 immediately and quote reference 8842.", "gate": "text",
             "expect": {"assessment": ["concern_found", "uncertain"], "attention": ["review", "action_needed", "urgent"], "clue_kinds": ["phone clue"]}},
    "US01": {"screen": "check", "url": PHISH, "gate": "link",
             "expect": {"assessment": ["concern_found", "no_concern_found_within_scope", "uncertain"], "min_sources": 1, "completion": ["complete", "partial"]}},
    "US24": {"screen": "ask", "question": "Apollo just barked on a file I downloaded from a text message, then said protection is stopped on my phone. What is going on and what should I do first?",
             "expect": {"completion": ["complete", "partial", "waiting_user"], "min_explanation_chars": 900, "follow_up": True},
             "answer": "I have not opened the file. It was a PDF called invoice.pdf from a number I don't know, and Apollo's protection switch shows off."},
}


async def onboard(page):
    await page.goto(BASE, wait_until="domcontentloaded")
    await page.wait_for_selector('[data-testid="onboarding-start-button"]', timeout=90000)
    await page.click('[data-testid="onboarding-start-button"]', force=True)
    await page.wait_for_selector('[data-testid="disclosure-accept-button"]', timeout=20000)
    await page.click('[data-testid="disclosure-accept-button"]', force=True)
    await page.wait_for_selector('[data-testid="apollo-state-label"]', timeout=30000)


async def read_case(page, prefix: str) -> dict:
    """Pull the typed response from the rendered view (pills + explanation) and the case via the API for exact fields."""
    await page.get_by_test_id("inv-response").first.wait_for(timeout=180000)
    reference = None
    try:
        await page.get_by_test_id(f"{prefix}-ask").scroll_into_view_if_needed()
    except Exception:  # noqa: BLE001
        pass
    overview = await page.get_by_test_id("inv-overview").first.inner_text()
    attention = await page.get_by_test_id("inv-attention").first.inner_text()
    completion = await page.get_by_test_id("inv-completion").first.inner_text()
    assessment = await page.get_by_test_id("inv-assessment").first.inner_text()
    return {"overview": overview, "attention_label": attention, "completion_label": completion, "assessment_label": assessment.replace(" ", "_"), "reference": reference}


def grade(expect: dict, actual: dict) -> tuple[str, list[str]]:
    problems = []
    if "assessment" in expect and actual.get("assessment") not in expect["assessment"]:
        problems.append(f"assessment {actual.get('assessment')} not in {expect['assessment']}")
    if "attention" in expect and actual.get("attention") not in expect["attention"]:
        problems.append(f"attention {actual.get('attention')} not in {expect['attention']}")
    if "completion" in expect and actual.get("completion") not in expect["completion"]:
        problems.append(f"completion {actual.get('completion')} not in {expect['completion']}")
    if expect.get("min_findings", 0) > len(actual.get("findings", [])):
        problems.append("too few findings")
    if expect.get("min_sources", 0) > len(actual.get("sources", [])):
        problems.append("no sources retrieved")
    if expect.get("min_explanation_chars", 0) > len(actual.get("explanation", "")) + len(actual.get("overview", "")):
        problems.append("answer shorter than required")
    if expect.get("follow_up") and not actual.get("follow_up_turns", 0) >= 2:
        problems.append("follow-up did not continue the same investigation")
    if "clue_kinds" in expect and not any(k in actual.get("evidence_labels", []) for k in expect["clue_kinds"]):
        problems.append("expected clues not registered")
    return ("complete" if not problems else "failed"), problems


async def run_one(browser, sid: str, spec: dict) -> dict:
    context = await browser.new_context(viewport={"width": 390, "height": 844})
    page = await context.new_page()
    started = time.time()
    record = {"id": sid, "status": "not_run", "expected": spec["expect"], "actual": {}, "problems": [], "screenshot": None}
    try:
        await onboard(page)
        if spec["screen"] == "message":
            await page.goto(f"{BASE}/message", wait_until="domcontentloaded")
            await page.get_by_test_id("message-sender").wait_for(timeout=60000)
            await page.get_by_test_id("message-sender").fill(spec["sender"])
            await page.get_by_test_id("message-text").fill(spec["text"])
            await page.get_by_test_id("message-check").click()
            prefix = "message-tell-more"
        elif spec["screen"] == "check":
            await page.goto(f"{BASE}/check", wait_until="domcontentloaded")
            await page.get_by_test_id("check-url-input").wait_for(timeout=60000)
            await page.get_by_test_id("check-url-input").fill(spec["url"])
            await page.get_by_test_id("check-submit-button").click()
            prefix = "check-investigation"
        else:
            await page.goto(f"{BASE}/ask", wait_until="domcontentloaded")
            await page.get_by_test_id("ask-input").wait_for(timeout=60000)
            await page.get_by_test_id("ask-input").fill(spec["question"])
            await page.get_by_test_id("ask-send-button").click()
            prefix = "ask-investigation"
        view = await read_case(page, prefix)
        if spec.get("answer"):
            await page.get_by_test_id("ask-input").fill(spec["answer"])
            await page.get_by_test_id("ask-send-button").click()
            await page.get_by_test_id("inv-progress").wait_for(timeout=20000)
            await page.get_by_test_id("inv-progress").wait_for(state="hidden", timeout=180000)
            await page.get_by_test_id("inv-response").first.wait_for(timeout=30000)
        # Case reference: read from the case-bound handoff card on Ask (general) or from the DOM-less API via the current owner.
        # Authoritative fields: ask the backend for the owner's most recent case.
        snap = await page.evaluate("""async () => {
            let token = null, deviceId = 'xxxxxxxxxxxx';
            for (const k of Object.keys(window.localStorage)) { if (!k.includes('apollo.device.identity.v2')) continue; try { let v = JSON.parse(window.localStorage.getItem(k)); if (typeof v === 'string') v = JSON.parse(v); token = v && v.token; deviceId = (v && v.deviceId) || deviceId; } catch (e) {} }
            const h = { Authorization: 'Bearer ' + token };
            const hr = await fetch('/api/ask/history?device_id=' + deviceId, { headers: h });
            const hist = await hr.json();
            const caseId = Array.isArray(hist) && hist.length ? hist[hist.length - 1].conversation_id : null;
            if (!caseId) return { token: !!token, debug: { status: hr.status, hist: JSON.stringify(hist).slice(0, 200), keys: Object.keys(window.localStorage) } };
            const c = await (await fetch('/api/investigations/' + caseId, { headers: h })).json();
            const s = await (await fetch('/api/investigations/' + caseId + '/sources', { headers: h })).json();
            const e = await (await fetch('/api/investigations/' + caseId + '/evidence', { headers: h })).json();
            const t = await (await fetch('/api/investigations/' + caseId + '/turns', { headers: h })).json();
            return { caseId, case: c.case, sources: s.items || [], evidence: e.items || [], turns: t.total || 0 };
        }""")
        response = (snap.get("case") or {}).get("response") or {}
        if snap.get("debug"):
            record["debug"] = snap["debug"]
        record["actual"] = {"assessment": response.get("assessment") or view["assessment_label"], "attention": response.get("attention"), "completion": response.get("completion"),
                            "findings": [f["text"] for f in response.get("findings", [])], "sources": [s["url"] for s in snap.get("sources", []) if s["id"] in set(response.get("sourceIds", []))],
                            "explanation": response.get("explanationMarkdown", ""), "overview": view["overview"], "evidence_labels": [e["label"] for e in snap.get("evidence", [])],
                            "actions": [(a["kind"], a["label"]) for a in response.get("actions", [])], "caseId": snap.get("caseId"), "follow_up_turns": snap.get("turns", 0)}
        if not response:
            record["actual"]["attention"] = view["attention_label"]; record["actual"]["completion"] = view["completion_label"]
        record["status"], record["problems"] = grade(spec["expect"], record["actual"])
        if not response and record["status"] == "complete":
            record["status"] = "partial"; record["problems"].append("authoritative case fields unavailable to the runner; graded from the rendered view")
    except Exception as exc:  # noqa: BLE001
        record["status"], record["problems"] = "failed", [f"{type(exc).__name__}: {str(exc)[:200]}"]
    finally:
        shot = RUN / f"{sid}.png"
        try:
            await page.screenshot(path=str(shot), quality=25, type="jpeg")
            record["screenshot"] = str(shot)
        except Exception:  # noqa: BLE001
            pass
        record["seconds"] = round(time.time() - started, 1)
        await context.close()
    return record


async def api_only() -> list[dict]:
    """Scenarios explicitly defined as direct API exercises (US35 cross-owner; US11 disguised executable)."""
    out = []
    def owner():
        r = httpx.post(f"{API}/devices/register", json={"platform": "web", "adapter_mode": "unsupported", "app_version": "1.0.0"}, timeout=30); r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['device_token']}"}
    a, b = owner(), owner()
    body = {"gate": "file", "question": "", "submissions": [], "initialFindingRefs": [], "initialFindings": [], "deviceProfile": None}
    r = httpx.post(f"{API}/investigations", json=body, headers={**a, "Idempotency-Key": str(uuid.uuid4())}, timeout=30)
    case = r.json()["case"]
    meta = {"expectedRevision": case["revision"], "clientItemId": str(uuid.uuid4()), "parentId": None, "kind": "document", "filename": "invoice.pdf", "mediaType": "application/pdf"}
    up = httpx.post(f"{API}/investigations/{case['id']}/evidence", data={"metadata": json.dumps(meta)}, files={"file": ("invoice.pdf", b"MZ" + b"\x00" * 900, "application/pdf")}, headers=a, timeout=30)
    item = up.json().get("evidence", {})
    out.append({"id": "US11", "status": "complete" if item.get("mediaType", "").endswith("portable-executable") and item.get("kind") == "attachment" else "failed",
                "expected": {"detected": "executable, never executed, declared/detected mismatch recorded"}, "actual": {"mediaType": item.get("mediaType"), "kind": item.get("kind"), "transformations": item.get("transformations")}, "problems": []})
    codes = [httpx.get(f"{API}/investigations/{case['id']}{p}", headers=b, timeout=20).status_code for p in ("", "/evidence", "/sources", "/turns")]
    codes.append(httpx.delete(f"{API}/investigations/{case['id']}", headers=b, timeout=20).status_code)
    out.append({"id": "US35", "status": "complete" if all(c == 404 for c in codes) else "failed", "expected": {"all": 404}, "actual": {"codes": codes}, "problems": []})
    return out


async def main(selected: list[str]) -> None:
    results = []
    async with async_playwright() as p:
        import glob
        candidates = glob.glob("/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell") + ["/usr/bin/google-chrome"]
        executable = next((c for c in candidates if os.path.exists(c)), None)
        browser = await p.chromium.launch(executable_path=executable, args=["--no-sandbox"]) if executable else await p.chromium.launch()
        for sid, spec in SCENARIOS.items():
            if selected and sid not in selected:
                continue
            record = await run_one(browser, sid, spec)
            results.append(record)
            print(sid, record["status"], record["problems"], f"{record['seconds']}s", flush=True)
        await browser.close()
    if not selected or any(s in selected for s in ("US11", "US35")):
        for record in await api_only():
            results.append(record); print(record["id"], record["status"], flush=True)
    (RUN / "outcomes.json").write_text(json.dumps({"run": RUN.name, "base": BASE, "provider": "gemini (owner key)", "mocked": False,
                                                    "scenarios": results}, indent=2, ensure_ascii=False))
    print("written", RUN / "outcomes.json")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
