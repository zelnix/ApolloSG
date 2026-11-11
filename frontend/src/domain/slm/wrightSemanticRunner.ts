/** On-device Wright semantic processing across source-linked evidence windows.
 * No cloud fallback, no cross-device references, no silent partial success.
 * Does not replace Phase 6 mandatory triage wiring or authoritative verdicts.
 */
import { runSLM, type SLMAdapter } from "./index.ts";
import { chunkWrightSources, type WrightSource, type WrightCoverage } from "./wrightEvidenceChunks.ts";
import type { WrightSemanticResult } from "./wrightSemanticContract.ts";

export type WrightSemanticRun =
  | { status: "complete"; coverage: WrightCoverage; interpretations: { evidenceId: string; parentEvidenceId: string; start: number; end: number; result: WrightSemanticResult }[] }
  | { status: "limited"; reason: string; coverage: WrightCoverage; examinedChunks: number };

export async function runWrightSemanticSources(sources: readonly WrightSource[], adapter: SLMAdapter | null): Promise<WrightSemanticRun> {
  let inventory: ReturnType<typeof chunkWrightSources>;
  try { inventory = chunkWrightSources(sources); }
  catch { return { status: "limited", reason: "invalid_source_inventory", coverage: { totalCharacters: 0, coveredCharacters: 0, complete: false, chunks: 0 }, examinedChunks: 0 }; }
  const interpretations: Extract<WrightSemanticRun, { status: "complete" }>["interpretations"] = [];
  if (!sources.length || inventory.chunks.length === 0)
    return { status: "limited", reason: "no_text_evidence", coverage: { ...inventory.coverage, complete: false, coveredCharacters: 0 }, examinedChunks: 0 };
  for (const chunk of inventory.chunks) {
    const run = await runSLM({
      role: "wright_triage", operation: "wright_semantic",
      question: "Interpret this source window only. Do not infer what occurred outside this window.",
      evidence: [{ evidenceId: chunk.evidenceId, text: chunk.text }],
    }, adapter);
    if (run.status !== "completed" || !run.answer.wrightSemantic) {
      return { status: "limited", reason: run.status === "completed" ? "missing_semantic_result" : run.reason,
        coverage: { ...inventory.coverage, complete: false,
          coveredCharacters: interpretations.length ? interpretations[interpretations.length - 1].end : 0 },
        examinedChunks: interpretations.length };
    }
    interpretations.push({ evidenceId: chunk.evidenceId, parentEvidenceId: chunk.parentEvidenceId,
      start: chunk.start, end: chunk.end, result: run.answer.wrightSemantic });
  }
  return { status: "complete", coverage: inventory.coverage, interpretations };
}
