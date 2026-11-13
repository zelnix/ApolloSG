"""LLM Evidence Boundary — single enforcement point before every Gemini request.

Protect the person, preserve the evidence, share only what is necessary: strips credentials/secrets from
everything, keeps security evidence intact, and withholds unrelated personal data outside an investigation.
Research/advisory text is additionally minimised. Works on a copy of the outbound payload — the original
evidence is never modified. Operates on the assembled payload immediately before
the SDK call — not on upstream helpers.

Principles:
- Preserve security indicators, facts, timestamps, confidence and evidence relationships.
- Remove credentials, tokens, authentication codes and recovery secrets.
- Minimise personal identifiers unless their actual values are essential and authorised.
- Reject unauthorised payloads rather than silently replacing them with summaries.
- Same restrictions apply to all external calls: inference, token counting, research, TTS.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any
from urllib.parse import urlparse, parse_qs, urlencode, unquote

from core.redaction import redact_investigation_secrets


# ── URL compression for token efficiency ────────────────────────────────
# Long tracking/marketing URLs waste tokens without adding investigative value.
# We preserve the domain, path and security-relevant query parameters while
# stripping analytics trackers and truncating the rest.

# Query parameters that are NEVER security-relevant — safe to strip unconditionally.
_TRACKING_PARAMS = frozenset({
    # Google / Urchin analytics
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    # Google Ads / click IDs
    "gclid", "gclsrc", "dclid", "gbraid", "wbraid", "gad_source",
    # Meta (Facebook / Instagram)
    "fbclid", "fb_action_ids", "fb_action_types", "fb_ref", "fb_source",
    # Microsoft / Bing Ads
    "msclkid",
    # Mailchimp / email marketing
    "mc_cid", "mc_eid", "_hsenc", "_hsmi", "hsa_cam", "hsa_grp", "hsa_mt",
    "hsa_src", "hsa_ad", "hsa_acc", "hsa_net", "hsa_ver", "hsa_la", "hsa_ol", "hsa_kw",
    # General analytics / session tracking
    "ref", "referrer", "source", "medium", "campaign", "cid", "sid",
    "_ga", "_gl", "_gid", "_gac", "_fbc", "_fbp",
    "s_kwcid", "ef_id", "s_cid", "guccounter", "guce_referrer", "guce_referrer_sig",
    "srsltid", "tracking_id", "trk", "trkCampaign", "trkInfo",
    "click_id", "clickid", "clkid",
    # Email platform tracking
    "vero_id", "vero_conv", "oly_enc_id", "oly_anon_id",
    "mc_tc", "sc_cid", "sc_lid",
})

# Parameters that may hold security-relevant information (redirect targets, scam pages).
_SECURITY_PARAMS = frozenset({
    "redirect", "redirect_uri", "redirect_url", "return", "return_url", "returnurl",
    "next", "url", "uri", "target", "destination", "goto", "continue", "redir",
    "callback", "callback_url", "login_hint", "state",
})

_URL_RE = re.compile(r"https?://[^\s\"'<>\]\)]+", re.ASCII)
_MAX_URL_LEN = 200  # Truncate any URL above this after cleaning
_MAX_PARAM_VALUE_LEN = 80  # Individual query parameter value cap


def compress_urls(text: str) -> str:
    """Compress long URLs in text to save tokens while preserving investigative value.

    Strategy per URL:
    1. Strip known tracking/analytics parameters unconditionally.
    2. Truncate remaining query-parameter values over 80 chars.
    3. If the cleaned URL is still over 200 chars, hard-truncate with a marker.

    Domain + path are ALWAYS preserved (they're the primary phishing indicator).
    Security-relevant params (redirect, callback, etc.) are kept but value-truncated.
    """
    if "http" not in text:
        return text

    def _compress(match: re.Match) -> str:
        raw_url = match.group(0)
        try:
            parsed = urlparse(raw_url)
            if not parsed.query:
                # No query string — only length-cap
                if len(raw_url) > _MAX_URL_LEN:
                    return raw_url[:_MAX_URL_LEN] + "…"
                return raw_url
            qs = parse_qs(parsed.query, keep_blank_values=True)
            # Strip tracking params and truncate long values
            cleaned_params: list[tuple[str, str]] = []
            for key, values in qs.items():
                if key.lower() in _TRACKING_PARAMS:
                    continue
                for v in values:
                    decoded = unquote(v)
                    if len(decoded) > _MAX_PARAM_VALUE_LEN:
                        cap = _MAX_PARAM_VALUE_LEN * 2 if key.lower() in _SECURITY_PARAMS else _MAX_PARAM_VALUE_LEN
                        decoded = decoded[:cap] + "…"
                    cleaned_params.append((key, decoded))
            new_query = urlencode(cleaned_params) if cleaned_params else ""
            rebuilt = parsed._replace(query=new_query, fragment="").geturl()
            # Final length cap
            if len(rebuilt) > _MAX_URL_LEN:
                return rebuilt[:_MAX_URL_LEN] + "…"
            return rebuilt
        except Exception:
            return raw_url[:_MAX_URL_LEN] + "…" if len(raw_url) > _MAX_URL_LEN else raw_url

    return _URL_RE.sub(_compress, text)


class Purpose(str, Enum):
    """Processing purposes — each permits different evidence fields."""
    ORDINARY_CHAT = "ordinary_chat"           # Structured facts, no raw evidence
    INVESTIGATION = "investigation"           # Authorised evidence for the case
    RESEARCH = "research"                     # Minimal public identifiers only
    VISION_PREFLIGHT = "vision_preflight"     # Image admission check (secret detection)
    TOKEN_COUNT = "token_count"               # Same as the associated purpose
    PUBLIC_ADVISORY_ANALYSIS = "public_advisory_analysis"  # Government scam advisory classification
    VISION_INVESTIGATION = "vision_investigation"  # Vision Gate: photograph/upload → indicator extraction + routing
    TRIAGE = "triage"                         # Evidence-readiness assessment only; never a scam verdict
    TC_FLYBY_SEARCH = "tc_flyby_search"             # TC Hawkeye: narrow factual web search lookups about public identifiers
    DEVICE_SETTING_VERIFICATION = "device_setting_verification"  # Screenshot verification of manual device settings


# ── One outbound privacy decision per field ────────────────────────────────
# A. credential/authentication secret → never sent.
# B. security evidence or the explicit lookup target → sent (credential stripping still applies to its text).
# C. unrelated personal data → withheld unless the purpose is an authorised investigation.
# The field registry (core.data_classification) says what a field holds; this is the only place that decides.
from core.data_classification import DataCategory, classify_field as _field_categories

_PERSONAL = {DataCategory.PII, DataCategory.LOCATION, DataCategory.MEDICAL, DataCategory.FINANCIAL,
             DataCategory.SENSITIVE_PERSONAL, DataCategory.UNKNOWN}


def field_decision(key: str) -> str:
    """'credential' | 'evidence' | 'personal' for a payload field name.

    Dual-classified fields (sender, caller_number, email address…) are evidence: a security indicator keeps its
    investigative value even though it also identifies someone. Unknown fields are treated as personal (withheld
    outside an investigation) — never silently as evidence."""
    cats = _field_categories(key)
    if DataCategory.CREDENTIAL in cats:
        return "credential"
    if DataCategory.SECURITY_INDICATOR in cats:
        return "evidence"
    if cats & _PERSONAL:
        return "personal"
    return "evidence"


# Patterns that indicate credential material — must be stripped before any external call.
_CREDENTIAL_PATTERNS = [
    re.compile(r"(?i)\b(password|passcode|p\.?i\.?n\.?|otp|one[- _]?time[- _]?code|verification[- _]?code|security[- _]?code|recovery[- _]?code|recovery[- _]?phrase|seed[- _]?phrase|private[- _]?key|secret[- _]?key|api[- _]?key|access[- _]?token|refresh[- _]?token|session[- _]?token|bearer[- _]?token)\b\s*(?:is|was|:|=)\s*[^\s]{3,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)([?&](?:(?:access|refresh|auth|api)[_-]?)?(?:token|password|secret|key|code|session|signature)=)[^\s&#\"']+"),
    re.compile(r"(https?://)[^\s/@]+:[^\s/@]+@"),
]

def strip_credentials(text: str) -> str:
    """Remove all credential patterns from text.

    Uses the base investigation redaction first (passwords, PINs, OTPs, codes),
    then applies additional patterns for API keys, bearer tokens, and URL credentials
    that the base redaction doesn't cover. Avoids double-redaction by checking
    whether the base pass already handled the pattern."""
    result = redact_investigation_secrets(text)
    # Additional patterns: only the ones NOT covered by redact_investigation_secrets
    # Pattern 0 overlaps with base redaction (password/PIN/OTP) — skip it
    # Patterns 1-3 are additional: Bearer tokens, URL query params, URL auth credentials
    for pattern in _CREDENTIAL_PATTERNS[1:]:
        result = pattern.sub("[credential redacted]", result)
    # Pattern 0 catches api_key=, secret_key=, access_token= etc. with underscore separators
    # that the base redaction misses. Apply it but only match lines not already redacted.
    result = _CREDENTIAL_PATTERNS[0].sub("[credential redacted]", result)
    return result


def enforce_boundary(purpose: Purpose, payload: Any, *, evidence_pii: set[str] | None = None) -> Any:
    """Enforce the LLM evidence boundary on an outgoing payload.

    For string payloads: strip credentials and (for research/TTS) minimise personal data.
    For structured payloads (dicts/lists): recursively process values.

    `evidence_pii`: optional set of known personal data values from the case evidence
    inventory. When provided and purpose is RESEARCH, these exact values are replaced
    deterministically in outbound text. This is safer than heuristic regex.

    Raises ValueError if the payload contains material that cannot be safely processed
    for the given purpose.
    """
    if isinstance(payload, str):
        return _enforce_text(purpose, payload, evidence_pii=evidence_pii)
    if isinstance(payload, dict):
        return _enforce_dict(purpose, payload, evidence_pii=evidence_pii)
    if isinstance(payload, (list, tuple)):
        return type(payload)(_enforce_item(purpose, item, evidence_pii=evidence_pii) for item in payload)
    return payload


# ABN, ACN and licence numbers: an exact number goes only to TC Hawkeye's register question about that number (its search
# call, where every other question already carries the number as a label: tc_flyby/search.prompt). Every other AI or
# research request carries it as a label.
_REGISTRATION_NUMBERS = (
    (re.compile(r"\bABN[\s:#.]*(?:\d[\s-]?){10}\d\b", re.I), "[business number]"),
    (re.compile(r"\bACN[\s:#.]*(?:\d[\s-]?){8}\d\b", re.I), "[company number]"),
    (re.compile(r"\b(?:AFSL|AFS\s+licen[cs]e|Australian\s+financial\s+services\s+licen[cs]e|ACL|Australian\s+credit\s+licen[cs]e)"
                r"(?:\s*(?:no\.?|number|#))?[\s:#]*\d{5,7}\b", re.I), "[licence number]"),
)


def redact_registration_numbers(text: str) -> str:
    """An ABN, ACN or AFSL/ACL licence number becomes its label ("[business number]", …)."""
    for pattern, label in _REGISTRATION_NUMBERS:
        text = pattern.sub(label, text)
    return text


def _enforce_text(purpose: Purpose, text: str, *, evidence_pii: set[str] | None = None) -> str:
    """Strip credentials from all text, compress long URLs. For research and advisory analysis, also minimise personal identifiers."""
    cleaned = strip_credentials(text)
    cleaned = compress_urls(cleaned)
    if purpose is not Purpose.TC_FLYBY_SEARCH:
        cleaned = redact_registration_numbers(cleaned)
    if purpose in (Purpose.RESEARCH, Purpose.PUBLIC_ADVISORY_ANALYSIS):
        # Research and advisory queries should contain only public identifiers, not personal data.
        # Public advisories may contain third-party PII (victim details, witness names).
        # Uses evidence-inventory-aware minimisation when available (deterministic, not heuristic).
        cleaned = _minimise_personal_identifiers(cleaned, evidence_pii=evidence_pii)
    return cleaned


def _enforce_dict(purpose: Purpose, data: dict, *, evidence_pii: set[str] | None = None) -> dict:
    """Recursively enforce boundary on dict values.

    For non-investigation purposes, personal data field VALUES are minimised (replaced
    with category labels), not silently dropped. This preserves the field structure
    while protecting the actual personal data content."""
    result = {}
    for key, value in data.items():
        decision = field_decision(key)
        if decision == "credential":
            continue  # Credential fields always excluded
        if decision == "personal" and purpose != Purpose.INVESTIGATION:
            # Minimise personal data values rather than dropping the field entirely.
            # This preserves structure while protecting content.
            if isinstance(value, str):
                result[key] = "[personal data withheld]"
            else:
                continue  # Non-string personal data (nested objects) excluded
        else:
            result[key] = _enforce_item(purpose, value, evidence_pii=evidence_pii)
    return result


def _enforce_item(purpose: Purpose, item: Any, *, evidence_pii: set[str] | None = None) -> Any:
    """Enforce boundary on a single item."""
    if isinstance(item, str):
        return _enforce_text(purpose, item, evidence_pii=evidence_pii)
    if isinstance(item, dict):
        return _enforce_dict(purpose, item, evidence_pii=evidence_pii)
    if isinstance(item, (list, tuple)):
        return type(item)(_enforce_item(purpose, i, evidence_pii=evidence_pii) for i in item)
    return item


def _minimise_personal_identifiers(text: str, evidence_pii: set[str] | None = None) -> str:
    """Replace personal identifiers with category labels when they're not security-relevant.

    Two protection layers:
    1. Deterministic pattern matching for email addresses, phone numbers, and financial identifiers.
       These patterns are narrow enough to avoid over-redacting domain names or security indicators.
    2. Evidence-inventory-aware replacement: if `evidence_pii` is provided, exact-match those
       known personal values in the outbound text. This is DETERMINISTIC (exact string match,
       not heuristic) and cannot over-redact investigation-relevant identifiers.

    DESIGN DECISION: No broad name-recognition regex is used. Name-pattern regexes would
    over-redact legitimate domain names, business names and scam identifiers that Higgins
    must investigate. Instead, personal names are protected only when they appear in the
    evidence inventory as known PII values — deterministic, not heuristic.
    """
    # Layer 1: Deterministic patterns (order matters: longer/specific patterns first)
    # Financial identifiers: credit card numbers (13-19 digits with optional separators)
    text = re.sub(r"\b(?:\d[ -]?){12,18}\d\b", "[financial identifier]", text)
    # BSB / sort codes (6 digits with dash in the middle, when preceded by context)
    text = re.sub(r"(?i)(?:BSB|sort\s*code|routing)[:\s]*\d{3}[- ]?\d{3}", "[financial identifier]", text)
    # Account numbers preceded by context keywords
    text = re.sub(r"(?i)(?:account|acct|a/c)[:\s#]*\d{4,12}", "[account number]", text)
    # Australian Tax File Number (TFN): 8-9 digits, often with spaces, preceded by context
    text = re.sub(r"(?i)(?:TFN|tax\s*file)[:\s]*\d{3}\s*\d{3}\s*\d{2,3}", "[tax identifier]", text)
    # Australian Medicare number: 10-11 digits, often formatted 1234 56789 0 / 1
    text = re.sub(r"(?i)(?:medicare)[:\s#]*\d{4}\s*\d{5}\s*\d{1,2}(?:\s*/\s*\d)?", "[medicare number]", text)
    # Australian Business Number (ABN): 11 digits preceded by context
    text = re.sub(r"(?i)(?:ABN)[:\s]*\d{2}\s*\d{3}\s*\d{3}\s*\d{3}", "[business number]", text)
    # Passport numbers preceded by context
    text = re.sub(r"(?i)(?:passport)[:\s#]*[A-Z]{1,2}\d{6,9}", "[passport number]", text)
    # National Insurance / SSN preceded by context
    text = re.sub(r"(?i)(?:SSN|social\s*security|NI\s*number)[:\s]*[\dA-Z]{6,11}", "[government identifier]", text)
    # Phone numbers (but not port numbers, IDs, years, or short numeric sequences).
    # Requires at least 8 digits total. The negative lookbehind/lookahead prevents matching
    # numbers embedded in larger numeric contexts. Dots in domains are excluded.
    text = re.sub(r"(?<![0-9@./])\+?\d[\d\s().-]{7,}\d(?![0-9@./])", "[phone number]", text)
    # Email addresses
    text = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[email]", text)

    # Layer 2: Evidence-inventory-aware deterministic replacement
    if evidence_pii:
        # Sort by length descending so longer matches replace first (prevents partial replacements)
        for pii_value in sorted(evidence_pii, key=len, reverse=True):
            if len(pii_value) >= 3 and pii_value in text:
                text = text.replace(pii_value, "[personal identifier]")

    return text


def extract_evidence_pii(evidence_texts: list[str]) -> set[str]:
    """Extract known personal identifiers from case evidence texts for deterministic protection.

    Returns a set of exact string values found in evidence that are personal data (emails,
    phone numbers, account numbers). These are then used by `_minimise_personal_identifiers()`
    to perform exact-match replacement in outbound research queries.

    This function does NOT use heuristic name detection. It only extracts identifiers that
    can be deterministically classified as personal data by their format.
    """
    pii: set[str] = set()
    for text in evidence_texts:
        if not text:
            continue
        # Extract email addresses
        for match in re.finditer(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text):
            pii.add(match.group(0))
        # Extract phone numbers (not port numbers or domain-embedded digits)
        for match in re.finditer(r"(?<![0-9@./])\+?\d[\d\s().-]{7,}\d(?![0-9@./])", text):
            pii.add(match.group(0).strip())
        # Extract financial identifiers (credit card-like)
        for match in re.finditer(r"\b(?:\d[ -]?){12,18}\d\b", text):
            pii.add(match.group(0).strip())
        # Extract account numbers with context
        for match in re.finditer(r"(?i)(?:account|acct|a/c)[:\s#]*(\d{4,12})", text):
            pii.add(match.group(1))
    return pii


def validate_outbound_payload(purpose: Purpose, text: str) -> list[str]:
    """Validate that an outbound text payload doesn't contain obvious credential leaks.
    Returns a list of violation descriptions (empty = clean)."""
    violations = []
    for pattern in _CREDENTIAL_PATTERNS:
        if pattern.search(text):
            violations.append(f"Credential pattern detected in {purpose.value} payload")
            break
    return violations
