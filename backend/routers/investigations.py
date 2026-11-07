"""Authenticated case API (spec §8). Owner identity comes from the bearer device; IDs never authorise another owner's data."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Body, File, Form, Header, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field, TypeAdapter, ValidationError
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from core import local_time
from core.config import HIBP_API_KEY, IPQS_API_KEY, SAFE_BROWSING_API_KEY
from core.db import db, now_utc
from core.redaction import redact_investigation_secrets
from services.email import email_configured
from services import device_pickup, work_dedupe
from services.investigation_projector import project_case_now, project_case_started
from services.storage import storage_configured
from routers.push import push_configured
from services.higgins import evidence as ev
from services.higgins import jobs
from services.higgins import ai_settings
from services.higgins import outcomes, presenter
from services.higgins import provider
from services.higgins import repository as repo
from services.higgins import tc_flyby
from services.higgins.capacity import EVIDENCE_RETENTION_SECONDS
from services.higgins.capacity import ITEMS, TEMPORARY_RETENTION, TEXT, policy
from services.higgins.contracts import (CreateCase, CreateUpload, DeviceProfile, DeviceResult, EvidenceSubmission, ExpectedObservation, ExpectedRevision,
                                        RecheckRequest, RecheckResult, RetryAttempt, SettingsPlan, SettingsPlanRequest, Submission, SubmitTurn,
                                        UUID_PATTERN, UploadMetadata, Wire)
from services.higgins.encryption import cipher, decrypt, encrypt
from services.higgins.repository import http
from services.investigation_lifecycle import (
    CHECK_CLAIM, same_evidence_case, first_job, _submit_turn,
    _pregather_specialist_evidence, _build_source_metadata, infer_gate,
)

router = APIRouter()
NO_STORE = {"Cache-Control": "private, no-store", "Pragma": "no-cache"}
ACTIVE = ("queued", "investigating", "retry_wait", "waiting_device")

# ContextVar used by background_text_intake to pass pre-gathered provider evidence
# into create_case — prevents a double provider-query for the same indicators.
# Each asyncio Task has its own context so this never leaks across requests.
_PRELOADED_PE: ContextVar[dict | None] = ContextVar("_preloaded_pe", default=None)


def owner_of(request: Request) -> str:
    return request.state.device["device_id"]


def _key(idempotency_key: Optional[str]) -> str:
    if not idempotency_key or not re.match(r"^[A-Za-z0-9._:-]{8,80}$", idempotency_key):
        raise http(400, "invalid_input", "An Idempotency-Key header (8–80 URL-safe characters) is required for this operation.")
    return idempotency_key




def _revision_check(case: dict, expected: int) -> None:
    if case["revision"] != expected:
        raise http(409, "conflict", f"The investigation changed (revision {case['revision']}). Reload it and resubmit with the current revision.")


async def _case_json(case: dict) -> dict:
    return {"case": (await repo.case_view(case)).wire()}


# ------------------------------------------------------------------ capabilities
@router.get("/ai/capabilities")
async def capabilities():
    sel = await ai_settings.selection()
    config = provider.configuration(sel["provider"])
    model = sel["model"]
    key = config["keyConfigured"]

    def modality(name: str, model: str, cap: str):
        supported = cap in ai_settings.capabilities(model) and config["connected"]
        status = "available" if key and supported else ("unconfigured" if not key else "unsupported")
        return {"name": name, "status": status, "model": model,
                "reason": None if status == "available" else (f"{config['provider']} API key missing" if not key else f"model lacks {cap}")}
    integrations = [{"name": "safe_browsing", "status": "available" if SAFE_BROWSING_API_KEY else "unconfigured", "reason": None if SAFE_BROWSING_API_KEY else "SAFE_BROWSING_API_KEY"},
                    {"name": "phone_reputation", "status": "available" if IPQS_API_KEY else "unconfigured", "reason": None if IPQS_API_KEY else "IPQS_API_KEY"},
                    {"name": "breach_lookup", "status": "available" if HIBP_API_KEY else "unconfigured", "reason": None if HIBP_API_KEY else "HIBP_API_KEY"},
                    {"name": "guardian_email", "status": "available" if email_configured() else "unconfigured", "reason": None if email_configured() else "RESEND_API_KEY / RESEND_FROM_EMAIL"},
                    {"name": "push_delivery", "status": "available" if push_configured() else "unconfigured", "reason": None if push_configured() else "EMERGENT_PUSH_KEY"},
                    {"name": "family_voice_storage", "status": "available" if storage_configured() else "unconfigured", "reason": None if storage_configured() else "FAMILY_STORAGE_BUCKET / ACCESS_KEY_ID / SECRET_ACCESS_KEY"}]
    bounds = {**policy()["bounds"], "fileBytes": {"value": ev.MAX_FILE_BYTES, "unit": "bytes", "purpose": "per-file upload ceiling", "overflow": "413; item listed as not received"},
              "caseBytes": {"value": ev.MAX_CASE_BYTES, "unit": "bytes", "purpose": "aggregate active-case payload", "overflow": "413"},
              "documentPages": {"value": ev.MAX_PAGES, "unit": "pages", "purpose": "supported document budget", "overflow": "later pages recorded as omitted"},
              "lifetimeSeconds": {"value": policy()["lifetimeSeconds"], "unit": "seconds", "purpose": "temporary content ceiling; never extended", "overflow": "410"}}
    return JSONResponse({"schemaVersion": 1, "provider": sel["provider"], "modalities": [modality("text", model, "text"), modality("vision", model, "vision"),
                         modality("research", model, "search")], "policyVersion": policy()["version"], "bounds": bounds, "integrations": integrations,
                         "providerMode": provider.get_provider_mode(),
            "models": {"magnum_di": model, "tc_flyby": model}, "researchCoordinator": "shared_case_engine"}, headers=NO_STORE)


# ── Source metadata builder and specialist evidence pre-gathering are defined
# in services/investigation_lifecycle.py and imported above.



async def _launch_investigation(
    owner: str,
    gate: str | None,
    question: str,
    submissions: list[dict],
    initial_findings: list[str] | None = None,
    intel_evidence: list[dict] | None = None,
    triage_provider_evidence: dict | None = None,
    source_metadata: dict | None = None,
    initiator: str = "user_check",
    client_submission_id: str | None = None,
) -> tuple[str | None, dict | None, str | None]:
    """Shared investigation lifecycle for compatibility gates.

    Creates case → ingests evidence → stores metadata → submits first turn.
    Returns (case_id, job_wire_dict, error). The error is a short, honest sentence when any stage
    failed — the gate passes it to the person instead of returning a silent "no investigation".
    A case_id is still returned when the case exists but a later stage failed, so what DID complete
    is not thrown away.

    Used by analysis.py compatibility endpoints (/message/analyse,
    /link/investigate) so the duplicate _create_investigation_case is removed
    and every investigation follows the canonical path.
    """
    case_id: str | None = None
    try:
        earlier, claim = await same_evidence_case(owner, [(s["kind"], s["value"]) for s in (submissions or [])])
        if earlier:
            job = await first_job(owner, earlier["case_id"])
            return earlier["case_id"], repo.job_view(job).wire() if job else None, None
        case = await repo.create_case(owner, gate, None, client_submission_id=client_submission_id, initiator=initiator)
        case_id = case["case_id"]
        if claim:
            await work_dedupe.attach(owner, CHECK_CLAIM, claim, case_id=case_id)

        # Ingest submitted evidence items
        for sub in (submissions or []):
            if sub["kind"] == "url":
                await ev.ingest_url(owner, case, sub["client_item_id"],
                                    sub["value"], label=sub.get("label", ""))
            else:
                await ev.ingest_text(owner, case, sub["client_item_id"],
                                     sub["value"],
                                     label=sub.get("label", "submitted text"))

        # Ingest pre-gathered specialist intelligence as evidence items. An item where no provider
        # returned anything holds no intelligence, so it is not recorded as evidence.
        for idx, intel_item in enumerate(intel_evidence or []):
            if not ev.has_intelligence(intel_item):
                continue
            await ev.ingest_text(
                owner, case, f"intel-{idx}",
                json.dumps(intel_item, ensure_ascii=False, default=str),
                origin="apollo_inference",
                label=intel_item.get("label", "Pre-gathered specialist intelligence"),
                coverage=ev.Coverage(status="examined", unit="items", total=1, examined=1))

        # Ingest Apollo initial findings
        for idx, finding in enumerate(initial_findings or []):
            await ev.ingest_text(
                owner, case, f"apollo-finding-{idx}", finding,
                origin="apollo_inference", label="Apollo initial finding",
                coverage=ev.Coverage(status="examined", unit="items", total=1, examined=1))

        # Source metadata (actual recorded identifiers — never Gemini-inferred)
        if source_metadata:
            await db.investigation_cases.update_one(
                {"owner_id": owner, "case_id": case_id},
                {"$set": {"source_metadata": source_metadata}})

        # Build triage_provider_evidence from intel if not already supplied
        _triage = triage_provider_evidence
        if not _triage and intel_evidence:
            _triage = {}
            for item in intel_evidence:
                key = item.get("label", f"intel_{len(_triage)}")
                _triage[key] = item

        if _triage:
            await db.investigation_cases.update_one(
                {"owner_id": owner, "case_id": case_id},
                {"$set": {"triage_provider_evidence": _triage}})

        # The case is findable from the moment it starts: write its patrol record now so that
        # call-investigate and Ask-Higgins-initiated cases appear in Threats while running,
        # not only after they answer. Same deterministic event id the committed projection
        # updates later — one record per case, identical path as POST /investigations.
        await project_case_started({**case, "source_metadata": source_metadata, "owner_id": owner})

        # Submit the first investigation turn
        if question.strip():
            idem_key = f"compat-{gate or 'general'}-{case_id}"
            job = await _submit_turn(
                owner, case,
                SubmitTurn(expected_revision=0,
                           turn_id=str(uuid.uuid4()),
                           message=question),
                idem_key)
            if not job:
                return case_id, None, "ApolloSG opened the investigation but Magnum DI did not start a turn on it."
            return case_id, repo.job_view(job).wire(), None
        return case_id, None, None
    except Exception as exc:
        __import__("logging").getLogger("apollo.investigations").warning(
            "_launch_investigation failed (gate=%s): %s", gate, type(exc).__name__)
        stage = "while preparing the evidence" if case_id else "while opening the case"
        return case_id, None, f"ApolloSG couldn't start the Magnum DI investigation {stage} ({type(exc).__name__})."



# ------------------------------------------------------------------ cases
@router.post("/investigations", status_code=201)
async def create_case(body: CreateCase, request: Request, idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    owner = owner_of(request)
    cipher()
    key = _key(idempotency_key)
    if len(body.submissions) + len(body.initial_findings) > ITEMS.value:
        raise http(413, "budget_exhausted", f"This request contains more than {ITEMS.value} evidence items. Submit a bounded batch, then append the continuation to the same case.")
    supplied_characters = len(body.question) + sum(len(item.value) for item in body.submissions) + sum(len(item) for item in body.initial_findings)
    if supplied_characters > TEXT.value:
        raise http(413, "budget_exhausted", f"This request contains more than {TEXT.value} text characters. Submit a bounded batch, then append the continuation to the same case.")
    existing, payload_digest = await repo.idempotent(owner, "create", key, body.model_dump_json())
    if existing:
        case = await repo.get_case(owner, existing["result"]["caseId"])
        return JSONResponse(await _case_json(case), status_code=201, headers=NO_STORE)

    # Gate provenance: if the client didn't supply a gate, infer it from the
    # evidence items so the investigation is properly attributed from creation.
    gate = body.gate
    if not gate and body.submissions:
        gate = infer_gate(body.submissions, body.question)

    # The same evidence already checked on this device: that case, not a new one (no new work, no new AI call).
    earlier, claim = await same_evidence_case(owner, [(item.kind, item.value) for item in body.submissions])
    if earlier:
        await repo.remember(owner, "create", key, payload_digest, {"caseId": earlier["case_id"]}, repo.utc(earlier["expires_at"]))
        job = await first_job(owner, earlier["case_id"])
        return JSONResponse({**await _case_json(earlier), "job": repo.job_view(job).wire() if job else None, "sameEvidence": True},
                            status_code=201, headers=NO_STORE)
    try:
        case = await repo.create_case(owner, gate, body.device_profile.wire() if body.device_profile else None, initiator="user_check", origin=body.origin,
                                      client_submission_id=body.patrol_event_id)
    except Exception:
        if claim:
            await work_dedupe.release(owner, CHECK_CLAIM, claim)
        raise
    if claim:
        await work_dedupe.attach(owner, CHECK_CLAIM, claim, case_id=case["case_id"])
    for item in body.submissions:
        if item.kind == "url":
            await ev.ingest_url(owner, case, item.client_item_id, item.value, label=item.label)
        else:
            await ev.ingest_text(owner, case, item.client_item_id, item.value, label=item.label or "submitted text")
    for index, finding in enumerate(body.initial_findings):
        await ev.ingest_text(owner, case, f"apollo-finding-{index}", finding, origin="apollo_inference", label="Apollo initial finding",
                             coverage=ev.Coverage(status="examined", unit="items", total=1, examined=1))
    question = redact_investigation_secrets(body.question)

    # ── Source metadata: record what was submitted (actual items, NOT Gemini-inferred) ──
    # This flows through to the patrol event via the investigation projector, enabling
    # the Original Item Summary on the investigation detail screen.
    _source_meta = _build_source_metadata(gate, body.submissions, body.question)
    if _source_meta:
        await db.investigation_cases.update_one(
            {"owner_id": owner, "case_id": case["case_id"]},
            {"$set": {"source_metadata": _source_meta}})

    await repo.remember(owner, "create", key, payload_digest, {"caseId": case["case_id"]}, repo.utc(case["expires_at"]))

    # The case is findable from the moment it starts: give it its patrol record now, so an
    # investigation begun in Ask Higgins is listed in Threats while it runs, not only once it answers.
    # Same deterministic event id the committed projection updates later — one record per case.
    await project_case_started({**case, "source_metadata": _source_meta, "owner_id": owner})

    # ── Pre-gather specialist evidence for Magnum DI ──────────────────────────
    # Before the expensive Magnum DI reasoning begins, automatically gather all
    # relevant free/already-paid specialist evidence for the submitted items.
    # Stored as `triage_provider_evidence` on the case document; Magnum DI's
    # tools read this for deduplication and the coordinator receives it as
    # structured Apollo observations — NOT injected into the person's question.
    # ── Pre-gather specialist evidence for Magnum DI ──────────────────────────
    # If the caller (e.g. background_text_intake) already gathered provider
    # evidence via triage_item, it sets _PRELOADED_PE so we skip a second,
    # identical round of outbound provider calls.
    _preloaded = _PRELOADED_PE.get(None)
    if _preloaded is not None:
        if _preloaded:
            await db.investigation_cases.update_one(
                {"owner_id": owner, "case_id": case["case_id"]},
                {"$set": {"triage_provider_evidence": _preloaded}})
    elif question.strip():
        try:
            provider_evidence = await _pregather_specialist_evidence(gate, body.submissions)
            if provider_evidence:
                await db.investigation_cases.update_one(
                    {"owner_id": owner, "case_id": case["case_id"]},
                    {"$set": {"triage_provider_evidence": provider_evidence}})
        except Exception as exc:
            __import__("logging").getLogger("apollo.investigations").warning(
                "pregather_evidence_failed case=%s error=%s", case["case_id"], type(exc).__name__)

    # A non-blank opening question is the first turn; otherwise the client attaches evidence first.
    job = await _submit_turn(owner, case, SubmitTurn(expected_revision=0, turn_id=str(uuid.uuid4()), message=question), key + ":turn0") if question.strip() else None
    case = await repo.get_case(owner, case["case_id"])
    return JSONResponse({**await _case_json(case), "job": repo.job_view(job).wire() if job else None}, status_code=201, headers=NO_STORE)


class BackgroundTextIn(Wire):
    submission_id: str = Field(pattern=UUID_PATTERN)
    source_key: str = Field(min_length=1, max_length=500)
    revision_digest: str = Field(min_length=16, max_length=128)
    sender: str = Field(default="", max_length=2048)
    text: str = Field(min_length=1, max_length=250_000)
    captured_at: datetime
    expires_at: datetime
    content_complete: bool = True
    original_characters: int = Field(ge=1, le=10_000_000)


async def _record_triage_history(owner: str, triage_result, *, category: str, source: dict | None = None,
                                 client_submission_id: str | None = None,
                                 investigation_case_id: str | None = None) -> None:
    """Save a completed Triage Investigation to Patrol History — every outcome, zero Gemini calls."""
    from services.triage import record_triage_history
    if triage_result.investigation is None:
        return  # cache replay of an already-recorded investigation
    try:
        await record_triage_history(owner, triage_result.investigation, category=category, source=source,
                                    evidence_source="device_submission",  # the captured notification this device sent
                                    client_submission_id=client_submission_id,
                                    investigation_case_id=investigation_case_id)
    except Exception as exc:
        __import__("logging").getLogger("apollo.triage").warning(
            "triage_history_write_failed owner=%s error=%s", owner, type(exc).__name__)


@router.post("/investigations/background/text", status_code=202)
async def background_text_intake(body: BackgroundTextIn, request: Request):
    """One durable intake path shared by the OS worker and foreground drain.

    Now includes Higgins Triage (3-tier screening) before escalating to Magnum DI.
    User-initiated Check bypasses this — only background-captured messages are triaged.
    """
    if repo.utc(body.expires_at) <= now_utc():
        raise http(410, "evidence_expired", "This captured notification reached its fixed retention deadline.")

    # ── Higgins Triage: screen before creating a full investigation ──
    from services.triage_engine import triage_item, _extract_evidence_from_text

    owner = owner_of(request)
    triage_evidence = _extract_evidence_from_text(body.sender, body.text)
    correlation_id = f"sms-triage-{body.submission_id[:20]}"

    # The rules read the message itself; a word such as "password" or "account" is never a finding on its own.
    triage_result = await triage_item(
        device_id=owner,
        evidence=triage_evidence,
        findings=[],
        correlation_id=correlation_id,
    )
    source = {"type": "text", "sender": body.sender or None, "preview": body.text or None, "received_at": now_utc(),
              "content_complete": body.content_complete}

    if not triage_result.should_escalate:
        # Deterministic Triage resolved NO THREAT or LIMITED → acknowledge intake, zero Gemini calls.
        _log_triage = __import__("logging").getLogger("apollo.triage")
        _log_triage.info("background_text_triage device=%s submission=%s outcome=%s",
                          owner, body.submission_id[:12], triage_result.outcome.value)
        await _record_triage_history(owner, triage_result, category="message", source=source,
                                     client_submission_id=body.submission_id)
        return JSONResponse({
            "caseId": None,
            "jobId": None,
            "acceptedAt": now_utc().isoformat(),
            "triage": triage_result.wire(),
        }, status_code=202, headers=NO_STORE)

    # ── Triage escalated: proceed to full investigation ──
    # Pre-gathered specialist intelligence is delivered to Magnum DI as structured
    # Apollo observations via the case's triage_provider_evidence field — not injected
    # into the person's question.
    limitation = "" if body.content_complete else f"\n\nCapture limitation: Android exposed {body.original_characters} characters; ApolloSG retained the first {len(body.text)} under its admission policy."
    submission = Submission(client_item_id=f"sms-{body.submission_id[:70]}", kind="text",
                            value=f"From: {body.sender}\n{body.text}{limitation}", label="opt-in text notification")
    investigation_question = (
        "Investigate this captured text-message notification, verify its claims and links, "
        "and identify the safest next action."
    )
    payload = CreateCase(gate="text", question=investigation_question, submissions=[submission])
    # Finding A: signal to create_case that provider evidence is already available so it
    # skips its own _pregather_specialist_evidence call (eliminates the double query).
    _pe_token = _PRELOADED_PE.set(triage_result.provider_evidence or {})
    try:
        response = await create_case(payload, request, idempotency_key=f"sms-notification-{body.submission_id}")
    finally:
        _PRELOADED_PE.reset(_pe_token)
    data = json.loads(response.body)
    # Server-owned: set client_submission_id and source metadata on the case document.
    # triage_provider_evidence is now written by create_case via _PRELOADED_PE — no double write.
    case_update: dict = {"client_submission_id": body.submission_id, "initiator": "apollo_automatic", "origin": "apollo"}
    # Source metadata — actual recorded text/SMS identifiers, NOT Gemini-inferred.
    case_update["source_metadata"] = source
    await db.investigation_cases.update_one(
        {"owner_id": owner_of(request), "case_id": data["case"]["id"]},
        {"$set": case_update})
    await _record_triage_history(owner, triage_result, category="message", source=source,
                                 client_submission_id=body.submission_id,
                                 investigation_case_id=data["case"]["id"])
    return JSONResponse({"caseId": data["case"]["id"], "jobId": data.get("job", {}).get("id") if data.get("job") else None,
                         "acceptedAt": now_utc().isoformat(),
                         "triage": triage_result.wire()}, status_code=202, headers=NO_STORE)


@router.get("/investigations/storage")
async def get_storage_info(request: Request):
    """Return investigation storage info — server no longer retains completed investigations."""
    return JSONResponse({
        "usedBytes": 0,
        "limitBytes": 0,
        "usedMB": 0,
        "limitMB": 0,
        "evidenceRetentionHours": EVIDENCE_RETENTION_SECONDS // 3600 if EVIDENCE_RETENTION_SECONDS else 24,
        "reportRetentionDays": 0,
        "serverRetention": "none",
        "storageLocation": "device_only",
    }, headers=NO_STORE)


@router.get("/investigations/{case_id}/export/pdf")
async def export_investigation_pdf(case_id: str, request: Request):
    """Generate and return a branded Apollo investigation PDF.
    The PDF includes the full Magnum DI investigation, Higgins explanation,
    Evidentiary Chain metadata, sources, and retention information."""
    from services.higgins.di_record import get_di_records
    from services.higgins.pdf_export import generate_pdf
    owner = owner_of(request)
    case_doc = await repo.get_case(owner, case_id)
    case_wire = (await repo.case_view(case_doc)).wire()
    evidence_rows = await repo.list_evidence(owner, case_id)
    evidence_wire = [repo.evidence_view(r).wire() for r in evidence_rows]
    subject = (case_wire.get("response") or {}).get("subject", "Investigation")
    # Tagged when any external source behind it was simulated: Magnum DI's Gemini call or TC Hawkeye's search.
    flyby = ((await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id}, {"_id": 0, "routing.tc_flyby.simulated": 1}) or {})
             .get("routing") or {}).get("tc_flyby") or {}
    simulated = bool(flyby.get("simulated")) or any(r.get("simulated") for r in await get_di_records(owner, case_id))
    # Every time in the report is the phone's local time: the offset it sends now, else the one it registered.
    sent = request.query_params.get("tzOffset", "")
    if re.fullmatch(r"-?\d{1,3}", sent):
        tz_offset = int(sent)
    else:
        tz_offset = ((await db.devices.find_one({"device_id": owner}, {"_id": 0, "tz_offset_minutes": 1})) or {}).get("tz_offset_minutes", 0)
    pdf_bytes = generate_pdf(case_wire, evidence_wire, subject=subject, simulated=simulated, tz_offset_minutes=local_time.clamp(tz_offset))
    safe_subject = re.sub(r'[^\w\s-]', '', subject)[:40].strip().replace(" ", "_") or "report"
    filename = f"Apollo_{safe_subject}_{case_id[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
            **NO_STORE,
        })


@router.get("/investigations/{case_id}")
async def get_case(case_id: str, request: Request):
    case = await repo.get_case(owner_of(request), case_id)
    return JSONResponse(await _case_json(case), headers=NO_STORE)


@router.get("/investigations/{case_id}/di")
async def get_di_transactions(case_id: str, request: Request):
    """How this case was investigated, for the DI tab: the recorded decision path (Higgins Triage → TC Hawkeye →
    Magnum DI → Evidence Lock) and each Magnum DI transaction described — whether it finished, live or the preview
    simulator, and what it was handed. Token counts, cost, the prompts, the full reply and rule-book codes stay in
    the Admin Portal. Evidence is untouched by this view."""
    from services.higgins.di_record import decision_trace, get_di_records
    owner = owner_of(request)
    # Authorise against the case document itself: the DI record outlives the evidence retention
    # window, so an expired or cleaned-up case must still be able to show how it was processed.
    if not await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id}, {"_id": 1}):
        raise http(404, "not_found", "No investigation with that reference belongs to this device.")
    # Every record is returned, in every environment. A simulated one carries `simulated: true` and its
    # own "SIMULATED" notice; withholding it would hide the fact that Gemini never answered, which is
    # exactly how production once ran on the simulator unnoticed.
    records = await get_di_records(owner, case_id)
    return JSONResponse({"caseId": case_id, "transactions": records, "trace": await decision_trace(owner, case_id)}, headers=NO_STORE)


@router.delete("/investigations/{case_id}")
async def delete_case(case_id: str, request: Request):
    owner = owner_of(request)
    if not await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id}, {"_id": 1}):
        raise http(404, "not_found", "No investigation with that reference belongs to this device.")
    await repo.revoke(owner, case_id, "deleted")
    await device_pickup.release(owner, case_id)  # the person deleted the check: the phone's held copy goes too
    status = await repo.run_cleanup(owner, case_id)
    return Response(status_code=204 if status == "complete" else 202, headers=NO_STORE)


# ------------------------------------------------------------------ evidence
@router.post("/investigations/{case_id}/evidence", status_code=201)
async def add_evidence(case_id: str, request: Request, file: Optional[UploadFile] = File(default=None), metadata: Optional[str] = Form(default=None)):
    owner = owner_of(request)
    case = await repo.get_case(owner, case_id, for_mutation=True)
    if file is not None:
        try:
            meta = UploadMetadata.model_validate_json(metadata or "")
        except ValidationError as exc:
            raise http(422, "invalid_input", "Multipart metadata did not match UploadMetadata.") from exc
        _revision_check(case, meta.expected_revision)
        data = await file.read(ev.MAX_FILE_BYTES + 1)
        if len(data) > ev.MAX_FILE_BYTES:
            raise http(413, "budget_exhausted", f"Files above {ev.MAX_FILE_BYTES // (1024 * 1024)} MiB are not accepted.")
        item = await ev.ingest_file(owner, case, meta.wire(), data)
    else:
        try:
            body = TypeAdapter(EvidenceSubmission).validate_python(await request.json())
        except (ValidationError, ValueError) as exc:
            raise http(422, "invalid_input", "Evidence submission did not match the schema.") from exc
        existing = await db.investigation_evidence.find_one(
            {"owner_id": owner, "case_id": case_id, "client_item_id": body.client_item_id}, {"_id": 0}
        )
        if existing:
            value = body.text if body.kind == "text" else (body.url if re.match(r"(?i)^https?://", body.url) else "https://" + body.url) if body.kind == "url" else json.dumps({
                "capabilityId": body.device_result.capability_id, "status": body.device_result.status, "values": body.device_result.values,
            }, ensure_ascii=False)
            meta_existing = repo.dec_json(existing["meta_ciphertext"])
            if meta_existing.get("inputDigest") != ev.text_input_digest(body.kind if body.kind != "observation" else "observation", value):
                raise http(409, "conflict", "This evidence identity was already used for different input.")
            published = await repo.get_evidence(owner, case_id, existing["evidence_id"])
            return JSONResponse({"evidence": repo.evidence_view(published).wire(), "caseRevision": case["revision"], "replayed": True}, status_code=201, headers=NO_STORE)
        _revision_check(case, body.expected_revision)
        if body.kind == "text":
            item = await ev.ingest_text(owner, case, body.client_item_id, body.text, parent_id=body.parent_id, label=body.label)
        elif body.kind == "url":
            item = await ev.ingest_url(owner, case, body.client_item_id, body.url, parent_id=body.parent_id, label=body.label)
        else:
            item = await ev.ingest_observation(owner, case, body.client_item_id, body.device_result.wire(), parent_id=body.parent_id)
    updated = await repo.cas(owner, case_id, {"revision": case["revision"]}, {"$set": {}})
    return JSONResponse({"evidence": item.wire(), "caseRevision": (updated or case)["revision"]}, status_code=201, headers=NO_STORE)


@router.get("/investigations/{case_id}/evidence")
async def list_evidence(case_id: str, request: Request, cursor: Optional[str] = None):
    owner = owner_of(request)
    await repo.get_case(owner, case_id)
    rows = await repo.list_evidence(owner, case_id)
    start = int(cursor or 0)
    page = rows[start:start + 100]
    return JSONResponse({"items": [repo.evidence_view(r).wire() for r in page], "nextCursor": str(start + 100) if len(rows) > start + 100 else None, "total": len(rows)}, headers=NO_STORE)


@router.post("/investigations/{case_id}/evidence-profile", status_code=201)
async def add_email_evidence_profile(case_id: str, request: Request):
    """Better email evidence for a case still under investigation (e.g. the original .eml after a screenshot).

    Only Higgins Triage's minimal findings arrive here — never the original email. A finished or expired case
    answers 410: the server doesn't keep finished investigations, so the phone keeps the new evidence with its case."""
    from services.email_evidence import EmailEvidenceFindings, attach
    owner = owner_of(request)
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) != {"findings"}:
            raise ValueError("findings only")
        findings = EmailEvidenceFindings.model_validate(payload["findings"])
    except (ValidationError, ValueError) as exc:
        raise http(422, "invalid_input", "Email evidence must be Higgins Triage's structured findings only.") from exc
    case = await repo.get_case(owner, case_id, for_mutation=True)
    if case.get("gates") and "email" not in case["gates"]:
        raise http(409, "conflict", "This investigation isn't about an email.")
    item, replayed = await attach(owner, case, findings)
    if not replayed:
        await repo.cas(owner, case_id, {"revision": case["revision"]}, {"$set": {}})
    return JSONResponse({"recorded": True, "replayed": replayed, "evidenceId": getattr(item, "id", None)}, status_code=201, headers=NO_STORE)


