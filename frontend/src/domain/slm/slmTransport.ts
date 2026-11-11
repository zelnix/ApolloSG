/**
 * Authenticated handoff for mandatory on-device SLM investigation stages.
 * The server issues the exact case request; the device returns its result.
 * No cloud-model substitution, cross-case evidence reuse, or invented verdict.
 */
import { apiPost } from "../../api/client.ts";
import { reasonForCase, type CaseSLMRequest } from "./caseContract.ts";
import type { SLMAdapter, SLMRole } from "./index.ts";

export interface Issued {
  request: CaseSLMRequest;
  expiresAt: string;
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

export async function submitIssuedAdvisory(
  caseId: string,
  issued: Issued,
  adapter: SLMAdapter | null,
): Promise<HandoffResult> {
  if (!adapter) return { status: "unavailable", reason: "on_device_model_unavailable" };
  const caseRevision = issued.request.caseRevision;
  const role = issued.request.role;
  if (issued.request.caseId !== caseId || issued.request.caseRevision !== caseRevision ||
      !issued.request.requestId || issued.request.role !== role ||
new Date(issued.expiresAt).getTime() <= Date.now()) {
    return { status: "invalid_output", reason: "invalid_server_request" };
  }
  const expiry = Date.parse(issued.expiresAt);
  const key = JSON.stringify([caseId, caseRevision, issued.request.requestId, adapter.modelId]);
  for (const [id, entry] of pendingReceipts) {
    if (entry.expiresAt <= Date.now()) pendingReceipts.delete(id);
  }
  let payload = pendingReceipts.get(key)?.payload;
  if (!payload) {
    const result = await reasonForCase(issued.request, adapter);
    if (result.status !== "completed") {
      // No fabricated success and no automatic Gemini fallback.
      return { status: result.status, reason: result.reason };
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
  pendingReceipts.delete(key);
  return { status: "accepted", requestId: payload.requestId };
}
