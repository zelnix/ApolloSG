"""Cost routing: Higgins Triage → TC Hawkeye → Magnum DI.

- Triage extracts entities deterministically and plans only the relevant checks.
- TC Hawkeye stops as soon as a check is reliably resolved: an official listing, an official domain, Apollo's
  KB or one targeted Brave search read deterministically — TC Hawkeye makes no AI call, and then Magnum DI is never called.
- When Magnum DI is needed it receives the material plus TC Hawkeye's brief (not the raw lookups), with web
  search off unless a specific external fact is still missing. One Magnum call, no second model.
- Admin portal shows "Answered by" and the cost-routing measurements.

Run: cd /app/backend && python -m pytest tests/test_tc_flyby_routing.py -q
"""
import uuid
from datetime import datetime

import pytest
from starlette.requests import Request

from core.db import db
from routers import admin_portal
from services.higgins import ai_settings, jobs, provider
from services.higgins import evidence as ev
from services.higgins import repository as repo
from services.higgins.preview.preview_simulator import evidence_blocks, simulated_text
from services.higgins.provider import AIResult, Purpose
from services.higgins.tc_flyby import official, search, triage

pytestmark = pytest.mark.anyio
REAL_SEARCH = search.run   # captured before conftest's offline stub replaces it


# ── Triage ───────────────────────────────────────────────────────────────────
def test_triage_extracts_entities_and_plans_relevant_checks():
    text = ("Dear investor, Apex Horizon Capital Pty Ltd (ABN 51 824 753 556, AFSL 123456) offers guaranteed returns of 12% per month. "
            "Mr John Carter, our senior adviser, will call you on 0412 345 678. Join at https://apex-horizon.io/join or email "
            "support@apex-horizon.io. Reference 2026-06-05.")
    plan = triage.plan("Is this investment real?", [text])
    ent = plan.entities
    assert ent.hosts == ["apex-horizon.io"] and ent.emails == ["support@apex-horizon.io"]
    assert ent.abns == ["51824753556"] and ent.licences == [("AFSL", "123456")]
    assert ent.companies == ["Apex Horizon Capital Pty Ltd"] and ent.people == ["John Carter"]
    assert ent.phones == ["0412 345 678"], "dates, ABNs and licence numbers are not phone numbers"
    assert ent.claims and "guaranteed returns" in ent.claims[0]
    assert plan.message_type == "investment"
    kinds = [c.kind for c in plan.checks]
    for kind in ("link", "phone", "email", "company", "abn", "licence", "person", "claim", "scam_alerts", "message_analysis"):
        assert kind in kinds, kind
    assert all(c.question for c in plan.checks if c.kind in ("link", "phone", "email", "company", "abn", "licence", "person"))


def test_registration_number_check_digits():
    assert triage.abn_valid("51 824 753 556") and not triage.abn_valid("51 824 753 557")
    assert triage.acn_valid("004 085 616") and triage.acn_valid("010 499 966") and not triage.acn_valid("004 085 617")


def test_a_general_question_is_not_material_to_check():
    assert triage.plan("What is a PayID scam?", ["What is a PayID scam?"]).general
    assert not triage.plan("I got a text from my bank, is it real?", ["I got a text from my bank, is it real?"]).general
    assert not triage.plan("Check this", ["Pay $2.99 at https://auspost-redeliver.top now"]).general


# ── Harness ──────────────────────────────────────────────────────────────────
def _gateway(monkeypatch, flyby_text=None, flyby_grounding=None):
    """Gemini gateway replaced: TC Hawkeye's search purpose answers with `flyby_text`, Magnum's with the simulator."""
    calls: list[dict] = []

    async def fake(system, contents, **kwargs):
        calls.append(kwargs)
        if kwargs["purpose"] == Purpose.TC_FLYBY_SEARCH:
            text, grounding = flyby_text or "", flyby_grounding
        else:
            text, grounding = simulated_text(Purpose.INVESTIGATION, True, evidence_blocks(contents)), None
        return AIResult(text=text, finish_reason="STOP",
                            usage={"prompt_token_count": 10, "candidates_token_count": 5, "total_token_count": 15}, grounding=grounding,
                            model=kwargs.get("model") or "gemini-3.1-flash-lite")

    monkeypatch.setattr(provider, "generate", fake)
    return calls


