/**
 * On-device SLM runtime: the only code that calls modules/apollo-slm. The rules live in ./core.ts.
 *
 * Off until the person turns it on (Settings → App → On-device AI). Even when on, it runs only if the phone's own
 * model is ready; nothing is downloaded or sent anywhere by ApolloSG. Each call is single-shot with a timeout; a
 * failure returns { ok: false, reason } and the caller keeps showing Apollo's fixed result as it is.
 *
 * The OS chooses and updates the model, so every call records which one answered (engine, Gemini Nano version or
 * iOS version), how long it took and the outcome, in a local log on the phone. The log never holds message text,
 * prompts or answers, and is not sent anywhere.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { ApolloSlm, type SlmNativeStatus } from "@/modules/apollo-slm";

import {
  EXPLAIN_INSTRUCTIONS, PRE_SCREEN_INSTRUCTIONS, SLM_TIMEOUT_MS,
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
export function slmStatusLine(s: SlmNativeStatus): string {
  switch (s.availability) {
    case "available": return `Ready — ${slmModelLabel(s)}`;
    case "downloading": return "The phone is still getting its model ready";
    case "downloadable": return "The phone can download its model (Wi-Fi recommended)";
    default:
      if (s.reason === "apple_intelligence_off") return "Turn on Apple Intelligence in iOS Settings to use this";
      if (s.reason === "not_in_this_build") return "Not in this build of ApolloSG";
      return "This phone doesn't have an on-device model ApolloSG can use";
  }
}

type RawCall = { ok: true; text: string; model: SlmModelInfo; elapsedMs: number } | { ok: false; reason: string };

async function runOnce(purpose: SlmPurpose, instructions: string, prompt: string, maxOutputTokens: number): Promise<RawCall> {
  if (!(await isSlmEnabled())) return { ok: false, reason: "off" };
  const status = await getSlmStatus();
  const base = { at: new Date().toISOString(), purpose, engine: status.engine, modelName: status.modelName, osVersion: status.osVersion };
  if (status.availability !== "available") {
    const reason = status.reason ?? status.availability;
    await record({ ...base, elapsedMs: null, outcome: `not_ready_${reason}` });
    return { ok: false, reason };
  }
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const timeout = new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error("timeout")), SLM_TIMEOUT_MS); });
    const res = await Promise.race([ApolloSlm.generate({ instructions, prompt, maxOutputTokens, temperature: 0.1 }), timeout]);
    const model: SlmModelInfo = { engine: res.engine, modelName: res.modelName ?? status.modelName, osVersion: res.osVersion ?? status.osVersion };
    // The caller records the final outcome once it has checked the answer.
    return { ok: true, text: res.text, model, elapsedMs: res.elapsedMs };
  } catch (e) {
    const code = (e as { code?: string })?.code;
    const reason = e instanceof Error && e.message === "timeout" ? "timeout" : code ?? "failed";
    await record({ ...base, elapsedMs: null, outcome: reason });
    return { ok: false, reason };
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/** Advisory pre-screen of a message's text. Never changes Apollo's result — see core.ts. */
export async function preScreenMessage(text: string, signals: FixedSignalsView): Promise<SlmOutcome<SlmAdvisory>> {
  const prepared = prepareSlmInput(text);
  if (!prepared) return { ok: false, reason: "empty" };
  const raw = await runOnce("pre_screen", PRE_SCREEN_INSTRUCTIONS, preScreenPrompt(prepared), 320);
  if (!raw.ok) return raw;
  const pre = parsePreScreen(raw.text, prepared);
  await record({ at: new Date().toISOString(), purpose: "pre_screen", ...raw.model, elapsedMs: raw.elapsedMs, outcome: `ok_${pre.hints.length}_kept_${pre.dropped}_dropped` });
  return { ok: true, value: advisoryFor(pre, signals), model: raw.model };
}

/** Plain-language re-wording of a settled result, or the reason it was not accepted. */
export async function explainSettledResult(result: SettledResult): Promise<SlmOutcome<string>> {
  const raw = await runOnce("explain", EXPLAIN_INSTRUCTIONS, explainPrompt(result), 200);
  if (!raw.ok) return raw;
  const checked = checkExplanation(raw.text, result);
  const outcome = checked.ok ? "ok" : `rejected_${checked.reason}`;
  await record({ at: new Date().toISOString(), purpose: "explain", ...raw.model, elapsedMs: raw.elapsedMs, outcome });
  return checked.ok ? { ok: true, value: checked.text, model: raw.model } : { ok: false, reason: outcome };
}
