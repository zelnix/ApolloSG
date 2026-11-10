"""Investigation coordinator: Higgins Triage → TC Hawkeye → Magnum DI.

On the first turn of a case, Higgins Triage decides what needs checking and TC Hawkeye runs those checks the
cheapest reliable way (official sources → Apollo KB → one targeted web search call). When TC Hawkeye
reliably settles the case, its result is committed and Magnum DI is not called at all.

Otherwise Magnum DI makes its call with the existing configured model. The request contains exactly three
things:
  1. the person's question, once;
  2. the case evidence Magnum DI needs — the submitted material itself plus TC Hawkeye's brief of what is
     still unresolved — each item labelled with its id and kind (raw lookups TC Hawkeye already settled are not
     resent);
  3. the required response shape (`response_schema.py`), which the provider adapter turns into its own
     structured-output schema.
There is no system prompt. Web search is attached only when a specific external fact is still missing.

The model is the one selected in ApolloSG Settings → AI Provider & Model (services/higgins/ai_settings.py),
pinned on the job when the investigation starts. The call goes through the single AI gateway (provider.generate),
never a provider SDK. TC Hawkeye makes no AI call.

ONE MAGNUM DI CALL PER CORRELATED CASE, AT MOST. There are no tool rounds, no nested research calls, no model
escalation, no Pro fallback, no second call to present the answer and no retry: Higgins shows what this one call
returned, or why it failed. The call is claimed atomically for the case (repository.claim_magnum_call) before anything
is sent, so a follow-up, retry, Resubmit, new job, recovered job or restart can never make a second one. Cases TC Hawkeye
settles use none. Follow-up questions are answered from the case's locked findings and ApolloSG's approved knowledge
(routers/investigations._follow_up), never by another investigation.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from core.db import db, now_utc
from services import device_stats
from services.higgins import case_evidence
from services.higgins import slm_advisory
from services.higgins import evidence as ev
from services.higgins import explain, history, outcomes
from services.higgins import ai_settings
from services.higgins import provider
from services.higgins.ai_request import Message, Part
from services.higgins import repository as repo
from services.higgins import tc_flyby
from services.higgins.contracts import Coverage, HigginsResponse, ProviderResult, TurnCommit, Usage
from services.higgins.response_schema import response_schema
from services.higgins.tools import grounding_sources
from services.higgins.validation import validate

log = logging.getLogger("apollo.coordinator")

# Apollo's pre-gathered specialist intelligence (RDAP, Safe Browsing, IPQualityScore, HIBP) is
# evidence collected for this case. It is registered as evidence, verbatim, so it can be cited.
TRIAGE_EVIDENCE_ITEM_ID = tc_flyby.PREGATHERED_ITEM_ID

# Magnum DI's one AI call for the whole correlated case. No retry.
MAX_MAGNUM_CALLS = 1



async def _slm_stage(owner: str, case: dict, job: dict, role: str) -> None:
    """Inspect any accepted local SLM advice at this stage; metadata only.

    Model hypotheses never become facts, findings, evidence, scores, source
    records or inputs to Magnum DI. Native SLM failure never interrupts work.
    """
    if not slm_advisory.enabled():
        return
    try:
        # Issue a stage-specific request on the already-authenticated case's
        # existing event stream. Never wait for a phone or a local model.
        from routers.slm_handoff import issue_stage_request
        issued = await issue_stage_request(owner, case["case_id"], job["job_id"],
                                           case["revision"], role)
        if issued:
            await repo.emit(owner, case["case_id"], job["job_id"],
                            "slm_advisory_request", issued,
                            case["revision"], repo.utc(case["expires_at"]))
        advice = await slm_advisory.accepted_for_stage(owner, case, job, role)
        if not advice:
            return
        counts = {key: len(advice.get(key, [])) for key in
                  ("observations", "contradictions", "alternativeExplanations", "verificationSuggestions")}
        await db.investigation_cases.update_one(
            {"owner_id": owner, "case_id": case["case_id"],
             "active_job_id": job["job_id"], "epoch": case.get("epoch"),
             "revision": case.get("revision"), "status": {"$in": ["queued", "investigating"]}},
            {"$set": {f"routing.slmAdvisory.{role}": {
                "status": "accepted_for_review", "counts": counts,
                "advisoryOnly": True, "at": now_utc(),
            }}},
        )
    except Exception:
        log.warning("slm_advisory_unavailable role=%s", role)


async def _await_case_finding(owner: str, case: dict, job: dict, progress) -> dict | None:
    """One bounded wait for an authenticated native SLM Finding; never invent a result."""
    if not slm_advisory.enabled():
        return None
    import asyncio
    from routers.slm_handoff import issue_stage_request

    try:
        issued = await issue_stage_request(owner, case["case_id"], job["job_id"],
                                           case["revision"], "case_finding")
        if not issued:
            return None
        await repo.emit(owner, case["case_id"], job["job_id"],
                        "slm_advisory_request", issued, case["revision"],
                        repo.utc(case["expires_at"]))
        await progress("assess", "The on-device model is reviewing the investigation.")
        for _ in range(30):
            advice = await slm_advisory.accepted_for_stage(owner, case, job, "case_finding")
            if advice and advice.get("caseFinding"):
                return advice
            await asyncio.sleep(0.5)
    except Exception:
        log.warning("slm_case_finding_unavailable case=%s", case["case_id"], exc_info=True)
    return None


async def _commit_slm_finding(owner: str, case: dict, job: dict, payload: dict,
                              advice: dict, capability_ids: set[str]) -> Optional[Outcome]:
    """Retain cited on-device Findings through the existing case repository."""
    finding = advice["caseFinding"]
    rows = await repo.list_evidence(owner, case["case_id"])
    evidence_ids = {row["evidence_id"] for row in rows}
    reasons = finding.get("reasons") or []
    if not reasons or any(not r.get("evidenceIds") or
                          not set(r["evidenceIds"]).issubset(evidence_ids) for r in reasons):
        return None
    outcome = finding["outcome"]
    concerns = outcome in ("scam", "likely_scam")
    advice_text = finding.get("advice")
    response_data = {
        "overview": finding["explanation"],
        "explanationMarkdown": finding["explanation"] + "\n\n" +
            "\n".join("- " + r["text"] for r in reasons),
        "assessment": outcomes.ASSESSMENT[outcome],
        "outcome": outcome,
        "attention": "review" if concerns else "none",
        "findings": [
            {"text": reason["text"], "basis": "inference", "confidence": "medium",
             "evidenceIds": reason["evidenceIds"], "sourceIds": [],
             "supersedesFindingIds": []}
            for reason in reasons
        ],
        "uncertainties": [finding["uncertainty"]] if finding.get("uncertainty") else [],
        "scope": "Submitted evidence and TC Hawkeye investigation available to the on-device model",
        "sourceIds": [], "remainingEvidenceIds": [],
        "actions": ([{"kind": "instruction", "label": "What to do",
                     "instruction": advice_text, "capabilityId": None, "sourceIds": [],
                     "desiredField": None, "desiredValue": None}] if advice_text else []),
        "recommendedActionIndex": 0 if advice_text else None,
        "question": None, "completion": "complete",
    }
    response, errors = validate(response_data, revision=(case.get("response_revision") or 0) + 1,
                                evidence_ids=evidence_ids,
                                source_ids={x["id"] for x in await repo.sources(owner, case["case_id"])},
                                capability_ids=capability_ids, pending_question=None,
                                provider_complete=True, material_gaps=_material_gaps(rows))
    if response is None:
        log.warning("slm_case_finding_invalid case=%s errors=%s", case["case_id"], errors[:3])
        return None
    provider_result = ProviderResult(provider="apollo", model=advice["modelId"],
                                     api_version="", finish_reason="STOP",
                                     provider_complete=True, usage=Usage(),
                                     source_ids=[], simulated=False, answered_by="higgins_luddish")
    return await _commit(owner, case, job, payload, response, provider_result,
                         evidence_ids, set())


async def _register_triage_evidence(owner: str, case: dict) -> None:
    """Store the raw triage provider results as a case evidence item, once."""
    pre_gathered = case.get("triage_provider_evidence")
    # An empty envelope (no provider consulted, no lookups) is bookkeeping, not intelligence.
    if not pre_gathered or not ev.has_intelligence(pre_gathered):
        return
    existing = await repo.list_evidence(owner, case["case_id"])
    if any(row.get("client_item_id") == TRIAGE_EVIDENCE_ITEM_ID for row in existing):
        return
    text = json.dumps(pre_gathered, ensure_ascii=False, sort_keys=True, default=str)
    await ev.ingest_text(
        owner, case, TRIAGE_EVIDENCE_ITEM_ID, text,
        kind="observation", origin="apollo_inference",
        label="Higgins triage specialist intelligence",
        meta={"source": "apollo_triage"},
        coverage=Coverage(status="examined", unit="items", total=1, examined=1),
    )


def _json_object(text: str) -> Optional[dict]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except ValueError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                value = json.loads(match.group(0))
                return value if isinstance(value, dict) else None
            except ValueError:
                return None
    return None


def _material_gaps(rows: list[dict]) -> set[str]:
    return {row["evidence_id"] for row in rows if row["availability"] == "available" and row["origin"] != "apollo_inference"
            and (row["coverage"].get("materialGap") or row["coverage"].get("status") in ("not_started", "partial"))
            and row["kind"] in ("text", "document", "url", "image", "source_snapshot")}


class Outcome:
    def __init__(self, kind: str, *, commit: Optional[TurnCommit] = None, request: Optional[dict] = None, case: Optional[dict] = None,
                 errors: Optional[list[str]] = None, provider_text: Optional[str] = None, finish_reason: Optional[str] = None,
                 model: Optional[str] = None, evidence_words: Optional[int] = None):
        self.kind, self.commit, self.request, self.case, self.errors = kind, commit, request, case, errors or []
        # Set only for "evidence_too_large": the real word count, so Higgins can state it.
        self.evidence_words = evidence_words
        # Real provider output kept verbatim for the technical details — never reshaped into a result.
        self.provider_text, self.finish_reason, self.model = provider_text, finish_reason, model


async def _plain_english(owner: str, case: dict, response: HigginsResponse, answered_by: str) -> tuple[HigginsResponse, Optional[dict]]:
    """Higgins' plain English for the validated result, after its Fidelity Check (services/higgins/explain). It sits
    beside the result and changes nothing in it. A renderer error never fails the investigation: the person then sees
    Apollo's own wording."""
    by = outcomes.investigator(answered_by)
    try:
        doc = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case["case_id"]}, {"_id": 0, "routing": 1, "gates": 1}) or {}
        plain, briefing = explain.explain_case(response, answered_by=answered_by, routing=doc.get("routing") or {},
                                               sources=await repo.sources(owner, case["case_id"]), gates=doc.get("gates") or [])
    except Exception as exc:  # noqa: BLE001 — presentation only; never logs case content
        log.warning("plain_english_renderer_error case=%s error=%s", case["case_id"], type(exc).__name__)
        return response, explain.renderer_error(by=by, revision=response.revision)
    return (response.model_copy(update={"plain_english": plain, "briefing": briefing}),
            explain.summary(plain, by=by, revision=response.revision, briefing=briefing))


