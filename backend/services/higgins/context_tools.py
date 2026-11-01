"""Deterministic context readers for Higgins chat.

Each reader is an authoritative, owner-scoped, freshness-checked data source.
The readers themselves are unchanged from their original implementation — only the
SELECTION mechanism has changed: context is now chosen deterministically by the
question classifier rather than by asking Gemini to pick tools.

Learn with Higgins article access is added as a new read-only source.
"""
from __future__ import annotations

import re
import logging
from datetime import timedelta
from typing import Awaitable, Callable, Optional

from core.db import db, now_utc
from core.evidence_model import evidence_model
from core.redaction import redact_investigation_secrets
from services import capability_registry, government_alerts
from services import patrol_records, learning
from services.higgins import context as memory
from services.higgins import repository as repo

log = logging.getLogger("apollo.higgins.context")

# What a record holding only the server's privacy-protected summary can say. Never where another copy might be:
# every Threat Case belongs to the device that detected it.
SUMMARY_ONLY = ("ApolloSG holds only a privacy-protected summary of this check: the kind of check and its result, "
                "not the content that was checked.")


# ── Authoritative context readers (unchanged) ────────────────────────────────

def _result(items: list[dict], provenance: list[str], *, observed_at=None, confidence: str = "high") -> dict:
    now = now_utc(); fresh = observed_at or now
    return {"status": "ok" if items else "none_found", "items": items, "provenance": provenance,
            "observedAt": fresh.isoformat() if hasattr(fresh, "isoformat") else str(fresh),
            "freshThrough": (now + timedelta(minutes=15)).isoformat(), "confidence": confidence,
            "note": "No matching owner-scoped record was found." if not items else "Secrets and raw evidence are excluded."}


async def protection(owner: str) -> dict:
    items = [item for item in await memory.current(owner) if item.category == "protection_state"][:3]
    return _result([{"summary": item.summary, "observedAt": item.observed_at.isoformat()} for item in items], ["device_observation"], observed_at=items[0].observed_at if items else None)


async def recent_cases(owner: str) -> dict:
    rows = await db.investigation_cases.find({"owner_id": owner, "deleted": False}, {"_id": 0, "case_id": 1, "status": 1, "gates": 1, "updated_at": 1, "accepted_commits": 1}).sort("updated_at", -1).limit(5).to_list(5)
    items = []
    for row in rows:
        turns = await repo.accepted_turns(owner, row); latest = max(turns, key=lambda turn: turn.committed_at) if turns else None
        items.append({"caseId": row["case_id"], "status": row["status"], "gates": row.get("gates", []), "updatedAt": row["updated_at"].isoformat(),
                      "summary": redact_investigation_secrets(latest.response.overview)[:400] if latest else "No completed answer yet."})
    return _result(items, ["investigation_case_store"], observed_at=rows[0]["updated_at"] if rows else None)


async def patrol(owner: str, *, one: bool = False) -> dict:
    limit = 1 if one else 5
    rows = [row for row in await patrol_records.current(owner, limit + 5) if row["category"] != "system"][:limit]
    items = []
    for row in rows:
        # The separated evidence model (core/evidence_model.py): a privacy summary is said to be one, and the
        # evidence source is only ever what supplied it — never the server that processed it.
        model = evidence_model(row.get("event") or {})
        summary_text = row.get("summary") or ""
        is_projected = model["evidence_representation"] == "privacy_summary" or not summary_text.strip()
        effective_state = row["effectiveState"]
        has_block = row.get("observedBlockReference") is not None
        scenario_ctx = row.get("scenarioContext") or {}
        structured_facts = {
            "category": row["category"],
            "effectiveState": effective_state,
            "verifiedBlock": has_block,
            "indicatorHost": scenario_ctx.get("indicatorHost"),
            "claimedBrand": scenario_ctx.get("claimedBrand"),
            "occurredAt": row["occurredAt"].isoformat() if hasattr(row["occurredAt"], "isoformat") else str(row["occurredAt"]),
        }
        items.append({
            "recordId": row["recordId"], "logicalIssueKey": row["logicalIssueKey"], "category": row["category"],
            "effectiveState": effective_state, "effectiveReason": row["effectiveReason"],
            "headline": redact_investigation_secrets(row["headline"])[:200],
            "summary": redact_investigation_secrets(summary_text)[:400] if not is_projected else SUMMARY_ONLY,
            "evidence_availability": "full" if not is_projected else "summary_only",
            **model,
            "structuredFacts": structured_facts,
            "occurredAt": row["occurredAt"].isoformat() if hasattr(row["occurredAt"], "isoformat") else str(row["occurredAt"]),
            "observedBlockReference": row.get("observedBlockReference"),
        })
    observed = rows[0]["occurredAt"] if rows else None
    return _result(items, ["authoritative_patrol_record_store"], observed_at=observed)


