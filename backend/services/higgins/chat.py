"""Higgins chat — the router. Higgins faithfully communicates what Apollo already knows. Ask Higgins makes NO AI call.

Each question goes to the first of these that applies; each one's work lives in its own module:
  1. Something specific to check → the shared investigation pipeline (pipeline_submit.py): TC FlyBy first, Magnum DI
     only when a deeper look could change the answer. Never answered here.
  2. A scam alert or Learn article the person opened → its source's own words (government_alerts, learning, presenter.py).
  3. What Apollo already established — Patrol findings, the phone's live state, recent investigations or Apollo's
     product knowledge → deterministic presentation (context_tools.py, presenter.py).
  4. Apollo's knowledge base — Learn articles, Scam Alerts, official guidance and researched trusted pages
     (knowledge.py), quoted with their provenance and labelled as general knowledge, never as a finding about a case.
When none of these covers a question, Higgins says so plainly — ApolloSG's trusted knowledge doesn't answer it —
rather than asking a general AI model. Questions outside Higgins' scope get a fixed reply.
Tavily is never used here — it only maintains the knowledge base.
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import Field

from core.redaction import redact_investigation_secrets
from services import government_alerts, learning
from services import reusable_intel as intel
from services import sufficiency
from services.higgins import app_knowledge, knowledge, pipeline_submit, presenter
from services.higgins import context as memory
from services.higgins import context_tools
from services.higgins.contracts import Wire

log = logging.getLogger("apollo.higgins.chat")

class NavTarget(Wire):
    """A validated Apollo destination the person can tap straight through to."""
    route: str
    label: str


class SnapshotGate(Wire):
    """One protection, exactly as the phone currently reports it."""
    id: str = Field(max_length=40)
    title: str = Field(max_length=60)
    status: str = Field(max_length=80)
    tone: str = Field(max_length=20)
    automatic: bool = False
    coverage: str = Field(default="", max_length=40)


class DeviceSnapshot(Wire):
    """Everything Apollo holds on this phone, as the phone reads it right now.

    Every field is a state reading or a short headline Apollo itself wrote. No
    message bodies, screenshots, files or secrets are ever carried here.
    """
    platform: Optional[str] = Field(default=None, max_length=20)
    checked_at: Optional[str] = Field(default=None, max_length=40)
    protection_on: Optional[bool] = None
    adapter: Optional[str] = Field(default=None, max_length=80)
    gates: list[SnapshotGate] = Field(default_factory=list, max_length=14)
    permissions: list[str] = Field(default_factory=list, max_length=14)
    network: Optional[str] = Field(default=None, max_length=240)
    threat_counts: list[str] = Field(default_factory=list, max_length=8)
    open_threats: list[str] = Field(default_factory=list, max_length=8)
    alerts: Optional[str] = Field(default=None, max_length=120)
    quiet_hours: Optional[str] = Field(default=None, max_length=80)
    battery_saver: Optional[bool] = None
    trusted_links: Optional[int] = None
    saved_checks: Optional[int] = None
    personal_data: Optional[str] = Field(default=None, max_length=160)
    call_screener: Optional[str] = Field(default=None, max_length=240)
    email_accounts: Optional[str] = Field(default=None, max_length=160)
    # Device Capabilities — what this device protects by itself, what Apollo is allowed to use, and
    # which native settings Apollo cannot read. Attribution is carried in the strings themselves.
    capability_summary: Optional[str] = Field(default=None, max_length=300)
    device_protections: list[str] = Field(default_factory=list, max_length=8)
    capabilities: list[str] = Field(default_factory=list, max_length=16)
    recommended_settings: list[str] = Field(default_factory=list, max_length=8)
    notes: list[str] = Field(default_factory=list, max_length=10)


class ContextUse(Wire):
    source: str
    status: str
    provenance: list[str] = Field(default_factory=list)
    observed_at: Optional[str] = None


class SuggestedAction(Wire):
    kind: Literal["app_destination"] = "app_destination"
    destination: Literal["check_it", "higgins_case"]
    label: str
    purpose: str


class ChatRetention(Wire):
    server_content_expires_at: str
    local_content_max_seconds: Literal[3600] = 3600
    receipt_only_after_expiry: Literal[True] = True


class ChatSource(Wire):
    """Where an answer's words come from: an official page (url) or an Apollo screen (route)."""
    title: str
    publisher: str
    url: Optional[str] = None
    route: Optional[str] = None
    licence: Optional[str] = None


