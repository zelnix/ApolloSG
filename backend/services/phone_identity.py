"""Phone Number Identity Resolution — who a number belongs to, from Apollo's own sources.

Pipeline:
  1. Normalize (phonenumbers / number_details)
  2. Check cache (phone_identity collection, freshness-bounded)
  3. Check Official Organisation Directory (Tier 1: the organisation's own page names this number)
  4. Check org_directory.number_verdict (Tier 2: not the official number but a known org is named)
  5. Check Apollo Knowledge Base for any existing research on this number
  6. Web search (Brave, same as TC FlyBy) — only when above sources leave it unresolved
  7. Deterministic association assessment (fixed rules, no AI)
  8. Cache with provenance

Constraints (from PRD):
- Do NOT use paid reverse-lookup APIs (no Truecaller, no WhitePages, no paid IPQS identity)
- Use existing Apollo KB, org_directory and Brave search only
- Every piece of evidence keeps its source URL, publisher and tier
- A search result on the subject's own domain is never a warning about it
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, Field

from core.db import db, now_utc
from services import brave_search, kb_sources, org_directory
from services.number_details import describe as describe_number
from services.phonerisk import normalize_phone

log = logging.getLogger("apollo.phone_identity")

# ── Configuration ──────────────────────────────────────────────────────────────

CACHE_TTL = timedelta(days=7)          # Fresh for 7 days
STALE_WINDOW = timedelta(days=30)      # Stale but usable for 30 days
MAX_SEARCH_RESULTS = 8

# ── Types ──────────────────────────────────────────────────────────────────────

class IdentityEvidence(BaseModel):
    source: str                            # URL or source name
    source_type: str                       # tier_1_official / tier_2_government / ... / tier_6_apollo_kb
    publisher: str                         # Who published this evidence
    claim: str                             # What the source establishes (the entity name)
    retrieved_at: str                      # ISO date
    last_verified_at: Optional[str] = None

class PhoneIdentityResult(BaseModel):
    canonical: str
    original: str
    country: Optional[str] = None
    number_type: Optional[str] = None      # mobile / landline / toll_free / ...
    geographic: Optional[str] = None       # for AU landlines
    valid: bool = True
    network: Optional[str] = None          # original carrier from numbering plan

    # Identity resolution
    associated_entity: Optional[str] = None
    association_confidence: str = "unknown"   # verified / strong / possible / unknown / conflicting
    evidence: list[IdentityEvidence] = Field(default_factory=list)
    scam_intel: Optional[str] = None
    known_impersonation: bool = False

    # Freshness
    checked_at: Optional[str] = None
    freshness: Optional[str] = None        # fresh / cached / stale

    # Lookup execution status — distinguishes "checked, nothing found" from "service unavailable"
    # Per source: "match" / "no_match" / "empty_response" / "unavailable" / "timeout" / "not_checked"
    lookup_status: dict[str, str] = Field(default_factory=dict)


# ── Normalisation helpers ──────────────────────────────────────────────────────

_NUMBERISH = re.compile(r"\+?\d[\d\s\-().]{4,18}\d")
_WARNING = re.compile(r"\b(scams?|scammers?|fraud\w*|phish\w*|fake|impersonat\w*|warnings?|alerts?|beware|malicious|suspicious)\b", re.I)


def _digits(raw: str) -> str:
    return re.sub(r"\D", "", raw)


def _national(e164: str) -> str:
    """For AU numbers return the national form for org_directory matching."""
    return org_directory.national(e164)


# ── Association assessment (deterministic, same rules as frontend) ─────────────

def assess_association(evidence: list[IdentityEvidence]) -> tuple[str, Optional[str]]:
    """Returns (confidence, entity_name). Same fixed rules as phoneIdentity.ts assessAssociation."""
    if not evidence:
        return "unknown", None

    # Group by claimed entity (normalised lower-case)
    by_entity: dict[str, list[dict]] = {}
    for e in evidence:
        key = e.claim.lower().strip()
        if not key:
            continue
        by_entity.setdefault(key, []).append({"tier": e.source_type, "claim": e.claim})

    if not by_entity:
        return "unknown", None

    # Conflicting: multiple distinct entity claims
    if len(by_entity) > 1:
        entities = list(by_entity.keys())
        substantive = any(
            not _names_match(a, b)
            for i, a in enumerate(entities)
            for b in entities[i + 1:]
        )
        if substantive:
            return "conflicting", None

    # Single entity (or name variations)
    entity_key, sources = max(by_entity.items(), key=lambda kv: len(kv[1]))
    entity = sources[0]["claim"]  # Use the original casing

    has_tier1 = any(s["tier"] == "tier_1_official" for s in sources)
    if has_tier1:
        return "verified", entity

    has_tier2 = any(s["tier"] in ("tier_2_government", "tier_3_regulatory") for s in sources)
    if has_tier2:
        return "strong", entity

    tier34_count = sum(1 for s in sources if s["tier"] in ("tier_4_web", "tier_3_regulatory"))
    if tier34_count >= 2:
        return "strong", entity

    has_tier4 = any(s["tier"] == "tier_4_web" for s in sources)
    if has_tier4:
        return "possible", entity

    tier5_count = sum(1 for s in sources if s["tier"] == "tier_5_community")
    if tier5_count >= 2:
        return "possible", entity

    return "possible", entity


def _names_match(a: str, b: str) -> bool:
    """Fuzzy name matching: 'RAC WA' vs 'RAC Western Australia' → True."""
    if a == b:
        return True
    if a in b or b in a:
        return True
    tok_a = {t for t in a.split() if len(t) > 1}
    tok_b = {t for t in b.split() if len(t) > 1}
    if not tok_a or not tok_b:
        return False
    overlap = len(tok_a & tok_b)
    return overlap / min(len(tok_a), len(tok_b)) >= 0.5


# ── Cache key ──────────────────────────────────────────────────────────────────

def _cache_key(e164: str) -> str:
    return hashlib.sha256(f"phone_identity:{e164}".encode()).hexdigest()[:32]


# ── Stage 1: Numbering plan (local, free) ──────────────────────────────────────

def _number_details(e164: str, country: Optional[str]) -> dict:
    """Type, country, carrier from the built-in numbering plan. No network call."""
    try:
        details = describe_number(e164, country)
        return {
            "valid": details.valid,
            "country": details.country,
            "country_code": details.country_code,
            "number_type": details.line_type,
            "network": details.network,
        }
    except Exception:
        return {"valid": True, "country": None, "country_code": None, "number_type": None, "network": None}


# ── Stage 2: Official Organisation Directory (Tier 1) ─────────────────────────

def _check_org_directory(e164: str) -> list[IdentityEvidence]:
    """Check if this number is published in the Official Organisation Directory."""
    evidence = []

    # Direct match: this number IS one of the organisation's published numbers
    owner = org_directory.phone_owner(e164)
    if owner:
        evidence.append(IdentityEvidence(
            source=owner.get("source_url") or "Official Organisation Directory",
            source_type="tier_1_official",
            publisher=owner["name"],
            claim=owner["name"],
            retrieved_at=now_utc().isoformat(),
            last_verified_at=(owner["confirmed_at"].isoformat() if isinstance(owner.get("confirmed_at"), datetime) else None),
        ))
        return evidence

    return evidence


# ── Stage 3: Apollo Knowledge Base ─────────────────────────────────────────────

async def _check_apollo_kb(e164: str) -> list[IdentityEvidence]:
    """Check if the Apollo KB has specific official organisation records mentioning this number.

    Only checks official_organisation records (not generic articles) to avoid false positives
    from articles that merely mention a number as an example."""
    national_form = _national(e164)
    digits = _digits(e164)
    evidence = []

    # Search official_organisation records that list this phone number
    # These are the same records org_directory uses, but checking for numbers
    # that might not be "confirmed" yet (unchecked/not_found status)
    async for record in db.higgins_knowledge.find(
        {"kind": "official_organisation", "status": {"$ne": "archived"},
         "phones.national": national_form},
        {"_id": 0, "name": 1, "phones": 1, "sources": 1, "provenance": 1},
    ).limit(3):
        # The phone is listed in an org record but might not be confirmed yet
        matched = next((p for p in (record.get("phones") or []) if p.get("national") == national_form), None)
        if matched:
            source_url = matched.get("source_url") or (record.get("sources") or [{}])[0].get("url") or "Official Organisation Directory"
            confirmed_status = matched.get("status", "unchecked")
            # Only count if it's at least listed (even unchecked)
            tier = "tier_1_official" if confirmed_status == "confirmed" else "tier_6_apollo_kb"
            evidence.append(IdentityEvidence(
                source=source_url,
                source_type=tier,
                publisher=record["name"],
                claim=record["name"],
                retrieved_at=now_utc().isoformat(),
                last_verified_at=(matched["confirmed_at"].isoformat()
                                  if isinstance(matched.get("confirmed_at"), datetime) else None),
            ))

    # Also check ASIC/government threat feed records that specifically name this number
    if not evidence and len(digits) >= 8:
        tail = digits[-8:]
        async for record in db.higgins_knowledge.find(
            {"kind": "researched", "status": "current",
             "authority_tier": {"$in": ["T1", "T2", "T3"]},
             "body": {"$regex": re.escape(tail)}},
            {"_id": 0, "title": 1, "url": 1, "publisher": 1, "authority_tier": 1, "provenance": 1},
        ).limit(3):
            tier_map = {"T1": "tier_2_government", "T2": "tier_2_government", "T3": "tier_3_regulatory"}
            source_type = tier_map.get(record.get("authority_tier", ""), "tier_4_web")
            prov = record.get("provenance") or {}
            publisher = record.get("publisher") or prov.get("publisher") or "Apollo Knowledge Base"
            evidence.append(IdentityEvidence(
                source=record.get("url") or "Apollo Knowledge Base",
                source_type=source_type,
                publisher=publisher,
                claim=publisher,  # The publisher itself is likely the entity warning about this number
                retrieved_at=now_utc().isoformat(),
            ))

    return evidence


# ── Stage 4: Web search (Brave, same as TC FlyBy) ─────────────────────────────

async def _web_search(e164: str, national_form: str) -> tuple[list[IdentityEvidence], str]:
    """Search the web for this number. Returns (evidence, status).
    Status: 'match' | 'no_match' | 'empty_response' | 'unavailable' | 'timeout' | 'not_checked'."""
    if not brave_search.configured():
        return [], "unavailable"

    # Build search query with number variants
    queries = []
    if e164.startswith("+"):
        queries.append(f'"{e164}"')
    if national_form and national_form != e164:
        queries.append(f'"{national_form}"')
        # Spaced form
        if national_form.startswith("0") and len(national_form) == 10:
            if national_form[1] == "4":
                spaced = f"{national_form[:4]} {national_form[4:7]} {national_form[7:]}"
            else:
                spaced = f"{national_form[:2]} {national_form[2:6]} {national_form[6:]}"
            queries.append(f'"{spaced}"')

    q = " OR ".join(queries[:3])
    if not q:
        return [], "not_checked"

    evidence = []
    try:
        results = await brave_search.search(q, correlation_id=f"phone-identity-{_digits(e164)[-6:]}",
                                             trigger_source="phone_identity")
    except TimeoutError:
        log.info("phone_identity web search timeout: e164=%s…%s", e164[:4], e164[-3:])
        return [], "timeout"
    except (brave_search.SearchUnavailable, Exception) as exc:
        log.info("phone_identity web search unavailable: %s", exc)
        return [], "unavailable"

    if not results:
        return [], "empty_response"

    digits_tail = _digits(e164)[-8:] if len(_digits(e164)) >= 8 else _digits(e164)

    for result in results[:MAX_SEARCH_RESULTS]:
        url = result.get("url") or ""
        title = result.get("title") or ""
        desc = result.get("description") or ""
        snippets = result.get("extraSnippets") or []
        combined = f"{title} {desc} {' '.join(snippets)}"

        # Only count if the result actually names this number
        found_numbers = [_digits(n) for n in _NUMBERISH.findall(combined)]
        if not any(n.endswith(digits_tail) for n in found_numbers if len(digits_tail) >= 8):
            continue

        # Determine source authority
        host = _host(url)
        source = kb_sources.source_for(f"https://{host}")
        if source and source.tier == kb_sources.TIER_1:
            source_type = "tier_2_government"  # Government/regulator
            publisher = source.publisher
        elif source:
            source_type = "tier_4_web"
            publisher = source.publisher
        else:
            source_type = "tier_5_community"
            publisher = host

        # Extract a claim (entity) from the result
        entity = _extract_entity_from_search(title, desc, host)
        if not entity:
            continue

        # Is this a warning/scam report or an identity association?
        if _WARNING.search(combined):
            # This is scam intel, not an identity association
            continue

        evidence.append(IdentityEvidence(
            source=url,
            source_type=source_type,
            publisher=publisher,
            claim=entity,
            retrieved_at=now_utc().isoformat(),
        ))

    return evidence, ("match" if evidence else "no_match")


def _host(url: str) -> str:
    match = re.match(r"^[a-z]+://([^/?#]+)", url or "", re.I)
    return (match.group(1) if match else "").lower().split("@")[-1].split(":")[0].removeprefix("www.")


def _extract_entity_from_search(title: str, desc: str, host: str) -> Optional[str]:
    """Extract an entity name from a search result about a phone number."""
    # Common patterns in search results:
    # "Phone Number for <Entity>" / "<Entity> Contact Details" / "<Entity> Phone Numbers"
    patterns = [
        re.compile(r"(?:phone|contact|call)\s+(?:number|details|info)\s+(?:for|of)\s+(.+?)(?:\s*[-–|]|$)", re.I),
        re.compile(r"^(.+?)\s+(?:contact|phone|call)\s+(?:number|details|info)", re.I),
        re.compile(r"^(.+?)\s*[-–|]\s+(?:contact|phone)", re.I),
    ]
    for pattern in patterns:
        for text in [title, desc]:
            m = pattern.search(text)
            if m:
                name = m.group(1).strip()
                if 2 <= len(name) <= 60 and not _WARNING.search(name):
                    return name

    # Fallback: if the host is a well-known org's own site, use that
    source = kb_sources.source_for(f"https://{host}")
    if source and source.tier == kb_sources.TIER_1:
        return source.publisher

    return None


# ── Stage 5: Scam intel from IPQS cache ───────────────────────────────────────

async def _check_scam_intel(e164: str) -> Optional[str]:
    """Check if IPQS has flagged this number (from the cached phone_risk_cache)."""
    cached = await db.phone_risk_cache.find_one({"phone_e164": e164}, {"_id": 0, "fraud_score": 1, "recent_abuse": 1, "risky": 1})
    if not cached:
        return None
    score = cached.get("fraud_score")
    if cached.get("recent_abuse"):
        return f"This number has been reported for recent abuse (fraud score: {score}/100)."
    if score is not None and score >= 85:
        return f"This number has elevated fraud risk signals (fraud score: {score}/100)."
    return None


# ── Stage 6: Impersonation check ──────────────────────────────────────────────

def _check_impersonation(e164: str, entity: Optional[str]) -> bool:
    """Check if the number's claimed identity doesn't match its org directory verdict."""
    if not entity:
        return False
    verdict = org_directory.number_verdict(e164, entity)
    if verdict and verdict.get("status") == "not_published":
        return True
    return False


# ── Main resolution pipeline ──────────────────────────────────────────────────

async def identify(raw_number: str, country: Optional[str] = None) -> PhoneIdentityResult:
    """Resolve who a phone number belongs to. Returns a PhoneIdentityResult."""
    # Step 1: Normalize
    e164 = normalize_phone(raw_number, country)
    now = now_utc()

    # Step 2: Check cache
    cache_id = _cache_key(e164)
    cached = await db.phone_identity.find_one({"cache_id": cache_id}, {"_id": 0})
    if cached:
        cached_at = cached.get("checked_at")
        if isinstance(cached_at, datetime):
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=timezone.utc)
            age = now - cached_at
            if age <= CACHE_TTL:
                log.info("phone_identity cache_hit e164=%s…%s", e164[:4], e164[-3:])
                cached_result = {k: v for k, v in cached["result"].items() if k != "freshness"}
                return PhoneIdentityResult(**cached_result, freshness="cached")
            elif age <= STALE_WINDOW:
                # Stale but usable — return it while we could refresh in background
                log.info("phone_identity stale_hit e164=%s…%s", e164[:4], e164[-3:])
                cached_result = {k: v for k, v in cached["result"].items() if k != "freshness"}
                return PhoneIdentityResult(**cached_result, freshness="stale")

    # Step 3: Number details from numbering plan
    details = _number_details(e164, country)
    lookup_status: dict[str, str] = {}

    # Step 4: Official Organisation Directory (Tier 1)
    evidence = _check_org_directory(e164)
    lookup_status["org_directory"] = "match" if evidence else "no_match"

    # Step 5: Apollo Knowledge Base
    if not evidence:
        kb_evidence = await _check_apollo_kb(e164)
        evidence.extend(kb_evidence)
        lookup_status["apollo_kb"] = "match" if kb_evidence else "no_match"
    else:
        lookup_status["apollo_kb"] = "not_checked"

    # Step 6: Web search (only if we still don't have evidence)
    if not evidence:
        national_form = _national(e164)
        web_evidence, web_status = await _web_search(e164, national_form)
        evidence.extend(web_evidence)
        lookup_status["web_search"] = web_status
    else:
        lookup_status["web_search"] = "not_checked"

    # Step 7: Scam intel
    scam_intel = await _check_scam_intel(e164)

    # Step 8: Deterministic association
    confidence, entity = assess_association(evidence)

    # Step 9: Impersonation check
    known_impersonation = _check_impersonation(e164, entity)

    # Build geographic description for AU landlines
    geographic = None
    if details.get("country_code") == "AU" and details.get("number_type") == "Landline":
        # Map area code to region
        nat = e164[3] if e164.startswith("+61") and len(e164) > 3 else None
        area_map = {"2": "New South Wales, ACT", "3": "Victoria, Tasmania", "7": "Queensland",
                    "8": "Western Australia, South Australia, Northern Territory"}
        geographic = area_map.get(nat)

    result = PhoneIdentityResult(
        canonical=e164,
        original=raw_number.strip(),
        country=details.get("country"),
        number_type=details.get("number_type"),
        geographic=geographic,
        valid=details.get("valid", True),
        network=details.get("network"),
        associated_entity=entity,
        association_confidence=confidence,
        evidence=evidence,
        scam_intel=scam_intel,
        known_impersonation=known_impersonation,
        checked_at=now.isoformat(),
        freshness="fresh",
        lookup_status=lookup_status,
    )

    # Step 10: Cache the result
    await db.phone_identity.update_one(
        {"cache_id": cache_id},
        {"$set": {
            "cache_id": cache_id,
            "e164": e164,
            "checked_at": now,
            "result": result.model_dump(),
        }},
        upsert=True,
    )

    log.info("phone_identity resolved e164=%s…%s confidence=%s entity=%s",
             e164[:4], e164[-3:], confidence, entity or "(none)")
    return result


# ── Indexes ────────────────────────────────────────────────────────────────────

async def ensure_indexes() -> None:
    await db.phone_identity.create_index("cache_id", unique=True)
    await db.phone_identity.create_index("e164")
    await db.phone_identity.create_index("checked_at")
