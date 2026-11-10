"""The server's copy kept for the phone until the phone confirms it has saved its own (owner's rule, 2026-11-01).

When an investigation finishes (answered, failed or cancelled), the server keeps one copy for the phone that asked:
the finished result (case, turns, sources, evidence list), the exact text and links that were submitted, and the
identifiers recorded at intake (who sent it, its subject, when it arrived). No clock removes it — not the 15-minute
working window and not the 24-hour rule. It goes only when the phone confirms that it saved and checked its own
complete copy (POST /investigations/{id}/confirm-commit), when the person deletes the check, or with all their data.
The phone fetches it with GET /investigations/{id}/pickup. Stored encrypted, like every other investigation content.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException

from core.config import logger
from core.db import db, now_utc
from services.higgins import repository as repo

COLLECTION = "investigation_device_pickups"
# The identifiers recorded at intake, and the label the phone saves each under.
HEADER_LABELS = {"sender": "From", "reply_to": "Reply-to", "subject": "Subject", "received_at": "Received"}
IDENTIFIERS = ("type", "sender", "reply_to", "subject", "received_at", "provider", "attachment_names", "url")
FINISHED = ("complete", "partial", "failed", "cancelled")


def finished(case: dict) -> bool:
    return not case.get("active_job_id") and case.get("status") in FINISHED


def _plain(value: Any) -> Any:
    return repo.utc(value).isoformat() if isinstance(value, datetime) else value


async def hold(owner: str, case_id: str) -> bool:
    """Keep (or refresh, after a follow-up) the phone's copy of a finished, still-live investigation."""
    doc = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id, "deleted": False}, {"_id": 0})
    if not doc or not finished(doc) or repo.utc(doc["expires_at"]) <= now_utc():
        return False
    try:
        rows = await repo.list_evidence(owner, case_id)
        originals = []
        evidence_content = []
        for row in rows:
            if row.get("availability") != "available":
                continue
            kind = row.get("kind")
            try:
                data = await repo.read_bytes(owner, case_id, row["evidence_id"])
            except HTTPException:
                # Never certify a snapshot that omits evidence marked available.
                raise
            # The existing authenticated evidence-content endpoint transfers
            # individual bytes. Never embed up to 64 MiB of case files in a
            # single MongoDB pickup document.
            import hashlib
            evidence_content.append({
                "evidenceId": row["evidence_id"], "kind": kind,
                "origin": row.get("origin"), "mediaType": row.get("media_type"),
                "byteLength": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            })
            if row.get("origin") == "user_submission" and not row.get("parent_id") and kind in ("text", "url"):
                originals.append({"evidenceId": row["evidence_id"], "kind": kind, "body": data.decode("utf-8")})
        source = {k: _plain(v) for k, v in (doc.get("source_metadata") or {}).items() if k in IDENTIFIERS and v not in (None, "", [])}
        snapshot = {
            "case": (await repo.case_view(doc)).wire(),
            "turns": [t.wire() for t in await repo.accepted_turns(owner, doc)],
            "sources": await repo.sources(owner, case_id),
            "evidence": [repo.evidence_view(r).wire() for r in rows],
            "originals": originals,
            "evidenceContent": evidence_content,
            "source": source,
        }
        # MongoDB documents have a 16 MiB limit. Never create a pickup that
        # appears complete but cannot be stored; the existing encrypted evidence
        # chunks remain the source of truth until a verified device transfer.
        from bson import BSON
        encoded_snapshot = repo.enc_json(snapshot)
        if len(BSON.encode({"snapshot_ciphertext": encoded_snapshot})) >= 15 * 1024 * 1024:
            logger.warning("device_pickup_snapshot_too_large case=%s", case_id[:8])
            return False
        now = now_utc()
        await db[COLLECTION].update_one({"owner_id": owner, "case_id": case_id},
                                        {"$set": {"snapshot_ciphertext": encoded_snapshot, "held_at": now},
                                         "$setOnInsert": {"owner_id": owner, "case_id": case_id, "first_held_at": now}}, upsert=True)
        return True
    except Exception as exc:  # noqa: BLE001 — never blocks an investigation finishing; never logs content
        logger.warning("device_pickup_hold_failed case=%s type=%s", case_id[:8], type(exc).__name__)
        return False


async def get(owner: str, case_id: str) -> Optional[dict]:
    row = await db[COLLECTION].find_one({"owner_id": owner, "case_id": case_id}, {"_id": 0})
    return {**repo.dec_json(row["snapshot_ciphertext"]), "heldAt": repo.utc(row["held_at"]).isoformat()} if row else None


async def release(owner: str, case_id: str) -> None:
    await db[COLLECTION].delete_one({"owner_id": owner, "case_id": case_id})


def needs_result(snapshot: dict) -> bool:
    """A finished answer the phone keeps as its saved result (a question still waiting, or a failed check, isn't one)."""
    case = snapshot.get("case") or {}
    response = case.get("response") or {}
    return bool(response) and not response.get("question") and case.get("status") != "failed"


def missing(snapshot: dict, saved: dict) -> list[str]:
    """What the phone says it hasn't saved yet, of what the server holds for it. Empty: its copy is complete."""
    out: list[str] = []
    required = {e["evidenceId"]: e["sha256"] for e in snapshot.get("evidenceContent") or []}
    reported = saved.get("evidenceDigests") or {}
    if any(reported.get(eid) != digest for eid, digest in required.items()):
        out.append("the investigation evidence (verified checksums)")
    kinds = {o.get("kind") for o in snapshot.get("originals") or []}
    if "text" in kinds and not saved.get("text"):
        out.append("the text")
    if "url" in kinds and not saved.get("link"):
        out.append("the link")
    have = {str(h).strip().lower() for h in saved.get("headers") or []}
    for key, label in HEADER_LABELS.items():
        if (snapshot.get("source") or {}).get(key) and label.lower() not in have:
            out.append(label)
    if needs_result(snapshot) and not saved.get("result"):
        out.append("the result")
    return out


async def confirmed(owner: str, case_id: str) -> None:
    """The phone has its own complete copy: release this one and let the 24-hour rule run for what else the server holds."""
    now = now_utc()
    await release(owner, case_id)
    await db.investigation_cases.update_one({"owner_id": owner, "case_id": case_id, "device_saved_at": None}, {"$set": {"device_saved_at": now}})
    await db.patrol_events.update_many({"device_id": owner, "investigation_case_id": case_id, "device_saved_at": None}, {"$set": {"device_saved_at": now}})


async def ensure_indexes() -> None:
    await db[COLLECTION].create_index([("owner_id", 1), ("case_id", 1)], unique=True)
