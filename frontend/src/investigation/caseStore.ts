// Case-scoped UI projection. Application-owned create/upload/append operations live in transferManager and survive screens.
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/src/api/client";
import { storage } from "@/src/utils/storage";
import { dlog } from "@/src/utils/dlog";
import { forgetCase } from "./caseIndex";
import { enqueueConfirmCommit, dequeueConfirmCommit, pendingConfirmCommits, deleteInvestigation, getInvestigation } from "./deviceStore";
import { pickUpCase } from "./pickup";
import { deleteImageEvidenceFor } from "@/src/store/imageEvidence";
import { deleteReportProgress } from "@/src/store/reportProgress";
import { deleteOriginalSource } from "@/src/store/originalSource";
import { deleteOriginalEmailsFor } from "@/src/store/originalEmail";
import { forgetStopped, rememberStopped } from "@/src/store/resubmitReminderStore";
import { canResubmit } from "./resubmit";
import * as api from "./client";
import { safeUUID } from "./client";
import { observe } from "./deviceBroker";
import { appendManagedOperation, cancelManagedOperation, expireOperation, managedOperation, retryManagedOperation,
  settleManagedOperation, startManagedOperation, subscribeManagedOperation, type ManagedOperation } from "./transferManager";
import type { CreateCase, DeviceResult, Failure, HigginsResponse, InvestigationCase, InvestigationEvent, Job, Question, SourceReference, TurnCommit } from "./types";
import { investigatorName } from "@/src/domain/messageVoice";
import { investigationFollowUp, isFinished, type FollowUpAnswer } from "@/src/higgins/followUp";

export type Phase = "idle" | "creating" | "working" | "reconnecting" | "waiting_device" | "waiting_user" | "answered" | "failed" | "expired";
export interface CaseState {
  phase: Phase; operationId: string | null; caseData: InvestigationCase | null; job: Job | null; progress: string[];
  response: HigginsResponse | null; sources: SourceReference[]; turns: TurnCommit[]; failure: Failure | null;
  question: Question | null; error: string | null; notice: string | null; undeleted?: string | null;
  /** Follow-ups on the finished investigation, each answered from its record (never by Gemini). */
  followUps: FollowUpAnswer[];
}

const EMPTY: CaseState = { phase: "idle", operationId: null, caseData: null, job: null, progress: [], response: null,
  sources: [], turns: [], failure: null, question: null, error: null, notice: null, followUps: [] };

/** New material handed to a finished investigation: not added, not checked, and said so. */
function finishedWithNewMaterial(response: HigginsResponse, sources: SourceReference[], input: Omit<CreateCase, "deviceProfile">, answeredBy: string | null): FollowUpAnswer {
  const material = [...input.submissions.map((item) => item.value), ...input.initialFindings].join("\n");
  const answer = investigationFollowUp(response, sources, `${input.question}\n${material}`, safeUUID(), answeredBy);
  const note = material.trim() && !answer.newItems.length
    ? `${investigatorName(answeredBy)}'s investigation is finished, so the new material wasn't added to it or checked. To have it checked, start a new check.\n\n` : "";
  return { ...answer, question: input.question, answer: `${note}${answer.answer}` };
}

/** Device-local commit handshake: a finished investigation (not one waiting for the person's answer) is saved to
 *  permanent device storage with its original, read back, and only then is the server told it may delete its copy
 *  (investigation/pickup.ts). Idempotent. Also runs when the app attaches to a case that was already answered —
 *  TC FlyBy often settles a case before the app starts following it. Anything not yet confirmed is queued for retry. */
async function commitAnswered(caseId: string, caseData: InvestigationCase, question: string): Promise<void> {
  if (!caseData.response || caseData.response.question || caseData.status === "failed") return;
  // Already on this device at this revision: nothing new to keep (an unconfirmed copy is already queued).
  if ((await getInvestigation(caseId).catch(() => null))?.response?.revision === caseData.response.revision) return;
  try {
    const outcome = await pickUpCase(caseId, { question });
    if (outcome === "waiting" || outcome === "incomplete") await enqueueConfirmCommit(caseId);
  } catch { await enqueueConfirmCommit(caseId); }
}

const UNDELETED_KEY = "apollo.investigation.undeleted";