async def _case(items: list[tuple[str, str]], *, message="Is this real?", pregathered=None):
    owner = f"flyby-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "text", None)
    for n, (kind, value) in enumerate(items):
        if kind == "url":
            await ev.ingest_url(owner, case, f"item-{n}", value)
        else:
            await ev.ingest_text(owner, case, f"item-{n}", value, kind="text", origin="user_submission", label="Submitted message text")
    if pregathered:
        await db.investigation_cases.update_one({"owner_id": owner, "case_id": case["case_id"]}, {"$set": {"triage_provider_evidence": pregathered}})
    case = await repo.get_case(owner, case["case_id"])
    turn_id = str(uuid.uuid4())
    job = await repo.create_job(owner, case, turn_id, repo.digest(turn_id), repo.digest("p"), "turn", {"message": message, "turnId": turn_id})
    await repo.cas(owner, case["case_id"], {"revision": case["revision"]}, {"$set": {"active_job_id": job["job_id"], "active_turn_id": turn_id, "status": "queued"}})
    await jobs.run(owner, case["case_id"], job["job_id"])
    events = await repo.events_after(owner, job["job_id"], 0)
    response = next((e["payload"]["response"] for e in events if e["type"] == "response"), None)
    stored = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case["case_id"]}, {"_id": 0})
    return owner, stored, response, events


PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc"
       b"\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _files_case(files: list[tuple[dict, bytes]], *, message="Is this real?"):
    """A case built from uploaded files (screenshots, documents), run through the real job."""
    owner = f"flyby-file-{uuid.uuid4().hex[:8]}"
    await repo.ensure_indexes()
    case = await repo.create_case(owner, "vision", None)
    for meta, data in files:
        await ev.ingest_file(owner, case, meta, data)
    case = await repo.get_case(owner, case["case_id"])
    turn_id = str(uuid.uuid4())
    job = await repo.create_job(owner, case, turn_id, repo.digest(turn_id), repo.digest("p"), "turn", {"message": message, "turnId": turn_id})
    await repo.cas(owner, case["case_id"], {"revision": case["revision"]}, {"$set": {"active_job_id": job["job_id"], "active_turn_id": turn_id, "status": "queued"}})
    await jobs.run(owner, case["case_id"], job["job_id"])
    events = await repo.events_after(owner, job["job_id"], 0)
    response = next((e["payload"]["response"] for e in events if e["type"] == "response"), None)
    stored = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case["case_id"]}, {"_id": 0})
    return owner, stored, response


def _spy(monkeypatch) -> list:
    """Captures what Magnum DI is sent (on top of _gateway)."""
    captured: list = []
    original = provider.generate

    async def spy(system, contents, **kwargs):
        if kwargs["purpose"] == Purpose.INVESTIGATION:
            captured.append([p for p in contents[0].parts])
        return await original(system, contents, **kwargs)

    monkeypatch.setattr(provider, "generate", spy)
    return captured


def _lookups(monkeypatch, *, verdict="clean", threats=(), age_days=4000):
    async def url(u):
        return {"verdict": verdict, "threatTypes": list(threats), "coverage": "full",
                "sources": [{"name": "google_safe_browsing", "status": "match" if verdict == "malicious" else "clear"}],
                "checkedAt": "2026-06-05T00:00:00+00:00"}

    async def domain(d):
        return {"registeredAt": "2015-01-01T00:00:00+00:00" if age_days > 365 else "2026-06-01T00:00:00+00:00",
                "ageDays": age_days, "registrar": "Example", "newlyRegistered": age_days < 30}

    monkeypatch.setattr(official, "lookup_url", url)
    monkeypatch.setattr(official, "lookup_domain", domain)
    # ASIC's real investor alert list names some placeholder numbers (0412 345 678): these cases are about other rules.
    from services import threat_feeds

    async def not_listed(_scope, _value):
        return []
    monkeypatch.setattr(threat_feeds, "listed", not_listed)
    # Earlier runs leave cross-device sightings of these same test links in the shared database; each case here is
    # about its own evidence only (observed intelligence has its own tests in test_free_kb_phases_3_5.py).
    from services import observed_intel

    async def not_seen(*_args, **_kwargs):
        return None

    async def none_related(*_args, **_kwargs):
        return []
    monkeypatch.setattr(observed_intel, "assertion", not_seen)
    monkeypatch.setattr(observed_intel, "related", none_related)


