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

class PrefixIntelligenceTier(BaseModel):
    """One tier of the progressive phone-number intelligence model."""
    tier: str                              # "geographic" | "number_block" | "caller"
    description: str                       # Plain-English finding for this tier
    entity: Optional[str] = None           # Associated entity name (null when unknown)
    qualifier: str                         # "regional association" | "possible association" | "verified identity" | "strong association" | "unknown"
    confidence: str                        # "high" | "medium" | "low"
    prefix: str                            # The prefix or number that was matched
    detail: Optional[str] = None           # Additional geographic or context info


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

    # Progressive prefix intelligence (3 tiers: geographic → number_block → caller)
    prefix_intelligence: list[PrefixIntelligenceTier] = Field(default_factory=list)

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

# ── Australian prefix knowledge base ──────────────────────────────────────────
# Richer geographic and number-block intelligence for progressive investigation.

AU_AREA_CODES: dict[str, dict] = {
    "02": {"region": "New South Wales, Australian Capital Territory", "cities": ["Sydney", "Canberra", "Newcastle", "Wollongong"]},
    "03": {"region": "Victoria, Tasmania", "cities": ["Melbourne", "Hobart", "Geelong", "Ballarat"]},
    "07": {"region": "Queensland", "cities": ["Brisbane", "Gold Coast", "Cairns", "Townsville"]},
    "08": {"region": "Western Australia, South Australia, Northern Territory", "cities": ["Perth", "Adelaide", "Darwin"]},
}

# Sub-area prefixes: narrower geographic intelligence within area codes.
AU_SUB_AREA_PREFIXES: dict[str, dict] = {
    # WA / SA / NT breakdown within 08
    "086": {"area": "Perth metropolitan area", "state": "Western Australia"},
    "0861": {"area": "Perth inner metropolitan", "state": "Western Australia"},
    "0862": {"area": "Perth metropolitan", "state": "Western Australia"},
    "0863": {"area": "Perth metropolitan", "state": "Western Australia"},
    "0864": {"area": "Perth metropolitan", "state": "Western Australia"},
    "0865": {"area": "Perth metropolitan", "state": "Western Australia"},
    "089": {"area": "Northern Territory", "state": "Northern Territory"},
    "0889": {"area": "Darwin and surrounds", "state": "Northern Territory"},
    "088": {"area": "South Australia", "state": "South Australia"},
    "0882": {"area": "Adelaide metropolitan", "state": "South Australia"},
    "0883": {"area": "Adelaide metropolitan", "state": "South Australia"},
    # NSW breakdown within 02
    "029": {"area": "Sydney metropolitan", "state": "New South Wales"},
    "028": {"area": "Sydney metropolitan", "state": "New South Wales"},
    "024": {"area": "Central Coast, Hunter, Blue Mountains", "state": "New South Wales"},
    "026": {"area": "Canberra, Southern NSW", "state": "Australian Capital Territory"},
    # VIC breakdown within 03
    "039": {"area": "Melbourne metropolitan", "state": "Victoria"},
    "038": {"area": "Melbourne metropolitan", "state": "Victoria"},
    "035": {"area": "Regional Victoria", "state": "Victoria"},
    "036": {"area": "Tasmania", "state": "Tasmania"},
    # QLD breakdown within 07
    "073": {"area": "Brisbane metropolitan", "state": "Queensland"},
    "074": {"area": "Sunshine Coast, regional Queensland", "state": "Queensland"},
    "075": {"area": "Gold Coast", "state": "Queensland"},
    "077": {"area": "North Queensland, Townsville", "state": "Queensland"},
}

# Known number-block associations: prefix → likely entity.
# These are NEVER "verified" — they represent "possible association" or "lead" intelligence only.
AU_NUMBER_BLOCK_ASSOCIATIONS: dict[str, dict] = {
    "08611664": {"entity": "RAC WA", "context": "RAC contacts members about roadside assistance, insurance, membership and travel services.", "confidence": "low"},
    "08611663": {"entity": "RAC WA", "context": "RAC contacts members about roadside assistance, insurance, membership and travel services.", "confidence": "low"},
    "0861166": {"entity": "RAC WA", "context": "RAC uses Perth-area numbers in the 08 6116 range for customer contact.", "confidence": "low"},
    "131111": {"entity": "RAC WA Roadside Assistance", "context": "RAC WA's nationally recognised roadside assistance hotline.", "confidence": "high"},
    "131132": {"entity": "NRMA", "context": "NRMA roadside assistance hotline.", "confidence": "high"},
    "132211": {"entity": "Telstra", "context": "Telstra's main customer service line.", "confidence": "high"},
    "131444": {"entity": "Police Assistance Line", "context": "Non-emergency police reporting across Australia.", "confidence": "high"},
    "131450": {"entity": "Translating and Interpreting Service", "context": "Australian Government translating service.", "confidence": "high"},
    "000": {"entity": "Emergency Services", "context": "Triple Zero — police, fire, ambulance.", "confidence": "high"},
    "131114": {"entity": "Lifeline", "context": "24-hour crisis support and suicide prevention.", "confidence": "high"},
    "1300363400": {"entity": "NBN Co", "context": "National Broadband Network customer service.", "confidence": "medium"},
    "1300555135": {"entity": "ATO", "context": "Australian Taxation Office general enquiries.", "confidence": "medium"},
    "1300360380": {"entity": "Centrelink", "context": "Centrelink (Services Australia) general line.", "confidence": "medium"},
}


