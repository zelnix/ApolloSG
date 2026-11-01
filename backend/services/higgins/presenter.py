"""Deterministic Higgins presentation — Higgins may change presentation, never meaning.

Every answer here is assembled from structured fields that TC FlyBy, Magnum DI, Patrol, the device or Apollo's
product knowledge already established, using fixed mappings and templates. No AI is called. When the
record doesn't hold the answer, Higgins says so instead of inferring one.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from services.higgins import app_knowledge, outcomes
from services.higgins.explain import words as W
from services.higgins.knowledge import terms

# The follow-up's verdict, why, findings and what isn't certain come from the case's Higgins Case Briefing — the one
# authoritative presentation of the result — and, for an older result recorded before briefings, from the result's
# own recorded fields. Nothing here decides or rewords a verdict.
STATE_TEXT = {"resting": "no concern found within the checks that completed", "sniffing": "Apollo is looking closer", "ears_up": "worth a look", "growling": "possible concern",
              "barking": "significant concern", "biting": "Apollo blocked it", "unknown": "state not known"}
SEVERITY_TEXT = {"EXTREME": "Extreme", "HIGH": "High", "MODERATE": "Moderate", "LOW": "Low"}

OUT_OF_SCOPE = ("I specialise in helping you stay safe from scams and cyber threats through ApolloSG. For that question, a general "
                "assistant would be a better fit. Is there anything security-related I can help with?")

NOT_IN_TRUSTED_KNOWLEDGE = ("ApolloSG's trusted knowledge doesn't cover that question yet, so I won't guess at an answer. "
                            "If it's about something you've received — a message, link, email, call, app or file — tap + and add it, "
                            "and Apollo's investigators will check it. Learn with Higgins has guides on the common scams.")


def not_in_trusted_knowledge() -> dict:
    """Nothing Apollo holds answers the question: said plainly, with no AI-written answer in its place."""
    return {"answer": NOT_IN_TRUSTED_KNOWLEDGE, "navigate": ["/higgins/learning"], "limitation": True}

_FOLLOW_UP_INTENTS: list[tuple[str, re.Pattern]] = [(name, re.compile(pattern, re.I)) for name, pattern in [
    ("recheck", r"\bre-?check|\bfresh (?:observation|reading)|\bre-?assess|\bcheck (?:it |this |that )?again\b"),
    ("not_established", r"\b(?:wasn'?t|not|never|couldn'?t|didn'?t)\s+(?:established|found|checked|confirmed|able|cover(?:ed)?|look(?:ed)?)\b|\bunknown\b|\buncertain"
                        r"|\blimitations?\b|\bmissing\b|\bgaps?\b|\bscope\b|what (?:don'?t|didn'?t) (?:you|we|it) know"),
    ("sources", r"\bsources?\b|where did (?:this|that|the|you|it)\b.*\b(?:come from|get)|\breferences?\b|\bcitations?\b|\blinks?\b"),
    ("evidence", r"\bevidence\b|\bproof\b|\bsupport(?:s|ed|ing)?\b|\bbased on\b|how do (?:you|we) know|what shows"),
    ("confidence", r"\bconfiden|\bsure\b|\bcertain(?:ty)?\b|how likely|how accurate|\breliable\b"),
    ("watch", r"watch (?:out )?for|look out|warning signs|red flags|\bsigns\b|be careful of|what to look"),
    ("why", r"\bwhy\b|\bsuspicious\b|what makes|what'?s wrong"),
    ("meaning", r"mean(?:s)? for me|what does (?:this|it|that) mean|\bworr|am i (?:safe|at risk|ok)|is (?:this|it|that) (?:safe|a scam|dangerous|legit|real|ok)"),
    ("actions", r"what (?:should|can|do) i do|next steps?|what now|what next|how do i (?:fix|stop|protect)|\brecommend|\bshould i\b|\bactions?\b"),
    ("findings", r"what did (?:you|magnum(?: di)?|it|apollo) find|\bfindings?\b|what was found|\bsummar|\boverview\b|tell me (?:more|about)|\bexplain\b|what happened"),
]]
_WATCH_WORDS = re.compile(r"\b(watch|look out|be wary|be careful|beware|signs?|suspicious|unexpected)\b", re.I)


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"• {line}" for line in lines if line)


def follow_up_intent(question: str) -> Optional[str]:
    return next((name for name, pattern in _FOLLOW_UP_INTENTS if pattern.search(question or "")), None)


# Something new in a follow-up: a link, an email address or a phone number the finished investigation never saw.
_NEW_ITEMS: list[tuple[str, re.Pattern]] = [
    ("an email address", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("a link", re.compile(r"\bhttps?://\S+|\bwww\.\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|info|biz|io|app|xyz|top|online|site|shop|link|co|au|uk|nz)(?:/\S*)?\b", re.I)),
    ("a phone number", re.compile(r"(?<![\w.])\+?\d[\d ()-]{6,}\d(?![\w.])")),
]
NEW_ITEM_NOTE = ("You've mentioned something new ({items}) that wasn't part of this investigation. ApolloSG doesn't reopen a finished investigation, "
                 "so its findings don't cover it and nothing new has been checked. To have it checked, start a new check.")


def new_items(question: str) -> list[str]:
    """The kinds of new material a follow-up mentions, in a fixed order. Emails are removed before links are looked for."""
    text = question or ""
    found: list[str] = []
    for label, pattern in _NEW_ITEMS:
        hits = [m.group(0) for m in pattern.finditer(text)]
        if label == "a phone number":
            hits = [h for h in hits if sum(ch.isdigit() for ch in h) >= 8]
        if hits:
            found.append(label)
            text = pattern.sub(" ", text)
    return found


def _join(labels: list[str]) -> str:
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


def is_finished(response: Optional[dict[str, Any]]) -> bool:
    """An investigation result (TC FlyBy's or Magnum DI's) that is complete or partial — not one still waiting for the person's answer."""
    return bool(response) and response.get("completion") in ("complete", "partial") and not response.get("question")