def _grounded(lines: list[str], urls: list[tuple[str, str]]) -> tuple[str, dict]:
    """Answer lines with each line supported by the matching (url, domain) chunk."""
    text = "\n".join(lines)
    supports, offset = [], 0
    for index, line in enumerate(lines):
        supports.append({"segment": {"start_index": offset, "end_index": offset + len(line.encode()), "text": line}, "grounding_chunk_indices": [index]})
        offset += len(line.encode()) + 1
    chunks = [{"web": {"uri": u, "title": d, "domain": d}} for u, d in urls]
    return text, {"grounding_chunks": chunks, "grounding_supports": supports, "web_search_queries": ["q"] * len(lines)}


# ── TC Hawkeye settles it: Magnum DI is never called ──────────────────────────
async def test_an_official_listing_settles_the_case_without_gemini(monkeypatch):
    calls = _gateway(monkeypatch)
    _lookups(monkeypatch, verdict="malicious", threats=["SOCIAL_ENGINEERING"])
    owner, case, response, _ = await _case([("text", "ANZ: your card is locked. Verify now at https://anz-verify.co/login")])
    assert calls == [], "a reliable official listing is not confirmed by Gemini"
    assert response["assessment"] == "concern_found" and response["attention"] == "action_needed"
    assert response["outcome"] == "scam" and case["routing"]["outcome"] == "scam"
    assert "Google Safe Browsing lists anz-verify.co" in response["overview"]
    assert response["findings"][0]["basis"] == "observation" and response["findings"][0]["evidenceIds"]
    assert any(a["label"] == "Don't open the link" for a in response["actions"])
    assert case["routing"]["answeredBy"] == "tc_flyby_official" and case["routing"]["tc_flyby"]["resolved"] is True
    assert case["routing"]["assessment"] == "concern_found" and "magnum" not in case["routing"]
    commit = await db.investigation_turn_commits.find_one({"owner_id": owner, "case_id": case["case_id"]})
    assert commit, "TC Hawkeye's result is committed through the same turn commit as Magnum DI's"


async def test_an_official_government_link_is_cleared_without_gemini(monkeypatch):
    calls = _gateway(monkeypatch)
    _lookups(monkeypatch)
    _owner, case, response, _ = await _case([("url", "https://www.ato.gov.au/individuals/lodging-your-tax-return")], message="Is this link safe?")
    assert calls == []
    assert response["assessment"] == "no_concern_found_within_scope" and response["attention"] == "none"
    assert response["outcome"] == "not_scam"
    assert "Australian Taxation Office's official domain" in response["overview"]
    assert "That settles who the address belongs to" in response["overview"] and "nothing here needs action" not in response["overview"]
    assert case["routing"]["answeredBy"] == "tc_flyby_official"


async def test_a_general_question_is_answered_from_apollo_kb(monkeypatch):
    from services.higgins import knowledge
    calls = _gateway(monkeypatch)
    await knowledge.ensure_indexes()
    await knowledge.upsert("official_guidance", f"test-payid-{uuid.uuid4().hex[:6]}", title="PayID scams: how they work",
                           body="PayID scams trick sellers into believing a payment is pending until they pay a fee.\n\nNever pay to receive money.",
                           publisher="Scamwatch (ACCC)", authority_tier="tier_1_authoritative", jurisdiction="AU",
                           url="https://www.scamwatch.gov.au/types-of-scams/payid-scams")
    _owner, case, response, _ = await _case([("text", "How do PayID scams work?")], message="How do PayID scams work?")
    assert calls == []
    assert case["routing"]["answeredBy"] == "tc_flyby_kb"
    assert "PayID scams trick sellers" in response["explanationMarkdown"] and response["findings"] == []
    assert "general information, not a finding" in response["explanationMarkdown"]
    assert response["outcome"] is None, "a general question has no case outcome"


def _brave(monkeypatch, results_for):
    """TC Hawkeye's Brave search replaced: `results_for(query)` gives the pages. Every request is recorded; none leaves the test."""
    monkeypatch.setattr(search, "run", REAL_SEARCH)
    monkeypatch.setattr(search.brave_search, "configured", lambda: True)
    queries: list[dict] = []

    async def fake(q, **kwargs):
        queries.append({"q": q, **kwargs})
        return results_for(q)

    monkeypatch.setattr(search.brave_search, "search", fake)
    return queries


ALERT_PAGE = {"url": "https://moneysmart.gov.au/check-and-report-scams/investor-alert-list", "title": "Investor Alert List",
              "description": "Zenith Quantum Markets is on ASIC's Investor Alert List (added March 2026). Do not deal with this company.",
              "extraSnippets": []}


