"""Reusable intelligence (services/reusable_intel.py): what Apollo's approved providers already told it, reused
before paying to ask again — kept apart from the authoritative Apollo KB and from private case evidence.

Covers: the cache record and its metadata, subject keys, freshness, reuse at every paid call site (Higgins' general
Gemini answer, TC FlyBy's grounded search, IPQualityScore phone and link reputation, RDAP), the KB boundary (AI
output never promoted), evidence isolation, moving the KB's old saved Gemini answers, observability (counters and
the admin portal) and the KB retrieval benchmark baseline. Every external call is replaced and counted.

Run: cd /app/backend && python -m pytest tests/test_reusable_intel.py -q
"""
import html
import json
import logging
import re
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from starlette.requests import Request

from core.db import db, now_utc
from core.models import DomainInfo
from routers import admin_portal
from services import kb_benchmark, phonerisk, rdap, sufficiency, urlrisk
from services import reusable_intel as intel
from services.higgins import chat, presenter, knowledge, provider
from services.higgins import tc_flyby
from services.higgins.tc_flyby import report, search
from services.higgins.tc_flyby.triage import Check

BACKEND = Path(__file__).resolve().parents[1]
REAL_SEARCH = search.run  # captured before conftest's offline stub replaces it
QUESTION = "Why do scammers ask for gift cards?"
ANSWER = "Gift cards are hard to trace and can't be reversed once the numbers are shared."


@pytest.fixture
async def store(monkeypatch):
    """The cache, its counters and a KB stand-in in collections of their own, so each test starts empty."""
    tag = uuid.uuid4().hex[:10]
    fake = SimpleNamespace(reusable_intelligence=db[f"test_intel_{tag}"], intel_reuse_metrics=db[f"test_intel_metrics_{tag}"],
                           higgins_knowledge=db[f"test_intel_kb_{tag}"], intel_inflight=db[f"test_intel_inflight_{tag}"])
    monkeypatch.setattr(intel, "db", fake)
    monkeypatch.setattr(intel, "_indexed", False)
    yield fake
    for coll in (fake.reusable_intelligence, fake.intel_reuse_metrics, fake.higgins_knowledge, fake.intel_inflight):
        await coll.drop()


async def counts(fake, site: str) -> dict:
    doc = await fake.intel_reuse_metrics.find_one({"day": now_utc().strftime("%Y-%m-%d"), "site": site}, {"_id": 0})
    return (doc or {}).get("counts", {})


def second(value):
    return value.replace(microsecond=0)


# ── The cache record ─────────────────────────────────────────────────────────
async def test_a_saved_result_carries_its_full_metadata(store):
    key = intel.subject_key("domain", "example-scam.top")
    cid = await intel.put(key, intel.BRAVE_SEARCH, intel.TC_FLYBY_LOOKUP, "web_lookup", {"status": "WARNING", "fact": "Listed."},
                          knowledge_class="search_result_lookup", ai_generated=False, provenance={"provider": "brave"})
    row = await store.reusable_intelligence.find_one({"cache_id": cid}, {"_id": 0})
    for field in ("cache_id", "subject_key", "provider", "source_type", "created_at", "last_verified_at", "expires_at", "knowledge_class"):
        assert row.get(field), field
    assert (row["subject_key"], row["provider"], row["source_type"], row["info_type"]) == (key, "brave_search", "tc_flyby_lookup", "web_lookup")
    assert row["ai_generated"] is False and row["authoritative"] is False and row["simulated"] is False and row["hits"] == 0
    assert row["expires_at"] - row["last_verified_at"] == intel.TTL["web_lookup"]
    assert row["purge_at"] - row["expires_at"] == intel.STALE_KEPT_FOR
    assert row["provenance"] == {"provider": "brave"}


