// Case API client: idempotent create/turn, event stream with sequence-based reconnect, explicit terminal completion.
import * as Crypto from "expo-crypto";
import { Platform } from "react-native";

import { API_BASE, ApiError, apiDelete, apiGet, apiPost } from "@/src/api/client";
import { getDeviceToken } from "@/src/auth/deviceIdentity";
import { enforceEgress } from "@/src/domain/privacy";
import { sanitizationMetadata, type SanitizationReceipt } from "@/src/domain/imageSanitization";
import { screenImage } from "@/src/domain/imagePrivacy";

/** Submitting an image authorises its analysis. The only privacy step is credential protection: if on-device
 *  text recognition finds a credential/authentication secret that wasn't already redacted, the image is not
 *  sent (it can't be blacked out here). Personal details are evidence and are kept. The original is unchanged.
 *  If on-device screening was unavailable (ocr_unavailable), the image is WITHHELD — fail-closed. */
async function investigationImageMeta(uri: string, gate?: SanitizationReceipt): Promise<Record<string, unknown>> {
  if (gate) {
    if (gate.decision === "withheld") return Promise.reject(new Error("This image was withheld."));
    return sanitizationMetadata(gate);
  }
  const screening = await screenImage(uri, "investigation_evidence");
  if (screening.status === "ocr_unavailable") {
    throw new Error("Apollo could not screen this image for credentials (text recognition unavailable). The image was not sent.");
  }
  if (screening.sensitiveRegions.some((r) => r.sensitiveType === "credential")) {
    throw new Error("This image appears to show a password, PIN or one-time code, so ApolloSG didn't send it. Crop that part out and add the image again.");
  }
  // The text the device read from the image (credentials already removed) goes with it, so Higgins Triage can
  // investigate the screenshot's content like any other text before deciding whether deeper analysis is needed.
  const deviceExtractedText = screening.extractedText.trim();
  return deviceExtractedText ? { deviceExtractedText } : {};
}
import type { CreateCase, DeviceProfile, DeviceResult, EvidenceItem, InvestigationCase, InvestigationEvent, Job, SourceReference, TurnCommit } from "./types";
import type { FollowUpAnswer } from "@/src/higgins/followUp";
import type { PickupOriginal, PickupSource, SavedParts } from "@/src/domain/pickupCheck";

/** Generate a UUID key with robust fallback for environments where expo-crypto's randomUUID isn't available. */
export function safeUUID(): string {
  try {
    const id = Crypto.randomUUID();
    if (id && typeof id === "string" && id.length >= 8) return id;
  } catch { /* fall through */ }
  // Fallback: manual UUID v4 using Math.random
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

async function postWithKey<T>(path: string, body: Record<string, unknown>, key: string, signal?: AbortSignal): Promise<T> {
  const token = await getDeviceToken();
  if (!token) throw new ApiError(401, "ApolloSG hasn't registered this device yet.");
  // Ensure key is always a valid string
  const safeKey = key && typeof key === "string" && key.length >= 8 ? key : safeUUID();
  const res = await fetch(`${API_BASE}${path}`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, "Idempotency-Key": safeKey }, body: JSON.stringify(enforceEgress("investigation", body)), signal });
  if (!res.ok) {
    let message = res.statusText;
    try { const data = await res.json(); message = data?.error?.message ?? data?.detail ?? message; } catch { /* keep */ }
    throw new ApiError(res.status, typeof message === "string" ? message : JSON.stringify(message));
  }
  return (await res.json()) as T;
}