def _briefing(response: dict[str, Any]) -> dict[str, Any]:
    """The result's Higgins Case Briefing when it passed its Fidelity Check; {} for a result without one."""
    briefing = response.get("briefing") or {}
    return briefing if (briefing.get("fidelity") or {}).get("status") == "PASS" else {}


def investigation_follow_up(response: dict[str, Any], sources: list[dict[str, Any]], question: str, answered_by: Optional[str] = None) -> dict[str, Any]:
    """Answer a follow-up from a completed investigation result (camelCase wire shape), credited to whichever
    investigator settled it (`answered_by`). Never infers.

    A follow-up never reaches an AI model, even when it brings something new: the new item is named as
    not covered, and the answer comes only from what the finished investigation recorded.
    """
    name = outcomes.investigator(answered_by)
    briefing = _briefing(response)
    overview = str(response.get("overview") or "").strip()
    status = briefing.get("status") or outcomes.LABELS.get(str(response.get("outcome") or ""), "")
    reason = str(briefing.get("statusReason") or response.get("attentionReason") or "").strip()
    verdict = " ".join(p for p in [f"{status}." if status else "", "" if reason and reason in overview else reason] if p)
    shown = {f.get("id"): f.get("finding") for f in briefing.get("findings") or []}
    findings = [{**f, "text": shown.get(f.get("id")) or f.get("text")} for f in response.get("findings") or [] if str(f.get("text") or "").strip()]
    actions = [a for a in response.get("actions") or [] if str(a.get("instruction") or a.get("label") or "").strip()]
    recommended = response.get("recommendedActionId")
    actions.sort(key=lambda a: a.get("id") != recommended)
    uncertainties = [str(u).strip() for u in briefing.get("unresolved") or response.get("uncertainties") or [] if str(u).strip()]
    scope = str(response.get("scope") or "").strip()
    by_source = {s.get("id"): s for s in sources}
    intent = follow_up_intent(question)
    limitation = False

    def finding_line(f: dict, *, detail: bool = False) -> str:
        known = f.get("basis") in W.BASIS and f.get("confidence") in W.CONFIDENCE
        line = f"{f['text']} ({W.detail(f['basis'], f['confidence'], name) if known else 'basis not recorded'}"
        if detail:
            count = len(f.get("evidenceIds") or [])
            titles = [by_source[i].get("title") for i in f.get("sourceIds") or [] if by_source.get(i, {}).get("title")]
            line += f"; {count} evidence item{'s' if count != 1 else ''}" if count else "; no evidence item cited"
            line += f"; source: {', '.join(titles)}" if titles else ""
        return line + ")"

    if intent == "recheck":
        answer = (f"{name}'s investigation is finished, so it isn't re-assessed — any fresh reading Apollo took is shown with the action, "
                  "and what the investigation established is unchanged.") + (f"\n\n{overview}" if overview else "")
    elif intent == "meaning":
        answer = "\n\n".join(part for part in [overview, verdict] if part)
    elif intent == "why":
        answer = "\n\n".join(part for part in [reason or verdict, f"What {name} found:\n" + _bullets([finding_line(f) for f in findings]) if findings else ""] if part)
        if not findings and not reason:
            answer, limitation = f"{name}'s investigation doesn't record specific reasons beyond its overall result. " + overview, True
    elif intent == "evidence":
        answer = ("Each finding and what supports it:\n" + _bullets([finding_line(f, detail=True) for f in findings])) if findings else \
            f"{name} didn't record individual findings with supporting evidence for this investigation."
        limitation = not findings
    elif intent == "confidence":
        counts = {level: sum(1 for f in findings if f.get("confidence") == level) for level in ("high", "medium", "low")}
        parts = [f"Overall: {status}." if status else "",
                 "Confidence in the findings: " + ", ".join(f"{n} {level}" for level, n in counts.items() if n) if findings else "",
                 "What it couldn't establish:\n" + _bullets(uncertainties) if uncertainties else ""]
        answer = "\n\n".join(p for p in parts if p) or f"{name} didn't record a confidence level for this investigation."
    elif intent == "watch":
        watch = [a.get("instruction") or a.get("label") for a in actions if _WATCH_WORDS.search(f"{a.get('label', '')} {a.get('instruction', '')}")]
        if watch:
            answer = f"What {name} says to look out for:\n" + _bullets(watch)
        else:
            answer, limitation = f"{name}'s investigation doesn't list specific warning signs to watch for.", True
            if actions:
                answer += " What it does recommend:\n" + _bullets([f"{a.get('label')}: {a.get('instruction')}" for a in actions])
    elif intent == "actions":
        answer = (f"What {name} recommends:\n" + _bullets([f"{a.get('label')}: {a.get('instruction')}" if a.get("label") else a.get("instruction") for a in actions])) \
            if actions else f"{name} didn't recommend any action for this."
    elif intent == "not_established":
        answer = "\n\n".join(p for p in [f"What {name} couldn't establish:\n" + _bullets(uncertainties) if uncertainties else
                                          f"{name} didn't record anything it was unable to establish.",
                                          f"What it checked: {scope}" if scope else ""] if p)
    elif intent == "sources":
        listed = [f"{s.get('title') or s.get('url')} — {s.get('url')} ({s.get('authority', 'unknown')} source)" for s in sources if s.get("url")]
        answer = (f"The sources {name} used:\n" + _bullets(listed)) if listed else \
            f"{name} didn't use any outside sources for this; its findings come from the evidence you submitted."
    elif intent == "findings":
        answer = "\n\n".join(p for p in [overview, "Findings:\n" + _bullets([finding_line(f) for f in findings]) if findings else ""] if p)
    else:
        limitation = True
        answer = (f"I can only answer from what {name}'s investigation established, and it doesn't answer that directly."
                  + (f" Here's what it did establish: {overview}" if overview else ""))
    mentioned = new_items(question)
    if mentioned:
        answer = NEW_ITEM_NOTE.format(items=_join(mentioned)) + "\n\n" + answer.strip()
    return {"answer": answer.strip(), "intent": intent or "unanswered", "limitation": limitation, "newItems": mentioned}