async def test_a_targeted_search_finding_an_official_warning_stops(monkeypatch):
    await db.reusable_intelligence.delete_many({"source_type": "tc_flyby_lookup"})
    queries = _brave(monkeypatch, lambda q: [ALERT_PAGE] if "Zenith Quantum Markets" in q else [])
    calls = _gateway(monkeypatch)
    owner, case, response, _ = await _case([("text", "Zenith Quantum Markets offers 3% daily returns. Message us on WhatsApp to start.")])
    assert calls == [], "TC Hawkeye makes no AI call, and Magnum DI isn't needed"
    assert len(queries) == 1 and "Zenith Quantum Markets" in queries[0]["q"], "one Brave search for the case"
    assert queries[0]["correlation_id"] == f"case-{case['case_id']}" and queries[0]["device_id"] == owner
    assert response["assessment"] == "concern_found" and "Investor Alert List" in response["overview"]
    assert response["outcome"] == "scam", "the planned search ran before TC Hawkeye settled the outcome"
    assert response["findings"][0]["sourceIds"], "the warning keeps its source"
    assert case["routing"]["answeredBy"] == "tc_flyby_search"
    flyby = case["routing"]["tc_flyby"]
    assert flyby["searchCalls"] == 1 and flyby["searchQueries"] == 1 and flyby["searchProvider"] == "brave" and flyby["aiCalls"] == 0

    # The same lookup in another case is reused from ApolloSG's earlier search: no second paid search.
    queries.clear()
    owner2, case2, response2, _ = await _case([("text", "Zenith Quantum Markets: 3% daily returns, guaranteed.")])
    assert queries == [] and calls == [] and case2["routing"]["tc_flyby"]["cacheHits"] == 1
    assert response2["assessment"] == "concern_found"
    # The reused lookup's page is shown with the time Apollo last checked it, not as a new lookup.
    first, later = await repo.sources(owner, case["case_id"]), await repo.sources(owner2, case2["case_id"])
    searched = [s for s in first if "investor-alert-list" in s["url"]]
    reused = [s for s in later if "investor-alert-list" in s["url"]]
    assert searched and not any(s["reused"] for s in first)
    assert reused and all(s["reused"] for s in reused) and not any(s["reused"] for s in later if s not in reused)
    assert datetime.fromisoformat(reused[0]["retrievedAt"]) <= datetime.fromisoformat(searched[0]["retrievedAt"]), "when it was last checked"


# ── Magnum DI receives only the unresolved slice ────────────────────────────
# A payment request through a route nobody verified, that no Higgins Triage rule flags: only Magnum DI's reasoning could
# change what to do. (Once Triage flags a message, TC Hawkeye settles it as Concerning — test_unified_energy_sms.py.)
INVOICE = ("Hi, it's Sarah from Brightline Accounts. Please pay invoice 4471 ($1,240) to "
           "account 1234 5678 today. The invoice is at https://brightline-docs.net/inv/4471")


async def test_magnum_gets_only_the_unresolved_issue_and_tc_flybys_brief_with_search_off(monkeypatch):
    await db.reusable_intelligence.delete_many({"source_type": "tc_flyby_lookup"})
    queries = _brave(monkeypatch, lambda q: [{"url": "https://example.com/brightline", "title": "brightline-docs.net",
                                              "description": "brightline-docs.net document sharing", "extraSnippets": []}])
    calls = _gateway(monkeypatch)
    _lookups(monkeypatch)
    captured = _spy(monkeypatch)
    pregathered = {"safe_browsing": {"urls": {"https://brightline-docs.net/inv/4471": {"verdict": "clean", "status": "ok", "queried_at": "2026-06-05"}}},
                   "_summary": {"providers_consulted": ["safe_browsing"], "total_lookups": 1}}
    _owner, case, response, _ = await _case([("text", INVOICE)], pregathered=pregathered)
    purposes = [c["purpose"] for c in calls]
    assert purposes == [Purpose.INVESTIGATION] and len(queries) == 1, "TC Hawkeye's one Brave search (no AI), then Magnum DI's one call"
    magnum = calls[0]
    assert magnum["web_search"] is False, "TC Hawkeye already has the external facts, so Magnum's Google Search is off"
    assert magnum["model"] == await ai_settings.investigation_model(), "the existing configured model — no escalation"
    assert "outcome" in magnum["response_schema"]["required"], "Magnum DI feeds the same outcome system"
    sent = [p.text for p in captured[0] if p.text]
    assert any("TC Hawkeye fly-by results" in t and "For Magnum DI to settle" in t for t in sent)
    assert any("(reasoning) Message and deception analysis" in t and "payment (“" in t for t in sent), "only the unresolved issue"
    assert not any("apollo-triage-intelligence" in t or '"safe_browsing"' in t for t in sent), "raw lookups TC Hawkeye settled are not resent"
    assert any("Please pay invoice 4471" in t for t in sent), "the material the issue is about is sent in full"
    flyby = case["routing"]["tc_flyby"]
    assert [i["capability"] for i in flyby["issues"]] == ["reasoning"]
    assert {c["kind"]: c["status"] for c in flyby["checks"]}["message_analysis"] == "needs_reasoning"
    assert case["routing"]["answeredBy"] == "magnum_di" and case["routing"]["magnum"]["search"] is False
    assert response is not None and response["outcome"] and case["routing"]["outcome"] == response["outcome"]


