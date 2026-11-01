"""Who an email or message presents itself as — never every organisation it mentions.

Read in order from: the From display name, then how the text introduces or signs itself ("This is Sam from Apple
Support", "The PayPal Team", "Regards, CommBank"). A brand that is only mentioned ("Shop the new Apple iPhone at JB
Hi-Fi") is not a claim to be that brand: a retailer selling Apple products is not impersonating Apple.
Pure: no I/O.
"""
from __future__ import annotations

import re

from services.higgins.indicators import BRANDS

_NAME = r"([A-Z][\w&'’.-]*(?:\s+[A-Z][\w&'’.-]*){0,3})"
_SIGN_OFF = re.compile(rf"(?:^|\n)\s*(?:(?:kind|best|warm)\s+regards|regards|sincerely|thanks|thank you|cheers|from)[,\s]+(?:the\s+)?{_NAME}", re.I | re.M)
_TEAM = re.compile(rf"\b(?:[Tt]he\s+)?{_NAME}\s+(?:Team|Support|Security|Customer Service|Service Centre|Accounts Team|Billing)\b")


def display_name(sender: str) -> str:
    """'"PayPal Security" <service@x.com>' → 'PayPal Security'; a bare address has none."""
    text = (sender or "").strip()
    if "<" not in text:
        return ""
    return text.split("<", 1)[0].strip().strip('"').strip("'").strip()


def brand_in(name: str) -> str | None:
    """The organisation on ApolloSG's register this name is (its words, not a substring of another word)."""
    low = (name or "").lower()
    for needle, (brand, _domain) in sorted(BRANDS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", low):
            return brand
    return None


def claimed(sender: str, text: str) -> dict | None:
    """{name, known, how, quote}: the organisation speaking. `known` when it is on ApolloSG's register (its own
    domains are known, so the sender and destinations can be compared with them)."""
    from services.triage_engine import organisation_named
    name = display_name(sender)
    if brand_in(name):
        return {"name": brand_in(name), "known": True, "how": "display_name", "quote": name}
    candidates = [(organisation_named(text or ""), "introduction")]
    candidates += [(m.group(1), "sign_off") for m in _SIGN_OFF.finditer(text or "")]
    candidates += [(m.group(1), "team") for m in _TEAM.finditer(text or "")]
    for candidate, how in candidates:
        if candidate and brand_in(candidate):
            return {"name": brand_in(candidate), "known": True, "how": how, "quote": candidate}
    if name and "@" not in name:
        return {"name": name, "known": False, "how": "display_name", "quote": name}
    return None
