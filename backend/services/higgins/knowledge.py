"""Apollo knowledge base (KB): reusable researched knowledge, searchable without AI.

Every entry keeps its source, link, authority tier, jurisdiction and dates, and Higgins quotes entries verbatim:
- learn_article      — published Learn with Higgins articles (in-app route)
- scam_alert         — official scam alerts and advisories from the government feeds
- official_guidance  — cyber.gov.au guidance (CC BY 4.0), shipped in data/cyber_gov_au_guidance.json
- scam_pattern       — established scam patterns as official sources describe them (tc_flyby/patterns.py), with the
                       markers TC Hawkeye compares submitted material against
- researched         — trusted pages found and maintained through Tavily (services/apollo_kb.py), versioned
- exploited_vulnerability, attack_technique — technical knowledge from the free feeds (services/threat_feeds.py):
                       CISA's Known Exploited Vulnerabilities (with NVD severity) and MITRE ATT&CK. Found only by its
                       exact id (a CVE or ATT&CK technique id), so it never stands in for everyday guidance.

AI-written answers are NOT KB knowledge and are never used to answer anyone: Ask Higgins no longer asks a general AI
model, and the answers it saved before that (moved to the reusable intelligence cache, services/reusable_intel.py)
are never shown again.

KB knowledge is general knowledge. It is never evidence about anything a person asked Apollo to check.

Search is deterministic, with no AI: a MongoDB text index narrows candidates, then a fixed weighted rule decides
whether an entry really answers the question (see "Matching a question to an entry" below).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from datetime import timedelta
from pathlib import Path
from typing import Optional

from core.db import db, now_utc
from core.redaction import redact_investigation_secrets
from services.kb_sources import JURISDICTION_LABEL, TIER_1, TIER_LABEL

log = logging.getLogger("apollo.knowledge")

GUIDANCE_FILE = Path(__file__).resolve().parents[2] / "data" / "cyber_gov_au_guidance.json"
CYBER_PUBLISHER = "Australian Cyber Security Centre (cyber.gov.au)"
CYBER_LICENCE = "CC BY 4.0"
CYBER_ATTRIBUTION = "© Commonwealth of Australia (Australian Signals Directorate), licensed under CC BY 4.0."

_STOP = set("""a about above after again all am an and any are as at be because been before being below between both but by can
could did do does doing down during each few for from further get got had has have having he her here hers him his how i if in
into is it its itself just me more most my myself no nor not now of off on once only or other our out over own same she should
so some such than that the their them then there these they this those through to too under until up very was we were what when
where which while who whom why will with would you your yours yourself apollo higgins please tell explain know want need help
really thing things someone something way ways much many also like""".split())
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
# Questions that carry personal detail are answered but never stored for reuse.
_PERSONAL = re.compile(r"https?://|www\.|@|\d{6,}|\b(my name is|i live at|my address)\b", re.I)


def _stem(word: str) -> str:
    for suffix in ("ing", "es", "ed", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def terms(text: str) -> list[str]:
    """Content terms of a question: lower-cased, stop words removed, lightly stemmed, order kept."""
    seen: list[str] = []
    for word in _WORD.findall((text or "").lower().replace("’", "'")):
        word = word.split("'")[0]
        if len(word) < 3 or word in _STOP:
            continue
        stem = _stem(word)
        if stem not in seen:
            seen.append(stem)
    return seen


def _coverage(query_terms: list[str], text: str) -> float:
    if not query_terms:
        return 0.0
    have = set(terms(text))
    return sum(1 for term in query_terms if term in have) / len(query_terms)


# ── Matching a question to an entry ───────────────────────────────────────────
# A person asks in their own words; a source writes in its own. Both are reduced to concepts the same way: common
# words dropped, endings trimmed, and everyday words for the same thing (bitcoin / crypto, rang / called) made one.
# terms() above is unchanged: it stays the key for saved answers.
_PHRASES = (("wi-fi", "wifi"), ("e-mail", "email"), ("pop-up", "popup"), ("same password", "reused password"), ("one-time", "onetime"))
_TWO_LETTER = {"qr", "ai", "id", "pc"}
_SAME_THING = {
    "crypto": "bitcoin btc ethereum crypto cryptocurrency cryptocurrencies usdt tether",
    "government": "government govt ato mygov centrelink",
    "identity": "identity passport passports licence license medicare",
    "scam": "scam scams scammer scammers scammed scamming",
    "pay": "pay paid paying payment payments",
    "reuse": "reuse reused reusing",
    "verify": "verify verified verifying check checking checked confirm",
    "steal": "steal stole stolen theft",
    "warn": "warn warning warnings popup popups",
    "romance": "dating romance romantic boyfriend girlfriend lover",
    "call": "call called caller callers calling rang",
    "text": "text texts texted sms msg txt",
    "gift": "gift itunes giftcard giftcards",
    "remote": "anydesk teamviewer",
    "computer": "computer laptop pc",
    "family": "mum mom dad son daughter grandson granddaughter kid child children family",
    "takeover": "hack hacked hacker hijack hijacked takeover compromised",
    "social": "instagram facebook tiktok snapchat social",
    "marketplace": "gumtree ebay marketplace",
    "rental": "landlord rent rental renting apartment accommodation airbnb",
    "job": "job jobs recruiter recruitment recruiting employer hiring",
    "delivery": "parcel parcels package delivery deliver delivered courier",
    "toll": "toll tolls linkt",
    "bank": "bank banks banking commbank westpac anz nab",
    "code": "code codes otp passcode",
    "malware": "malware virus viruses infected infection trojan",
    "pressure": "urgency urgent rush rushing hurry pressure",
    "prize": "prize prizes lottery winnings jackpot",
    "charity": "charity charities donation donations donate fundraising",
    "subscription": "subscription subscriptions trial renew renewal renewed",
    "shame": "embarrassed embarrassing ashamed shame stupid",
    "evidence": "evidence screenshot screenshots",
    "older": "elderly older grandparents grandparent seniors senior aged",
    "deepfake": "deepfake deepfakes clone cloned",
    "breach": "breach breaches leak leaked exposed",
    "blackmail": "blackmail sextortion extortion extort threaten threatening threatened",
}
# Words in a question that don't say what it's about: asking, telling, wanting, and Australia (Apollo's home).
_CHATTER = set("""want wants wanted wanting say says said saying told tell need needs needed show shows showed showing good bad last ever
give gave given make made makes real legit okay fine now unless time one use used using everywhere latest someone somebody stranger person
people ask asks asked asking get gets getting come came take took look looking try trying see think put let going goes went day today week
tonight yesterday morning even still already first safe australia australian australians aussie""".split())

MIN_COVERAGE = 0.3   # weighted share of the question's concepts the entry must hold
MIN_SCORE = 0.3      # 0.4 × coverage + 0.25 × the question's share in the title + 0.35 × the title's share in the question
UNKNOWN_WEIGHT = 1.0  # a word no entry holds still counts against a match
WEIGHTS_FOR = timedelta(hours=1)


def _trim(word: str) -> str:
    for suffix, keep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if word.endswith(suffix) and len(word) > len(suffix) + 2 and not (suffix == "s" and word.endswith(("ss", "us"))):
            word = word[: -len(suffix)] + keep
            if suffix in ("ing", "ed") and len(word) > 3 and word[-1] == word[-2] and word[-1] not in "lsz":
                word = word[:-1]  # scammed → scam, not scamm
            break
    return word[:-1] if len(word) > 4 and word.endswith("e") else word


_CONCEPT: dict[str, str] = {}
for _canon, _words in _SAME_THING.items():
    for _w in _words.split():
        _CONCEPT[_w] = _CONCEPT[_trim(_w)] = _canon
_ALIASES: dict[str, list[str]] = {}
for _w, _canon in _CONCEPT.items():
    _ALIASES.setdefault(_canon, []).append(_w)


def concepts(text: str, *, query: bool = False) -> list[str]:
    """What `text` is about, as concepts in order. `query`: also drop the question's own chatter."""
    text = (text or "").lower().replace("’", "'")
    for phrase, same in _PHRASES:
        text = text.replace(phrase, same)
    out: list[str] = []
    for word in _WORD.findall(text):
        word = word.split("'")[0]
        if (len(word) < 3 and word not in _TWO_LETTER) or word in _STOP or (query and word in _CHATTER):
            continue
        concept = _CONCEPT.get(word) or _CONCEPT.get(_trim(word)) or _trim(word)
        if concept not in out:
            out.append(concept)
    return out