@router.get("/investigations/{case_id}/evidence/{evidence_id}")
async def get_single_evidence(case_id: str, evidence_id: str, request: Request):
    """Return a single evidence item's metadata. Available even after evidence content expires."""
    owner = owner_of(request)
    await repo.get_case(owner, case_id)
    row = await repo.get_evidence(owner, case_id, evidence_id, content_required=False)
    return JSONResponse({"evidence": repo.evidence_view(row).wire()}, headers=NO_STORE)


@router.get("/investigations/{case_id}/evidence/{evidence_id}/content")
async def get_evidence_content(case_id: str, evidence_id: str, request: Request):
    """Serve the retained evidence bytes (images, files, text content).
    Returns the actual investigated version of the evidence for the Evidentiary Chain popup.
    Returns 410 if the 24-hour evidence retention period has expired."""
    owner = owner_of(request)
    await repo.get_case(owner, case_id)
    row = await repo.get_evidence(owner, case_id, evidence_id, content_required=True)
    media_type = row.get("media_type", "application/octet-stream")
    try:
        data = await repo.read_bytes(owner, case_id, evidence_id)
    except Exception:
        raise repo.http(410, "evidence_content_expired",
                        "This evidence was automatically deleted after 24 hours to protect your privacy. "
                        "The investigation findings remain available in your saved report.")
    return Response(content=data, media_type=media_type, headers={**NO_STORE, "Content-Length": str(len(data))})



