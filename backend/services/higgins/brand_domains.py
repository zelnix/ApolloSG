"""Whether an address belongs to the organisation a message names, and what counts as a sign that it doesn't.

An address that isn't an organisation's main domain is not, on its own, evidence of impersonation. Big
organisations run country sites (ebay.com.au) and sub-sites (pages.ebay.com.au). ApolloSG treats only a real
lookalike sign as a warning: the name with words added (signin-ebay.com.au), a misspelling (paypa1.com), the
name inside someone else's address (ebay.com.secure-login.example), the name on another ending (commbank.co),
or the name on a link-sharing or website service anyone can use (ebay.onelink.me). An address that doesn't
carry the name at all can't be confirmed either way until something independent backs it up.

Pure: no I/O.
"""
from __future__ import annotations

import re

from services.higgins.indicators import BRANDS

_SECOND_LEVEL = ("com", "net", "org", "gov", "edu", "asn", "id", "co")


def registrable(host: str) -> str:
    """Last two labels, or three for second-level suffixes (commbank.com.au, ebay.co.uk).

    Strips trailing non-domain characters (quotes, punctuation) defensively before parsing,
    so text-extraction artefacts like 'amazon.co.jp"' are handled correctly.
    """
    # Strip characters that cannot appear in a valid hostname label (defensive against text-extraction artefacts)
    cleaned = re.sub(r"[^a-z0-9.\-]", "", (host or "").lower().removeprefix("www."))
    parts = cleaned.split(".")
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else cleaned


# Each organisation's published domains beyond the main one in BRANDS (its own country sites, sign-in and
# asset domains). Only domains the organisation itself runs.
_MORE_OFFICIAL: dict[str, tuple[str, ...]] = {
    "CommBank": ("netbank.com.au", "cba.com.au"),
    "ANZ": ("anz.com", "anz.co.nz"),
    "PayPal": ("paypal.com.au", "paypal.me", "paypalobjects.com"),
    "Telstra": ("telstra.com",),
    "myGov": ("servicesaustralia.gov.au",),
    "Medicare": ("my.gov.au",),
    "Centrelink": ("my.gov.au",),
    "Microsoft": ("microsoftonline.com", "live.com", "office.com", "outlook.com", "sharepoint.com", "office365.com"),
    "Google": ("google.com.au", "gmail.com", "youtube.com"),
    "Apple": ("icloud.com",),
    "Amazon": ("amazon.com.au", "amazon.co.uk", "amazon.de", "amazon.ca", "amazon.co.jp", "amazon.in", "amazon.sg"),
    "eBay": ("ebay.com.au", "ebay.co.uk", "ebay.ca", "ebay.de", "ebay.fr", "ebay.it", "ebay.es", "ebay.ie", "ebay.at", "ebay.ch",
             "ebay.nl", "ebay.be", "ebay.pl", "ebay.com.sg", "ebay.com.hk", "ebay.com.my", "ebay.ph", "ebaystatic.com", "ebayimg.com",
             "ebayinc.com"),
}

# Services where anyone can put any name in front of the service's own address.
SHARED_SERVICES = frozenset({
    "onelink.me", "page.link", "app.link", "web.app", "firebaseapp.com", "github.io", "gitlab.io", "netlify.app", "vercel.app",
    "pages.dev", "workers.dev", "herokuapp.com", "glitch.me", "repl.co", "wixsite.com", "weebly.com", "blogspot.com",
    "wordpress.com", "square.site", "godaddysites.com", "webflow.io", "framer.website", "carrd.co", "linktr.ee", "notion.site",
    "ngrok.io", "ngrok-free.app", "trycloudflare.com", "azurewebsites.net", "r2.dev", "surge.sh", "000webhostapp.com", "canva.site",
})

