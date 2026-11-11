"""Wright Triage — Tier 1 server-side entry point. ZERO Gemini calls, always.

Tier 1 (here): deterministic catalogue rules (services/triage) over normalised
    evidence plus specialist provider results. Outcome is one of
    NO THREAT IDENTIFIED / POSSIBLE THREAT IDENTIFIED / LIMITED-UNABLE TO DETERMINE.
Tier 2 (the investigation): started by the caller ONLY for POSSIBLE THREAT — one correlated
    case, investigated by TC Hawkeye first and by Magnum DI (exactly one Gemini call) only
    when a deeper look could change the answer.

DESIGN PRINCIPLES:
    • No AI triage tier exists. There is no fallback that spends tokens on
      uncertainty, errors, timeouts or missing evidence.
    • Missing evidence is recorded as a Coverage Gap. It can prevent NO THREAT but
      can never create POSSIBLE THREAT, and never downgrades real threat evidence.
    • Cache uses risk-aware expiry (30d possible-threat, 7d no-threat). LIMITED is
      never cached — a transient gap must not suppress a later successful check.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from core.db import db, now_utc
from services.triage import Outcome, TriageInvestigation, evaluate, legacy_outcome, run_with_retries
from services.intel import answered, listed_by
from services.triage.completeness import from_sources, incomplete_check

_log = logging.getLogger("apollo.triage")

# ── Result data class ───────────────────────────────────────────────────────

@dataclass
class TriageResult:
    outcome: Outcome
    reason: str
    investigation: Optional[TriageInvestigation] = None
    cached: bool = False
    cache_key: Optional[str] = None
    source_type: str = ""            # "email", "text", etc.
    indicators_summary: dict = field(default_factory=dict)
    provider_evidence: dict = field(default_factory=dict)  # Specialist provider results with provenance
    providers_used: list = field(default_factory=list)      # Which providers contributed
    #: Triage never spends tokens. Kept explicit so cost reporting stays auditable.
    cost_usd: float = 0.0

    @property
    def should_escalate(self) -> bool:
        """Only a deterministic POSSIBLE THREAT may open one investigation case (TC Hawkeye first, Magnum DI only if needed)."""
        return self.outcome is Outcome.POSSIBLE_THREAT

    @property
    def escalation_reason(self) -> Optional[str]:
        return self.reason if self.outcome is Outcome.POSSIBLE_THREAT else None

    @property
    def coverage_gaps(self) -> list:
        return list(self.investigation.coverage_gaps) if self.investigation else []

    def wire(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "reason": self.reason,
            "cached": self.cached,
            "source_type": self.source_type,
            "providers_used": self.providers_used,
            "geminiCalls": 0,
            "investigation": self.investigation.wire() if self.investigation else None,
        }

    def compact_evidence_for_magnum_di(self) -> str:
        """Produce a compact, provenance-attributed summary of all specialist
        provider findings.  Delegates to the module-level function for a single
        canonical implementation; the method form exists for caller convenience.
        """
        return compact_evidence_for_magnum_di(self.provider_evidence)


def compact_evidence_for_magnum_di(provider_evidence: dict) -> str:
    """Standalone version of TriageResult.compact_evidence_for_magnum_di.
    Produces a compact provenance-attributed summary from a raw provider_evidence dict.
    Used by manual Check pre-gathering where there is no TriageResult."""
    lines = ["Pre-gathered specialist intelligence (Wright Triage):"]
    pe = provider_evidence

    for domain, info in pe.get("rdap", {}).get("domains", {}).items():
        if info.get("status") == "ok":
            reg = info.get("registration_date", "unknown")
            registrar = info.get("registrar", "unknown")
            newly = " — NEWLY REGISTERED (≤30 days)" if info.get("newly_registered") else ""
            lines.append(f"  • Domain {domain}: registered {reg} via {registrar}{newly} (RDAP, {info.get('queried_at', '?')})")
    for url, info in pe.get("safe_browsing", {}).get("urls", {}).items():
        if info.get("verdict") == "malicious":
            threats = ", ".join(info.get("threat_types", []))
            lines.append(f"  • URL {url}: LISTED as {threats} by {listed_by(info.get('sources'))} ({info.get('queried_at', '?')})")
        elif info.get("verdict") == "clean":
            lines.append(f"  • URL {url}: Not currently listed by {answered(info.get('sources'))} ({info.get('queried_at', '?')})")
    for url, info in pe.get("redirects", {}).get("urls", {}).items():
        chain = info.get("chain", [])
        if len(chain) > 1:
            final = info.get("final_url")
            destination = final if final else f"NOT CONFIRMED — {info.get('detail') or 'the chain could not be followed to the end'}; last seen: {info.get('last_seen_url', chain[-1])}"
            lines.append(f"  • URL {url}: redirects through {len(chain)} hops → final: {destination} ({info.get('queried_at', '?')})")
    for phone, info in pe.get("ipqs", {}).get("phones", {}).items():
        if info.get("status") == "ok":
            score = info.get("fraud_score", "?")
            abuse = "; RECENT ABUSE" if info.get("recent_abuse") else ""
            carrier = info.get("carrier", "unknown")
            lines.append(f"  • Phone {phone}: IPQS fraud score {score}/100, carrier: {carrier}{abuse} ({info.get('queried_at', '?')})")
    for url, info in pe.get("ipqs", {}).get("urls", {}).items():
        if info.get("status") == "ok":
            score = info.get("risk_score", "?")
            decision = info.get("decision", "unknown")
            flags = []
            if info.get("phishing"): flags.append("PHISHING")
            if info.get("malware"): flags.append("MALWARE")
            if info.get("suspicious"): flags.append("SUSPICIOUS")
            if info.get("parking"): flags.append("PARKED DOMAIN")
            flag_str = f" — {', '.join(flags)}" if flags else ""
            lines.append(f"  • URL {url[:120]}: IPQS risk score {score}/100, decision: {decision}{flag_str} ({info.get('queried_at', '?')})")
    for item in pe.get("download_links", {}).get("items", []):
        lines.append(f"  • DOWNLOAD LINK DETECTED: {item.get('url', '?')[:120]} → file: {item.get('filename', '?')} [{item.get('category', 'unknown')}] — direct file download links in unsolicited messages are a common malware delivery method")
    # VirusTotal URL reputation
    for url, info in pe.get("virustotal", {}).get("urls", {}).items():
        if info.get("status") == "ok":
            verdict = info.get("verdict", "unknown")
            det = info.get("detection_count", 0)
            total = info.get("total_engines", 0)
            if verdict == "malicious":
                lines.append(f"  • URL {url[:120]}: VirusTotal FLAGGED — {det}/{total} engines, verdict: malicious ({info.get('queried_at', '?')})")
            elif verdict == "suspicious":
                lines.append(f"  • URL {url[:120]}: VirusTotal suspicious — {det}/{total} engines ({info.get('queried_at', '?')})")
            elif verdict == "clean":
                lines.append(f"  • URL {url[:120]}: VirusTotal clean — {total} engines checked ({info.get('queried_at', '?')})")
    for email, info in pe.get("hibp", {}).get("emails", {}).items():
        if info.get("status") == "found":
            count = len(info.get("breaches", []))
            lines.append(f"  • Email {email}: found in {count} known breach(es) ({info.get('queried_at', '?')})")
        elif info.get("status") == "clear":
            lines.append(f"  • Email {email}: not found in known breaches ({info.get('queried_at', '?')})")
    for match in pe.get("scam_intel", {}).get("matches", []):
        lines.append(f"  • Active scam advisory match: \"{match.get('title', '?')}\" — severity: {match.get('severity', '?')}, matched on: {match.get('matched_on', '?')}")

    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _extract_indicators(text: str) -> dict:
    """Extract URLs, domains, phone numbers and emails from arbitrary text.
    Used by manual Check pre-gathering to identify indicators to check."""
    import re as _re
    result: dict = {"urls": [], "domains": [], "phones": [], "emails": []}

    # URLs
    url_matches = _re.findall(r'https?://[^\s<>"\')\]]+', text)
    result["urls"] = list(dict.fromkeys(url_matches))[:10]

    # Domains from URLs
    from urllib.parse import urlparse
    for url in result["urls"]:
        try:
            host = urlparse(url).hostname
            if host:
                result["domains"].append(host)
        except Exception:
            pass

    # Emails
    email_matches = _re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', text)
    result["emails"] = list(dict.fromkeys(email_matches))[:10]

    # Phone numbers (basic E.164 and common formats)
    phone_matches = _re.findall(r'(?:\+\d{1,3}[\s-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}', text)
    result["phones"] = list(dict.fromkeys(phone_matches))[:10]

    result["domains"] = list(dict.fromkeys(result["domains"]))[:10]
    return result


# ── Collection ──────────────────────────────────────────────────────────────

COLLECTION = "triage_results"


async def ensure_indexes() -> None:
    coll = db[COLLECTION]
    await coll.create_index("fingerprint")
    await coll.create_index("created_at")
    await coll.create_index("expires_at")
    await coll.create_index([("device_id", 1), ("fingerprint", 1)])
    await coll.create_index([("outcome", 1)])


# ── Cache TTL policy (risk-aware) ──────────────────────────────────────────

_CACHE_TTL = {
    Outcome.NO_THREAT: timedelta(days=7),         # Deterministically clean
    Outcome.POSSIBLE_THREAT: timedelta(days=30),  # Known-bad indicator
    # LIMITED is never cached — a transient gap must not suppress a later check.
}


def _cache_ttl(outcome: Outcome) -> Optional[timedelta]:
    """Return cache TTL or None if this result should not be cached."""
    return _CACHE_TTL.get(outcome)


# ── Fingerprint computation ─────────────────────────────────────────────────

def compute_fingerprint(evidence: dict) -> str:
    """Compute a normalized indicator fingerprint from structured evidence.

    Captures the MATERIAL identity of the threat indicator:
    - Sender domain (not display name)
    - Subject line (normalized lowercase, stripped of Re:/Fwd:)
    - Link destination domains (sorted, deduplicated)
    - Authentication results (SPF/DKIM/DMARC)
    - Attachment extensions (sorted)

    Does NOT include:
    - Message body text (too variable)
    - Timestamps
    - Message IDs
    """
    parts = []

    # Sender domain
    sender = evidence.get("sender_domain", "").lower().strip()
    if sender:
        parts.append(f"sender:{sender}")

    # Normalized subject
    subject = evidence.get("subject", "").lower().strip()
    subject = re.sub(r"^(?:re:|fwd?:|fw:)\s*", "", subject, flags=re.IGNORECASE).strip()
    if subject:
        parts.append(f"subject:{subject[:200]}")  # Cap at 200 chars

    # Link domains (sorted, unique)
    link_domains = sorted(set(
        d.lower() for d in evidence.get("link_domains", []) if d
    ))
    if link_domains:
        parts.append(f"links:{','.join(link_domains[:20])}")

    # Auth results
    auth = evidence.get("auth_results", {})
    if auth:
        auth_str = "|".join(f"{k}={v}" for k, v in sorted(auth.items()) if v)
        if auth_str:
            parts.append(f"auth:{auth_str}")

    # Attachment extensions
    exts = sorted(set(evidence.get("attachment_extensions", [])))
    if exts:
        parts.append(f"attachments:{','.join(exts)}")

    # Reply-to domain mismatch indicator
    reply_domain = evidence.get("reply_to_domain", "").lower().strip()
    if reply_domain and reply_domain != sender:
        parts.append(f"reply_to:{reply_domain}")

    # The rule catalogue's version: a result reached under earlier rules is never reused as this one's.
    from services.triage.catalogue import VERSION
    parts.append(f"catalogue:{VERSION}")
    fingerprint_input = "|".join(parts)
    return hashlib.sha256(fingerprint_input.encode()).hexdigest()


# ── Cache lookup & storage ──────────────────────────────────────────────────

async def _cache_lookup(fingerprint: str, device_id: str) -> Optional[dict]:
    """Look up a cached triage result. Returns None if not found or expired."""
    now = now_utc()
    result = await db[COLLECTION].find_one(
        {
            "fingerprint": fingerprint,
            "device_id": device_id,
            "expires_at": {"$gt": now},
        },
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    if result:
        # Increment cache hit counter
        await db[COLLECTION].update_one(
            {"fingerprint": fingerprint, "device_id": device_id, "created_at": result["created_at"]},
            {"$inc": {"cache_hit_count": 1}, "$set": {"last_hit_at": now}},
        )
    return result


async def _cache_store(
    fingerprint: str,
    device_id: str,
    result: TriageResult,
    evidence_summary: dict,
) -> None:
    """Store a triage result in the cache with risk-aware TTL."""
    ttl = _cache_ttl(result.outcome)
    if ttl is None or (result.investigation and result.investigation.incomplete_checks):
        # Don't cache LIMITED, or a result with a check that didn't complete — the gap may clear on the next check
        return

    now = now_utc()
    doc = {
        "fingerprint": fingerprint,
        "device_id": device_id,
        "outcome": result.outcome.value,
        "reason": result.reason,
        "cost_usd": 0.0,
        "source_type": result.source_type,
        "providers_used": result.providers_used,
        "rules_met": [r.rule_id for r in result.investigation.met_rules] if result.investigation else [],
        "evidence_summary": _without_content(evidence_summary),
        "created_at": now,
        "expires_at": now + ttl,
        "cache_hit_count": 0,
        "last_hit_at": None,
    }
    await db[COLLECTION].insert_one(doc)


def _without_content(evidence: dict) -> dict:
    """What the cache keeps of the evidence: its identifiers, never the message's words or its links as written."""
    return {k: v for k, v in evidence.items() if k not in ("body", "text_preview", "links")}