async def test_reverifying_keeps_when_it_was_first_obtained_and_moves_its_expiry(store):
    key = intel.subject_key("domain", "example-scam.top")
    first, later = second(now_utc() - timedelta(days=3)), second(now_utc())
    args = (key, intel.GEMINI_SEARCH, intel.TC_FLYBY_LOOKUP, "web_lookup")
    await intel.put(*args, {"status": "WARNING"}, knowledge_class="grounded_lookup", ai_generated=True, verified_at=first)
    await intel.put(*args, {"status": "WARNING", "fact": "still listed"}, knowledge_class="grounded_lookup", ai_generated=True, verified_at=later)
    rows = await store.reusable_intelligence.find({"subject_key": key}).to_list(5)
    assert len(rows) == 1, "one record per subject, provider and process"
    assert (rows[0]["created_at"], rows[0]["last_verified_at"], rows[0]["expires_at"]) == (first, later, later + intel.TTL["web_lookup"])
    assert rows[0]["payload"]["fact"] == "still listed"


async def test_preview_and_live_results_never_share_a_record(store):
    key = intel.subject_key("domain", "example-scam.top")
    await intel.put(key, intel.GEMINI_SEARCH, intel.TC_FLYBY_LOOKUP, "web_lookup", {"status": "WARNING"},
                    knowledge_class="grounded_lookup", ai_generated=True, simulated=True)
    assert await intel.find(key, intel.GEMINI_SEARCH, intel.TC_FLYBY_LOOKUP) == []
    assert len(await intel.find(key, intel.GEMINI_SEARCH, intel.TC_FLYBY_LOOKUP, simulated=True)) == 1
    assert intel.cache_id(key, "p", "s", True) != intel.cache_id(key, "p", "s", False)


def test_freshness_comes_from_one_table():
    assert set(intel.TTL) == {"general_answer", "web_lookup", "web_lookup_negative", "phone_reputation", "url_reputation", "domain_registration"}
    assert intel.TTL["web_lookup_negative"] < intel.TTL["web_lookup"], "'nothing found' ages faster than a finding"
    assert phonerisk.CACHE_TTL == intel.TTL["phone_reputation"] and urlrisk.CACHE_TTL == intel.TTL["url_reputation"]
    assert rdap.CACHE_TTL == intel.TTL["domain_registration"]


def test_fresh_is_strictly_before_expiry_and_reads_stored_times_as_utc():
    now = now_utc()
    assert intel.fresh({"expires_at": now + timedelta(seconds=1)}, now)
    assert not intel.fresh({"expires_at": now}, now) and not intel.fresh({}, now)
    assert intel.fresh({"expires_at": (now + timedelta(hours=1)).replace(tzinfo=None)}, now)


# ── Subject keys ─────────────────────────────────────────────────────────────
def test_domains_and_links_are_keyed_on_what_identifies_them():
    assert intel.subject_key("domain", "https://WWW.Example.COM/path?x=1") == intel.subject_key("domain", "example.com.") == "domain:example.com"
    assert intel.subject_key("domain", "bücher.de") == "domain:xn--bcher-kva.de"
    assert (intel.subject_key("url", "https://Example.com:443/a/?b=2&utm_source=x&a=1&fbclid=z")
            == intel.subject_key("url", "example.com/a?a=1&b=2") == "url:https://example.com/a?a=1&b=2")
    assert intel.subject_key("url", "https://example.com/a?id=1") != intel.subject_key("url", "https://example.com/a?id=2")


def test_personal_identifiers_are_keyed_by_a_one_way_fingerprint():
    keys = {intel.subject_key("phone", v) for v in ("0412 345 678", "+61 412 345 678", "+61412345678")}
    assert len(keys) == 1
    phone = keys.pop()
    assert "412" not in phone and "345" not in phone and re.fullmatch(r"phone:[0-9a-f]{32}", phone)
    email = intel.subject_key("email", " Support@Apex-Horizon.io ")
    assert email == intel.subject_key("email", "support@apex-horizon.io") and "@" not in email and "apex" not in email


def test_organisations_and_registrations_are_keyed_on_their_identity():
    assert intel.subject_key("entity", "Apex Horizon Capital Pty Ltd") == intel.subject_key("entity", "apex horizon capital") == "entity:apex horizon capital"
    assert intel.subject_key("abn", "51 824 753 556") == "abn:51824753556"
    assert intel.subject_key("question", QUESTION) == intel.subject_key("question", "why do scammers ask you for gift cards")


