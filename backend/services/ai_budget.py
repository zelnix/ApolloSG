"""Daily AI spending limits, enforced at the AI gateway (services/higgins/provider.py) and for TC FlyBy's web search
(services/brave_search.py).

Two limits, both changeable by an admin (routers/admin.py → /api/admin/ai-budget), kept in apollo_config:
    total      — everything ApolloSG spends on AI calls and paid searches in one UTC day (default $5.00)
    automated  — how much of that total automatic checks (mailbox monitoring, recovery, advisories, health checks)
                 may use (default $2.00). It sits INSIDE the total, never on top of it.

An ESTIMATED spending guard, not a guaranteed billing ceiling. Before each paid call its estimated cost is reserved
against today's ledger in one atomic update: the update matches only while reserved + estimate stays within the
limit(s), so concurrent calls can't jointly reserve more than the limit. After the call the reservation is settled to
the actual cost from the usage the provider reported, with no second limit check: when the actual cost is higher than
the estimate (estimate_call_usd's assumptions — 3 characters a token, a fixed allowance per image or audio part,
SEARCH_ALLOWANCE searches — can be exceeded), the day's total can go over the limit by that difference, and further
calls are refused until the next day or a higher limit. When the billing outcome
isn't known (a timeout, a dropped connection, an answer with no usage) the full estimate stays reserved — that is the
allowance kept for calls that may have been billed — until reconcile() is given the actual cost. A call refused before
it could be billed (rejected request, rate limit) releases its reservation.

Money is counted in whole micro-dollars so the atomic arithmetic is exact.
"""
from __future__ import annotations

import math
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from core.db import db, now_utc

DEFAULT_TOTAL_USD = 5.00
DEFAULT_AUTOMATED_USD = 2.00
TOTAL_KEY = "daily_total_ai_budget_usd"
AUTOMATED_KEY = "automated_daily_budget_usd"
# Searches the model may run when web search is attached to an AI call, reserved up front (each is billed).
SEARCH_ALLOWANCE = 5
# Estimated tokens for one image or audio part when the request is measured before sending.
BINARY_PART_TOKENS = 1600
_DAYS, _RESERVATIONS = "ai_spend_days", "ai_spend_reservations"


class BudgetExceeded(Exception):
    def __init__(self, which: str, spent_usd: float, limit_usd: float):
        self.which, self.spent_usd, self.limit_usd = which, spent_usd, limit_usd
        self.code = "budget_limit"
        label = "automatic checks' share of ApolloSG's daily AI spending limit" if which == "automated" else "ApolloSG's daily AI spending limit"
        super().__init__(f"This call would go over {label} (${limit_usd:.2f}; ${spent_usd:.2f} already used or held today).")


@dataclass
class Reservation:
    reservation_id: str | None   # None: nothing was reserved (a zero-cost call)
    day: str
    micros: int
    automated: bool


def micros(usd: float) -> int:
    return max(0, math.ceil(round(usd * 1_000_000, 3)))


def _usd(value: int) -> float:
    return round(value / 1_000_000, 6)


def day_of(when: datetime | None = None) -> str:
    return (when or now_utc()).astimezone(timezone.utc).strftime("%Y-%m-%d")


def automated(trigger_source: str | None) -> bool:
    from services.gemini_usage import AUTOMATED_SOURCES
    return (trigger_source or "") in AUTOMATED_SOURCES


async def ensure_indexes() -> None:
    await db[_DAYS].create_index("day", unique=True)
    await db[_RESERVATIONS].create_index("reservation_id", unique=True)
    await db[_RESERVATIONS].create_index([("state", 1), ("created_at", 1)])


# ── Limits ──────────────────────────────────────────────────────────────────
async def _config(key: str, env: str, default: float) -> float:
    row = await db.apollo_config.find_one({"key": key}, {"_id": 0, "value": 1})
    if row and row.get("value") is not None:
        return float(row["value"])
    raw = os.getenv(env, "").strip()
    return float(raw) if raw else default


async def limits() -> tuple[float, float]:
    """(total, automated) in USD. The automated limit can never exceed the total."""
    total = await _config(TOTAL_KEY, "APOLLO_DAILY_AI_BUDGET_USD", DEFAULT_TOTAL_USD)
    auto = await _config(AUTOMATED_KEY, "APOLLO_AUTOMATED_DAILY_AI_BUDGET_USD", DEFAULT_AUTOMATED_USD)
    return total, min(auto, total)


async def set_limits(*, total: float | None = None, automated_usd: float | None = None) -> tuple[float, float]:
    current_total, current_auto = await limits()
    new_total = current_total if total is None else float(total)
    new_auto = current_auto if automated_usd is None else float(automated_usd)
    if new_total < 0 or new_auto < 0:
        raise ValueError("Spending limits can't be negative.")
    if new_auto > new_total:
        raise ValueError("The automatic-check limit is part of the total, so it can't be more than the total.")
    for key, value in ((TOTAL_KEY, new_total), (AUTOMATED_KEY, new_auto)):
        await db.apollo_config.update_one({"key": key}, {"$set": {"value": value, "updated_at": now_utc()}}, upsert=True)
    return new_total, new_auto


