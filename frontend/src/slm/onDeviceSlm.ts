/**
 * On-device SLM runtime: the only code that calls modules/apollo-slm. The rules live in ./core.ts.
 *
 * Off until the person turns it on (Settings → App → On-device AI). Even when on, it runs only if the phone's own
 * model is ready; nothing is downloaded or sent anywhere by ApolloSG. Each call is single-shot with a timeout; a
 * failure returns { ok: false, reason } and the caller keeps showing Apollo's fixed result as it is.
 *
 * Which model answers: the phone's built-in one (Gemini Nano / Apple) when it's ready; otherwise the model ApolloSG
 * downloaded at the person's request (fallbackModel.ts, llama.cpp); otherwise none, and nothing extra is shown.
 *
 * Every call records which one answered (engine, Gemini Nano version or
 * iOS version), how long it took and the outcome, in a local log on the phone. The log never holds message text,
 * prompts or answers, and is not sent anywhere.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { ApolloSlm, type SlmNativeStatus } from "@/modules/apollo-slm";

import { installedFallback } from "./fallbackModel.ts";

import {
  EXPLAIN_INSTRUCTIONS, PRE_SCREEN_INSTRUCTIONS, SLM_FALLBACK_TIMEOUT_MS, SLM_TIMEOUT_MS,
  advisoryFor, appendCallRecord, checkExplanation, explainPrompt, parsePreScreen, preScreenPrompt, prepareSlmInput,
  slmModelLabel,
  type FixedSignalsView, type SettledResult, type SlmAdvisory, type SlmCallRecord, type SlmModelInfo, type SlmPurpose,
} from "./core.ts";

const ENABLED_KEY = "apollo.slm.enabled.v1";
const CALL_LOG_KEY = "apollo.slm.calls.v1";

export type SlmOutcome<T> = { ok: true; value: T; model: SlmModelInfo } | { ok: false; reason: string };

export async function isSlmEnabled(): Promise<boolean> {
  try { return (await AsyncStorage.getItem(ENABLED_KEY)) === "on"; } catch { return false; }
}

export async function setSlmEnabled(on: boolean): Promise<void> {
  await AsyncStorage.setItem(ENABLED_KEY, on ? "on" : "off");
}

export async function getSlmStatus(): Promise<SlmNativeStatus> {
  try { return await ApolloSlm.getStatus(); }
  catch { return { availability: "unavailable", engine: "none", reason: "status_unreadable", modelName: null, osVersion: null, observedAt: new Date().toISOString() }; }
}

export async function requestSlmDownload(): Promise<SlmNativeStatus> {
  try { return await ApolloSlm.requestDownload(); }
  catch { return getSlmStatus(); }
}

/** The phone's local record of on-device calls, newest first. */
export async function getSlmCallLog(): Promise<SlmCallRecord[]> {
  try { const raw = await AsyncStorage.getItem(CALL_LOG_KEY); return raw ? (JSON.parse(raw) as SlmCallRecord[]) : []; } catch { return []; }
}

async function record(rec: SlmCallRecord): Promise<void> {
  try { await AsyncStorage.setItem(CALL_LOG_KEY, JSON.stringify(appendCallRecord(await getSlmCallLog(), rec))); } catch { /* a lost record never blocks the result */ }
}

/** What the Settings row says about the phone's model, including which version it is. */
export function slmStatusLine(s: SlmNativeStatus, fallbackLabel?: string | null): string {
  if (s.availability !== "available" && fallbackLabel) return `Ready — ${fallbackLabel} (downloaded by ApolloSG)`;
  switch (s.availability) {
    case "available": return `Ready — ${slmModelLabel(s)}`;
    case "downloading": return "The phone is still getting its model ready";
    case "downloadable": return "The phone can download its model (Wi-Fi recommended)";
    default:
      if (s.reason === "apple_intelligence_off") return "Turn on Apple Intelligence in iOS Settings to use this";
      if (s.reason === "not_in_this_build") return "Not in this build of ApolloSG";
      return "No built-in model on this phone. You can download one in On-device AI models";
  }
}

type RawCall = { ok: true; text: string; model: SlmModelInfo; elapsedMs: number } | { ok: false; reason: string };

/** Which model will answer: the phone's built-in one if it's ready, else ApolloSG's downloaded one, else none. */
export async function activeEngine(): Promise<{ kind: "system"; status: SlmNativeStatus } | { kind: "fallback"; status: SlmNativeStatus; modelId: string } | { kind: "none"; status: SlmNativeStatus }> {
  const status = await getSlmStatus();
  if (status.availability === "available") return { kind: "system", status };
  const fb = await installedFallback().catch(() => null);
  return fb ? { kind: "fallback", status, modelId: fb.id } : { kind: "none", status };
}