async def saved_reports(owner: str) -> dict:
    """Server-side saved reports have been removed (Stage 11).  Returns empty result.
    The device owns completed investigation records locally."""
    return _result([], ["device_local_storage"], observed_at=None)


async def preferences(owner: str) -> dict:
    items = [item for item in await memory.current(owner) if item.category == "preference"][:10]
    learning_preferences = await db.learning_preferences.find_one({"owner_id": owner}, {"_id": 0, "owner_id": 0})
    values = [{"summary": item.summary, "observedAt": item.observed_at.isoformat()} for item in items]
    if learning_preferences: values.append({"learning": learning_preferences})
    return _result(values, ["owner_preference_store", "learning_preference_store"], observed_at=items[0].observed_at if items else learning_preferences.get("updatedAt") if learning_preferences else None)


async def scams(_owner: str) -> dict:
    value = await government_alerts.snapshot(5)
    items = [{"title": item["title"], "source": item["source"], "region": item.get("regionLabel"),
              "severity": item.get("severity"), "australianRelevance": item.get("australianRelevance"),
              "publishedAt": item["publishedAt"].isoformat() if item.get("publishedAt") else None, "url": item["url"]}
             for item in value["alerts"]]
    statuses = [feed["status"] for feed in value["feeds"].values()]
    return _result(items, ["recognised_government_feed_cache"], confidence="high" if "fresh" in statuses else "medium")


async def product_capabilities(owner: str) -> dict:
    value = await capability_registry.product_capabilities(owner)
    return _result([value], ["authoritative_capability_registry"], observed_at=value["generatedAt"])


async def gate_states(owner: str) -> dict:
    value = await capability_registry.gate_states(owner)
    return _result(value["items"], ["authoritative_gate_registry", "fresh_device_observation"], observed_at=value["generatedAt"])


# ── NEW: Learn with Higgins article search ────────────────────────────────────

async def learn_articles(query: str) -> dict:
    """Search published Learn with Higgins articles for content relevant to the query.

    Read-only access to the published catalogue. Never publishes or edits.
    """
    try:
        result = await learning.list_articles(
            category=None, audience=None, tag=None, risk_context=None,
            content_type=None, language=None, search=query[:80] if query else None,
            cursor=None, limit=5,
        )
        items = []
        for article_summary in result.get("items", []):
            # For matched articles, also fetch full content for Higgins to reference
            full = await learning.get_article(article_summary["slug"])
            if full:
                sections_text = ""
                for section in (full.get("sections") or [])[:4]:
                    heading = section.get("heading", "")
                    paragraphs = "\n".join(str(p) for p in (section.get("paragraphs") or []))
                    bullets = "\n".join(f"- {b}" for b in (section.get("bullets") or []))
                    sections_text += f"\n### {heading}\n{paragraphs}\n{bullets}" if heading else f"\n{paragraphs}\n{bullets}"
                items.append({
                    "slug": full["slug"],
                    "title": full["title"],
                    "summary": full.get("summary", ""),
                    "category": full.get("category", ""),
                    "content": redact_investigation_secrets(sections_text)[:2000],
                    "citations": [{"label": c.get("label", ""), "url": c.get("url", "")} for c in (full.get("citations") or [])[:4]],
                })
            else:
                items.append({
                    "slug": article_summary["slug"],
                    "title": article_summary["title"],
                    "summary": article_summary.get("summary", ""),
                })
        return _result(items, ["learn_with_higgins_catalogue"])
    except Exception:
        return _result([], ["learn_with_higgins_catalogue"], confidence="low")


