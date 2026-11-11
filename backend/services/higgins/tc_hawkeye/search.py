"""TC Hawkeye stage 3 — one targeted web search, read deterministically. No AI is called.

Only checks that the direct sources and Apollo's KB could not settle reach this stage.

1. Earlier lookups first. Each open check about a public identifier is looked up in reusable intelligence
   (services/reusable_intel.py) by its subject key. A fresh earlier search result is reused, not paid for again:
   something found counts as current for 7 days, "nothing found" for 1 day.
2. One search per correlated case. Of the checks still open, the one most likely to change Apollo's finding or
   Higgins' guidance is searched (target()): a link, number or address a consequential request goes through first,
   then the kinds an official source can settle. ONE Brave Search request (services/brave_search.py), claimed
   atomically for the case (`tc_hawkeye_searches`, unique per correlation id), so no retry, job or recovery can make a
   second. Every other open check is recorded as not searched: missing evidence, never a pass.
3. One lookup at a time. A search about the same public identifier that another case is already running is waited
   for and its saved result reused, never sent twice (reusable_intel.once). The claim holds only the lookup's
   fingerprint: no device, case or content, so device isolation is kept.
4. Deterministic reading. A result counts only when its own words name the exact value; the publisher's authority
   comes from ApolloSG's trusted-source list (kb_sources); the fact quotes the page's words with its publisher.
   Nothing is generated, summarised or inferred. A page on the subject's own domain is never a warning about it.

Lookups about the material itself (an exact phrase, a person's name) are case evidence: never saved, never shared.
Until BRAVE_API_KEY is set — and on the preview server, which makes no paid calls — the search is reported as
unavailable, with nothing sent.
"""
from __future__ import annotations

import re
from datetime import timezone

from pymongo.errors import DuplicateKeyError

from core.db import db, now_utc
from services import brave_search, kb_sources
from services import reusable_intel as intel
from services import sufficiency
from services.higgins import brand_domains, knowledge
from services.higgins.llm_boundary import redact_registration_numbers, strip_credentials
from services.higgins.tc_hawkeye.triage import Check, digits

SITE = "tc_hawkeye_search"   # this call site, in the reuse counters
# Check kinds whose lookups are about public identifiers, and how their subject is keyed. Others (an exact phrase from
# the material, a person's name) are case evidence and never enter the shared cache.
SUBJECT_KIND = {"link": "domain", "phone": "phone", "email": "email", "company": "entity", "abn": "abn", "acn": "acn",
                "licence": "licence", "general_question": "question"}
NOT_USABLE = {"UNANSWERED", "UNSOURCED", "UNAVAILABLE"}
NOT_FOUND = {"NO_WARNING_FOUND", "NO_RECORD_FOUND", "NOT_CONFIRMED"}
REGISTER_CHECKS = ("abn", "acn", "licence")
REGISTER_DOMAINS = ("abr.business.gov.au", "asic.gov.au", "moneysmart.gov.au")
# Which open check the one search goes to: what a consequential request goes through first (focus), then these ranks.
_RANK = {"link": 0, "phone": 0, "email": 0, "company": 1, "abn": 2, "acn": 2, "licence": 2, "general_question": 3, "phrase": 4, "person": 5}
_WARNING_WORDS = re.compile(r"\b(scams?|scammers?|fraud\w*|phish\w*|fake|impersonat\w*|warnings?|alerts?|beware|malicious|malware|"
                            r"suspicious|blacklist\w*|investor alert list|do not (?:click|call|reply|respond|pay))\b", re.I)
_NUMBERISH = re.compile(r"\+?\d[\d\s\-().]{6,}\d")
_QUOTED = re.compile(r'"([^"]{2,160})"')


# ── Which check gets the one search ─────────────────────────────────────────
def _in_focus(check: Check, focus: set[str]) -> bool:
    subject = check.subject.lower()
    tail = digits(check.subject)[-8:]
    return any(subject and subject in f or (check.kind == "phone" and len(tail) == 8 and tail == digits(f)[-8:]) for f in focus)


def target(checks: list[Check], focus: set[str]) -> Check:
    """The open check most likely to change Apollo's finding or Higgins' guidance."""
    return min(checks, key=lambda c: (0 if _in_focus(c, focus) else 1, _RANK.get(c.kind, 9), checks.index(c)))