# ── Ask Higgins makes no AI call, and never shows an old AI-written answer ────
@pytest.fixture
def no_ai(monkeypatch, store):
    calls = AsyncMock(side_effect=AssertionError("Ask Higgins makes no AI call"))
    monkeypatch.setattr(provider, "generate", calls)
    monkeypatch.setattr(chat.memory, "add_chat_exchange", AsyncMock(return_value=now_utc() + timedelta(minutes=5)))
    monkeypatch.setattr(chat.knowledge, "search", AsyncMock(return_value=[]))
    monkeypatch.setattr(chat.pipeline_submit, "submit_to_investigation_pipeline", AsyncMock(side_effect=AssertionError("no investigation")))
    return calls


async def ask(message: str):
    return await chat.reply("owner-reuse", "conversation-1", "turn-00000001", message, [])


async def test_an_old_saved_ai_answer_is_never_shown_and_no_call_is_made(no_ai, store):
    await intel.put(intel.subject_key("question", QUESTION), intel.GEMINI, intel.GENERAL_ANSWER, "general_answer", {"answer": ANSWER},
                    knowledge_class="ai_generated_answer", ai_generated=True, question=QUESTION)
    reply = await ask(QUESTION)
    assert ANSWER not in reply.answer and reply.answer == presenter.NOT_IN_TRUSTED_KNOWLEDGE
    assert reply.answered_by == "apollo" and no_ai.await_count == 0
    assert (await store.reusable_intelligence.find_one({}))["hits"] == 0
    assert await counts(store, chat.GENERAL_SITE) == {"sufficiency_unknown": 1, "external_call_avoided": 1}


async def test_kb_knowledge_answers_with_no_call(no_ai, store, monkeypatch):
    entry = {"kb_id": "learn_article:gift-cards", "kind": "learn_article", "status": "current", "title": "Gift card scams", "body": "..."}
    monkeypatch.setattr(chat.knowledge, "search", AsyncMock(return_value=[entry]))
    monkeypatch.setattr(chat.knowledge, "present", lambda entries, question: ("From the Learn with Higgins article “Gift card scams”", []))
    reply = await ask(QUESTION)
    assert reply.answered_by == "knowledge_base" and no_ai.await_count == 0
    assert await counts(store, chat.GENERAL_SITE) == {"sufficiency_known": 1, "kb_hit": 1, "external_call_avoided": 1}


async def test_an_off_topic_question_still_gets_the_fixed_reply(no_ai, store):
    reply = await ask("What's a good recipe for pavlova?")
    assert reply.answer == presenter.OUT_OF_SCOPE and no_ai.await_count == 0


def test_no_code_path_writes_ai_output_into_the_kb():
    source = (BACKEND / "services/reusable_intel.py").read_text()
    assert set(re.findall(r"higgins_knowledge\.(\w+)\(", source)) <= {"find", "delete_one"}, "the cache only reads the KB (and removes moved answers)"
    for path in (BACKEND / "services").rglob("*.py"):
        assert not re.search(r"upsert\(\s*[\"']gemini_answer", path.read_text()), path


def _code() -> dict[str, str]:
    return {p.relative_to(BACKEND).as_posix(): p.read_text() for folder in ("services", "routers") for p in (BACKEND / folder).rglob("*.py")}


def test_only_approved_lookups_write_the_reusable_cache():
    code = _code()
    writers = {path for path, text in code.items() if re.search(r"\b(?:intel|reusable_intel)\.put\(", text)}
    assert writers == {"services/higgins/tc_flyby/search.py"}, "only TC FlyBy's public-identifier lookups are cached; Ask Higgins writes nothing"
    direct = {path for path, text in code.items() if "db.reusable_intelligence" in text}
    assert direct == {"services/reusable_intel.py", "services/stats_reset.py"}
    reset = code["services/stats_reset.py"]
    assert re.findall(r"db\.reusable_intelligence\.(\w+)\(", reset) == ["update_many"] and '{"$set": {"hits": 0}}' in reset, \
        "Reset Stats only zeroes the hit counts; it never writes a lookup"