async def learn_index() -> dict:
    """The Learn with Higgins catalogue as titles only.

    Supplied on every turn so Higgins knows which articles exist and can name and
    link the right one. Full article bodies are only fetched when the question is
    actually educational (see `learn_articles`).
    """
    try:
        result = await learning.list_articles(
            category=None, audience=None, tag=None, risk_context=None,
            content_type=None, language=None, search=None, cursor=None, limit=30,
        )
        items = [{"slug": item["slug"], "title": item["title"], "category": item.get("category", "")}
                 for item in result.get("items", [])]
        return _result(items, ["learn_with_higgins_catalogue"])
    except Exception:
        return _result([], ["learn_with_higgins_catalogue"], confidence="low")


# ── Deterministic context classifier ─────────────────────────────────────────

class ContextPlan:
    """Minimum set of context readers and knowledge modules for a Higgins question."""
    __slots__ = ("readers", "label", "learn_query", "knowledge_modules", "route_groups")

    def __init__(self, readers: list[str], label: str, learn_query: Optional[str] = None,
                 knowledge_modules: Optional[list[str]] = None,
                 route_groups: Optional[list[str]] = None):
        self.readers = readers
        self.label = label
        self.learn_query = learn_query
        self.knowledge_modules = knowledge_modules or []
        self.route_groups = route_groups or []

    def __repr__(self) -> str:
        return f"ContextPlan({self.label}, readers={self.readers}, modules={self.knowledge_modules}, routes={self.route_groups})"


# Patterns for deterministic classification — ordered by specificity
_PROTECTION_RE = re.compile(
    r"(?i)\b(?:am i|is (?:my|the|this)|are (?:my|we))\s+(?:\w+ )?(?:protected|safe|secure)"
    r"|(?:protection|security)\s+(?:status|state|running|active|on|off|working)"
    r"|(?:is|are)\s+(?:apollo|protection)\s+(?:on|running|active|working|enabled|protecting)"
    r"|apollo\s+protecting"
)
_CURRENT_ISSUES_RE = re.compile(
    r"(?i)(?:why\s+(?:is|are|'s)\s+(?:apollo|it|you)\s+(?:barking|growling|warning|alerting))"
    r"|(?:what(?:'s| is)\s+wrong)"
    r"|(?:any|what|are there)\s+(?:issues?|problems?|warnings?|alerts?)"
    r"|(?:needs?|requires?)\s+attention"
)
_PATROL_HISTORY_RE = re.compile(
    r"(?i)(?:what\s+happened|what(?:'s| has)\s+been\s+(?:happening|going on))"
    r"|(?:recent|latest|last)\s+(?:findings?|events?|checks?|activity|results?|scans?)"
    r"|(?:show\s+me|tell\s+me\s+about)\s+(?:my\s+)?(?:recent|latest|patrol|history|findings)"
)
_SCAM_ALERTS_RE = re.compile(
    r"(?i)(?:scam|fraud|threat)\s+(?:alerts?|warnings?|advisories?|bulletins?|news)"
    r"|(?:latest|recent|new|current)\s+(?:scam|fraud|threat|phishing)s?"
    r"|(?:government|official)\s+(?:scam|fraud|threat)\s+(?:alerts?|warnings?)"
    r"|(?:what\s+scams?\s+(?:are|is)\s+(?:there|around|going|happening|active))"
)
_INVESTIGATION_EXPLAIN_RE = re.compile(
    r"(?i)(?:explain|tell me about|summarise|summarize|describe)\s+(?:this|that|the|my|an?)\s*(?:investigation|case|report|result|finding|assessment)"
    r"|(?:what\s+did\s+(?:magnum|apollo|it)\s+find)"
    r"|(?:what\s+(?:does|did)\s+(?:the|this|that|my)\s+(?:investigation|report|case)\s+(?:say|find|show|mean))"
)
_PRODUCT_INFO_RE = re.compile(
    r"(?i)(?:what\s+(?:does|can|is)\s+(?:apollo|higgins|magnum))"
    r"|(?:how\s+(?:does|do)\s+(?:apollo|higgins|magnum|protection|gates?))"
    r"|(?:features?|capabilities?|settings?)\s+(?:of|in|for)?\s*(?:apollo)?"
    r"|(?:what\s+(?:are|is)\s+(?:the\s+)?gates?)"
)
_LEARN_RE = re.compile(
    r"(?i)(?:how\s+(?:can i|do i|to)\s+(?:recognise|recognize|spot|identify|avoid|prevent|report|protect))"
    r"|(?:what\s+(?:is|are)\s+(?:a\s+)?(?:phishing|smishing|vishing|romance|investment|impersonation|identity|credential|social engineering))"
    r"|(?:teach|educate|learn|article|guide|tip|advice)\s+(?:me|about)"
    r"|(?:show\s+me\s+(?:what\s+you(?:'ve| have)\s+got|articles?|guides?|tips?))"
    r"|(?:tell\s+me\s+(?:about|how)\s+\w+\s+scam)"
    r"|(?:types?\s+of\s+(?:scam|fraud|phishing|attack))"
)
_DEVICE_INFO_RE = re.compile(
    r"(?i)(?:what\s+(?:version|os|android|ios|phone|device|model|build))"
    r"|(?:my\s+(?:device|phone|os|android|ios)\s+(?:version|info|details|model))"
    r"|(?:(?:device|phone|os)\s+(?:info|details|information))"
    r"|(?:what\s+(?:am i|phone am i)\s+(?:running|using))"
)


