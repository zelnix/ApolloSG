"""Opt-in mailbox monitor using the same durable Higgins case engine as every Gate.

Raw messages exist only in Gmail response memory and encrypted temporary investigation evidence. Patrol keeps a
redacted summary; case retention/recovery is owned by the Higgins maintenance worker.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
import re
import uuid
from datetime import timedelta
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from fastapi import HTTPException

from core.config import logger
from core.db import db, now_utc
from core.redaction import redact_investigation_secrets
from services import gmail, work_dedupe
from services.higgins import evidence, jobs, repository as repo

PROCESSING_CLAIM_SECONDS = 120   # how long one pass holds a message before another may take it over (a crashed holder)


def _extract_domain_from_email(email_str: str) -> str | None:
    """Extract the domain from an email address or From header like 'Name <user@domain.com>'."""
    import re as _re
    match = _re.search(r'[\w.+-]+@([\w.-]+)', email_str)
    return match.group(1).lower() if match else None


def _org_domain(domain: str) -> str:
    """Get the organizational domain (eTLD+1 approximation). For 'mail.example.com' → 'example.com'.
    For 'example.co.uk' → 'example.co.uk' (simplified: uses last 2 parts, or 3 for known 2-part TLDs)."""
    parts = domain.lower().rstrip(".").split(".")
    two_part_tlds = {"co.uk", "com.au", "co.nz", "co.za", "com.br", "co.jp", "co.kr", "org.uk", "net.au", "ac.uk"}
    if len(parts) >= 3 and ".".join(parts[-2:]) in two_part_tlds:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


def _domains_same_org(a: str, b: str) -> bool:
    """Check if two domains belong to the same organization (share the same eTLD+1)."""
    return _org_domain(a) == _org_domain(b)


URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>\]\[\"']+")


async def _scan_attachments_vt(device_id: str, message: dict, provider: str) -> list[str]:
    """Scan email attachments via VirusTotal hash lookup. Returns list of finding strings.
    Non-blocking: failures or missing configuration produce informational messages, not errors."""
    from services.virustotal import VT_API_KEY
    if not VT_API_KEY:
        return []  # Not configured — silently skip (already reported by attachment risk flagging)
    attachment_names = message.get("attachment_names", [])
    if not attachment_names or not isinstance(attachment_names, list):
        return []
    message_id = message.get("id", "")
    if not message_id:
        return []
    findings: list[str] = []
    try:
        # Get attachment IDs from the Gmail message payload
        # Note: we need the raw message payload which isn't stored in our scan results.
        # The attachment data is fetched on-demand from Gmail API.
        from services.gmail import download_attachment, get_attachment_ids
        from services.virustotal import lookup_hash, compute_sha256

        # Reconstruct attachment info — re-fetch message with full payload to get attachment IDs.
        # format=full returns the parts tree with body.attachmentId; format=metadata omits it.
        access_token = await gmail._access_token_for(device_id)
        import httpx
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(
                f"{gmail.GMAIL_API}/messages/{message_id}",
                params={"format": "full"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code != 200:
            return []

        msg_data = resp.json()
        attachments = get_attachment_ids(msg_data.get("payload", {}))

        for att in attachments[:5]:  # Limit to 5 attachments per email (rate limit protection)
            try:
                file_bytes = await download_attachment(device_id, message_id, att["attachmentId"])
                if not file_bytes:
                    continue
                sha256 = compute_sha256(file_bytes)
                result = await lookup_hash(sha256, att["filename"])
                if result.status == "malicious":
                    names_str = f" ({', '.join(result.malware_names[:3])})" if result.malware_names else ""
                    findings.append(
                        f"Malware detected in attachment '{att['filename']}': "
                        f"{result.detection_count}/{result.total_engines} antivirus engines flagged this file{names_str}. "
                        f"Do not open this attachment."
                    )
                elif result.status == "suspicious":
                    findings.append(
                        f"Suspicious attachment '{att['filename']}': "
                        f"{result.detection_count}/{result.total_engines} engines flagged this file. "
                        f"Exercise caution — some engines may produce false positives."
                    )
                elif result.status == "unknown":
                    findings.append(
                        f"Attachment '{att['filename']}' is not in the VirusTotal malware database. "
                        f"This does not confirm it is safe — it means this file has not been previously analyzed."
                    )
                # "clean" and "error" results are not added as findings (clean is good news, error is non-actionable)
            except Exception as exc:
                logger.info("VT scan failed for an attachment: %s", type(exc).__name__)
    except Exception as exc:
        logger.info("VT attachment scanning failed for a monitored message: %s", type(exc).__name__)
    return findings

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\s().-]*){9,14}(?!\w)")
SCAN_SECONDS = 15 * 60
PENDING_SECONDS = 20


def _safe_summary(value: str) -> str:
    protected = redact_investigation_secrets(value)
    return PHONE_RE.sub("[phone]", EMAIL_RE.sub("[email]", URL_RE.sub("[link]", protected)))[:400]


def _message_digest(provider: str, message_id: str) -> str:
    return hashlib.sha256(f"{provider}:{message_id}".encode()).hexdigest()


async def ensure_indexes() -> None:
    await db.mailbox_assessment_receipts.create_index([("provider", 1), ("device_id", 1), ("message_digest", 1)], unique=True)
    await db.mailbox_assessment_receipts.create_index([("state", 1), ("updated_at", 1)])
    await db.gmail_connections.create_index([("monitoring_enabled", 1), ("monitor_lease_until", 1)])


async def _submit_shared_case(provider: str, device_id: str, message: dict[str, Any], intake_mode: str) -> bool:
    digest = _message_digest(provider, str(message.get("id", "")))
    key = {"provider": provider, "device_id": device_id, "message_digest": digest}
    try:
        await db.mailbox_assessment_receipts.insert_one({**key, "state": "claimed", "intake_mode": intake_mode, "created_at": now_utc(), "updated_at": now_utc()})
    except DuplicateKeyError:
        pass
    receipt = await db.mailbox_assessment_receipts.find_one(key, {"_id": 0})
    if not receipt or receipt.get("state") in ("submitted", "complete"):
        return False
    # Atomic in-progress claim on this message: a second pass, worker or account scan arriving while it is being
    # handled launches nothing. The claim lapses on its own if the holder crashes.
    now = now_utc()
    if not await db.mailbox_assessment_receipts.find_one_and_update(
            {**key, "state": {"$nin": ["submitted", "complete"]},
             "$or": [{"processing_until": {"$exists": False}}, {"processing_until": None}, {"processing_until": {"$lte": now}}]},
            {"$set": {"processing_until": now + timedelta(seconds=PROCESSING_CLAIM_SECONDS)}}, projection={"_id": 1}):
        return False
    # The same email already taken on by this device (another connected account, a forwarded copy with a new id):
    # nothing new is launched — not even Higgins Triage. Device-scoped: another device's mail never matches.
    content = work_dedupe.digest(device_id, str(message.get("from", "")), str(message.get("subject", "")), str(message.get("body", "")))
    earlier = await work_dedupe.claim(device_id, "email", content, message_digest=digest)
    if earlier and earlier.get("message_digest") != digest:
        await db.mailbox_assessment_receipts.update_one(key, {"$set": {"state": "complete", "screening_result": "duplicate",
                                                                      "duplicate_of": earlier.get("message_digest"), "case_id": earlier.get("case_id"),
                                                                      "processed_at": now_utc(), "updated_at": now_utc()}})
        logger.info("mailbox_duplicate_suppressed device=%s digest=%s", device_id, digest[:12])
        return False
    # Temporary failures (e.g. "temporary_case_unavailable") are retryable — only permanent
    # terminal states ("complete") and active submissions ("submitted") are skipped.
    if receipt.get("state") == "failed":
        failure_reason = receipt.get("failure", "")
        terminal_failures = {"cancelled", "expired"}
        if failure_reason in terminal_failures:
            return False
        # Retryable failure: reset state to "claimed" and re-process
        await db.mailbox_assessment_receipts.update_one(key, {"$set": {"state": "claimed", "updated_at": now_utc()}})

    # C1: Reconcile retries with existing case/job to prevent duplicate investigations.
    existing_case_id = receipt.get("case_id")
    existing_job_id = receipt.get("job_id")
    reuse_existing = False
    if existing_case_id and existing_job_id:
        try:
            existing_case = await repo.get_case(device_id, existing_case_id)
            existing_job = await repo.get_job(device_id, existing_case_id, existing_job_id)
            if existing_job["status"] in ("queued", "investigating", "retry_wait", "waiting_device"):
                await db.mailbox_assessment_receipts.update_one(key, {"$set": {"state": "submitted", "updated_at": now_utc()}})
                return True
            if existing_case.get("response_ciphertext"):
                await db.mailbox_assessment_receipts.update_one(key, {"$set": {"state": "complete", "processed_at": now_utc(), "updated_at": now_utc()}})
                return False
            reuse_existing = True
        except Exception:
            pass

    sender = str(message.get("from", ""))
    subject = str(message.get("subject", ""))
    body = str(message.get("body", ""))
    links = message.get("links", []) if isinstance(message.get("links"), list) else []
    # Preserve Reply-To and attachment filenames during intake where available
    reply_to = str(message.get("reply_to", "")) if message.get("reply_to") else ""
    attachment_names = message.get("attachment_names", []) if isinstance(message.get("attachment_names"), list) else []
    auth_results = message.get("auth_results", {}) if isinstance(message.get("auth_results"), dict) else {}
    link_context = "\n".join(f"Displayed link text: {link.get('text', '')}\nActual destination: {link.get('href', '')}" for link in links if isinstance(link, dict))
    link_section = f"\n\nHTML link destinations:\n{link_context}" if link_context else ""
    reply_section = f"\nReply-To: {reply_to}" if reply_to and reply_to != sender else ""
    attachment_section = f"\nAttachment filenames: {', '.join(attachment_names)}" if attachment_names else ""
    # #3: Include authentication evidence plainly
    auth_section = ""
    if auth_results:
        auth_lines = []
        for mech in ("spf", "dkim", "dmarc"):
            result = auth_results.get(mech, "unknown")
            if result in ("fail", "softfail", "permerror"):
                auth_lines.append(f"Sender authentication ({mech.upper()}): FAILED ({result})")
            elif result == "pass":
                auth_lines.append(f"Sender authentication ({mech.upper()}): passed")
            elif result != "unknown":
                auth_lines.append(f"Sender authentication ({mech.upper()}): {result}")
        if auth_lines:
            auth_section = "\n" + "\n".join(auth_lines)
    text = f"From: {sender}{reply_section}\nSubject: {subject}{auth_section}{attachment_section}\n\n{body}{link_section}".strip()

    # ─── Lightweight deterministic findings (no external API calls) ───
    # Only flag ACTUAL threat indicators, not routine email features.
    local_findings = []

    # Different sender and link domains prove nothing on their own (newsletters, receipts and click tracking all do it):
    # who the email presents itself as and where its links really go are judged by the Triage rules from the email.
    sender_domain = _extract_domain_from_email(sender)
    # Reply-To mismatch detection
    if reply_to:
        reply_domain = _extract_domain_from_email(reply_to)
        if reply_domain and sender_domain and not _domains_same_org(reply_domain, sender_domain):
            local_findings.append(
                f"The Reply-To address ({reply_to}) uses a different domain ({reply_domain}) from the sender ({sender_domain}). "
                "Replies will go to a different address than the one displayed."
            )
    # Authentication failure detection
    if auth_results:
        for mech in ("dmarc", "spf", "dkim"):
            result = auth_results.get(mech, "unknown")
            if result in ("fail", "softfail", "permerror"):
                local_findings.append(
                    f"Sender authentication failed ({mech.upper()}: {result}). "
                    "The sender's identity could not be authenticated by the email provider. "
                    "This does not prove fraud, but the sender could not be verified."
                )
                break  # one auth failure finding is enough
    # Attachment risk flagging (executable types only — no external API call)
    risky_extensions = {".exe", ".scr", ".bat", ".cmd", ".com", ".pif", ".js", ".vbs", ".wsf",
                        ".msi", ".dll", ".hta", ".ps1", ".reg", ".lnk", ".iso", ".img", ".cab"}
    for name in attachment_names:
        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext in risky_extensions:
            local_findings.append(
                f"Risky attachment type: {name} ({ext}). This file type can execute code on your device. "
                "Apollo flagged the filename — attachment contents were not inspected."
            )

    # ─── Higgins Triage Engine: run BEFORE case creation ───
    # SAFE emails never get a case, never appear in Threats.
    # Only genuinely suspicious items proceed to case creation + Magnum DI.
    from services.triage_engine import triage_item, _extract_evidence_from_email

    triage_evidence = _extract_evidence_from_email(message)
    triage_result = await triage_item(
        device_id=device_id,
        evidence=triage_evidence,
        findings=local_findings,
        correlation_id=f"mailbox-{digest[:12]}",
    )

    if not triage_result.should_escalate:
        # Deterministic Triage resolved NO THREAT or LIMITED → no case, no Gemini call.
        await db.mailbox_assessment_receipts.update_one(key, {"$set": {
            "state": "complete",
            "screening_result": "clear",
            "triage_outcome": triage_result.outcome.value,
            "triage_reason": triage_result.reason,
            "triage_cost_usd": 0.0,
            "triage_cached": triage_result.cached,
            "screening_findings_count": len(local_findings),
            "processed_at": now_utc(),
            "updated_at": now_utc(),
        }})
        logger.info("triage_resolved device=%s digest=%s outcome=%s cached=%s",
                     device_id, digest[:12], triage_result.outcome.value, triage_result.cached)
        if triage_result.investigation is not None:
            from services.triage import record_triage_history
            try:
                await record_triage_history(device_id, triage_result.investigation, category="email",
                                            evidence_source="connected_mailbox", subject=subject,
                                            source={"type": "email", "sender": sender or None, "subject": subject or None,
                                                    "received_at": receipt.get("received_at") or receipt.get("created_at"),
                                                    "provider": provider})
            except Exception as exc:
                logger.warning("triage_history_write_failed device=%s error=%s", device_id, type(exc).__name__)
        return True  # Email screened and resolved — no case needed, zero Gemini calls

    # ─── Triage escalation: POSSIBLE THREAT → create case + exactly one Magnum DI call ───
    # Budget check before launching paid investigation.
    from services.gemini_usage import check_automated_budget
    budget_ok, budget_spent, budget_limit = await check_automated_budget()
    if not budget_ok:
        await db.mailbox_assessment_receipts.update_one(key, {"$set": {
            "state": "budget_paused",
            "processing_until": None,
            "screening_result": "suspicious",
            "triage_outcome": triage_result.outcome.value,
            "triage_reason": triage_result.reason,
            "triage_escalation_reason": triage_result.escalation_reason,
            "triage_cost_usd": 0.0,
            "budget_spent": budget_spent,
            "budget_limit": budget_limit,
            "updated_at": now_utc(),
        }})
        logger.warning("mailbox_budget_paused device=%s spent=$%.2f limit=$%.2f triage=%s",
                        device_id, budget_spent, budget_limit, triage_result.outcome.value)
        return False  # Budget exhausted — paused, will not launch Magnum DI

    # ─── Case creation (only for escalated items) ───
    if reuse_existing and existing_case_id:
        case = await repo.get_case(device_id, existing_case_id)
    else:
        case = await repo.create_case(device_id, "email", None, initiator="apollo_automatic")
    item = await evidence.ingest_text(device_id, case, f"mailbox-{digest}", text, label=f"{provider} message selected by ongoing monitoring")

    # Ingest the lightweight findings as evidence items
    for index, finding in enumerate(local_findings):
        await evidence.ingest_text(device_id, case, f"mailbox-{digest}-finding-{index}", finding, origin="apollo_inference",
                                   label="ApolloSG background intake observation", coverage=evidence.Coverage(status="examined", unit="items", total=1, examined=1))

    # VirusTotal attachment scanning — only for escalated items (saves API calls for SAFE mail)
    vt_findings = await _scan_attachments_vt(device_id, message, provider)
    for vt_idx, vt_finding in enumerate(vt_findings):
        await evidence.ingest_text(device_id, case, f"mailbox-{digest}-vt-{vt_idx}", vt_finding, origin="apollo_inference",
                                   label="VirusTotal attachment scan", coverage=evidence.Coverage(status="examined", unit="items", total=1, examined=1))

    # ─── Escalate to Magnum DI (Tier 2) ───
    # Pre-gathered specialist intelligence is delivered to Magnum DI as structured
    # Apollo observations via the case's triage_provider_evidence field — not injected
    # into the investigation prompt.
    logger.info("triage_escalation device=%s digest=%s outcome=%s escalation=%s providers=%s",
                 device_id, digest[:12], triage_result.outcome.value, (triage_result.escalation_reason or "")[:80], triage_result.providers_used)
    turn_id = str(uuid.uuid4())
    investigation_prompt = (
        "Investigate this monitored email. Verify its sender, claims and every material link; "
        "explain one safe next action."
    )
    payload = {"message": investigation_prompt,
               "answerToQuestionId": None, "evidenceIds": [item.id], "turnId": turn_id}
    job = await repo.create_job(device_id, case, turn_id, repo.digest(f"mailbox:{digest}"), repo.digest(str(payload)), "turn", payload, source="mailbox_monitor")
    updated = await repo.cas(device_id, case["case_id"], {"revision": case["revision"], "active_job_id": None},
                             {"$set": {"status": "queued", "active_job_id": job["job_id"], "active_turn_id": turn_id}})
    if not updated:
        raise RuntimeError("mailbox case ownership conflict")
    # Store triage provider evidence on the case for downstream tool deduplication.
    # Also store source metadata for the patrol event projection (Original Item Summary).
    case_updates: dict = {}
    if triage_result.provider_evidence:
        case_updates["triage_provider_evidence"] = triage_result.provider_evidence
    # Source metadata — actual recorded email identifiers, NOT Gemini-inferred.
    case_updates["source_metadata"] = {
        "type": "email",
        "sender": sender or None,
        "subject": subject or None,
        "received_at": receipt.get("received_at") or receipt.get("created_at") or now_utc(),
        "reply_to": reply_to if reply_to and reply_to != sender else None,
        "attachment_count": len(attachment_names),
        "attachment_names": attachment_names[:5],
        "auth_passed": bool(auth_results and any(auth_results.get(m) == "pass" for m in ("spf", "dkim", "dmarc"))),
        "link_count": len(links),
        "provider": provider,
    }
    if case_updates:
        await db.investigation_cases.update_one(
            {"owner_id": device_id, "case_id": case["case_id"]},
            {"$set": case_updates})
    await db.mailbox_assessment_receipts.update_one(key, {"$set": {
        "state": "submitted",
        "screening_result": "suspicious",
            "triage_outcome": triage_result.outcome.value,
        "triage_reason": triage_result.reason,
        "triage_escalation_reason": triage_result.escalation_reason,
        "triage_cost_usd": 0.0,
        "case_id": case["case_id"],
        "job_id": job["job_id"],
        "updated_at": now_utc(),
    }})
    await work_dedupe.attach(device_id, "email", content, case_id=case["case_id"])
    if triage_result.investigation is not None:
        from services.triage import record_triage_history
        try:
            await record_triage_history(device_id, triage_result.investigation, category="email",
                                        evidence_source="connected_mailbox", subject=subject,
                                        source=case_updates["source_metadata"],
                                        investigation_case_id=case["case_id"])
        except Exception as exc:
            logger.warning("triage_history_write_failed device=%s error=%s", device_id, type(exc).__name__)
    jobs.launch(device_id, case["case_id"], job["job_id"])
    return True


async def _finalise_receipt(receipt: dict) -> None:
    owner, case_id, job_id = receipt["device_id"], receipt["case_id"], receipt["job_id"]
    try:
        case = await repo.get_case(owner, case_id)
        job = await repo.get_job(owner, case_id, job_id)
    except Exception:
        # Distinguish temporary backend unavailability from terminal failure. Use a "retry_failed"
        # state so the receipt remains eligible for re-processing by _submit_shared_case.
        await db.mailbox_assessment_receipts.update_one({"provider": receipt["provider"], "device_id": owner, "message_digest": receipt["message_digest"]},
                                                         {"$set": {"state": "failed", "failure": "temporary_case_unavailable", "retry_after": now_utc() + timedelta(minutes=5), "updated_at": now_utc()}})
        return
    if job["status"] in ("queued", "investigating", "retry_wait", "waiting_device"):
        return
    selector = {"provider": receipt["provider"], "device_id": owner, "message_digest": receipt["message_digest"], "state": "submitted"}
    if not case.get("response_ciphertext"):
        if job["status"] in ("failed", "cancelled", "expired"):
            await db.mailbox_assessment_receipts.update_one(selector, {"$set": {"state": "failed", "failure": job["status"], "updated_at": now_utc()}})
        return
    await db.mailbox_assessment_receipts.update_one(selector, {"$set": {"state": "complete", "processed_at": now_utc(), "updated_at": now_utc()}})
    # C2: Update the gmail connection's assessment timestamp
    try:
        await db.gmail_connections.update_one(
            {"device_id": owner},
            {"$set": {"monitor_last_assessment_at": now_utc()}}
        )
    except Exception:
        pass
    # Push notification is handled exclusively by the investigation projector:
    # project_committed_cases() creates a Patrol event from the completed case, and
    # push_owner_alert() fires for events with state >= growling. This eliminates the
    # duplicate push path that previously existed here (_send_assessment_push).


async def finalise_pending_assessments() -> None:
    async for receipt in db.mailbox_assessment_receipts.find({"state": "submitted"}, {"_id": 0}).limit(100):
        await _finalise_receipt(receipt)


async def scan_gmail_through_shared_pipeline(device_id: str, intake_mode: str, email: str | None = None) -> dict:
    """One page for one account. Incremental per account: each connected mailbox keeps its own checkpoint (the newest
    message time a finished pass covered). A pass asks Gmail only for mail after it, page by page; when the pass ends
    the checkpoint moves to the newest message it handled — but never past a message paused by the spending limit, so
    paused mail is read again later. Messages already handled are skipped by their receipts."""
    lease = str(uuid.uuid4()); now = now_utc()
    lease_query: dict = {"device_id": device_id, "$or": [{"monitor_lease_until": {"$lte": now}}, {"monitor_lease_until": {"$exists": False}}, {"monitor_lease_until": None}]}
    if email:
        lease_query["email"] = email
    row = await db.gmail_connections.find_one_and_update(
        lease_query,
        {"$set": {"monitor_lease": lease, "monitor_lease_until": now + timedelta(seconds=90), "monitor_last_attempt_at": now}},
        projection={"_id": 0, "monitor_next_page_token": 1, "email": 1, "monitor_checkpoint_ms": 1, "monitor_pass_floor_ms": 1,
                    "monitor_pass_max_ms": 1, "monitor_pass_hold_ms": 1},
        return_document=ReturnDocument.AFTER,
    )
    if row is None:
        exists = await db.gmail_connections.find_one({"device_id": device_id}, {"_id": 1})
        if exists is None:
            raise HTTPException(404, "Gmail is not connected")
        return {"status": "busy", "checked": 0, "accepted": 0, "nextCursor": None}
    account = row.get("email")
    lease_filter = {"device_id": device_id, "monitor_lease": lease}
    cursor = row.get("monitor_next_page_token")
    # A pass in progress keeps the floor it started with; a new pass starts at the account's checkpoint.
    floor = row.get("monitor_pass_floor_ms") if cursor else row.get("monitor_checkpoint_ms")
    try:
        scan_kwargs: dict = {"email": account}
        if floor:
            scan_kwargs["after_ms"] = floor
        messages, next_cursor = await gmail.scan_inbox_page(device_id, cursor, **scan_kwargs)
        accepted = 0
        for message in messages:
            accepted += int(await _submit_shared_case("gmail", device_id, message, intake_mode))
        times = [int(m["internal_date"]) for m in messages if str(m.get("internal_date") or "").isdigit()]
        paused = {r["message_digest"] async for r in db.mailbox_assessment_receipts.find(
            {"provider": "gmail", "device_id": device_id, "state": "budget_paused",
             "message_digest": {"$in": [_message_digest("gmail", str(m.get("id", ""))) for m in messages]}}, {"message_digest": 1})}
        held = [int(m["internal_date"]) for m in messages if _message_digest("gmail", str(m.get("id", ""))) in paused
                and str(m.get("internal_date") or "").isdigit()]
        pass_max = max([*times, *([row["monitor_pass_max_ms"]] if cursor and row.get("monitor_pass_max_ms") else [])], default=None)
        pass_hold = min([*held, *([row["monitor_pass_hold_ms"]] if cursor and row.get("monitor_pass_hold_ms") else [])], default=None)
        progress: dict = {"monitor_next_page_token": next_cursor}
        if next_cursor:
            progress.update(monitor_pass_floor_ms=floor, monitor_pass_max_ms=pass_max, monitor_pass_hold_ms=pass_hold)
        else:
            checkpoint = row.get("monitor_checkpoint_ms")
            if pass_max:
                newest = pass_max if pass_hold is None else min(pass_max, pass_hold - 1000)
                checkpoint = max(checkpoint or 0, newest) or checkpoint
            progress.update(monitor_checkpoint_ms=checkpoint, monitor_pass_floor_ms=None, monitor_pass_max_ms=None, monitor_pass_hold_ms=None)
        # C2: Distinguish successful retrieval from completed assessment. `monitor_last_success_at`
        # now reflects RETRIEVAL success only. `monitor_last_assessment_at` tracks when assessments
        # actually complete (updated by finalise_pending_assessments). The Email Gate should check
        # BOTH timestamps — retrieval without assessment means the gate is degraded, not working.
        await db.gmail_connections.update_one(lease_filter, {"$set": {
            **progress, "monitor_last_checked_at": now_utc(),
            "monitor_last_retrieval_at": now_utc(),  # C2: renamed from monitor_last_success_at
            "monitor_last_success_at": now_utc(),    # kept for backward compat; gate must also check assessment
            "monitor_last_error_at": None, "monitor_last_error": None, "monitor_lease": None, "monitor_lease_until": None,
        }})
        return {"status": "accepted", "checked": len(messages), "accepted": accepted, "nextCursor": next_cursor}
    except Exception as exc:
        await db.gmail_connections.update_one(lease_filter, {"$set": {
            "monitor_last_error_at": now_utc(), "monitor_last_error": type(exc).__name__, "monitor_lease": None, "monitor_lease_until": None,
        }})
        raise


async def monitor_enabled_mailboxes_once() -> None:
    async for row in db.gmail_connections.find({"monitoring_enabled": True, "refresh_token_enc": {"$exists": True}}, {"_id": 0, "device_id": 1, "email": 1}):
        try:
            await scan_gmail_through_shared_pipeline(row["device_id"], "monitored", row.get("email"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("gmail mailbox monitoring failed for one device: %s", type(exc).__name__)


async def mailbox_monitor_loop() -> None:
    loop = asyncio.get_running_loop(); next_scan = 0.0
    while True:
        try:
            await finalise_pending_assessments()
            if loop.time() >= next_scan:
                await monitor_enabled_mailboxes_once(); next_scan = loop.time() + SCAN_SECONDS
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("mailbox monitor pass failed: %s", type(exc).__name__)
        await asyncio.sleep(PENDING_SECONDS)


async def supervise_mailbox_monitor() -> None:
    failures = 0
    while True:
        try:
            await mailbox_monitor_loop()
            failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - final ownership boundary
            failures += 1
            delay = min(60, 2 ** min(failures, 5)) + random.random()
            logger.error("mailbox monitor exited: %s; retrying in %.2fs", type(exc).__name__, delay)
            await asyncio.sleep(delay)