class ChatReply(Wire):
    turn_id: str
    conversation_id: str
    answer: str
    evidence_basis: list[str]
    uncertainty: list[str]
    clarification: Optional[str]
    context_used: list[ContextUse]
    suggested_actions: list[SuggestedAction]
    navigation: list[NavTarget] = Field(default_factory=list)
    investigation_available: bool
    investigative_work_started: bool = False
    pipeline_case_id: Optional[str] = None
    sources: list[ChatSource] = Field(default_factory=list)
    # apollo = Apollo's own records; knowledge_base = quoted KB sources. There is no AI-written answer.
    answered_by: Literal["apollo", "knowledge_base"] = "apollo"
    retention: ChatRetention


async def reply(owner: str, conversation_id: str, turn_id: str, message: str, previous_turn_ids: list[str],
                selected_patrol_record_id: str | None = None, device_snapshot: DeviceSnapshot | None = None,
                selected_scam_alert_url: str | None = None) -> ChatReply:
    clean = redact_investigation_secrets(message).strip()

    # ── 1. Something specific to check → the shared investigation pipeline (never a pseudo-investigation here) ──
    if pipeline_submit.detect_investigation_intent(clean):
        items = pipeline_submit.extract_submittable_items(clean)
        if items:
            try:
                result = await pipeline_submit.submit_to_investigation_pipeline(owner, clean, items)
                return await _submitted(owner, conversation_id, turn_id, clean, result["case_id"], pipeline_submit.submitted_answer(items))
            except Exception as exc:
                log.warning("higgins_pipeline_submit_failed device=%s error=%s", owner[:12], type(exc).__name__)
                # Fall through to normal chat if pipeline submission fails

    # ── 2. A scam alert the person opened → the source's own sections (0 AI calls) ──
    card = context_tools.alert_card_in(clean)
    alert_url = selected_scam_alert_url or (card or {}).get("url") or context_tools.alert_url_in(clean)
    if alert_url or card:
        alert = await government_alerts.alert_by_url(alert_url) if alert_url else None
        if alert:
            return await _deterministic(owner, conversation_id, turn_id, clean, presenter.scam_alert_explanation(alert),
                                        "scam_alert", ["recognised_government_feed_cache"])
        if card:
            # Apollo no longer holds the full alert: present only what the card carried.
            return await _deterministic(owner, conversation_id, turn_id, clean,
                                        presenter.scam_alert_card(card["title"], card["source"], card["summary"], card["url"]),
                                        "scam_alert", ["scam_alert_card"])

    # ── 2b. A Learn with Higgins article the person opened → its own words (0 AI calls) ──
    article_title = context_tools.article_title_in(clean)
    if article_title:
        article = await learning.article_by_title(article_title)
        result = presenter.learn_article(article) if article else {
            "answer": f"I couldn't find “{article_title}” in ApolloSG's Learn with Higgins library, so I have nothing of its to show you.",
            "navigate": ["/higgins/learning"], "limitation": True}
        return await _deterministic(owner, conversation_id, turn_id, clean, result, "learn_article", ["learn_with_higgins_catalogue"])

    # ── 3. Anything Apollo already knows is presented as it stands ──
    plan = context_tools.classify_context(clean, has_selected_patrol_record=bool(selected_patrol_record_id))
    established = await _from_apollo(owner, clean, plan, device_snapshot, selected_patrol_record_id)
    if established:
        result, label, provenance = established
        return await _deterministic(owner, conversation_id, turn_id, clean, result, label, provenance)

    # ── 4. Apollo's knowledge base (Learn, Scam Alerts, official guidance, researched trusted pages) ──
    entries = await knowledge.search(clean)
    decision = sufficiency.assess(sufficiency.Requirement(intel.subject_key("question", clean), needs=("answer",)), kb=entries)
    await intel.count(GENERAL_SITE, *decision.events(call_made=False))
    if decision.kb:
        answer, sources = knowledge.present(decision.kb, clean)
        return await _deterministic(owner, conversation_id, turn_id, clean, {"answer": answer, "navigate": [], "sources": sources},
                                    "knowledge_base", [e["kind"] for e in decision.kb], answered_by="knowledge_base")

    # ── 5. Nothing trusted answers it. Higgins says so; no general AI model is asked. ──
    if not context_tools.in_scope(clean):
        return await _deterministic(owner, conversation_id, turn_id, clean, {"answer": presenter.OUT_OF_SCOPE, "navigate": []},
                                    "out_of_scope", [])
    return await _deterministic(owner, conversation_id, turn_id, clean, presenter.not_in_trusted_knowledge(), "not_in_trusted_knowledge", [])


