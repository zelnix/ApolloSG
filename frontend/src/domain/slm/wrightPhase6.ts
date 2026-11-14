/** Required on-device evidence-readiness stage. Wright never assesses scam merit. */
import { runWrightReadinessSources } from "./wrightReadinessRunner.ts";
import type { WrightReadinessResult } from "./wrightReadinessContract.ts";
import type { SLMAdapter, SLMReference } from "./index.ts";

export type WrightPhase6Result =
  | { status: "complete"; readiness: WrightReadinessResult; windows: number }
  | { status: "limited"; reason: string };

export async function assessMandatoryWright(evidence: readonly SLMReference[], adapter: SLMAdapter | null): Promise<WrightPhase6Result> {
  const run = await runWrightReadinessSources(evidence, adapter);
  if (run.status !== "complete") return run;
  return { status: "complete", readiness: run.readiness, windows: run.windows };
}

/** Uses only the existing authenticated case/revision/request handoff. */
export async function respondToWrightStage(
  request: { caseId: string; caseRevision: number; requestId: string;
    role: string; operation: string; evidence: readonly SLMReference[] },
  adapter: SLMAdapter | null,
): Promise<{ status: "ready"; payload: Record<string, unknown> } | { status: "limited"; reason: string }> {
  if (request.role !== "wright_triage" || request.operation !== "investigation_readiness")
    return { status: "limited", reason: "wrong_stage" };
  const assessment = await assessMandatoryWright(request.evidence, adapter);
  if (assessment.status !== "complete") return assessment;
  return { status: "ready", payload: {
    caseId: request.caseId, caseRevision: request.caseRevision, requestId: request.requestId,
    execution: "on_device", modelId: adapter!.modelId,
    answer: { observations: [], contradictions: [], alternativeExplanations: [],
      verificationSuggestions: [], draftExplanation: null, wrightReadiness: assessment.readiness },
  } };
}
