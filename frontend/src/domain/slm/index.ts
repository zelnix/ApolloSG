/**
 * Shared SLM boundary for Wright Triage, TC Hawkeye, Magnum DI and Luddish.
 * This file deliberately contains no model runtime, server transport or Gemini routing.
 * A native model adapter must be supplied explicitly by the app. All responses are
 * advisory: investigation, scoring, Evidence Lock and user-visible verdicts stay in
 * their existing authoritative components.
 */
import { validateWrightSemantic, type WrightSemanticResult } from "./wrightSemanticContract.ts";
import { recordSuccessfulSLMInference } from "./sharedRuntime.ts";

export type SLMRole = "wright_triage" | "higgins_triage" | "tc_hawkeye" | "magnum_di" | "luddish" | "ask_higgins" | "case_finding" | "higgins_escalation_assessment";
export type SLMOperation = "wright_semantic" | "investigation_readiness" | "evidence_reasoning" | "explanation" | "chat_explanation" | "case_finding" | "escalation_assessment";

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

export interface SLMEscalationAssessment {
  decision: "proceed_local" | "escalate" | "additional_evidence_required";
  rationale: string;
  evidenceIds: readonly string[];
  materialGaps: readonly string[];
}

export interface SLMAnswer {
  observations: readonly SLMObservation[];
  contradictions: readonly SLMObservation[];
  alternativeExplanations: readonly SLMObservation[];
  verificationSuggestions: readonly SLMObservation[];
  /** Draft language only; existing Evidence Lock / fidelity checks must approve display. */
  draftExplanation: string | null;
  caseFinding?: SLMCaseFinding | null;
  escalationAssessment?: SLMEscalationAssessment | null;
  wrightSemantic?: WrightSemanticResult;
}

export interface SLMAdapter {
  canFit?(request: SLMRequest): boolean;
  readonly modelId: string;
  /** A native on-device model implementation, never Gemini or a silent network fallback. */
  infer(request: SLMRequest): Promise<unknown>;
}

export type SLMRun =
  | { status: "completed"; execution: "on_device"; modelId: string; answer: SLMAnswer }
  | { status: "unavailable" | "invalid_output"; execution: "none"; reason: string };

const ROLES: readonly SLMRole[] = ["wright_triage", "higgins_triage", "tc_hawkeye", "magnum_di", "luddish", "ask_higgins", "case_finding", "higgins_escalation_assessment"];
const OPERATIONS: readonly SLMOperation[] = ["wright_semantic", "investigation_readiness", "evidence_reasoning", "explanation", "chat_explanation", "case_finding", "escalation_assessment"];
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

function validEscalation(value: unknown, refs: Set<string>): value is SLMEscalationAssessment {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const a = value as Record<string, unknown>;
  return ["proceed_local", "escalate", "additional_evidence_required"].includes(String(a.decision)) &&
    typeof a.rationale === "string" && a.rationale.trim().length > 0 && a.rationale.length <= MAX_TEXT &&
    Array.isArray(a.evidenceIds) && a.evidenceIds.length > 0 && a.evidenceIds.length <= MAX_EVIDENCE &&
    a.evidenceIds.every((id: unknown) => typeof id === "string" && refs.has(id)) &&
    Array.isArray(a.materialGaps) && a.materialGaps.length <= 12 &&
    a.materialGaps.every((gap: unknown) => typeof gap === "string" && gap.length > 0 && gap.length <= 1500) &&
    (a.decision !== "proceed_local" || a.materialGaps.length === 0);
}

function validate(value: unknown, refs: Set<string>, operation: SLMOperation): SLMAnswer | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  if (operation === "wright_semantic") {
    const semantic = validateWrightSemantic(value, [...refs]);
    return semantic ? { observations: [], contradictions: [], alternativeExplanations: [], verificationSuggestions: [], draftExplanation: null, wrightSemantic: semantic } : null;
  }
  const a = value as Record<string, unknown>;
  // Unexpected fields (including a model-authored verdict or score) must not leak downstream.
  if ((operation !== "case_finding" && a.caseFinding != null) ||
      (operation !== "escalation_assessment" && a.escalationAssessment != null)) return null;
  const permitted = new Set(["observations", "contradictions", "alternativeExplanations",
    "verificationSuggestions", "draftExplanation", "caseFinding", "escalationAssessment"]);
  if (Object.keys(a).some((k) => !permitted.has(k))) return null;
  if (!observations(a.observations, refs) || !observations(a.contradictions, refs) ||
      !observations(a.alternativeExplanations, refs) ||
      !observations(a.verificationSuggestions, refs)) return null;
  if (a.draftExplanation !== null &&
      (typeof a.draftExplanation !== "string" || a.draftExplanation.length > MAX_TEXT)) return null;
  if (operation === "escalation_assessment" && !validEscalation(a.escalationAssessment, refs)) return null;
  if (a.escalationAssessment != null && !validEscalation(a.escalationAssessment, refs)) return null;
  if (operation === "case_finding" && !validCaseFinding(a.caseFinding, refs)) return null;
  if (a.caseFinding != null && !validCaseFinding(a.caseFinding, refs)) return null;
  return {
    ...(a.caseFinding != null ? { caseFinding: a.caseFinding as SLMCaseFinding } : {}),
    ...(a.escalationAssessment != null ? { escalationAssessment: a.escalationAssessment as SLMEscalationAssessment } : {}),
    observations: a.observations, contradictions: a.contradictions,
    alternativeExplanations: a.alternativeExplanations,
    verificationSuggestions: a.verificationSuggestions, draftExplanation: a.draftExplanation,
  };
}