# ── Record triage outcome (always, including non-cached) ────────────────────

async def record_triage(
    device_id: str,
    fingerprint: str,
    result: TriageResult,
    evidence_summary: dict,
    *,
    cached: bool = False,
) -> None:
    """Record every triage decision for reporting — cached or fresh."""
    now = now_utc()
    investigation = result.investigation
    doc = {
        "record_type": "decision",
        "fingerprint": fingerprint,
        "device_id": device_id,
        "outcome": result.outcome.value,
        "reason": result.reason,
        "cost_usd": 0.0,
        "source_type": result.source_type,
        "cached": cached,
        "providers_used": result.providers_used,
        "gemini_calls": 0,
        "investigation": investigation.wire() if investigation else None,
        "decided_at": now,
    }
    await db[COLLECTION].insert_one(doc)


# ── Evidence extraction ─────────────────────────────────────────────────────

def _extract_evidence_from_email(message: dict) -> dict:
    """The email as received, for fingerprinting and the Triage rules: its sender, subject, body, Reply-To, the
    receiving server's authentication results and each link's displayed text and actual destination. This is the
    source content only — Apollo's own observations about it are kept apart (`findings`) and never stand in for it.
    """
    sender = str(message.get("from", ""))
    subject = str(message.get("subject", ""))
    body = str(message.get("body") or "")
    links = message.get("links", []) if isinstance(message.get("links"), list) else []
    reply_to = str(message.get("reply_to", "")) if message.get("reply_to") else ""
    attachment_names = message.get("attachment_names", []) if isinstance(message.get("attachment_names"), list) else []
    recorded = message.get("auth_results", {}) if isinstance(message.get("auth_results"), dict) else {}
    # Only the results the receiving server actually recorded; "unknown" is no result at all.
    auth_results = {m: str(recorded[m]) for m in ("spf", "dkim", "dmarc") if recorded.get(m) not in (None, "", "unknown")}

    # Extract domains
    from services.mailbox_monitor import _extract_domain_from_email, _org_domain
    sender_domain = _extract_domain_from_email(sender) or ""
    reply_to_domain = _extract_domain_from_email(reply_to) or ""

    # Link domains
    link_domains = []
    from urllib.parse import urlparse
    for link in links:
        href = link.get("href", "") if isinstance(link, dict) else ""
        if href:
            try:
                parsed = urlparse(href if "://" in href else f"https://{href}")
                host = (parsed.hostname or "").lower()
                if host:
                    link_domains.append(host)
            except Exception:
                pass

    # Attachment extensions
    attachment_extensions = []
    for name in attachment_names:
        if "." in name:
            attachment_extensions.append("." + name.rsplit(".", 1)[-1].lower())

    hrefs = [str(link.get("href") or "") for link in links if isinstance(link, dict) and link.get("href")]
    return {
        "sender": sender,
        "sender_domain": sender_domain,
        "subject": subject,
        "body": body,
        "reply_to": reply_to,
        "reply_to_domain": reply_to_domain,
        "link_domains": link_domains,
        # Each link as written: the text shown to the reader and where it actually goes.
        "links": [{"text": str(link.get("text") or "")[:300], "href": str(link.get("href") or "")}
                  for link in links if isinstance(link, dict) and link.get("href")],
        "attachment_names": attachment_names,
        "attachment_extensions": attachment_extensions,
        "auth_results": auth_results,
        "auth_recorded_by": str(recorded.get("recorded_by") or "") or None,
        "source_type": "email",
        "link_urls": hrefs,
    }