async def _with_history(owner: str, case: dict, response: HigginsResponse) -> tuple[HigginsResponse, dict]:
    """The validated result with its related history beside it (services/higgins/history.py): history that agrees with
    a concern raises the confidence of the findings about the same subject; nothing else in the result changes. A failure
    leaves the result exactly as validated."""
    try:
        stored = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case["case_id"]}, {"_id": 0, "tc_flyby_ciphertext": 1}) or {}
        record = repo.dec_json(stored["tc_flyby_ciphertext"]) if stored.get("tc_flyby_ciphertext") else {}
        return history.weigh(response, record.get("history") or []), record
    except Exception:  # noqa: BLE001 — history is context; it never fails an investigation
        log.warning("history_weigh_failed case=%s", case["case_id"], exc_info=True)
        return response, {}


def _with_evidence(case: dict, response: HigginsResponse, record: dict, provider_result: ProviderResult) -> HigginsResponse:
    """The result with its Evidence record (services/higgins/case_evidence.py): each fact once, with who found it first
    and who established it too. A failure leaves the Evidence record unrecorded (None) — never reconstructed later."""
    try:
        facts = case_evidence.build(response, record, answered_by=provider_result.answered_by,
                                    simulated=bool(provider_result.simulated or (record.get("search") or {}).get("simulated")))
    except Exception:  # noqa: BLE001 — the Evidence record never fails an investigation
        log.warning("case_evidence_failed case=%s", case["case_id"], exc_info=True)
        return response
    return response.model_copy(update={"evidence": facts})


