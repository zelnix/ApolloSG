/**
 * Model comparison: the same fixed cases for every on-device model, scored by the same checks the app applies.
 *
 * Every message here is made up for testing; none is a real person's message. A model is scored on:
 *  - pre-screen: which request kinds survive the verbatim/negation checks, against the kinds each case really holds
 *    (precision = found and real / found; recall = found and real / real);
 *  - explain: how many re-wordings pass checkExplanation;
 *  - speed: median milliseconds per call.
 * Pure, so the scoring is tested under `node --test`; the runner that calls a model is in benchmarkRunner.ts.
 */
import { advisoryFor, checkExplanation, parsePreScreen, prepareSlmInput, type SettledResult, type SlmRequestKind } from "./core.ts";

export interface PreScreenCase { id: string; text: string; expected: SlmRequestKind[] }
export interface ExplainCase { id: string; settled: SettledResult }

export const PRE_SCREEN_CASES: readonly PreScreenCase[] = [
  { id: "bank-code", text: "CommBank: We noticed a new device. To keep your account open, reply with the 6-digit code we just sent you.", expected: ["share_code", "call_or_reply"] },
  { id: "toll-pay", text: "Linkt: You have an unpaid toll of $4.20. Pay now at linkt-pay-au.com to avoid a $90 fine.", expected: ["send_money"] },
  { id: "family", text: "Hi Mum, I broke my phone, this is my new number. Can you transfer $850 to my friend for rent today? I'll pay you back.", expected: ["send_money"] },
  { id: "remote", text: "Microsoft Support: your computer is infected. Install AnyDesk and give us the access number so we can fix it.", expected: ["install_app", "remote_access"] },
  { id: "negated", text: "CommBank will never ask you to share a code or your password. Your new statement is ready in the app.", expected: [] },
  { id: "ordinary", text: "Dinner is at 7 at Mia's place. Bring the salad if you can. See you then!", expected: [] },
];

export const EXPLAIN_CASES: readonly ExplainCase[] = [
  { id: "growling", settled: { stateName: "Growling", verdict: "This message asks for a code and uses a link that isn't CommBank's.", why: ["Asks for a code", "Link isn't the bank's own"], recommendation: "Don't reply or tap the link. Call CommBank on the number on your card." } },
  { id: "barking", settled: { stateName: "Barking", verdict: "This matches a known toll scam: an unpaid-toll message with a link that isn't Linkt's.", why: ["Known toll scam pattern", "Payment link isn't Linkt's own"], recommendation: "Don't pay through the link. Check your account in the Linkt app." } },
  { id: "unable", settled: { stateName: "Sniffing", verdict: "Apollo couldn't settle this message from what it could check.", why: ["The sender couldn't be confirmed"], recommendation: "If it asks you to do anything, check with the sender using contact details you already have." } },
];

export interface CaseScore { id: string; found: SlmRequestKind[]; truePositives: number; falsePositives: number; missed: number; dropped: number; ok: boolean }

export function scorePreScreen(c: PreScreenCase, raw: string | null): CaseScore {
  if (raw == null) return { id: c.id, found: [], truePositives: 0, falsePositives: 0, missed: c.expected.length, dropped: 0, ok: false };
  const prepared = prepareSlmInput(c.text);
  const pre = parsePreScreen(raw, prepared);
  // Score what the app would act on: verified request kinds (advisoryFor with no fixed signals keeps them all).
  const found = [...new Set(advisoryFor(pre, {}).extra.flatMap((h) => (h.type === "request" ? [h.kind] : [])))];
  const tp = found.filter((k) => c.expected.includes(k)).length;
  return { id: c.id, found, truePositives: tp, falsePositives: found.length - tp, missed: c.expected.filter((k) => !found.includes(k)).length, dropped: pre.dropped, ok: true };
}

export interface BenchmarkSummary {
  model: string;
  precision: number | null;
  recall: number | null;
  explanationsAccepted: number;
  explanationsTotal: number;
  failedCalls: number;
  medianMs: number | null;
  rejections: Record<string, number>;
}

export function summarise(model: string, pre: CaseScore[], explain: Array<{ raw: string | null; settled: SettledResult }>, timingsMs: number[]): BenchmarkSummary {
  const tp = pre.reduce((n, s) => n + s.truePositives, 0);
  const fp = pre.reduce((n, s) => n + s.falsePositives, 0);
  const fn = pre.reduce((n, s) => n + s.missed, 0);
  const rejections: Record<string, number> = {};
  let accepted = 0;
  for (const e of explain) {
    if (e.raw == null) continue;
    const r = checkExplanation(e.raw, e.settled);
    if (r.ok) accepted++; else rejections[r.reason] = (rejections[r.reason] ?? 0) + 1;
  }
  const sorted = [...timingsMs].sort((a, b) => a - b);
  return {
    model,
    precision: tp + fp ? tp / (tp + fp) : null,
    recall: tp + fn ? tp / (tp + fn) : null,
    explanationsAccepted: accepted,
    explanationsTotal: explain.length,
    failedCalls: pre.filter((s) => !s.ok).length + explain.filter((e) => e.raw == null).length,
    medianMs: sorted.length ? sorted[Math.floor(sorted.length / 2)] : null,
    rejections,
  };
}

const pct = (n: number | null) => (n == null ? "–" : `${Math.round(n * 100)}%`);

export function summaryLine(s: BenchmarkSummary): string {
  return `Finds requests ${pct(s.recall)} · correct ${pct(s.precision)} · explanations ${s.explanationsAccepted}/${s.explanationsTotal} · ${s.medianMs == null ? "–" : `${(s.medianMs / 1000).toFixed(1)} s`} per call${s.failedCalls ? ` · ${s.failedCalls} failed` : ""}`;
}