@router.get("/investigations/{case_id}/sources")
async def list_sources(case_id: str, request: Request, cursor: Optional[str] = None):
    owner = owner_of(request)
    await repo.get_case(owner, case_id)
    rows = await repo.sources(owner, case_id)
    start = int(cursor or 0)
    return JSONResponse({"items": rows[start:start + 100], "nextCursor": str(start + 100) if len(rows) > start + 100 else None, "total": len(rows)}, headers=NO_STORE)


# ------------------------------------------------------------------ finding feedback (false-positive reporting)
class FindingFeedback(Wire):
    finding_id: str = Field(pattern=UUID_PATTERN)
    verdict: str = Field(pattern=r"^(incorrect|legitimate)$")
    reason: str = Field(default="", max_length=500)

@router.post("/investigations/{case_id}/feedback", status_code=201)
async def submit_finding_feedback(case_id: str, body: FindingFeedback, request: Request):
    """Record user feedback that a specific finding is incorrect or about a legitimate sender.
    This does NOT auto-whitelist senders or domains — it is stored for review and calibration only."""
    owner = owner_of(request)
    case = await repo.get_case(owner, case_id)
    # Verify the finding ID exists in the case response
    findings = (case.get("response") or {}).get("findings") or []
    if not any(f.get("id") == body.finding_id for f in findings):
        return JSONResponse({"error": "finding_not_found", "detail": f"No finding '{body.finding_id}' in this case."}, status_code=404)
    doc = {
        "case_id": case_id,
        "finding_id": body.finding_id,
        "device_id": owner,
        "verdict": body.verdict,
        "reason": body.reason,
        "created_at": now_utc(),
    }
    # Upsert: one feedback per finding per device
    await db.finding_feedback.update_one(
        {"case_id": case_id, "finding_id": body.finding_id, "device_id": owner},
        {"$set": doc},
        upsert=True,
    )
    return JSONResponse({"ok": True, "findingId": body.finding_id, "verdict": body.verdict}, status_code=201, headers=NO_STORE)