def _extract_evidence_from_text(sender: str, text: str) -> dict:
    """Extract structured evidence from a background text/SMS message."""
    from urllib.parse import urlparse
    import re as _re

    link_domains = []
    urls = _re.findall(r"(?i)\bhttps?://[^\s<>\]\[\"']+", text)
    for url in urls:
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if host:
                link_domains.append(host)
        except Exception:
            pass

    # For SMS, sender is often a phone number or short code
    sender_domain = ""
    if "@" in sender:
        from services.mailbox_monitor import _extract_domain_from_email
        sender_domain = _extract_domain_from_email(sender) or ""

    return {
        "sender": sender,
        "sender_domain": sender_domain,
        "subject": "",  # SMS has no subject
        "reply_to_domain": "",
        "link_domains": link_domains,
        "attachment_names": [],
        "attachment_extensions": [],
        "auth_results": {},
        "body": text,                # the whole message: every rule reads all of it
        "source_type": "text",
        "link_urls": urls,           # Full URLs for redirect expansion
        "sender_phone": sender if not "@" in sender else "",
    }


# ── Provider Evidence Gathering ─────────────────────────────────────────────
# Runs specialist providers ONCE. Results flow through Tier 0 → Tier 1 → Tier 2
# without re-querying. Provider failure is NEVER interpreted as SAFE.

