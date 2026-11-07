"""Reusable intelligence: what Apollo's approved external providers already told it, reused before paying to ask again.

This is NOT the Apollo knowledge base (services/higgins/knowledge.py). The KB is Apollo's trusted, sourced, general
knowledge. This cache holds results Apollo bought from external providers — Gemini's answers to general questions,
TC Hawkeye's grounded lookups about public identifiers — each with its provider, when it was obtained and last
verified, and when it stops counting as current. Nothing here is ever promoted into the KB: AI-derived results stay
labelled as AI-derived (`ai_generated`), and `authoritative` is always False.

Privacy: only results about public identifiers or general questions with no personal detail are stored. Private case
evidence (the material someone sent, Magnum DI's case conclusions, text quoted from a message, people's names) never
enters this cache. Phone numbers, email addresses and other personal identifiers are keyed by a one-way fingerprint.

Freshness: every record has created_at, last_verified_at and expires_at (from TTL, the one place freshness is set).
An expired record never counts as current; it can only be shown as stale, historical context, and it is deleted
STALE_KEPT_FOR after it expires.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pymongo.errors import DuplicateKeyError

from core.db import db, now_utc

log = logging.getLogger("apollo.reusable_intel")

# ── Freshness: information type → how long a record counts as current. Change it here only. ──
TTL: dict[str, timedelta] = {
    "general_answer": timedelta(days=90),       # Gemini's answer to a general scam-safety question
    "web_lookup": timedelta(days=7),            # TC Hawkeye grounded search that found something (a warning, a register entry)
    "web_lookup_negative": timedelta(days=1),   # ...that found nothing: new warnings appear fast, so "nothing found" ages quickly
    "phone_reputation": timedelta(hours=24),    # IPQualityScore phone scoring (phonerisk.py)
    "url_reputation": timedelta(hours=12),      # IPQualityScore URL scoring (urlrisk.py)
    "domain_registration": timedelta(hours=48), # RDAP registration record (rdap.py)
}
STALE_KEPT_FOR = timedelta(days=90)

# Providers and source types (who produced it, by which Apollo process).
GEMINI = "gemini"
GEMINI_SEARCH = "gemini_google_search"   # TC Hawkeye's old AI-grounded lookups: no longer read or written
BRAVE_SEARCH = "brave_search"            # TC Hawkeye's web search results, read deterministically
GENERAL_ANSWER = "higgins_general_answer"
TC_FLYBY_LOOKUP = "tc_flyby_lookup"
# How long an in-progress claim on a public lookup holds before another request may take it over (a crashed holder).
INFLIGHT_SECONDS = 30

# Aggregate counters (no content). One document per day and call site.
EVENTS = ("kb_hit", "cache_hit", "cache_expired", "sufficiency_known", "sufficiency_partial", "sufficiency_unknown",
          "external_call_avoided", "external_call_required", "cache_write")

_indexed = False


async def ensure_indexes() -> None:
    global _indexed
    await db.reusable_intelligence.create_index("cache_id", unique=True)
    await db.reusable_intelligence.create_index([("subject_key", 1), ("provider", 1), ("source_type", 1)])
    await db.reusable_intelligence.create_index("purge_at", expireAfterSeconds=0)
    await db.reusable_intelligence.create_index([("question", "text")], name="intel_question_text", default_language="english")
    await db.intel_reuse_metrics.create_index([("day", 1), ("site", 1)], unique=True)
    await db.intel_inflight.create_index("lookup_id", unique=True)
    await db.intel_inflight.create_index("purge_at", expireAfterSeconds=0)
    _indexed = True


async def _ready() -> None:
    if not _indexed:
        await ensure_indexes()


# ── Subject keys: a stable, deterministic identity for what was looked up ─────
_CORPORATE = re.compile(r"\b(pty|ltd|limited|inc|llc|plc|the|group|holdings|co)\b\.?", re.I)
_TRACKING = re.compile(r"^(utm_\w+|fbclid|gclid|mc_eid|mc_cid)$", re.I)


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def norm_domain(value: str) -> str:
    host = (value or "").strip().lower().rstrip(".")
    host = re.sub(r"^[a-z]+://", "", host).split("/")[0].split("?")[0].split("#")[0].split("@")[-1].split(":")[0]
    host = host.removeprefix("www.")
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return host


def norm_url(value: str) -> str:
    raw = (value or "").strip()
    parts = urlsplit(raw if re.match(r"^[a-z]+://", raw, re.I) else f"https://{raw}")
    host = norm_domain(parts.hostname or "")
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)))
    path = parts.path.rstrip("/") or ""
    return urlunsplit((parts.scheme.lower(), host + port, path, query, ""))


def norm_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if (value or "").strip().startswith("+"):
        return f"+{digits}"
    if digits.startswith("0") and len(digits) == 10:  # an Australian national number
        return f"+61{digits[1:]}"
    return f"+{digits}" if len(digits) > 10 else digits


def norm_text(value: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (value or "").lower()).split())


def subject_key(kind: str, value: str) -> str:
    """`kind:normalised value`. Personal identifiers (phone, email) and free text are one-way fingerprints."""
    if kind == "domain":
        return f"domain:{norm_domain(value)}"
    if kind == "url":
        return f"url:{norm_url(value)}"
    if kind == "phone":
        return f"phone:{fingerprint(norm_phone(value))}"
    if kind == "email":
        return f"email:{fingerprint((value or '').strip().lower())}"
    if kind in ("abn", "acn"):
        return f"{kind}:{re.sub(r'[^0-9]', '', value or '')}"
    if kind == "licence":
        return f"licence:{norm_text(value)}"
    if kind == "entity":
        return f"entity:{' '.join(_CORPORATE.sub(' ', norm_text(value)).split())}"
    if kind == "question":
        from services.higgins.knowledge import terms
        return f"question:{' '.join(terms(value))}"
    return f"hash:{fingerprint(norm_text(value))}"


def cache_id(key: str, provider: str, source_type: str, simulated: bool) -> str:
    return fingerprint(f"{key}|{provider}|{source_type}|{'sim' if simulated else 'live'}")


def aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value


def fresh(record: dict, now: datetime | None = None) -> bool:
    expires = aware(record.get("expires_at"))
    return bool(expires and expires > (now or now_utc()))


# ── Reading and writing ───────────────────────────────────────────────────────
async def find(key: str, provider: str, source_type: str, *, simulated: bool = False) -> list[dict]:
    """The record for this subject from this provider and process (fresh or expired), or none."""
    await _ready()
    row = await db.reusable_intelligence.find_one({"cache_id": cache_id(key, provider, source_type, simulated)}, {"_id": 0})
    return [row] if row else []


async def put(key: str, provider: str, source_type: str, info_type: str, payload: dict, *, knowledge_class: str, ai_generated: bool,
              provenance: Optional[dict] = None, simulated: bool = False, question: str = "", verified_at: datetime | None = None) -> str:
    """Store or re-verify one result. One record per subject, provider and process: a repeat refreshes it
    (last_verified_at, expires_at) and keeps when Apollo first obtained it."""
    await _ready()
    now = verified_at or now_utc()
    expires = now + TTL[info_type]
    cid = cache_id(key, provider, source_type, simulated)
    await db.reusable_intelligence.update_one({"cache_id": cid}, {
        "$set": {"subject_key": key, "provider": provider, "source_type": source_type, "info_type": info_type,
                 "knowledge_class": knowledge_class, "ai_generated": ai_generated, "authoritative": False, "simulated": simulated,
                 "payload": payload, "provenance": provenance or {}, "question": question[:400], "last_verified_at": now,
                 "expires_at": expires, "purge_at": expires + STALE_KEPT_FOR},
        "$setOnInsert": {"cache_id": cid, "created_at": now, "hits": 0}}, upsert=True)
    return cid


async def used(record: dict) -> None:
    if record.get("cache_id"):
        await db.reusable_intelligence.update_one({"cache_id": record["cache_id"]}, {"$inc": {"hits": 1}, "$set": {"last_hit_at": now_utc()}})


# ── One request at a time for the same public lookup ──────────────────────────
async def _claim(lookup_id: str) -> str | None:
    """An atomic in-progress claim, or None while another request holds it. Holds the lookup's fingerprint only —
    no device, case or content — so a waiting device learns nothing about who else asked."""
    await _ready()
    token, now = uuid.uuid4().hex, now_utc()
    fields = {"token": token, "until": now + timedelta(seconds=INFLIGHT_SECONDS), "purge_at": now + timedelta(seconds=INFLIGHT_SECONDS * 10)}
    try:
        await db.intel_inflight.insert_one({"lookup_id": lookup_id, **fields})
        return token
    except DuplicateKeyError:
        taken = await db.intel_inflight.find_one_and_update({"lookup_id": lookup_id, "until": {"$lte": now}}, {"$set": fields})
        return token if taken else None


async def once(lookup_id: str, fetch, *, reuse, wait_seconds: float = 15.0, poll_seconds: float = 0.25):
    """Run `fetch()` for a reusable public lookup unless another request is already running it. A request that finds
    the lookup claimed waits for the result the holder saves (`reuse()`), and never sends the same lookup alongside it.
    Returns fetch()'s or reuse()'s result, or None when the holder neither saved a result nor let go in time."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    while True:
        token = await _claim(lookup_id)
        if token:
            try:
                return await fetch()
            finally:
                await db.intel_inflight.delete_one({"lookup_id": lookup_id, "token": token})
        while True:
            await asyncio.sleep(poll_seconds)
            found = await reuse()
            if found is not None:
                return found
            if loop.time() >= deadline:
                return None
            if not await db.intel_inflight.find_one({"lookup_id": lookup_id, "until": {"$gt": now_utc()}}, {"_id": 1}):
                break   # the holder let go without a reusable result: this request may run the lookup itself