@router.get("/investigations/{case_id}/feedback")
async def list_finding_feedback(case_id: str, request: Request):
    """List all feedback this device has submitted for findings in a case."""
    owner = owner_of(request)
    await repo.get_case(owner, case_id)
    rows = await db.finding_feedback.find(
        {"case_id": case_id, "device_id": owner},
        {"_id": 0, "finding_id": 1, "verdict": 1, "reason": 1, "created_at": 1},
    ).to_list(100)
    return JSONResponse({"items": rows}, headers=NO_STORE)


# ------------------------------------------------------------------ resumable uploads
@router.post("/investigations/{case_id}/uploads", status_code=201)
async def create_upload(case_id: str, body: CreateUpload, request: Request):
    owner = owner_of(request)
    case = await repo.get_case(owner, case_id, for_mutation=True)
    if body.declared_bytes > ev.MAX_FILE_BYTES:
        raise http(413, "budget_exhausted", f"Files above {ev.MAX_FILE_BYTES // (1024 * 1024)} MiB are not accepted.")
    immutable = body.wire(); immutable.pop("expectedRevision", None)
    request_digest = repo.digest(json.dumps(immutable, sort_keys=True))
    existing = await db.investigation_uploads.find_one(
        {"owner_id": owner, "case_id": case_id, "metadata.clientItemId": body.client_item_id}, {"_id": 0}
    )
    if existing:
        if existing.get("request_digest") != request_digest:
            raise http(409, "conflict", "This file identity was already reserved for different immutable input.")
        return JSONResponse({"uploadId": existing["upload_id"], "chunkBytes": repo.CHUNK_BYTES,
                             "expiresAt": repo.utc(existing["expires_at"]).isoformat(),
                             "evidenceRootId": existing["evidence_root_id"], "replayed": True}, status_code=201, headers=NO_STORE)
    _revision_check(case, body.expected_revision)
    upload_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"apollo-upload:{owner}:{case_id}:{body.client_item_id}"))
    evidence_root_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"apollo-evidence:{owner}:{case_id}:{body.client_item_id}"))
    expires = repo.utc(case["expires_at"])
    document = {"owner_id": owner, "case_id": case_id, "upload_id": upload_id, "evidence_root_id": evidence_root_id,
                "request_digest": request_digest, "metadata": body.wire(), "chunks": {}, "finalisation": None,
                "created_at": now_utc(), "expires_at": expires}
    try:
        await db.investigation_uploads.insert_one(document)
        replayed = False
    except DuplicateKeyError:
        existing = await db.investigation_uploads.find_one(
            {"owner_id": owner, "case_id": case_id, "metadata.clientItemId": body.client_item_id}, {"_id": 0}
        )
        if not existing or existing.get("request_digest") != request_digest:
            raise http(409, "conflict", "This file identity was concurrently reserved for different input.")
        upload_id, evidence_root_id, expires, replayed = existing["upload_id"], existing["evidence_root_id"], repo.utc(existing["expires_at"]), True
    return JSONResponse({"uploadId": upload_id, "chunkBytes": repo.CHUNK_BYTES, "expiresAt": expires.isoformat(),
                         "evidenceRootId": evidence_root_id, "replayed": replayed}, status_code=201, headers=NO_STORE)


@router.put("/investigations/{case_id}/uploads/{upload_id}/chunks/{index}", status_code=204)
async def put_chunk(case_id: str, upload_id: str, index: int, request: Request):
    owner = owner_of(request)
    await repo.get_case(owner, case_id, for_mutation=True)
    upload = await db.investigation_uploads.find_one({"owner_id": owner, "case_id": case_id, "upload_id": upload_id, "expires_at": {"$gt": now_utc()}}, {"_id": 0})
    if not upload:
        raise http(404, "not_found", "Unknown or expired upload.")
    if index < 0 or index * repo.CHUNK_BYTES >= upload["metadata"]["declaredBytes"]:
        raise http(413, "budget_exhausted", "Chunk index is outside the declared size.")
    data, received = bytearray(), 0
    async for piece in request.stream():  # stream-limited: never buffer more than one chunk
        received += len(piece)
        if received > repo.CHUNK_BYTES:
            raise http(413, "budget_exhausted", "Chunk exceeds the chunk budget.")
        data.extend(piece)
    chunk_digest = repo.digest(bytes(data).hex())
    try:
        await db.investigation_upload_chunks.insert_one({"owner_id": owner, "case_id": case_id, "upload_id": upload_id, "chunk_index": index, "digest": chunk_digest,
                                                          "ciphertext": encrypt(bytes(data)), "length": len(data), "expires_at": upload["expires_at"]})
    except DuplicateKeyError:
        existing = await db.investigation_upload_chunks.find_one({"owner_id": owner, "upload_id": upload_id, "chunk_index": index}, {"_id": 0, "digest": 1})
        if existing and existing["digest"] != chunk_digest:
            raise http(409, "conflict", "A different chunk was already stored at that index.")
    return Response(status_code=204, headers=NO_STORE)


LEASE_RENEWAL_SECONDS = 40


class LeaseLost(Exception):
    """Raised when a renewable-ownership fence stops matching mid-operation (another attempt took over, or the
    claim was otherwise superseded) — the wrapped work is cancelled promptly rather than left running unsupervised."""


async def _with_lease_renewal(collection, selector: dict, fence_field: str, fence: str, ts_field: str, coro):
    """Keeps a renewable-ownership fence alive for a potentially long-running step, AND stops that step promptly if
    ownership is lost. A heartbeat that only refreshes a timestamp while unrelated work keeps running underneath it
    is not a guard — this races the heartbeat's own write against the work and cancels the work the moment a
    renewal fails to match. The eventual authoritative write at the call site remains separately fenced regardless;
    this only bounds how long a superseded attempt can keep doing work it no longer owns."""
    lost = asyncio.Event()

    async def _heartbeat():
        while True:
            await asyncio.sleep(LEASE_RENEWAL_SECONDS)
            result = await collection.update_one({**selector, fence_field: fence}, {"$set": {ts_field: now_utc()}})
            if result.matched_count == 0:
                lost.set()
                return

    work = asyncio.ensure_future(coro)
    beat = asyncio.ensure_future(_heartbeat())
    try:
        done, _pending = await asyncio.wait({work, beat}, return_when=asyncio.FIRST_COMPLETED)
        if beat in done and work not in done:
            work.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await work
            raise LeaseLost(f"lost ownership of {selector} mid-operation")
        return await work
    finally:
        beat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beat