# Concepts that say how something arrived, not what it is: an entry matched on these alone isn't on the subject.
GENERIC = {c for w in "scam phone call text message email online money pay number account app website internet fake device change".split()
           for c in concepts(w)}


def search_words(question: str) -> str:
    """What the text index is asked for: the question's words and the everyday words for the same concepts."""
    words = terms(question) + [w for c in concepts(question, query=True) for w in _ALIASES.get(c, ())]
    return " ".join(dict.fromkeys(words))


_WEIGHTS: dict[str, tuple] = {}


async def _weights(coll) -> tuple[int, dict[str, int]]:
    """How many entries hold each concept (rarer = more telling), counted over the whole collection, kept an hour."""
    cached = _WEIGHTS.get(coll.full_name)
    if cached and now_utc() - cached[0] < WEIGHTS_FOR:
        return cached[1], cached[2]
    held: dict[str, int] = {}
    n = 0
    async for doc in coll.find(_GENERAL, {"_id": 0, "title": 1, "body": 1}):
        n += 1
        for concept in set(concepts(f"{doc.get('title') or ''} {doc.get('body') or ''}")):
            held[concept] = held.get(concept, 0) + 1
    _WEIGHTS[coll.full_name] = (now_utc(), n, held)
    return n, held


# Technical knowledge is answered only when asked for by its exact id; it takes no part in matching everyday questions.
TECHNICAL_KINDS = ("exploited_vulnerability", "attack_technique")
# The Official Organisation Directory is reference data the checks read (services/org_directory.py), never quoted as an answer.
_NOT_GENERAL = {"$nin": ["gemini_answer", *TECHNICAL_KINDS, "official_organisation"]}
# What a general question or related reading may use: every general kind, except the phone-call scam patterns, which
# are TC Hawkeye's matching rules for a call check (patterns.py), not library articles.
_GENERAL = {"kind": _NOT_GENERAL, "pattern.channel": {"$exists": False}}
_TECHNICAL_ID = re.compile(r"\b(CVE-\d{4}-\d{4,}|T\d{4}(?:\.\d{3})?)\b", re.I)


