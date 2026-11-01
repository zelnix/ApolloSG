"""Durable KB contribution queue — ensures qualifying investigation results contribute
privacy-safe intelligence to the knowledge base, surviving case deletion and retrying
failed writes without AI calls.

Rules:
- When committing a qualifying result, durably queue its privacy-safe KB contribution.
- Retry failed writes without AI calls.
- Pending contributions survive case deletion.
- Prevent duplicate contributions (idempotency via contribution_key).
- Preserve device isolation and consensus rules.
- Already contributed KB intelligence is never affected by case deletion.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

from core.db import db, now_utc

log = logging.getLogger("apollo.kb_queue")

# ── Queue operations ──────────────────────────────────────────────────────────

async def ensure_indexes() -> None:
    await db.kb_contribution_queue.create_index("contribution_key", unique=True)
    await db.kb_contribution_queue.create_index("status")
    await db.kb_contribution_queue.create_index("created_at")


def _contribution_key(case_id: str, kind: str) -> str:
    """Unique key for deduplication: one contribution per case per kind."""
    return hashlib.sha256(f"{case_id}:{kind}".encode()).hexdigest()


async def enqueue(*, case_id: str, owner_id: str, kind: str, title: str, body: str,
                  publisher: str, authority_tier: str, jurisdiction: str,
                  url: str | None = None, published_at=None) -> bool:
    """Durably queue a privacy-safe KB contribution. Returns True if newly queued, False if duplicate."""
    key = _contribution_key(case_id, kind)
    now = now_utc()
    try:
        await db.kb_contribution_queue.insert_one({
            "contribution_key": key,
            "case_id": case_id,
            "owner_id": owner_id,
            "kind": kind,
            "title": title[:300],
            "body": body[:20000],
            "publisher": publisher,
            "authority_tier": authority_tier,
            "jurisdiction": jurisdiction,
            "url": url,
            "published_at": published_at,
            "status": "pending",
            "attempts": 0,
            "last_attempt_at": None,
            "contributed_at": None,
            "kb_id": None,
            "created_at": now,
            "updated_at": now,
        })
        log.info("KB contribution queued: case=%s kind=%s", case_id, kind)
        return True
    except Exception:
        # Duplicate key — already queued or contributed
        return False


async def process_pending(limit: int = 20) -> int:
    """Process pending KB contributions. Retries failed writes without AI calls.
    Returns the number successfully written."""
    from services.higgins import knowledge

    now = now_utc()
    # Only retry entries that haven't been attempted in the last 60 seconds
    retry_cutoff = now - timedelta(seconds=60)
    cursor = db.kb_contribution_queue.find({
        "status": {"$in": ["pending", "failed"]},
        "$or": [{"last_attempt_at": None}, {"last_attempt_at": {"$lte": retry_cutoff}}],
    }).sort("created_at", 1).limit(limit)

    written = 0
    async for doc in cursor:
        try:
            kb_id = await knowledge.upsert(
                doc["kind"], doc["contribution_key"],
                title=doc["title"], body=doc["body"],
                publisher=doc["publisher"], authority_tier=doc["authority_tier"],
                jurisdiction=doc["jurisdiction"], url=doc.get("url"),
                published_at=doc.get("published_at"),
                knowledge_class="investigation_contribution",
            )
            await db.kb_contribution_queue.update_one(
                {"contribution_key": doc["contribution_key"]},
                {"$set": {"status": "contributed", "kb_id": kb_id, "contributed_at": now,
                          "last_attempt_at": now, "updated_at": now},
                 "$inc": {"attempts": 1}},
            )
            written += 1
            log.info("KB contribution written: key=%s kb_id=%s", doc["contribution_key"], kb_id)
        except Exception:
            # Mark as failed for retry — no AI call, just a DB write
            await db.kb_contribution_queue.update_one(
                {"contribution_key": doc["contribution_key"]},
                {"$set": {"status": "failed", "last_attempt_at": now, "updated_at": now},
                 "$inc": {"attempts": 1}},
            )
            log.warning("KB contribution failed (will retry): key=%s", doc["contribution_key"], exc_info=True)
    return written


async def cleanup_old(days: int = 90) -> int:
    """Remove completed contributions older than the retention window."""
    cutoff = now_utc() - timedelta(days=days)
    result = await db.kb_contribution_queue.delete_many({
        "status": "contributed", "contributed_at": {"$lte": cutoff},
    })
    return result.deleted_count