async def gather_provider_evidence(evidence: dict) -> dict:
    """Run all applicable specialist providers and return structured results.

    Called ONCE before triage_item. Results are reused across all tiers and
    forwarded to the investigation (TC Hawkeye, then Magnum DI if needed) if escalation occurs.

    Each provider entry includes:
      - status: "ok" | "unavailable" | "not_configured" | "not_applicable"
      - queried_at: ISO timestamp
      - data_class: "shareable_threat_intel" | "device_private"
      - data fields specific to the provider

    Provider failure → status="unavailable". Never treated as evidence of safety.

    Data classification:
      shareable_threat_intel: Non-user-specific reputation/threat data that may
        be reused across devices (e.g. domain reputation, URL safety, breach lists).
        Never contains user content, messages, screenshots, or private investigation context.
      device_private: Results that incorporate or reference user-specific content,
        device identity, or private investigation state. Never shared cross-device.
    """
    import asyncio
    pe: dict = {}
    providers_used: list[str] = []
    ts = now_utc().isoformat()

    link_domains = evidence.get("link_domains", [])
    link_urls = evidence.get("link_urls", [])
    # Finding F: normalise URLs before provider lookups — strip tracking params
    # (UTM, fbclid, gclid …), unify scheme capitalisation, strip default ports.
    # Two URLs differing only in tracking params are now treated as one indicator.
    if link_urls:
        from services.url_normalise import normalise_urls
        link_urls = normalise_urls(link_urls)
    sender_phone = evidence.get("sender_phone", "")
    source_type = evidence.get("source_type", "unknown")

    # ── 1. RDAP: domain registration intelligence ──
    if link_domains:
        rdap_results = {}
        unique_domains = list(set(d for d in link_domains if d and "." in d))[:10]
        for domain in unique_domains:
            try:
                from services.rdap import lookup_domain_cached
                domain_info = await asyncio.wait_for(lookup_domain_cached(domain), timeout=6.0)
                if domain_info:
                    rdap_results[domain] = {
                        "registrar": domain_info.registrar or "unknown",
                        "registration_date": domain_info.registration_date.isoformat() if domain_info.registration_date else "unknown",
                        "newly_registered": bool(domain_info.newly_registered),
                        "country": domain_info.country or "unknown",
                        "status": "ok",
                        "queried_at": ts,
                        "data_class": "shareable_threat_intel",
                    }
                    providers_used.append("rdap")
                else:
                    rdap_results[domain] = {"status": "unavailable", "detail": "No RDAP data returned", "queried_at": ts}
            except Exception as exc:
                rdap_results[domain] = {"status": "unavailable", "detail": type(exc).__name__, "queried_at": ts}
                _log.debug("rdap_lookup_failed domain=%s error=%s", domain, type(exc).__name__)
        if rdap_results:
            pe["rdap"] = {"domains": rdap_results}

    # ── 2. Redirect expansion + Safe Browsing on final destinations ──
    if link_urls:
        redirect_results = {}
        sb_results = {}
        unique_urls = list(dict.fromkeys(link_urls))[:10]  # preserve order, dedup
        for url in unique_urls:
            try:
                from services.intel import expand_redirects_detailed, run_intel_check
                chain, expansion_complete, expansion_reason, expansion_failure = await asyncio.wait_for(expand_redirects_detailed(url), timeout=12)
                if len(chain) > 1:
                    redirect_results[url] = {
                        "chain": chain,
                        # Only call it the final URL when the chain was actually followed to the end.
                        "final_url": chain[-1] if expansion_complete else None,
                        "last_seen_url": chain[-1],
                        "hops": len(chain) - 1,
                        "status": "ok" if expansion_complete else "incomplete",
                        **({} if expansion_complete else {"detail": expansion_reason, "failure": expansion_failure}),
                        "queried_at": ts,
                    }
                    providers_used.append("redirect_expansion")
                    # Check final destination against Safe Browsing
                    try:
                        final_result = await asyncio.wait_for(
                            run_intel_check("url", chain[-1]), timeout=6.0
                        )
                        sb_results[chain[-1]] = {
                            "verdict": final_result.verdict,
                            "threat_types": list(final_result.threat_types),
                            "coverage": final_result.coverage,
                            "status": "ok",
                            # Sources that didn't answer — recorded as incomplete checks, never as completed ones.
                            "sources": [s.model_dump() for s in final_result.sources],
                            "queried_at": ts,
                            "via_redirect_from": url,
                        }
                        providers_used.append("safe_browsing")
                    except Exception as sb_exc:  # noqa: BLE001
                        # An unchecked destination is recorded as unchecked, never left blank.
                        sb_results[chain[-1]] = {"status": "unavailable", "detail": type(sb_exc).__name__,
                                                 "failure": "timeout" if isinstance(sb_exc, asyncio.TimeoutError) else "provider_unavailable",
                                                 "queried_at": ts, "via_redirect_from": url}
                else:
                    redirect_results[url] = {
                        "chain": chain,
                        "final_url": url if expansion_complete else None,
                        "last_seen_url": url,
                        "hops": 0,
                        "status": "ok" if expansion_complete else "incomplete",
                        **({} if expansion_complete else {"detail": expansion_reason, "failure": expansion_failure}),
                        "queried_at": ts,
                    }
            except Exception as exc:
                redirect_results[url] = {"status": "unavailable", "detail": type(exc).__name__,
                                         "failure": "timeout" if isinstance(exc, asyncio.TimeoutError) else "redirect_failure", "queried_at": ts}
                _log.debug("redirect_expansion_failed url=%s error=%s", url[:60], type(exc).__name__)
        if redirect_results:
            pe["redirects"] = {"urls": redirect_results}
        if sb_results:
            pe.setdefault("safe_browsing", {})["urls"] = {**pe.get("safe_browsing", {}).get("urls", {}), **sb_results}

    # ── 3. IPQS: phone number fraud scoring (SMS/text only) ──
    if sender_phone:
        try:
            from services.phonerisk import check_phone_risk
            risk = await asyncio.wait_for(check_phone_risk(sender_phone, None), timeout=8.0)
            if risk.decision != "unknown":
                pe["ipqs"] = {"phones": {sender_phone: {
                    "fraud_score": risk.fraud_score,
                    "recent_abuse": bool(risk.recent_abuse),
                    "voip": bool(risk.voip),
                    "carrier": risk.carrier or "unknown",
                    "line_type": risk.line_type or "unknown",
                    "country": risk.country or "unknown",
                    "decision": risk.decision,
                    "status": "ok",
                    # "stale" = the live lookup failed and this is the last known score (failure says why).
                    "freshness": risk.freshness, "failure": risk.failure,
                    "checked_at": risk.checked_at.isoformat(),
                    "queried_at": ts,
                }}}
                providers_used.append("ipqs")
            else:
                pe["ipqs"] = {"phones": {sender_phone: {"status": "not_configured" if risk.source == "not_configured" else "unavailable",
                                                        "failure": risk.failure, "queried_at": ts}}}
        except Exception as exc:
            pe["ipqs"] = {"phones": {sender_phone: {"status": "unavailable", "detail": type(exc).__name__,
                                                    "failure": "timeout" if isinstance(exc, asyncio.TimeoutError) else getattr(exc, "failure", "provider_unavailable"),
                                                    "queried_at": ts}}}
            _log.debug("ipqs_lookup_failed phone=%s error=%s", sender_phone[:6], type(exc).__name__)

    # ── 3b. IPQS URL reputation scoring ──
    if link_urls:
        try:
            from services.urlrisk import check_url_risk
            from core.config import IPQS_API_KEY
            if IPQS_API_KEY:
                ipqs_url_results = {}
                # Check up to 5 unique URLs (most suspicious first — shorteners get priority)
                from services.urlrisk import is_shortener
                sorted_urls = sorted(dict.fromkeys(link_urls), key=lambda u: (0 if is_shortener(u) else 1))[:5]
                for url in sorted_urls:
                    try:
                        url_result = await asyncio.wait_for(check_url_risk(url), timeout=10.0)
                        if url_result:
                            # "error" (e.g. insufficient provider credits) is still a failure to surface —
                            # never silently dropped — but only a clean "ok" answer counts as a used provider.
                            ipqs_url_results[url] = url_result
                            if url_result.get("status") == "ok":
                                providers_used.append("ipqs_url")
                    except Exception as url_exc:
                        ipqs_url_results[url] = {"status": "unavailable", "detail": type(url_exc).__name__, "queried_at": ts}
                        _log.debug("ipqs_url_check_failed url=%s error=%s", url[:60], type(url_exc).__name__)
                if ipqs_url_results:
                    pe.setdefault("ipqs", {})["urls"] = ipqs_url_results
        except Exception as exc:
            _log.debug("ipqs_url_section_failed error=%s", type(exc).__name__)

    # ── 3c. Download-link detection (static, no network call) ──
    if link_urls:
        try:
            from services.urlrisk import detect_download_links
            download_links = detect_download_links(link_urls)
            if download_links:
                pe["download_links"] = {"items": download_links, "count": len(download_links), "queried_at": ts}
                providers_used.append("download_link_detection")
        except Exception as exc:
            _log.debug("download_link_detection_failed error=%s", type(exc).__name__)

    # ── 3d. VirusTotal URL reputation ──────────────────────────────────────────
    if link_urls:
        try:
            from services.virustotal_url import check_url as _vt_check_url, VT_API_KEY as _VT_KEY
            if _VT_KEY:
                vt_url_results: dict = {}
                # Cap at 5 URLs; prefer IPQS-flagged or shortener URLs first (already sorted above).
                for _url in list(dict.fromkeys(link_urls))[:5]:
                    try:
                        _vt_res = await asyncio.wait_for(_vt_check_url(_url), timeout=12.0)
                        vt_url_results[_url] = {
                            "verdict": _vt_res.verdict,
                            "detection_count": _vt_res.detection_count,
                            "total_engines": _vt_res.total_engines,
                            "categories": _vt_res.categories,
                            "community_score": _vt_res.community_score,
                            "detail": _vt_res.detail,
                            "status": "ok" if _vt_res.verdict != "error" else "unavailable",
                            "queried_at": ts,
                            "data_class": "shareable_threat_intel",
                        }
                        if _vt_res.verdict not in ("error", "not_configured"):
                            providers_used.append("virustotal_url")
                    except Exception as _url_exc:
                        vt_url_results[_url] = {
                            "status": "unavailable", "detail": type(_url_exc).__name__, "queried_at": ts
                        }
                        _log.debug("virustotal_url_check_failed url=%s error=%s", _url[:60], type(_url_exc).__name__)
                if vt_url_results:
                    pe["virustotal"] = {"urls": vt_url_results}
        except Exception as exc:
            _log.debug("virustotal_url_section_failed error=%s", type(exc).__name__)

    # ── 4. Scam intel feed cross-reference ──
    try:
        scam_matches = await _match_scam_intel(evidence)
        if scam_matches:
            pe["scam_intel"] = {"matches": scam_matches}
            providers_used.append("scam_intel")
    except Exception as exc:
        _log.debug("scam_intel_match_failed error=%s", type(exc).__name__)

    # Deduplicate providers_used
    pe["_summary"] = {
        "providers_consulted": sorted(set(providers_used)),
        "total_lookups": len(providers_used),
        "gathered_at": ts,
    }

    # ── Data classification sweep ──
    # Tag all provider results with their privacy classification.
    # Providers that return public threat intelligence about indicators
    # (domains, URLs, phone reputation, breach lists) are shareable.
    # Results that incorporate user content are device_private.
    _SHAREABLE_SECTIONS = {"rdap", "safe_browsing", "redirects", "ipqs", "scam_intel", "download_links", "virustotal"}
    for section_name, section in pe.items():
        if section_name.startswith("_") or not isinstance(section, dict):
            continue
        if section_name in _SHAREABLE_SECTIONS:
            for collection in section.values():
                if isinstance(collection, dict):
                    for key, item in collection.items():
                        if isinstance(item, dict) and "data_class" not in item:
                            item["data_class"] = "shareable_threat_intel"
                elif isinstance(collection, list):
                    for item in collection:
                        if isinstance(item, dict) and "data_class" not in item:
                            item["data_class"] = "shareable_threat_intel"
        else:
            # Unknown/future sections default to device_private
            for collection in section.values():
                if isinstance(collection, dict):
                    for key, item in collection.items():
                        if isinstance(item, dict) and "data_class" not in item:
                            item["data_class"] = "device_private"

    return pe


async def _match_scam_intel(evidence: dict) -> list[dict]:
    """Cross-reference incoming evidence against the scam intel learning feed.

    Matches on: sender domain patterns, link domain patterns, subject keywords
    from active advisories classified in the scam_intel feed.

    Returns compact match summaries, not full advisory bodies.
    """
    matches = []
    sender_domain = evidence.get("sender_domain", "")
    link_domains = set(evidence.get("link_domains", []))
    subject = evidence.get("subject", "").lower()
    text_preview = str(evidence.get("body") or evidence.get("text_preview") or "").lower()

    # Query recent active advisories from scam analysis results
    try:
        recent_advisories = await db.scam_analysis_results.find(
            {"is_relevant_to_australia": True},
            {"_id": 0, "feed_item_id": 1, "title": 1, "severity": 1, "tier": 1,
             "facts": 1, "scam_types": 1, "indicators": 1}
        ).sort("analysed_at", -1).limit(50).to_list(50)
    except Exception:
        return []

    for adv in recent_advisories:
        title = (adv.get("title") or "").lower()
        indicators = adv.get("indicators", {}) if isinstance(adv.get("indicators"), dict) else {}
        scam_types = adv.get("scam_types", []) if isinstance(adv.get("scam_types"), list) else []

        # Check domain indicators
        adv_domains = indicators.get("domains", []) if isinstance(indicators.get("domains"), list) else []
        matched_domain = None
        for d in adv_domains:
            d_lower = d.lower()
            if d_lower == sender_domain or d_lower in link_domains:
                matched_domain = d
                break

        # Check keyword patterns in subject/text
        keywords = indicators.get("keywords", []) if isinstance(indicators.get("keywords"), list) else []
        matched_keyword = None
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in subject or kw_lower in text_preview:
                matched_keyword = kw
                break

        if matched_domain or matched_keyword:
            matches.append({
                "advisory_id": adv.get("feed_item_id", "unknown"),
                "title": adv.get("title", "Unknown advisory"),
                "severity": adv.get("severity", "unknown"),
                "scam_types": scam_types[:3],
                "matched_on": f"domain: {matched_domain}" if matched_domain else f"keyword: {matched_keyword}",
            })

    return matches[:5]  # Cap at 5 most relevant matches