def _prefix_intelligence(e164: str, details: dict) -> list[PrefixIntelligenceTier]:
    """Build progressive prefix intelligence for an Australian phone number.

    Returns up to 2 tiers (geographic + number_block). The caller tier is added
    later in the pipeline from the exact-number lookup results.

    Number-block matches are NEVER promoted to verified — they always carry
    'possible association' qualification.
    """
    tiers: list[PrefixIntelligenceTier] = []
    country_code = details.get("country_code")

    if country_code != "AU":
        return tiers

    # Derive the national-format number (without leading 0)
    national = e164[3:] if e164.startswith("+61") and len(e164) > 3 else None
    if not national:
        return tiers

    # Reconstruct the local dialling form: 0 + national digits
    local = "0" + national

    # ── Tier 1: Geographic (area code) ──
    area_code = local[:2]  # e.g. "08"
    area_info = AU_AREA_CODES.get(area_code)
    if area_info:
        # Check for sub-area precision
        sub_area = None
        for prefix_len in (5, 4, 3):
            sub_key = local[:prefix_len]
            if sub_key in AU_SUB_AREA_PREFIXES:
                sub_area = AU_SUB_AREA_PREFIXES[sub_key]
                break

        if sub_area:
            desc = f"Australian geographic number in the {sub_area['area']} ({area_code} prefix), {sub_area['state']}."
            detail = f"Part of the {area_info['region']} numbering region."
        else:
            desc = f"Australian geographic number in the {area_info['region']} region ({area_code} prefix)."
            detail = f"Major cities in this region: {', '.join(area_info['cities'][:3])}."

        tiers.append(PrefixIntelligenceTier(
            tier="geographic",
            description=desc,
            entity=None,
            qualifier="regional association",
            confidence="high",
            prefix=area_code,
            detail=detail,
        ))

    # Also check mobile prefixes
    if local.startswith("04"):
        tiers.append(PrefixIntelligenceTier(
            tier="geographic",
            description="Australian mobile number (04 prefix).",
            entity=None,
            qualifier="regional association",
            confidence="high",
            prefix="04",
            detail="Mobile numbers are not geographically fixed — the owner could be anywhere in Australia.",
        ))

    # ── Tier 2: Number-block (narrower prefix association) ──
    # Check from most specific prefix to least specific
    for prefix_len in range(len(local), 2, -1):
        prefix = local[:prefix_len]
        block = AU_NUMBER_BLOCK_ASSOCIATIONS.get(prefix)
        if block:
            entity = block["entity"]
            context = block["context"]
            conf = block["confidence"]

            # Number-block intelligence is NEVER "verified identity"
            qualifier = "possible association"
            if conf == "high":
                # Well-known service numbers (like 131111) get "strong association" but still not "verified"
                qualifier = "strong association"

            tiers.append(PrefixIntelligenceTier(
                tier="number_block",
                description=f"The number range appears to be associated with {entity}.",
                entity=entity,
                qualifier=qualifier,
                confidence=conf,
                prefix=prefix,
                detail=context,
            ))
            break  # Only the most specific match

    # Also try the e164 form for service numbers
    if not any(t.tier == "number_block" for t in tiers):
        digits = re.sub(r"\D", "", e164)
        for prefix_len in range(len(digits), 2, -1):
            prefix = digits[:prefix_len]
            block = AU_NUMBER_BLOCK_ASSOCIATIONS.get(prefix)
            if block:
                tiers.append(PrefixIntelligenceTier(
                    tier="number_block",
                    description=f"The number range appears to be associated with {block['entity']}.",
                    entity=block["entity"],
                    qualifier="strong association" if block["confidence"] == "high" else "possible association",
                    confidence=block["confidence"],
                    prefix=prefix,
                    detail=block["context"],
                ))
                break

    # Also check national form directly (for service numbers like 13xxxx, 1300xxxxxx)
    if not any(t.tier == "number_block" for t in tiers):
        for prefix_len in range(len(national), 2, -1):
            prefix = national[:prefix_len]
            block = AU_NUMBER_BLOCK_ASSOCIATIONS.get(prefix)
            if block:
                tiers.append(PrefixIntelligenceTier(
                    tier="number_block",
                    description=f"This is a known service number associated with {block['entity']}.",
                    entity=block["entity"],
                    qualifier="strong association" if block["confidence"] == "high" else "possible association",
                    confidence=block["confidence"],
                    prefix=prefix,
                    detail=block["context"],
                ))
                break

    return tiers

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

    # Step 3b: Progressive prefix intelligence (geographic + number-block tiers)
    prefix_tiers = _prefix_intelligence(e164, details)

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

    # Step 10: Build caller tier from exact-number lookup results
    caller_tier = PrefixIntelligenceTier(
        tier="caller",
        description=(
            f"Exact-number lookup identified {entity} ({confidence} confidence)."
            if entity else "No exact-number identity was established."
        ),
        entity=entity,
        qualifier={
            "verified": "verified identity",
            "strong": "strong association",
            "possible": "possible association",
            "conflicting": "conflicting information",
        }.get(confidence, "unknown"),
        confidence={
            "verified": "high",
            "strong": "medium",
            "possible": "low",
        }.get(confidence, "low"),
        prefix=e164,
        detail=(
            f"Based on {len(evidence)} source(s): "
            + ", ".join(sorted({e.publisher for e in evidence}))
            if evidence else "Apollo checked its Official Organisation Directory, knowledge base, and public sources."
        ),
    )

    # Assemble all tiers: geographic → number_block → caller
    all_tiers = prefix_tiers + [caller_tier]

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
        prefix_intelligence=all_tiers,
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