def test_magnum_di_and_case_evidence_never_reach_the_cache():
    code = _code()
    for path in ("services/higgins/coordinator.py", "services/higgins/jobs.py", "services/higgins/evidence.py", "services/higgins/repository.py"):
        assert "reusable_intel" not in code[path], path
    assert not re.search(r"investigation_cases|evidence_chunks|\bev\.", code["services/reusable_intel.py"])


# ── Evidence isolation ───────────────────────────────────────────────────────
def check(kind: str, subject: str) -> Check:
    return Check(id=uuid.uuid4().hex[:8], kind=kind, subject=subject, question=f"Is there an official scam warning about {subject}?",
                 statuses=("WARNING", "NO_WARNING_FOUND"))


def test_lookups_about_the_material_itself_are_never_keyed():
    for kind, subject in (("person", "John Carter"), ("claim", "guaranteed returns of 12% per month"), ("scam_alerts", "x"),
                          ("message_analysis", "Hi Mum, this is my new number"), ("general_question", "My name is Jane — is this a scam?")):
        assert search.lookup_key(check(kind, subject)) is None, kind
    assert search.lookup_key(check("link", "WWW.Example-Scam.top")) == "link|domain:example-scam.top"
    phone = search.lookup_key(check("phone", "0412 345 678"))
    assert phone.startswith("phone|phone:") and "412" not in phone


def test_a_question_with_personal_detail_is_not_storable():
    for question in ("My name is Jane, why do scammers want gift cards?", "Is 0412345678 a scam number?", "Is help@bank.example real?",
                     "Is https://example-scam.top safe?", "I live at 1 Main St, is this a scam?"):
        assert not knowledge.storable(question), question
    assert knowledge.storable(QUESTION)


# ── TC FlyBy's one Brave search (no AI) ─────────────────────────────────────
@pytest.fixture
def web(monkeypatch, store):
    """TC FlyBy's Brave search replaced (no request leaves the test): each search returns one official page that names
    the query's quoted subject, with a warning unless `status[subject]` says otherwise."""
    monkeypatch.setattr(search, "run", REAL_SEARCH)
    monkeypatch.setattr(search.brave_search, "configured", lambda: True)
    state = SimpleNamespace(queries=[], status={}, named=True)

    async def fake(q, **kwargs):
        state.queries.append(q)
        subject = (re.findall(r'"([^"]+)"', q) or [q])[0]
        words = "scam warning: do not pay" if state.status.get(subject, "WARNING") == "WARNING" else "company profile and contact page"
        text = f"{subject} {words}" if state.named else f"An unrelated page, {words}"
        return [{"url": "https://moneysmart.gov.au/alert", "title": "Investor Alert List", "description": text, "extraSnippets": []}]

    monkeypatch.setattr(search.brave_search, "search", fake)
    return state


async def lookup(*checks: Check) -> dict:
    # Each lookup is its own case: one Brave search per correlated case.
    return await search.run(list(checks), correlation_id=f"case-test-reuse-{uuid.uuid4().hex[:8]}", trigger_source="test")


async def test_a_fresh_lookup_is_reused_and_not_paid_for_again(web, store):
    first = await lookup(check("link", "zenith-quantum.top"))
    assert len(web.queries) == 1 and first["calls"] == 1 and first["cacheHits"] == 0 and first["provider"] == "brave"
    row = await store.reusable_intelligence.find_one({}, {"_id": 0})
    assert (row["subject_key"], row["info_type"], row["knowledge_class"]) == ("link|domain:zenith-quantum.top", "web_lookup", "search_result_lookup")
    assert row["ai_generated"] is False and row["provenance"]["sources"], "provenance keeps the pages behind the answer"

    again = await lookup(c := check("link", "https://www.zenith-quantum.top/join"))
    assert len(web.queries) == 1 and again["calls"] == 0 and again["cacheHits"] == 1 and again["status"] == "cached"
    answer = again["answers"][c.id]
    assert answer["reused"] is True and answer["status"] == "WARNING" and answer["sources"]
    assert answer["lastVerifiedAt"] == row["last_verified_at"].isoformat()
    assert (await store.reusable_intelligence.find_one({}))["hits"] == 1
    assert (await counts(store, search.SITE)) == {"sufficiency_unknown": 1, "external_call_required": 1, "cache_write": 1,
                                                 "sufficiency_known": 1, "cache_hit": 1, "external_call_avoided": 1}


