"""Deep Investigation (DI) transaction record — the real Magnum DI processing record.

One record per AI-gateway call: exactly what was prepared for the provider (the real system prompt,
the real investigation context, and the post-redaction attachments that would be transmitted), what
the provider — the selected live provider or the preview simulator — returned, and the processing statistics
available for that call.

This is NOT evidence. Evidence stays the original evidentiary source Apollo received or detected;
this record only describes Magnum DI's processing of it. Nothing here modifies evidence, and the
attachment entries describe the post-redaction derivative that the production AI boundary
receives — never an original unredacted attachment.
"""
from __future__ import annotations

import logging
import struct
from typing import Any

from core.db import db, now_utc

_log = logging.getLogger("apollo.di_record")

# Rough public per-million-token prices used only for an ESTIMATE, clearly labelled as such.
_EST_PRICE_PER_M = {"input": 0.30, "output": 2.50}


def _image_dimensions(data: bytes, mime: str) -> dict | None:
    """Width/height for the formats Apollo actually sends, read from the bytes themselves."""
    try:
        if mime == "image/png" and data[:8] == b"\x89PNG\r\n\x1a\n":
            width, height = struct.unpack(">II", data[16:24])
            return {"width": width, "height": height}
        if mime in ("image/jpeg", "image/jpg"):
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                    height, width = struct.unpack(">HH", data[i + 5:i + 9])
                    return {"width": width, "height": height}
                i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    except Exception:
        return None
    return None


def describe_request(system: str, contents: Any, web_search: bool) -> dict:
    """The actual final request at the AI gateway — not a reconstruction."""
    from services.higgins.ai_request import Message, Part

    prompt_parts: list[str] = []
    attachments: list[dict] = []
    items = contents if isinstance(contents, list) else [contents]
    for item in items:
        if isinstance(item, str):
            prompt_parts.append(item)
            continue
        for part in item.parts if isinstance(item, Message) else [item] if isinstance(item, Part) else []:
            if part.text:
                prompt_parts.append(part.text)
            if part.data is not None:
                data = part.data
                mime = part.mime_type or "application/octet-stream"
                entry: dict[str, Any] = {
                    "mimeType": mime,
                    "sizeBytes": len(data),
                    # Apollo's privacy screening and redaction run on the device and during ingestion,
                    # before anything reaches this boundary, so what is here is already the derivative.
                    "privacyScreening": "completed_before_boundary",
                    "redactionStatus": "post_redaction_derivative",
                    "transmittedForm": f"{mime}, {len(data)} bytes (post-redaction derivative)",
                }
                dims = _image_dimensions(data, mime)
                if dims:
                    entry["dimensions"] = dims
                attachments.append(entry)

    tool_names = ["web_search"] if web_search else []

    prompt_text = "\n\n".join(prompt_parts)
    return {
        "systemPrompt": system or "",
        "investigationPrompt": prompt_text,
        "attachments": attachments,
        "attachmentCount": len(attachments),
        "tools": tool_names,
        "requestBytes": len((system or "").encode()) + len(prompt_text.encode())
                        + sum(a["sizeBytes"] for a in attachments),
    }


def estimate_cost(usage: dict | None) -> dict:
    usage = usage or {}
    prompt = usage.get("prompt_token_count") or 0
    output = usage.get("candidates_token_count") or 0
    cost = (prompt / 1_000_000) * _EST_PRICE_PER_M["input"] + (output / 1_000_000) * _EST_PRICE_PER_M["output"]
    return {"amountUsd": round(cost, 6), "basis": "estimated", "note": "Estimated from token counts and public list prices."}


async def save_di_record(*, correlation_id: str | None, owner: str | None, investigation_id: str | None,
                         model: str, purpose: str, simulated: bool, provider: str = "gemini", environment: str, status: str,
                         request: dict, response_text: str, finish_reason: str | None,
                         usage: dict | None, duration_ms: int, retries: int, calls: int,
                         failure_code: str | None = None) -> None:
    """Persist one DI transaction. Never raises into the investigation pipeline."""
    usage = usage or {}
    record = {
        "correlation_id": correlation_id,
        "owner": owner,
        "investigation_id": investigation_id,
        "created_at": now_utc(),
        "environment": environment,
        "simulated": simulated,
        "engine": "Magnum DI",
        "provider": provider,
        "model_requested": model,
        "purpose": purpose,
        "status": status,
        "failure_code": failure_code,
        "request": request,
        "response": {"text": response_text, "finishReason": finish_reason},
        "processing": {
            "promptTokens": usage.get("prompt_token_count"),
            "outputTokens": usage.get("candidates_token_count"),
            "totalTokens": usage.get("total_token_count"),
            "cachedTokens": usage.get("cached_content_token_count"),
            "tokensAreEstimates": bool(usage.get("estimated")),
            "tokensAreSimulated": bool(usage.get("simulated")),
            "attachmentCount": request.get("attachmentCount", 0),
            "requestBytes": request.get("requestBytes"),
            "durationMs": duration_ms,
            "geminiCalls": calls,
            "retries": retries,
            "cacheStatus": "hit" if (usage.get("cached_content_token_count") or 0) > 0 else "none",
            "cost": estimate_cost(usage) | ({"basis": "simulated"} if simulated else {}),
        },
    }
    try:
        await db.di_transactions.insert_one(record)
    except Exception:
        _log.warning("di_record: failed to persist DI transaction for %s", correlation_id, exc_info=True)