def stopped_follow_up(reason: Optional[str], established: list[str]) -> dict[str, Any]:
    """A follow-up on a case whose one Magnum DI call didn't produce a result: why it stopped, and what TC FlyBy
    established, word for word. No investigation is reopened and nothing is inferred."""
    parts = [reason or "Magnum DI's one call for this case didn't produce a result, so there is no finished investigation to answer from.",
             ("What TC FlyBy established:\n" + _bullets(established)) if established else "TC FlyBy didn't establish anything specific before that."]
    return {"answer": "\n\n".join(parts).strip(), "intent": "unanswered", "limitation": True, "newItems": []}



# ── Device / Apollo state ─────────────────────────────────────────────────────

_DEVICE_INTENTS: list[tuple[str, re.Pattern]] = [(name, re.compile(pattern, re.I)) for name, pattern in [
    ("permissions", r"\bpermission"),
    ("device_protections", r"\b(?:built[- ]in|device|phone|android|ios|iphone|samsung|google|apple)(?:'s)?\s+(?:own\s+)?(?:protection|security)|play protect|what does my (?:phone|device) protect"),
    ("capabilities", r"\bcapabilit|what can apollo (?:see|use|access|read)|allowed to (?:use|read|see)"),
    ("settings", r"settings? (?:should|to) (?:i )?(?:turn on|check|change)|recommended settings|what should i turn on"),
    ("threats", r"\bthreats?\b|\bissues?\b|\bproblems?\b|\bwarnings?\b|what'?s wrong|needs? attention|(?:barking|growling)"),
    ("network", r"\bwi-?fi\b|\bnetwork\b|\binternet\b|\bconnection\b|\bvpn\b"),
    ("calls", r"call screen|caller id|screen(?:ing)? (?:my )?calls"),
    ("email", r"email accounts?|\bgmail\b|\bmailbox"),
    ("alerts", r"\bnotifications?\b|quiet hours|\balerts? (?:on|off|working)"),
    ("protection", r"\bprotect(?:ed|ion|ions|ing)?\b|\bsafe\b|\bsecure\b|\bstatus\b|\brunning\b|\bgates?\b"),
]]