async def by_id(text: str, limit: int = 2) -> list[dict]:
    """Technical entries named by their exact id in the text: CVE-2024-3400, or an ATT&CK technique like T1660."""
    ids = list(dict.fromkeys(match.upper() for match in _TECHNICAL_ID.findall(text or "")))[:limit]
    if not ids:
        return []
    rows = await db.higgins_knowledge.find({"kind": {"$in": list(TECHNICAL_KINDS)}, "status": {"$ne": "historical"},
                                            "source_reference": {"$in": ids}}, {"_id": 0, "sketch": 0}).to_list(limit * 2)
    rows.sort(key=lambda row: (ids.index(row["source_reference"]), row.get("matrix") != "mobile"))  # Mobile first: ApolloSG is on phones
    picked, seen = [], set()
    for row in rows:
        if row["source_reference"] not in seen:
            seen.add(row["source_reference"])
            picked.append(row)
    picked = picked[:limit]
    if picked:
        await db.higgins_knowledge.update_many({"kb_id": {"$in": [row["kb_id"] for row in picked]}}, {"$inc": {"hits": 1}})
    return picked


def forget_weights() -> None:
    _WEIGHTS.clear()


def _kb_id(kind: str, key: str) -> str:
    return hashlib.sha256(f"{kind}:{key}".encode()).hexdigest()[:32]


async def ensure_indexes() -> None:
    # Pages once quoted for a live question (Tavily is now for KB maintenance only); the KB re-reads them properly.
    await db.higgins_knowledge.delete_many({"kind": "web_result"})
    await db.higgins_knowledge.create_index("kb_id", unique=True)
    await db.higgins_knowledge.create_index([("kind", 1), ("updated_at", -1)])
    await db.higgins_knowledge.create_index([("title", "text"), ("question", "text"), ("body", "text")],
                                            weights={"title": 6, "question": 8, "body": 1}, name="kb_text", default_language="english")


async def upsert(kind: str, key: str, *, title: str, body: str, publisher: str, authority_tier: str, jurisdiction: str,
                 url: str | None = None, route: str | None = None, question: str = "", licence: str = "", attribution: str = "",
                 published_at=None, retrieved_via: str = "apollo", knowledge_class: str = "general_knowledge",
                 extra: Optional[dict] = None) -> str:
    kb_id = _kb_id(kind, key)
    now = now_utc()
    provenance = {"source_url": url, "publisher": publisher, "authority_tier": authority_tier, "jurisdiction": jurisdiction,
                  "licence": licence, "attribution": attribution, "published_at": published_at, "retrieved_at": now,
                  "last_checked_at": now, "retrieved_via": retrieved_via}
    await db.higgins_knowledge.update_one({"kb_id": kb_id}, {
        "$set": {"kind": kind, "key": key, "title": title[:300], "body": body[:20000], "publisher": publisher, "url": url, "route": route,
                 "question": question[:400], "licence": licence, "attribution": attribution, "authority_tier": authority_tier,
                 "jurisdiction": jurisdiction, "knowledge_class": knowledge_class, "status": "current", "provenance": provenance,
                 "updated_at": now, **(extra or {})},
        "$setOnInsert": {"kb_id": kb_id, "created_at": now, "hits": 0}}, upsert=True)
    return kb_id


