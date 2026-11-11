/** Mandatory Wright stage: all source windows are interpreted locally before one
 * case-scoped semantic result is submitted. No cloud or deterministic fallback.
 */
import { runWrightSemanticSources } from "./wrightSemanticRunner.ts";
import type { WrightSemanticResult } from "./wrightSemanticContract.ts";
import type { SLMAdapter, SLMReference } from "./index.ts";

export type WrightPhase6Result =
  | { status: "complete"; semantic: WrightSemanticResult; windows: number }
  | { status: "limited"; reason: string };

export async function assessMandatoryWright(
  evidence: readonly SLMReference[], adapter: SLMAdapter | null,
): Promise<WrightPhase6Result> {
  if (!evidence.length) return { status: "limited", reason: "no_source_evidence" };
  const run = await runWrightSemanticSources(
    evidence.map(e => ({ evidenceId: e.evidenceId, text: e.text })), adapter);
  if (run.status !== "complete" || !run.coverage.complete)
    return { status: "limited", reason: run.status === "limited" ? run.reason : "incomplete_coverage" };
  const refs = [...new Set(run.interpretations.flatMap(i =>
    i.result.supportingEvidenceIds.length ? [i.parentEvidenceId] : []))];
  const labels = run.synthesis.classifications;
  const classification: WrightSemanticResult["classification"] =
    run.synthesis.contradictory ? "ambiguous" :
    labels.length === 1 ? labels[0] as WrightSemanticResult["classification"] : "ambiguous";
  const exposureFields = ["payment", "credentials", "identity", "remoteAccess"] as const;
  const exposure = {} as WrightSemanticResult["exposure"];
  for (const field of exposureFields) {
    const states = new Set(run.interpretations.map(i => i.result.exposure[field]));
    exposure[field] = states.size === 1 ? [...states][0] : "UNKNOWN";
  }
  const coercions = new Set(run.interpretations.map(i => i.result.coercion));
  const coercion = coercions.size === 1 ? [...coercions][0] : "uncertain";
  const scamTypes = [...new Set(run.interpretations.flatMap(i => i.result.scamTypes))].slice(0, 6);
  const uncertainty = (run.synthesis.contradictory
    ? "Conflicting legitimate and scam indicators across windows; further verification required."
    : run.synthesis.uncertainties.join("; ") || "Context outside each window may be incomplete.").slice(0, 600);
  const semantic: WrightSemanticResult = {
    version: "wright.semantic.v1", classification, scamTypes,
    intent: "Combined interpretation of all submitted source windows.",
    coercion, exposure,
    narrative: `Examined ${run.interpretations.length} source windows. Classifications: ${labels.join(", ")}.`,
    uncertainty, supportingEvidenceIds: refs,
  };
  // Any positive assertion must have at least one source citation.
  if ((classification === "scam_indicators" || classification === "legitimate_context" ||
      coercion === "present" || Object.values(exposure).includes("CONFIRMED")) && !refs.length)
    return { status: "limited", reason: "missing_source_citations" };
  return { status: "complete", semantic, windows: run.interpretations.length };
}