/** Privacy-safe contract diagnostics: field names and error classes only, never model text. */
function contractFailure(value: unknown, refs: Set<string>, operation: SLMOperation): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "not_object";
  if (operation === "wright_semantic") return "wright_semantic_contract_failed";
  const a = value as Record<string, unknown>;
  const allowed = new Set(["observations", "contradictions", "alternativeExplanations", "verificationSuggestions", "draftExplanation", "caseFinding", "escalationAssessment"]);
  if (Object.keys(a).some(k => !allowed.has(k))) return "unexpected_field";
  for (const field of ["observations", "contradictions", "alternativeExplanations", "verificationSuggestions"] as const) {
    if (!Array.isArray(a[field])) return field + "_missing_or_not_array";
    if (!observations(a[field], refs)) return field + "_invalid_or_reference";
  }
  if (a.draftExplanation !== null && (typeof a.draftExplanation !== "string" || a.draftExplanation.length > MAX_TEXT))
    return "draft_explanation_invalid";
  if (operation === "case_finding" && !validCaseFinding(a.caseFinding, refs)) {
    const f = a.caseFinding as Record<string, unknown> | null | undefined;
    if (!f || typeof f !== "object" || Array.isArray(f)) return "case_finding_missing";
    if (!["scam", "likely_scam", "unlikely_scam", "not_scam"].includes(String(f.outcome))) return "case_finding_outcome_invalid";
    if (typeof f.explanation !== "string" || !f.explanation.length || f.explanation.length > MAX_TEXT) return "case_finding_explanation_invalid";
    if (!observations(f.reasons, refs) || !Array.isArray(f.reasons) || f.reasons.length === 0 || f.reasons.length > 12) return "case_finding_reasons_invalid_or_reference";
    return "case_finding_optional_fields_invalid";
  }
  if (operation === "escalation_assessment" && !validEscalation(a.escalationAssessment, refs)) return "escalation_assessment_invalid";
  if (a.caseFinding != null && !validCaseFinding(a.caseFinding, refs)) return "case_finding_invalid";
  if (a.escalationAssessment != null && !validEscalation(a.escalationAssessment, refs)) return "escalation_assessment_invalid";
  return "unknown_contract_failure";
}

/**
 * Executes only an explicitly installed on-device adapter. No model chosen by
 * default; failures must be handled by the existing workflow, not by Gemini.
 * This boundary does not persist prompts, evidence or cross-device case data.
 */
export async function runSLM(request: SLMRequest, adapter: SLMAdapter | null): Promise<SLMRun> {
  if (!ROLES.includes(request.role) || !OPERATIONS.includes(request.operation) ||
      (request.operation === "wright_semantic" && request.role !== "wright_triage") ||
      !Array.isArray(request.evidence) || request.evidence.length > MAX_EVIDENCE ||
      typeof request.question !== "string" || request.question.length > MAX_TEXT ||
      request.evidence.some((e) => !e || typeof e.evidenceId !== "string" ||
        !e.evidenceId || typeof e.text !== "string") ||
      request.evidence.reduce((sum, e) => sum + e.text.length, 0) > MAX_CHARS ||
      new Set(request.evidence.map((e) => e.evidenceId)).size !== request.evidence.length) {
    return { status: "invalid_output", execution: "none", reason: "invalid_request" };
  }
  if (!adapter) return { status: "unavailable", execution: "none", reason: "on_device_model_unavailable" };
  if ((request.operation === "case_finding" || request.operation === "escalation_assessment") &&
      adapter.canFit && !adapter.canFit(request)) {
    const { reasonAcrossWindows } = await import("./reasoningWindows.ts");
    return reasonAcrossWindows(request, adapter);
  }
  // Server-issued Wright stage must examine every bounded source window. Internal
  // window requests use the exact marker below to avoid recursive dispatch.
  if (request.operation === "wright_semantic" &&
      request.question !== "Interpret this source window only. Do not infer what occurred outside this window.") {
    const { assessMandatoryWright } = await import("./wrightPhase6.ts");
    const assessment = await assessMandatoryWright(request.evidence, adapter);
    if (assessment.status !== "complete")
      return { status: "unavailable", execution: "none", reason: assessment.reason };
    return { status: "completed", execution: "on_device", modelId: adapter.modelId,
      answer: { observations: [], contradictions: [], alternativeExplanations: [],
        verificationSuggestions: [], draftExplanation: null, wrightSemantic: assessment.semantic } };
  }
  try {
    const candidate = await adapter.infer(request);
    const answer = validate(candidate, new Set(request.evidence.map((e) => e.evidenceId)), request.operation);
    if (!answer) return { status: "invalid_output", execution: "none", reason: "response_contract_failed:" + contractFailure(candidate, new Set(request.evidence.map(e => e.evidenceId)), request.operation) };
    recordSuccessfulSLMInference(adapter);
    return { status: "completed", execution: "on_device", modelId: adapter.modelId, answer };
  } catch (error: unknown) {
    // Only the explicit safe stage/code is returned. Never expose native messages,
    // stack traces, filesystem paths, prompts or evidence in diagnostics.
    const { LocalInferenceError } = await import("./llamaRnRuntime.ts");
    const reason = error instanceof LocalInferenceError
      ? `on_device_inference_failed:${error.stage}:${error.code}`
      : "on_device_inference_failed:unknown:unclassified_exception";
    return { status: "unavailable", execution: "none", reason };
  }
}