@router.post("/investigations/{case_id}/uploads/{upload_id}/complete", status_code=201)
async def complete_upload(case_id: str, upload_id: str, body: ExpectedRevision, request: Request):
    owner = owner_of(request)
    case = await repo.get_case(owner, case_id, for_mutation=True)
    upload = await db.investigation_uploads.find_one({"owner_id": owner, "case_id": case_id, "upload_id": upload_id}, {"_id": 0})
    if not upload:
        raise http(404, "not_found", "Unknown or expired upload.")
    if upload.get("evidence_id"):  # finalisation replay after a durable commit resolves to the same evidence
        row = await repo.get_evidence(owner, case_id, upload["evidence_id"])
        return JSONResponse({"evidence": repo.evidence_view(row).wire(), "caseRevision": case["revision"], "replayed": True}, status_code=201, headers=NO_STORE)
    _revision_check(case, body.expected_revision)
    declared = upload["metadata"]["declaredBytes"]
    expected_chunks = (declared + repo.CHUNK_BYTES - 1) // repo.CHUNK_BYTES
    rows = await db.investigation_upload_chunks.find({"owner_id": owner, "upload_id": upload_id}, {"_id": 0}).sort("chunk_index", 1).to_list(None)
    if [r["chunk_index"] for r in rows] != list(range(expected_chunks)):
        raise http(409, "conflict", "The upload has missing chunks; a file with gaps cannot be accepted as complete. Uploaded chunks are kept for resumption.")
    data = b"".join(decrypt(r["ciphertext"]) for r in rows)
    if len(data) != declared:
        raise http(409, "conflict", "Received bytes do not match the declared length. Uploaded chunks are kept for correction.")
    meta = {k: v for k, v in upload["metadata"].items() if k != "declaredBytes"}
    content_digest = hashlib.sha256(data).hexdigest()
    fin = upload.get("finalisation")  # exclusive, renewable-ownership state: {"state": "ingesting"|"committed", "digest", "started_at", "fence", "evidence_id"}
    if fin and fin["digest"] != content_digest:
        raise http(409, "conflict", "The chunks differ from the ones that were being finalised; a changed file cannot complete the same upload.")
    if not fin:
        fence = str(uuid.uuid4())
        claimed = await db.investigation_uploads.find_one_and_update({"owner_id": owner, "upload_id": upload_id, "finalisation": None},
                                                                     {"$set": {"finalisation": {"state": "ingesting", "digest": content_digest, "started_at": now_utc(), "fence": fence, "evidence_id": None}}})
        if claimed is None:  # a concurrent finaliser holds the claim; it (or a later retry) completes ingestion
            raise http(409, "conflict", "This upload is being finalised by another request; retry to obtain the result.")
    elif fin["state"] == "ingesting" and (now_utc() - repo.utc(fin["started_at"])).total_seconds() < 120:
        raise http(409, "conflict", "This upload is being finalised; retry shortly.")  # exclusivity window; after it the attempt is presumed dead and redone
    else:
        # Renewable-ownership takeover of a stale claim: the CAS matches the EXACT prior fence/started_at, so only one
        # concurrent retry wins a fresh fence. The superseded attempt's own commit below is always gated on ITS OWN
        # (now stale) fence and can never land after this — it discards its work instead of racing to finish.
        fence = str(uuid.uuid4())
        taken = await db.investigation_uploads.find_one_and_update(
            {"owner_id": owner, "upload_id": upload_id, "finalisation.state": "ingesting", "finalisation.fence": fin.get("fence"), "finalisation.started_at": fin["started_at"]},
            {"$set": {"finalisation.fence": fence, "finalisation.started_at": now_utc()}})
        if taken is None:
            current = await db.investigation_uploads.find_one({"owner_id": owner, "upload_id": upload_id}, {"_id": 0})
            if current and current.get("evidence_id"):
                row = await repo.get_evidence(owner, case_id, current["evidence_id"])
                return JSONResponse({"evidence": repo.evidence_view(row).wire(), "caseRevision": case["revision"], "replayed": True}, status_code=201, headers=NO_STORE)
            raise http(409, "conflict", "This upload is being finalised by another attempt; retry shortly.")
    # One immutable client item owns one deterministic evidence root. A committed root is authoritative even if the
    # upload projection was interrupted before it recorded evidence_id.
    root_id = upload.get("evidence_root_id") or str(uuid.uuid5(uuid.NAMESPACE_URL, f"apollo-evidence:{owner}:{case_id}:{meta['clientItemId']}"))
    partial = await db.investigation_evidence.find_one(
        {"owner_id": owner, "case_id": case_id, "evidence_id": root_id},
        {"_id": 0, "evidence_id": 1, "publication_state": 1, "ingestion_attempt_id": 1, "publication_owner": 1, "meta_ciphertext": 1},
    )
    if partial:
        if partial.get("publication_state") == "committed":
            published_meta = repo.dec_json(partial["meta_ciphertext"])
            if published_meta.get("contentDigest") != content_digest:
                raise http(409, "conflict", "A different file was already published under this immutable item identity.")
            committed = await db.investigation_uploads.find_one_and_update(
                {"owner_id": owner, "upload_id": upload_id, "finalisation.fence": fence},
                {"$set": {"finalisation.state": "committed", "finalisation.evidence_id": root_id, "evidence_id": root_id}})
            if committed is not None:
                await db.investigation_upload_chunks.delete_many({"owner_id": owner, "upload_id": upload_id})
            row = await repo.get_evidence(owner, case_id, root_id)
            return JSONResponse({"evidence": repo.evidence_view(row).wire(), "caseRevision": case["revision"], "replayed": True}, status_code=201, headers=NO_STORE)
        # A stale staging root is abandoned only by matching its exact attempt/owner. If it wins publication first,
        # abandonment matches nothing and the now-committed root is replayed on the next request—never deleted.
        abandoned = await repo.discard_incomplete_ingestion(
            owner, case_id, root_id, attempt_id=partial.get("ingestion_attempt_id"), publication_owner=partial.get("publication_owner")
        )
        if not abandoned:
            winner = await db.investigation_evidence.find_one(
                {"owner_id": owner, "case_id": case_id, "evidence_id": root_id}, {"_id": 0, "publication_state": 1, "meta_ciphertext": 1}
            )
            if winner and winner.get("publication_state") == "committed" and repo.dec_json(winner["meta_ciphertext"]).get("contentDigest") == content_digest:
                bound = await db.investigation_uploads.find_one_and_update(
                    {"owner_id": owner, "upload_id": upload_id, "finalisation.fence": fence},
                    {"$set": {"finalisation.state": "committed", "finalisation.evidence_id": root_id, "evidence_id": root_id}},
                )
                if bound is not None:
                    await db.investigation_upload_chunks.delete_many({"owner_id": owner, "upload_id": upload_id})
                row = await repo.get_evidence(owner, case_id, root_id)
                return JSONResponse({"evidence": repo.evidence_view(row).wire(), "caseRevision": case["revision"], "replayed": True}, status_code=201, headers=NO_STORE)
            raise http(409, "conflict", "The reserved evidence root is owned by another active ingestion attempt.")
    publication_owner = {"upload_id": upload_id, "fence": fence}
    try:
        item = await _with_lease_renewal(db.investigation_uploads, {"owner_id": owner, "upload_id": upload_id}, "finalisation.fence", fence, "finalisation.started_at",
                                         ev.ingest_file(owner, case, meta, data, evidence_root_id=root_id, ingestion_attempt_id=fence,
                                                        publication_owner=publication_owner, content_digest=content_digest))
    except LeaseLost:
        current = await db.investigation_uploads.find_one({"owner_id": owner, "upload_id": upload_id}, {"_id": 0})
        if current and current.get("evidence_id"):
            row = await repo.get_evidence(owner, case_id, current["evidence_id"])
            return JSONResponse({"evidence": repo.evidence_view(row).wire(), "caseRevision": case["revision"], "replayed": True}, status_code=201, headers=NO_STORE)
        raise http(409, "conflict", "This upload is being finalised by another attempt; retry to obtain the result.")
    # The root publication is authoritative. This upload projection is fenced, but a lost projection write must never
    # delete the already-published root; the next replay binds it by immutable digest.
    committed = await db.investigation_uploads.find_one_and_update(
        {"owner_id": owner, "upload_id": upload_id, "finalisation.fence": fence},
        {"$set": {"finalisation.state": "committed", "finalisation.evidence_id": item.id, "evidence_id": item.id}},
        return_document=ReturnDocument.AFTER)
    if committed is None:
        current = await db.investigation_uploads.find_one({"owner_id": owner, "upload_id": upload_id}, {"_id": 0})
        if current and current.get("evidence_id"):
            row = await repo.get_evidence(owner, case_id, current["evidence_id"])
            return JSONResponse({"evidence": repo.evidence_view(row).wire(), "caseRevision": case["revision"], "replayed": True}, status_code=201, headers=NO_STORE)
        row = await repo.get_evidence(owner, case_id, item.id)
        return JSONResponse({"evidence": repo.evidence_view(row).wire(), "caseRevision": case["revision"], "replayed": True}, status_code=201, headers=NO_STORE)
    # Upload state is released only after evidence is committed.
    await db.investigation_upload_chunks.delete_many({"owner_id": owner, "upload_id": upload_id})
    updated = await repo.cas(owner, case_id, {"revision": case["revision"]}, {"$set": {}})
    return JSONResponse({"evidence": item.wire(), "caseRevision": (updated or case)["revision"]}, status_code=201, headers=NO_STORE)


# ------------------------------------------------------------------ turns / jobs
async def _follow_up(owner: str, case: dict, body: SubmitTurn) -> Optional[dict]:
    """Every follow-up on a case that has been investigated is answered from the case's locked findings — no job, no
    AI call, no second investigation. This holds for an answer to Magnum DI's own question too, and when the follow-up
    brings something new (a link, an email, a number or fresh evidence): the case's one investigation is never reopened.

    None only when the case has had no investigation yet (no result, and its Magnum DI call unused): the turn is then the
    case's first investigation.
    """
    if case.get("active_job_id"):
        return None
    question = redact_investigation_secrets(body.message)
    answered_by = (case.get("routing") or {}).get("answeredBy")
    if case.get("response_ciphertext"):
        response = repo.dec_json(case["response_ciphertext"])
        answer = presenter.investigation_follow_up(response, await repo.sources(owner, case["case_id"]), question, answered_by)
    elif await repo.magnum_call_used(owner, case["case_id"]):
        # Magnum DI's one call didn't produce a result: the reason, and what TC Hawkeye established.
        answer = presenter.stopped_follow_up(await _failure_of(owner, case), await tc_flyby.established(owner, case["case_id"]))
    else:
        return None
    if body.evidence_ids and answer["intent"] != "recheck":
        answer = {**answer, "answer": (f"The new material was kept with this case, but {outcomes.investigator(answered_by)}'s investigation is finished, "
                                       "so it wasn't re-assessed. If it's a separate message or incident, check it on its own.\n\n" + answer["answer"])}
    return {"turnId": body.turn_id, "question": question, "answer": answer["answer"],
            "intent": answer["intent"], "limitation": answer["limitation"], "newItems": answer["newItems"], "answeredBy": "apollo"}


async def _failure_of(owner: str, case: dict) -> Optional[str]:
    job = await db.investigation_jobs.find_one({"owner_id": owner, "case_id": case["case_id"], "failure": {"$ne": None}}, {"_id": 0, "failure": 1},
                                               sort=[("created_at", -1)])
    return ((job or {}).get("failure") or {}).get("message")


@router.post("/investigations/{case_id}/turns", status_code=202)
async def submit_turn(case_id: str, body: SubmitTurn, request: Request, idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    owner = owner_of(request)
    case = await repo.get_case(owner, case_id, for_mutation=True)
    key = _key(idempotency_key)
    existing = await db.investigation_jobs.find_one({"owner_id": owner, "case_id": case_id, "idempotency_key_digest": repo.digest(f"{owner}:turn:{key}")}, {"_id": 0})
    if not existing:
        _revision_check(case, body.expected_revision)
        follow_up = await _follow_up(owner, case, body)
        if follow_up:
            return JSONResponse({"job": None, "followUp": follow_up, "caseRevision": case["revision"]}, status_code=200, headers=NO_STORE)
    job = await _submit_turn(owner, case, body, key)
    case = await repo.get_case(owner, case_id)
    return JSONResponse({"job": repo.job_view(job).wire(), "caseRevision": case["revision"]}, status_code=202, headers=NO_STORE)


@router.get("/investigations/{case_id}/turns")
async def list_turns(case_id: str, request: Request, cursor: Optional[str] = None):
    owner = owner_of(request)
    case = await repo.get_case(owner, case_id)
    turns = await repo.accepted_turns(owner, case)
    start = int(cursor or 0)
    return JSONResponse({"items": [t.wire() for t in turns[start:start + 50]], "nextCursor": str(start + 50) if len(turns) > start + 50 else None, "total": len(turns)}, headers=NO_STORE)


@router.get("/investigations/{case_id}/jobs/{job_id}")
async def get_job(case_id: str, job_id: str, request: Request):
    owner = owner_of(request)
    case = await repo.get_case(owner, case_id)
    job = await repo.get_job(owner, case_id, job_id)
    return JSONResponse({"job": repo.job_view(job).wire(), "caseRevision": case["revision"], "responseRevision": case.get("response_revision"),
                         "audioIds": job.get("audio_ids", [])}, headers=NO_STORE)


@router.get("/investigations/{case_id}/jobs/{job_id}/events")
async def job_events(case_id: str, job_id: str, request: Request, after: int = 0):
    owner = owner_of(request)
    await repo.get_case(owner, case_id)
    await repo.get_job(owner, case_id, job_id)

    async def stream():
        sequence = after
        idle = 0
        while idle < 600:
            events = await repo.events_after(owner, job_id, sequence)
            for event in events:
                sequence = event["sequence"]
                yield f"id: {sequence}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"
                if event["type"] in ("completed", "failed", "cancelled", "expired", "device_request"):
                    return
            job = await db.investigation_jobs.find_one({"owner_id": owner, "job_id": job_id}, {"_id": 0, "status": 1})
            if not events and job and job["status"] in ("complete", "partial", "waiting_user", "failed", "cancelled", "waiting_device"):
                return
            if await request.is_disconnected():
                return
            idle += 1
            yield ": keepalive\n\n" if idle % 20 == 0 else ""
            await asyncio.sleep(0.5)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={**NO_STORE, "X-Accel-Buffering": "no"})


