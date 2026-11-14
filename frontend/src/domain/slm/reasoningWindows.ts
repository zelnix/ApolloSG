/** Read all source windows before bounded escalation/Finding synthesis.
 * Notes remain explicitly unverified model interpretations, never stored evidence.
 * If the complete set cannot fit, stop honestly instead of dropping notes/sources.
 */
import { runSLM, type SLMAdapter, type SLMReference, type SLMRequest, type SLMRun } from "./index.ts";
import { chunkWrightSources } from "./wrightEvidenceChunks.ts";

export async function reasonAcrossWindows(request: SLMRequest, adapter: SLMAdapter): Promise<SLMRun> {
  const { chunks } = chunkWrightSources(request.evidence, 1200, 120);
  let completed = 0;
  request.onProgress?.(0, chunks.length + 1);
  const notes = new Map<string, unknown[]>();
  for (const chunk of chunks) {
    const windowRequest: SLMRequest = {
      deadlineAt: request.deadlineAt, signal: request.signal,
      role: request.role, operation: "evidence_reasoning",
      question: "Read this source window only. Retain observations, contradictions, alternative explanations and missing evidence with citations. Never issue an outcome. These are unverified interpretations for a later case-wide assessment.",
      evidence: [{ evidenceId: chunk.evidenceId, text: chunk.text }],
    };
    if (adapter.canFitAsync ? !await adapter.canFitAsync(windowRequest) : adapter.canFit && !adapter.canFit(windowRequest))
      return { status: "unavailable", execution: "none", reason: "source_window_context_exceeded" };
    const run = await runSLM(windowRequest, adapter);
    if (run.status !== "completed") return run;
    const groups = ["observations", "contradictions", "alternativeExplanations", "verificationSuggestions"] as const;
    if (groups.some(group => run.answer[group].some(note => !note.evidenceIds.length)))
      return { status: "invalid_output", execution: "none", reason: "uncited_window_interpretation" };
    const row = {
      start: chunk.start, end: chunk.end, originalCharacters: request.evidence.find(e => e.evidenceId === chunk.parentEvidenceId)!.text.length,
      ...Object.fromEntries(groups.map(group => [group, run.answer[group].map(note => ({ text: note.text, evidenceIds: [chunk.parentEvidenceId] }))])),
    };
    const existing = notes.get(chunk.parentEvidenceId) ?? [];
    existing.push(row); notes.set(chunk.parentEvidenceId, existing);
    request.onProgress?.(++completed, chunks.length + 1);
  }
  const evidence: SLMReference[] = [...notes].map(([evidenceId, windows]) => ({
    evidenceId, text: JSON.stringify({ representation: "unverified_local_interpretations_not_source_facts", allSourceWindowsProcessed: true, windows }),
  }));
  const synthesis = { ...request, evidence };
  if (adapter.canFitAsync ? !await adapter.canFitAsync(synthesis) : !adapter.canFit || !adapter.canFit(synthesis))
    return { status: "unavailable", execution: "none", reason: "complete_window_synthesis_context_exceeded" };
  const final = await runSLM(synthesis, adapter);
  if (final.status === "completed") request.onProgress?.(chunks.length + 1, chunks.length + 1);
  return final;
}