def wire(record: dict) -> dict:
    """Shape one stored record for the app's DI tab: what happened, never how much it cost. Token counts, cost, timings,
    the prompts sent and the full reply are Apollo's own diagnostics: they stay in the Admin Portal (`admin_records`).
    The provider and model are never sent to the app: the DI tab names Magnum DI only."""
    created = record.get("created_at")
    request = record.get("request") or {}
    return {
        "investigationId": record.get("investigation_id") or (record.get("correlation_id") or "").removeprefix("case-"),
        "engine": record.get("engine", "Magnum DI"),
        "environment": record.get("environment", "unknown"),
        "mode": "Simulated" if record.get("simulated") else "Live",
        "simulated": bool(record.get("simulated")),
        "status": record.get("status"),
        "failureCode": record.get("failure_code"),
        "occurredAt": _iso(created),
        # What was handed over, described: the attachments' screening and form, and whether web search was on.
        "request": {"attachments": request.get("attachments") or [], "attachmentCount": request.get("attachmentCount", 0),
                    "tools": [_TOOL_NAMES.get(t, t) for t in request.get("tools") or []]},
        "notice": "SIMULATED — the preview stood in for the outside service Magnum DI calls; everything else ran exactly as in production" if record.get("simulated") else None,
    }


async def admin_records(case_id: str) -> list[dict]:
    """Every stored DI transaction for one case, in full (prompts, reply, tokens, cost, model) — the Admin Portal only."""
    cursor = db.di_transactions.find({"correlation_id": f"case-{case_id}"}, {"_id": 0, "owner": 0}).sort("created_at", 1)
    return [doc async for doc in cursor]


# Tool and route names as the DI tab shows them — no provider's product name (older records say google_search).
_TOOL_NAMES = {"google_search": "web_search"}
_FLYBY_FIELDS = ("resolved", "answeredBy", "outcome", "basis", "messageType", "pattern", "searchCalls", "searchQueries",
                 "cacheHits", "magnumNeeded", "magnumSearch", "reusedOnRetry", "gaps", "issues", "simulated")


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


async def decision_trace(owner: str, case_id: str) -> dict:
    """The recorded decision path for one case: the deterministic Triage record, what TC FlyBy checked and
    decided, whether Magnum DI was engaged, and how Higgins presented the result. Recorded data only —
    a stage with no record is null, never inferred."""
    from services import rulebook
    case = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id}, {"_id": 0, "routing": 1}) or {}
    routing = case.get("routing") or {}
    triage = await db.triage_investigations.find_one({"device_id": owner, "investigation_case_id": case_id},
                                                     {"_id": 0, "record": 1}, sort=[("evaluated_at", -1)])
    recorded, magnum, fidelity = routing.get("tc_flyby"), routing.get("magnum"), routing.get("fidelity")
    flyby = None
    if recorded:
        flyby = {key: recorded.get(key) for key in _FLYBY_FIELDS}
        flyby["ranAt"] = _iso(recorded.get("ranAt"))
        flyby["checks"] = [{**c, "route": _TOOL_NAMES.get(c.get("route"), c.get("route"))} for c in recorded.get("checks") or []]
    return {
        "triage": (triage or {}).get("record"),
        "flyby": flyby,
        "magnum": {"webSearch": bool(magnum.get("search")), "searchQueries": magnum.get("searchQueries") or 0,
                   "itemsSent": magnum.get("itemsSent") or 0, "simulated": bool(magnum.get("simulated")),
                   "at": _iso(magnum.get("at"))} if magnum else None,
        "answeredBy": routing.get("answeredBy"),
        "outcome": routing.get("outcome"),
        "completion": routing.get("completion"),
        # The settling rule by name and sentence; its rule-book code stays in the Admin Portal.
        "settledReason": {k: reason[k] for k in ("rule", "by", "sentence")} if (reason := rulebook.settled_reason(routing)) else None,
        "higgins": {"status": fidelity.get("status"), "mode": fidelity.get("mode"), "attempts": fidelity.get("attempts")} if fidelity else None,
    }


async def get_di_records(owner: str, case_id: str) -> list[dict]:
    """Magnum DI's own records for one case. TC FlyBy's search call is recorded under the same case but is not
    Magnum DI: it stays in the Admin Portal, so a case TC FlyBy settled never shows Magnum DI as engaged. Access is
    authorised by the caller (it resolves the case for this device first)."""
    cursor = db.di_transactions.find({"correlation_id": f"case-{case_id}", "purpose": {"$ne": "tc_flyby_search"}}).sort("created_at", 1)
    return [wire(doc) async for doc in cursor]
