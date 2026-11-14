"""Retrieval/context only. No conversational generation, provider calls or case mutation."""
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from services.higgins import app_knowledge, knowledge, context_tools, chat
from core.redaction import redact_investigation_secrets

async def retrieve(owner, body):
    question = redact_investigation_secrets(body.message)
    # Keep investigation routing at its existing authenticated boundary.
    if chat._items_to_check(question):
        return {"kind": "investigation_required", "passages": [], "navigation": []}
    plan = context_tools.classify_context(question, has_selected_patrol_record=bool(body.selected_patrol_record_id))
    product = app_knowledge.knowledge_block(plan.knowledge_modules)
    query_terms = knowledge.terms(question)
    passages = []
    # Retrieve relevant paragraphs, not the entire product guide.
    for paragraph in sorted(product.split("\n\n"), key=lambda p: -len(set(knowledge.terms(p)) & set(query_terms))):
        if not set(knowledge.terms(paragraph)) & set(query_terms):
            continue
        passages.append({"id": "product-" + sha256(paragraph.encode()).hexdigest()[:16], "title": "ApolloSG product guide", "url": None,
                         "text": knowledge.excerpt(paragraph, query_terms), "publishedAt": None, "checkedAt": None, "freshness": "versioned_product_guide"})
        if len(passages) == 2:
            break
    for entry in await knowledge.search(question, limit=6-len(passages)):
        provenance = entry.get("provenance") or {}
        passages.append({"id": str(entry.get("entry_id") or entry.get("id") or sha256(str(entry.get("url", entry["title"])).encode()).hexdigest()),
                         "title": entry["title"], "url": entry.get("url"), "text": knowledge.excerpt(entry["body"], query_terms),
                         "publishedAt": str(provenance.get("published_at") or "") or None,
                         "checkedAt": str(provenance.get("last_checked_at") or "") or None,
                         "freshness": entry.get("status", "unknown")})
    findings = []
    # Explicit record selection only. Never pull unrelated cases into ordinary chat.
    if body.selected_patrol_record_id:
        found = await context_tools.execute(owner, "get_recent_patrol_outcomes")
        findings = [x for x in found.get("items", []) if x.get("recordId") == body.selected_patrol_record_id]
    now = datetime.now(timezone.utc)
    return {"kind": "grounded_chat", "conversationId": body.conversation_id,
            "turnId": body.turn_id, "caseScopeId": body.selected_patrol_record_id, "scope": "in_scope" if context_tools.in_scope(question) else "out_of_scope",
            "userStatement": question, "passages": passages[:6], "kbVersion": "apollosg-product-v1",
            "deviceObservation": body.device_snapshot.wire() if body.device_snapshot else None,
            "caseFindings": findings, "navigation": [{"route": route, "label": label} for route, label in app_knowledge.NAV_ROUTES.items() if set(knowledge.terms(label)) & set(query_terms)][:3], "retrievedAt": now.isoformat(),
            "expiresAt": (now + timedelta(seconds=45)).isoformat()}