# ── Navigation / route-need patterns ─────────────────────────────────────────
_NAVIGATE_RE = re.compile(
    r"(?i)(?:where|how)\s+(?:do i|can i|to)\s+(?:find|go|get|open|see|access|navigate|get to)"
    r"|(?:show\s+me|take\s+me|open|go\s+to|navigate\s+to)"
    r"|(?:where\s+(?:is|are)\s+(?:the|my)?)"
)
_CHECKS_RE = re.compile(
    r"(?i)(?:check|scan|verify|inspect|test|analyse|analyze)\s+(?:a|an|my|this|that|the)?\s*"
    r"(?:link|url|file|app|message|email|number|code|qr|screenshot|photo|picture|image|device|network|internet|wifi|wi-fi|account|text)"
    r"|(?:how\s+(?:do i|can i|to)\s+(?:check|scan|verify|test))"
    r"|(?:call\s+screen)"
)
_RECORDS_RE = re.compile(
    r"(?i)(?:history|saved|past|previous|record|archive|digest|weekly)"
    r"|(?:what\s+(?:have i|did i)\s+(?:checked|scanned|looked at))"
)
_SETTINGS_RE = re.compile(
    r"(?i)(?:setting|configure|config|option|preference|toggle|turn\s+(?:on|off))"
    r"|(?:quiet\s+hours|battery\s+saver|notification)"
    r"|(?:family|email\s+account)"
)
# ── Sharing / product-help intent (must outrank privacy and product_info) ──────
_SHARING_HELP_RE = re.compile(
    r"(?i)(?:how\s+(?:do|can|to)\s+i?\s*(?:share|send|submit|add|upload|get|put))\s+(?:\w+\s+){0,3}(?:into|to|in|for|with)\s+(?:apollo|the app)"
    r"|(?:(?:share|send|submit|add|upload)\s+(?:a\s+|an\s+|my\s+|some\s+|the\s+)?(?:message|screenshot|link|email|file|photo|picture|image|something|thing|stuff|content|item)\s+(?:into|to|in|for|with)\s+(?:apollo|the app))"
    r"|(?:(?:share|send)\s+(?:into|to|from|with)\s+(?:apollo|another\s+app))"
    r"|(?:can\s+i\s+(?:share|send|submit)\s+(?:\w+\s+)?(?:from\s+(?:another|a|the)\s+app|to\s+(?:apollo|the app)))"
    r"|(?:(?:apollo(?:\s?sg)?|it)(?:'s| is)\s+not\s+(?:in|on|showing)\s+(?:my\s+)?(?:share|sharing)\s+menu)"
    r"|(?:(?:apollo(?:\s?sg)?)\s+isn.t\s+(?:in|on|showing)\s+(?:my\s+)?(?:share|sharing)\s+menu)"
    r"|(?:not\s+in\s+(?:my\s+)?(?:share|sharing)\s+menu)"
    r"|(?:how\s+(?:do|can|to)\s+i?\s*get\s+(?:something|things?|stuff|content|it)\s+into\s+(?:apollo|the app))"
    r"|(?:share\s+menu)"
    r"|(?:how\s+(?:do|can)\s+i\s+(?:send|share)\s+(?:apollo|higgins)\s+(?:a\s+)?(?:screenshot|message|link|email|file|photo|picture|image))"
)
_PRIVACY_RE = re.compile(
    r"(?i)(?:\bprivacy\b|personal\s+(?:data|information)|gdpr)"
    r"|(?:what\s+(?:does|do|will|would|can)\s+(?:apollo\s?(?:sg)?|you|higgins|it|the app)\s+(?:store|collect|keep|know|send|share|track|upload|retain|delete|do with))"
    r"|(?:what\s+(?:info(?:rmation)?|data)\s+(?:does|do|will|would|can)\s+(?:apollo\s?(?:sg)?|you|higgins|it|the app)\s+(?:share|send|collect|store|keep|upload|retain|delete))"
    r"|(?:(?:my|our|user)\s+data\b)"
    r"|(?:(?:does|do|is|will)\s+(?:anything|data|info(?:rmation)?|my (?:data|info(?:rmation)?))\s+(?:leave|get sent|go to|stay on|get shared|get uploaded|stored|deleted|retained|kept))"
    r"|(?:(?:who|what|where)\s+(?:can|does|do|will)\s+(?:see|access|read|get)\s+(?:my|the|our|what I)\s+(?:data|info(?:rmation)?|message|screenshot|file|content|share))"
    r"|(?:(?:is|are)\s+(?:my\s+)?(?:data|messages?|files?|screenshots?|conversations?|sharing)\s+(?:private|secure|encrypted|safe|shared|sent|stored|deleted|retained))"
    r"|(?:(?:data|info(?:rmation)?)\s+(?:retention|deletion|collection|storage|sharing|privacy))"
    r"|(?:(?:how long|when)\s+(?:(?:is|are)\s+)?(?:my\s+)?(?:data|info(?:rmation)?|messages?|conversations?)\s+(?:stored|kept|retained|deleted))"
)
_FLOWS_RE = re.compile(
    r"(?i)(?:how\s+(?:does|do)\s+(?:checks?|triage|investigation|escalation|sharing|screening)\s+work)"
    r"|(?:what\s+(?:happens|occurs)\s+(?:when|after|if))"
    r"|(?:sniffing|growling|barking|biting|patrolling)"
    r"|(?:one\s+case|dedup|share\s+into)"
    r"|(?:what\s+(?:are|is)\s+(?:the\s+)?(?:states?|stages?|status|tone))"
)
_CALL_SCREENING_RE = re.compile(
    r"(?i)(?:call\s+screen|caller\s+id|spam\s+(?:block|filter|screen))"
    r"|(?:default\s+(?:call|dialer|phone)\s+(?:app|screen|handler))"
    r"|(?:screen\s+(?:my\s+)?calls)"
)