# Country endings sold to anyone as general-purpose addresses: the organisation's name on one isn't a country site.
_OPEN_COUNTRY_ENDINGS = frozenset({"co", "me", "io", "tv", "cc", "ws", "tk", "ml", "ga", "cf", "gq", "ly", "to", "sh", "ai", "gg",
                                   "vc", "la", "fm", "am", "so", "su", "nu", "pw", "ac", "im", "bz", "li", "st", "sx", "cx", "cm"})

# What gives a lookalike away, said after the mismatch — only where it adds something the address doesn't already
# show. "added_words" (commbank-cancel.co) has no entry: the added words are plain from the address itself.
SIGN_WORDS = {"misspelt": "the name is spelt to look like it",
              "inside": "the name sits in front of someone else's address",
              "other_ending": "the name is on a different web ending"}

# The Official Organisation Directory's counted domains per organisation (filled by services/org_directory.load()).
DIRECTORY: dict[str, tuple[str, ...]] = {}

# Well-established, genuinely safe domains that ApolloSG recognises for the narrow "a message
# contains nothing but a link to a well-known, correctly-matched domain, with nothing else present"
# carve-out (Unified Evidence Classification PRD §4, owner confirmation 2026-11-08). Deliberately
# NOT added to BRANDS: BRANDS drives impersonation-matching against arbitrary message text (a short
# keyword like "abc" would false-match all sorts of unrelated mentions), whereas this list is only
# ever consulted against an already-extracted link's own host — never scanned for in free text.
# These are major, unambiguous, non-impersonation-target organisations (news, public broadcasters) —
# never a bank, government payment service or anything scammers actually impersonate; those stay in
# BRANDS/the Official Organisation Directory, where the stronger impersonation-aware checks apply.
RECOGNISED_SAFE_DOMAINS = frozenset({
    "abc.net.au",   # Australian Broadcasting Corporation
})


def is_recognised_safe_domain(host: str) -> bool:
    """A link's own host is one of RECOGNISED_SAFE_DOMAINS or an organisation's published domain
    (brand_domains.owner()) — genuinely known to ApolloSG's registers, not merely "nothing flagged it
    as bad"."""
    return registrable(host) in RECOGNISED_SAFE_DOMAINS or bool(owner(host))


def official_domains(name: str) -> tuple[str, ...]:
    """The organisation's published domains, main one first: ApolloSG's own register, then the Official Organisation
    Directory's (services/org_directory.py keeps DIRECTORY current)."""
    main = tuple(dict.fromkeys(domain for brand, domain in BRANDS.values() if brand == name))
    more = (*_MORE_OFFICIAL.get(name, ()), *DIRECTORY.get(name, ()))
    return main + tuple(dict.fromkeys(d for d in more if d not in main))


def owner(host: str) -> str | None:
    """The organisation whose published domain this host is on, if any."""
    reg = registrable(host)
    return next((name for name, _ in dict.fromkeys(BRANDS.values()) if reg in official_domains(name)), None)


def _tokens(name: str) -> list[str]:
    needles = [n for n, (brand, _) in BRANDS.items() if brand == name] + [name.lower()]
    return list(dict.fromkeys(v for n in needles for v in (n.replace(" ", ""), n.replace(" ", "-"))))


