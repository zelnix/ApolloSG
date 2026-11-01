"""Temporary encrypted content with fixed scope expiry and deletion fencing.

Minimal tombstones outlive content; neither retries nor reads extend a scope.
TTL is a backstop. Every read/publish checks expiry and the owner's generation.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta, timezone
import uuid

from fastapi import HTTPException

from core.db import db, now_utc
from services.higgins.capacity import LIFETIME_SECONDS, TEMPORARY_RETENTION

CONTENT_COLLECTIONS = ("ask_messages", "ask_handoffs")
LEGACY_CONTENT_MIGRATION = "higgins-discard-pre-v1-temporary-content"
# Also match the old retention class for backward compatibility during migration
LEGACY_TEMPORARY_RETENTION = "apollo_15_minute_temporary"


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


async def generation(owner: str) -> str:
    await db.investigation_owners.update_one({"owner_id": owner},
        {"$setOnInsert": {"generation": uuid.uuid4().hex}}, upsert=True)
    value = await db.investigation_owners.find_one({"owner_id": owner}, {"_id": 0})
    return value["generation"]


async def open_scope(owner: str, scope_id: str) -> dict:
    current = await generation(owner)
    now = now_utc()
    await db.investigation_scopes.update_one({"owner_id": owner, "scope_id": scope_id}, {"$setOnInsert": {
        "owner_id": owner, "scope_id": scope_id, "generation": current, "created_at": now,
        "expires_at": now + timedelta(seconds=LIFETIME_SECONDS), "retention_class": TEMPORARY_RETENTION, "deleted": False}}, upsert=True)
    return await require_scope(owner, scope_id)


async def require_scope(owner: str, scope_id: str) -> dict:
    scope = await db.investigation_scopes.find_one({"owner_id": owner, "scope_id": scope_id}, {"_id": 0})
    if not scope:
        raise HTTPException(404, "Temporary investigation not found.")
    if scope["deleted"] or utc(scope["expires_at"]) <= now_utc() or scope["generation"] != await generation(owner):
        raise HTTPException(410, "The temporary investigation has expired or was deleted. Start a new check with the required evidence.")
    return scope


async def delete_scope(owner: str, scope_id: str) -> int:
    await db.investigation_scopes.update_one({"owner_id": owner, "scope_id": scope_id}, {
        "$set": {"deleted": True}, "$unset": {'context_ciphertext': ''}, "$setOnInsert": {"generation": await generation(owner),
        "created_at": now_utc(), "expires_at": now_utc()}}, upsert=True)
    count = 0
    for name in CONTENT_COLLECTIONS:
        result = await db[name].delete_many({"device_id": owner, "scope_id": scope_id})
        count += result.deleted_count
    return count


async def delete_owner_content(owner: str) -> int:
    # Invalidate before deletion; late workers keep the old generation and cannot publish.
    await db.investigation_owners.update_one({"owner_id": owner}, {"$set": {"generation": uuid.uuid4().hex}}, upsert=True)
    await db.investigation_scopes.update_many({"owner_id": owner}, {"$set": {"deleted": True}, '$unset': {'context_ciphertext': ''}})
    count = 0
    for name in CONTENT_COLLECTIONS:
        result = await db[name].delete_many({"device_id": owner})
        count += result.deleted_count
    return count


async def _discard_legacy_content_once(migration_id: str = LEGACY_CONTENT_MIGRATION) -> bool:
    """Runs the approved pre-v1 temporary-content discard once, with a recoverable lease."""
    now = now_utc()
    token = uuid.uuid4().hex
    await db.apollo_migrations.create_index("migration_id", unique=True)
    await db.apollo_migrations.update_one(
        {"migration_id": migration_id},
        {"$setOnInsert": {"migration_id": migration_id, "status": "pending", "created_at": now}},
        upsert=True,
    )
    claimed = await db.apollo_migrations.find_one_and_update(
        {"migration_id": migration_id, "completed_at": {"$exists": False},
         "$or": [{"lease_until": {"$exists": False}}, {"lease_until": {"$lte": now}}]},
        {"$set": {"status": "running", "lease_token": token, "lease_until": now + timedelta(minutes=5), "started_at": now}},
    )
    if not claimed:
        return False
    try:
        for name in CONTENT_COLLECTIONS:
            await db[name].delete_many({"content_version": {"$ne": 1}})
    except Exception:
        await db.apollo_migrations.update_one(
            {"migration_id": migration_id, "lease_token": token},
            {"$set": {"status": "pending", "failed_at": now_utc()}, "$unset": {"lease_until": "", "lease_token": ""}},
        )
        raise
    await db.apollo_migrations.update_one(
        {"migration_id": migration_id, "lease_token": token},
        {"$set": {"status": "completed", "completed_at": now_utc()}, "$unset": {"lease_until": "", "lease_token": ""}},
    )
    return True


async def migrate_and_index() -> None:
    await db.investigation_owners.create_index("owner_id", unique=True)
    await db.investigation_scopes.create_index([("owner_id", 1), ("scope_id", 1)], unique=True)
    await db.investigation_scopes.create_index("expires_at")  # preserve content-free deletion tombstones
    # Legacy-content cleanup is intentionally NOT invoked during startup. `_discard_legacy_content_once` is an
    # operator-only, audited migration helper; deployment initialization must preserve every existing record.
    for name in CONTENT_COLLECTIONS:
        indexes = await db[name].index_information()
        for index_name, definition in indexes.items():
            if definition.get("key") == [("expires_at", 1)] and definition.get("partialFilterExpression") != {"retention_class": TEMPORARY_RETENTION}:
                await db[name].drop_index(index_name)
        await db[name].create_index("expires_at", name="temporary_evidence_expiry_ttl", expireAfterSeconds=0,
                                    partialFilterExpression={"retention_class": {"$in": [TEMPORARY_RETENTION, LEGACY_TEMPORARY_RETENTION]}})
        await db[name].create_index([("device_id", 1), ("scope_id", 1)])


async def sweep() -> None:
    # Deployment-safe invariant: automatic cleanup can only select records explicitly created under Apollo's
    # temporary-evidence contract. Persistent/user-owned records are never selected by age alone.
    retention_filter = {'retention_class': {'$in': [TEMPORARY_RETENTION, LEGACY_TEMPORARY_RETENTION]}}
    await db.investigation_scopes.update_many({**retention_filter,
                                               '$or': [{'expires_at': {'$lte': now_utc()}}, {'deleted': True}]},
                                              {'$unset': {'context_ciphertext': ''}})
    for name in CONTENT_COLLECTIONS:
        await db[name].delete_many({**retention_filter, "expires_at": {"$lte": now_utc()}})
    async for scope in db.investigation_scopes.find({**retention_filter, "deleted": True}, {"_id": 0, "owner_id": 1, "scope_id": 1}):
        await delete_scope(scope["owner_id"], scope["scope_id"])


async def sweep_loop() -> None:
    while True:
        try:
            await sweep()
        except asyncio.CancelledError:
            raise
        except Exception:
            # No content/errors from providers are logged. The next pass retries deletion.
            from core.config import logger
            logger.error("temporary_content_cleanup_failed")
        await asyncio.sleep(30)