def classify_context(message: str, *, has_selected_patrol_record: bool = False) -> ContextPlan:
    """Deterministically select the minimum Apollo context required for a Higgins question.

    This replaces the previous pattern of asking Gemini to choose from a toolbox
    of context functions.  The classification is fast, predictable and testable.

    Returns a ContextPlan that now also includes knowledge_modules and route_groups
    for the modular prompt architecture.
    """
    msg = message.strip()

    # ── Classify knowledge modules and route groups ──────────────────────
    modules: list[str] = []
    routes: list[str] = []

    # Fail-safe: when navigation intent is detected, include tabs overview
    needs_navigation = bool(_NAVIGATE_RE.search(msg))
    if needs_navigation:
        routes.append("tabs")

    # Check-related → checks routes + flows
    if _CHECKS_RE.search(msg):
        routes.append("checks")
        if "flows" not in modules:
            modules.append("flows")

    # Records / history
    if _RECORDS_RE.search(msg):
        routes.append("records")

    # Settings
    if _SETTINGS_RE.search(msg):
        routes.append("settings")
        if "settings_detail" not in modules:
            modules.append("settings_detail")

    # Sharing / product-help intent (must outrank privacy and product-info)
    if _SHARING_HELP_RE.search(msg):
        routes.append("checks")
        if "flows" not in modules:
            modules.append("flows")
        # Do NOT add privacy — this is a procedural question

    # Privacy (only when the question has genuine privacy/data semantics)
    elif _PRIVACY_RE.search(msg):
        if "privacy" not in modules:
            modules.append("privacy")
        if "settings" not in routes:
            routes.append("settings")   # privacy routes live under settings

    # Flows (states, how things work)
    if _FLOWS_RE.search(msg):
        if "flows" not in modules:
            modules.append("flows")

    # Call screening
    if _CALL_SCREENING_RE.search(msg):
        if "call_screening" not in modules:
            modules.append("call_screening")
        if "checks" not in routes:
            routes.append("checks")

    # Learning
    if _LEARN_RE.search(msg):
        if "learning" not in routes:
            routes.append("learning")

    # ── Fail-safe: unknown classification gets baseline context ──────────
    # If nothing matched for modules and it's a product question, include flows + tabs
    if _PRODUCT_INFO_RE.search(msg):
        if not modules:
            modules.append("flows")
        if not routes:
            routes.append("tabs")
            routes.append("checks")

    # ── Classify context readers (unchanged logic) ───────────────────────
    if has_selected_patrol_record:
        return ContextPlan(["get_last_relevant_outcome"], "patrol_record_context",
                           knowledge_modules=modules, route_groups=routes)

    if _PROTECTION_RE.search(msg):
        return ContextPlan(["get_protection_summary", "get_gate_states"], "protection_status",
                           knowledge_modules=modules, route_groups=routes)

    if _CURRENT_ISSUES_RE.search(msg):
        if "flows" not in modules:
            modules.append("flows")  # fail-safe: states need flows context
        return ContextPlan(["get_last_relevant_outcome", "get_protection_summary"], "current_issues",
                           knowledge_modules=modules, route_groups=routes)

    if _DEVICE_INFO_RE.search(msg):
        return ContextPlan(["get_product_capabilities"], "device_info",
                           knowledge_modules=modules, route_groups=routes)

    if _PATROL_HISTORY_RE.search(msg):
        if "records" not in routes:
            routes.append("records")
        return ContextPlan(["get_recent_patrol_outcomes"], "patrol_history",
                           knowledge_modules=modules, route_groups=routes)

    if _SCAM_ALERTS_RE.search(msg):
        return ContextPlan(["get_new_scams_digest"], "scam_alerts",
                           knowledge_modules=modules, route_groups=routes)

    if _INVESTIGATION_EXPLAIN_RE.search(msg):
        return ContextPlan(["get_recent_cases", "get_saved_reports"], "investigation_explain",
                           knowledge_modules=modules, route_groups=routes)

    if _LEARN_RE.search(msg):
        learn_query = msg[:80]
        return ContextPlan([], "learn_articles", learn_query=learn_query,
                           knowledge_modules=modules, route_groups=routes)

    if _PRODUCT_INFO_RE.search(msg):
        return ContextPlan(["get_product_capabilities"], "product_info",
                           knowledge_modules=modules, route_groups=routes)

    # Sharing help: high-priority, returns early with just the sharing intent
    if _SHARING_HELP_RE.search(msg):
        return ContextPlan([], "sharing_help",
                           knowledge_modules=["flows"], route_groups=["checks"])

    return ContextPlan([], "general_knowledge",
                       knowledge_modules=modules, route_groups=routes)