def _carries(text: str, tokens: list[str]) -> bool:
    """The name is part of the text: names of four letters or more anywhere, shorter ones (ANZ, ING) only as a whole word."""
    return any(len(t) >= 4 and t in text or re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", text) for t in tokens)


def _deobfuscate(label: str) -> str:
    """Undo look-alike characters: paypa1 → paypal, micr0soft → microsoft, rn → m.

    Also handles:
    * Unicode / IDN homoglyphs — Cyrillic 'а' and Greek 'ο' look identical to Latin letters
      in most typefaces; we map them before the numeric-substitution pass.
    * Punycode (xn--) labels — decoded first so the resulting ASCII label can be checked
      for lookalikes (xn--mzon-3-spa → amazon via Cyrillic 'а').
    * NFKC normalisation — converts full-width and ligature characters to ASCII equivalents.
    """
    import unicodedata
    text = (label or "").lower()
    # Punycode decode — if the label is ACE-encoded (xn--...) try to get the Unicode form
    if text.startswith("xn--"):
        try:
            text = text.encode("ascii").decode("idna")
        except (UnicodeError, UnicodeDecodeError):
            pass
    # NFKC: full-width 'ａ' → 'a', ligatures 'ﬁ' → 'fi', etc.
    text = unicodedata.normalize("NFKC", text)
    # Visually identical Unicode characters → Latin equivalents (Cyrillic, Greek homoglyphs)
    _HOMOGLYPHS = str.maketrans({
        "а": "a", "е": "e", "о": "o", "с": "c", "р": "r", "у": "u", "х": "x",   # Cyrillic
        "ё": "e", "і": "i", "ї": "i",                                             # Cyrillic variants
        "α": "a", "β": "b", "ε": "e", "ο": "o", "σ": "s", "τ": "t", "υ": "u",   # Greek
    })
    text = text.translate(_HOMOGLYPHS)
    # Numeric substitution (l33t-speak): 0→o, 1→l, 3→e, 4→a, 5→s, 7→t
    table = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t"})
    return re.sub(r"[^a-z]", "", text.translate(table).replace("rn", "m").replace("vv", "w"))


def _one_edit(a: str, b: str) -> bool:
    """One letter changed, added or dropped."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def _country_ending(suffix: str) -> bool:
    parts = suffix.split(".")
    if len(parts) == 2 and parts[0] in ("com", "co"):
        parts = parts[1:]
    return len(parts) == 1 and len(parts[0]) == 2 and parts[0].isalpha() and parts[0] not in _OPEN_COUNTRY_ENDINGS


def classify(name: str, place: str) -> tuple[str, str]:
    """(kind, detail) for an address in material that names `name`:
    official       — on one of the organisation's published domains (detail: that domain)
    country_site   — exactly the organisation's name on a country ending, as a global organisation's own
                     country sites are (ebay.com.au); genuine, though not on ApolloSG's register
    shared_service — the name in front of a link-sharing or website service anyone can use (detail: the service)
    lookalike      — a real lookalike sign (detail: added_words | misspelt | inside | other_ending)
    unrelated      — the address doesn't carry the name: on its own this can't be confirmed either way."""
    host = (place or "").lower().strip(".").removeprefix("www.")
    reg = registrable(host)
    official = official_domains(name)
    if not official or reg in official:
        return "official", reg
    main = official[0]
    main_label = main.split(".")[0]
    label, _, suffix = reg.partition(".")
    if label == main_label and main.count(".") == 1 and main.endswith(".com") and _country_ending(suffix):
        return "country_site", reg
    tokens = _tokens(name)
    in_front = host[: -len(reg)].rstrip(".") if host.endswith(reg) else ""
    if reg in SHARED_SERVICES:
        return ("shared_service", reg) if _carries(in_front, tokens) or _carries(_deobfuscate(in_front), tokens) else ("unrelated", reg)
    if label == main_label or label.replace("-", "") in {t.replace("-", "") for t in tokens}:
        return "lookalike", "other_ending"
    if _carries(label, tokens):
        return "lookalike", "added_words"
    plain = _deobfuscate(label)
    if (plain != label.replace("-", "") and _carries(plain, tokens)) or (len(main_label) >= 5 and _one_edit(label, main_label)):
        return "lookalike", "misspelt"
    if in_front and _carries(in_front, tokens):
        return "lookalike", "inside"
    return "unrelated", reg


def genuine(name: str, place: str) -> bool:
    return classify(name, place)[0] in ("official", "country_site")


def same_organisation(a: str, b: str) -> bool:
    """Two addresses on the same site, or both on one organisation's published domains."""
    ra, rb = registrable(a), registrable(b)
    return ra == rb or (owner(a) is not None and owner(a) == owner(b))