async def test_a_mixed_batch_asks_only_what_is_still_open(web, store):
    await lookup(check("company", "Zenith Quantum Markets Pty Ltd"))
    known, new = check("company", "Zenith Quantum Markets"), check("link", "brightline-docs.net")
    out = await lookup(known, new)
    assert len(web.queries) == 2 and "brightline-docs.net" in web.queries[1] and "Zenith" not in web.queries[1]
    assert out["answers"][known.id]["reused"] is True and "reused" not in out["answers"][new.id]


async def test_an_expired_lookup_is_asked_again(web, store):
    await lookup(check("link", "zenith-quantum.top"))
    await store.reusable_intelligence.update_many({}, {"$set": {"expires_at": now_utc() - timedelta(minutes=1)}})
    out = await lookup(c := check("link", "zenith-quantum.top"))
    assert len(web.queries) == 2 and "reused" not in out["answers"][c.id]
    assert intel.fresh(await store.reusable_intelligence.find_one({})), "refreshed by the new answer"


async def test_nothing_found_counts_as_current_for_a_day_only(web, store):
    web.status["quiet-site.top"] = "NO_WARNING_FOUND"
    out = await lookup(c := check("link", "quiet-site.top"))
    assert out["answers"][c.id]["status"] == "NO_WARNING_FOUND"
    row = await store.reusable_intelligence.find_one({})
    assert row["info_type"] == "web_lookup_negative" and row["expires_at"] - row["last_verified_at"] == timedelta(days=1)


async def test_a_page_that_doesnt_name_the_exact_value_is_never_a_warning(web, store):
    web.named = False
    out = await lookup(c := check("link", "zenith-quantum.top"))
    assert out["answers"][c.id]["status"] == "NO_WARNING_FOUND" and out["answers"][c.id]["sources"] == []


async def test_a_lookup_saved_in_preview_is_never_reused_live(web, store):
    key = search.lookup_key(c := check("link", "zenith-quantum.top"))
    await intel.put(key, intel.BRAVE_SEARCH, intel.TC_FLYBY_LOOKUP, "web_lookup", {"status": "WARNING", "fact": "simulated", "sources": []},
                    knowledge_class="search_result_lookup", ai_generated=False, simulated=True)
    out = await lookup(c)
    assert len(web.queries) == 1 and "reused" not in out["answers"][c.id]


async def test_case_evidence_is_never_written_to_the_cache(web, store):
    person, claim = "Jane Citizen", "pay the invoice to BSB 062-000 account 1234 5678 today"
    await lookup(check("person", person), check("claim", claim))
    await lookup(check("person", person), check("claim", claim))
    assert len(web.queries) == 2, "never reused: each case asks for itself"
    assert await store.reusable_intelligence.count_documents({}) == 0
    assert await counts(store, search.SITE) == {"sufficiency_unknown": 2, "external_call_required": 2}


CHECKED = "2026-10-25T07:00:00+00:00"
PAGE = {"url": "https://moneysmart.gov.au/alert", "title": "Investor Alert List", "domain": "moneysmart.gov.au", "authority": "official", "basis": "ASIC"}


def _applied() -> tuple[Check, Check]:
    """One check settled by a reused lookup (last checked at CHECKED), one by a new lookup."""
    no_companies = SimpleNamespace(entities=SimpleNamespace(companies=[]))
    reused, new = check("link", "zenith-quantum.top"), check("link", "brightline-docs.net")
    tc_flyby._apply(reused, {"status": "WARNING", "fact": "ASIC lists zenith-quantum.top.", "sources": [PAGE], "reused": True,
                          "lastVerifiedAt": CHECKED}, no_companies)
    tc_flyby._apply(new, {"status": "WARNING", "fact": "A warning names brightline-docs.net.", "sources": [{**PAGE, "url": "https://moneysmart.gov.au/b"}]},
                 no_companies)
    return reused, new