# ── What the person's message asks Higgins about ─────────────────────────────
# The app's own hand-offs (an opened scam alert or Learn article), and what a question is about. Deterministic.
_ALERT_URL = re.compile(r"official source:\s*(https?://\S+)", re.I)
_ALERT_CARD = re.compile(r"i just read this scam alert", re.I)
_CARD_FIELD = {"title": re.compile(r"^\W*title:\s*(.+)$", re.I | re.M), "source": re.compile(r"^\W*source:\s*(.+)$", re.I | re.M),
               "summary": re.compile(r"^\W*what the source says:\s*(.+)$", re.I | re.M)}
_ARTICLE = re.compile(r"explain the learning article:\s*(.+?)\s*$", re.I | re.S)


def alert_url_in(message: str) -> Optional[str]:
    match = _ALERT_URL.search(message or "")
    return match.group(1).rstrip(").,") if match else None


def alert_card_in(message: str) -> Optional[dict]:
    """The alert card the Scam Alerts screen hands to Higgins: its title, source, summary and official link."""
    if not _ALERT_CARD.search(message or ""):
        return None
    fields = {name: (m.group(1).strip() if (m := pattern.search(message)) else "") for name, pattern in _CARD_FIELD.items()}
    if not fields["title"]:
        return None
    return {**fields, "url": alert_url_in(message) or ""}


