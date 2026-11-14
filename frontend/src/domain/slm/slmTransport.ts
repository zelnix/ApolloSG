/**
 * Authenticated handoff for mandatory on-device SLM investigation stages.
 * The server issues the exact case request; the device returns its result.
 * No cloud-model substitution, cross-case evidence reuse, or invented verdict.
 */
import { investigationAudit } from "../../investigation/auditStore";
import { recordSuccessfulSLMInference, recordFailedSLMInference } from "./sharedRuntime.ts";
import { apiPost } from "../../api/client.ts";
import { reasonForCase, type CaseSLMRequest } from "./caseContract.ts";
import type { SLMAdapter, SLMRole } from "./index.ts";

export interface Issued {
  request: CaseSLMRequest;
  expiresAt: string;
  issuedAt?: string;
}
interface Receipt {
  accepted: boolean;
  advisoryOnly: boolean;
  caseId: string;
  requestId: string;
}

export type HandoffResult =
  | { status: "accepted"; requestId: string }
  | { status: "unavailable" | "invalid_output"; reason: string };

export async function submitAdvisoryForActiveCase(
  caseId: string,
  jobId: string,
  caseRevision: number,
  role: SLMRole,
  adapter: SLMAdapter | null,
): Promise<HandoffResult> {
  // Server chooses the evidence and instructions. This API refuses expired,
  // superseded or cross-device cases; callers must not substitute evidence.
  const issued = await apiPost<Issued>(
    `/investigations/${encodeURIComponent(caseId)}/slm/requests`,
    "slm_advisory",
    { jobId, caseRevision, role },
  );
  return submitIssuedAdvisory(caseId, issued, adapter);
}

/** The investigation coordinator may issue the same request over the
 * authenticated SSE stream. Do not open a second request or use Gemini.
 */
// In-memory only: a lost HTTP acknowledgement must resend the EXACT same
// inference result. Rerunning a nondeterministic model could cause a conflict.
const pendingReceipts = new Map<string, { expiresAt: number; payload: {
  caseId: string; caseRevision: number; requestId: string;
  execution: string; modelId: string; answer: unknown;
} }>();

const inFlight = new Map<string, Promise<HandoffResult>>();
const pendingFailures = new Map<string, { expiresAt: number; result: Extract<HandoffResult, { status: "unavailable" | "invalid_output" }> }>();
export function submitIssuedAdvisory(caseId: string, issued: Issued, adapter: SLMAdapter | null): Promise<HandoffResult> {
  const key = JSON.stringify([caseId, issued.request.requestId]);
  const active = inFlight.get(key);
  if (active) return active;
  const work = deliverIssuedAdvisory(caseId, issued, adapter).finally(() => inFlight.delete(key));
  inFlight.set(key, work);
  return work;
}

async function deliverIssuedAdvisory(
  caseId: string,
  issued: Issued,
  adapter: SLMAdapter | null,
): Promise<HandoffResult> {
  if (!adapter) return { status: "unavailable", reason: "on_device_model_unavailable" };
  const caseRevision = issued.request.caseRevision;
  if (issued.request.caseId !== caseId || !Number.isFinite(Date.parse(issued.expiresAt)) ||
      !Number.isSafeInteger(caseRevision) || caseRevision < 0 || !issued.request.requestId ||
      new Date(issued.expiresAt).getTime() <= Date.now()) {
    return { status: "invalid_output", reason: "invalid_server_request" };
  }
  const auditToken = await investigationAudit.open(caseId).catch(() => null);
  const stage = { caseId, caseRevision, requestId: issued.request.requestId, role: issued.request.role, operation: issued.request.operation };
  const save = async (change: Partial<import("../investigationAudit").SlmStage>) => {
    if (auditToken) await investigationAudit.stage(auditToken, { ...stage, status: "requested", ...change }).catch(() => console.warn("[SLM audit] Local audit could not be retained"));
  };
  const priorAudit = await investigationAudit.get(caseId).catch(() => null);
  if (priorAudit?.stages.some((s) => s.requestId === stage.requestId && s.caseRevision === stage.caseRevision && s.acceptedAt))
    return { status: "accepted", requestId: stage.requestId };
  if (!priorAudit?.stages.some((s) => s.requestId === stage.requestId && s.caseRevision === stage.caseRevision))
    await save({ status: "requested", observedAt: new Date().toISOString(), requestedAt: issued.issuedAt ?? null });
  const expiry = Date.parse(issued.expiresAt);
  const key = JSON.stringify([caseId, caseRevision, issued.request.requestId, adapter.modelId]);
  for (const [id, entry] of pendingReceipts) {
    if (entry.expiresAt <= Date.now()) pendingReceipts.delete(id);
  }
  for (const [id, entry] of pendingFailures) if (entry.expiresAt <= Date.now()) pendingFailures.delete(id);
  const reportFailure = async (result: Extract<HandoffResult, { status: "unavailable" | "invalid_output" }>): Promise<HandoffResult> => {
    const reason = /^[A-Za-z0-9_:.-]{1,200}$/.test(result.reason) ? result.reason : result.status;
    await apiPost(`/investigations/${encodeURIComponent(caseId)}/slm/failures`, "slm_advisory", {
      caseId, caseRevision, requestId: issued.request.requestId, status: result.status, reason,
    });
    return result;
  };
  const failure = pendingFailures.get(key);
  if (failure) return reportFailure(failure.result);
  let payload = pendingReceipts.get(key)?.payload;
  if (!payload) {
    let invoked = false;
    const observedAdapter: SLMAdapter = { modelId: adapter.modelId, canFit: adapter.canFit?.bind(adapter), infer: async (request) => {
      if (!invoked) { invoked = true; await save({ status: "running", startedAt: new Date().toISOString(), modelId: adapter.modelId }); }
      return adapter.infer(request);
    } };
    const result = await reasonForCase(issued.request, observedAdapter);
    // The audit wrapper is not the registered runtime identity; preserve its contract-validated activity status.
    if (invoked) {
      if (result.status === "completed") recordSuccessfulSLMInference(adapter);
      else recordFailedSLMInference(adapter, result.status);
    }
    if (result.status === "completed") await save({ status: "returned", returnedAt: new Date().toISOString(), output: result.answer });
    else await save({ status: "failed", failedAt: new Date().toISOString(), failure: result.reason });
    if (result.status !== "completed") {
      // No fabricated success and no automatic Gemini fallback.
      const failureResult = { status: result.status, reason: result.reason };
      pendingFailures.set(key, { expiresAt: expiry, result: failureResult });
      return reportFailure(failureResult);
    }
    payload = {
      caseId: result.caseId, caseRevision: result.caseRevision,
      requestId: result.requestId, execution: result.execution,
      modelId: result.modelId, answer: result.answer,
    };
    if (pendingReceipts.size >= 32) pendingReceipts.delete(pendingReceipts.keys().next().value!);
    pendingReceipts.set(key, { expiresAt: expiry, payload });
  }
  const receipt = await apiPost<Receipt>(
    `/investigations/${encodeURIComponent(caseId)}/slm/results`,
    "slm_advisory",
    payload,
  );
  if (!receipt.accepted || receipt.advisoryOnly !== true ||
      receipt.caseId !== caseId || receipt.requestId !== payload.requestId) {
    return { status: "invalid_output", reason: "invalid_server_receipt" };
  }
  await save({ status: "accepted", acceptedAt: new Date().toISOString() });
  pendingReceipts.delete(key);
  return { status: "accepted", requestId: payload.requestId };
}