@router.post("/investigations/{case_id}/jobs/{job_id}/resume", status_code=202)
async def resume_job(case_id: str, job_id: str, body: ExpectedRevision, request: Request, idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    owner = owner_of(request)
    case = await repo.get_case(owner, case_id, for_mutation=True)
    job = await repo.get_job(owner, case_id, job_id)
    _key(idempotency_key)
    if job["status"] in ACTIVE:
        return JSONResponse({"job": repo.job_view(job).wire(), "caseRevision": case["revision"]}, status_code=202, headers=NO_STORE)
    if job["status"] != "failed":
        raise http(409, "conflict", "Only a failed turn can be resumed; this turn already completed.")
    for evidence_id in repo.dec_json(job["payload_ciphertext"]).get("evidenceIds", []):
        await repo.get_evidence(owner, case_id, evidence_id)
    if case.get("active_job_id") and case["active_job_id"] != job_id:
        raise http(409, "conflict", "Another turn is active.")
    # One Magnum DI call per correlated case: once it was made, Resubmit can't make another.
    if await repo.magnum_call_used(owner, case_id):
        raise http(409, "conflict", "Magnum DI has already made this case's one call, so it can't be resubmitted. "
                                    "Its findings, and why it stopped, stay on the case.")
    deadline = min(repo.utc(case["expires_at"]), now_utc() + timedelta(seconds=policy()["workSeconds"]))
    resubmitted = RetryAttempt(attempt=len(job.get("retry_history") or []) + 1, kind="manual_retry",
                               failure_code=(job.get("failure") or {}).get("code"), failure_message="Resubmitted by the person",
                               timestamp=now_utc().isoformat(), outcome="retrying").wire()
    # A resubmission picks up the same investigation, with the same evidence, before its Magnum DI call was made.
    await db.investigation_jobs.update_one({"owner_id": owner, "job_id": job_id}, {"$set": {"status": "queued", "failure": None, "lease_until": None, "fence": None,
                                                                                            "deadline_at": deadline, "epoch": case["epoch"], "work_epoch": case.get("work_epoch", case["epoch"]), "retry_at": None,
                                                                                            "resubmit_at": None},
                                                                                   "$push": {"retry_history": resubmitted}})
    await repo.cas(owner, case_id, {"revision": case["revision"]}, {"$set": {"status": "queued", "active_job_id": job_id, "active_turn_id": job["turn_id"]}}, bump=False)
    jobs.launch(owner, case_id, job_id)
    return JSONResponse({"job": repo.job_view(await repo.get_job(owner, case_id, job_id)).wire(), "caseRevision": case["revision"]}, status_code=202, headers=NO_STORE)


@router.post("/investigations/{case_id}/jobs/{job_id}/cancel", status_code=202)
async def cancel_job(case_id: str, job_id: str, body: ExpectedRevision, request: Request):
    owner = owner_of(request)
    case = await repo.get_case(owner, case_id)
    job = await repo.get_job(owner, case_id, job_id)
    async def turn_was_accepted(current_case: dict) -> bool:
        return any(turn.turn_id == job["turn_id"] for turn in await repo.accepted_turns(owner, current_case))
    if job["status"] not in ACTIVE:
        already_cancelled = job["status"] == "cancelled"
        outcome = "cancelled" if already_cancelled else "completed" if job["status"] in ("complete", "completed") else "failed" if job["status"] == "failed" else "superseded"
        return JSONResponse({"status": job["status"], "outcome": outcome, "cleanupStatus": "complete" if already_cancelled else "not_required",
                             "cancelled": already_cancelled, "caseRevision": case["revision"], "responseRevision": case.get("response_revision")}, status_code=200, headers=NO_STORE)
    _revision_check(case, body.expected_revision)
    # The case control record is authoritative. Match the exact job and work epoch observed above so a completed job
    # followed by a newer turn can never have that newer turn cleared by this stale cancellation request.
    updated = await repo.cas(owner, case_id, {
        "revision": case["revision"], "active_job_id": job_id,
        "work_epoch": job.get("work_epoch", job["epoch"]),
    }, {"$set": {"work_epoch": uuid.uuid4().hex, "active_job_id": None, "active_turn_id": None, "lease_fence": None,
                  "status": "partial" if case.get("response_ciphertext") else "queued"}})
    if not updated:
        current_job = await repo.get_job(owner, case_id, job_id)
        current_case = await repo.get_case(owner, case_id)
        if current_job["status"] not in ACTIVE:
            outcome = "completed" if current_job["status"] in ("complete", "completed") else "failed" if current_job["status"] == "failed" else "cancelled" if current_job["status"] == "cancelled" else "superseded"
            return JSONResponse({"status": current_job["status"], "outcome": outcome, "cleanupStatus": "not_required", "cancelled": outcome == "cancelled",
                                 "caseRevision": current_case["revision"], "responseRevision": current_case.get("response_revision")}, status_code=200, headers=NO_STORE)
        accepted = await turn_was_accepted(current_case)
        outcome = "completed" if accepted else "superseded"
        return JSONResponse({"status": "complete" if accepted else current_job["status"], "outcome": outcome, "cleanupStatus": "not_required", "cancelled": False,
                             "caseRevision": current_case["revision"], "responseRevision": current_case.get("response_revision")}, status_code=200, headers=NO_STORE)
    cancelled = await db.investigation_jobs.find_one_and_update(
        {"owner_id": owner, "job_id": job_id, "work_epoch": job.get("work_epoch", job["epoch"]), "status": {"$in": list(ACTIVE)}},
        {"$set": {"status": "cancelled", "lease_until": None, "checkpoint_ciphertext": None}},
    )
    if not cancelled:
        current_job = await repo.get_job(owner, case_id, job_id)
        current_case = await repo.get_case(owner, case_id)
        outcome = "completed" if current_job["status"] in ("complete", "completed") else "failed" if current_job["status"] == "failed" else "superseded"
        return JSONResponse({"status": current_job["status"], "outcome": outcome, "cleanupStatus": "not_required", "cancelled": False,
                             "caseRevision": current_case["revision"], "responseRevision": current_case.get("response_revision")}, status_code=200, headers=NO_STORE)
    await repo.start_deletion_clock(owner, case_id)  # a cancelled check has finished: its 24 hours start now
    await repo.emit(owner, case_id, job_id, "cancelled", {"cleanupStatus": "complete"}, updated["revision"], repo.utc(case["expires_at"]))
    return JSONResponse({"status": "cancelled", "outcome": "cancelled", "cleanupStatus": "complete", "cancelled": True,
                         "caseRevision": updated["revision"], "responseRevision": updated.get("response_revision")}, status_code=202, headers=NO_STORE)


def _canonical_result(body: DeviceResult, requested: list[str]) -> DeviceResult:
    """Normalises a device result before hashing/storage: only requested fields, stable key order, no observed-at drift."""
    values = {k: body.values[k] for k in sorted(body.values) if not requested or k in requested}
    return body.model_copy(update={"values": values})


def _result_digest(body: DeviceResult) -> str:
    return repo.digest(json.dumps(body.wire(), sort_keys=True, separators=(",", ":")))


# ------------------------------------------------------------------ device results
@router.post("/investigations/{case_id}/device-results", status_code=202)
async def device_results(case_id: str, body: DeviceResult, request: Request):
    owner = owner_of(request)
    case = await repo.get_case(owner, case_id, for_mutation=True)
    pending = await db.investigation_device_requests.find_one({"owner_id": owner, "case_id": case_id, "request_id": body.request_id}, {"_id": 0})
    if not pending:
        raise http(409, "conflict", "No outstanding device request with that ID for this investigation.")
    if pending["request"]["capabilityId"] != body.capability_id:
        raise http(409, "conflict", "The result does not match the requested capability.")
    device = repo.device_profile(case) or {}
    if body.simulation and device.get("evidenceOrigin") == "native":
        raise http(409, "conflict", "A native device profile cannot submit simulated observations.")
    body = _canonical_result(body, pending["request"]["fields"])  # canonicalise BEFORE hashing, for first submission and replay alike
    digest = _result_digest(body)
    submission = pending.get("submission")  # recoverable record: {"state": claimed|stored|resumed, "digest", "result_ciphertext", "evidence_id"}
    if submission:
        if submission["digest"] != digest:
            raise http(409, "conflict", "A different result was already recorded for this device request.")
        if submission["state"] == "resumed":
            return JSONResponse({"accepted": True, "received": True, "consumed": True, "duplicate": True, "evidenceId": submission.get("evidence_id"), "jobId": pending["job_id"]}, status_code=202, headers=NO_STORE)
        # Identical retry of an interrupted submission: finish it (idempotent) instead of acknowledging without evidence.
        item_id = await _finish_device_submission(owner, case, pending)
        current = await db.investigation_device_requests.find_one({"owner_id": owner, "case_id": case_id, "request_id": body.request_id}, {"_id": 0, "submission.state": 1})
        consumed = (current or {}).get("submission", {}).get("state") == "resumed"
        return JSONResponse({"accepted": consumed, "received": True, "consumed": consumed, "duplicate": True, "evidenceId": item_id, "jobId": pending["job_id"]}, status_code=202, headers=NO_STORE)
    if repo.utc(datetime.fromisoformat(pending["request"]["expiresAt"])) <= now_utc():
        raise http(409, "conflict", "This device request expired before its result arrived. Higgins will ask again if the observation still matters.")
    job = await repo.get_job(owner, case_id, pending["job_id"])
    if job.get("status") in ("cancelled", "failed", "expired", "complete", "partial") or case.get("status") in ("cancelled", "expired"):
        raise http(409, "conflict", "This device request was superseded (the investigation was cancelled, finished or expired); its result cannot restart work.")
    # Atomic claim of (owner, case, request). The claim persists the canonical result itself, so a crash at ANY later point is
    # recoverable: an identical retry or the sweeper finishes ingestion and resumes the job; a changed retry gets 409.
    claimed = await db.investigation_device_requests.find_one_and_update(
        {"owner_id": owner, "case_id": case_id, "request_id": body.request_id, "submission": None},
        {"$set": {"submission": {"state": "claimed", "digest": digest, "result_ciphertext": repo.enc_json(body.wire()), "evidence_id": None, "claimed_at": now_utc(), "fence": str(uuid.uuid4())}}})
    if claimed is None:
        current = await db.investigation_device_requests.find_one({"owner_id": owner, "case_id": case_id, "request_id": body.request_id}, {"_id": 0})
        if not current or not current.get("submission") or current["submission"]["digest"] != digest:
            raise http(409, "conflict", "A different result was already recorded for this device request.")
        item_id = await _finish_device_submission(owner, case, current)
        refreshed = await db.investigation_device_requests.find_one({"owner_id": owner, "case_id": case_id, "request_id": body.request_id}, {"_id": 0, "submission.state": 1})
        consumed = (refreshed or {}).get("submission", {}).get("state") == "resumed"
        return JSONResponse({"accepted": consumed, "received": True, "consumed": consumed, "duplicate": True, "evidenceId": item_id, "jobId": pending["job_id"]}, status_code=202, headers=NO_STORE)
    pending = await db.investigation_device_requests.find_one({"owner_id": owner, "case_id": case_id, "request_id": body.request_id}, {"_id": 0})
    item_id = await _finish_device_submission(owner, case, pending)
    refreshed = await db.investigation_device_requests.find_one({"owner_id": owner, "case_id": case_id, "request_id": body.request_id}, {"_id": 0, "submission.state": 1})
    consumed = (refreshed or {}).get("submission", {}).get("state") == "resumed"
    return JSONResponse({"accepted": consumed, "received": True, "consumed": consumed, "evidenceId": item_id, "jobId": pending["job_id"]}, status_code=202, headers=NO_STORE)


DEVICE_SUBMISSION_STALE_SECONDS = 120


async def _claim_submission_stage(owner: str, case_id: str, request_id: str, from_state: str, busy_state: str) -> Optional[str]:
    """Fenced exclusive claim for one in-flight stage of device-submission recovery (renewable ownership): wins
    immediately when `submission.state == from_state` (normal progression, or a fresh sweeper/retry pass on an
    untouched claim), or by taking over a `busy_state` claim stuck past `DEVICE_SUBMISSION_STALE_SECONDS` — matched
    by CAS on the EXACT prior fence/timestamp, so the timed-out attempt's own completion write below (always gated
    on ITS OWN fence) can never land after this. Returns a fresh fence on success, else None (another live attempt
    currently owns this stage; the caller backs off instead of racing it)."""
    fence, now = uuid.uuid4().hex, now_utc()
    won = await db.investigation_device_requests.find_one_and_update(
        {"owner_id": owner, "case_id": case_id, "request_id": request_id, "submission.state": from_state},
        {"$set": {"submission.state": busy_state, "submission.fence": fence, "submission.stage_started_at": now}})
    if won:
        return fence
    current = await db.investigation_device_requests.find_one({"owner_id": owner, "case_id": case_id, "request_id": request_id}, {"_id": 0, "submission": 1})
    sub = (current or {}).get("submission") or {}
    if sub.get("state") == busy_state and sub.get("stage_started_at") and (now - repo.utc(sub["stage_started_at"])).total_seconds() >= DEVICE_SUBMISSION_STALE_SECONDS:
        taken = await db.investigation_device_requests.find_one_and_update(
            {"owner_id": owner, "case_id": case_id, "request_id": request_id, "submission.state": busy_state,
             "submission.fence": sub.get("fence"), "submission.stage_started_at": sub["stage_started_at"]},
            {"$set": {"submission.fence": fence, "submission.stage_started_at": now}})
        if taken:
            return fence
    return None


async def _finish_device_submission(owner: str, case: dict, pending: dict) -> Optional[str]:
    """Idempotently advances a claimed device submission: claimed → stored (evidence durable) → resumed (job queued
    + launched), each transition gated by a renewable, fenced claim (`_claim_submission_stage`) so the request path,
    an identical retry, and the recovery sweeper can run concurrently without a superseded attempt's write landing
    after a takeover, and without two live attempts both ingesting or both resuming the same job."""
    case_id, request_id = pending["case_id"], pending["request_id"]
    sub = pending["submission"]
    result = repo.dec_json(sub["result_ciphertext"])
    if sub["state"] in ("claimed", "storing"):
        # `from_state="claimed"` covers the untouched-claim path; a doc already sitting in "storing" (e.g. the
        # sweeper picking up a crashed attempt) falls through to the staleness-takeover branch of the SAME call.
        fence = await _claim_submission_stage(owner, case_id, request_id, "claimed", "storing")
        if not fence:
            refreshed = (await db.investigation_device_requests.find_one({"owner_id": owner, "case_id": case_id, "request_id": request_id}, {"_id": 0, "submission": 1}) or {}).get("submission") or {}
            return refreshed.get("evidence_id") if refreshed.get("state") in ("stored", "resuming", "resumed") else None
        selector = {"owner_id": owner, "case_id": case_id, "request_id": request_id}
        existing = await db.investigation_evidence.find_one({"owner_id": owner, "case_id": case_id, "client_item_id": f"observation-{request_id}"}, {"_id": 0, "evidence_id": 1})
        if existing and not await db.investigation_content_chunks.find_one({"owner_id": owner, "case_id": case_id, "evidence_id": existing["evidence_id"]}, {"_id": 0, "chunk_index": 1}):
            # A metadata row exists but its content never finished storing (a crash between the metadata insert and
            # the byte write) — that is NOT completed ingestion. Discard it and re-ingest fresh from the submission
            # payload this claim already durably retained (`result`), never leaving a resumed investigation pointed
            # at evidence with no actual content.
            await repo.discard_incomplete_ingestion(owner, case_id, existing["evidence_id"])
            existing = None
        try:
            item_id = existing["evidence_id"] if existing else (await _with_lease_renewal(
                db.investigation_device_requests, selector, "submission.fence", fence, "submission.stage_started_at",
                ev.ingest_observation(owner, case, f"observation-{request_id}", result))).id
        except LeaseLost:
            refreshed = (await db.investigation_device_requests.find_one(selector, {"_id": 0, "submission": 1}) or {}).get("submission") or {}
            return refreshed.get("evidence_id") if refreshed.get("state") in ("stored", "resuming", "resumed") else None
        committed = await db.investigation_device_requests.find_one_and_update(
            {**selector, "submission.fence": fence},
            {"$set": {"submission.state": "stored", "submission.evidence_id": item_id, "evidence_id": item_id}})
        if not committed:  # fenced out mid-ingestion: our write never lands; defer entirely to the current owner
            refreshed = (await db.investigation_device_requests.find_one(selector, {"_id": 0, "submission": 1}) or {}).get("submission") or {}
            sub = refreshed or sub
        else:
            sub = {**sub, "state": "stored", "evidence_id": item_id}
    if sub["state"] in ("stored", "resuming"):
        fence = await _claim_submission_stage(owner, case_id, request_id, "stored", "resuming")
        if not fence:
            refreshed = (await db.investigation_device_requests.find_one({"owner_id": owner, "case_id": case_id, "request_id": request_id}, {"_id": 0, "submission": 1}) or {}).get("submission") or {}
            return refreshed.get("evidence_id", sub.get("evidence_id"))
        selector = {"owner_id": owner, "case_id": case_id, "request_id": request_id}

        async def _resume() -> bool:
            for _ in range(12):
                job = await repo.get_job(owner, case_id, pending["job_id"])
                if request_id in job.get("consumed_device_request_ids", []):
                    return True
                if job.get("status") not in ("waiting_device", "queued", "investigating", "retry_wait"):
                    return False
                checkpoint = repo.dec_json(job["checkpoint_ciphertext"]) if job.get("checkpoint_ciphertext") else {"contents": [], "rounds": 0}
                if not any(r.get("evidenceId") == sub["evidence_id"] for r in checkpoint.get("deviceResults", [])):
                    checkpoint.setdefault("deviceResults", []).append({**result, "evidenceId": sub["evidence_id"]})
                revision = int(job.get("checkpoint_revision", 0))
                revision_condition = ({"$or": [{"checkpoint_revision": 0}, {"checkpoint_revision": {"$exists": False}}]}
                                      if revision == 0 else {"checkpoint_revision": revision})
                # Different requests serialize through checkpoint_revision. A loser reloads and merges its still-
                # unconsumed result, so consumed IDs and encrypted checkpoint content can never diverge.
                resumed_job = await db.investigation_jobs.find_one_and_update(
                    {"owner_id": owner, "job_id": job["job_id"],
                     "status": {"$in": ["waiting_device", "queued", "retry_wait"]},
                     "consumed_device_request_ids": {"$ne": request_id},
                     "$and": [revision_condition, {"$or": [{"lease_until": None}, {"lease_until": {"$lte": now_utc()}}]}]},
                    {"$set": {"checkpoint_ciphertext": repo.enc_json(checkpoint), "status": "queued", "lease_until": None},
                     "$addToSet": {"consumed_device_request_ids": request_id}, "$inc": {"checkpoint_revision": 1}},
                    return_document=ReturnDocument.AFTER,
                )
                if resumed_job is None:
                    continue
                await repo.cas(owner, case_id, {
                    "work_epoch": job.get("work_epoch", job["epoch"]), "active_job_id": job["job_id"],
                    "status": {"$in": ["waiting_device", "queued"]}, "pending_device_request_ids": request_id,
                }, {"$set": {"status": "queued"}, "$pull": {"pending_device_request_ids": request_id}})
                return True
            return request_id in (await repo.get_job(owner, case_id, pending["job_id"])).get("consumed_device_request_ids", [])
        # No multi-document transactions here (standalone MongoDB): the job/case writes above are protected instead by
        # holding the SAME renewed fence for their whole duration — no other attempt can also be in "resuming" while
        # this one is alive and heartbeating — AND each write is itself conditioned on the job's/case's own state, so
        # a write that arrives after the fence is lost (heartbeat cancelled work promptly, but a write already in
        # flight could still land) still cannot corrupt a state it no longer matches.
        try:
            consumed = await _with_lease_renewal(db.investigation_device_requests, selector, "submission.fence", fence, "submission.stage_started_at", _resume())
        except LeaseLost:
            refreshed = (await db.investigation_device_requests.find_one(selector, {"_id": 0, "submission": 1}) or {}).get("submission") or {}
            return refreshed.get("evidence_id", sub.get("evidence_id"))
        committed = await db.investigation_device_requests.find_one_and_update(
            {**selector, "submission.fence": fence},
            {"$set": ({"submission.state": "resumed", "fulfilled": True, "result_digest": sub["digest"], "consumed_at": now_utc()}
                      if consumed else {"submission.state": "stored", "submission.deferred_at": now_utc()})})
        if committed and consumed:
            # Wake only after the inbox projection says fulfilled. If the process dies here, the queued job is found
            # by recovery; if it dies before here, inbox recovery finishes the acknowledgement and then wakes it.
            jobs.launch(owner, case_id, pending["job_id"])
        if not committed:  # fenced out: another attempt owns the outcome; do not claim credit for the resume ourselves
            refreshed = (await db.investigation_device_requests.find_one({"owner_id": owner, "case_id": case_id, "request_id": request_id}, {"_id": 0, "submission": 1}) or {}).get("submission") or {}
            sub = refreshed or sub
    return sub.get("evidence_id")


# Settings destinations the client may advertise (mirrors frontend/src/settings/guidance.ts keywords). The plan binds to the
# most specific destination the DEVICE advertised for this target; a generic app-settings page is the last resort, never a default
# for unrelated targets.
SETTINGS_DESCRIPTOR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "open_settings.notifications": ("notification", "alert"),
    "open_settings.vpn": ("vpn", "dns filter", "site gate"),
    "open_settings.accessibility": ("accessibility",),
    "open_settings.notification_access": ("notification access", "notification listener", "text gate"),
    "open_settings.security": ("security", "lock screen", "screen lock", "play protect"),
    "open_settings.unknown_sources": ("unknown source", "install unknown", "sideload"),
    "open_settings.overlay": ("overlay", "display over", "draw over"),
    "open_settings.developer": ("developer", "usb debugging"),
    "open_settings.apps": ("uninstall", "installed app", "app list", "app info"),
    "open_settings.safari_extensions": ("safari", "content blocker", "extension", "site gate"),
}