# ── Loading what Apollo already holds ─────────────────────────────────────────

def _article_text(article: dict) -> str:
    parts = [article.get("summary") or ""]
    for section in article.get("sections") or []:
        parts.append("\n".join([section.get("heading") or "", *[str(p) for p in section.get("paragraphs") or []],
                                *[str(b) for b in section.get("bullets") or []]]))
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


_LANGUAGE_REGION = {"en-AU": "AU", "en-US": "US", "en-GB": "UK", "en-NZ": "NZ", "en-CA": "CA"}


async def sync_learn_articles() -> int:
    count = 0
    # Articles Apollo made from researched pages are already in the KB as those pages' own records.
    async for article in db.learning_articles.find({"status": "published", "deleted_at": None, "source_type": {"$ne": "apollo_kb"}}, {"_id": 0}):
        citations = [c.get("label") for c in article.get("citations") or [] if c.get("label")]
        await upsert("learn_article", article["slug"], title=article["title"], body=_article_text(article),
                     publisher="Learn with Higgins" + (f" (sources: {', '.join(citations[:3])})" if citations else ""),
                     route=f"/higgins/learning/{article['slug']}", authority_tier="apollo_curated",
                     jurisdiction=_LANGUAGE_REGION.get(article.get("language") or "", "INTL"), published_at=article.get("published_at"))
        count += 1
    return count


async def sync_scam_alerts() -> int:
    """Every analysed official alert/advisory, in the source's own words."""
    from services import government_alerts, scam_analysis, scam_intel
    sources = {row["source_id"]: row for row in await db.learning_sources.find({}, {"_id": 0, "source_id": 1, "name": 1}).to_list(500)}
    count = 0
    # Alerts the KB itself found (origin apollo_kb) are already in the KB as researched records.
    async for row in db.learning_feed_items.find({"scam_analysis.analysisVersion": scam_analysis.ANALYSIS_VERSION,
                                                  "origin": {"$ne": "apollo_kb"}}, {"_id": 0}):
        analysis = row["scam_analysis"]
        if not (row.get("title") and row.get("url")) or row.get("url", "").find("#") >= 0:
            continue
        sections = analysis.get("sections") or {}
        body = "\n\n".join(part for part in [row.get("summary") or "", sections.get("whereHappening") or "",
                                             sections.get("whatToWatch") or "", sections.get("whatToDo") or ""] if part)
        source_name = government_alerts.SOURCE_DISPLAY_NAME.get(row["source_id"], (sources.get(row["source_id"]) or {}).get("name") or row["source_id"])
        region = scam_intel.region_for(row["source_id"])
        await upsert("scam_alert", row["url"], title=row["title"], body=body, publisher=source_name, url=row["url"],
                     authority_tier=TIER_1, jurisdiction="INTL" if region == "GLOBAL" else region, published_at=row.get("published_at"),
                     retrieved_via="government_feed", extra={"tier": analysis.get("tier"), "severity": analysis.get("severity"), "region": region})
        count += 1
    return count


async def load_official_guidance() -> int:
    """cyber.gov.au guidance shipped with Apollo (CC BY 4.0, attributed)."""
    if not GUIDANCE_FILE.exists():
        return 0
    entries = json.loads(GUIDANCE_FILE.read_text())
    for entry in entries:
        await upsert("official_guidance", entry["url"], title=entry["title"], body=entry["body"], publisher=CYBER_PUBLISHER,
                     url=entry["url"], licence=CYBER_LICENCE, attribution=CYBER_ATTRIBUTION, authority_tier=TIER_1, jurisdiction="AU",
                     retrieved_via="shipped_with_apollo")
    return len(entries)


async def refresh() -> dict:
    """Bring the KB up to date with Learn, Scam Alerts, the shipped official guidance and scam patterns. Idempotent."""
    from services.higgins.tc_hawkeye import patterns
    result = {"learn": await sync_learn_articles(), "alerts": await sync_scam_alerts(), "guidance": await load_official_guidance(),
              "patterns": await patterns.load()}
    forget_weights()
    log.info("knowledge_refresh %s", result)
    return result