def device_intent(question: str) -> Optional[str]:
    return next((name for name, pattern in _DEVICE_INTENTS if pattern.search(question or "")), None)


def _named_lines(s: Any, question: str) -> list[str]:
    """Protections and capabilities the question names, exactly as the phone reports them."""
    asked = (question or "").lower()
    quoted = [q.strip().lower() for q in re.findall(r"[“\"]([^”\"]{3,80})[”\"]", question or "")]
    lines = [f"{g.title}: {g.status}" + ("" if g.automatic else " (manual checks only)") for g in s.gates if len(g.title) >= 3 and g.title.lower() in asked]
    for line in [*s.capabilities, *s.device_protections, *s.recommended_settings]:
        label = re.split(r"\s+—\s+|:\s", line, maxsplit=1)[0].strip().lower()
        if (len(label) >= 4 and label in asked) or any(q and q in line.lower() for q in quoted):
            if line not in lines:
                lines.append(line)
    return lines


def device_state(snapshot: Any, question: str, intent: Optional[str] = None, *, about_phone: bool = False) -> Optional[dict[str, Any]]:
    """Answer from the phone's live, authoritative reading. None when the question isn't about device state.

    A question about this phone always gets an answer from the reading — the protections or capabilities it
    names, the topic it asks about, or the full reading — never an inferred one.
    """
    intent = intent or device_intent(question)
    named = _named_lines(snapshot, question) if snapshot is not None else []
    if not intent and not named and not about_phone:
        return None
    if snapshot is None:
        return {"answer": "I don't have a live reading from this phone in this conversation, so I can't tell you its current state. "
                          "Open Your protections to see it.", "navigate": ["/(tabs)/guard"], "limitation": True}
    s = snapshot
    when = f" (read {s.checked_at})" if s.checked_at else ""
    missing = "ApolloSG doesn't have a reading for that on this phone."
    lines: list[str] = []
    navigate: list[str] = []
    if named:
        lines = ["What this phone reports for what you asked about:\n" + _bullets(named),
                 *(["Open right now:\n" + _bullets(s.open_threats)] if s.open_threats else [])]
        navigate = ["/(tabs)/guard", "/device-protection"]
    elif intent == "permissions":
        lines = ["Permissions on this phone:\n" + _bullets(s.permissions)] if s.permissions else [missing]
    elif intent == "device_protections":
        lines = ["Protection built into this device (provided by the device maker or operating system, not by ApolloSG):\n" + _bullets(s.device_protections)] \
            if s.device_protections else [missing]
        navigate = ["/device-protection"]
    elif intent == "capabilities":
        lines = [p for p in [s.capability_summary or "", "What ApolloSG is allowed to use:\n" + _bullets(s.capabilities) if s.capabilities else ""] if p] or [missing]
        navigate = ["/device-protection"]
    elif intent == "settings":
        lines = ["Apollo can't read these settings, so please check them yourself:\n" + _bullets(s.recommended_settings)] if s.recommended_settings else [missing]
        navigate = ["/device-protection"]
    elif intent == "threats":
        lines = [p for p in ["Threats recorded: " + "; ".join(s.threat_counts) if s.threat_counts else "",
                             "Open right now:\n" + _bullets(s.open_threats) if s.open_threats else "No threats are open on this phone right now."] if p]
        navigate = ["/(tabs)/patrol"]
    elif intent == "network":
        lines = [f"Internet connection: {s.network}"] if s.network else [missing]
        navigate = ["/network"]
    elif intent == "calls":
        lines = [f"Call screening: {s.call_screener}"] if s.call_screener else [missing]
        navigate = ["/call-guard"]
    elif intent == "email":
        lines = [f"Email accounts: {s.email_accounts}"] if s.email_accounts else [missing]
        navigate = ["/settings/email-accounts"]
    elif intent == "alerts":
        lines = [p for p in [f"Security alerts: {s.alerts}" if s.alerts else "", f"Quiet hours: {s.quiet_hours}" if s.quiet_hours else ""] if p] or [missing]
        navigate = ["/notification-check"]
    if not lines or (lines == [missing] and about_phone and intent != "protection"):
        # The protection overview — also what a question about this phone gets when its topic has no reading.
        switched = "" if s.protection_on is None else ("Apollo protection is switched on." if s.protection_on else "Apollo protection is switched off.")
        gates = [f"{g.title}: {g.status}" + ("" if g.automatic else " (manual checks only)") for g in s.gates]
        lines = [p for p in [switched, "Your protections:\n" + _bullets(gates) if gates else "",
                             "Open right now:\n" + _bullets(s.open_threats) if s.open_threats else "",
                             "Apollo can't read these settings, so please check them yourself:\n" + _bullets(s.recommended_settings) if s.recommended_settings else "",
                             *s.notes] if p] or [missing]
        navigate = ["/(tabs)/guard"]
    return {"answer": f"Here's what Apollo reads on this phone right now{when}:\n\n" + "\n\n".join(lines), "navigate": navigate,
            "limitation": lines == [missing]}


