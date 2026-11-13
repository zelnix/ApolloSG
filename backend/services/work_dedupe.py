"""One piece of work per piece of evidence per device.

Before Apollo launches work for an email or other submitted evidence, it claims the evidence's digest for that device
(`work_claims`, unique per device, kind and digest). The same evidence arriving again on the same device — a second
connected mailbox, a re-captured notification, the same check submitted twice — is matched to the work already
claimed and launches nothing new. Claims are per device only: one device's evidence never matches another's.

The digest is a one-way SHA-256 of the device id and the normalised evidence; no content is stored.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta

from pymongo.errors import DuplicateKeyError

from core.db import db, now_utc

COLLECTION = "work_claims"
KEEP_FOR = timedelta(days=31)   # longer than the mailbox look-back (30 days), so a re-scan never re-launches


async def ensure_indexes() -> None:
    await db[COLLECTION].create_index([("owner_id", 1), ("kind", 1), ("digest", 1)], unique=True)
    await db[COLLECTION].create_index("expires_at", expireAfterSeconds=0)


def digest(owner: str, *parts: str) -> str:
    # Work identity covers exact evidence. URL paths and source whitespace may
    # be significant; provider-cache normalization is a separate contract.
    normalised = "\x1f".join(str(p or "") for p in parts)
    return hashlib.sha256(f"{owner}\x1e{normalised}".encode("utf-8")).hexdigest()


async def claim(owner: str, kind: str, value: str, **fields) -> dict | None:
    """Claim this evidence for this device. None when the claim is new (go ahead); otherwise the earlier claim."""
    await ensure_indexes()
    doc = {"owner_id": owner, "kind": kind, "digest": value, "created_at": now_utc(), "expires_at": now_utc() + KEEP_FOR, **fields}
    try:
        await db[COLLECTION].insert_one(doc)
        return None
    except DuplicateKeyError:
        return await db[COLLECTION].find_one({"owner_id": owner, "kind": kind, "digest": value}, {"_id": 0})


async def attach(owner: str, kind: str, value: str, **fields) -> None:
    await db[COLLECTION].update_one({"owner_id": owner, "kind": kind, "digest": value}, {"$set": fields})


async def release(owner: str, kind: str, value: str) -> None:
    await db[COLLECTION].delete_one({"owner_id": owner, "kind": kind, "digest": value})


async def wait_for(owner: str, kind: str, value: str, field: str, *, seconds: float = 5.0) -> dict | None:
    """The earlier claim once it records `field` (the case it started), or None if it doesn't in time."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while loop.time() < deadline:
        row = await db[COLLECTION].find_one({"owner_id": owner, "kind": kind, "digest": value}, {"_id": 0})
        if row is None or row.get(field):
            return row
        await asyncio.sleep(0.2)
    return None
