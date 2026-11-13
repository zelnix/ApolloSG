"""Durable job execution: leases, fencing, events, failure classification, cancellation and recovery (spec §5, §12).

Work starts after a 202 and runs in-process; a crashed or restarted server recovers abandoned jobs once their lease expires.

NO RETRIES (one correlated case = at most one Magnum DI call): when Magnum DI's call fails or its answer doesn't pass
Apollo's checks, the investigation stops and Higgins says why. Nothing is tried again — not automatically, not by a
recovered job and not by Resubmit — and TC Hawkeye's deterministic findings stay with the case and are shown. Only a stop
BEFORE the case's Magnum DI call was made (TC Hawkeye interrupted, the daily spending limit) can be resubmitted.
"""
from __future__ import annotations

import asyncio
import time as _time
from typing import Optional

from core.config import logger
from core.db import db, now_utc
from core.redaction import redact_investigation_secrets
from services.higgins import coordinator, provider, tc_hawkeye
from services.higgins import repository as repo
from services.higgins.evidence import EVIDENCE_WORD_LIMIT
from services.higgins.contracts import DiagnosticDetail, Failure, RetryAttempt

_tasks: set[asyncio.Task] = set()

# Why the investigation stopped.
_STOP_REASONS: dict[str, str] = {
    "rate_limited": "the analysis service was too busy to answer",
    "provider_unavailable": "the analysis service didn't answer in time",
    "incomplete_output": "the answer stopped before it was complete",
    "response_invalid": "the answer didn't pass Apollo's checks (the AI tool's actual reply is kept in the technical details)",
    "budget_exhausted": "the investigation ran out of time before it could finish",
    "budget_limit": "ApolloSG's daily AI spending limit was reached, so nothing was sent",
    "transport_interrupted": "the connection dropped before the answer arrived",
    "call_limit": "this case has already had its one Magnum DI call",
}

PROVIDER_CONFIGURATION_MESSAGE = ("Magnum DI couldn't access one of its analysis services because it isn't configured correctly. "
                                  "This needs a technical fix rather than another attempt.")


def stop_message(reason: str, *, magnum_used: bool, kept: list[str]) -> str:
    """Higgins says plainly why the investigation stopped, and keeps what TC Hawkeye established. Nothing is substituted."""
    why = _STOP_REASONS.get(reason, "something interrupted the investigation")
    if magnum_used:
        text = (f"Magnum DI stopped because {why}. No conclusion has been made up in its place. "
                "A request that may already have reached the provider is not sent again.")
    else:
        text = (f"The investigation stopped because {why}, before Magnum DI's call was made. No conclusion has been made up "
                "in its place. Everything you submitted is kept, so you can resubmit with one tap.")
    if kept:
        text += " What TC Hawkeye established before that: " + " ".join(f"• {line}" for line in kept)
    return text


def evidence_too_large_message(words: int) -> str:
    """Higgins explains the size limit plainly, and points to the person's own AI assistant.
    No evidence was sent, shortened or left out quietly — nothing was investigated."""
    return (
        f"There is too much written material in this case for Apollo's standard investigation — about {words:,} words, "
        f"and ApolloSG's limit is {EVIDENCE_WORD_LIMIT:,} words for one investigation. "
        "I haven't sent any of it to be investigated, and nothing has been shortened or left out behind your back. "
        "For documents this long, open them in an AI assistant on your own device, "
        "where you can work through the whole document yourself. "
        "If you'd like Apollo to investigate, remove some of the material from this case and run the check again."
    )


def launch(owner: str, case_id: str, job_id: str) -> None:
    task = asyncio.create_task(run(owner, case_id, job_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _emit(owner: str, case: dict, job: dict, kind: str, payload: dict) -> None:
    fresh = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case["case_id"]}, {"_id": 0, "revision": 1})
    await repo.emit(owner, case["case_id"], job["job_id"], kind, payload, (fresh or case)["revision"], repo.utc(case["expires_at"]))
    # Push notification for background assessment completion (Text Gate + Email Gate).
    # Only fires for "completed" events on cases created by background intake (gate: text/email).
    if kind == "completed":
        try:
            await _push_background_completion(owner, case)
        except Exception:
            pass  # Non-blocking