async def today() -> dict:
    """Today's ledger in USD: held (reserved, settled and unknown together), the automatic share, and the allowance
    still held for calls whose billing isn't known."""
    total, auto = await limits()
    row = await db[_DAYS].find_one({"day": day_of()}, {"_id": 0}) or {}
    unknown = await db[_RESERVATIONS].aggregate([{"$match": {"day": day_of(), "state": "unknown"}},
                                                  {"$group": {"_id": None, "m": {"$sum": "$micros"}}}]).to_list(1)
    return {"day": day_of(), "totalLimitUsd": total, "automatedLimitUsd": auto, "usedUsd": _usd(row.get("total_micros", 0)),
            "automatedUsedUsd": _usd(row.get("automated_micros", 0)), "unknownBillingHeldUsd": _usd(unknown[0]["m"] if unknown else 0),
            "calls": row.get("calls", 0)}


# ── Reserve → settle ────────────────────────────────────────────────────────
async def _ensure_day(day: str) -> None:
    try:
        await db[_DAYS].update_one({"day": day}, {"$setOnInsert": {"day": day, "total_micros": 0, "automated_micros": 0, "calls": 0}}, upsert=True)
    except DuplicateKeyError:
        pass   # another call created it at the same moment


async def reserve(estimate_usd: float, *, automated: bool, purpose: str, model: str, provider: str, correlation_id: str | None = None,
                  device_id: str | None = None, case_id: str | None = None, job_id: str | None = None) -> Reservation:
    """Hold the estimated cost of one call, atomically, or raise BudgetExceeded and send nothing."""
    amount = micros(estimate_usd)
    day = day_of()
    if amount == 0:
        return Reservation(None, day, 0, automated)
    total, auto = await limits()
    await _ensure_day(day)
    match: dict = {"day": day, "total_micros": {"$lte": micros(total) - amount}}
    inc = {"total_micros": amount, "calls": 1}
    if automated:
        match["automated_micros"] = {"$lte": micros(auto) - amount}
        inc["automated_micros"] = amount
    held = await db[_DAYS].find_one_and_update(match, {"$inc": inc, "$set": {"updated_at": now_utc()}}, return_document=ReturnDocument.AFTER)
    if held is None:
        row = await db[_DAYS].find_one({"day": day}, {"_id": 0}) or {}
        over_auto = automated and row.get("automated_micros", 0) + amount > micros(auto)
        raise BudgetExceeded("automated" if over_auto else "total", _usd(row.get("automated_micros" if over_auto else "total_micros", 0)),
                             auto if over_auto else total)
    rid = str(uuid.uuid4())
    await db[_RESERVATIONS].insert_one({"reservation_id": rid, "day": day, "micros": amount, "estimate_micros": amount, "automated": automated,
                                        "state": "reserved", "purpose": purpose, "model": model, "provider": provider,
                                        "correlation_id": correlation_id, "device_id": device_id, "case_id": case_id, "job_id": job_id,
                                        "created_at": now_utc()})
    return Reservation(rid, day, amount, automated)


async def _settle(reservation_id: str, actual_usd: float, *, from_states: tuple[str, ...], state: str) -> bool:
    actual = micros(actual_usd)
    row = await db[_RESERVATIONS].find_one_and_update(
        {"reservation_id": reservation_id, "state": {"$in": list(from_states)}},
        {"$set": {"state": state, "actual_micros": actual, "settled_at": now_utc()}}, return_document=ReturnDocument.BEFORE)
    if row is None:
        return False   # already settled: a reservation is adjusted once
    delta = actual - row["micros"]
    await db[_RESERVATIONS].update_one({"reservation_id": reservation_id}, {"$set": {"micros": actual}})
    if delta:
        inc = {"total_micros": delta, **({"automated_micros": delta} if row.get("automated") else {})}
        await db[_DAYS].update_one({"day": row["day"]}, {"$inc": inc, "$set": {"updated_at": now_utc()}})
    return True


async def settle(reservation: Reservation, actual_usd: float) -> None:
    """The call's actual cost is known (0 for a call refused before it could be billed)."""
    if reservation.reservation_id:
        await _settle(reservation.reservation_id, actual_usd, from_states=("reserved",), state="settled")


async def unknown(reservation: Reservation) -> None:
    """The billing outcome isn't known: the full estimate stays held until reconcile()."""
    if reservation.reservation_id:
        await db[_RESERVATIONS].update_one({"reservation_id": reservation.reservation_id, "state": "reserved"},
                                           {"$set": {"state": "unknown", "unknown_at": now_utc()}})


async def reconcile(reservation_id: str, actual_usd: float) -> bool:
    """Actual usage became available for a call whose billing wasn't known: replace the held estimate with it."""
    return await _settle(reservation_id, actual_usd, from_states=("unknown",), state="reconciled")


# ── Estimating one AI call before it is sent ────────────────────────────────
def estimate_call_usd(model: str, provider: str, payload_audit: dict, *, web_search: bool, max_output_tokens: int) -> float:
    """An estimate, not an enforced maximum: the request's text (3 characters a token, rounded up) plus each image or
    audio part (BINARY_PART_TOKENS), the most output the call may produce at the dearer of the output and thinking
    rates, and SEARCH_ALLOWANCE searches when web search is attached. The provider can bill more input tokens or
    searches than this assumes."""
    from services.gemini_usage import SEARCH_QUERY_USD, pricing_for
    rates = pricing_for(model)
    chars = int(payload_audit.get("system_chars") or 0) + int(payload_audit.get("total_text_chars") or 0)
    input_tokens = math.ceil(chars / 3) + BINARY_PART_TOKENS * int(payload_audit.get("total_binary_parts") or 0)
    cost = input_tokens / 1_000_000 * rates["input"] + max_output_tokens / 1_000_000 * max(rates["output"], rates["thinking"])
    if web_search:
        cost += SEARCH_ALLOWANCE * SEARCH_QUERY_USD.get(provider, max(SEARCH_QUERY_USD.values()))
    return cost