async function pendingDeletions(): Promise<string[]> {
  const raw = await storage.getItem<string | null>(UNDELETED_KEY, null).catch(() => null);
  try { return raw ? (JSON.parse(raw) as string[]) : []; } catch { return []; }
}
async function rememberDeletion(id: string) { const ids = await pendingDeletions(); if (!ids.includes(id)) await storage.setItem(UNDELETED_KEY, JSON.stringify([...ids, id])).catch(() => undefined); }
async function forgetDeletion(id: string) { await storage.setItem(UNDELETED_KEY, JSON.stringify((await pendingDeletions()).filter((value) => value !== id))).catch(() => undefined); }

export function useInvestigation(boundOperationId?: string | null) {
  const [state, setState] = useState<CaseState>(EMPTY);
  const stream = useRef<{ abort: () => void; lastSequence: () => number } | null>(null);
  const pending = useRef<{ turnId: string; key: string; message: string; answerTo: string | null } | null>(null);
  const caseRef = useRef<InvestigationCase | null>(null);
  const operationRef = useRef<string | null>(boundOperationId ?? null);
  const followed = useRef<string | null>(null);
  const generation = useRef(0);
  const pendingCancellation = useRef<{ caseId: string; jobId: string } | null>(null);
  const pendingDeviceResult = useRef<{ caseId: string; result: DeviceResult; job: Job; after: number } | null>(null);
  const cancelAction = useRef<() => Promise<void>>(async () => undefined);
  // When attach() is in control, adoptManaged must not fight it by setting state or calling follow.
  const attachOwns = useRef(false);
  const update = (patch: Partial<CaseState> | ((previous: CaseState) => Partial<CaseState>)) => setState((previous) => ({ ...previous, ...(typeof patch === "function" ? patch(previous) : patch) }));

  const refresh = useCallback(async (caseId: string, gen = generation.current) => {
    const [{ case: caseData }, turns, sources] = await Promise.all([api.getCase(caseId), api.listTurns(caseId), api.listSources(caseId)]);
    if (gen !== generation.current || (caseRef.current && caseRef.current.id !== caseId)) return caseData;
    caseRef.current = caseData;
    update({ caseData, turns: turns.items, sources: sources.items, response: caseData.response, question: caseData.response?.question ?? null });
    return caseData;
  }, []);

  const flushPendingDeletions = useCallback(async () => {
    for (const id of await pendingDeletions()) {
      try { await api.deleteCase(id); await forgetDeletion(id); }
      catch (error: unknown) { if (error instanceof ApiError && (error.status === 404 || error.status === 410)) await forgetDeletion(id); }
    }
    update({ undeleted: (await pendingDeletions())[0] ?? null });
    // Also retry confirmations not yet made (the phone's copy wasn't saved, checked or confirmed yet)
    for (const caseId of await pendingConfirmCommits()) {
      try { const outcome = await pickUpCase(caseId); if (outcome === "confirmed" || outcome === "nothing_held") await dequeueConfirmCommit(caseId); }
      catch (error: unknown) { if (error instanceof ApiError && (error.status === 404 || error.status === 410)) await dequeueConfirmCommit(caseId); }
    }
  }, []);

  /** When the server copy becomes unavailable, load the verified device record instead of clearing.
   *  Processing timeouts are separate: they report that work stopped and preserve available findings. */
  const handleServerUnavailable = useCallback(async (caseId: string, reason: string) => {
    const local = await getInvestigation(caseId).catch(() => null);
    if (local?.response) {
      const reconstructed: InvestigationCase = {
        schemaVersion: 1, id: local.caseId, revision: 0, gates: local.gates as import("./types").Gate[],
        status: (local.status ?? "complete") as import("./types").CaseStatus,
        createdAt: local.createdAt, updatedAt: local.completedAt, expiresAt: new Date(Date.now() + 365 * 24 * 3600_000).toISOString(),
        evidenceExpiresAt: null, reportExpiresAt: null, retentionClass: "device_local",
        reportByteSize: 0, response: local.response, activeJobId: null,
        pendingDeviceRequestIds: [], inventory: { total: 0, examined: 0, partial: 0, unavailable: 0, purged: 0, contentExpired: 0 },
        cleanupStatus: "complete" as const, answeredBy: local.answeredBy ?? null, settledReason: local.settledReason ?? null,
        simulated: local.simulated, origin: local.origin ?? null,
      };
      caseRef.current = reconstructed;
      setState((prev) => ({ ...prev, caseData: reconstructed, response: local.response, sources: local.sources, turns: local.turns,
        question: local.response.question ?? null, phase: local.response.question ? "waiting_user" : "answered",
        notice: "Original evidence has been cleaned up from the server. The saved investigation report is shown from this device." }));
    } else {
      // No device record available — show the reason clearly
      setState((prev) => ({ ...prev, phase: "expired",
        error: reason || "The server working copy is no longer available and no saved report was found on this device." }));
    }
  }, []);

  const follow = useCallback((caseId: string, job: Job, after = 0) => {
    dlog('caseStore', 'follow', { caseId, jobId: job.id, after, gen: generation.current });
    stream.current?.abort();
    const gen = generation.current;
    const operationId = operationRef.current;
    const live = () => gen === generation.current && caseRef.current?.id === caseId;
    update({ job, phase: "working" });
    stream.current = api.streamEvents(caseId, job.id, after, (event: InvestigationEvent) => {
      if (!live() || event.caseId !== caseId || event.jobId !== job.id) return;
      if (event.type === "progress") update((previous) => ({ progress: [...previous.progress.slice(-6), event.payload.message] }));
      else if (event.type === "response") update({ response: event.payload.response, sources: event.payload.sources, question: event.payload.response.question });
      else if (event.type === "retry_scheduled") update((previous) => ({ progress: [...previous.progress.slice(-6), event.payload.failure.message], phase: "working" }));
      else if (event.type === "device_request") {
        update({ phase: "waiting_device" });
        const consumed = event.sequence;
        void observe(event.payload).then((result) => { pendingDeviceResult.current = { caseId, result, job, after: consumed }; return api.submitDeviceResult(caseId, result); }).then(({ jobId }) => {
          pendingDeviceResult.current = null; if (live()) follow(caseId, { ...job, id: jobId ?? job.id }, consumed);
        }).catch(() => { if (live()) update({ phase: "failed", error: "ApolloSG couldn't safely deliver this device observation. Retry sends the same observation without starting a new check." }); });
      } else if (event.type === "completed") {
        dlog('caseStore', 'stream COMPLETED', { caseId, jobId: job.id, completion: event.payload.completion });
        pending.current = null;
        void refresh(caseId, gen).then(async (caseData) => {
          if (!live()) return;
          const phase = event.payload.completion === "waiting_user" ? "waiting_user" : "answered";
          update({ phase, failure: null, caseData });
          if (operationId) settleManagedOperation(operationId, caseId, caseData, { ...job, status: event.payload.caseStatus });
          // Only completed (not waiting_user) investigations are committed to permanent device storage.
          if (phase === "answered") await commitAnswered(caseId, caseData, pending.current?.message ?? "");
        }).catch(() => undefined);
      } else if (event.type === "partial") update({ failure: event.payload.reason });
      else if (event.type === "failed") {
        const failed = { ...job, status: "failed" as const, failure: event.payload };
        update({ phase: "failed", failure: event.payload, error: event.payload.message, job: failed });
        void refresh(caseId, gen).then((caseData) => { if (live() && operationId) settleManagedOperation(operationId, caseId, caseData, failed); }).catch(() => undefined);
      } else if (event.type === "cancelled") {
        pending.current = null;
        void refresh(caseId, gen).then((caseData) => { if (live()) update({ phase: caseData.response ? "answered" : "idle", progress: [] }); }).catch(() => undefined);
      } else if (event.type === "expired") {
        if (operationId) expireOperation(operationId, caseId);
        // Processing stopped — try to recover saved findings from device
        void handleServerUnavailable(caseId, "Temporary evidence expired before the investigation finished. Available findings are preserved.");
      }
    }, (reason) => {
      if (!live() || reason === "terminal") return;
      if (reason === "unauthorized") { update({ phase: "failed", error: "ApolloSG needs to re-register this device." }); return; }
      update({ phase: "reconnecting" });
      setTimeout(() => {
        if (!live()) return;
        api.getJob(caseId, job.id).then(({ job: fresh }) => {
          if (!live()) return;
          if (["queued", "investigating", "retry_wait", "waiting_device"].includes(fresh.status)) follow(caseId, fresh, stream.current?.lastSequence() ?? 0);
          else void refresh(caseId, gen).then((caseData) => {
            if (!live()) return;
            update({ phase: fresh.status === "failed" ? "failed" : caseData.response?.question ? "waiting_user" : "answered",
              failure: fresh.failure, error: fresh.failure?.message ?? null, job: fresh });
            if (operationId) settleManagedOperation(operationId, caseId, caseData, fresh);
          }).catch(() => undefined);
        }).catch((error: unknown) => { if (live()) {
          if (error instanceof ApiError && error.status === 410) void handleServerUnavailable(caseId, "The server working copy is no longer available.");
          else update({ phase: "failed", error: "Connection lost. Retry to reconnect to the same investigation." });
        } });
      }, 1500);
    });
  }, [refresh]);

  const adoptManaged = useCallback((record: ManagedOperation) => {
    if (operationRef.current !== record.operationId) return;
    // When attach() is managing the case, adoptManaged must not override its state.
    // attach() owns the lifecycle: it sets the generation, follows the job, and settles the case.
    if (attachOwns.current) {
      dlog('caseStore', 'adoptManaged SUPPRESSED (attach owns)', { phase: record.phase, caseId: record.caseData?.id });
      return;
    }
    dlog('caseStore', 'adoptManaged', { phase: record.phase, caseId: record.caseData?.id, jobId: record.job?.id, opId: record.operationId });
    if (record.caseData) { caseRef.current = record.caseData; }
    const progress = record.phase === "failed" ? ["This exact operation is ready to retry."]
      : record.phase === "submitted" || record.phase === "settled" ? ["The operation is attached to this investigation."]
      : ["Magnum DI is continuing this investigation."];
    // Propagate failure data from the job if available, or construct from error string
    const failure = record.job?.failure ?? (record.phase === "failed" && record.error ? { code: "operation_failed", message: record.error, retryable: true, retryAfterSeconds: null, missingEvidenceIds: [] } : null);
    const answered = record.followUp;
    if (answered) update((previous) => previous.followUps.some((item) => item.turnId === answered.turnId) ? {} : { followUps: [...previous.followUps, answered] });
    update({ operationId: record.operationId, caseData: record.caseData, job: record.job, error: record.error, failure, progress,
      phase: record.phase === "failed" ? "failed" : record.phase === "expired" ? "expired" : record.phase === "settled"
        ? record.caseData?.response?.question ? "waiting_user" : record.caseData?.response ? "answered" : "idle" : "working",
      response: record.caseData?.response ?? null, question: record.caseData?.response?.question ?? null });
    if (record.caseData && record.job && record.phase === "submitted") {
      const key = `${record.operationId}:${record.caseData.id}:${record.job.id}`;
      if (followed.current !== key) { followed.current = key; follow(record.caseData.id, record.job); }
    }
  }, [follow]);

  useEffect(() => {
    if (!boundOperationId) return;
    dlog('caseStore', 'subscribe managed op', { boundOperationId, gen: generation.current + 1 });
    stream.current?.abort(); generation.current += 1; followed.current = null; operationRef.current = boundOperationId;
    const unsubscribe = subscribeManagedOperation(boundOperationId, adoptManaged);
    return unsubscribe;
  }, [boundOperationId, adoptManaged]);

  const start = useCallback(async (input: Omit<CreateCase, "deviceProfile">, files: { uri: string; name: string; mediaType: string }[] = [], operationId = boundOperationId ?? safeUUID()) => {
    stream.current?.abort(); generation.current += 1; followed.current = null; operationRef.current = operationId; caseRef.current = null;
    setState((previous) => ({ ...EMPTY, undeleted: previous.undeleted, operationId, phase: "creating", progress: ["Creating the investigation case."] }));
    void flushPendingDeletions();
    const unsubscribe = subscribeManagedOperation(operationId, adoptManaged);
    const record = await startManagedOperation(operationId, input, files);
    adoptManaged(record); unsubscribe();
    return record.phase === "failed" || record.phase === "expired" ? null : record.caseData;
  }, [adoptManaged, boundOperationId, flushPendingDeletions]);

  const ask = useCallback(async (message: string) => {
    const caseData = caseRef.current ?? state.caseData; if (!caseData) return false;
    // A finished investigation is answered from its own record, on this device: no Magnum DI turn, no Gemini call —
    // even when the follow-up mentions a new link, email or number.
    const finished = state.response ?? caseData.response;
    if (isFinished(finished)) {
      const answer = investigationFollowUp(finished, state.sources, message, safeUUID(), caseData.answeredBy ?? null);
      update((previous) => ({ followUps: [...previous.followUps, answer], phase: "answered", error: null, notice: null }));
      return true;
    }
    const turn = pending.current?.message === message ? pending.current : { turnId: safeUUID(), key: safeUUID(), message,
      answerTo: (caseRef.current?.response?.question ?? state.question)?.id ?? null };
    pending.current = turn;
    update({ phase: "working", error: null, notice: null, failure: null, progress: ["Sending your follow-up to Magnum DI."] });
    const gen = generation.current; const live = () => gen === generation.current && caseRef.current?.id === caseData.id;
    try {
      const fresh = await api.getCase(caseData.id); if (!live()) return false;
      const { job, followUp } = await api.submitTurn(caseData.id, { expectedRevision: fresh.case.revision, turnId: turn.turnId, message,
        answerToQuestionId: turn.answerTo, evidenceIds: [] }, turn.key);
      if (!live()) return false;
      if (!job) { // the server found the investigation finished and answered from its record
        pending.current = null;
        update((previous) => ({ caseData: fresh.case, phase: "answered", followUps: followUp ? [...previous.followUps, followUp] : previous.followUps }));
        return true;
      }
      update({ caseData: fresh.case }); follow(caseData.id, job); return true;
    } catch (error: unknown) { if (live()) update({ phase: "failed", error: error instanceof Error ? error.message : "Magnum DI could not take this follow-up." }); return false; }
  }, [state.caseData, state.question, state.response, state.sources, follow]);

  const continueWith = useCallback(async (input: Omit<CreateCase, "deviceProfile">, operationId = boundOperationId ?? safeUUID()) => {
    const caseData = caseRef.current ?? state.caseData; if (!caseData || (caseData.activeJobId && !managedOperation(operationId, caseData.id))) return false;
    const finished = state.response ?? caseData.response;
    if (isFinished(finished)) {
      const answer = finishedWithNewMaterial(finished, state.sources, input, caseData.answeredBy ?? null);
      update((previous) => ({ followUps: [...previous.followUps, answer], phase: "answered", error: null, notice: null }));
      return true;
    }
    operationRef.current = operationId; followed.current = null;
    const unsubscribe = subscribeManagedOperation(operationId, adoptManaged);
    try {
      const record = await appendManagedOperation(operationId, caseData, input); adoptManaged(record); return record.phase !== "failed";
    } catch (error: unknown) { update({ phase: "failed", error: error instanceof Error ? error.message : "ApolloSG could not append the fresh observation." }); return false; }
    finally { unsubscribe(); }
  }, [adoptManaged, boundOperationId, state.caseData, state.response, state.sources]);

  const retry = useCallback(async () => {
    const caseData = caseRef.current ?? state.caseData;
    if (pendingDeviceResult.current) {
      const pendingResult = pendingDeviceResult.current; update({ phase: "working", error: null, progress: ["Retrying the same device observation."] });
      try { const { jobId } = await api.submitDeviceResult(pendingResult.caseId, pendingResult.result); pendingDeviceResult.current = null; follow(pendingResult.caseId, { ...pendingResult.job, id: jobId ?? pendingResult.job.id }, pendingResult.after); }
      catch { update({ phase: "failed", error: "ApolloSG still couldn't safely deliver this device observation. Retry remains available." }); }
      return;
    }
    if (operationRef.current) {
      const record = managedOperation(operationRef.current, caseData?.id);
      if (record?.phase === "failed") { update({ phase: "working", error: null, notice: null, progress: ["Resuming this exact operation."] }); adoptManaged((await retryManagedOperation(record.operationId, record.caseId))!); return; }
    }
    if (pendingCancellation.current) { await cancelAction.current(); return; }
    if (pending.current && (!state.job || state.job.status !== "failed")) { await ask(pending.current.message); return; }
    if (!caseData || !state.job) return;
    const gen = generation.current; const live = () => gen === generation.current && caseRef.current?.id === caseData.id;
    try { const fresh = await api.getCase(caseData.id); if (!live()) return; const { job } = await api.resumeJob(caseData.id, state.job.id, fresh.case.revision); if (live()) follow(caseData.id, job); }
    catch (error: unknown) { if (live()) update({ phase: "failed", error: error instanceof Error ? error.message : "Could not resume." }); }
  }, [state.caseData, state.job, ask, adoptManaged, follow]);

  const cancel = useCallback(async () => {
    const { caseData, job } = state; if (!caseData || !job) return;
    pendingCancellation.current = { caseId: caseData.id, jobId: job.id };
    update({ phase: "working", error: null, notice: null, progress: ["Requesting cancellation. Work remains connected until Apollo confirms it stopped."] });
    const gen = generation.current; const live = () => gen === generation.current && caseRef.current?.id === caseData.id;
    try {
      const result = await api.cancelJob(caseData.id, job.id, caseData.revision); const fresh = await refresh(caseData.id, gen); if (!live()) return;
      pendingCancellation.current = null;
      if (result.cancelled) { stream.current?.abort(); pending.current = null; if (operationRef.current) cancelManagedOperation(operationRef.current, caseData.id);
        update({ phase: fresh.response ? "answered" : "idle", progress: [], error: null,
          notice: "The active turn was cancelled. Existing case evidence remains available until its deadline." }); return; }
      if (result.outcome === "completed" || fresh.response) {
        stream.current?.abort(); pending.current = null;
        if (operationRef.current) settleManagedOperation(operationRef.current, caseData.id, fresh, null);
        update({ phase: fresh.response?.question ? "waiting_user" : "answered", response: fresh.response, question: fresh.response?.question ?? null,
          progress: [], error: null, notice: "Magnum DI finished before cancellation took effect, so the completed answer is shown." });
        return;
      }
      if (result.outcome === "failed") { stream.current?.abort(); update({ phase: "failed", progress: [], notice: null,
        error: "This turn finished with an error before cancellation took effect." }); return; }
      if (!["complete", "failed", "cancelled", "expired", "waiting_user"].includes(result.status) && fresh.activeJobId) {
        const active = (await api.getJob(caseData.id, fresh.activeJobId)).job;
        update({ notice: "This turn was no longer active; ApolloSG stayed connected to the current work." }); follow(caseData.id, active);
      } else { stream.current?.abort(); update({ notice: "This turn was no longer active, so no cancellation was applied." }); }
    } catch (error: unknown) {
      if (live()) update({ phase: "failed", notice: null, error: error instanceof ApiError && error.status === 409
        ? "Cancellation was not confirmed because this is no longer the same active turn. Retry against current work."
        : "Cancellation was not confirmed. ApolloSG kept the investigation connected; Retry to try again." });
    }
  }, [state, refresh, follow]);
  useEffect(() => { cancelAction.current = cancel; }, [cancel]);

  /** Open an existing case. `stoppedJobId` reopens a stopped turn so its Resubmit (and its pause) come back with it. */
  const attach = useCallback(async (caseId: string, stoppedJobId?: string) => {
    dlog('caseStore', 'attach START', { caseId, gen: generation.current + 1, opRef: operationRef.current });
    attachOwns.current = true;
    stream.current?.abort(); pending.current = null; generation.current += 1; followed.current = null;
    caseRef.current = { id: caseId } as InvestigationCase;
    setState((previous) => ({ ...EMPTY, undeleted: previous.undeleted, operationId: operationRef.current, phase: "creating", progress: ["Opening the investigation."] }));
    void flushPendingDeletions(); const gen = generation.current; const live = () => gen === generation.current && caseRef.current?.id === caseId;
    try {
      const caseData = await refresh(caseId, gen);
      if (!live()) { dlog('caseStore', 'attach STALE after refresh', { caseId, gen, current: generation.current }); attachOwns.current = false; return null; }
      const stopped = !caseData.activeJobId && stoppedJobId ? (await api.getJob(caseId, stoppedJobId)).job : null;
      if (!live()) { dlog('caseStore', 'attach STALE after getJob', { caseId }); attachOwns.current = false; return null; }
      if (caseData.activeJobId) {
        dlog('caseStore', 'attach → FOLLOW active job', { caseId, jobId: caseData.activeJobId });
        const { job } = await api.getJob(caseId, caseData.activeJobId);
        // attach has determined the path — release ownership before follow takes over
        attachOwns.current = false;
        if (live()) follow(caseId, job);
      } else if (stopped?.status === "failed") {
        dlog('caseStore', 'attach → FAILED (stopped job)', { caseId });
        attachOwns.current = false;
        update({ phase: "failed", job: stopped, failure: stopped.failure, error: stopped.failure?.message ?? null });
      } else {
        const phase = caseData.status === "failed" ? "failed" : caseData.response?.question ? "waiting_user" : caseData.response ? "answered" : "idle";
        dlog('caseStore', 'attach → SETTLED', { caseId, phase, hasResponse: !!caseData.response });
        attachOwns.current = false;
        update({ phase });
        void commitAnswered(caseId, caseData, "");
      }
      return caseData;
    } catch (error: unknown) {
      attachOwns.current = false;
      if (!live()) return null;
      // Server returned 404/410 — the investigation may have been purged after local commit.
      // Try loading from the device store.
      if (error instanceof ApiError && (error.status === 404 || error.status === 410)) {
        const { getInvestigation } = await import("./deviceStore");
        const local = await getInvestigation(caseId).catch(() => null);
        if (local) {
          const reconstructed: InvestigationCase = {
            schemaVersion: 1, id: local.caseId, revision: 0, gates: local.gates as import("./types").Gate[],
            status: (local.status ?? "complete") as import("./types").CaseStatus,
            createdAt: local.createdAt, updatedAt: local.completedAt, expiresAt: new Date(Date.now() + 365 * 24 * 3600_000).toISOString(),
            evidenceExpiresAt: null, reportExpiresAt: null, retentionClass: "device_local",
            reportByteSize: 0, response: local.response, activeJobId: null,
            pendingDeviceRequestIds: [], inventory: { total: 0, examined: 0, partial: 0, unavailable: 0, purged: 0, contentExpired: 0 },
            cleanupStatus: "complete" as const, answeredBy: local.answeredBy ?? null, settledReason: local.settledReason ?? null,
            simulated: local.simulated, origin: local.origin ?? null,
          };
          caseRef.current = reconstructed;
          update({ caseData: reconstructed, response: local.response, sources: local.sources, turns: local.turns,
            question: local.response.question ?? null, phase: local.response.question ? "waiting_user" : "answered" });
          return reconstructed;
        }
      }
      update({ phase: error instanceof ApiError && error.status === 410 ? "expired" : "failed", error: error instanceof Error ? error.message : "Could not open this investigation." });
      return null;
    }
  }, [refresh, follow, flushPendingDeletions, handleServerUnavailable]);

  const remove = useCallback(async () => {
    const caseData = state.caseData; stream.current?.abort(); pending.current = null;
    if (operationRef.current) cancelManagedOperation(operationRef.current, caseData?.id);
    generation.current += 1; caseRef.current = null; operationRef.current = null;
    setState((previous) => ({ ...EMPTY, undeleted: previous.undeleted }));
    if (caseData) {
      // Remove from all local stores (device investigation + supplementary stores)
      void forgetStopped(caseData.id);
      await deleteInvestigation(caseData.id);
      await forgetCase(caseData.id);
      void deleteImageEvidenceFor(caseData.id);
      void deleteReportProgress(caseData.id);
      void deleteOriginalSource(caseData.id);
      void deleteOriginalEmailsFor(caseData.id);
      try { await api.deleteCase(caseData.id); } catch { await rememberDeletion(caseData.id); update({ error: "Local view cleared; server deletion could not be confirmed.", undeleted: caseData.id }); }
    }
  }, [state.caseData]);

  const retryDelete = useCallback(async () => {
    const id = state.undeleted; if (!id) return;
    try { await api.deleteCase(id); await forgetDeletion(id); update({ undeleted: null, error: null }); }
    catch (error: unknown) { if (error instanceof ApiError && (error.status === 404 || error.status === 410)) { await forgetDeletion(id); update({ undeleted: null, error: null }); } }
  }, [state.undeleted]);

  // Quiet reminder on Ask Higgins: a stopped case is remembered until it is resubmitted, answered or removed.
  const stoppedCaseId = state.caseData?.id; const stoppedJobId = state.job?.id; const resubmitAt = state.failure?.resubmitAt;
  const caseExpiresAt = state.caseData?.expiresAt; const resubmittable = canResubmit(state.failure);
  useEffect(() => {
    if (!stoppedCaseId) return;
    if (state.phase === "failed" && resubmitAt && stoppedJobId && caseExpiresAt && resubmittable) {
      void rememberStopped({ caseId: stoppedCaseId, jobId: stoppedJobId, resubmitAt, expiresAt: caseExpiresAt });
    } else if (state.phase === "working" || state.phase === "answered" || state.phase === "waiting_user") void forgetStopped(stoppedCaseId);
  }, [state.phase, stoppedCaseId, stoppedJobId, resubmitAt, caseExpiresAt, resubmittable]);

  useEffect(() => () => { stream.current?.abort(); }, []);
  return { state, start, ask, continueWith, retry, cancel, remove, attach, retryDelete };
}