async def _push_background_completion(owner: str, case: dict) -> None:
    """Send a push notification when a background investigation completes.
    Only fires for background-originated cases (text gate auto-assessment, email monitoring).
    The email path also has its own push via _finalise_receipt, so we only push for text here."""
    gate = case.get("gate", "")
    if gate not in ("text",):
        return  # Email gate push is handled by mailbox_monitor._send_assessment_push
    from routers.push import send_push, PUSH_GROWL
    case_id = case.get("case_id", "")
    await send_push(
        recipients=[owner],
        data={
            "title": "ApolloSG: message assessed",
            "message": "ApolloSG completed a background assessment of a captured message. Open ApolloSG to review.",
            "action_url": f"/patrol/{case_id}?focus=alert" if case_id else "/patrol",
            **PUSH_GROWL,
        },
        owner_id=owner,
        idempotency_key=f"bg-completion-{case_id}" if case_id else None,
    )


async def _fail(owner: str, case: dict, job: dict, failure: Failure, *, partial: bool = False) -> None:
    # Populate case/job IDs in diagnostics if present
    if failure.diagnostics:
        failure.diagnostics.case_id = case.get("case_id")
        failure.diagnostics.job_id = job.get("job_id")
    # Merge any existing retry history from the job document
    existing_history = job.get("retry_history", [])
    if existing_history:
        merged = [RetryAttempt(**h) if isinstance(h, dict) else h for h in existing_history]
        failure.retry_history = merged + failure.retry_history

    await repo.set_job(owner, job["job_id"], job.get("fence"), {
        "$set": {"status": "failed", "failure": failure.wire(), "lease_until": None, "resubmit_at": failure.resubmit_at,
                 "retry_history": [h.wire() if hasattr(h, 'wire') else h for h in failure.retry_history]}})
    if await repo.cas(owner, case["case_id"], {"epoch": job["epoch"], "work_epoch": job.get("work_epoch", job["epoch"]), "active_job_id": job["job_id"], **({"lease_fence": job["fence"]} if job.get("fence") else {})},
                      {"$set": {"status": "partial" if partial or case.get("response_ciphertext") else "failed", "active_job_id": None, "active_turn_id": None, "lease_fence": None}}, bump=False):
        await repo.start_deletion_clock(owner, case["case_id"])  # a failed check has finished too: its 24 hours start now
    if partial:
        await _emit(owner, case, job, "partial", {"responseRevision": case.get("response_revision"), "reason": failure.wire(), "canContinue": failure.retryable or failure.code != "provider_configuration"})
    await _emit(owner, case, job, "failed", failure.wire())


async def _stop(owner: str, case: dict, job: dict, code: str, diag: Optional[DiagnosticDetail],
                history: list[RetryAttempt], *, reason: Optional[str] = None) -> None:
    """Stop the investigation and say why, keeping TC Hawkeye's findings. Once the case's Magnum DI call was made nothing
    can be resubmitted; before it (TC Hawkeye interrupted, the spending limit) the person may resubmit."""
    used = await repo.magnum_call_used(owner, case["case_id"])
    kept = await tc_hawkeye.established(owner, case["case_id"])
    if diag:
        diag.final_status = "failed"
    await _fail(owner, case, job, Failure(code=code, message=stop_message(reason or code, magnum_used=used, kept=kept), retryable=not used,
                                          diagnostics=diag, retry_history=history), partial=True)