export function createCase(body: CreateCase, key = safeUUID()) { return postWithKey<{ case: InvestigationCase; job?: Job }>("/investigations", body as unknown as Record<string, unknown>, key); }
export function getCase(caseId: string) { return apiGet<{ case: InvestigationCase }>(`/investigations/${caseId}`); }
export function getJob(caseId: string, jobId: string) { return apiGet<{ job: Job; caseRevision: number; responseRevision: number | null }>(`/investigations/${caseId}/jobs/${jobId}`); }
export function listTurns(caseId: string) { return apiGet<{ items: TurnCommit[]; total: number }>(`/investigations/${caseId}/turns`); }
export function listSources(caseId: string) { return apiGet<{ items: SourceReference[]; total: number }>(`/investigations/${caseId}/sources`); }
export function listEvidence(caseId: string) { return apiGet<{ items: EvidenceItem[]; total: number }>(`/investigations/${caseId}/evidence`); }
export function getEvidence(caseId: string, evidenceId: string) { return apiGet<{ evidence: EvidenceItem }>(`/investigations/${caseId}/evidence/${evidenceId}`); }
/** Returns the URL for fetching evidence content bytes (images, files). Must be fetched with auth headers. */
export function evidenceContentUrl(caseId: string, evidenceId: string) { return `${API_BASE}/investigations/${caseId}/evidence/${evidenceId}/content`; }
export function deleteCase(caseId: string) { return apiDelete<void>(`/investigations/${caseId}`); }
export function confirmCommit(caseId: string, saved?: SavedParts) { return apiPost<{ purged: boolean; status: string; removedAt?: string | null }>(`/investigations/${caseId}/confirm-commit`, "investigation", saved ? { saved } : {}); }
/** What the server keeps for this phone until the phone confirms it saved its own copy (investigation/pickup.ts). */
export interface HeldCopy {
  caseId: string; held: true; heldAt: string;
  case: InvestigationCase; turns: TurnCommit[]; sources: SourceReference[]; evidence: EvidenceItem[];
  originals: PickupOriginal[]; source: PickupSource;
}
export function getPickup(caseId: string) { return apiGet<HeldCopy | { caseId: string; held: false; working: boolean }>(`/investigations/${caseId}/pickup`); }
export function submitTurn(caseId: string, body: { expectedRevision: number; turnId: string; message: string; answerToQuestionId: string | null; evidenceIds: string[] }, key: string, signal?: AbortSignal) {
  // A follow-up on a finished investigation comes back answered from its record, with no job (no Magnum DI call).
  return postWithKey<{ job: Job | null; followUp?: FollowUpAnswer; caseRevision: number }>(`/investigations/${caseId}/turns`, body, key, signal);
}
export function resumeJob(caseId: string, jobId: string, expectedRevision: number) { return postWithKey<{ job: Job }>(`/investigations/${caseId}/jobs/${jobId}/resume`, { expectedRevision }, safeUUID()); }
export function cancelJob(caseId: string, jobId: string, expectedRevision: number) { return apiPost<{ status: string; outcome: "cancelled" | "completed" | "failed" | "superseded"; cancelled: boolean; cleanupStatus: string; caseRevision: number; responseRevision: number | null }>(`/investigations/${caseId}/jobs/${jobId}/cancel`, "investigation", { expectedRevision }); }
export function submitDeviceResult(caseId: string, result: DeviceResult) { return postWithKey<{ accepted: boolean; jobId: string }>(`/investigations/${caseId}/device-results`, result as unknown as Record<string, unknown>, result.requestId); }
export function addObservationEvidence(expectedRevision: number, caseId: string, deviceResult: DeviceResult) {
  return apiPost<{ evidence: EvidenceItem; caseRevision: number }>(`/investigations/${caseId}/evidence`, "investigation", { expectedRevision, clientItemId: Crypto.randomUUID(), parentId: null, kind: "observation", deviceResult: deviceResult as unknown as Record<string, unknown> });
}
export interface SettingsPlan { id: string; caseId: string; target: string; match: "exact" | "platform_only" | "unresolved"; mode: "permission_request" | "settings_link" | "instructions"; instructions: string[]; sourceIds: string[]; executionDescriptorId: string | null; expectedObservation: { capabilityId: string; field: string; expectedValue: boolean | string | null } | null }
export interface SavedReport { reportId: string; caseId: string; gates: string[]; savedAt: string; responseRevision: number; overview: string; explanationMarkdown: string; assessment: string; attention: string; scope: string; findings: string[]; uncertainties: string[]; sources: { url: string; title: string; authority: string }[]; actions: { id: string; label: string; instruction: string; kind: string }[]; historical: boolean; retentionNotice: string }
export function createSettingsPlan(caseId: string, body: { expectedRevision: number; target: string; device: DeviceProfile; capabilityId: string | null; expectedField: string; expectedValue: boolean | string | null }) {
  return apiPost<{ plan: SettingsPlan; researchNote: string | null }>(`/investigations/${caseId}/settings-plan`, "investigation", body as unknown as Record<string, unknown>);
}
export function recheckPlan(caseId: string, planId: string, deviceResultIds: string[]) {
  return apiPost<{ planId: string; checkedAt: string; outcome: "correct" | "not_yet_correct" | "cannot_observe" | "failed"; evidenceIds: string[]; explanation: string }>(`/investigations/${caseId}/settings-plan/${planId}/recheck`, "investigation", { deviceResultIds });
}
export function confirmSettingsPlan(caseId: string, planId: string, confirmed: boolean) {
  return apiPost<{ planId: string; confirmed: boolean; checkedAt: string; evidenceId: string; verification: "user_reported"; explanation: string }>(`/investigations/${caseId}/settings-plan/${planId}/confirm`, "investigation", { confirmed });
}
export function saveReport(caseId: string, responseRevision: number) { return apiPost<{ reportId: string }>(`/investigations/${caseId}/reports`, "investigation", { responseRevision }); }
export function listReports(cursor?: string | null, limit = 25) { return apiGet<{ items: SavedReport[]; total: number; nextCursor: string | null }>(`/investigations/reports/list?limit=${limit}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`); }
export function getReport(reportId: string) { return apiGet<{ report: SavedReport }>(`/investigations/reports/${encodeURIComponent(reportId)}`); }
export function deleteReport(reportId: string) { return apiDelete<void>(`/investigations/reports/${reportId}`); }
export function addTextEvidence(caseId: string, expectedRevision: number, text: string, label: string) {
  return apiPost<{ evidence: EvidenceItem; caseRevision: number }>(`/investigations/${caseId}/evidence`, "investigation", { expectedRevision, clientItemId: Crypto.randomUUID(), parentId: null, kind: "text", text, label });
}
export function addSubmissionEvidence(caseId: string, expectedRevision: number, item: { clientItemId: string; kind: "text" | "url"; value: string; label?: string }, signal?: AbortSignal) {
  return postWithKey<{ evidence: EvidenceItem; caseRevision: number }>(`/investigations/${caseId}/evidence`, {
    expectedRevision, clientItemId: item.clientItemId, parentId: null, kind: item.kind,
    ...(item.kind === "url" ? { url: item.value } : { text: item.value }), label: item.label ?? "",
  }, item.clientItemId, signal);
}

