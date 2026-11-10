/**
 * Shared SLM boundary for Higgins Triage, TC Hawkeye, Magnum DI and Luddish.
 * This file deliberately contains no model runtime, server transport or Gemini routing.
 * A native model adapter must be supplied explicitly by the app. All responses are
 * advisory: investigation, scoring, Evidence Lock and user-visible verdicts stay in
 * their existing authoritative components.
 */
import { recordSuccessfulSLMInference } from "./sharedRuntime.ts";

export type SLMRole = "higgins_triage" | "tc_hawkeye" | "magnum_di" | "luddish" | "ask_higgins";
export type SLMOperation = "investigation_readiness" | "evidence_reasoning" | "explanation" | "chat_explanation" | "case_finding";

export interface SLMReference {
  /** Only references supplied to this invocation may be cited by the model. */
  evidenceId: string;
  text: string;
}

export interface SLMRequest {
  role: SLMRole;
  operation: SLMOperation;
  /** Case-scoped only: must never include evidence from other devices. */
  evidence: readonly SLMReference[];
  /** Case-scoped instructions; not a licence to change the authoritative verdict. */
  question: string;
}

export interface SLMObservation {
  /** Advisory hypothesis, never itself evidence or a verified finding. */
  text: string;
  /** References to evidence included in this request; empty means unsupported hypothesis. */
  evidenceIds: readonly string[];
}

export interface SLMCaseFinding {
  outcome: "scam" | "likely_scam" | "unlikely_scam" | "not_scam";
  explanation: string;
  reasons: readonly SLMObservation[];
  uncertainty: string | null;
  advice: string | null;
}

export interface SLMAnswer {
  observations: readonly SLMObservation[];
  contradictions: readonly SLMObservation[];
  alternativeExplanations: readonly SLMObservation[];
  verificationSuggestions: readonly SLMObservation[];
  /** Draft language only; existing Evidence Lock / fidelity checks must approve display. */
  draftExplanation: string | null;
  caseFinding?: SLMCaseFinding | null;
}

export interface SLMAdapter {
  readonly modelId: string;
  /** A native on-device model implementation, never Gemini or a silent network fallback. */
  infer(request: SLMRequest): Promise<unknown>;
}

export type SLMRun =
  | { status: "completed"; execution: "on_device"; modelId: string; answer: SLMAnswer }
  | { status: "unavailable" | "invalid_output"; execution: "none"; reason: string };

const ROLES: readonly SLMRole[] = ["higgins_triage", "tc_hawkeye", "magnum_di", "luddish", "ask_higgins"];
const OPERATIONS: readonly SLMOperation[] = ["investigation_readiness", "evidence_reasoning", "explanation", "chat_explanation", "case_finding"];
const MAX_EVIDENCE = 64;
const MAX_CHARS = 120_000;
const MAX_OBSERVATIONS = 24;
const MAX_TEXT = 3_000;

function validObservation(value: unknown, refs: Set<string>): value is SLMObservation {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const v = value as Record<string, unknown>;
  return typeof v.text === "string" && v.text.trim().length > 0 &&
    v.text.length <= MAX_TEXT && Array.isArray(v.evidenceIds) &&
    v.evidenceIds.every((id: unknown) => typeof id === "string" && refs.has(id));
}

function observations(value: unknown, refs: Set<string>): value is SLMObservation[] {
  return Array.isArray(value) && value.length <= MAX_OBSERVATIONS &&
    value.every((item) => validObservation(item, refs));
}

function validCaseFinding(value: unknown, refs: Set<string>): value is SLMCaseFinding {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const f = value as Record<string, unknown>;
  return ["scam", "likely_scam", "unlikely_scam", "not_scam"].includes(String(f.outcome)) &&
    typeof f.explanation === "string" && f.explanation.length > 0 && f.explanation.length <= MAX_TEXT &&
    observations(f.reasons, refs) && (f.reasons as unknown[]).length > 0 &&
    (f.reasons as unknown[]).length <= 12 &&
    (f.uncertainty === null || (typeof f.uncertainty === "string" && f.uncertainty.length <= 1500)) &&
    (f.advice === null || (typeof f.advice === "string" && f.advice.length <= 1500));
}

function validate(value: unknown, refs: Set<string>, operation: SLMOperation): SLMAnswer | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const a = value as Record<string, unknown>;
  // Unexpected fields (including a model-authored verdict or score) must not leak downstream.
  const permitted = new Set(["observations", "contradictions", "alternativeExplanations",
    "verificationSuggestions", "draftExplanation", "caseFinding"]);
  if (Object.keys(a).some((k) => !permitted.has(k))) return null;
  if (!observations(a.observations, refs) || !observations(a.contradictions, refs) ||
      !observations(a.alternativeExplanations, refs) ||
      !observations(a.verificationSuggestions, refs)) return null;
  if (a.draftExplanation !== null &&
      (typeof a.draftExplanation !== "string" || a.draftExplanation.length > MAX_TEXT)) return null;
  if (operation === "case_finding" && !validCaseFinding(a.caseFinding, refs)) return null;
  if (a.caseFinding != null && !validCaseFinding(a.caseFinding, refs)) return null;
  return {
    caseFinding: (a.caseFinding as SLMCaseFinding | null | undefined) ?? null,
    observations: a.observations, contradictions: a.contradictions,
    alternativeExplanations: a.alternativeExplanations,
    verificationSuggestions: a.verificationSuggestions, draftExplanation: a.draftExplanation,
  };
}

/**
 * Executes only an explicitly installed on-device adapter. No model chosen by
 * default; failures must be handled by the existing workflow, not by Gemini.
 * This boundary does not persist prompts, evidence or cross-device case data.
 */
export async function runSLM(request: SLMRequest, adapter: SLMAdapter | null): Promise<SLMRun> {
  if (!ROLES.includes(request.role) || !OPERATIONS.includes(request.operation) ||
      !Array.isArray(request.evidence) || request.evidence.length > MAX_EVIDENCE ||
      typeof request.question !== "string" || request.question.length > MAX_TEXT ||
      request.evidence.some((e) => !e || typeof e.evidenceId !== "string" ||
        !e.evidenceId || typeof e.text !== "string") ||
      request.evidence.reduce((sum, e) => sum + e.text.length, 0) > MAX_CHARS ||
      new Set(request.evidence.map((e) => e.evidenceId)).size !== request.evidence.length) {
    return { status: "invalid_output", execution: "none", reason: "invalid_request" };
  }
  if (!adapter) return { status: "unavailable", execution: "none", reason: "on_device_model_unavailable" };
  try {
    const candidate = await adapter.infer(request);
    const answer = validate(candidate, new Set(request.evidence.map((e) => e.evidenceId)), request.operation);
    if (!answer) return { status: "invalid_output", execution: "none", reason: "response_contract_failed" };
    recordSuccessfulSLMInference(adapter);
    return { status: "completed", execution: "on_device", modelId: adapter.modelId, answer };
  } catch {
    // Do not log private evidence or model responses.
    return { status: "unavailable", execution: "none", reason: "on_device_inference_failed" };
  }
}