async def run(owner: str, case_id: str, job_id: str) -> None:
    job = await repo.acquire_lease(owner, job_id)
    if not job:
        return
    case = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id}, {"_id": 0})
    if not case or case["deleted"] or case["epoch"] != job["epoch"] or case.get("work_epoch", case["epoch"]) != job.get("work_epoch", job["epoch"]) or repo.utc(case["expires_at"]) <= now_utc():
        await repo.set_job(owner, job_id, job["fence"], {"$set": {"status": "cancelled", "lease_until": None}})
        return
    accepted = await repo.accepted_commit_for(owner, case, job["turn_id"])
    if accepted:  # crash after acceptance: repair job/event projections from the authoritative commit, no second conclusion
        commit = repo.dec_json(accepted["commit_ciphertext"])
        await repo.set_job(owner, job_id, job["fence"], {"$set": {"status": case["status"] if case["status"] in ("complete", "partial", "waiting_user") else "complete", "lease_until": None, "checkpoint_ciphertext": None}})
        sources = await repo.sources(owner, case_id)
        await _emit(owner, case, job, "response", {"response": commit["response"], "sources": [s for s in sources if s["id"] in set(commit["response"]["sourceIds"])]})
        await _emit(owner, case, job, "completed", {"turnId": job["turn_id"], "responseRevision": commit["committedRevision"], "providerComplete": True,
                                                    "completion": commit["response"]["completion"], "caseStatus": case["status"], "cleanupStatus": case.get("cleanup_status", "not_due"), "repaired": True})
        return
    fenced = await repo.cas(owner, case_id, {"epoch": job["epoch"], "work_epoch": job.get("work_epoch", job["epoch"]), "active_job_id": job_id}, {"$set": {"lease_fence": job["fence"], "status": "investigating"}}, bump=False)
    if not fenced:
        await repo.set_job(owner, job_id, job["fence"], {"$set": {"status": "cancelled", "lease_until": None}})
        return
    case = fenced
    stop = asyncio.Event()

    async def heartbeat():
        while not stop.is_set():
            await asyncio.sleep(10)
            if not await repo.heartbeat(owner, job_id, job["fence"]):
                stop.set()

    async def progress(phase: str, message: str) -> None:
        if stop.is_set():
            raise asyncio.CancelledError()
        await _emit(owner, case, job, "progress", {"phase": phase, "message": message})

    beat = asyncio.create_task(heartbeat())
    # This run's failure record; _fail() prepends what the job document already recorded.
    retry_history: list[RetryAttempt] = []
    job_start = _time.monotonic()

    def failed(code: str, message: Optional[str], duration_ms: Optional[int] = None) -> None:
        retry_history.append(RetryAttempt(attempt=len(retry_history) + 1, kind="provider_retry", failure_code=code, failure_message=message,
                                          timestamp=now_utc().isoformat(), duration_ms=duration_ms, outcome="failed"))

    try:
        remaining = (repo.utc(job["deadline_at"]) - now_utc()).total_seconds()
        if remaining <= 5:
            diag = DiagnosticDetail(
                component="magnum_di", service="Investigation Engine", operation="investigation",
                original_error_code="deadline_exceeded",
                original_message=f"Investigation deadline reached after {int(_time.monotonic() - job_start)}s processing.",
                timestamp=now_utc().isoformat(), duration_ms=int((_time.monotonic() - job_start) * 1000))
            await _stop(owner, case, job, "budget_exhausted", diag, retry_history)
            return
        turn_start = _time.monotonic()
        try:
            outcome = await asyncio.wait_for(coordinator.run_turn(owner, case, job, progress), timeout=remaining)
        except asyncio.TimeoutError:
            duration_ms = int((_time.monotonic() - turn_start) * 1000)
            diag = DiagnosticDetail(
                component="magnum_di", service="Investigation Engine", operation="investigation",
                original_error_code="investigation_deadline_exceeded",
                original_message=f"Investigation turn timed out after {duration_ms}ms (deadline: {int(remaining)}s remaining).",
                timestamp=now_utc().isoformat(), duration_ms=duration_ms)
            failed("investigation_deadline", "Turn exceeded remaining deadline", duration_ms)
            await _stop(owner, case, job, "provider_unavailable", diag, retry_history)
            return
        except provider.ProviderFailure as exc:
            duration_ms = int((_time.monotonic() - turn_start) * 1000)
            diag = DiagnosticDetail(
                component="provider_adapter", service="AI service", operation=exc.operation or "response_generation",
                original_error_code=exc.code,
                http_status=exc.http_status,
                original_message=exc.original_message,
                exception_type=exc.exception_type,
                timestamp=now_utc().isoformat(), duration_ms=duration_ms)
            failed(exc.code, exc.original_message, duration_ms)
            if exc.code == "budget_limit":
                # Refused by the spending limit before anything was sent: no call was made, so none is counted.
                await repo.release_magnum_call(owner, case_id)
            if exc.code == "provider_configuration":
                diag.final_status = "failed"
                await _fail(owner, case, job, Failure(code="provider_configuration", message=PROVIDER_CONFIGURATION_MESSAGE,
                    retryable=False, diagnostics=diag, retry_history=retry_history), partial=True)
                return
            code = exc.code if exc.code in _STOP_REASONS else "provider_unavailable"
            await _stop(owner, case, job, code, diag, retry_history)
            return
        if outcome.kind == "call_limit_reached":
            # The case's one Magnum DI call was already made (a recovered job, a duplicate worker): nothing more is sent.
            diag = DiagnosticDetail(component="magnum_di", service="ApolloSG", operation="magnum_call_limit",
                original_error_code="call_limit_reached", original_message="; ".join(outcome.errors)[:400],
                timestamp=now_utc().isoformat())
            failed("call_limit_reached", "; ".join(outcome.errors)[:200] or None)
            await _stop(owner, case, job, "provider_unavailable", diag, retry_history, reason="call_limit")
            return
        if outcome.kind == "waiting_device":
            await repo.set_job(owner, job_id, job["fence"], {"$set": {"status": "waiting_device", "lease_until": None}})
            await repo.cas(owner, case_id, {"epoch": job["epoch"], "work_epoch": job.get("work_epoch", job["epoch"]), "active_job_id": job_id},
                           {"$set": {"status": "waiting_device"}, "$addToSet": {"pending_device_request_ids": outcome.request["id"]}}, bump=False)
            await _emit(owner, case, job, "device_request", outcome.request)
            return
        if outcome.kind == "invalid":
            # The provider replied, but the reply failed Apollo's validation. Nothing is substituted:
            # the real reply is carried verbatim (redacted, truncated) into the technical details so
            # Support/DI can see exactly what Gemini returned.
            raw = (outcome.provider_text or "").strip()
            provider_response = provider._sanitise_diagnostic(redact_investigation_secrets(raw))[:4000] if raw else None
            diag = DiagnosticDetail(component="magnum_di", service="AI service", operation="validation",
                original_error_code="response_invalid",
                original_message="Answer failed Apollo's validation: " + "; ".join(outcome.errors)[:400],
                provider_response=provider_response,
                provider_model=outcome.model,
                provider_finish_reason=outcome.finish_reason,
                timestamp=now_utc().isoformat())
            failed("response_invalid", "; ".join(outcome.errors)[:200] or None)
            await _stop(owner, case, job, "response_invalid", diag, retry_history)
            return
        if outcome.kind == "evidence_too_large":
            # Deliberate stop before any Gemini call: the evidence exceeds Apollo's word limit.
            words = outcome.evidence_words or 0
            diag = DiagnosticDetail(component="magnum_di", service="ApolloSG", operation="evidence_size_check",
                original_error_code="evidence_too_large",
                original_message="; ".join(outcome.errors)[:400],
                timestamp=now_utc().isoformat(), final_status="failed")
            await _fail(owner, case, job, Failure(code="evidence_too_large",
                message=evidence_too_large_message(words),
                retryable=False, diagnostics=diag, retry_history=retry_history), partial=False)
            return
        if outcome.kind == "superseded":
            await repo.set_job(owner, job_id, job["fence"], {"$set": {"status": "cancelled", "lease_until": None}})
            pass  # unaccepted bundles of this attempt are reclaimed by the sweeper; accepted history is never touched here
            return
        if outcome.kind == "device_unavailable":
            stage_failure = job.get("slm_failure") or {}
            diagnostic = DiagnosticDetail(component="on_device_ai", service="On-device AI",
                                          operation=stage_failure.get("stage", "investigation"),
                                          original_error_code=stage_failure.get("reason", "on_device_result_unavailable"),
                                          timestamp=now_utc().isoformat())
            await _fail(owner, case, job, Failure(
                code="device_unavailable", message="; ".join(outcome.errors), retryable=True, diagnostics=diagnostic,
            ), partial=True)
            return
        if outcome.kind != "committed" or outcome.commit is None or outcome.case is None:
            raise RuntimeError("unsupported_investigation_outcome:" + outcome.kind)
        commit, updated = outcome.commit, outcome.case
        await repo.set_job(owner, job_id, job["fence"], {"$set": {"status": updated["status"], "lease_until": None, "checkpoint_ciphertext": None}})
        sources = await repo.sources(owner, case_id)
        await _emit(owner, case, job, "response", {"response": commit.response.wire(), "sources": [s for s in sources if s["id"] in set(commit.response.source_ids)]})
        if commit.response.question:
            await _emit(owner, case, job, "question", commit.response.question.wire())
        await _emit(owner, case, job, "completed", {"turnId": commit.turn_id, "responseRevision": commit.committed_revision, "providerComplete": True,
                                                    "completion": commit.response.completion, "caseStatus": updated["status"], "cleanupStatus": updated.get("cleanup_status", "not_due")})
    except asyncio.CancelledError:
        if stop.is_set():
            await repo.set_job(owner, job_id, job["fence"], {"$set": {"status": "cancelled", "lease_until": None}})
        raise
    except Exception as _exc:  # noqa: BLE001 — surface a typed failure with diagnostics
        logger.error("investigation_job_failed job=%s err_type=%s", job_id, type(_exc).__name__)
        duration_ms = int((_time.monotonic() - job_start) * 1000)
        diag = DiagnosticDetail(
            component="magnum_di", service="Investigation Engine", operation="investigation",
            original_error_code=type(_exc).__name__,
            original_message=provider._sanitise_diagnostic(str(_exc)) if str(_exc) else None,
            exception_type=type(_exc).__name__,
            timestamp=now_utc().isoformat(), duration_ms=duration_ms)
        failed(type(_exc).__name__, provider._sanitise_diagnostic(str(_exc)[:200]) if str(_exc) else "Unknown internal error", duration_ms)
        try:
            await _stop(owner, case, job, "provider_unavailable", diag, retry_history, reason="unknown")
        except Exception:  # noqa: BLE001
            pass
    finally:
        stop.set()
        beat.cancel()