def article_title_in(message: str) -> Optional[str]:
    """The Learn article the person opened and asked Higgins to explain."""
    match = _ARTICLE.search(message or "")
    return match.group(1).strip().strip("“”\"'.") if match else None


_SCOPE = re.compile(r"\b(scam\w*|fraud\w*|phish\w*|smish\w*|vish\w*|spam|hack\w*|malware|virus\w*|ransomware|spyware|security|secure|safe\w*|cyber\w*|"
                    r"password\w*|passphrase\w*|passkey\w*|pin|two[- ]factor|2fa|mfa|authenticat\w*|identity|id theft|privacy|private|data breach\w*|breach\w*|"
                    r"account\w*|bank\w*|card\w*|payment\w*|money|transfer\w*|invest\w*|crypto\w*|bitcoin|gift cards?|romance|dating|sextortion|blackmail|"
                    r"impersonat\w*|fake|suspicious|link\w*|url|website\w*|email\w*|text messages?|sms|message\w*|calls?|caller|number|phone|device|app\w*|"
                    r"wi-?fi|network|vpn|router|update\w*|backup\w*|download\w*|attachment\w*|qr|remote access|tech support|apollo|higgins|magnum|"
                    r"report\w*|stolen|steal\w*|lost|trick\w*|con|deepfake\w*|ai voice|social media|facebook|instagram|whatsapp|marketplace)\b", re.I)
_ABOUT_THIS_PHONE = re.compile(r"\b(my|this)\s+(phone|device|mobile|iphone|android)\b|\bon (?:my|this) (?:phone|device)\b|\b(?:am i|are my|is my)\b", re.I)
# Unmistakably about the state Apollo reads on this phone: always answered from the reading, whatever the wording.
_ABOUT_STATE = re.compile(r"\bmy\s+(?:[\w'-]+\s+){0,3}(?:protections?|gates?|permissions|security (?:review|check|status)|device (?:check|assessment))\b"
                          r"|\bapollo (?:says|shows|reports) (?:its|the|my) status\b", re.I)
_ABOUT_APOLLO = re.compile(r"\b(apollo|higgins|magnum|this app)\b|\bwhere (?:do|can) i\b|\bhow (?:do|can) i (?:check|scan|open|find|turn|use)\b", re.I)


def in_scope(question: str) -> bool:
    """A question about scams, security, privacy or ApolloSG — what Higgins answers."""
    return bool(_SCOPE.search(question or ""))


def about_state(message: str) -> bool:
    return bool(_ABOUT_STATE.search(message or ""))


def about_this_phone(message: str) -> bool:
    return bool(_ABOUT_THIS_PHONE.search(message or ""))


def about_apollo(message: str) -> bool:
    return bool(_ABOUT_APOLLO.search(message or ""))


_PROCEDURAL_RE = re.compile(
    r"(?i)^\W*(?:(?:hi|hey|ok|okay|so|higgins|please)\b[\s,]*)*"
    r"(?:how\s+(?:do|can|should|would)\s+i\b|how\s+to\b|where\s+(?:do|can|should|would)\s+i\b|where\s+(?:is|are)\b|where'?s\b"
    r"|i\s+can'?t\s+find\b|i\s+cannot\s+find\b)"
)


def procedural(message: str) -> bool:
    """A "how do I…" / "where is…" question about using the app — not scam education ("how do I spot…")."""
    return bool(_PROCEDURAL_RE.search(message or "")) and not _LEARN_RE.search(message or "")


# ── Reader registry (unchanged) ──────────────────────────────────────────────

