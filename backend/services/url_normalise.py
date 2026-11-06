"""URL normalisation for the investigation pipeline (Finding F).

Strips well-known tracking-only query parameters (UTM, fbclid, gclid …) and
unifies scheme/host capitalisation and default ports before provider lookups.

Design constraints:
  • Never alters the host, path, or any non-tracking query parameter — a URL
    with a meaningful query string (e.g. a search result) is preserved exactly.
  • Strips the fragment (#…) because server-side lookups never need it.
  • Does NOT strip 'www.' — that changes the domain identity used by brand
    classification and RDAP.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Well-known tracking-only parameters that never change page content.
# This list is intentionally conservative: when in doubt a parameter is kept.
_TRACKING_PARAMS: frozenset[str] = frozenset({
    # Google / UTM
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    "gclid", "dclid",
    # Meta / Facebook
    "fbclid", "igshid",
    # Microsoft
    "msclkid",
    # TikTok
    "ttclid",
    # Yandex
    "yclid",
    # Mailchimp
    "mc_cid", "mc_eid",
    # Zanox / Awin
    "zanpid",
    # Generic campaign IDs used exclusively by tracking systems
    "s_cid",
})


def normalise_url(url: str) -> str:
    """Return the canonical form of *url* for provider lookups.

    Two URLs differing only in tracking parameters, scheme capitalisation or
    default port numbers are treated as one indicator after normalisation.
    """
    if not url or "://" not in url:
        return url
    try:
        p = urlparse(url)
        scheme = p.scheme.lower()
        netloc = p.netloc.lower()
        # Strip the default port for the scheme (never changes site identity).
        if scheme == "http":
            netloc = re.sub(r":80$", "", netloc)
        elif scheme == "https":
            netloc = re.sub(r":443$", "", netloc)
        # Drop every query parameter whose key is a known tracking-only param;
        # preserve all others in their original order.
        qs = [
            (k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
            if k.lower() not in _TRACKING_PARAMS
        ]
        # Drop the fragment — server-side reputation lookups never need it.
        return urlunparse((scheme, netloc, p.path, p.params, urlencode(qs), ""))
    except Exception:
        return url


def normalise_urls(urls: list[str]) -> list[str]:
    """Normalise *urls* and deduplicate, preserving the first-seen order.

    Two entries that collapse to the same normalised form after tracking-param
    removal are merged into one — only one provider lookup is made for them.
    """
    seen: dict[str, str] = {}
    for url in urls:
        norm = normalise_url(url)
        if norm not in seen:
            seen[norm] = url
    return list(seen.keys())