async def _commit(owner: str, case: dict, job: dict, payload: dict, response: HigginsResponse, provider_result: ProviderResult,
                  evidence_ids: set[str], source_ids: set[str]) -> Outcome:
    response, record = await _with_history(owner, case, response)
    # Luddish has already produced the Finding before commit; do not run a second advisory stage.
    response, fidelity = await _plain_english(owner, case, response, provider_result.answered_by)
    response = _with_evidence(case, response, record, provider_result)
    commit = TurnCommit(turn_id=job["turn_id"], case_id=case["case_id"], input_revision=job["input_revision"], committed_revision=response.revision,
                        question=payload["message"], answer_to_question_id=payload.get("answerToQuestionId"), response=response, provider=provider_result,
                        evidence_ids=sorted(evidence_ids), source_ids=sorted(source_ids), committed_at=now_utc())
    commit_id = await repo.stage_turn(owner, commit, job, repo.utc(case["expires_at"]))
    status = {"complete": "complete", "partial": "partial", "waiting_user": "waiting_user"}[response.completion]
    updated = await repo.accept_turn(owner, case, job, commit, commit_id, status, response.attention, response.question.wire() if response.question else None)
    if not updated:
        return Outcome("superseded")
    if response.revision == 1:
        await db.investigation_cases.update_one({"owner_id": owner, "case_id": case["case_id"]}, {"$set": {
            "routing.answeredBy": provider_result.answered_by, "routing.assessment": response.assessment,
            "routing.completion": response.completion, "routing.answeredAt": now_utc()}})
        counter = device_stats.investigator(provider_result.answered_by)
        if counter:
            await device_stats.bump(owner, counter)
    if response.outcome:
        # Apollo's case outcome — the latest one, from whichever layer answered.
        await db.investigation_cases.update_one({"owner_id": owner, "case_id": case["case_id"]}, {"$set": {"routing.outcome": response.outcome}})
        # ApolloSG's previous reports: this device's mark (supporting, contradicting, inconclusive or insufficient) on each
        # of the case's subjects, as one-way codes (services/observed_intel.py). Never content; never a simulated result.
        try:
            from services import observed_intel
            await observed_intel.record_case(owner, case["case_id"], response.outcome, completion=response.completion,
                                             simulated=bool(provider_result.simulated or getattr(response, "simulated", False)))
        except Exception:  # noqa: BLE001 — counting never fails the investigation
            log.warning("observed_intel_record_failed case=%s", case["case_id"], exc_info=True)
        # This device's own case history: one-way codes of the case's subjects and its result, read back only on this device.
        try:
            await history.record(owner, case, response.outcome, record.get("historyKeys") or [])
        except Exception:  # noqa: BLE001
            log.warning("case_history_record_failed case=%s", case["case_id"], exc_info=True)
    if fidelity:
        # The Fidelity Check of the latest result's plain English, for the admin portal: PASS/FAIL and why, no content.
        await db.investigation_cases.update_one({"owner_id": owner, "case_id": case["case_id"]},
                                                {"$set": {"routing.fidelity": {**fidelity, "at": now_utc()}}})
    return Outcome("committed", commit=commit, case=updated)