async def test_a_newly_registered_link_is_a_weak_signal_never_concerning(monkeypatch):
    """No fixed list sends a message to Magnum DI, and a newly registered domain is a weak signal: alone it never makes
    a case Concerning. It is recorded, and the case is Not a Scam (ordinary, unverified, score-only boundary — rule
    book, TC Hawkeye weak signals, reverted on direct instruction)."""
    calls = _gateway(monkeypatch)
    _lookups(monkeypatch, age_days=6)
    _owner, case, response, _ = await _case([("text", "Hi, it's Sarah from the conference. Here are the slides you asked for: https://slides-deck.net/deck")])
    assert calls == [], "Magnum DI couldn't change the finding or what to do"
    assert response["outcome"] == "not_scam"
    assert any("registered on 2026-06-01" in f["text"] for f in response["findings"]), "the weak signal is still listed among the findings"
    # Offline, the link's targeted search is unavailable: the gap and the weak signal are both named, nothing broader.
    assert {c["kind"]: c["status"] for c in case["routing"]["tc_flyby"]["checks"]}["link"] == "unavailable"
    assert case["routing"]["tc_flyby"]["issues"] == [] and case["routing"]["tc_flyby"]["basis"] == "clear"


async def test_a_plain_message_asking_nothing_is_settled_without_magnum(monkeypatch):
    calls = _gateway(monkeypatch)
    _owner, case, response, _ = await _case([("text", "Hey, are we still on for dinner on Friday? Let me know what time suits.")])
    assert calls == []
    assert response["outcome"] == "not_scam" and response["assessment"] == "no_concern_found_within_scope"
    flyby = case["routing"]["tc_flyby"]
    assert flyby["resolved"] is True and flyby["issues"] == []
    assert {c["kind"]: c["status"] for c in flyby["checks"]}["message_analysis"] == "not_needed"
    assert (await repo.case_view(case)).wire()["answeredBy"] == flyby["answeredBy"] == "tc_flyby_kb", "the app is told who settled it"
    assert (await repo.case_view(case)).wire()["simulated"] is False, "nothing outside was simulated"
    assert (await repo.case_view({**case, "routing": {**case["routing"], "tc_flyby": {**flyby, "simulated": True}}})).wire()["simulated"] is True
    assert (await repo.case_view({**case, "routing": {**case["routing"], "magnum": {"simulated": True}}})).wire()["simulated"] is True


async def test_a_screenshot_is_investigated_through_the_text_triage_extracted(monkeypatch):
    calls = _gateway(monkeypatch)
    meta = {"clientItemId": "shot", "filename": "shot.png", "mediaType": "image/png", "kind": "image",
            "deviceExtractedText": "Hi Mum, I dropped my phone in the pool so this is my new number. Can you transfer $300 for the repair today?"}
    owner, case, response = await _files_case([(meta, PNG)])
    assert calls == [], "Triage extracted the screenshot's text; a full KB pattern match settles it"
    assert response["outcome"] == "likely_scam" and response["completion"] == "complete"
    flyby = case["routing"]["tc_flyby"]
    assert flyby["gaps"] == [] and flyby["pattern"] == {"key": "family_new_number", "stage": "full"}
    image = next(r for r in await repo.list_evidence(owner, case["case_id"]) if r["kind"] == "image")
    assert image["coverage"]["status"] == "examined", "the image was examined through the text read from it"


