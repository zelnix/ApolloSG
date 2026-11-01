"""What a push notification actually says.

Two jobs, both at the notification boundary only:
1. A purpose-built short summary of a Patrol event ("Higgins: The Instagram link you sent has signs that need
   checking. Open ApolloSG to see what I found.") — never the full Higgins explanation, which stays in the
   Threat Case untouched.
2. present_push(): decode HTML entities (&quot; &amp; &#39; &lt; …) exactly once, tidy whitespace and fit the
   OS limits, just before the text is handed to the relay (Android/iOS). Stored investigations and evidence
   are never altered.

Mirror of frontend src/push/notificationText.ts.
"""
from __future__ import annotations

import html
import re
from typing import Any

def decode_entities(text: str) -> str:
    """One pass: "&amp;quot;" becomes "&quot;", never '"'."""
    return html.unescape(text)


def _present(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    return re.sub(r"\s+", " ", decode_entities(text)).strip()


def present_push(data: dict) -> dict:
    """The push presentation boundary — applied once, in send_push, to every notification. Every line a person reads
    goes through Higgins Luddish here (the title as a headline), so no notification, whoever composed it, reaches the
    phone in other words than the app's. Nothing is cut short: only the OS's own display limit shortens it."""
    from services.higgins.luddish import luddish_text
    out = dict(data)
    for key in ("title", "message", "subtext"):
        if key in out:
            shown = _present(out[key])
            out[key] = luddish_text(shown, key == "title") if isinstance(shown, str) else shown
    return out


# ── The short summary ────────────────────────────────────────────────────────

_NOUN = {"link": "link", "website": "website", "connection": "website", "known_threat": "website", "message": "text",
         "email": "email", "call": "call", "app": "app", "file": "file", "account": "account alert"}
_SENT_TO_CHECK = {"link", "message", "email", "file"}
_RECEIVED = {"message", "email"}
_SITES = {"website", "connection", "known_threat"}
_OPEN = "Open ApolloSG to see what I found."
_OPEN_IN_SENTENCE = "open ApolloSG to see what I found."
# Lines a record carries that say how it was kept or checked, never what was found (frontend luddish/present.ts).
_NOT_A_REASON = {
    "Apollo checked this again under its updated rules, using the original kept on this device.",
    "ApolloSG's servers keep only this privacy-protected summary, not the content that was checked.",
    "The investigation is still running.",
}


def _named(value: Any) -> str:
    """A recorded identifier, whole."""
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""


def _host(value: Any) -> str:
    raw = _named(value)
    host = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", raw).split("/")[0].split("?")[0].split("#")[0]
    host = re.sub(r":\d+$", "", re.sub(r"^www\.", "", host, flags=re.I))
    return host.lower() if re.fullmatch(r"[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", host) else ""


def notification_subject(event: Any, source: dict | None = None) -> str:
    """"The Instagram link you sent", "The email from billing@acme.co", "The call from +61 412 345 678" — from recorded
    identifiers only, never guessed. Mirror of frontend notificationSubject."""
    category = event.category
    noun = _NOUN.get(category, "item")
    source = source or {}
    brand, sender = _named(event.claimed_brand), _named(source.get("sender"))
    if event.background:
        yours = " you received" if category in _RECEIVED else ""
    else:
        yours = " you sent" if category in _SENT_TO_CHECK else ""
    if category == "call":
        caller = _named(getattr(event, "local_indicator", None)) or sender
        return f"The call from {caller}" if caller else f"The {brand} call" if brand else "The call"
    if brand:
        return f"The {brand} {noun}{yours}"
    if category in _RECEIVED and sender:
        return f"The {noun} from {sender}"
    if category == "file":
        file = next((_named(n) for n in source.get("attachment_names") or [] if _named(n)), "")
        if file:
            return f"The file {file}"
    host = _host(source.get("url") or getattr(event, "local_indicator", None) or event.indicator_host)
    if host and category == "link":
        return f"The {host} link{yours}"
    if host and category in _SITES:
        return f"The website {host}"
    return f"The {noun}{yours}"


def _reason(event: Any) -> str:
    """The first concrete thing Apollo recorded about the event — a rule it met, a finding — or nothing."""
    return next((w.strip() for w in event.why or [] if w.strip() and w.strip() not in _NOT_A_REASON), "")


# The ordinary words a reason starts with; anything else (a name: "PhishTank lists …") keeps its capital in a sentence.
_ORDINARY_START = re.compile(r"(?:The|This|That|These|Those|A|An|It|Its|Their|There|One|Some|No|Nothing|Someone|Asks|Uses|Claims|Says"
                             r"|Contains|Links|Sends|Comes|Pretends|Wants|Mentions|Offers|Promises|Threatens|Requests|Tells|Gives"
                             r"|Points|Goes|Leads|Looks|Has|Is|Was|Matches|Names|Shows|Appears)\b")


def _in_sentence(reason: str) -> str:
    """A reason inside a sentence: no closing stop, first word lower-cased only when it is an ordinary word, never a
    name. Mirror of frontend luddish/present.ts reasonInSentence."""
    r = re.sub(r"[.!?…]+$", "", reason).strip()
    return r[0].lower() + r[1:] if _ORDINARY_START.match(r) else r


def _composed(event: Any, briefing: Any, source: dict | None) -> str:
    """Mirror of frontend notificationText composed(): the briefing's first finding, else the subject, the recorded state
    and the first concrete thing Apollo recorded."""
    if briefing is not None and briefing.headline and briefing.summary:
        from services.higgins.luddish import hold, restore
        held, kept = hold(briefing.summary)
        first = restore((re.split(r"(?<=[.!?])\s", held.strip()) or [held])[0], kept).strip()
        needs = briefing.user_action_required and (briefing.action_reason or "").strip() and event.status not in ("resolved", "trusted")
        return f"Higgins: {first}{' This needs your decision.' if needs else ''} {_OPEN}"
    subject = notification_subject(event, source)
    in_sentence = re.sub(r"^The ", "the ", subject)
    reason = _reason(event)
    because = f": {_in_sentence(reason)}" if reason else ""
    if event.state == "biting":
        return f"Higgins: Apollo blocked {in_sentence}. {_OPEN}"
    if event.state == "barking":
        return f"Higgins: {subject} looks like a scam{because}. Don't act on it — {_OPEN_IN_SENTENCE}"
    if event.state == "growling":
        return f"Higgins: {subject} has {'a warning sign' if reason else 'signs that need checking'}{because}. {_OPEN}"
    if ((event.triage_investigation or {}).get("outcome")) == "LIMITED_UNABLE_TO_DETERMINE":
        return f"Higgins: I couldn't fully check {in_sentence}{because}. Treat it with caution — {_OPEN_IN_SENTENCE}"
    return f"Higgins: {subject} needs a closer look{because}. {_OPEN}"


def owner_alert_summary(event: Any, *, briefing: Any = None, source: dict | None = None) -> str:
    """The push's words, in the same Higgins Luddish the app uses (services/higgins/luddish.py)."""
    from services.higgins.luddish import luddish_text
    return luddish_text(_composed(event, briefing, source))