# ── The query (deterministic, minimal) ──────────────────────────────────────
def query(check: Check) -> str | None:
    """None when the check can't be searched without sending personal detail."""
    subject = check.subject.strip()
    kind = check.kind
    if kind == "link":
        q = f'"{subject}" scam OR phishing OR fraud OR warning'
    elif kind in ("phone", "email"):
        q = f'"{subject}" scam OR fraud OR warning'
    elif kind == "company":
        q = f'"{subject}" scam OR warning OR "investor alert" OR registered'
    elif kind == "abn":
        q = f"ABN {digits(subject)} site:abr.business.gov.au"
    elif kind == "acn":
        q = f"ACN {digits(subject)} company register"
    elif kind == "licence":
        q = f'"{digits(subject) or subject}" licence ASIC register'
    elif kind == "general_question":
        if not knowledge.storable(subject):
            return None
        q = subject
    elif kind == "person":
        q = " ".join(f'"{part}"' for part in _QUOTED.findall(check.question)[:2]) or f'"{subject}"'
    elif kind == "phrase":
        q = f'"{subject[:120]}"'
    else:
        return None
    q = strip_credentials(q)
    return q if kind in REGISTER_CHECKS else redact_registration_numbers(q)


# ── Reading the results ─────────────────────────────────────────────────────
def authority(domain: str) -> tuple[str, str]:
    source = kb_sources.source_for(f"https://{domain}")
    if source and source.tier == kb_sources.TIER_1:
        return "official", f"Search result from {source.publisher}, an official government or regulator source"
    if source:
        return "independent", f"Search result from {source.publisher}"
    return "unknown", "Search result; publisher not independently verified"


def _host(url: str) -> str:
    match = re.match(r"^[a-z]+://([^/?#]+)", url or "", re.I)
    return (match.group(1) if match else "").lower().split("@")[-1].split(":")[0].removeprefix("www.")


def _pieces(result: dict) -> list[str]:
    return [p for p in [result.get("title") or "", result.get("description") or "", *(result.get("extraSnippets") or [])] if p]