/** Multipart file evidence (single shot, no resume): kept only for callers that accept an all-or-nothing upload.
 *  Images are checked on-device for credentials first (see investigationImageMeta). */
export async function uploadFileEvidence(caseId: string, expectedRevision: number, file: { uri: string; name: string; mediaType: string }, kind: "image" | "document" | "audio" | "attachment", sanitization?: SanitizationReceipt) {
  const sanitizationMeta = kind === "image" ? await investigationImageMeta(file.uri, sanitization) : {};
  const token = await getDeviceToken();
  if (!token) throw new ApiError(401, "ApolloSG hasn't registered this device yet.");
  const form = new FormData();
  form.append("metadata", JSON.stringify({ expectedRevision, clientItemId: Crypto.randomUUID(), parentId: null, kind, filename: file.name, mediaType: file.mediaType, ...sanitizationMeta }));
  if (Platform.OS === "web") form.append("file", await (await fetch(file.uri)).blob(), file.name);
  else form.append("file", { uri: file.uri, name: file.name, type: file.mediaType } as unknown as Blob);
  const res = await fetch(`${API_BASE}/investigations/${caseId}/evidence`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: form });
  if (!res.ok) { let message = res.statusText; try { const data = await res.json(); message = data?.error?.message ?? message; } catch { /* keep */ } throw new ApiError(res.status, message); }
  return (await res.json()) as { evidence: EvidenceItem; caseRevision: number };
}

