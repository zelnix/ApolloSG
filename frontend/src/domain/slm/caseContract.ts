/**
 * Matching client envelope for ApolloSG's existing authenticated case/device
 * request workflow. This is a pure boundary, NOT a second API or submission
 * path. The backend decides when a request is valid and whether it can be used.
 */
import { runSLM, type SLMAdapter, type SLMRequest, type SLMRun } from "./index.ts";

export interface CaseSLMRequest extends SLMRequest {
  caseId: string;
  caseRevision: number;
  requestId: string;
}

export type CaseSLMResult =
  | { status: "completed"; caseId: string; caseRevision: number; requestId: string;
      execution: "on_device"; modelId: string; answer: Extract<SLMRun, { status: "completed" }>["answer"] }
  | { status: "unavailable" | "invalid_output"; reason: string };

const validId = (id: unknown) => typeof id === "string" && id.length >= 4 && id.length <= 80;
const validCase = (r: CaseSLMRequest) => validId(r.caseId) && validId(r.requestId) &&
  Number.isSafeInteger(r.caseRevision) && r.caseRevision >= 0;

/**
 * Evidence must be provided only by an authenticated case-scoped request.
 * Do not read other cases, fetch arbitrary evidence, persist a chat history or
 * return this result via an unvalidated or unrequested endpoint.
 */
export async function reasonForCase(
  request: CaseSLMRequest,
  adapter: SLMAdapter | null,
): Promise<CaseSLMResult> {
  if (!validCase(request)) {
    return { status: "invalid_output", reason: "invalid_case_request" };
  }
  const run = await runSLM(request, adapter);
  if (run.status !== "completed") {
    return { status: run.status, reason: run.reason };
  }
  return {
    status: "completed",
    caseId: request.caseId,
    caseRevision: request.caseRevision,
    requestId: request.requestId,
    execution: "on_device",
    modelId: run.modelId,
    answer: run.answer,
  };
}
