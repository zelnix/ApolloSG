"""Records saved under TC Hawkeye's old internal name ("teddy") move to its current names, once, at startup.

Moved: a case's routing record (`routing.teddy` → `routing.tc_flyby`), its encrypted check record (`teddy_ciphertext`
→ `tc_flyby_ciphertext`), who settled it (`teddy_*` → `tc_flyby_*`), TC Hawkeye's internal evidence items, and the purpose
on usage and DI transaction records. Turn commits are immutable (their digest covers the whole body), so they stay as
recorded. The old search cache, which nothing reads any more, is dropped. Running it again finds nothing to do.
"""
from __future__ import annotations

import logging
from typing import Any

from core.db import db
from services.higgins import repository as repo

log = logging.getLogger("apollo.tc_flyby.legacy_names")

KEYS = {"teddy": "tc_flyby", "teddyTokens": "flybyTokens"}
ITEM_IDS = {"teddy-di-checks": "tc-flyby-di-checks", "teddy-di-brief": "tc-flyby-di-brief"}


def renamed(value: Any) -> Any:
    """The same value with TC Hawkeye's old names replaced: keys, `teddy_*` routes and `teddy-*` item ids."""
    if isinstance(value, dict):
        return {KEYS.get(k, k): renamed(v) for k, v in value.items()}
    if isinstance(value, list):
        return [renamed(v) for v in value]
    if isinstance(value, str):
        if value.startswith("teddy_"):
            return "tc_flyby_" + value[len("teddy_"):]
        return ITEM_IDS.get(value, value)
    return value


async def _cases() -> int:
    moved = 0
    async for doc in db.investigation_cases.find({"$or": [{"routing.teddy": {"$exists": True}}, {"teddy_ciphertext": {"$exists": True}},
                                                          {"routing.answeredBy": {"$regex": "^teddy_"}}]},
                                                 {"_id": 1, "routing": 1, "teddy_ciphertext": 1}):
        routing = doc.get("routing") or {}
        update: dict[str, dict] = {"$set": {}, "$unset": {}}
        if "teddy" in routing:
            update["$set"]["routing.tc_flyby"] = renamed(routing["teddy"])
            update["$unset"]["routing.teddy"] = ""
        if str(routing.get("answeredBy") or "").startswith("teddy_"):
            update["$set"]["routing.answeredBy"] = renamed(routing["answeredBy"])
        if "teddy_ciphertext" in doc:
            if doc["teddy_ciphertext"]:
                update["$set"]["tc_flyby_ciphertext"] = repo.enc_json(renamed(repo.dec_json(doc["teddy_ciphertext"])))
            update["$unset"]["teddy_ciphertext"] = ""
        await db.investigation_cases.update_one({"_id": doc["_id"]}, {op: fields for op, fields in update.items() if fields})
        moved += 1
    return moved


async def migrate() -> dict[str, int]:
    counts = {"cases": await _cases()}
    for old, new in ITEM_IDS.items():
        counts[old] = (await db.investigation_evidence.update_many({"client_item_id": old}, {"$set": {"client_item_id": new}})).modified_count
    for collection in ("gemini_usage", "di_transactions"):
        counts[collection] = (await db[collection].update_many({"purpose": "teddy_search"}, {"$set": {"purpose": "tc_flyby_search"}})).modified_count
    if "teddy_search_cache" in await db.list_collection_names():
        await db.teddy_search_cache.drop()
    if any(counts.values()):
        log.info("tc_flyby_legacy_names_moved %s", counts)
    return counts