# ── Moving the KB's old saved Gemini answers here (kept, never discarded) ─────
async def migrate_gemini_answers() -> int:
    """Saved Gemini answers used to sit in the KB collection (kind gemini_answer). Each is copied here with its
    dates and provenance, and only then removed from the KB, so it stays usable and stops looking like KB knowledge.
    Idempotent."""
    await _ready()
    moved = 0
    async for entry in db.higgins_knowledge.find({"kind": "gemini_answer"}, {"_id": 0}):
        question = entry.get("question") or entry.get("title") or ""
        verified = aware(entry.get("updated_at") or entry.get("created_at")) or now_utc()
        cid = await put(subject_key("question", question), GEMINI, GENERAL_ANSWER, "general_answer", {"answer": entry.get("body") or ""},
                        knowledge_class="ai_generated_answer", ai_generated=True, question=question, verified_at=verified,
                        provenance={"publisher": entry.get("publisher"), "migrated_from": "higgins_knowledge", "kb_id": entry.get("kb_id")})
        await db.reusable_intelligence.update_one({"cache_id": cid}, {"$set": {"created_at": aware(entry.get("created_at")) or verified},
                                                                       "$max": {"hits": entry.get("hits") or 0}})
        if await db.reusable_intelligence.find_one({"cache_id": cid}, {"_id": 1}):
            await db.higgins_knowledge.delete_one({"kb_id": entry["kb_id"]})
            moved += 1
    if moved:
        log.info("reusable_intel_migrated_gemini_answers count=%s", moved)
    return moved


