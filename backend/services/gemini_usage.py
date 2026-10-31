"""Gemini API usage tracking and cost estimation.

Persists actual token counts from every Gemini generation call.
Calculates estimated costs using model-specific pricing rates.
Provides aggregated usage reports by model, purpose and time period.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from core.db import db

# ── Collection ───────────────────────────────────────────────────────────────
COLLECTION = "gemini_usage"


# ── Model pricing (USD per 1M tokens) ───────────────────────────────────────
# Source: https://ai.google.dev/gemini-api/docs/pricing (retrieved Oct 2026)
# Rates effective through 31 Dec 2026 unless noted.
# IMPORTANT: These are ESTIMATES for reconciliation. Actual Google billing
# charges may differ due to caching, tiered pricing, or rate changes.

PRICING_VERSION = "2026-10-20"

# Each entry: { input, output, thinking, cached_input } in USD per 1M tokens.
# "thinking" tokens are billed at the output rate for most models.
# "cached_input" is the discounted rate for context-cached input tokens.
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Magnum DI's investigation model (standard tier, ai.google.dev/gemini-api/docs/pricing).
    "gemini-3.1-flash-lite": {
        "input": 0.25,          # text / image / video
        "output": 1.50,
        "thinking": 1.50,       # same as output
        "cached_input": 0.025,
    },
    "gemini-3.8-flash": {
        "input": 0.75,
        "output": 3.75,
        "thinking": 3.75,      # same as output
        "cached_input": 0.075,  # ~10x discount
    },
    "gemini-3.5-flash": {
        "input": 1.50,
        "output": 9.00,
        "thinking": 9.00,
        "cached_input": 0.15,
    },
    "gemini-3.7-flash": {
        "input": 0.75,
        "output": 3.75,
        "thinking": 3.75,
        "cached_input": 0.075,
    },
    "gemini-3.6-flash": {
        "input": 0.75,
        "output": 3.75,
        "thinking": 3.75,
        "cached_input": 0.075,
    },
    "gemini-2.5-flash": {
        "input": 0.30,
        "output": 2.50,
        "thinking": 2.50,
        "cached_input": 0.030,
    },
    "gemini-2.5-flash-lite": {
        "input": 0.10,
        "output": 0.40,
        "thinking": 0.40,
        "cached_input": 0.010,
    },
    "gemini-2.5-pro": {
        "input": 1.25,
        "output": 10.00,
        "thinking": 10.00,
        "cached_input": 0.125,
    },
    "gemini-3.1-pro-preview": {
        "input": 1.25,
        "output": 10.00,
        "thinking": 10.00,
        "cached_input": 0.125,
    },
    "gemini-3-flash-preview": {
        "input": 0.75,
        "output": 3.75,
        "thinking": 3.75,
        "cached_input": 0.075,
    },
    # Anthropic Claude (platform.claude.com/docs/en/about-claude/pricing; Haiku 5.5 at its up-to-100k-token prompt price).
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "thinking": 0.50, "cached_input": 0.01},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "thinking": 10.00, "cached_input": 0.10},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "thinking": 20.00, "cached_input": 0.20},
    # OpenAI (developers.openai.com/api/docs/models; reasoning tokens are billed as output).
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20, "thinking": 1.20, "cached_input": 0.02},
    "gpt-5.4-mini": {"input": 0.75, "output": 4.50, "thinking": 4.50, "cached_input": 0.075},
    "gpt-5.6-terra": {"input": 2.00, "output": 12.00, "thinking": 12.00, "cached_input": 0.20},
    "gpt-5.4": {"input": 2.50, "output": 15.00, "thinking": 15.00, "cached_input": 0.25},
    "gpt-5.6-sol": {"input": 4.00, "output": 20.00, "thinking": 20.00, "cached_input": 0.40},
    "gpt-5.5": {"input": 5.00, "output": 30.00, "thinking": 30.00, "cached_input": 0.50},
}

# Fallback pricing for unknown models
_DEFAULT_PRICING = {
    "input": 1.00,
    "output": 5.00,
    "thinking": 5.00,
    "cached_input": 0.10,
}

# Web search is billed per search the model runs, by provider: Grounding with Google Search on Gemini 3 models
# $14 per 1,000 queries (list price before any monthly free allowance); Claude's web search $10 per 1,000 searches;
# OpenAI's web search tool $10 per 1,000 calls.
SEARCH_QUERY_USD = {"gemini": 0.014, "anthropic": 0.010, "openai": 0.010}


def pricing_for(model: str) -> dict[str, float]:
    """Pricing for a model, falling back to conservative defaults."""
    return MODEL_PRICING.get(model, _DEFAULT_PRICING)


def estimate_cost_usd(model: str, tokens: dict[str, int | None]) -> float:
    """Estimated cost in USD from the token counts the provider reported.

    Every adapter reports candidate (answer) tokens WITHOUT the thinking tokens (services/higgins/ai_request.py), so the
    two are charged separately — candidates at the output rate, thinking at the thinking rate — and never subtracted
    from each other. Cached input is charged at the cached rate and the rest of the input at the input rate.
    Missing values are left out, never treated as zero. 0.0 when no usable token data is present.
    """
    pricing = pricing_for(model)
    cost = 0.0
    input_tokens, cached_tokens = tokens.get("input") or 0, tokens.get("cached_input") or 0
    if input_tokens > 0:
        cached = min(cached_tokens, input_tokens)
        cost += cached / 1_000_000 * pricing["cached_input"] + (input_tokens - cached) / 1_000_000 * pricing["input"]
    cost += (tokens.get("candidates") or 0) / 1_000_000 * pricing["output"]
    cost += (tokens.get("thinking") or 0) / 1_000_000 * pricing["thinking"]
    return cost


def _first(usage: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        if usage.get(key) is not None:
            return usage[key]
    return None


def _extract_tokens(usage_metadata: dict[str, Any] | None) -> dict[str, int | None]:
    """Token counts from the gateway's usage record, preserving None for missing values. `candidates` (also kept as
    `output`) excludes thinking; `thinking` is counted on its own."""
    if not usage_metadata:
        return {"input": None, "output": None, "candidates": None, "total": None, "thinking": None, "cached_input": None, "admission_input": None}
    candidates = _first(usage_metadata, "candidates_token_count", "output_tokens")
    return {
        "input": _first(usage_metadata, "prompt_token_count", "input_tokens"),
        "output": candidates,
        "candidates": candidates,
        "total": _first(usage_metadata, "total_token_count", "total_tokens"),
        "thinking": _first(usage_metadata, "thoughts_token_count", "thinking_tokens"),
        "cached_input": _first(usage_metadata, "cached_content_token_count", "cached_tokens"),
        "admission_input": usage_metadata.get("admission_input_tokens"),
    }


def call_cost(model: str, provider: str, usage_metadata: dict[str, Any] | None, search_queries: int = 0, *, simulated: bool = False) -> float:
    """One call's estimated cost: its tokens plus every web search it ran (each is billed). A simulated call costs nothing."""
    if simulated:
        return 0.0
    return estimate_cost_usd(model, _extract_tokens(usage_metadata)) + search_queries * SEARCH_QUERY_USD.get(provider, SEARCH_QUERY_USD["gemini"])