def test_a_reused_lookup_keeps_when_it_was_last_checked_on_its_finding():
    reused, new = _applied()
    assert reused.facts[0]["source"]["reused"] is True and reused.facts[0]["source"]["checkedAt"] == CHECKED
    assert "reused" not in new.facts[0]["source"]


async def test_reused_sources_are_registered_with_their_last_checked_time(monkeypatch):
    saved: list = []

    async def add_sources(_owner, _case_id, refs):
        saved.extend(refs)
        return {r.id: r.id for r in refs}

    monkeypatch.setattr(tc_flyby.repo, "add_sources", add_sources)
    await tc_flyby._register_sources("owner", "case", list(_applied()))
    reused = [r for r in saved if r.reused]
    assert len(reused) == 1 and reused[0].retrieved_at.isoformat() == CHECKED
    assert reused[0].wire()["reused"] is True and reused[0].wire()["retrievedAt"].startswith("2026-10-25T07:00:00")
    newly = [r for r in saved if not r.reused]
    assert len(newly) == 1 and newly[0].retrieved_at > reused[0].retrieved_at


def test_the_result_says_when_a_search_was_reused():
    def searched(reused: bool) -> Check:
        c = check("link", "x.top")
        c.route, c.facts = "web_search", [{"source": {"reused": reused}}]
        return c
    assert report._routes([searched(False)]) == "a targeted web search"
    assert report._routes([searched(True)]) == "ApolloSG's recent targeted web search, reused while still current"
    assert report._routes([searched(True), searched(False)]) == "a targeted web search, partly reused from ApolloSG's recent lookups"


# ── IPQualityScore and RDAP: cache hits avoid the call and are counted ───────
async def test_a_phone_reputation_check_is_not_repeated_while_current(monkeypatch, store):
    number = f"+614{uuid.uuid4().int % 10**8:08d}"
    query = AsyncMock(return_value={"valid": True, "active": True, "fraud_score": 12, "recent_abuse": False, "risky": False, "VOIP": False,
                                    "line_type": "Wireless", "carrier": "Telstra", "country": "AU"})
    monkeypatch.setattr(phonerisk, "IPQS_API_KEY", "test-key")
    monkeypatch.setattr(phonerisk, "_query_ipqs", query)
    try:
        first = await phonerisk.check_phone_risk(number, None)
        again = await phonerisk.check_phone_risk(number, None)
        assert query.await_count == 1 and first.cached is False and again.cached is True and again.fraud_score == 12
        await db.phone_risk_cache.update_one({"phone_e164": first.number}, {"$set": {"expires_at": now_utc() - timedelta(minutes=1)}})
        await phonerisk.check_phone_risk(number, None)
        assert query.await_count == 2, "expired: checked again"
    finally:
        await db.phone_risk_cache.delete_many({"phone_e164": number})
    assert await counts(store, phonerisk.SITE) == {"sufficiency_unknown": 1, "external_call_required": 2, "cache_write": 2, "cache_hit": 1,
                                                  "sufficiency_known": 1, "external_call_avoided": 1, "cache_expired": 1, "sufficiency_partial": 1}


async def test_a_link_reputation_check_is_not_repeated_while_current(monkeypatch, store):
    url = f"https://apollo-reuse-{uuid.uuid4().hex[:8]}.top/login"
    posts: list = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"success": True, "domain": "x.top", "risk_score": 90, "phishing": True}

    class Client:
        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, *_a, **_k):
            posts.append(1)
            return Response()

    monkeypatch.setattr(urlrisk, "IPQS_API_KEY", "test-key")
    monkeypatch.setattr(urlrisk, "httpx", SimpleNamespace(AsyncClient=Client, Timeout=httpx.Timeout, TimeoutException=httpx.TimeoutException,
                                                          RequestError=httpx.RequestError, HTTPStatusError=httpx.HTTPStatusError))
    try:
        first = await urlrisk.check_url_risk(url)
        again = await urlrisk.check_url_risk(url)
    finally:
        await db.url_risk_cache.delete_many({"url": url})
    assert len(posts) == 1 and first["decision"] == "dangerous" and again["cached"] is True and again["decision"] == "dangerous"
    assert await counts(store, urlrisk.SITE) == {"sufficiency_unknown": 1, "external_call_required": 1, "cache_write": 1, "cache_hit": 1,
                                                "sufficiency_known": 1, "external_call_avoided": 1}


