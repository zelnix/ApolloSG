"""What submitted material itself states — organisations named, links, requests for credentials or money,
amounts, urgency, numbers and addresses. Deterministic reading, no inference and no lookup.

Used by Higgins Triage (tc_flyby/triage.py) and TC Hawkeye in every environment, and by the preview simulator.
It lives outside the preview package so production never loads a simulation module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── Indicators ───────────────────────────────────────────────────────────────

# Organisations commonly impersonated in Australia, with the domain they actually use.
BRANDS: dict[str, tuple[str, str]] = {
    "commbank": ("CommBank", "commbank.com.au"),
    "commonwealth bank": ("CommBank", "commbank.com.au"),
    "netbank": ("CommBank", "commbank.com.au"),
    "westpac": ("Westpac", "westpac.com.au"),
    "nab": ("NAB", "nab.com.au"),
    "anz": ("ANZ", "anz.com.au"),
    "bendigo bank": ("Bendigo Bank", "bendigobank.com.au"),
    "ing": ("ING", "ing.com.au"),
    "auspost": ("AusPost", "auspost.com.au"),
    "australia post": ("AusPost", "auspost.com.au"),
    "linkt": ("Linkt", "linkt.com.au"),
    "e-toll": ("E-Toll", "etoll.com.au"),
    "mygov": ("myGov", "my.gov.au"),
    "ato": ("the ATO", "ato.gov.au"),
    "medicare": ("Medicare", "servicesaustralia.gov.au"),
    "centrelink": ("Centrelink", "servicesaustralia.gov.au"),
    "telstra": ("Telstra", "telstra.com.au"),
    "optus": ("Optus", "optus.com.au"),
    "paypal": ("PayPal", "paypal.com"),
    "netflix": ("Netflix", "netflix.com"),
    "amazon": ("Amazon", "amazon.com"),
    "ebay": ("eBay", "ebay.com"),
    "microsoft": ("Microsoft", "microsoft.com"),
    "apple": ("Apple", "apple.com"),
    "google": ("Google", "google.com"),
    "woolworths": ("Woolworths", "woolworths.com.au"),
    "coles": ("Coles", "coles.com.au"),
}

CREDENTIAL_TERMS: dict[str, str] = {
    "password": "your password",
    "netbank password": "your NetBank password",
    "passcode": "your passcode",
    "pin": "your PIN",
    "one-time code": "a one-time code",
    "one time code": "a one-time code",
    "security code": "a security code",
    "verification code": "a verification code",
    "otp": "a one-time code",
    "2fa": "a two-factor code",
    "card number": "your card number",
    "cvv": "your card security number",
    "bsb": "your BSB and account number",
    "account number": "your account number",
    "tax file number": "your tax file number",
    "tfn": "your tax file number",
    "medicare number": "your Medicare number",
    "licence number": "your licence number",
    "log in": "your login",
    "login": "your login",
    "sign in": "your sign-in details",
    "verify your account": "your account login",
    "confirm your identity": "identity details",
}

PAYMENT_TERMS = ("pay", "payment", "fee", "fine", "toll", "invoice", "transfer", "refund",
                 "bitcoin", "crypto", "gift card", "voucher", "itunes", "steam card")

URGENCY_TERMS = ("immediately", "right now", "within 24 hours", "within 48 hours", "today",
                 "final notice", "last chance", "urgent", "suspended", "will be closed",
                 "avoid a fine", "avoid legal", "expires", "cancel it now", "act now")

URL_RE = re.compile(r"\bhttps?://[^\s<>\"')\]]+", re.I)
# Covers common generic TLDs + gov/edu (Australian govt/edu sites) + widely-used country TLDs.
# 'co' + optional '.[a-z]{2}' handles amazon.co.jp, commbank.com.au, ebay.co.uk etc.
BARE_DOMAIN_RE = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:com|net|org|gov|edu|au|co|io|info|xyz|top|shop|site|live|online)(?:\.[a-z]{2})?\b",
    re.I
)
AMOUNT_RE = re.compile(r"(?:AUD\s?)?\$\s?\d[\d,]*(?:\.\d{2})?", re.I)
# General international phone pattern: matches numbers with 7–15 digits,
# accepts leading + for international prefix, tolerates common separators.
# Replaces the previous AU-only AU_PHONE_RE — 'triage.py' uses a matching pattern for the full plan.
PHONE_RE = re.compile(r"(?<![\w@.+/])(\+?\d[\d\s().\-]{5,18}\d)(?![\w@])")
AU_PHONE_RE = PHONE_RE   # backward-compat alias for any callers still referencing AU_PHONE_RE
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def _host(url: str) -> str:
    # Split off protocol, path, query, fragment, and port in that order
    host = re.sub(r"^https?://", "", url, flags=re.I).split("/")[0].split("?")[0].split(":")[0].lower()
    # Strip any non-hostname characters left over from text extraction (quotes, brackets, commas …)
    host = re.sub(r"[^a-z0-9.\-]", "", host)
    return host[4:] if host.startswith("www.") else host



@dataclass
class Indicators:
    brands: list[tuple[str, str]] = field(default_factory=list)   # (display name, official domain)
    hosts: list[str] = field(default_factory=list)
    mismatched: list[tuple[str, str, str]] = field(default_factory=list)  # (brand, official, host)
    credentials: list[str] = field(default_factory=list)
    payments: list[str] = field(default_factory=list)
    amounts: list[str] = field(default_factory=list)
    urgency: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def read_indicators(text: str) -> Indicators:
    """Everything the evidence itself states. No inference yet."""
    low = text.lower()
    ind = Indicators()

    for needle, (name, official) in BRANDS.items():
        if needle in low and (name, official) not in ind.brands:
            ind.brands.append((name, official))

    hosts = [_host(u) for u in URL_RE.findall(text)]
    # Bare domains go through the same normalisation, so "www.abc.net.au" written in the text and
    # "https://abc.net.au/..." are recognised as one destination rather than two.
    hosts += [_host(h) for h in BARE_DOMAIN_RE.findall(text)]
    ind.hosts = _dedupe([h for h in hosts if h])

    # An address that isn't the organisation's main domain is a mismatch only when it isn't one of its own
    # (published domains and country sites): pages.ebay.com.au and ebay.com.au are eBay's.
    from services.higgins.brand_domains import genuine
    for name, official in ind.brands:
        for host in ind.hosts:
            if not genuine(name, host) and (name, official, host) not in ind.mismatched:
                ind.mismatched.append((name, official, host))

    ind.credentials = _dedupe([plain for term, plain in CREDENTIAL_TERMS.items() if term in low])
    ind.payments = _dedupe([term for term in PAYMENT_TERMS if term in low])
    ind.amounts = _dedupe(AMOUNT_RE.findall(text))
    ind.urgency = _dedupe([term for term in URGENCY_TERMS if term in low])
    # Extract all plausible phone numbers — international (e.g. +61, +1, +44) and domestic alike.
    # Keep only matches whose digit-only form is 7–15 chars (ITU E.164 practical range).
    ind.phones = _dedupe([
        m.group(1).strip()
        for m in PHONE_RE.finditer(text)
        if 7 <= len(re.sub(r"\D", "", m.group(1))) <= 15
    ])
    ind.emails = _dedupe(EMAIL_RE.findall(text))
    return ind