READERS: dict[str, Callable[[str], Awaitable[dict]]] = {
    "get_protection_summary": protection, "get_recent_cases": recent_cases,
    "get_last_relevant_outcome": lambda owner: patrol(owner, one=True), "get_saved_reports": saved_reports,
    "get_recent_patrol_outcomes": patrol, "get_user_learning_preferences": preferences, "get_new_scams_digest": scams,
    "get_product_capabilities": product_capabilities, "get_gate_states": gate_states,
    "get_learn_catalogue": lambda _owner: learn_index(),
}

# Higgins is the savant of Apollo, so these are gathered on every turn rather than
# only when a question happens to match a pattern. Everything the service holds for
# this person is in front of him before he answers.
CORE_READERS: tuple[str, ...] = (
    "get_protection_summary",
    "get_gate_states",
    "get_recent_patrol_outcomes",
    "get_recent_cases",
    "get_new_scams_digest",
    "get_learn_catalogue",
)


def with_core_readers(plan: ContextPlan) -> ContextPlan:
    """Return the plan with the always-on Apollo readers merged in, order preserved."""
    merged = list(CORE_READERS)
    for reader in plan.readers:
        if reader not in merged:
            merged.append(reader)
    return ContextPlan(merged, plan.label, plan.learn_query,
                       knowledge_modules=plan.knowledge_modules,
                       route_groups=plan.route_groups)


async def execute(owner: str, name: str) -> dict:
    reader = READERS.get(name)
    if not reader:
        return {"status": "unknown_tool", "items": [], "provenance": [], "confidence": "low"}
    try:
        return await reader(owner)
    except Exception:  # noqa: BLE001 — context absence is explicit, never fabricated
        return {"status": "unavailable", "items": [], "provenance": [], "confidence": "low", "note": "This context source is unavailable."}


async def gather_context(owner: str, plan: ContextPlan) -> tuple[str, list[dict]]:
    """Execute the context plan and return (context_text, context_uses).

    This is the single entry point for all deterministic context gathering.
    Returns a formatted text block ready for injection into the Higgins prompt,
    plus structured metadata about what was consulted.
    """
    uses: list[dict] = []
    context_parts: list[str] = []

    # Fetch Learn articles if the plan requests it
    if plan.learn_query:
        learn_result = await learn_articles(plan.learn_query)
        uses.append({"source": "learn_articles", "status": learn_result.get("status", "unavailable"),
                      "provenance": learn_result.get("provenance", [])})
        if learn_result.get("items"):
            parts = ["--- LEARN WITH HIGGINS ARTICLES ---"]
            for article in learn_result["items"]:
                parts.append(f"\nArticle: {article.get('title', 'Untitled')}")
                if article.get("summary"):
                    parts.append(f"Summary: {article['summary']}")
                if article.get("content"):
                    parts.append(article["content"])
                if article.get("citations"):
                    parts.append("Sources: " + ", ".join(f"{c['label']} ({c['url']})" for c in article["citations"] if c.get("url")))
            parts.append("--- END LEARN ARTICLES ---")
            parts.append("Use the above articles to answer the person's question. Reference the article by name when relevant.")
            context_parts.append("\n".join(parts))

    # Fetch registered context readers
    for reader_name in plan.readers:
        result = await execute(owner, reader_name)
        uses.append({"source": reader_name, "status": result.get("status", "unavailable"),
                      "provenance": result.get("provenance", []),
                      "observedAt": result.get("observedAt")})
        if result.get("items"):
            context_parts.append(f"--- {reader_name.upper()} ---\n{_format_context_items(reader_name, result['items'])}\n--- END ---")

    context_text = "\n\n".join(context_parts) if context_parts else ""
    return context_text, uses


def _format_context_items(reader_name: str, items: list[dict]) -> str:
    """Format context items into a readable text block for the prompt."""
    if not items:
        return "No data available."
    limit = 30 if reader_name == "get_learn_catalogue" else 8
    parts = []
    for item in items[:limit]:
        if isinstance(item, dict):
            # Filter out internal fields and format compactly
            display = {k: v for k, v in item.items() if v is not None and k not in ("_id",)}
            parts.append(str(display))
        else:
            parts.append(str(item))
    return "\n".join(parts)