# ── Trigger source constants ────────────────────────────────────────────────
# Every Gemini call records who/what initiated it, enabling cost attribution.
class TriggerSource:
    USER_INITIATED = "user_initiated"
    MAILBOX_MONITOR = "mailbox_monitor"
    RECOVERY_RESUME = "recovery_resume"
    VALIDATION_TEST = "validation_test"
    HEALTH_CHECK = "health_check"
    SCAM_ANALYSIS = "scam_analysis"
    CHAT = "chat"
    RESEARCH = "research"
    MSG_CHECK = "msg_check"
    PHONE_CHECK = "phone_check"
    TRIAGE = "triage"
    BACKGROUND_TEXT = "background_text"

# Sources considered "automated" for budget-cap purposes
AUTOMATED_SOURCES = frozenset({
    TriggerSource.MAILBOX_MONITOR,
    TriggerSource.RECOVERY_RESUME,
    TriggerSource.SCAM_ANALYSIS,
    TriggerSource.HEALTH_CHECK,
})

async def check_automated_budget() -> tuple[bool, float, float]:
    """Whether automatic checks still have room in today's spending ledger (services/ai_budget.py), counting what is
    held for calls whose billing isn't known. An early guard only: the gateway's reservation is what enforces it.

    Returns (allowed, used_usd, automated_limit_usd).
    """
    from services import ai_budget
    ledger = await ai_budget.today()
    used, limit = ledger["automatedUsedUsd"], ledger["automatedLimitUsd"]
    return (used < limit and ledger["usedUsd"] < ledger["totalLimitUsd"], used, limit)