async def _commit_flyby(owner: str, case: dict, job: dict, payload: dict, fly_by: tc_flyby.FlyByOutcome,
                        capability_ids: set[str]) -> Optional[Outcome]:
    """TC Hawkeye settled the case: its result passes the same validation as Magnum DI's, then commits.
    None when it doesn't validate — Magnum DI then takes the case."""
    rows = await repo.list_evidence(owner, case["case_id"])
    evidence_ids = {row["evidence_id"] for row in rows}
    source_ids = {s["id"] for s in await repo.sources(owner, case["case_id"])}
    response, errors = validate(fly_by.response, revision=(case.get("response_revision") or 0) + 1, evidence_ids=evidence_ids,
                                source_ids=source_ids, capability_ids=capability_ids, pending_question=None, provider_complete=True,
                                material_gaps=_material_gaps(rows))
    if response is None:
        log.warning("tc_flyby_result_invalid case=%s errors=%s", case["case_id"], "; ".join(errors)[:300])
        return None
    provider_result = ProviderResult(provider="apollo", model="tc-flyby" + (f" + {fly_by.model}" if fly_by.model else ""), api_version="",
                                     finish_reason="STOP", provider_complete=True, usage=Usage(**fly_by.usage),
                                     source_ids=sorted(response.source_ids), simulated=fly_by.simulated, answered_by=fly_by.answered_by)
    return await _commit(owner, case, job, payload, response, provider_result, evidence_ids, source_ids)