async def test_a_document_is_investigated_through_its_text_layer(monkeypatch):
    import io
    import docx
    calls = _gateway(monkeypatch)
    document = docx.Document()
    document.add_paragraph("Hi Mum, I lost my phone so this is my new number. Could you please send $450 for the rent today?")
    buffer = io.BytesIO()
    document.save(buffer)
    meta = {"clientItemId": "letter", "filename": "letter.docx", "mediaType": DOCX, "kind": "document"}
    _owner, case, response = await _files_case([(meta, buffer.getvalue())])
    assert calls == [] and response["outcome"] == "likely_scam"
    assert case["routing"]["tc_flyby"]["gaps"] == []


async def test_an_image_tc_flyby_cannot_read_goes_to_magnum_with_search_on(monkeypatch):
    calls = _gateway(monkeypatch)
    captured = _spy(monkeypatch)
    _owner, case, _response = await _files_case([({"clientItemId": "shot", "filename": "shot.png", "mediaType": "image/png", "kind": "image"}, PNG)])
    assert [c["purpose"] for c in calls] == [Purpose.INVESTIGATION]
    assert calls[0]["web_search"], "Magnum DI reads the image for the first time, so external facts may be missing: Search on"
    flyby = case["routing"]["tc_flyby"]
    assert flyby["magnumSearch"] is True and [i["capability"] for i in flyby["issues"]] == ["reading"]
    assert any(p.data is not None for p in captured[0]), "the image itself is what Magnum DI receives"


async def test_a_magnum_retry_reuses_tc_flybys_record(monkeypatch):
    from services.higgins import tc_flyby
    _lookups(monkeypatch)
    owner = f"flyby-retry-{uuid.uuid4().hex[:8]}"
    case = await repo.create_case(owner, "text", None)
    await ev.ingest_text(owner, case, "m", INVOICE, kind="text", origin="user_submission")
    case = await repo.get_case(owner, case["case_id"])
    job = {"job_id": "j", "source": "user_initiated"}

    async def progress(*_a):
        return None

    rows = await repo.list_evidence(owner, case["case_id"])
    first = await tc_flyby.investigate(owner, case, job, "Is this real?", rows, progress)
    second = await tc_flyby.investigate(owner, case, job, "Is this real?", rows, progress)
    assert not first.resolved and [r["evidence_id"] for r in first.rows] == [r["evidence_id"] for r in second.rows]
    stored = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case["case_id"]}, {"_id": 0, "routing": 1})
    assert stored["routing"]["tc_flyby"]["reusedOnRetry"] == 1
    briefs = [r for r in await repo.list_evidence(owner, case["case_id"]) if r["client_item_id"] == tc_flyby.BRIEF_ITEM_ID]
    assert len(briefs) == 1


# ── Admin portal: Answered by + cost routing measurements ──────────────────
async def test_admin_report_shows_answered_by_and_routing(monkeypatch):
    _gateway(monkeypatch)
    _lookups(monkeypatch, verdict="malicious", threats=["MALWARE"])
    _owner, case, _response, _ = await _case([("text", "Your parcel is held: https://auspost-held.top/pay")])

    async def admin(_request):
        return {"email": "owner@example.com", "name": "Owner"}

    async def no_audit(*_a, **_k):
        return None

    monkeypatch.setattr(admin_portal, "_admin", admin)
    monkeypatch.setattr(admin_portal, "_audit_log", no_audit)
    request = Request({"type": "http", "method": "GET", "path": "/api/admin/investigations-cost", "query_string": b"period=all", "headers": []})
    page = await admin_portal.investigations_cost_report(request)
    assert "Answered By" in page and 'data-testid="answered-by-tc_flyby_official"' in page and ">Official check</span>" in page
    assert 'data-testid="outcome-scam"' in page and "This is a scam" in page and "<th>Outcome</th>" in page
    assert 'data-testid="cost-routing-heading"' in page and "Resolved Without Magnum DI" in page and "Repeated Searches Avoided" in page
    drill = await admin_portal.investigation_drilldown(request, case["case_id"])
    assert "Cost Routing" in drill and ">Official check</span>" in drill and "Not called" in drill
    assert 'data-testid="outcome-scam"' in drill


