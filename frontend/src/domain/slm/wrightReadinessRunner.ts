/** Examine every source window for readability, preserving source IDs and gaps. */
import { runSLM, type SLMAdapter, type SLMReference } from "./index.ts";
import { chunkWrightSources, type WrightCoverage } from "./wrightEvidenceChunks.ts";
import { validateWrightReadiness, WRIGHT_WINDOW_QUESTION, type WrightReadinessResult } from "./wrightReadinessContract.ts";

export type WrightReadinessRun =
  | { status: "complete"; readiness: WrightReadinessResult; coverage: WrightCoverage; windows: number }
  | { status: "limited"; reason: string };

export async function runWrightReadinessSources(sources: readonly SLMReference[], adapter: SLMAdapter | null): Promise<WrightReadinessRun> {
  let inventory: ReturnType<typeof chunkWrightSources>;
  try { inventory = chunkWrightSources(sources); }
  catch { return { status: "limited", reason: "invalid_source_inventory" }; }
  if (!sources.length) return { status: "limited", reason: "no_source_evidence" };
  if (!adapter) return { status: "limited", reason: "on_device_model_unavailable" };
  const evidence: WrightReadinessResult["evidence"] = [];
  let windows = 0;
  for (const source of sources) {
    // Representation comes from the authenticated server evidence record,
    // never from words or JSON an adversary may have placed in source text.
    if (source.representation === "inventory_only") {
      evidence.push({ evidenceId: source.evidenceId, availability: "inventory_only" });
      continue;
    }
    if (!source.text.trim()) {
      evidence.push({ evidenceId: source.evidenceId, availability: "unreadable" });
      continue;
    }
    let readable = true;
    for (const chunk of inventory.chunks.filter(item => item.parentEvidenceId === source.evidenceId)) {
      const run = await runSLM({ role: "wright_triage", operation: "investigation_readiness",
        question: WRIGHT_WINDOW_QUESTION,
        evidence: [{ evidenceId: chunk.evidenceId, text: chunk.text, representation: source.representation }],
      }, adapter);
      if (run.status !== "completed" || !run.answer.wrightReadiness) {
        return { status: "limited", reason: run.status === "completed" ? "missing_wright_readiness" : run.reason };
      }
      const status = run.answer.wrightReadiness.evidence[0].availability;
      if (status === "inventory_only") return { status: "limited", reason: "invalid_readability_status" };
      readable = readable && status === "readable";
      windows++;
    }
    evidence.push({ evidenceId: source.evidenceId, availability: readable ? "readable" : "unreadable" });
  }
  // A metadata-only response cannot claim that native inference took place.
  if (!windows) return { status: "limited", reason: "no_readable_source_evidence" };
  const readiness = validateWrightReadiness({ version: "wright.readiness.v1", evidence }, sources);
  if (!readiness) return { status: "limited", reason: "readiness_contract_failed" };
  const totalCharacters = sources.filter(s => s.representation !== "inventory_only").reduce((n, s) => n + s.text.length, 0);
  return { status: "complete", readiness, coverage: { totalCharacters, coveredCharacters: totalCharacters, complete: true, chunks: windows }, windows };
}
