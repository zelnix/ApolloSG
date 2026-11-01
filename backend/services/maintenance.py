"""Supervised, idempotent background maintenance for durable Apollo work.

The API liveness probe remains independent. This worker records its own component-level
heartbeat so recovery/retention failures are visible without making the HTTP process unhealthy.
"""
from __future__ import annotations

import asyncio
import os
import random
import socket
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta

from core.config import logger
from core.db import db, now_utc
from services.investigation_projector import project_committed_cases, project_ended_cases, project_open_cases
from services.higgins import jobs, repository
from services.higgins.retention import sweep as sweep_temporary_content
from services.system_health_jobs import recover_stale as recover_health_checks
from services.threat_revalidation import revalidate_due_indicators
from services.government_alerts import cleanup_stale_records as cleanup_alert_records
from services.caller_id_db import cleanup_expired_reputation
from services.held_copies import sweep as sweep_held_copies

WORKER_NAME = "apollo-maintenance"
WORKER_INTERVAL_SECONDS = 20
WORKER_STALE_SECONDS = 75
COMPONENT_TIMEOUT_SECONDS = 15
MAX_BACKOFF_SECONDS = 60
INSTANCE_ID = os.getenv("HOSTNAME") or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"

MaintenanceStep = tuple[str, Callable[[], Awaitable[object]]]


def maintenance_steps() -> tuple[MaintenanceStep, ...]:
    return (
        ("temporary_content", sweep_temporary_content),
        ("case_expiry_and_deletion", repository.sweep),
        ("tombstones", repository.sweep_tombstones),
        ("job_and_device_inbox_recovery", jobs.recover),
        ("investigation_patrol_projection", project_committed_cases),
        ("investigation_open_projection", project_open_cases),
        ("investigation_ended_projection", project_ended_cases),
        ("health_check_recovery", recover_health_checks),
        ("threat_revalidation", revalidate_due_indicators),
        ("alert_record_cleanup", cleanup_alert_records),
        ("caller_reputation_cleanup", cleanup_expired_reputation),
        ("held_copies_24h", sweep_held_copies),
    )


async def ensure_indexes() -> None:
    await db.worker_heartbeats.create_index([("worker", 1), ("instance_id", 1)], unique=True)
    await db.worker_heartbeats.create_index("last_heartbeat_at")


async def _record(patch: dict) -> None:
    await db.worker_heartbeats.update_one(
        {"worker": WORKER_NAME, "instance_id": INSTANCE_ID},
        {"$set": {"worker": WORKER_NAME, "instance_id": INSTANCE_ID, **patch}},
        upsert=True,
    )


async def _safe_record(patch: dict, *, context: str) -> bool:
    """Telemetry must never own the lifetime of retention/recovery work."""
    try:
        await _record(patch)
        return True
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - content-free diagnostic only
        logger.warning("maintenance_telemetry_failed context=%s type=%s", context, type(exc).__name__)
        return False


async def _safe_failure_record(name: str, exc: Exception) -> None:
    try:
        await db.worker_heartbeats.update_one(
            {"worker": WORKER_NAME, "instance_id": INSTANCE_ID},
            {"$set": {"worker": WORKER_NAME, "instance_id": INSTANCE_ID, f"components.{name}.status": "failed",
                      f"components.{name}.last_failure_at": now_utc(), f"components.{name}.failure_type": type(exc).__name__},
             "$inc": {f"components.{name}.consecutive_failures": 1}},
            upsert=True,
        )
    except asyncio.CancelledError:
        raise
    except Exception as telemetry_exc:  # noqa: BLE001
        logger.warning("maintenance_telemetry_failed context=%s_failure type=%s", name, type(telemetry_exc).__name__)


