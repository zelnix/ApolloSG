/** Legacy Wright semantic decoder, retained for historical fixtures only.
 * Pure validation only. No verdict authority, network access, persistence or model invocation.
 * Phase 6 will connect this to mandatory initial triage after native qualification.
 */
export const WRIGHT_SEMANTIC_VERSION = "wright.semantic.v1" as const;
export type Exposure = "CONFIRMED" | "NOT_CONFIRMED" | "UNKNOWN";
export type SemanticClass = "scam_indicators" | "legitimate_context" | "ambiguous" | "insufficient_evidence";
export interface WrightSemanticResult {
  version: typeof WRIGHT_SEMANTIC_VERSION;
  classification: SemanticClass;
  scamTypes: string[];
  intent: string;
  coercion: "present" | "absent" | "uncertain";
  exposure: { payment: Exposure; credentials: Exposure; identity: Exposure; remoteAccess: Exposure };
  narrative: string;
  uncertainty: string | null;
  supportingEvidenceIds: string[];
}
const own = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const keys = (v: Record<string, unknown>, allowed: string[]) =>
  Object.keys(v).length === allowed.length && Object.keys(v).every(k => allowed.includes(k));
const exposure = (v: unknown): v is Exposure =>
  v === "CONFIRMED" || v === "NOT_CONFIRMED" || v === "UNKNOWN";
const text = (v: unknown, max: number) => typeof v === "string" && v.trim().length > 0 && v.length <= max;

/** Fail closed on unexpected fields, unsupported citations, invented identifiers and certainty. */
export function validateWrightSemantic(value: unknown, allowedEvidenceIds: readonly string[]): WrightSemanticResult | null {
  if (!own(value) || !keys(value, ["version", "classification", "scamTypes", "intent", "coercion", "exposure", "narrative", "uncertainty", "supportingEvidenceIds"])) return null;
  if (value.version !== WRIGHT_SEMANTIC_VERSION ||
      !["scam_indicators", "legitimate_context", "ambiguous", "insufficient_evidence"].includes(String(value.classification)) ||
      !["present", "absent", "uncertain"].includes(String(value.coercion)) ||
      !text(value.intent, 400) || !text(value.narrative, 1200) ||
      !(value.uncertainty === null || (typeof value.uncertainty === "string" && value.uncertainty.length <= 600))) return null;
  if (!Array.isArray(value.scamTypes) || value.scamTypes.length > 6 ||
      !value.scamTypes.every(t => text(t, 60)) || new Set(value.scamTypes).size !== value.scamTypes.length) return null;
  if (!own(value.exposure) || !keys(value.exposure, ["payment", "credentials", "identity", "remoteAccess"]) ||
      !Object.values(value.exposure).every(exposure)) return null;
  const refs = value.supportingEvidenceIds;
  const permitted = new Set(allowedEvidenceIds);
  if (!Array.isArray(refs) || refs.length > 32 || new Set(refs).size !== refs.length ||
      !refs.every(id => typeof id === "string" && permitted.has(id))) return null;
  // Semantic interpretations with positive or negative confidence must cite their basis.
  if ((value.classification === "scam_indicators" || value.classification === "legitimate_context" ||
       value.coercion === "present" || Object.values(value.exposure).includes("CONFIRMED")) && refs.length === 0) return null;
  return value as unknown as WrightSemanticResult;
}