def _settings_descriptor_for(target: str, advertised: list[str]) -> Optional[str]:
    """Picks the MOST SPECIFIC advertised destination for `target` — the longest matching keyword phrase wins,
    never simple declaration order, so a broad word like "notification" can't shadow a more specific phrase like
    "notification access" that also appears in the same target text."""
    t = target.lower()
    best: Optional[tuple[int, str]] = None
    for descriptor, keywords in SETTINGS_DESCRIPTOR_KEYWORDS.items():
        if descriptor not in advertised:
            continue
        match_len = max((len(k) for k in keywords if k in t), default=0)
        if match_len and (best is None or match_len > best[0]):
            best = (match_len, descriptor)
    if best:
        return best[1]
    return "open_settings.app" if "open_settings.app" in advertised else None


# ------------------------------------------------------------------ settings plans
@router.post("/investigations/{case_id}/settings-plan")
async def settings_plan(case_id: str, body: SettingsPlanRequest, request: Request):
    owner = owner_of(request)
    case = await repo.get_case(owner, case_id)
    _revision_check(case, body.expected_revision)
    # No research call: the steps are Magnum DI's own action from the investigation's one Gemini call
    # (the target text). The plan only binds that action to an observable expectation for the recheck.
    capability = body.capability_id if body.capability_id in body.device.capability_ids else None
    settings_capability = _settings_descriptor_for(body.target, body.device.capability_ids)
    mode = "permission_request" if capability and capability.startswith("permission.") else ("settings_link" if settings_capability else "instructions")
    steps = [line.strip("-• ").strip() for line in re.split(r"(?<=[.!?])\s+", body.target) if line.strip()]
    plan = SettingsPlan(id=str(uuid.uuid4()), case_id=case_id, target=body.target, device=body.device, match="unresolved", mode=mode, instructions=steps,
                        source_ids=[], execution_descriptor_id=capability or settings_capability,
                        expected_observation=ExpectedObservation(capability_id=capability, field=body.expected_field, expected_value=body.expected_value) if capability and body.expected_value is not None else None)
    await db.investigation_settings_plans.insert_one({"owner_id": owner, "case_id": case_id, "plan_id": plan.id, "plan_ciphertext": repo.enc_json(plan.wire()), "created_at": now_utc(),
                                                      "expires_at": repo.utc(case["expires_at"])})
    return JSONResponse({"plan": plan.wire(), "researchNote": None}, headers=NO_STORE)