def _case_of(correlation_id: str | None) -> str | None:
    return correlation_id.removeprefix("case-") if (correlation_id or "").startswith("case-") else None


async def record_usage(
    *,
    record_id: str | None = None,
    correlation_id: str | None = None,
    model: str,
    provider: str = "gemini",
    purpose: str,
    call_type: str,
    success: bool,
    failure_code: str | None = None,
    usage_metadata: dict[str, Any] | None = None,
    duration_ms: int | None = None,
    extra: dict[str, Any] | None = None,
    device_id: str | None = None,
    case_id: str | None = None,
    job_id: str | None = None,
    reservation_id: str | None = None,
) -> str:
    """Persist one AI call's usage: model, purpose, time, device, case, job, input / candidate / thinking / cached tokens,
    web searches and estimated cost. A failed call records whatever usage the provider reported before it failed.

    Returns the record_id used (generated if not provided). Prevents duplicates via upsert on record_id.
    """
    if record_id is None:
        record_id = str(uuid.uuid4())

    tokens = _extract_tokens(usage_metadata)
    search_queries = int((extra or {}).get("search_queries") or 0)
    simulated = bool((extra or {}).get("simulated"))
    search_cost = 0.0 if simulated else search_queries * SEARCH_QUERY_USD.get(provider, SEARCH_QUERY_USD["gemini"])
    cost = call_cost(model, provider, usage_metadata, search_queries, simulated=simulated)
    now = datetime.now(timezone.utc)

    doc = {
        "record_id": record_id,
        "correlation_id": correlation_id,
        "device_id": device_id,
        "case_id": case_id or _case_of(correlation_id),
        "job_id": job_id,
        "reservation_id": reservation_id,
        "timestamp": now,
        "provider": provider,
        "model": model,
        "purpose": purpose,
        "call_type": call_type,
        "success": success,
        "failure_code": failure_code,
        "tokens": tokens,
        "estimated_cost_usd": cost if cost > 0 else None,
        "search_queries": search_queries,
        "search_cost_usd": search_cost,
        "pricing_version": PRICING_VERSION,
        "pricing_rates": pricing_for(model),
        "duration_ms": duration_ms,
        "usage_metadata_available": usage_metadata is not None,
    }
    if extra:
        doc["extra"] = extra

    await db[COLLECTION].update_one(
        {"record_id": record_id},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return record_id


async def record_search(*, record_id: str, provider: str, model: str, purpose: str, success: bool, failure_code: str | None, cost_usd: float,
                        correlation_id: str | None, device_id: str | None, case_id: str | None, trigger_source: str | None) -> None:
    """One paid web-search request that isn't an AI call (TC FlyBy's Brave search): no tokens, one search, its price."""
    now = datetime.now(timezone.utc)
    await db[COLLECTION].update_one({"record_id": record_id}, {"$set": {
        "record_id": record_id, "correlation_id": correlation_id, "device_id": device_id, "case_id": case_id or _case_of(correlation_id),
        "job_id": None, "reservation_id": record_id, "timestamp": now, "provider": provider, "model": model, "purpose": purpose,
        "call_type": "web_search", "success": success, "failure_code": failure_code, "tokens": _extract_tokens(None),
        "estimated_cost_usd": cost_usd or None, "search_queries": 1, "search_cost_usd": cost_usd, "pricing_version": PRICING_VERSION,
        "duration_ms": None, "usage_metadata_available": False, "extra": {"trigger_source": trigger_source} if trigger_source else {}},
        "$setOnInsert": {"created_at": now}}, upsert=True)


async def get_usage_report(
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    model: str | None = None,
    purpose: str | None = None,
) -> dict[str, Any]:
    """Aggregated usage report with breakdowns by model and purpose.

    Returns calls, tokens, estimated cost, and breakdowns.
    """
    match: dict[str, Any] = {}
    if start or end:
        ts_filter: dict[str, Any] = {}
        if start:
            ts_filter["$gte"] = start
        if end:
            ts_filter["$lte"] = end
        match["timestamp"] = ts_filter
    if model:
        match["model"] = model
    if purpose:
        match["purpose"] = purpose

    pipeline = [
        {"$match": match} if match else {"$match": {}},
        {
            "$group": {
                "_id": {"model": "$model", "purpose": "$purpose"},
                "total_calls": {"$sum": 1},
                "successful_calls": {"$sum": {"$cond": ["$success", 1, 0]}},
                "failed_calls": {"$sum": {"$cond": ["$success", 0, 1]}},
                "total_input_tokens": {"$sum": {"$ifNull": ["$tokens.input", 0]}},
                "total_output_tokens": {"$sum": {"$ifNull": ["$tokens.output", 0]}},
                "total_thinking_tokens": {"$sum": {"$ifNull": ["$tokens.thinking", 0]}},
                "total_cached_tokens": {"$sum": {"$ifNull": ["$tokens.cached_input", 0]}},
                "total_estimated_cost": {"$sum": {"$ifNull": ["$estimated_cost_usd", 0]}},
                "calls_with_usage_data": {"$sum": {"$cond": ["$usage_metadata_available", 1, 0]}},
                "calls_without_usage_data": {"$sum": {"$cond": ["$usage_metadata_available", 0, 1]}},
                "first_call": {"$min": "$timestamp"},
                "last_call": {"$max": "$timestamp"},
            }
        },
        {"$sort": {"total_estimated_cost": -1}},
    ]

    rows = await db[COLLECTION].aggregate(pipeline).to_list(200)

    # Build summary
    total_calls = sum(r["total_calls"] for r in rows)
    total_cost = sum(r["total_estimated_cost"] for r in rows)
    total_input = sum(r["total_input_tokens"] for r in rows)
    total_output = sum(r["total_output_tokens"] for r in rows)
    total_thinking = sum(r["total_thinking_tokens"] for r in rows)
    total_cached = sum(r["total_cached_tokens"] for r in rows)
    with_usage = sum(r["calls_with_usage_data"] for r in rows)
    without_usage = sum(r["calls_without_usage_data"] for r in rows)

    breakdowns = []
    for r in rows:
        breakdowns.append({
            "model": r["_id"]["model"],
            "purpose": r["_id"]["purpose"],
            "calls": r["total_calls"],
            "successful": r["successful_calls"],
            "failed": r["failed_calls"],
            "input_tokens": r["total_input_tokens"],
            "output_tokens": r["total_output_tokens"],
            "thinking_tokens": r["total_thinking_tokens"],
            "cached_tokens": r["total_cached_tokens"],
            "estimated_cost_usd": round(r["total_estimated_cost"], 6),
            "period": {
                "first": r["first_call"].isoformat() if r["first_call"] else None,
                "last": r["last_call"].isoformat() if r["last_call"] else None,
            },
        })

    return {
        "disclaimer": "Costs are ESTIMATES based on published model pricing. "
                      "Actual Google billing charges may differ due to caching discounts, "
                      "tiered pricing, promotional credits or rate changes.",
        "pricing_version": PRICING_VERSION,
        "period": {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        },
        "summary": {
            "total_calls": total_calls,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_thinking_tokens": total_thinking,
            "total_cached_tokens": total_cached,
            "estimated_total_cost_usd": round(total_cost, 6),
            "calls_with_usage_data": with_usage,
            "calls_without_usage_data": without_usage,
        },
        "by_model_and_purpose": breakdowns,
    }


async def get_investigation_trace(correlation_id: str) -> dict[str, Any]:
    """Per-call chronological trace for a single investigation/correlation.

    Returns every Gemini call with token breakdown, payload audit,
    and cumulative totals — directly suitable for building the
    Round | Reason | Input | Output | Cumulative | Content table.
    """
    rows = await db[COLLECTION].find(
        {"correlation_id": correlation_id},
        {"_id": 0}
    ).sort("timestamp", 1).to_list(200)

    calls = []
    cumulative_input = 0
    cumulative_output = 0
    cumulative_thinking = 0
    cumulative_cost = 0.0

    for idx, row in enumerate(rows):
        tokens = row.get("tokens", {})
        inp = tokens.get("input") or tokens.get("admission_input") or 0
        out = tokens.get("output") or 0
        thinking = tokens.get("thinking") or 0
        cached = tokens.get("cached_input") or 0
        cost = row.get("estimated_cost_usd") or 0.0

        cumulative_input += inp
        cumulative_output += out
        cumulative_thinking += thinking
        cumulative_cost += cost

        audit = (row.get("extra") or {}).get("payload_audit", {})
        content_summary = []
        for r in audit.get("rounds", []):
            label = r.get("role", "?")
            parts = []
            if r.get("text_chars"):
                parts.append(f"{r['text_chars']:,} chars")
            if r.get("binary_parts"):
                parts.append(f"{r['binary_parts']} image(s)")
            if r.get("fn_calls"):
                parts.append(f"{r['fn_calls']} fn_call(s)")
            if r.get("fn_responses"):
                parts.append(f"{r['fn_responses']} fn_response(s)")
            content_summary.append(f"{label}: {', '.join(parts) or 'empty'}")

        calls.append({
            "call_number": idx + 1,
            "call_type": row.get("call_type"),
            "purpose": row.get("purpose"),
            "model": row.get("model"),
            "success": row.get("success"),
            "failure_code": row.get("failure_code"),
            "timestamp": row.get("timestamp").isoformat() if row.get("timestamp") else None,
            "duration_ms": row.get("duration_ms"),
            "tokens": {
                "input": inp,
                "output": out,
                "thinking": thinking,
                "cached_input": cached,
                "admission_input": tokens.get("admission_input"),
            },
            "estimated_cost_usd": round(cost, 6),
            "cumulative": {
                "input_tokens": cumulative_input,
                "output_tokens": cumulative_output,
                "thinking_tokens": cumulative_thinking,
                "estimated_cost_usd": round(cumulative_cost, 6),
            },
            "payload_audit": {
                "system_chars": audit.get("system_chars"),
                "system_est_tokens": audit.get("system_est_tokens"),
                "content_rounds": audit.get("content_rounds"),
                "total_text_chars": audit.get("total_text_chars"),
                "total_est_tokens": audit.get("total_est_tokens"),
                "total_binary_parts": audit.get("total_binary_parts"),
                "total_function_calls": audit.get("total_function_calls"),
                "total_function_responses": audit.get("total_function_responses"),
            } if audit else None,
            "content_summary": content_summary or None,
        })

    return {
        "correlation_id": correlation_id,
        "total_calls": len(calls),
        "totals": {
            "input_tokens": cumulative_input,
            "output_tokens": cumulative_output,
            "thinking_tokens": cumulative_thinking,
            "estimated_cost_usd": round(cumulative_cost, 6),
        },
        "calls": calls,
    }


async def ensure_indexes():
    """Create indexes for efficient querying."""
    coll = db[COLLECTION]
    await coll.create_index("record_id", unique=True)
    await coll.create_index("correlation_id")
    await coll.create_index([("device_id", 1), ("timestamp", 1)])
    await coll.create_index("timestamp")
    await coll.create_index([("model", 1), ("purpose", 1), ("timestamp", 1)])