def _link_evidence_from_providers(evidence: dict, provider_evidence: dict) -> dict:
    """Normalise specialist provider output into the shared link-evidence shape. Every check that didn't complete
    (a source that didn't answer, a final destination that couldn't be verified) goes into `incomplete_checks`."""
    sb = provider_evidence.get("safe_browsing", {}).get("urls", {})
    redirects = provider_evidence.get("redirects", {}).get("urls", {})
    rdap = provider_evidence.get("rdap", {}).get("domains", {})

    malicious = [url for url, info in sb.items() if info.get("verdict") == "malicious"]
    # An answer in which no source could check anything (coverage "none") is unavailable, never clean.
    unavailable = [url for url, info in sb.items() if info.get("status") in ("unavailable", "not_configured", "error")
                   or info.get("coverage") == "none"]
    reputation: dict = {}
    if malicious:
        reputation = {"status": "ok", "verdict": "malicious", "source": listed_by(sb[malicious[0]].get("sources")),
                      "threat_types": sb[malicious[0]].get("threat_types", [])}
    elif unavailable:
        info = sb[unavailable[0]]
        failure = info.get("failure") or next((s.get("failure") for s in info.get("sources") or [] if s.get("failure")), None)
        reputation = {"status": "unavailable", "verdict": "unknown", **({"failure": failure} if failure else {})}
    elif sb:
        reputation = {"status": "ok", "verdict": "clean"}

    incomplete: list[dict] = []
    for info in sb.values():
        if info.get("status") == "ok" and info.get("coverage") != "none":
            incomplete += from_sources(info.get("sources") or [])
    for url, info in redirects.items():
        if info.get("status") in ("incomplete", "unavailable"):
            incomplete.append(incomplete_check("final_destination", info.get("failure") or "redirect_failure", status="unresolved",
                                               detail=info.get("detail") or "", source="redirect_expansion"))

    redirect: dict = {}
    for url, info in redirects.items():
        hops = info.get("hops", 0) or 0
        if hops:
            final = info.get("final_url") or ""
            redirect = {"status": info.get("status", "ok"), "hops": hops, "final_url": final,
                        "detail": info.get("detail"), "failure": info.get("failure"),
                        "final_verdict": sb.get(final, {}).get("verdict", "unknown") if final else "unknown"}
            break

    domain_age: dict = {}
    for domain, info in rdap.items():
        if info.get("status") == "ok":
            domain_age = {"status": "ok", "newly_registered": bool(info.get("newly_registered")), "domain": domain}
            if info.get("newly_registered"):
                break
        elif info.get("status") in ("unavailable", "error", "not_configured") and not domain_age:
            domain_age = {"status": "unavailable"}

    return {"reputation": reputation, "redirect": redirect, "domain_age": domain_age, "incomplete_checks": incomplete}


_PAYMENT_WORDS = ("payid", "osko", "pay id", "transfer now", "immediate payment", "instant transfer")
_FORWARD_CODES = ("*21", "*67", "**21", "*72", "21#", "##21", "*#21")

# What the source asks or claims, read from its own sentences (services/triage/requests.py reads secrets and sign-ins).
_THREAT_RE = re.compile(r"\b(?:suspend(?:ed)?|locked|limited|restricted|disabled|deactivat(?:ed|ion)|terminated|legal action|penalt(?:y|ies)|"
                        r"arrest|warrant|unusual activity|unauthori[sz]ed (?:access|activity|sign-?in))\b", re.I)
_STRICT_URGENCY = re.compile(r"\bimmediately\b|\burgent(?:ly)?\b|\bwithin \d{1,2} (?:minutes?|hours?|days?)\b|\bfinal (?:notice|warning)\b|\bact now\b"
                             r"|\blast chance\b|\b(?:will|may) be (?:suspended|closed|locked|deleted|terminated|disabled)\b|\bexpires? (?:today|tonight|in)\b", re.I)
_CTA = re.compile(r"\b(?:sign ?in|log ?in|login|verify|confirm|update|unlock|restore|reactivate|secure|reset|pay|view|review|check|access|claim|download)\b", re.I)
_BANK_CHANGE = re.compile(r"\b(?:new|updated|changed|different)\b[^.!?]{0,60}\b(?:bank|account|bsb|payment) (?:details|account|information)\b"
                          r"|\b(?:bank|account|payment) details (?:have|has) (?:changed|been updated)\b", re.I)
_INVOICE = re.compile(r"\b(?:invoice|remittance|payment|bill|pay)\b", re.I)
_PAY_ASK = re.compile(r"\b(?:pay|make (?:a|the) payment|settle|transfer)\b[^.!?]{0,30}\b(?:the|your|this|now|today|\$|aud|invoice|amount|balance|fee|funds)\b", re.I)
_EXEC = re.compile(r"\b(?:ceo|chief executive|managing director|chief financial officer|cfo|company director)\b", re.I)
_WIRE = re.compile(r"\b(?:urgent (?:transfer|payment|wire)|wire transfer|bank transfer|gift cards?|transfer the funds|process a payment)\b", re.I)
_IDENTITY_ASK = re.compile(r"\b(?:send|provide|confirm|verify|reply with|enter|upload|submit|give|tell)\b[^.!?]{0,40}\b(?:date of birth|medicare (?:number|card)|"
                           r"passport|driver'?s? licen[cs]e|tax file number|tfn)\b", re.I)
_HOSTISH = re.compile(r"^(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)(?:[/?#]\S*)?$", re.I)


def _asked(pattern: re.Pattern, text: str) -> Optional[str]:
    """The first clause that asks this of the reader (a negated one — "never pay …" — doesn't)."""
    from services.triage import requests as rq
    for clause in rq._clauses(text):
        m, negated = rq.ask_in(pattern, clause)
        if m and not negated:
            return clause
    return None


