/**
 * Runs the model comparison (benchmark.ts) on whichever model is active now, and keeps each model's latest score on
 * the phone, so a tester can download Qwen 0.5B, run it, swap to Llama 1B, run it, and compare.
 * The cases are made-up messages; nothing the person has received is used, and nothing is sent anywhere.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

import { EXPLAIN_CASES, PRE_SCREEN_CASES, scorePreScreen, summarise, type BenchmarkSummary } from "./benchmark.ts";
import { EXPLAIN_INSTRUCTIONS, PRE_SCREEN_INSTRUCTIONS, explainPrompt, preScreenPrompt, prepareSlmInput, slmModelLabel } from "./core.ts";
import { generateRaw } from "./onDeviceSlm.ts";

const KEY = "apollo.slm.benchmarks.v1";

export interface StoredBenchmark extends BenchmarkSummary { at: string }

export async function savedBenchmarks(): Promise<StoredBenchmark[]> {
  try { const raw = await AsyncStorage.getItem(KEY); return raw ? (JSON.parse(raw) as StoredBenchmark[]) : []; } catch { return []; }
}

/** Runs every case once, one after another. onStep reports progress as (done, total). */
export async function runBenchmark(onStep: (done: number, total: number) => void): Promise<StoredBenchmark | { error: string }> {
  const total = PRE_SCREEN_CASES.length + EXPLAIN_CASES.length;
  let done = 0;
  let modelLabel: string | null = null;
  const timings: number[] = [];
  const pre = [];
  for (const c of PRE_SCREEN_CASES) {
    const r = await generateRaw("benchmark", PRE_SCREEN_INSTRUCTIONS, preScreenPrompt(prepareSlmInput(c.text)), 320, { json: true, record: false, requireEnabled: false });
    if (r.ok) { modelLabel ??= slmModelLabel(r.model); timings.push(r.elapsedMs); }
    else if (r.reason.startsWith("not_ready")) return { error: "No on-device model is ready on this phone." };
    pre.push(scorePreScreen(c, r.ok ? r.text : null));
    onStep(++done, total);
  }
  const explain = [];
  for (const c of EXPLAIN_CASES) {
    const r = await generateRaw("benchmark", EXPLAIN_INSTRUCTIONS, explainPrompt(c.settled), 200, { json: false, record: false, requireEnabled: false });
    if (r.ok) { modelLabel ??= slmModelLabel(r.model); timings.push(r.elapsedMs); }
    explain.push({ raw: r.ok ? r.text : null, settled: c.settled });
    onStep(++done, total);
  }
  const result: StoredBenchmark = { ...summarise(modelLabel ?? "Unknown model", pre, explain, timings), at: new Date().toISOString() };
  const others = (await savedBenchmarks()).filter((b) => b.model !== result.model);
  try { await AsyncStorage.setItem(KEY, JSON.stringify([result, ...others].slice(0, 10))); } catch { /* the score is still shown */ }
  return result;
}