/** One call to whichever model is active. Exported for the model comparison, which records its own results. */
export async function generateRaw(purpose: SlmPurpose, instructions: string, prompt: string, maxOutputTokens: number, opts: { json: boolean; record: boolean; requireEnabled: boolean }): Promise<RawCall> {
  if (opts.requireEnabled && !(await isSlmEnabled())) return { ok: false, reason: "off" };
  const engine = await activeEngine();
  const os = engine.status.osVersion;
  const base = { at: new Date().toISOString(), purpose };
  const fail = async (reason: string, model: SlmModelInfo): Promise<RawCall> => {
    if (opts.record) await record({ ...base, ...model, elapsedMs: null, outcome: reason });
    return { ok: false, reason };
  };
  if (engine.kind === "none") {
    const reason = `not_ready_${engine.status.reason ?? engine.status.availability}`;
    return fail(reason, { engine: engine.status.engine, modelName: engine.status.modelName, osVersion: os });
  }
  const planned: SlmModelInfo = engine.kind === "system"
    ? { engine: engine.status.engine, modelName: engine.status.modelName, osVersion: os }
    : { engine: "llama_cpp", modelName: engine.modelId, osVersion: os };
  let timer: ReturnType<typeof setTimeout> | undefined;
  // A downloaded model on a mid-range phone is slower than the built-in ones, so it gets longer.
  const limit = engine.kind === "system" ? SLM_TIMEOUT_MS : SLM_FALLBACK_TIMEOUT_MS;
  try {
    const timeout = new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error("timeout")), limit); });
    if (engine.kind === "system") {
      const res = await Promise.race([ApolloSlm.generate({ instructions, prompt, maxOutputTokens, temperature: 0.1 }), timeout]);
      return { ok: true, text: res.text, elapsedMs: res.elapsedMs, model: { engine: res.engine, modelName: res.modelName ?? planned.modelName, osVersion: res.osVersion ?? os } };
    }
    const res = await Promise.race([generateWithFallback(instructions, prompt, maxOutputTokens, 0.1, opts.json), timeout]);
    return { ok: true, text: res.text, elapsedMs: res.elapsedMs, model: { engine: "llama_cpp", modelName: res.modelId, osVersion: os } };
  } catch (e) {
    const code = (e as { code?: string })?.code;
    return fail(e instanceof Error && e.message === "timeout" ? "timeout" : code ?? "failed", planned);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

const runOnce = (purpose: SlmPurpose, instructions: string, prompt: string, maxOutputTokens: number, json: boolean) =>
  generateRaw(purpose, instructions, prompt, maxOutputTokens, { json, record: true, requireEnabled: true });

/** Advisory pre-screen of a message's text. Never changes Apollo's result — see core.ts. */
export async function preScreenMessage(text: string, signals: FixedSignalsView): Promise<SlmOutcome<SlmAdvisory>> {
  const prepared = prepareSlmInput(text);
  if (!prepared) return { ok: false, reason: "empty" };
  const raw = await runOnce("pre_screen", PRE_SCREEN_INSTRUCTIONS, preScreenPrompt(prepared), 320, true);
  if (!raw.ok) return raw;
  const pre = parsePreScreen(raw.text, prepared);
  await record({ at: new Date().toISOString(), purpose: "pre_screen", ...raw.model, elapsedMs: raw.elapsedMs, outcome: `ok_${pre.hints.length}_kept_${pre.dropped}_dropped` });
  return { ok: true, value: advisoryFor(pre, signals), model: raw.model };
}

/** Plain-language re-wording of a settled result, or the reason it was not accepted. */
export async function explainSettledResult(result: SettledResult): Promise<SlmOutcome<string>> {
  const raw = await runOnce("explain", EXPLAIN_INSTRUCTIONS, explainPrompt(result), 200, false);
  if (!raw.ok) return raw;
  const checked = checkExplanation(raw.text, result);
  const outcome = checked.ok ? "ok" : `rejected_${checked.reason}`;
  await record({ at: new Date().toISOString(), purpose: "explain", ...raw.model, elapsedMs: raw.elapsedMs, outcome });
  return checked.ok ? { ok: true, value: checked.text, model: raw.model } : { ok: false, reason: outcome };
}