def _host(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower()
    except ValueError:
        return ""


def _email_reading(evidence: dict, provider_evidence: dict, raw_text: str) -> dict:
    """Who the email presents itself as, what it links to and where those links really go — before impersonation is
    judged. A brand that is only mentioned is not the sender; different sender and link domains alone prove nothing."""
    from services.email_infrastructure import is_tracking
    from services.higgins import brand_domains
    from services.triage import speaker
    sender_domain = (evidence.get("sender_domain") or "").lower()
    who = speaker.claimed(str(evidence.get("sender") or ""), raw_text)
    brand = who["name"] if who and who["known"] else None
    sender_kind = brand_domains.classify(brand, sender_domain)[0] if brand and sender_domain else None
    finals = {url: _host(str((info or {}).get("final_url") or ""))
              for url, info in (((provider_evidence or {}).get("redirects") or {}).get("urls") or {}).items()}
    destinations, displayed = [], None
    for link in evidence.get("links") or []:
        href, shown = str(link.get("href") or ""), str(link.get("text") or "").strip()
        host = _host(href)
        if is_tracking(host):
            host = finals.get(href) or ""          # a sending service's click tracking: judged by where it really goes, if known
        if not host or is_tracking(host):
            continue
        written = _HOSTISH.match(shown)
        if written and not displayed and not brand_domains.same_organisation(written.group(1).lower(), host):
            displayed = {"shown": written.group(1).lower(), "actual": host}
        destinations.append({"host": host, "text": shown[:80], "action": bool(_CTA.search(shown)),
                             "kind": brand_domains.classify(brand, host)[0] if brand else None})
    actions = [d for d in destinations if d["action"]] or destinations
    return {"who": who, "brand": brand, "sender_kind": sender_kind,
            "sender_mismatch": sender_kind not in (None, "official", "country_site"),
            "destinations": destinations, "actions": actions, "displayed": displayed,
            "destination_mismatch": bool(brand) and any(d["kind"] in ("lookalike", "shared_service", "unrelated") for d in actions),
            "deceptive_destination": bool(brand) and any(d["kind"] in ("lookalike", "shared_service") for d in actions)}

# Callback-scam signals — mirror of frontend src/domain/messageAnalysis.ts (CALLBACK_RE, CHARGE_*).
_CALLBACK_RE = re.compile(r"(?:\+?61[\s().-]*|\b0)(?:1800|1300|[2-478])(?:[\s().-]*\d){6,8}|\b1[38]00(?:[\s.-]*\d){6}\b|\b13[\s-]?\d{2}[\s-]?\d{2}\b")
_CALLBACK_WORDS = re.compile(r"\b(?:call|contact|phone|ring|fraud response|support line|helpline)\b")
_CHARGE_STRONG = re.compile(r"\bunauthori[sz]ed charge\b|\bunrecogni[sz]ed (?:charge|transaction)\b|\bsuspicious transaction\b|\bmerchant\s*:|\bamount\s*:|\bfunds (?:are|will be) released\b")
_CHARGE_CLAIM = re.compile(r"\b(?:been|was|were|being) (?:charged|debited|billed)\b|\b(?:charge|payment|transaction|purchase|debit|withdrawal|order) of (?:aud\s?)?\$\s?\d")
_CHARGE_DISPUTE = re.compile(r"\bif (?:you|this) (?:did ?n[o']?t|was ?n[o']?t)\b|\bnot you\b|\bdid ?n[o']?t (?:make|authori[sz]e|recogni[sz]e)\b|\bto (?:cancel|dispute|stop|reverse) (?:this|the) (?:charge|payment|transaction|order|purchase)\b")
_URGENCY = re.compile(r"\bimmediately\b|\burgent(?:ly)?\b|\bright now\b|\bwithin \d{1,2} (?:minutes?|hours?|days?)\b|\btoday\b|\bexpires?\b|\bfinal notice\b|\blast chance\b|\bact now\b|\bnow\b")


def callback_request(blob: str) -> bool:
    """A supplied callback number with call/contact wording. Lower-case text."""
    return bool(_CALLBACK_RE.search(blob)) and bool(_CALLBACK_WORDS.search(blob))


def alleged_charge(blob: str) -> bool:
    """An unexpected charge/payment claim: the explicit forms, or a charge claim with dispute or urgency wording."""
    return bool(_CHARGE_STRONG.search(blob)) or (bool(_CHARGE_CLAIM.search(blob))
                                                  and bool(_CHARGE_DISPUTE.search(blob) or _URGENCY.search(blob)))


# Mirror of frontend src/domain/messageAnalysis.ts (DISGUISE, INVISIBLE, OTHER_SCRIPT, organisationNamed, REPLY_RE, …).
# Look-alike characters: typographic ligatures (ﬁ ﬂ ﬀ), full-width and mathematical letters/digits, Greek or Cyrillic
# letters inside a word written in English letters, and invisible joiners inside a word.
_DISGUISE = re.compile("[\ufb00-\ufb06\uff10-\uff19\uff21-\uff3a\uff41-\uff5a\U0001d400-\U0001d7ff]")
_INVISIBLE = re.compile("[\u200b-\u200d\u2060\ufeff]")
_OTHER_SCRIPT = re.compile("[\u0370-\u03ff\u0400-\u04ff]")
_WORD_SPLIT = re.compile(r"[\s.,;:!?()\"“”‘’']+")
_ORG_WORD = re.compile(r"\b(?:energy|solar|power|electric(?:al|ity)?|gas|bank|banking|group|australian?|pty|ltd|limited|services?|insurance|telco|"
                       r"telecom|mobile|finance|financial|super|health|support|team|company|corp(?:oration)?|inc|homes?|realty|motors|logistics|"
                       r"express|post|retail|solutions|renewables?|batter(?:y|ies)|installations?|installers?|utilities|water)\b", re.I)
_NAME_END = re.compile(r"[.,;:!?)]+$")
_INTRO = re.compile(r"\b(?:it'?s|it’s|this is|we are|we'?re|we’re)\s+", re.I)
_CALLING_FROM = re.compile(r"\bcalling (?:you )?from\s+", re.I)
_REPLY = re.compile(r"\breply\s+(?:with\s+)?[\"“']?(?:yes|y|ok(?:ay)?|confirm|interested|[1-9])\b[\"”']?|\breply (?:to (?:confirm|book|claim|secure))\b"
                    r"|\btext (?:back|us back|yes)\b|\brespond (?:with )?yes\b", re.I)
_OFFER = r"(?:rebates?|prices?|offers?|discounts?|savings?|subsid(?:y|ies)|incentives?|stcs?|deals?|spots?|places?)"
_PRESSURE = re.compile("|".join((
    rf"\bbefore (?:the )?(?:\w+\s+){{0,2}}{_OFFER}\s+(?:drops?|dropping|ends?|expires?|changes?|go(?:es)?|closes?|runs? out|disappears?|reduces?|falls?)\b"
    r"(?:\s+(?:next|this) (?:week|month|year))?",
    rf"\b{_OFFER}\s+(?:are|is)\s+(?:dropping|ending|expiring|closing|running out|going up|changing|reducing|disappearing)\b",
    r"\bbefore (?:the )?(?:year[- ]end|end of (?:the )?(?:year|month|week|financial year)|eofy)\b",
    r"\b(?:limited time|limited (?:spots|places)|while (?:stocks?|spots?|places?) last|ends? soon|only \d+ (?:spots|places) left)\b",
)), re.I)
_REBATE = re.compile(r"\b(?:government|govt|federal|state)(?:[- ](?:funded|backed))?\s+(?:[\w-]+\s+){0,3}?(?:rebates?|grants?|subsid(?:y|ies)|incentives?|stcs?|"
                     r"schemes?|programs?|programmes?|bonus(?:es)?)\b|\bsmall[- ]scale technology certificates?\b|\b(?:solar|battery|batteries|energy|"
                     r"electricity|heat pump|hot water)\s+(?:[\w-]+\s+){0,2}?(?:rebates?|subsid(?:y|ies)|grants?|incentives?)\b|\bcheaper home batteries\b", re.I)
_STC = re.compile(r"\bstcs?\b(?:\s+(?:savings?|rebates?|discounts?))?", re.I)
_ENERGY_CONTEXT = re.compile(r"\brebates?\b|\bsolar\b|\bbatter(?:y|ies)\b|\bsavings?\b|\binstall(?:ation)?\b", re.I)


def disguised_words(text: str) -> list[str]:
    """Each word that contains a look-alike character."""
    out = []
    for word in _WORD_SPLIT.split(text):
        latin = bool(re.search(r"[A-Za-z]", word))
        if word and any(_DISGUISE.match(ch) or (latin and (_INVISIBLE.match(ch) or _OTHER_SCRIPT.match(ch))) for ch in word):
            out.append(word)
    return out


def _capitalised_run(rest: str) -> tuple[str, Optional[str]]:
    """The run of capitalised words at the start of `rest` (at most four), stopping at punctuation; and the next word."""
    name: list[str] = []
    for token in rest.strip().split():
        word = _NAME_END.sub("", token)
        if not word or not word[0].isupper() or len(name) == 4:
            return " ".join(name), word.lower() or None
        name.append(word)
        if word != token:
            return " ".join(name), None
    return " ".join(name), None


def organisation_named(text: str) -> Optional[str]:
    """The organisation a message introduces itself as ("It's UNIﬁed Energy here", "This is Sam from Bright Solar",
    "calling from AGL Energy"). Only a name with an organisation word counts — never a person's name."""
    import unicodedata
    is_org = lambda name: bool(name) and bool(_ORG_WORD.search(unicodedata.normalize("NFKC", name)))  # noqa: E731
    for m in _INTRO.finditer(text):
        rest = text[m.end():]
        name, following = _capitalised_run(rest)
        if following in ("here", "calling", "team", "again", "with") and is_org(name):
            return name
        frm = re.match(r"\S+\s+from\s+", rest, re.I)
        if frm and is_org(org := _capitalised_run(rest[frm.end():])[0]):
            return org
    for m in _CALLING_FROM.finditer(text):
        if is_org(org := _capitalised_run(text[m.end():])[0]):
            return org
    return None


def lookalike_name(text: str) -> bool:
    """The organisation the message introduces itself as is written with a look-alike character."""
    org = organisation_named(text)
    return bool(org) and any(word in org for word in disguised_words(text))


def rebate_claim(text: str) -> bool:
    """A claimed government rebate: an explicit one, or STCs offered as savings or rebates."""
    return bool(_REBATE.search(text)) or (bool(_ENERGY_CONTEXT.search(text)) and bool(_STC.search(text)))


def _attachment_triage(names: list[str]) -> dict:
    """Each attachment judged by the File Gate rules (by its name: the server never receives the file here)."""
    from services.triage import evaluate
    rules_met: list[str] = []
    for name in names:
        if "." in name and ("." + name.rsplit(".", 1)[-1].lower()) in _RISKY_ATTACHMENT_EXT:
            result = evaluate({"source_type": "file", "filename": name, "provenance": "email", "expected": False})
            rules_met += [r.rule_id for r in result.met_rules if r.rule_id not in rules_met]
    return {"outcome": Outcome.POSSIBLE_THREAT.value if rules_met else (Outcome.NO_THREAT.value if names else None), "rules_met": rules_met}


def _rule_evidence(evidence: dict, findings: list[str], provider_evidence: dict,
                   correlation: Optional[dict] = None) -> dict:
    """Build the shared Triage evidence dict from server-side intake evidence.

    Every rule reads the source itself — its subject, body, sender, Reply-To, authentication results and links.
    `findings` are Apollo's own observations: kept on the record beside the source, never read as evidence of it."""
    from services.higgins.brand_domains import same_organisation
    from services.triage import requests as rq
    source_type = evidence.get("source_type", "unknown")
    raw_text = str(evidence.get("body") or evidence.get("text_preview") or "")
    subject_raw = str(evidence.get("subject") or "")
    text = raw_text.lower()
    subject = subject_raw.lower()
    blob = f"{subject} {text}"
    asks = rq.read(f"{subject_raw}\n{raw_text}")

    providers = _link_evidence_from_providers(evidence, provider_evidence)
    sender_domain = (evidence.get("sender_domain") or "").lower()
    link_domains = [str(d).lower() for d in (evidence.get("link_domains") or [])]
    link_threat = providers["reputation"].get("verdict") == "malicious"
    threat, urgent = bool(_THREAT_RE.search(blob)), bool(_STRICT_URGENCY.search(blob))
    email = _email_reading(evidence, provider_evidence, raw_text) if source_type == "email" else {}
    auth = evidence.get("auth_results") or {}
    auth_failed = [m for m in ("spf", "dkim", "dmarc") if auth.get(m) in ("fail", "softfail", "permerror")]
    reply_domain = (evidence.get("reply_to_domain") or "").lower()
    reply_mismatch = ((bool(reply_domain) and bool(sender_domain) and not same_organisation(reply_domain, sender_domain))
                      if (auth or reply_domain) else None)
    # A sign-in, verification or payment-update request is ordinary on its own: it counts only with supporting context.
    support = [name for name, flag in (("the sender isn't the organisation it presents itself as", email.get("sender_mismatch")),
                                       ("the link it asks you to use goes elsewhere", email.get("destination_mismatch")),
                                       ("a link shows one address but goes to another", email.get("displayed")),
                                       ("the receiving server's authentication failed", auth_failed),
                                       ("replies go to a different organisation", reply_mismatch),
                                       ("it threatens the account with a deadline", threat and urgent),
                                       ("a link is on a threat list", link_threat)) if flag]
    sign_in_flagged = bool((asks["sign_in_request"] or asks["payment_detail_update"]) and support)
    credential_request = bool(asks["secret_request"] or asks["card_request"] or sign_in_flagged)
    code_request = bool(asks["code_request"])
    identity = _asked(_IDENTITY_ASK, raw_text)
    payment_change = bool(_BANK_CHANGE.search(raw_text) and _INVOICE.search(blob))
    pay_ask = _asked(_PAY_ASK, raw_text)
    attachment = _attachment_triage([str(name) for name in (evidence.get("attachment_names") or [])])

    shared: dict = {
        "source_type": source_type,
        "sender_domain": sender_domain,
        "link_domains": link_domains,
        # Apollo's observations about the source, kept apart from it: no rule reads them as evidence.
        "observations": findings,
        "auth_results": auth,
        "reply_to_mismatch": reply_mismatch,
        "sender_domain_mismatch": bool(email.get("sender_mismatch")),
        "claimed_brand": email.get("brand") or evidence.get("claimed_brand"),
        "claimed_sender": email.get("who"),
        "brand_mismatch": bool(email.get("sender_mismatch") or email.get("destination_mismatch")),
        "destination_mismatch": bool(email.get("destination_mismatch")),
        "deceptive_destination": bool(email.get("deceptive_destination")),
        "action_destinations": email.get("actions") or [],
        **({"displayed_host": email["displayed"]["shown"], "actual_host": email["displayed"]["actual"]} if email.get("displayed") else {}),
        "security_alert": bool(asks["security_notice"] or threat),
        "requests": asks,
        "request_support": support,
        "credential_request": credential_request,
        "credential_interaction": credential_request,
        "code_request": code_request,
        "identity_request": bool(identity),
        "banking_request": bool(asks["card_request"]),
        "payment_change": payment_change,
        "executive_request": bool(_EXEC.search(blob) and _WIRE.search(blob)),
        "consequential_action": bool(credential_request or code_request or identity or payment_change or pay_ask),
        # ROUTE rules (EMAIL-09, EMAIL-10, MSG-12): each part is judged by its own gate, and the threat-producing rules
        # met there are the ones the case cites. A malicious listing is LINK-01; an attachment is judged by the File Gate.
        "attachment_outcome": attachment["outcome"],
        "attachment_rules_met": attachment["rules_met"],
        "link_outcome": Outcome.POSSIBLE_THREAT.value if providers["reputation"].get("verdict") == "malicious" else None,
        "link_rules_met": ["LINK-01"] if providers["reputation"].get("verdict") == "malicious" else [],
        "correlation": correlation or {},
        **providers,
    }

    if source_type in ("text", "sms", "message"):
        shared["signals"] = {
            "code_request": code_request,
            # A password, PIN or login-detail request; an ordinary sign-in request only with a threat, a deadline, a
            # listed link or a disguised organisation name behind it.
            "login_request": bool(asks["secret_request"] or ((asks["sign_in_request"] or asks["payment_detail_update"])
                                                             and (threat or urgent or link_threat or lookalike_name(raw_text)))),
            "identity_request": bool(identity or asks["card_request"]),
            "safe_account": any(word in blob for word in ("safe account", "secure account", "protected account")),
            "gift_cards": "gift card" in blob or "itunes" in blob or "voucher code" in blob,
            "remote_access": any(word in blob for word in ("anydesk", "teamviewer", "remote access", "remote support")),
            "install_request": any(word in blob for word in ("install this", "download this app", "install our app")),
            "extortion": any(word in blob for word in ("hacked", "recorded you", "webcam", "expose")),
            "advance_fee": "release fee" in blob or "processing fee" in blob or "clearance fee" in blob,
            "fake_payment": any(word in blob for word in ("payment has been sent", "you've been paid", "already paid")),
            "family_claim": any(word in blob for word in ("hi mum", "hi mom", "hi dad", "it's me")),
            "new_number": any(word in blob for word in ("new number", "new phone", "lost my phone", "broke my phone")),
            "money_request": any(word in blob for word in ("send money", "transfer", "lend me", "pay the bill")),
            "payment_request": any(word in blob for word in ("pay", "payment", "invoice", "fee", "overdue")),
            "guaranteed_returns": "guaranteed" in blob or "risk-free" in blob or "passive income" in blob,
            "job_offer": "job" in blob or "hiring" in blob or "recruiter" in blob,
            "romance_escalation": any(word in blob for word in ("my love", "darling", "sweetheart")) and "money" in blob,
            "platform_switch": any(word in blob for word in ("telegram", "whatsapp", "signal", "wechat")),
            "urgency": any(word in blob for word in ("urgent", "immediately", "final notice", "expires", "act now")) or bool(_PRESSURE.search(raw_text)),
            "threat": any(word in blob for word in ("suspended", "locked", "penalty", "fine", "legal action", "arrest")),
            "unknown_sender": not sender_domain,
            "claimed_brand": evidence.get("claimed_brand"),
            "brand_kind": evidence.get("brand_kind"),
            "instant_payment": any(word in blob for word in _PAYMENT_WORDS),
            "payment_change": shared["payment_change"],
            "forwarding_code": any(code in blob for code in _FORWARD_CODES),
            "forwarding_intent": "divert" in blob or "forward your calls" in blob or "redirect your messages" in blob,
            # Mirror of frontend messageAnalysis.ts: a supplied number + call/contact wording; a charge claim only
            # with dispute or urgency wording. A phone number on its own is never suspicious.
            "callback_request": callback_request(blob),
            "alleged_charge": alleged_charge(blob),
            # Read on the message as written (case and look-alike characters kept).
            "lookalike_name": lookalike_name(raw_text),
            "lookalike_chars": bool(disguised_words(raw_text)),
            "reply_request": bool(_REPLY.search(raw_text)),
            "time_pressure": bool(_PRESSURE.search(raw_text)),
            "government_rebate": rebate_claim(raw_text),
        }
        phones = provider_evidence.get("ipqs", {}).get("phones", {})
        for phone, info in phones.items():
            if info.get("status") == "ok":
                score = info.get("fraud_score") or 0
                shared["phone_reputation"] = {"status": "ok", "verdict": "malicious" if score >= 85 else "clean",
                                              "fraud_score": score, "number": phone}
                if info.get("freshness") == "stale":
                    shared["incomplete_checks"] = [*shared.get("incomplete_checks", []), incomplete_check(
                        "number_reputation", info.get("failure"), status="stale", source="ipqs", at=info.get("checked_at"))]
            else:
                failure = info.get("failure") or ("not_configured" if info.get("status") == "not_configured" else None)
                shared.setdefault("phone_reputation", {"status": "unavailable", "verdict": "unknown",
                                                       **({"failure": failure} if failure else {})})
                shared["incomplete_checks"] = [*shared.get("incomplete_checks", []), incomplete_check(
                    "number_reputation", failure, source="ipqs", detail=info.get("detail") or "")]
            break

    if source_type == "email":
        shared["auth_recorded_by"] = evidence.get("auth_recorded_by")
        if not evidence.get("auth_results"):
            # Missing headers are a check that couldn't run — recorded as incomplete, never as a threat or a gap.
            shared["auth_results"] = {}
            shared["incomplete_checks"] = [*shared.get("incomplete_checks", []), incomplete_check("sender_authentication", "not_recorded")]

    scam_matches = provider_evidence.get("scam_intel", {}).get("matches", [])
    if any(m.get("severity") in ("high", "critical") for m in scam_matches):
        shared["indicator_match"] = True
        shared["local_level"] = "malicious"
        shared["local_signals"] = ["active_scam_advisory_match"]

    return shared


_RISKY_ATTACHMENT_EXT = {".exe", ".scr", ".bat", ".cmd", ".com", ".pif", ".js", ".vbs", ".wsf",
                         ".msi", ".dll", ".hta", ".ps1", ".reg", ".lnk", ".iso", ".img", ".cab"}


# ── Main triage entry point ────────────────────────────────────────────────

async def triage_item(
    device_id: str,
    evidence: dict,
    findings: list[str],
    correlation_id: str,
    *,
    bypass_cache: bool = False,
    provider_evidence: Optional[dict] = None,
    correlation: Optional[dict] = None,
) -> TriageResult:
    """Deterministic Triage Investigation. Makes ZERO Gemini calls.

    1. Cache lookup (an identical indicator already resolved deterministically).
    2. Gather specialist provider evidence, with bounded retries for transient failures.
    3. Evaluate the canonical rule catalogue.

    Tier 2 (the investigation) is NOT invoked here — the caller starts exactly one
    investigation per correlated case when result.should_escalate is True.
    """
    fingerprint = compute_fingerprint(evidence)
    source_type = evidence.get("source_type", "unknown")

    if not bypass_cache:
        cached = await _cache_lookup(fingerprint, device_id)
        if cached:
            outcome_value = cached.get("outcome")
            outcome = Outcome(outcome_value) if outcome_value in {o.value for o in Outcome} else legacy_outcome(cached.get("verdict", ""))
            result = TriageResult(
                outcome=outcome,
                reason=f"[Previously checked] {cached.get('reason', 'Resolved deterministically.')}",
                cached=True,
                cache_key=fingerprint,
                source_type=source_type,
                providers_used=cached.get("providers_used", []),
            )
            await record_triage(device_id, fingerprint, result, evidence, cached=True)
            _log.info("triage_cache_hit device=%s fingerprint=%s outcome=%s",
                      device_id, fingerprint[:12], result.outcome.value)
            return result

    retries: list = []
    if provider_evidence is None:
        provider_evidence, retry_record = await run_with_retries(
            "specialist_provider_evidence", lambda: gather_provider_evidence(evidence))
        retries.append(retry_record)
        if provider_evidence is None:
            provider_evidence = {}

    rule_evidence = _rule_evidence(evidence, findings, provider_evidence, correlation)
    investigation = evaluate(rule_evidence, investigation_id=correlation_id, retries=retries)

    result = TriageResult(
        outcome=investigation.outcome,
        reason=investigation.reason,
        investigation=investigation,
        cache_key=fingerprint,
        source_type=source_type,
        provider_evidence=provider_evidence,
        providers_used=provider_evidence.get("_summary", {}).get("providers_consulted", []),
    )
    await _cache_store(fingerprint, device_id, result, evidence)
    await record_triage(device_id, fingerprint, result, evidence)
    _log.info("triage_deterministic device=%s fingerprint=%s outcome=%s rules_met=%s gaps=%s",
              device_id, fingerprint[:12], result.outcome.value,
              [r.rule_id for r in investigation.met_rules],
              [g.code for g in investigation.coverage_gaps])
    return result


# ── Reporting aggregation ───────────────────────────────────────────────────

async def get_triage_stats(start: datetime | None = None, end: datetime | None = None) -> dict:
    """Aggregate Triage statistics for the admin dashboard.

    Triage spends nothing, so cost reporting exists only to prove that: every
    deterministic decision is $0 and investigation escalations equal POSSIBLE THREAT count.
    """
    match: dict = {"record_type": "decision"}
    if start or end:
        ts_filter: dict = {}
        if start:
            ts_filter["$gte"] = start
        if end:
            ts_filter["$lte"] = end
        match["decided_at"] = ts_filter

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {"outcome": {"$ifNull": ["$outcome", "$verdict"]}},
            "count": {"$sum": 1},
            "cost": {"$sum": {"$ifNull": ["$cost_usd", 0]}},
            "cached": {"$sum": {"$cond": ["$cached", 1, 0]}},
        }},
    ]
    rows = await db[COLLECTION].aggregate(pipeline).to_list(50)

    provider_pipeline = [
        {"$match": match},
        {"$unwind": {"path": "$providers_used", "preserveNullAndEmptyArrays": False}},
        {"$group": {"_id": "$providers_used", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    provider_rows = await db[COLLECTION].aggregate(provider_pipeline).to_list(50)

    total_items = 0
    total_cost = 0.0
    cached_count = 0
    outcomes = {o.value: 0 for o in Outcome}

    for row in rows:
        raw = row["_id"]["outcome"] or ""
        value = raw if raw in outcomes else legacy_outcome(raw).value
        count = row["count"]
        total_items += count
        total_cost += row["cost"]
        cached_count += row["cached"]
        outcomes[value] += count

    escalations = outcomes[Outcome.POSSIBLE_THREAT.value]
    resolved_without_ai = total_items - escalations

    return {
        "items_screened": total_items,
        "triage_deterministic": total_items,
        "magnum_di_escalations": escalations,
        "resolved_without_ai": resolved_without_ai,
        "cached_resolutions": cached_count,
        "gemini_calls_prevented": resolved_without_ai,
        "total_cost_usd": round(total_cost, 6),
        "avg_cost_per_item": round(total_cost / total_items, 8) if total_items else 0.0,
        "kpi_target": 0.0,
        "kpi_met": total_cost == 0.0,
        "distribution": {
            "no_threat_pct": round(outcomes[Outcome.NO_THREAT.value] / total_items * 100, 1) if total_items else 0,
            "possible_threat_pct": round(escalations / total_items * 100, 1) if total_items else 0,
            "limited_pct": round(outcomes[Outcome.LIMITED.value] / total_items * 100, 1) if total_items else 0,
        },
        "outcomes": outcomes,
        "provider_utilisation": {row["_id"]: row["count"] for row in provider_rows},
    }