def _clean(text: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", "", text or "").split())


def _numbers(text: str) -> list[str]:
    return [digits(n) for n in _NUMBERISH.findall(text or "")]


def names(check: Check, text: str) -> bool:
    """These words name this exact value — not a similar one."""
    low = (text or "").lower()
    if check.kind == "phone":
        tail = digits(check.subject)[-8:]
        return len(tail) == 8 and any(n.endswith(tail) for n in _numbers(text))
    if check.kind in REGISTER_CHECKS:
        number = digits(check.subject)
        return bool(number) and any(number in n for n in _numbers(text) + [digits(text)] if len(number) >= 6)
    if check.kind == "company":
        from services.higgins.tc_hawkeye import _core
        core = _core(check.subject)
        return bool(core) and core in " ".join(_core(low).split())
    if check.kind == "phrase":
        wanted = " ".join(re.sub(r"[^\w\s]", " ", check.subject.lower()).split())[:80]
        return bool(wanted) and wanted in " ".join(re.sub(r"[^\w\s]", " ", low).split())
    if check.kind == "person":
        return all(part.lower() in low for part in _QUOTED.findall(check.question)[:2]) if _QUOTED.findall(check.question) else check.subject.lower() in low
    return check.subject.lower() in low


def _source(result: dict) -> dict:
    domain = _host(result["url"])
    level, basis = authority(domain)
    return {"url": result["url"], "title": _clean(result.get("title") or domain)[:200], "domain": domain, "authority": level, "basis": basis}


def _quote(check: Check, result: dict, source: dict, *, warning: bool = False) -> str:
    pieces = [_clean(p) for p in _pieces(result)]
    hit = next((p for p in pieces if names(check, p) and (not warning or _WARNING_WORDS.search(p))), None) \
        or next((p for p in pieces if names(check, p)), pieces[0] if pieces else source["title"])
    publisher = (kb_sources.source_for(result["url"]).publisher if kb_sources.source_for(result["url"]) else source["domain"])
    return f"{publisher} ({source['domain']}): “{hit}”"


def _own_site(check: Check, domain: str) -> bool:
    if check.kind == "link":
        return domain == check.subject.lower().removeprefix("www.") or domain.endswith("." + check.subject.lower())
    if check.kind == "email":
        return domain == check.subject.lower().split("@")[-1]
    return False


def _pick(statuses: tuple[str, ...], wanted: str) -> str:
    if wanted in statuses:
        return wanted
    return next((s for s in statuses if s in NOT_FOUND), "UNANSWERED")


def read(check: Check, results: list[dict], brands: list[str]) -> dict:
    """{status, fact, sources} from the results' own words, by fixed rules."""
    rows = [(r, _source(r)) for r in results]
    naming = [(r, s) for r, s in rows if not _own_site(check, s["domain"]) and any(names(check, p) for p in [r["url"], *_pieces(r)])]
    kind = check.kind

    def answer(status: str, picked: list[tuple[dict, dict]], *, warning: bool = False) -> dict:
        ordered = sorted(picked, key=lambda rs: {"official": 0, "independent": 1}.get(rs[1]["authority"], 2))
        lead = ordered[0]
        return {"status": _pick(check.statuses, status), "fact": _quote(check, lead[0], lead[1], warning=warning),
                "sources": [s for _, s in ordered][:4]}

    def nothing(searched_for: str) -> dict:
        return {"status": _pick(check.statuses, "NO_RECORD_FOUND" if "NO_RECORD_FOUND" in check.statuses else "NO_WARNING_FOUND"),
                "fact": f"A web search for {searched_for} found no page naming it." if not naming
                        else f"A web search found pages naming {searched_for}, none of them a warning or an official record.", "sources": []}

    if kind in REGISTER_CHECKS:
        official = [(r, s) for r, s in naming if s["authority"] == "official" and s["domain"].endswith(REGISTER_DOMAINS)]
        return answer("FOUND", official) if official else nothing(check.subject)
    if kind == "general_question":
        trusted = [(r, s) for r, s in rows if s["authority"] in ("official", "independent")]
        return answer("ANSWER", trusted) if trusted else {"status": _pick(check.statuses, "NO_RECORD_FOUND"),
                                                         "fact": "A web search found no page from a trusted source on this question.", "sources": []}
    if kind == "person":
        return answer("CONFIRMED", naming) if naming else nothing(check.subject)
    warned = [(r, s) for r, s in naming if any(_WARNING_WORDS.search(p) and names(check, p) for p in _pieces(r))]
    if warned:
        return answer("WARNING", warned, warning=True)
    if kind == "phrase":
        return answer("FOUND_ELSEWHERE", naming) if naming else nothing("this text")
    if kind == "company":
        registered = [(r, s) for r, s in naming if s["authority"] == "official" and s["domain"].endswith(REGISTER_DOMAINS)]
        if registered:
            return answer("REGISTERED", registered)
    if kind in ("phone", "email"):
        # A published contact only on the named organisation's own domain: anything else is not an official record.
        own = {d for b in brands for d in brand_domains.official_domains(b)}
        published = [(r, s) for r, s in naming if any(s["domain"] == d or s["domain"].endswith("." + d) for d in own)]
        if published:
            return answer("OFFICIAL", published)
    return nothing(check.subject)


# ── Reuse ───────────────────────────────────────────────────────────────────
def lookup_key(check: Check) -> str | None:
    """The subject key of a lookup that may be saved and reused, or None when it is case evidence."""
    kind = SUBJECT_KIND.get(check.kind)
    if not kind or (kind == "question" and not knowledge.storable(check.subject)):
        return None
    return f"{check.kind}|{intel.subject_key(kind, check.subject)}"


async def cached(check: Check) -> sufficiency.Decision:
    """KNOWN with the earlier search result to reuse, or PARTIAL/UNKNOWN."""
    key = lookup_key(check)
    if key is None:
        return sufficiency.Decision(sufficiency.UNKNOWN, "case_evidence")
    records = await intel.find(key, intel.BRAVE_SEARCH, intel.TC_FLYBY_LOOKUP)
    return sufficiency.assess(sufficiency.Requirement(key, needs=("status",), usable=lambda p: p.get("status") not in NOT_USABLE), cache=records)


async def store(check: Check, answer: dict) -> bool:
    key = lookup_key(check)
    if key is None or answer.get("status") in NOT_USABLE:
        return False
    await intel.put(key, intel.BRAVE_SEARCH, intel.TC_FLYBY_LOOKUP, "web_lookup_negative" if answer["status"] in NOT_FOUND else "web_lookup",
                    answer, knowledge_class="search_result_lookup", ai_generated=False,
                    provenance={"provider": "brave", "sources": [s.get("url") for s in answer.get("sources") or []][:4]})
    return True


def _when(value) -> str:
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat() if hasattr(value, "isoformat") else str(value)


def _reused(record: dict) -> dict:
    return {**record["payload"], "cached": True, "reused": True, "lastVerifiedAt": _when(record["last_verified_at"])}


async def _claim_case_search(correlation_id: str) -> bool:
    """The case's one search, taken atomically. False when this case already used it."""
    await db.tc_hawkeye_searches.create_index("correlation_id", unique=True)
    try:
        await db.tc_hawkeye_searches.insert_one({"correlation_id": correlation_id, "claimed_at": now_utc()})
        return True
    except DuplicateKeyError:
        return False


def _unavailable(check: Check, reason: str, note: str) -> dict:
    return {"status": "UNAVAILABLE", "fact": "", "sources": [], "reason": reason, "note": note}


_REASON_WORDS = {
    "not_configured": "TC Hawkeye's web search isn't set up yet",
    "preview_no_paid_search": "the preview server makes no paid web searches",
    "budget_limit": "ApolloSG's daily spending limit was reached",
    "one_search_used": "this case had already used its one web search",
    "personal_details": "the question holds personal details, so it wasn't sent to a search provider",
    "lookup_running": "the same search was already running for another check and didn't finish in time",
}


def _why(reason: str) -> str:
    return _REASON_WORDS.get(reason, f"the web search failed ({reason})")


async def run(checks: list[Check], *, correlation_id: str, trigger_source: str | None = None, owner: str | None = None,
              focus: set[str] | None = None, brands: list[str] | None = None) -> dict:
    """Earlier results first, then at most ONE web search for the case. Never raises; never calls an AI model."""
    pending = [c for c in checks if c.question]
    out = {"answers": {}, "calls": 0, "queries": 0, "cacheHits": 0, "tokens": {"input": 0, "output": 0},
           "simulated": False, "model": None, "provider": None, "target": None, "status": "skipped"}
    if not pending:
        return out
    to_ask: list[Check] = []
    for check in pending:
        decision = await cached(check)
        if decision.known:
            record = decision.reuse[0]
            out["answers"][check.id] = _reused(record)
            out["cacheHits"] += 1
            await intel.used(record)
            await intel.count(SITE, *decision.events(call_made=False))
        else:
            to_ask.append(check)
    if not to_ask:
        out["status"] = "cached"
        return out

    chosen = target(to_ask, {f.lower() for f in (focus or set())})
    out["target"] = chosen.id
    for check in to_ask:
        if check is not chosen:
            out["answers"][check.id] = _unavailable(check, "one_search_per_case",
                                                    f"TC Hawkeye runs one web search per case. It went to {chosen.subject}, so {check.subject} wasn't searched.")

    q = query(chosen)
    if q is None:
        out["answers"][chosen.id] = _unavailable(chosen, "personal_details", f"{chosen.subject} wasn't searched: {_why('personal_details')}.")
        out["status"] = "unavailable"
        return out
    key = lookup_key(chosen)

    async def search_once() -> dict:
        if not brave_search.configured():
            return _unavailable(chosen, "not_configured", f"{chosen.subject} wasn't searched: {_why('not_configured')}.")
        if not await _claim_case_search(correlation_id):
            return _unavailable(chosen, "one_search_used", f"{chosen.subject} wasn't searched: {_why('one_search_used')}.")
        await intel.count(SITE, "sufficiency_unknown", "external_call_required")
        try:
            results = await brave_search.search(q, correlation_id=correlation_id, trigger_source=trigger_source, device_id=owner,
                                                case_id=correlation_id.removeprefix("case-"))
        except brave_search.SearchUnavailable as exc:
            return _unavailable(chosen, exc.reason, f"{chosen.subject} wasn't searched: {_why(exc.reason)}.")
        out.update(calls=1, queries=1, provider="brave")
        answer = read(chosen, results, brands or [])
        if await store(chosen, answer):
            await intel.count(SITE, "cache_write")
        return answer

    if key is None:
        answer = await search_once()
    else:
        async def reuse() -> dict | None:
            decision = await cached(chosen)
            return _reused(decision.reuse[0]) if decision.known else None
        answer = await intel.once(intel.cache_id(key, intel.BRAVE_SEARCH, intel.TC_FLYBY_LOOKUP, False), search_once, reuse=reuse)
        if answer is None:
            answer = _unavailable(chosen, "lookup_running", f"{chosen.subject} wasn't searched: {_why('lookup_running')}.")
        elif answer.get("reused"):
            out["cacheHits"] += 1
    out["answers"][chosen.id] = answer
    out["status"] = "ok" if out["calls"] else ("cached" if answer.get("reused") else "unavailable")
    return out