# ── Patrol, investigations, scam alerts ───────────────────────────────────────

def patrol_findings(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {"answer": "ApolloSG has no recent findings recorded for this device.", "navigate": ["/(tabs)/patrol"], "limitation": False}
    lines = []
    for item in items[:5]:
        line = f"{item.get('headline') or 'Finding'} — {STATE_TEXT.get(item.get('effectiveState'), item.get('effectiveState') or 'state not known')}."
        if item.get("evidence_availability") == "summary_only":
            line += " ApolloSG holds only a privacy-protected summary of this one."
        elif item.get("summary"):
            line += f" {item['summary']}"
        lines.append(line)
    return {"answer": "Apollo's most recent findings:\n" + _bullets(lines), "navigate": ["/(tabs)/patrol"], "limitation": False}


def patrol_record(item: dict[str, Any]) -> dict[str, Any]:
    """One Patrol finding, explained from its own record: what Apollo saw, its state, and what it confirmed."""
    state = STATE_TEXT.get(item.get("effectiveState"), item.get("effectiveState") or "state not known")
    parts = [f"{item.get('headline') or 'This finding'} — {state}."]
    if item.get("evidence_availability") == "summary_only":
        parts.append("ApolloSG holds only a privacy-protected summary of this finding — the kind of check and its result — so I can't explain more than its state.")
    elif item.get("summary"):
        parts.append(f"What Apollo recorded:\n{item['summary']}")
    facts = item.get("structuredFacts") or {}
    if facts.get("indicatorHost"):
        parts.append(f"Where: {facts['indicatorHost']}")
    if facts.get("claimedBrand"):
        parts.append(f"Who it claimed to be: {facts['claimedBrand']}")
    parts.append("Apollo confirmed it blocked this." if item.get("observedBlockReference") else "Apollo hasn't confirmed a block for this one.")
    return {"answer": "Here's what Apollo recorded about this finding:\n\n" + "\n\n".join(parts), "navigate": ["/(tabs)/patrol"], "limitation": False}


def recent_investigations(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {"answer": "You don't have any recent investigations on this device.", "navigate": ["/saved-reports"], "limitation": False}
    lines = [f"{(item.get('gates') or ['Apollo'])[0].title()} check ({item.get('status')}): {item.get('summary')}" for item in items[:5]]
    return {"answer": "Your recent investigations, in the investigators' own words:\n" + _bullets(lines), "navigate": ["/saved-reports"], "limitation": False}


def scam_alerts(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    if not alerts:
        return {"answer": "There are no current official scam alerts from the government sources ApolloSG follows.", "navigate": ["/(tabs)/scams"],
                "limitation": False, "sources": []}
    lines = [f"{a['title']} — {a['source']}, {a.get('dateLabel') or 'date not stated'}. Urgency: {SEVERITY_TEXT.get(a.get('severity'), 'not rated')}."
             for a in alerts[:5]]
    return {"answer": "The latest official scam alerts:\n" + _bullets(lines), "navigate": ["/(tabs)/scams"], "limitation": False,
            "sources": [{"title": a["title"], "publisher": a["source"], "url": a["url"], "route": None, "licence": None} for a in alerts[:5]]}


def scam_alert_explanation(alert: dict[str, Any]) -> dict[str, Any]:
    """One alert, section by section, in the source's own words. Empty sections say so."""
    h = alert.get("higgins") or {}
    not_said = "The source doesn't say."
    parts = [f"“{alert['title']}” — {alert['source']}, {alert.get('dateLabel') or 'date not stated'}.",
             f"What happened:\n{h.get('whatHappened') or not_said}",
             f"Where:\n{h.get('whereHappening') or not_said}",
             f"What to watch for:\n{h.get('whatToWatch') or not_said}",
             f"What to do:\n{h.get('whatToDo') or not_said}",
             f"Urgency: {SEVERITY_TEXT.get(alert.get('severity'), 'not rated')}. {alert.get('severityReason') or ''}".strip()]
    return {"answer": "\n\n".join(parts), "navigate": [], "limitation": False,
            "sources": [{"title": alert["title"], "publisher": alert["source"], "url": alert["url"], "route": None, "licence": None}]}


def scam_alert_card(title: str, source: str, summary: str, url: str) -> dict[str, Any]:
    """An alert Apollo no longer holds the full record for: only what the card itself carried, and where to read the rest."""
    parts = [f"“{title}”" + (f" — {source}." if source else "."),
             f"What the source says:\n{summary}" if summary else "The alert card didn't include the source's summary.",
             "ApolloSG doesn't hold the rest of this alert right now, so I won't add to it."
             + (" The full details are on the official page." if url else "")]
    sources = [{"title": title, "publisher": source or "Official source", "url": url, "route": None, "licence": None}] if url else []
    return {"answer": "\n\n".join(parts), "navigate": ["/(tabs)/scams"], "limitation": not summary, "sources": sources}


def learn_article(article: dict[str, Any], max_chars: int = 1800) -> dict[str, Any]:
    """A Learn with Higgins article — answer the question using the article’s own words, without metadata."""
    blocks: list[str] = []
    if article.get("summary"):
        blocks.append(article["summary"])
    used = sum(len(b) for b in blocks)
    for section in article.get("sections") or []:
        lines = [f"**{section['heading']}**"] if section.get("heading") else []
        lines += [str(p) for p in section.get("paragraphs") or []] + [f"• {b}" for b in section.get("bullets") or []]
        text = "\n".join(lines).strip()
        if not text or used + len(text) > max_chars:
            break
        blocks.append(text)
        used += len(text)
    sources = [{"title": c.get("label") or c["url"], "publisher": "Learn with Higgins source", "url": c["url"], "route": None, "licence": None}
               for c in (article.get("citations") or [])[:3] if c.get("url")]
    return {"answer": "\n\n".join(blocks), "navigate": ["/higgins/learning"], "limitation": False,
            "sources": sources}


# ── Direct Answer First — intent-specific presenters ─────────────────────────
# Source hierarchy:
# 1. Live device/Apollo state — "Is my protection on?"
# 2. ApolloSG User Guide — "How do I use this?"
# 3. Case/investigation evidence — "Why did Apollo flag this?"
# 4. Apollo KB / Learn / Scam Alerts — scam and cybersecurity education.
# 5. Honest limitation — if Apollo does not know.
#
# A product-use question must not fall through to the scam/cybersecurity KB
# simply because the User Guide did not match it.

from services.higgins import user_guide

_SHARE_TROUBLE = re.compile(r"(?i)\b(?:isn'?t|not|doesn'?t|can'?t|cannot|missing|won'?t)\b")


def sharing_help(question: str) -> dict[str, Any]:
    """Sharing into ApolloSG, from the User Guide: the procedure, or what to do when ApolloSG isn't in the Share menu."""
    topic = "share-missing" if _SHARE_TROUBLE.search(question or "") else "share-into"
    return user_guide.topic_reply(user_guide.TOPIC_BY_ID[topic])


# ── Apollo product knowledge (refactored: select minimum facts, not whole modules) ──

_PRODUCT_TOPICS = {"privacy": "privacy", "flows": "flows", "call_screening": "call_screening", "settings_detail": "settings_detail"}
_HIGGINS_ONLY = re.compile(r"\s*[—-]?\s*(?:never offer[^.]*|Say this plainly; never imply parity|\(state accurately\))\.?", re.I)


def _display(module_text: str) -> tuple[str, list[str]]:
    """Product knowledge as the person should read it: heading and instructions-to-Higgins removed, routes as links."""
    routes = [r for r in re.findall(r"`([^`]+)`", module_text) if app_knowledge.valid_route(r)]
    body = "\n".join(module_text.splitlines()[1:])
    body = re.sub(r"\s*`[^`]+`", "", body)
    body = _HIGGINS_ONLY.sub("", body)
    return body.strip(), routes


def product_knowledge(question: str, modules: list[str], *, intent_label: str = "") -> Optional[dict[str, Any]]:
    """Apollo's own product knowledge — selects minimum relevant facts, not whole modules.

    Source hierarchy:
    1. Intent-specific presenters (sharing_help, etc.)
    2. ApolloSG User Guide (structured task lookup)
    3. Legacy knowledge modules (minimum relevant facts)
    4. Route matching

    Direct Answer First: the first paragraph independently answers the question.
    A keyword match never means 'display this whole module.'
    """
    # 1. Intent-specific presenters
    if intent_label == "sharing_help":
        return sharing_help(question)

    # 2. ApolloSG User Guide — structured task lookup
    guide_result = user_guide.guide_answer(question)
    if guide_result:
        return guide_result

    # 3. Legacy knowledge modules — minimum relevant facts
    blocks: list[str] = []
    navigate: list[str] = []

    # Select minimum relevant facts from each module
    for module in modules:
        text = app_knowledge.KNOWLEDGE_MODULES.get(module)
        if not text:
            continue
        body, routes = _display(text)
        # Extract only the bullet points that are relevant to the question
        relevant_lines = _select_relevant_lines(body, question)
        if relevant_lines:
            blocks.append(relevant_lines)
            navigate.extend(r for r in routes if r not in navigate)
        elif not blocks:
            # Fallback: if no specific lines matched, include a brief excerpt
            lines = [line.strip() for line in body.split("\n") if line.strip() and line.strip().startswith("-")]
            if lines:
                blocks.append("\n".join(lines[:3]))  # max 3 most relevant bullets
                navigate.extend(r for r in routes if r not in navigate)

    # Route matching — select relevant destinations
    query_terms = terms(question)
    scored = []
    for group in app_knowledge.ROUTE_GROUPS.values():
        for route, description in group.items():
            have = set(terms(description))
            cover = sum(1 for t in query_terms if t in have) / len(query_terms) if query_terms else 0
            if cover >= 0.5:
                scored.append((cover, route, description))
    scored.sort(key=lambda item: -item[0])
    places = []
    for _cover, route, description in scored:
        if route not in [p[0] for p in places]:
            places.append((route, description))
        if len(places) == 2:
            break
    if places:
        blocks.append("You can do that here:\n" + _bullets([description for _route, description in places]))
        navigate = [route for route, _d in places] + [r for r in navigate if r not in [p[0] for p in places]]
    if not blocks:
        return None

    # Response-size guard: procedural answers should be 2-6 sentences
    answer = "\n\n".join(blocks)
    return {"answer": answer, "navigate": navigate[:2], "limitation": False}


def _select_relevant_lines(body: str, question: str) -> str:
    """Select only the bullet points from a knowledge module that are relevant to the question.
    Returns the relevant lines as a string, or empty string if nothing is specifically relevant."""
    q_lower = (question or "").lower()
    q_terms = set(terms(question))
    lines = [line.strip() for line in body.split("\n") if line.strip()]
    relevant = []
    for line in lines:
        line_terms = set(terms(line))
        # A line is relevant if it shares multiple terms with the question
        overlap = q_terms & line_terms
        if len(overlap) >= 2 or any(t in line.lower() for t in q_lower.split() if len(t) > 4):
            relevant.append(line)
    # Keep it concise — max 4 relevant lines
    return "\n".join(relevant[:4])