# ── When a case is resolved at TC Hawkeye (Apollo's outcome criteria) ─────────
async def test_impersonation_with_a_brand_new_domain_is_concerning_without_gemini(monkeypatch):
    calls = _gateway(monkeypatch)
    _lookups(monkeypatch, age_days=6)
    _owner, case, response, _ = await _case([("text", "CommBank: please read the notice about your account changes at https://commbank-notice.net/info")])
    assert calls == [], "Magnum DI couldn't change the finding or what to do"
    assert response["outcome"] == "likely_scam" and response["assessment"] == "concern_found"
    assert "isn't CommBank's domain" in response["overview"] and "registered on 2026-06-01" in response["overview"]
    assert "commbank-notice.net isn't one of CommBank's published domains" in response["explanationMarkdown"]
    assert "no reason to send you" not in response["explanationMarkdown"]
    assert response["attentionReason"] == ("Anything typed into that link goes to whoever runs commbank-notice.net, which isn't one of "
                                           "CommBank's published domains.")
    assert any(a["label"] == "Don't use the link" for a in response["actions"])
    assert "So these weren't taken further:" in response["explanationMarkdown"] and "deception analysis" in response["explanationMarkdown"]
    assert not any("TC Hawkeye" in u or "Not taken further" in u for u in response["uncertainties"]), "how Apollo checked is on the DI tab"
    assert case["routing"]["answeredBy"] == "tc_flyby_official" and case["routing"]["tc_flyby"]["basis"] == "impersonation"
    assert "magnum" not in case["routing"]


async def test_a_message_matching_a_kb_scam_pattern_is_likely_scam_without_gemini(monkeypatch):
    calls = _gateway(monkeypatch)
    _owner, case, response, _ = await _case([("text", "Hi Mum, I dropped my phone in the pool so this is my new number. "
                                                      "Can you transfer $300 for the repair today? I'll pay you back")])
    assert calls == []
    assert response["outcome"] == "likely_scam" and response["attention"] == "action_needed"
    assert "Scamwatch" in response["overview"] and "new number" in response["overview"]
    quoted = " ".join(f["text"] for f in response["findings"])
    assert "“Hi Mum”" in quoted and "$300" in quoted, "the findings are the material's own words"
    assert all(f["basis"] == "observation" and f["evidenceIds"] for f in response["findings"])
    assert "isn't proof that this particular sender is a scammer" in response["explanationMarkdown"]
    assert response["sourceIds"], "the KB pattern keeps its official source"
    assert any(a["label"] == "Call them on their usual number" for a in response["actions"])
    assert case["routing"]["answeredBy"] == "tc_flyby_kb" and case["routing"]["tc_flyby"]["pattern"] == {"key": "family_new_number", "stage": "full"}
    assert await db.higgins_knowledge.count_documents({"kind": "scam_pattern", "key": "family_new_number"}) == 1, "the pattern lives in Apollo's KB"


async def test_the_opening_of_a_kb_pattern_is_concerning(monkeypatch):
    calls = _gateway(monkeypatch)
    _owner, _case_doc, response, _ = await _case([("text", "Hi Mum, this is my new number. Save it and delete the old one x")])
    assert calls == [] and response["outcome"] == "likely_scam" and response["attention"] == "review"
    assert "hasn't asked for anything yet" in response["overview"]


async def test_an_unclear_pattern_match_goes_to_magnum(monkeypatch):
    calls = _gateway(monkeypatch)
    captured: list = []
    original = provider.generate

    async def spy(system, contents, **kwargs):
        captured.append(contents)
        return await original(system, contents, **kwargs)

    monkeypatch.setattr(provider, "generate", spy)
    _owner, case, response, _ = await _case([("text", "Hi Mum, can you send me $50 for lunch?")])
    assert [c["purpose"] for c in calls] == [Purpose.INVESTIGATION]
    sent = [p.text for p in captured[0][0].parts if p.text]
    assert any("partly matches the family member" in t for t in sent)
    assert case["routing"]["tc_flyby"]["pattern"]["stage"] == "partial" and case["routing"]["answeredBy"] == "magnum_di"
    assert response["outcome"]


async def test_a_pattern_contradicted_by_official_links_is_settled_by_the_deciding_test(monkeypatch):
    calls = _gateway(monkeypatch)
    _lookups(monkeypatch)
    _owner, case, response, _ = await _case([("text", "AusPost: your parcel is held. Pay the $2.50 redelivery fee at https://auspost.com.au/redeliver")])
    assert calls == [], "the request goes to AusPost's own domain: nothing Magnum DI could add changes what to do"
    assert response["outcome"] == "not_scam"
    pattern = case["routing"]["tc_flyby"]["pattern"]
    assert pattern == {"key": "delivery_toll", "stage": "partial"}, "an impersonation pattern needs a link that isn't the organisation's own"

    calls.clear()   # the same wording, but the money goes somewhere nobody verified: Magnum DI's analysis could change the action
    _owner, case, _response, _ = await _case([("text", "AusPost: your parcel is held. Pay the $2.50 redelivery fee by PayID to 0412 345 678. "
                                                       "Track it at https://auspost.com.au/redeliver")])
    assert [c["purpose"] for c in calls] == [Purpose.INVESTIGATION]
    assert [i["capability"] for i in case["routing"]["tc_flyby"]["issues"]] == ["reasoning"]