GENERAL_SITE = "higgins_general_question"  # this call site, in the reuse counters (always answered without an AI call)


async def _from_apollo(owner: str, message: str, plan: context_tools.ContextPlan,
                       snapshot: DeviceSnapshot | None, patrol_record_id: str | None = None) -> Optional[tuple[dict, str, list[str]]]:
    """What Apollo, Patrol, TC FlyBy, Magnum DI or the device already established — presented, never re-reasoned."""
    label = plan.label
    if label == "patrol_record_context" and patrol_record_id:
        found = await context_tools.execute(owner, "get_recent_patrol_outcomes")
        record = next((item for item in found.get("items") or [] if item.get("recordId") == patrol_record_id), None)
        if record:
            return presenter.patrol_record(record), label, ["authoritative_patrol_record_store"]
    if label in ("patrol_record_context", "patrol_history"):
        found = await context_tools.execute(owner, "get_recent_patrol_outcomes")
        return presenter.patrol_findings(found.get("items") or []), label, ["authoritative_patrol_record_store"]
    if label == "current_issues" and snapshot is None:
        found = await context_tools.execute(owner, "get_recent_patrol_outcomes")
        return presenter.patrol_findings(found.get("items") or []), label, ["authoritative_patrol_record_store"]
    # Anything about THIS phone's state is answered from its live reading — never inferred.
    about_state = label in ("protection_status", "current_issues", "device_info") or context_tools.about_state(message)
    device = presenter.device_state(snapshot, message, about_phone=about_state)
    if device and (about_state or context_tools.about_this_phone(message)):
        return device, "device_state", ["device_snapshot" if snapshot else "no_device_reading"]
    if label == "scam_alerts":
        snapshot_alerts = await government_alerts.snapshot(5)
        return presenter.scam_alerts(snapshot_alerts["alerts"]), label, ["recognised_government_feed_cache"]
    if label == "investigation_explain":
        found = await context_tools.execute(owner, "get_recent_cases")
        return presenter.recent_investigations(found.get("items") or []), label, ["investigation_case_store"]
    if plan.knowledge_modules or label == "product_info" or label == "sharing_help" or context_tools.about_apollo(message):
        product = presenter.product_knowledge(message, plan.knowledge_modules, intent_label=label)
        if product:
            return product, "product_knowledge", ["apollo_product_knowledge"]
    return None


async def _submitted(owner: str, conversation_id: str, turn_id: str, message: str, case_id: str, answer: str) -> ChatReply:
    """The reply when the message went to the investigation pipeline: where to find the case."""
    expires = await memory.add_chat_exchange(owner, conversation_id, turn_id, message, answer, classification="investigation_submission",
                                             context_sources=["pipeline_submit"], investigation_available=True)
    log.info("higgins_investigation_routed device=%s case=%s", owner[:12], case_id[:12])
    return ChatReply(turn_id=turn_id, conversation_id=conversation_id, answer=answer, evidence_basis=["investigation_pipeline"], uncertainty=[],
                     clarification=None, context_used=[ContextUse(source="pipeline_submit", status="submitted")],
                     suggested_actions=[SuggestedAction(destination="higgins_case", label="View Investigation",
                                                        purpose="Open the investigation that was submitted from this conversation.")],
                     investigation_available=True, investigative_work_started=True, pipeline_case_id=case_id,
                     retention=ChatRetention(server_content_expires_at=expires.isoformat()))


async def _deterministic(owner: str, conversation_id: str, turn_id: str, message: str, result: dict, label: str,
                         provenance: list[str], *, uncertainty: list[str] | None = None, answered_by: str = "apollo") -> ChatReply:
    """Higgins presents what is already established. No AI call is made."""
    expires = await memory.add_chat_exchange(owner, conversation_id, turn_id, message, result["answer"], classification=label,
                                             context_sources=provenance, investigation_available=False)
    limitation = ["Apollo's records don't answer this directly."] if result.get("limitation") else []
    return ChatReply(turn_id=turn_id, conversation_id=conversation_id, answer=result["answer"], evidence_basis=provenance,
                     uncertainty=(uncertainty or []) + limitation, clarification=None,
                     context_used=[ContextUse(source=item, status="ok") for item in provenance], suggested_actions=[],
                     navigation=[NavTarget(route=route, label=name) for route, name in app_knowledge.navigation(result.get("navigate") or [])],
                     sources=[ChatSource(**src) for src in result.get("sources") or []],
                     investigation_available=False, answered_by=answered_by,
                     retention=ChatRetention(server_content_expires_at=expires.isoformat()))