# ── Observability: aggregate counts only ──────────────────────────────────────
async def count(site: str, *events: str) -> None:
    """Add one to each event for `site` today. Logged without any content."""
    if not events:
        return
    day = now_utc().strftime("%Y-%m-%d")
    try:
        await db.intel_reuse_metrics.update_one({"day": day, "site": site}, {"$inc": {f"counts.{e}": 1 for e in events}}, upsert=True)
    except Exception:  # noqa: BLE001 — counting never breaks the work it counts
        log.warning("intel_reuse_count_failed site=%s", site)
    log.info("intel_reuse site=%s events=%s", site, ",".join(events))


async def metrics(days: int = 14) -> list[dict]:
    since = (now_utc() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    return await db.intel_reuse_metrics.find({"day": {"$gte": since}}, {"_id": 0}).sort([("day", -1), ("site", 1)]).to_list(500)


async def inventory() -> list[dict]:
    now = now_utc()
    return await db.reusable_intelligence.aggregate([
        {"$group": {"_id": {"provider": "$provider", "source_type": "$source_type", "ai": "$ai_generated"},
                    "records": {"$sum": 1}, "fresh": {"$sum": {"$cond": [{"$gt": ["$expires_at", now]}, 1, 0]}}, "hits": {"$sum": "$hits"}}},
        {"$sort": {"_id.provider": 1, "_id.source_type": 1}}]).to_list(50)