async def test_isolated_keywords_never_make_a_pattern_match():
    from services.higgins.tc_flyby import patterns
    assert await patterns.best("Your parcel delivery is booked for Tuesday. Toll roads may be busy, so pay attention.", has_link=False,
                               has_brand=False, offsite=None) is None
    negated = await patterns.best("CommBank will never ask you to log in via a link to verify your account details. Your account is suspended "
                                  "only if you tell us.", has_link=True, has_brand=True, offsite=True)
    assert negated is None or negated.stage != "full", "a negated request is not a request"
    full = await patterns.best("Hi Dad, I broke my phone, this is my new number. Can you send me $200?", has_link=False, has_brand=False, offsite=None)
    assert full.stage == "full" and full.entry["pattern"]["key"] == "family_new_number"


async def test_a_lookalike_bare_link_follows_the_same_rule(monkeypatch):
    calls = _gateway(monkeypatch)
    _lookups(monkeypatch)
    _owner, case, response, _ = await _case([("url", "https://commbank-secure-login.net/")], message="Is this link safe?")
    assert calls == [] and response["outcome"] == "likely_scam"
    assert response["overview"] == "Do not click or open that link."


async def test_a_bare_link_ends_concerning_or_unable_to_determine_without_gemini(monkeypatch):
    calls = _gateway(monkeypatch)
    _lookups(monkeypatch, age_days=6)
    _owner, case, response, _ = await _case([("url", "https://fresh-deals.shop/promo")], message="Is this link safe?")
    # A newly registered domain is a weak signal: recorded, never Concerning on its own. Nothing was
    # positively verified either, but the score-only boundary contract (reverted on direct instruction)
    # still reads this real, low score as "Not a Scam".
    assert calls == [] and response["outcome"] == "not_scam" and response["assessment"] == "no_concern_found_within_scope"
    assert any("registered on 2026-06-01" in f["text"] for f in response["findings"])
    calls.clear()   # now nothing can be checked: every lookup and the search are unavailable
    from services.higgins.tc_flyby import search as tc_flyby_search

    async def unavailable(checks, **_k):
        return {"answers": {c.id: {"status": "UNAVAILABLE", "fact": "", "sources": []} for c in checks}, "calls": 0, "queries": 0,
                "cacheHits": 0, "tokens": {"input": 0, "output": 0}, "simulated": False, "model": None, "status": "unavailable"}

    async def none(*_a):
        return None

    monkeypatch.setattr(tc_flyby_search, "run", unavailable)
    monkeypatch.setattr(official, "lookup_url", none)
    monkeypatch.setattr(official, "lookup_domain", none)
    _owner, case, response, _ = await _case([("url", "https://quietbrook-gardens.net/")], message="Is this link safe?")
    assert calls == [], "Magnum DI can't open the page either: nothing it could add"
    assert response["outcome"] == "not_scam" and response["assessment"] == "no_concern_found_within_scope"
    assert case["routing"]["outcome"] == "not_scam" and case["routing"]["tc_flyby"]["resolved"] is True


def test_magnums_outcome_must_agree_with_its_assessment():
    from services.higgins.validation import validate
    base = {"overview": "x", "explanationMarkdown": "y", "attention": "review", "attentionReason": None, "findings": [], "uncertainties": [],
            "scope": "", "sourceIds": [], "remainingEvidenceIds": [], "actions": [], "recommendedActionIndex": None, "question": None,
            "completion": "complete"}
    kwargs = {"revision": 1, "evidence_ids": set(), "source_ids": set(), "capability_ids": set(), "pending_question": None, "provider_complete": True}
    response, errors = validate({**base, "assessment": "uncertain", "outcome": "likely_scam"}, **kwargs)
    assert response is None and any("outcome 'likely_scam' requires assessment 'concern_found'" in e for e in errors)
    response, errors = validate({**base, "assessment": "uncertain", "outcome": "unable_to_determine"}, **kwargs)
    assert errors == [] and response.outcome == "unable_to_determine"