async def run_turn(owner: str, case: dict, job: dict, progress) -> Outcome:
    """The case's investigation: Higgins Triage → TC Hawkeye → (only if needed) Magnum DI's one call for the case.

    Magnum DI flow: claim the case's one call → send question and evidence → validate the schema-shaped response
    → commit. No autonomous tool rounds, reassessment cycles, repair loops or retries.
    """
    payload = repo.dec_json(job["payload_ciphertext"])
    device = repo.device_profile(case)
    capability_ids = set((device or {}).get("capabilityIds", []))
    # Preserve the job's existing model metadata for TC Hawkeye, but do not
    # resolve or pin a cloud provider as a prerequisite for local inference.
    # An unavailable external provider must never block an on-device Finding.

    # ── Step 1: Assemble the case evidence ──
    await progress("ingest", "Assembling the case evidence.")
    await _register_triage_evidence(owner, case)
    rows = await repo.list_evidence(owner, case["case_id"])
    first_turn = not case.get("response_revision") and not payload.get("answerToQuestionId")
    search_on = True
    # What Magnum DI's result can't go below: TC Hawkeye's concern, established or provisional (tc_flyby/decide.floor).
    stored = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case["case_id"]}, {"_id": 0, "routing.tc_flyby.floor": 1}) or {}
    floor = ((stored.get("routing") or {}).get("tc_flyby") or {}).get("floor")

    # Too much written evidence for one investigation. Apollo sends NOTHING rather than quietly
    # shortening, sampling or dropping any of it, and no evidence is marked as examined — so this is
    # decided before TC Hawkeye reads anything.
    _parts, _marks, evidence_words = await ev.model_parts(owner, case, rows)
    if evidence_words > ev.EVIDENCE_WORD_LIMIT:
        return Outcome("evidence_too_large", evidence_words=evidence_words,
                       errors=[f"written evidence is {evidence_words} words; Apollo's limit for one investigation is {ev.EVIDENCE_WORD_LIMIT}"])

    # ── Step 2: Higgins Triage → TC Hawkeye (first turn only) ──
    if not first_turn:
        # A follow-up is answered from the case's locked findings (routers/investigations._follow_up), never by
        # another investigation: this turn sends nothing.
        return Outcome("call_limit_reached", errors=["a follow-up is answered from the case's findings, not by another investigation"])
    await _slm_stage(owner, case, job, "higgins_triage")
    fly_by = await tc_flyby.investigate(owner, case, job, payload["message"], rows, progress)
    await _slm_stage(owner, case, job, "tc_hawkeye")
    # Hawkeye determines whether deeper investigation is necessary. A resolved
    # case skips Magnum DI; an unresolved case requests its existing local role.
    if not fly_by.resolved:
        await _slm_stage(owner, case, job, "magnum_di")
    slm_finding = await _await_case_finding(owner, case, job, progress)
    if slm_finding:
        committed = await _commit_slm_finding(owner, case, job, payload, slm_finding, capability_ids)
        if committed is not None:
            return committed
    # SLM-led cases must not silently fall back to Hawkeye's old score or
    # to a cloud model when local inference is unavailable or invalid.
    return Outcome("device_unavailable", errors=[
        "An evidence-grounded on-device SLM Finding was not received. "
        "ApolloSG cannot complete this investigation on this device."
    ])