// ---------------------------------------------------------------- resumable / retry-safe file upload
// The evidence-acknowledgement boundary is durable evidence publication on the SERVER, never "the request started"
// or "bytes were sent". A file is read into memory exactly once per attempt; the resulting `FileUploadHandle` is
// handed back to the caller after every step so a caller-held reference survives a failure and lets a RETRY resume
// from the exact chunk reached — reusing the SAME upload session (each chunk PUT is idempotent server-side) — with
// no duplicate upload, no re-reading the original file, and no risk of the original being deleted mid-transfer.
const UPLOAD_CHUNK_BYTES = 1024 * 1024; // must match services.higgins.repository.CHUNK_BYTES

export interface FileUploadHandle {
  transferId: string; createRequestKey: string; uploadId: string | null; evidenceRootId: string | null;
  clientItemId: string; declaredBytes: number | null; bytes: Uint8Array | null; nextChunk: number; expiresAt: string;
}

export function createFileUploadHandle(caseExpiresAt: string): FileUploadHandle {
  return { transferId: Crypto.randomUUID(), createRequestKey: Crypto.randomUUID(), uploadId: null, evidenceRootId: null,
    clientItemId: Crypto.randomUUID(), declaredBytes: null, bytes: null, nextChunk: 0, expiresAt: caseExpiresAt };
}

export function createUpload(caseId: string, body: { expectedRevision: number; clientItemId: string; parentId: string | null; kind: "image" | "document" | "audio" | "attachment"; filename: string; mediaType: string; declaredBytes: number; imageMeta?: Record<string, unknown> }, key: string, signal?: AbortSignal) {
  const { imageMeta, ...rest } = body;
  return postWithKey<{ uploadId: string; chunkBytes: number; expiresAt: string; evidenceRootId: string; replayed: boolean }>(`/investigations/${caseId}/uploads`, { ...rest, ...(imageMeta ?? {}) } as unknown as Record<string, unknown>, key, signal);
}