async def test_a_domain_registration_lookup_is_not_repeated_while_current(monkeypatch, store):
    domain = f"apollo-reuse-{uuid.uuid4().hex[:8]}.com"
    fetch = AsyncMock(return_value=DomainInfo(domain=domain, registrar="Example Registrar", registered_at=now_utc() - timedelta(days=3)))
    monkeypatch.setattr(rdap, "_fetch_live", fetch)
    try:
        first = await rdap.lookup_domain_cached(f"login.{domain}")
        again = await rdap.lookup_domain_cached(domain)
    finally:
        await db.domain_info_cache.delete_many({"domain": domain})
    assert fetch.await_count == 1 and first.newly_registered and again.registrar == "Example Registrar" and again.newly_registered
    assert (await counts(store, rdap.SITE))["external_call_avoided"] == 1


# ── Moving the KB's old saved Gemini answers ─────────────────────────────────
async def test_saved_gemini_answers_move_out_of_the_kb_with_their_history(store):
    recent, old = second(now_utc() - timedelta(days=10)), second(now_utc() - timedelta(days=120))
    created = second(now_utc() - timedelta(days=200))
    await store.higgins_knowledge.insert_many([
        {"kb_id": "gemini_answer:a", "kind": "gemini_answer", "question": QUESTION, "title": QUESTION, "body": ANSWER, "hits": 5,
         "publisher": knowledge.GEMINI_PUBLISHER, "created_at": created, "updated_at": recent},
        {"kb_id": "gemini_answer:b", "kind": "gemini_answer", "question": "What is a PayID scam?", "title": "What is a PayID scam?",
         "body": "An older answer.", "hits": 0, "publisher": knowledge.GEMINI_PUBLISHER, "created_at": old, "updated_at": old},
        {"kb_id": "learn_article:payid", "kind": "learn_article", "title": "PayID scams", "body": "Sourced."}])
    assert await intel.migrate_gemini_answers() == 2
    assert await store.higgins_knowledge.count_documents({"kind": "gemini_answer"}) == 0
    assert await store.higgins_knowledge.count_documents({"kind": "learn_article"}) == 1, "KB knowledge is untouched"

    moved = await intel.find(intel.subject_key("question", QUESTION), intel.GEMINI, intel.GENERAL_ANSWER)
    row = moved[0]
    assert (row["created_at"], row["last_verified_at"], row["expires_at"]) == (created, recent, recent + intel.TTL["general_answer"])
    assert row["payload"] == {"answer": ANSWER} and row["hits"] == 5 and row["question"] == QUESTION
    assert row["ai_generated"] is True and row["authoritative"] is False
    assert row["provenance"] == {"publisher": knowledge.GEMINI_PUBLISHER, "migrated_from": "higgins_knowledge", "kb_id": "gemini_answer:a"}
    need = sufficiency.Requirement(row["subject_key"], needs=("answer",))
    assert sufficiency.assess(need, cache=moved).level == sufficiency.KNOWN

    stale = await intel.find(intel.subject_key("question", "What is a PayID scam?"), intel.GEMINI, intel.GENERAL_ANSWER)
    decision = sufficiency.assess(sufficiency.Requirement(stale[0]["subject_key"], needs=("answer",)), cache=stale)
    assert (decision.level, decision.reason) == (sufficiency.PARTIAL, "expired"), "kept, but an old answer is never current"

    assert await intel.migrate_gemini_answers() == 0, "idempotent"
    assert await store.reusable_intelligence.count_documents({}) == 2


