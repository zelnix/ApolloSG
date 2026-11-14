"""Ordinary Higgins chat and typed owner context.

These routes never import or call the investigation coordinator. A case begins only through the
separate `/investigations` API after an explicit user action in the client.
"""
from __future__ import annotations

import json
import re
import uuid
from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field

from services.higgins import chat
from services.higgins import context as memory
from services.higgins.contracts import Wire
from services.higgins import repository as investigation_repository
from services import feed_health, government_alerts, rulebook
from core.db import db
from core.redaction import redact_investigation_secrets

router = APIRouter()
NO_STORE = {"Cache-Control": "private, no-store", "Pragma": "no-cache"}


class ChatRequest(Wire):
    turn_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=8, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=4, max_length=80)
    previous_turn_ids: list[str] = Field(default_factory=list, max_length=8)
    selected_patrol_record_id: str | None = Field(default=None, max_length=100)
    # Live reading of this phone's own Apollo state, so Higgins answers from what is
    # actually true rather than from what he can infer. State only — never content.
    device_snapshot: chat.DeviceSnapshot | None = None
    # The official alert the person opened, so Higgins explains it from the source's own words.
    selected_scam_alert_url: str | None = Field(default=None, max_length=600)


@router.post("/higgins/chat/context")
async def higgins_chat_context(body: ChatRequest, request: Request):
    from services.higgins.chat_context import retrieve
    return JSONResponse(await retrieve(request.state.device["device_id"], body), headers=NO_STORE)


@router.post("/higgins/chat", response_model=chat.ChatReply)
async def higgins_chat(body: ChatRequest, request: Request):
    owner = request.state.device["device_id"]
    result = await chat.reply(owner, body.conversation_id, body.turn_id, body.message, body.previous_turn_ids,
                              body.selected_patrol_record_id, body.device_snapshot, body.selected_scam_alert_url)
    return JSONResponse(result.wire(), headers=NO_STORE)


@router.post("/ask/stream")
async def ask_stream(body: ChatRequest, request: Request):
    """Compatibility SSE transport with ordinary-chat semantics and no case side effect."""
    result = await chat.reply(request.state.device["device_id"], body.conversation_id, body.turn_id, body.message, body.previous_turn_ids,
                              body.selected_patrol_record_id, body.device_snapshot, body.selected_scam_alert_url)
    async def events():
        yield f"data: {json.dumps({'delta': result.answer, 'clarification': result.clarification, 'suggested_actions': [a.wire() for a in result.suggested_actions], 'investigative_work_started': result.investigative_work_started, 'pipeline_case_id': result.pipeline_case_id})}\n\n"
        yield f"data: {json.dumps({'done': True, 'provider_complete': True, 'finish_reason': 'STOP', 'investigative_work_started': result.investigative_work_started})}\n\n"
    return StreamingResponse(events(), media_type="text/event-stream", headers={**NO_STORE, "X-Accel-Buffering": "no"})


@router.get("/ask/history")
async def ask_history(request: Request, device_id: str = Query(min_length=8, max_length=64)):
    del device_id
    owner = request.state.device["device_id"]
    return JSONResponse([item.wire() for item in await memory.chat_history(owner)], headers=NO_STORE)


@router.get("/higgins/chat/history")
async def higgins_chat_history(request: Request, device_id: str = Query(min_length=8, max_length=64)):
    del device_id
    owner = request.state.device["device_id"]
    return JSONResponse({"items": [item.wire() for item in await memory.chat_history(owner)], "receipts": await memory.chat_receipts(owner), "kind": "ordinary_chat"}, headers=NO_STORE)


@router.delete("/ask/history")
async def clear_ask_history(request: Request, device_id: str = Query(min_length=8, max_length=64)):
    del device_id
    return {"deleted": await memory.clear_chat(request.state.device["device_id"]), "investigations_deleted": 0}


@router.get("/higgins/context")
async def higgins_context(request: Request):
    return JSONResponse({"items": [item.wire() for item in await memory.current(request.state.device["device_id"])], "scope": "owner_only"}, headers=NO_STORE)


@router.post("/higgins/context", status_code=201)
async def add_higgins_context(body: memory.ContextWrite, request: Request):
    return JSONResponse({"item": (await memory.put(request.state.device["device_id"], body)).wire()}, status_code=201, headers=NO_STORE)


@router.delete("/higgins/context")
async def clear_higgins_context(request: Request):
    return {"deleted": await memory.clear(request.state.device["device_id"])}