async def run_maintenance_cycle(steps: tuple[MaintenanceStep, ...] | None = None) -> dict[str, str]:
    """Run every independent maintenance component once; one failure never skips the others."""
    started = now_utc()
    await _safe_record({"status": "running", "last_started_at": started, "last_heartbeat_at": started}, context="cycle_start")
    outcomes: dict[str, str] = {}
    failures = 0
    for name, operation in steps or maintenance_steps():
        attempted = now_utc()
        await _safe_record({f"components.{name}.last_attempt_at": attempted}, context=f"{name}_attempt")
        try:
            await asyncio.wait_for(operation(), timeout=COMPONENT_TIMEOUT_SECONDS)
            outcomes[name] = "ok"
            await _safe_record({f"components.{name}.status": "ok", f"components.{name}.last_success_at": now_utc(),
                                f"components.{name}.consecutive_failures": 0}, context=f"{name}_success")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - content-free type only; next cycle retries
            failures += 1
            outcomes[name] = "failed"
            await _safe_failure_record(name, exc)
            logger.error("maintenance_component_failed component=%s type=%s", name, type(exc).__name__)
    finished = now_utc()
    await _safe_record({"status": "degraded" if failures else "healthy", "last_heartbeat_at": finished,
                        "last_completed_at": finished, "last_cycle_failures": failures,
                        "cycle_seconds": (finished - started).total_seconds()}, context="cycle_complete")
    return outcomes


async def maintenance_loop() -> None:
    """Run immediately after startup, then forever until supervised shutdown."""
    failures = 0
    while True:
        try:
            await run_maintenance_cycle()
            failures = 0
            await asyncio.sleep(WORKER_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            await _safe_record({"status": "stopped", "stopped_at": now_utc(), "last_heartbeat_at": now_utc()}, context="shutdown")
            raise
        except Exception as exc:  # noqa: BLE001 - outer ownership boundary
            failures += 1
            delay = min(MAX_BACKOFF_SECONDS, 2 ** min(failures, 5)) + random.random()
            logger.error("maintenance_cycle_failed type=%s retry_seconds=%.2f", type(exc).__name__, delay)
            await _safe_record({"status": "degraded", "last_loop_failure_at": now_utc(),
                                "loop_failure_type": type(exc).__name__}, context="loop_failure")
            await asyncio.sleep(delay)


async def supervise_maintenance() -> None:
    """Lifespan-owned watcher: an unexpected loop exit is restarted with bounded backoff."""
    failures = 0
    while True:
        try:
            await maintenance_loop()
            failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - final containment boundary
            failures += 1
            delay = min(MAX_BACKOFF_SECONDS, 2 ** min(failures, 5)) + random.random()
            logger.critical("maintenance_worker_exited type=%s retry_seconds=%.2f", type(exc).__name__, delay)
            await asyncio.sleep(delay)


async def worker_status() -> dict:
    cutoff = now_utc() - timedelta(seconds=WORKER_STALE_SECONDS)
    row = await db.worker_heartbeats.find_one(
        {"worker": WORKER_NAME},
        {"_id": 0, "worker": 1, "instance_id": 1, "status": 1, "last_heartbeat_at": 1,
         "last_completed_at": 1, "last_cycle_failures": 1, "components": 1},
        sort=[("last_heartbeat_at", -1)],
    )
    if not row:
        return {"status": "missing", "stale": True, "lastHeartbeatAt": None, "components": {}}
    heartbeat = row.get("last_heartbeat_at")
    normalised_heartbeat = repository.utc(heartbeat) if heartbeat else None
    try:
        backlog = {
            "investigationJobs": await db.investigation_jobs.count_documents({"status": {"$in": ["queued", "running", "waiting_device", "cancelling"]}}),
            "audioCleanup": await db.family_audio_cleanup.count_documents({"state": {"$in": ["stored", "outcome_unknown", "delete_pending"]}}),
            "expiredCases": await db.investigation_cases.count_documents({"deleted": False, "expires_at": {"$lte": now_utc()}}),
        }
    except Exception as exc:  # noqa: BLE001 - health remains available when backlog telemetry fails
        logger.warning("maintenance_backlog_unavailable type=%s", type(exc).__name__)
        backlog = {"status": "unavailable"}
    return {
        "status": row.get("status", "unknown"),
        "stale": not normalised_heartbeat or normalised_heartbeat <= cutoff,
        "lastHeartbeatAt": normalised_heartbeat.isoformat() if normalised_heartbeat else None,
        "lastCompletedAt": repository.utc(row["last_completed_at"]).isoformat() if row.get("last_completed_at") else None,
        "lastCycleFailures": row.get("last_cycle_failures", 0),
        "components": row.get("components", {}),
        "pendingBacklog": backlog,
    }