async function putChunk(caseId: string, uploadId: string, index: number, chunk: Uint8Array, signal?: AbortSignal): Promise<void> {
  const token = await getDeviceToken();
  if (!token) throw new ApiError(401, "ApolloSG hasn't registered this device yet.");
  let lastError: unknown = null;
  for (let attempt = 0; attempt <= 1; attempt++) {
    try {
      const res = await fetch(`${API_BASE}/investigations/${caseId}/uploads/${uploadId}/chunks/${index}`, { method: "PUT", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/octet-stream" }, body: chunk as unknown as BodyInit, signal });
      if (!res.ok) { let message = res.statusText; try { const data = await res.json(); message = data?.error?.message ?? message; } catch { /* keep */ } throw new ApiError(res.status, message); }
      return;
    } catch (e) { lastError = e; if (attempt === 0) await new Promise((r) => setTimeout(r, 500)); }
  }
  throw lastError instanceof Error ? lastError : new ApiError(0, "Chunk upload failed.");
}

export function completeUpload(caseId: string, uploadId: string, expectedRevision: number, key = Crypto.randomUUID(), signal?: AbortSignal) {
  return postWithKey<{ evidence: EvidenceItem; caseRevision: number; replayed?: boolean }>(`/investigations/${caseId}/uploads/${uploadId}/complete`, { expectedRevision }, key, signal);
}

/** Reads the file once (or reuses the reserved handle's already-read bytes), uploads it chunk by chunk
 * through the resumable endpoints, and finalises. `onHandle` is invoked before I/O, after session replay and after
 * every chunk so the caller can retain the handle for a retry; nothing here ever touches the source file's URI
 * after the initial read, and finalisation is the ONLY point at which the evidence becomes durably published.
 * Images are checked on-device for credentials first (see investigationImageMeta). */
export async function uploadFileEvidenceResumable(
  caseId: string, expectedRevision: number, file: { uri: string; name: string; mediaType: string }, kind: "image" | "document" | "audio" | "attachment",
  reserved: FileUploadHandle, onHandle: (handle: FileUploadHandle) => void,
  signal?: AbortSignal, sanitization?: SanitizationReceipt,
): Promise<{ evidence: EvidenceItem; caseRevision: number }> {
  let handle = reserved;
  onHandle(handle);
  if (!handle.bytes) {
    const response = await fetch(file.uri, { signal });
    if (!response.ok) throw new Error("ApolloSG could not read the selected file copy.");
    const bytes = new Uint8Array(await response.arrayBuffer());
    handle = { ...handle, declaredBytes: bytes.length, bytes };
    onHandle(handle);
  }
  if (!handle.uploadId) {
    const imageMeta = kind === "image" ? await investigationImageMeta(file.uri, sanitization) : undefined;
    const created = await createUpload(caseId, { expectedRevision, clientItemId: handle.clientItemId, parentId: null, kind,
      filename: file.name, mediaType: file.mediaType, declaredBytes: handle.declaredBytes!, imageMeta }, handle.createRequestKey, signal);
    handle = { ...handle, uploadId: created.uploadId, evidenceRootId: created.evidenceRootId, expiresAt: created.expiresAt };
    onHandle(handle);
  }
  const totalChunks = Math.max(1, Math.ceil(handle.declaredBytes! / UPLOAD_CHUNK_BYTES));
  for (let index = handle.nextChunk; index < totalChunks; index++) {
    if (Date.parse(handle.expiresAt) <= Date.now()) throw new Error("The secure upload window expired. Select the file again.");
    const start = index * UPLOAD_CHUNK_BYTES;
    const chunk = handle.bytes!.subarray(start, Math.min(start + UPLOAD_CHUNK_BYTES, handle.declaredBytes!));
    await putChunk(caseId, handle.uploadId!, index, chunk, signal);
    handle = { ...handle, nextChunk: index + 1 };
    onHandle(handle);
  }
  return await completeUpload(caseId, handle.uploadId!, expectedRevision, handle.transferId, signal);
}

/** SSE over XHR with sequence-based reconnect. `onTerminal` fires only on an explicit terminal event; EOF alone is an interruption. */
export function streamEvents(caseId: string, jobId: string, after: number, onEvent: (event: InvestigationEvent) => void, onEnd: (reason: "terminal" | "interrupted" | "unauthorized") => void) {
  const xhr = new XMLHttpRequest();
  let seen = 0; let finished = false; let last = after;
  const end = (reason: "terminal" | "interrupted" | "unauthorized") => { if (!finished) { finished = true; onEnd(reason); } };
  xhr.open("GET", `${API_BASE}/investigations/${caseId}/jobs/${jobId}/events?after=${after}`);
  xhr.setRequestHeader("Accept", "text/event-stream");
  void getDeviceToken().then((token) => { if (!token) { end("unauthorized"); return; } xhr.setRequestHeader("Authorization", `Bearer ${token}`); xhr.send(); });
  const consume = () => {
    const text = xhr.responseText ?? ""; const chunk = text.slice(seen); const lastBreak = chunk.lastIndexOf("\n\n");
    if (lastBreak < 0) return; seen += lastBreak + 2;
    for (const block of chunk.slice(0, lastBreak).split("\n\n")) {
      const data = block.split("\n").find((line) => line.startsWith("data: "));
      if (!data) continue;
      try {
        const event = JSON.parse(data.slice(6)) as InvestigationEvent;
        if (event.sequence <= last) continue;
        last = event.sequence; onEvent(event);
        if (["completed", "failed", "cancelled", "expired", "device_request"].includes(event.type)) end("terminal");
      } catch { /* partial */ }
    }
  };
  xhr.onprogress = consume;
  xhr.onload = () => { consume(); if (xhr.status === 401 || xhr.status === 403) end("unauthorized"); else end("interrupted"); };
  xhr.onerror = () => end("interrupted");
  xhr.timeout = 150000; xhr.ontimeout = () => end("interrupted");
  return { abort: () => { finished = true; xhr.abort(); }, lastSequence: () => last };
}
