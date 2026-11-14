"""Check completeness — Apollo never presents an incomplete examination as a complete one.

An incomplete check is one Apollo needed but couldn't finish: a reputation source that didn't answer, a link whose
final destination couldn't be verified, a number scored only from an earlier lookup. It is recorded as
{check, status, failure, detail, source}. When no rule is met and some check is incomplete, the result is
"No threat found by available checks" — not Limited, and never the unqualified "No threat identified".
The wording follows the kind of check and how it failed, never the provider. Mirror:
frontend/src/domain/triage/completeness.ts. Words: content/triage_catalogue.json "completeness".
"""
from __future__ import annotations

from typing import Optional
import re
from urllib.parse import urlsplit

from services.triage.catalogue import CATALOGUE

_WORDS: dict = CATALOGUE["completeness"]
AVAILABLE_CHECKS: str = _WORDS["availableChecksLabel"]


def service_function(source: str | None, check: str) -> str:
    norm = lambda text: re.sub(r"[^a-z0-9]", "", text.lower())
    for service in _WORDS["serviceFunctions"]:
        if source and any(norm(source) == norm(alias) for alias in [service["name"], *service["aliases"]]):
            return service["name"]
    return {"reputation": "Website threat checking", "final_destination": "Link destination checking",
            "sender_authentication": "Email sender authentication", "number_reputation": "Phone number validation",
            "domain_age": "Website registration checking", "block_proof": "Protection action verification"}.get(check, "External verification")


def plain_service_text(text: str) -> str:
    aliases = [(alias, s["name"]) for s in _WORDS["serviceFunctions"] for alias in s["aliases"]]
    for alias, name in sorted(aliases, key=lambda item: len(item[0]), reverse=True):
        text = re.sub(r"\b" + re.escape(alias) + r"\b", lambda _match, replacement=name: replacement, text, flags=re.I)
    return re.sub(r"\bIP address(es)?\b", lambda m: "internet addresses" if m[1] else "internet address", text, flags=re.I)


def incomplete_check(check: str, failure: Optional[str], *, status: str = "unavailable", detail: str = "",
                     source: Optional[str] = None, at: Optional[str] = None, subject: Optional[str] = None) -> dict:
    """One incomplete check. status: "unavailable" (no answer), "unresolved" (final destination), "stale" (earlier result used)."""
    if subject:
        try:
            subject = urlsplit(subject if "://" in subject else "https://" + subject).hostname or subject
        except ValueError:
            subject = None
    return {"check": check, "status": status, "failure": failure, "detail": detail, "source": source, "at": at,
            **({"subject": subject} if subject else {})}


def incomplete_plain(check: dict) -> str:
    """'Apollo couldn't verify where this link finally leads (the website's address doesn't exist).'"""
    what = _WORDS["checks"].get(check.get("check"), "A check didn't complete")
    why = _WORDS["failures"].get(check.get("failure") or "", "")
    result = (f"{what}: {_WORDS['stale'].format(failure=why or 'no answer')}." if check.get("status") == "stale"
              else f"{what} ({why})." if why else f"{what}.")
    result = plain_service_text(result)
    if check.get("source") or check.get("subject"):
        subject = check.get("subject")
        if subject:
            try:
                subject = urlsplit(subject if "://" in subject else "https://" + subject).hostname or subject
            except ValueError:
                pass
        if check.get("status") == "unavailable":
            return f"{service_function(check.get('source'), check.get('check', ''))}{' for ' + subject if subject else ''} could not be checked{' (' + why + ')' if why else ''}."
        return f"{service_function(check.get('source'), check.get('check', ''))}{' for ' + subject if subject else ''}: {result}"
    return result


def from_sources(sources: list[dict], subject: str | None = None) -> list[dict]:
    """Every source of a reputation answer that didn't complete (status unavailable / not_configured)."""
    return [incomplete_check(s.get("check") or "reputation", s.get("failure"),
                             status="unresolved" if s.get("check") == "final_destination" else "unavailable",
                             detail=s.get("detail") or "", source=s.get("name"), subject=subject)
            for s in sources if s.get("status") in ("unavailable", "not_configured")]