async def recover() -> None:
    """Startup/sweeper: relaunch jobs whose lease expired while processing, or that never started; reconcile jobs past their work deadline.
    An accepted turn is authoritative: a job whose turn was already accepted is repaired (via run()), never failed for a passed deadline.
    
    COST SAFETY: Stale mailbox-monitor jobs older than STALE_AUTO_JOB_HOURS are failed rather than relaunched
    to prevent billing-restoration backlog explosions. A failed job is never resumed automatically, and a relaunched
    job can never make a second Magnum DI call for its case (repository.claim_magnum_call).
    """
    from datetime import timedelta
    from services.gemini_usage import check_automated_budget, AUTOMATED_SOURCES
    STALE_AUTO_JOB_HOURS = 2  # Mailbox-monitor jobs older than this are considered stale

    now = now_utc()
    stale_cutoff = now - timedelta(hours=STALE_AUTO_JOB_HOURS)

    async for job in db.investigation_jobs.find({"status": {"$in": ["queued", "investigating", "retry_wait"]}, "deadline_at": {"$lte": now},
                                                 "$or": [{"lease_until": None}, {"lease_until": {"$lte": now}}]}, {"_id": 0}):
        case = await db.investigation_cases.find_one({"owner_id": job["owner_id"], "case_id": job["case_id"]}, {"_id": 0})
        if not case:
            continue
        if await repo.accepted_commit_for(job["owner_id"], case, job["turn_id"]):
            launch(job["owner_id"], job["case_id"], job["job_id"])  # run() repairs projections from the accepted commit
            continue
        await _stop(job["owner_id"], case, job, "budget_exhausted", None, [])
    # Device submissions interrupted after the claim (crash before storage or before resume): finish them idempotently.
    # "storing"/"resuming" are the fenced in-flight sub-states `_claim_submission_stage` uses for renewable ownership;
    # a submission stuck there past its staleness window is taken over by the same call, never left stranded.
    from routers.investigations import _finish_device_submission  # local import: router depends on this module
    async for pending in db.investigation_device_requests.find({"submission.state": {"$in": ["claimed", "storing", "stored", "resuming"]}}, {"_id": 0}):
        case = await db.investigation_cases.find_one({"owner_id": pending["owner_id"], "case_id": pending["case_id"], "deleted": False}, {"_id": 0})
        if not case:
            # Case deleted while submission was in-flight — abandon so it's not retried every sweep.
            await db.investigation_device_requests.update_one(
                {"owner_id": pending["owner_id"], "case_id": pending["case_id"], "request_id": pending["request_id"]},
                {"$set": {"submission.state": "abandoned"}})
            logger.warning("device submission recovery: case gone, abandoned request=%s", pending["request_id"])
            continue
        try:
            await _finish_device_submission(pending["owner_id"], case, pending)
        except Exception as exc:  # noqa: BLE001
            from fastapi.exceptions import HTTPException
            if isinstance(exc, HTTPException) and exc.status_code == 404:
                # Job was deleted/expired/swept — mark abandoned so the sweep stops retrying.
                await db.investigation_device_requests.update_one(
                    {"owner_id": pending["owner_id"], "case_id": pending["case_id"], "request_id": pending["request_id"]},
                    {"$set": {"submission.state": "abandoned"}})
                logger.warning("device submission recovery: job gone (404), abandoned request=%s", pending["request_id"])
            else:
                logger.exception("device submission recovery failed request=%s", pending["request_id"])

    # ── Phase 1b: Relaunch jobs with valid deadlines but expired leases ──
    # COST SAFETY: Check stale automated jobs and budget before relaunching
    async for job in db.investigation_jobs.find({"status": {"$in": ["queued", "investigating", "retry_wait"]}, "deadline_at": {"$gt": now},
                                                 "$or": [{"lease_until": None}, {"lease_until": {"$lte": now}}]}, {"_id": 0, "owner_id": 1, "case_id": 1, "job_id": 1, "source": 1, "created_at": 1}):
        job_source = job.get("source", "user_initiated")
        job_created = job.get("created_at", now)

        # Stale automated jobs: fail instead of relaunching
        if job_source in AUTOMATED_SOURCES and job_created < stale_cutoff:
            case = await db.investigation_cases.find_one({"owner_id": job["owner_id"], "case_id": job["case_id"]}, {"_id": 0})
            if case:
                await _fail(job["owner_id"], case, job, Failure(
                    code="budget_exhausted",
                    message="This automated investigation was too old to safely relaunch after a service interruption.",
                    retryable=False), partial=True)
                logger.info("stale_auto_job_expired job=%s source=%s age_hours=%.1f",
                            job["job_id"], job_source, (now - job_created).total_seconds() / 3600)
            continue

        # Budget check for automated jobs before relaunching
        if job_source in AUTOMATED_SOURCES:
            budget_ok, spent, limit = await check_automated_budget()
            if not budget_ok:
                logger.warning("auto_budget_skip_relaunch job=%s spent=$%.2f limit=$%.2f", job["job_id"], spent, limit)
                continue  # leave in current state, don't relaunch

        launch(job["owner_id"], job["case_id"], job["job_id"])


async def sweep_loop() -> None:
    while True:
        try:
            await repo.sweep()
            await repo.sweep_tombstones()
            await recover()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.error("investigation_sweep_failed")
        await asyncio.sleep(20)
