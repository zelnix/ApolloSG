import type { SLMRequest } from "./index.ts";
const text = { type: "string", maxLength: 3000 };
const list = (items: unknown, maxItems = 24) => ({ type: "array", items, maxItems });
const obj = (properties: Record<string, unknown>): { type: "object"; [key: string]: unknown } => ({ type: "object", properties, required: Object.keys(properties), additionalProperties: false });
const nullable = { anyOf: [text, { type: "null" }] };
export function outputSchema(r: SLMRequest) {
  const id = r.evidence.length ? { type: "string", enum: r.evidence.map(e => e.evidenceId) } : { type: "string" };
  const refs = list(id, r.evidence.length ? 32 : 0);
  const observation = obj({ text, evidenceIds: refs });
  if (r.operation === "grounded_chat") return obj({ answer: text, citations: list(id, r.evidence.length ? 6 : 0), quotations: list(obj({ passageId: id, text }), r.evidence.length ? 6 : 0), clarification: nullable, uncertainty: list(text, 8) });
  if (r.operation === "wright_semantic") return obj({ version: { const: "wright.semantic.v1" }, classification: { enum: ["scam_indicators", "legitimate_context", "ambiguous", "insufficient_evidence"] }, scamTypes: list({ type: "string", minLength: 1, maxLength: 60 }, 6), intent: { type: "string", minLength: 1, maxLength: 400 }, coercion: { enum: ["present", "absent", "uncertain"] }, exposure: obj(Object.fromEntries(["payment", "credentials", "identity", "remoteAccess"].map(k => [k, { enum: ["CONFIRMED", "NOT_CONFIRMED", "UNKNOWN"] }]))), narrative: { type: "string", minLength: 1, maxLength: 1200 }, uncertainty: { anyOf: [{ type: "string", maxLength: 600 }, { type: "null" }] }, supportingEvidenceIds: refs });
  const p: Record<string, unknown> = { observations: list(observation), contradictions: list(observation), alternativeExplanations: list(observation), verificationSuggestions: list(observation), draftExplanation: nullable };
  if (r.operation === "case_finding") p.caseFinding = obj({ outcome: { enum: ["scam", "likely_scam", "unlikely_scam", "not_scam"] }, explanation: text, reasons: list(observation, 12), uncertainty: nullable, advice: nullable });
  if (r.operation === "escalation_assessment") p.escalationAssessment = obj({ decision: { enum: ["proceed_local", "escalate", "additional_evidence_required"] }, rationale: text, evidenceIds: refs, materialGaps: list(text, 12) });
  return obj(p);
}