# ── Remembering new knowledge ─────────────────────────────────────────────────

def storable(question: str) -> bool:
    return redact_investigation_secrets(question) == question and not _PERSONAL.search(question)


GEMINI_PUBLISHER = "Higgins (written by an AI tool)"  # provenance on the old saved answers (reusable_intel)


# ── Search and verbatim presentation ──────────────────────────────────────────

def _accepts(entry: dict, query: list[str], weights: tuple[int, dict[str, int]]) -> float:
    """How well the entry answers the question (its concepts `query`), or 0 when it doesn't.

    Each concept is weighted by how rare it is in the KB. The entry must hold at least MIN_COVERAGE of the
    question's weight, its title must share a concept with the question, and a match on generic concepts alone
    (phone, email, money…) counts only when it is the whole question. Ranking order is search()'s job."""
    n, held = weights
    weight = lambda c: math.log(n / held[c]) if held.get(c) else UNKNOWN_WEIGHT  # noqa: E731
    total = sum(weight(c) for c in query)
    if not total:
        return 0.0
    title = set(concepts(entry.get("title") or ""))
    body = title | set(concepts(entry.get("body") or ""))
    hit = [c for c in query if c in body]
    coverage = sum(weight(c) for c in hit) / total
    in_title = sum(weight(c) for c in query if c in title) / total
    named = [c for c in title if c not in GENERIC]  # what the title is about: "What is a scam?" names nothing in particular
    title_weight = sum(weight(c) for c in named)
    title_covered = sum(weight(c) for c in named if c in query) / title_weight if title_weight else 0.0
    on_subject = any(c not in GENERIC for c in hit) or len(hit) == len(query)
    score = 0.4 * coverage + 0.25 * in_title + 0.35 * title_covered
    if not in_title or coverage < MIN_COVERAGE or score < MIN_SCORE or not on_subject:
        return 0.0
    return score


def _rank(entry: dict, score: float) -> tuple:
    """Rulebook order, strictest first: current before historical, then a title that names something before one
    that names nothing in particular ("What is a scam?"), then the score, then the text index's own score."""
    names_something = any(c not in GENERIC for c in concepts(entry.get("title") or ""))
    return (entry.get("status") != "historical", names_something, score, entry["score"])


async def search(question: str, limit: int = 2, *, collection=None) -> list[dict]:
    """KB entries that answer `question`, best first. Gemini's saved answers are never KB knowledge and never
    returned. `collection`: another collection with the same shape and text index (the benchmark's corpus)."""
    coll = db.higgins_knowledge if collection is None else collection
    if collection is None and (named := await by_id(question, limit)):
        return named
    query = concepts(question, query=True)
    if not query:
        return []
    try:
        rows = await coll.find({"$text": {"$search": search_words(question)}, **_GENERAL},
                               {"_id": 0, "score": {"$meta": "textScore"}}).sort([("score", {"$meta": "textScore"})]).limit(25).to_list(25)
    except Exception:  # noqa: BLE001 — a missing index means no match, never a crash
        return []
    weights = await _weights(coll)
    scored = [(_rank(row, score), row) for row in rows if (score := _accepts(row, query, weights)) > 0]
    scored.sort(key=lambda item: item[0], reverse=True)
    picked = [row for _rank_key, row in scored[:limit]]
    if picked:
        await coll.update_many({"kb_id": {"$in": [row["kb_id"] for row in picked]}}, {"$inc": {"hits": 1}})
    return picked


def related_share(entry: dict, query_terms: list[str]) -> float:
    """How strongly a sourced entry is ON THE SAME SUBJECT as the text: the share of its title found in the text.
    0 when it isn't related. Looser than _accepts — it needn't answer a question word for word — and saved AI
    answers never count, because they aren't sourced knowledge."""
    if entry.get("kind") == "gemini_answer":
        return 0.0
    title_terms = terms(entry.get("title") or "")
    if not title_terms:
        return 0.0
    wanted = set(query_terms)
    shared = sum(1 for term in title_terms if term in wanted)
    share = shared / len(title_terms)
    if len(query_terms) <= 6:  # a question: it must share its subject words with the entry
        return share if shared >= min(2, len(query_terms)) else 0.0
    return share if shared >= 2 and share >= 0.5 else 0.0  # evidence: half the entry's title must be in it