@router.post("/investigations/{case_id}/settings-plan/{plan_id}/recheck")
async def recheck(case_id: str, plan_id: str, body: RecheckRequest, request: Request):
    owner = owner_of(request)
    await repo.get_case(owner, case_id)
    row = await db.investigation_settings_plans.find_one({"owner_id": owner, "case_id": case_id, "plan_id": plan_id}, {"_id": 0})
    if not row:
        raise http(404, "not_found", "Unknown settings plan.")
    plan = SettingsPlan.model_validate(repo.dec_json(row["plan_ciphertext"]))
    if not plan.expected_observation:
        return JSONResponse(RecheckResult(plan_id=plan_id, checked_at=now_utc(), outcome="cannot_observe", evidence_ids=[],
                                          explanation="Apollo cannot observe this setting on this device; only you can confirm it. Your confirmation is recorded as user-reported, not observed.").wire(), headers=NO_STORE)
    outcome, explanation, used = "cannot_observe", "No fresh observation of the target capability was supplied.", []
    for evidence_id in body.device_result_ids:
        evidence = await repo.get_evidence(owner, case_id, evidence_id)
        result = (await repo.evidence_meta(evidence)).get("deviceResult") or {}
        if result.get("capabilityId") != plan.expected_observation.capability_id:
            continue
        used.append(evidence_id)
        if repo.utc(evidence["collected_at"]) <= repo.utc(row["created_at"]) or (evidence.get("observed_at") and repo.utc(evidence["observed_at"]) <= repo.utc(row["created_at"])):
            outcome, explanation = "cannot_observe", "The only matching observation predates the plan; a fresh observation taken after the change is required."
            continue
        if evidence.get("simulation") and (repo.device_profile(await repo.get_case(owner, case_id)) or {}).get("evidenceOrigin") == "native":
            continue  # a preview fixture never becomes native proof
        if result.get("status") != "observed":
            outcome, explanation = "cannot_observe", f"The device reported '{result.get('status')}' for this capability; the setting could not be read."
        elif result.get("values", {}).get(plan.expected_observation.field) == plan.expected_observation.expected_value:
            outcome, explanation = "correct", "A fresh observation shows the setting now matches the expected value."
        else:
            outcome, explanation = "not_yet_correct", "A fresh observation shows the setting is still not at the expected value. Reopen Settings and check the exact item named in the instructions."
    return JSONResponse(RecheckResult(plan_id=plan_id, checked_at=now_utc(), outcome=outcome, evidence_ids=used, explanation=explanation).wire(), headers=NO_STORE)


@router.post("/investigations/{case_id}/settings-plan/{plan_id}/confirm")
async def confirm_settings_plan(case_id: str, plan_id: str, request: Request, confirmed: bool = Body(embed=True)):
    owner = owner_of(request)
    case = await repo.get_case(owner, case_id)
    row = await db.investigation_settings_plans.find_one({"owner_id": owner, "case_id": case_id, "plan_id": plan_id}, {"_id": 0})
    if not row:
        raise http(404, "not_found", "Unknown settings plan.")
    plan = SettingsPlan.model_validate(repo.dec_json(row["plan_ciphertext"]))
    item = await ev.ingest_text(owner, case, f"settings-confirmation-{plan_id}",
                                f"The user reported that they {'completed and checked' if confirmed else 'could not complete'} the guided setting: {plan.target}.",
                                origin="user_submission", label="user-reported settings confirmation",
                                coverage=ev.Coverage(status="examined", unit="items", total=1, examined=1))
    checked_at = now_utc()
    await db.investigation_settings_plans.update_one({"owner_id": owner, "case_id": case_id, "plan_id": plan_id},
                                                       {"$set": {"user_confirmed": confirmed, "user_confirmed_at": checked_at, "user_confirmation_evidence_id": item.id}})
    return JSONResponse({"planId": plan_id, "confirmed": confirmed, "checkedAt": checked_at.isoformat(), "evidenceId": item.id,
                         "verification": "user_reported", "explanation": "Recorded as your report; Apollo did not independently observe this setting."}, headers=NO_STORE)


# ------------------------------------------------------------------ device commit confirmation
@router.get("/investigations/{case_id}/pickup")
async def device_pickup_copy(case_id: str, request: Request):
    """The copy the server keeps for this phone until the phone confirms it saved its own (services/device_pickup.py).
    Served whatever the case's working window or 24-hour clock says. `held: false, working: true`: still being checked."""
    owner = owner_of(request)
    case = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id},
                                                 {"_id": 0, "deleted": 1, "status": 1, "active_job_id": 1})
    if not case:
        raise http(404, "not_found", "No investigation with that reference belongs to this device.")
    held = await device_pickup.get(owner, case_id)
    if held is None and not case.get("deleted") and device_pickup.finished(case) and await device_pickup.hold(owner, case_id):
        held = await device_pickup.get(owner, case_id)  # it finished moments ago: keep the phone's copy now
    if held is None:
        working = not case.get("deleted") and case.get("status") not in (*device_pickup.FINISHED, "expired", "deleted")
        return JSONResponse({"caseId": case_id, "held": False, "working": working}, headers=NO_STORE)
    return JSONResponse({"caseId": case_id, "held": True, **held}, headers=NO_STORE)


async def _saved_report(request: Request) -> Optional[dict]:
    """What the phone says it saved and checked: {"saved": {"text", "link", "result": bool, "headers": [labels]}}."""
    try:
        body = await request.json()
    except ValueError:
        return None
    saved = body.get("saved") if isinstance(body, dict) else None
    if saved is None:
        return None
    if not isinstance(saved, dict) or set(saved) - {"text", "link", "result", "headers"} \
            or any(not isinstance(saved.get(k, False), bool) for k in ("text", "link", "result")) \
            or not isinstance(saved.get("headers", []), list) or len(saved.get("headers", [])) > 20 \
            or any(not isinstance(h, str) or len(h) > 40 for h in saved.get("headers", [])):
        raise http(422, "invalid_input", "saved must say which parts the phone saved: text, link, result and header labels.")
    return saved


@router.post("/investigations/{case_id}/confirm-commit", status_code=200)
async def confirm_commit(case_id: str, request: Request):
    """Device confirms it has saved and checked its own complete copy of the investigation (`saved` says what it holds).
    Until then the server keeps the phone's copy, however long that takes. The server then purges all associated
    working data for this case and says when (`removedAt`), for the result's note."""
    owner = owner_of(request)
    saved = await _saved_report(request)
    held = await device_pickup.get(owner, case_id)
    if held is not None and saved is not None:
        gaps = device_pickup.missing(held, saved)
        if gaps:
            raise http(409, "conflict", f"This phone hasn't saved {', '.join(gaps)} yet, so ApolloSG keeps its copy until it has.", missing=gaps)
    case = await db.investigation_cases.find_one(
        {"owner_id": owner, "case_id": case_id, "deleted": {"$ne": True}},
        {"_id": 0, "owner_id": 1, "case_id": 1, "response_ciphertext": 1, "status": 1, "cleanup_status": 1, "active_job_id": 1})
    if not case:
        # Already purged or never existed — idempotent success. A purged case's record says when it was removed.
        await device_pickup.confirmed(owner, case_id)
        gone = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id, "deleted": True, "cleanup_status": "complete"},
                                                     {"_id": 0, "updated_at": 1})
        removed_at = repo.utc(gone["updated_at"]).isoformat() if gone and gone.get("updated_at") else None
        return JSONResponse({"purged": True, "status": "already_clean", "removedAt": removed_at}, headers=NO_STORE)
    # Only purge a finished investigation: one with a completed response, or a finished check whose copy was kept.
    if not case.get("response_ciphertext") and held is None:
        raise http(409, "conflict", "Cannot confirm commit for an investigation that has no completed response.")
    # The result reaches Threats and history first: once purged, the server can no longer project it.
    await project_case_now(owner, case_id)
    # Purge: revoke the case (marks deleted, rotates epoch) then run cleanup
    await repo.revoke(owner, case_id, "expired")
    cleanup_status = await repo.run_cleanup(owner, case_id)
    await device_pickup.confirmed(owner, case_id)
    removed_at = now_utc().isoformat() if cleanup_status == "complete" else None  # a failed clean-up is retried; no time is claimed
    return JSONResponse({"purged": True, "status": cleanup_status, "removedAt": removed_at}, headers=NO_STORE)