@router.get("/higgins/history")
async def higgins_history(request: Request, limit: int = Query(default=25, ge=1, le=100), cursor: str | None = None,
                          status: str | None = None, gate: str | None = None, search: str | None = None):
    owner = request.state.device["device_id"]
    items: list[dict] = []
    history_query: dict = {"owner_id": owner, "deleted": False}
    if cursor:
        try:
            from datetime import datetime
            history_query["last_update"] = {"$lt": datetime.fromisoformat(cursor.replace("Z", "+00:00"))}
        except ValueError:
            pass
    if status:
        history_query["status"] = status
    if gate:
        history_query["gates"] = gate
    if search:
        history_query["conclusion"] = {"$regex": re.escape(search[:80]), "$options": "i"}
    history_rows = await db.higgins_investigation_history.find(history_query, {"_id": 0}).sort("last_update", -1).limit(limit + 1).to_list(limit + 1)
    for row in history_rows[:limit]:
        items.append({"id": row["history_id"], "kind": "investigation", "title": f"{(row.get('gates') or ['Apollo'])[0].title()} Gate investigation",
                      "summary": redact_investigation_secrets(row.get("conclusion", ""))[:300], "status": row.get("status", "completed"),
                      "occurredAt": row["last_update"], "caseStart": row["case_start"], "lastUpdate": row["last_update"], "gates": row.get("gates", []),
                      "attention": row.get("attention", "unknown"), "conclusion": redact_investigation_secrets(row.get("conclusion", ""))[:600],
                      "caseId": row.get("case_id"), "reportId": None, "reopenable": False})
    cases = await db.investigation_cases.find({"owner_id": owner, "deleted": False}, {"_id": 0, "case_id": 1, "status": 1, "gates": 1, "created_at": 1, "updated_at": 1, "response_revision": 1, "accepted_commits": 1}).sort("updated_at", -1).limit(limit).to_list(limit)
    for case in cases:
        turns = await investigation_repository.accepted_turns(owner, case)
        latest = max(turns, key=lambda turn: turn.committed_at) if turns else None
        summary = redact_investigation_secrets(latest.response.overview)[:300] if latest else "Investigation is still being prepared."
        active = case.get("status") not in {"complete", "expired", "cancelled", "failed"}
        items.append({"id": case["case_id"], "kind": "investigation", "title": f"{(case.get('gates') or ['Apollo'])[0].title()} Gate investigation", "summary": summary,
                      "status": "active" if active else "completed", "occurredAt": case.get("updated_at") or case["created_at"], "caseStart": case["created_at"],
                      "lastUpdate": case.get("updated_at") or case["created_at"], "gates": case.get("gates", []), "attention": latest.response.attention if latest else "unknown",
                      "conclusion": summary, "caseId": case["case_id"], "reportId": None, "reopenable": active})
    deduped = list({f"{item['kind']}:{item.get('caseId') or item['id']}": item for item in items}.values())
    deduped.sort(key=lambda item: item["occurredAt"], reverse=True)
    next_cursor = history_rows[limit - 1]["last_update"].isoformat() if len(history_rows) > limit else None
    return JSONResponse(jsonable_encoder({"items": deduped[:limit], "nextCursor": next_cursor, "redaction": "Secrets and raw evidence are excluded."}), headers=NO_STORE)


@router.delete("/higgins/history/{history_id}", status_code=204)
async def delete_higgins_history(history_id: str, request: Request):
    owner = request.state.device["device_id"]
    changed = await db.higgins_investigation_history.update_one({"owner_id": owner, "history_id": history_id, "deleted": False}, {"$set": {"deleted": True}})
    if not changed.matched_count:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="History item not found.")
    return None


@router.get("/higgins/scams")
async def government_scam_feed(limit: int = Query(default=50, ge=1, le=100)):
    return JSONResponse(jsonable_encoder(await government_alerts.snapshot(limit)), headers=NO_STORE)


@router.get("/feeds/health")
async def feed_health_report():
    """Settings > Diagnostics > Feed health: sync status of every enabled government feed."""
    return JSONResponse(jsonable_encoder(await feed_health.snapshot()), headers=NO_STORE)


@router.get("/rules/book")
async def rule_book():
    """Settings > Rule book: Apollo's rule book, word for word — the same file the admin portal shows."""
    return JSONResponse(rulebook.read(), headers=NO_STORE)