async def related(text: str, limit: int = 2) -> list[dict]:
    """Sourced entries on the same subject as `text`, best first. Used by the preview simulator, which answers
    from Apollo's own library instead of calling Gemini. Never raises: no index or no match means no entries."""
    query_terms = terms(text)[:30]
    if not query_terms:
        return []
    try:
        rows = await db.higgins_knowledge.find({"$text": {"$search": " ".join(query_terms)}, **_GENERAL},
                                               {"_id": 0, "sketch": 0, "score": {"$meta": "textScore"}}
                                               ).sort([("score", {"$meta": "textScore"})]).limit(25).to_list(25)
    except Exception:  # noqa: BLE001
        return []
    scored = [(share, row["score"], row) for row in rows if (share := related_share(row, query_terms)) > 0]
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [row for _share, _score, row in scored[:limit]]


def excerpt(body: str, query_terms: list[str], max_chars: int = 900) -> str:
    """The passages of the entry that best match the question, verbatim and in their original order."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", body or "") if len(p.strip()) > 1]
    if not paragraphs:
        return ""
    ranked = sorted(range(len(paragraphs)), key=lambda i: (-_coverage(query_terms, paragraphs[i]), i))
    chosen: list[int] = []
    total = 0
    for index in ranked:
        if total and _coverage(query_terms, paragraphs[index]) == 0:
            break
        if total + len(paragraphs[index]) > max_chars and chosen:
            continue
        chosen.append(index)
        total += len(paragraphs[index])
        if total >= max_chars * 0.6:
            break
    return "\n\n".join(paragraphs[i] for i in sorted(chosen))[: max_chars + 200]


GENERAL_KNOWLEDGE_NOTE = "This is general knowledge from ApolloSG's library. It isn't a finding about anything you've asked Apollo to check."


def _day(value) -> str:
    return value.strftime("%-d %B %Y") if hasattr(value, "strftime") else ""


def provenance_line(entry: dict) -> str:
    """Who says it, how authoritative they are, where it applies, when it was published or checked, and its status."""
    provenance = entry.get("provenance") or {}
    tier = TIER_LABEL.get(entry.get("authority_tier") or "", "")
    jurisdiction = entry.get("jurisdiction") or ""
    parts = [p for p in [tier, JURISDICTION_LABEL.get(jurisdiction, "") if jurisdiction != "INTL" else ""] if p]
    if provenance.get("published_at"):
        parts.append(f"published {_day(provenance['published_at'])}")
    elif provenance.get("last_checked_at") and entry.get("kind") == "researched":
        parts.append(f"Apollo last checked it {_day(provenance['last_checked_at'])}")
    if entry.get("status") == "updated" and entry.get("changed_at"):
        parts.append(f"updated {_day(entry['changed_at'])}")
    line = f"({' · '.join(parts)})" if parts else ""
    if entry.get("status") == "historical":
        line += " Historical: its source no longer publishes this, so it may be out of date."
    if jurisdiction not in ("", "AU", "INTL"):
        line += f" This is {JURISDICTION_LABEL.get(jurisdiction, jurisdiction)} guidance — contacts and reporting steps may differ where you live."
    return line.strip()


def present(entries: list[dict], question: str) -> tuple[str, list[dict]]:
    """Verbatim presentation: who says it, their words, its provenance, and where to read the rest."""
    query_terms = terms(question)
    blocks: list[str] = []
    sources: list[dict] = []
    for entry in entries:
        words = excerpt(entry["body"], query_terms)
        intro = f"{entry['publisher']} — “{entry['title']}”" if entry["kind"] != "learn_article" else f"From the Learn with Higgins article “{entry['title']}”"
        meta = provenance_line(entry)
        link = f"\n\nRead the original: {entry['url']}" if entry.get("url") else ""
        blocks.append(f"{intro}{(' ' + meta) if meta else ''}:\n\n{words}{link}")
        sources.append({"title": entry["title"], "publisher": entry["publisher"], "url": entry.get("url"), "route": entry.get("route"),
                        "licence": entry.get("licence") or None})
    if sources:
        blocks.append(GENERAL_KNOWLEDGE_NOTE)
    return "\n\n———\n\n".join(blocks), sources


async def stats() -> list[dict]:
    return await db.higgins_knowledge.aggregate([{"$group": {"_id": "$kind", "entries": {"$sum": 1}, "hits": {"$sum": "$hits"},
                                                             "updated": {"$max": "$updated_at"}}}, {"$sort": {"_id": 1}}]).to_list(20)