# ── Observability ────────────────────────────────────────────────────────────
async def test_counters_are_aggregate_and_content_free(store, caplog):
    with caplog.at_level(logging.INFO, logger="apollo.reusable_intel"):
        await intel.count("ipqs_phone", "cache_hit", "external_call_avoided")
        await intel.count("ipqs_phone", "cache_hit")
        await intel.count("ipqs_phone")
    doc = await store.intel_reuse_metrics.find_one({}, {"_id": 0})
    assert set(doc) == {"day", "site", "counts"} and doc["counts"] == {"cache_hit": 2, "external_call_avoided": 1}
    lines = [r.getMessage() for r in caplog.records if r.name == "apollo.reusable_intel"]
    assert lines == ["intel_reuse site=ipqs_phone events=cache_hit,external_call_avoided", "intel_reuse site=ipqs_phone events=cache_hit"]
    assert (await intel.metrics(14))[0]["counts"]["cache_hit"] == 2


async def test_admin_portal_shows_reuse_and_savings(store, monkeypatch):
    for _ in range(3):
        await intel.count("ipqs_phone", "cache_hit", "sufficiency_known", "external_call_avoided")
    await intel.count("higgins_general_question", "sufficiency_unknown", "external_call_required", "cache_write")
    await intel.put(intel.subject_key("question", QUESTION), intel.GEMINI, intel.GENERAL_ANSWER, "general_answer", {"answer": ANSWER},
                    knowledge_class="ai_generated_answer", ai_generated=True, question=QUESTION)

    async def admin(_request):
        return {"email": "owner@example.com", "name": "Owner"}

    monkeypatch.setattr(admin_portal, "_admin", admin)
    page = await admin_portal.intel_reuse_page(Request({"type": "http", "method": "GET", "path": "/api/admin/intel-reuse", "query_string": b"", "headers": []}))
    page = page.body.decode() if hasattr(page, "body") else page
    for testid in ("intel-reuse-heading", "intel-reuse-sites", "intel-reuse-days", "intel-reuse-inventory", "intel-reuse-ttl"):
        assert f'data-testid="{testid}"' in page, testid
    assert "Calls avoided (14 days)" in page and "75%" in page, "3 avoided of 4"
    assert "Phone reputation (IPQualityScore)" in page and html.escape("Ask Higgins general question (ApolloSG's KB; no AI call)") in page
    assert "AI-derived" in page and "higgins_general_answer" in page and "90 days" in page and "12 hours" in page
    assert ANSWER not in page and QUESTION not in page, "counts and kinds only, never content"
    assert ("Intelligence Reuse", "/api/admin/intel-reuse", "&#9851;") in admin_portal.NAV


# ── Apollo KB lexical retrieval benchmark ────────────────────────────────────
@pytest.mark.parametrize("held_out", [False, True], ids=["main", "holdout"])
async def test_the_kb_retrieval_benchmark_reproduces_its_baseline(held_out):
    saved = json.loads((BACKEND / "tests/kb_benchmark_baseline.json").read_text())
    baseline = saved["holdout" if held_out else "main"]
    name = f"kb_benchmark_test_{uuid.uuid4().hex[:8]}"
    try:
        result = await kb_benchmark.run(holdout=held_out, collection_name=name)
    finally:
        await db[name].drop()
    assert {k: result[k] for k in baseline} == baseline, "KB retrieval changed; re-record with scripts/kb_benchmark.py --record"
    cases = kb_benchmark.cases(holdout=held_out)
    assert all({"id", "area", "query", "expected", "must_find"} <= set(c) for c in cases)
    assert any(not c["must_find"] for c in cases), "off-topic questions must find nothing"
    # The owner's bar: find far more than before, with at most about 1 in 20 answers pointing to the wrong article.
    before = saved["before"]["holdout" if held_out else "main"]
    assert result["top3"] >= before["top3"] + 0.4 and result["irrelevant"] <= 0.05 and result["offTopicReturned"] <= 1


def test_the_held_out_questions_are_new():
    main = {c["query"].lower() for c in kb_benchmark.cases()}
    held = kb_benchmark.cases(holdout=True)
    assert len(held) >= 40 and not main & {c["query"].lower() for c in held}
    assert not {c["id"] for c in kb_benchmark.cases()} & {c["id"] for c in held}