@router.get("/higgins/scams/diagnostics")
async def scam_alerts_diagnostics():
    """Transparent diagnostics view showing every filter stage for scam alerts.
    Returns counts at each step so the user can see exactly why N alerts appear."""
    from datetime import datetime, timezone
    from services import scam_analysis

    now = datetime.now(timezone.utc)
    recency_cutoff = government_alerts.RECENCY_CUTOFF

    # 1. Raw item count
    total_items = await db.learning_feed_items.count_documents({})

    # 2. Items with and without analysis
    with_analysis = await db.learning_feed_items.count_documents({"scam_analysis": {"$exists": True, "$ne": None}})
    without_analysis = total_items - with_analysis

    # 3. Items matching current analysis version
    current_version = scam_analysis.ANALYSIS_VERSION
    matching_version = await db.learning_feed_items.count_documents({"scam_analysis.analysisVersion": current_version})
    wrong_version = with_analysis - matching_version

    # 4. Walk the items that pass version filter and classify
    rows = await db.learning_feed_items.find(
        {"scam_analysis.analysisVersion": current_version},
        {"_id": 0, "title": 1, "url": 1, "source_id": 1, "published_at": 1, "scam_analysis": 1, "trust_status": 1}
    ).sort("published_at", -1).to_list(500)

    specific_scam = []
    emerging_pattern = []
    general_education = []
    stale_items = []
    unknown_tier = []

    for row in rows:
        analysis = row.get("scam_analysis", {})
        tier = analysis.get("tier", "unknown")
        published = row.get("published_at")
        reported = analysis.get("reportedDate")
        # Parse effective date
        effective = None
        if published:
            effective = published if published.tzinfo else published.replace(tzinfo=timezone.utc)
        elif reported:
            for fmt in ("%Y-%m-%d", "%Y-%m"):
                try:
                    effective = datetime.strptime(reported.strip(), fmt).replace(tzinfo=timezone.utc)
                    break
                except (ValueError, AttributeError):
                    pass

        age_days = (now - effective).days if effective else None
        is_stale = effective and (now - effective) > recency_cutoff

        item_info = {
            "title": row.get("title", "")[:100],
            "url": row.get("url", "")[:120],
            "source_id": row.get("source_id", ""),
            "tier": tier,
            "severity": analysis.get("severity", ""),
            "region": analysis.get("australianRelevance", ""),
            "published_at": published.isoformat() if published else None,
            "reported_date": reported,
            "effective_date": effective.isoformat() if effective else None,
            "age_days": age_days,
            "is_stale": bool(is_stale),
        }

        if is_stale:
            stale_items.append(item_info)
        elif tier == "specific_scam":
            specific_scam.append(item_info)
        elif tier == "emerging_pattern":
            emerging_pattern.append(item_info)
        elif tier == "general_education":
            general_education.append(item_info)
        else:
            unknown_tier.append(item_info)

    # 5. Feed source status
    feeds = await db.learning_feeds.find({"enabled": True}, {"_id": 0}).to_list(100)
    states = {r["feed_id"]: r for r in await db.learning_feed_state.find({}, {"_id": 0}).to_list(100)}
    feed_diagnostics = []
    for feed in feeds:
        state = states.get(feed["feed_id"], {})
        feed_diagnostics.append({
            "feed_id": feed["feed_id"],
            "source_id": feed.get("source_id", ""),
            "content_type": feed.get("content_type", ""),
            "status": state.get("status", "never_run"),
            "last_success": state.get("last_success_at"),
            "last_checked": state.get("last_checked_at"),
            "error": state.get("error"),
            "items_ingested": state.get("items_ingested", 0),
        })

    diagnostics = {
        "generated_at": now.isoformat(),
        "recency_cutoff_days": recency_cutoff.days,
        "analysis_version": current_version,
        "pipeline": {
            "1_total_feed_items": total_items,
            "2_with_analysis": with_analysis,
            "3_without_analysis_pending": without_analysis,
            "4_matching_current_version": matching_version,
            "5_wrong_version_needs_reanalysis": wrong_version,
            "6_after_filters": {
                "specific_scam_shown": len(specific_scam),
                "emerging_pattern_shown": len(emerging_pattern),
                "general_education_excluded": len(general_education),
                "stale_excluded": len(stale_items),
                "unknown_tier": len(unknown_tier),
            },
        },
        "shown_alerts": specific_scam,
        "shown_emerging": emerging_pattern,
        "excluded_stale": stale_items[:20],
        "excluded_education": general_education[:10],
        "feeds": feed_diagnostics,
    }

    return JSONResponse(jsonable_encoder(diagnostics), headers=NO_STORE)