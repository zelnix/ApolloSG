/**
 * On-device SLM runtime: the only code that calls modules/apollo-slm. The rules live in ./core.ts.
 *
 * Off until the person turns it on (Settings → App → On-device AI). Even when on, it runs only if the phone's own
 * model is ready; nothing is downloaded or sent anywhere by ApolloSG. Each call is single-shot with a timeout; a
 * failure returns { ok: false, reason } and the caller keeps showing Apollo's fixed result as it is.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { ApolloSlm, type SlmNativeStatus } from "@/modules/apollo-slm";

import {
  EXPLAIN_INSTRUCTIONS, PRE_SCREEN_INSTRUCTIONS, SLM_TIMEOUT_MS,
  advisoryFor, checkExplanation, explainPrompt, parsePreScreen, preScreenPrompt, prepareSlmInput,
  type FixedSignalsView, type SettledResult, type SlmAdvisory,
} from "./core.ts";

const ENABLED_KEY = "apollo.slm.enabled.v1";

export type SlmOutcome<T> = { ok: true; value: T } | { ok: false; reason: string };

export async function isSlmEnabled(): Promise<boolean> {
  try { return (await AsyncStorage.getItem(ENABLED_KEY)) === "on"; } catch { return false; }
}

export async function setSlmEnabled(on: boolean): Promise<void> {
  await AsyncStorage.setItem(ENABLED_KEY, on ? "on" : "off");
}

export async function getSlmStatus(): Promise<SlmNativeStatus> {
  try { return await ApolloSlm.getStatus(); }
  catch { return { availability: "unavailable", engine: "none", reason: "status_unreadable", observedAt: new Date().toISOString() }; }
}

export async function requestSlmDownload(): Promise<SlmNativeStatus> {
  try { return await ApolloSlm.requestDownload(); }
  catch { return getSlmStatus(); }
}

/** What the Settings row says about the phone's model. */
export function slmStatusLine(s: SlmNativeStatus): string {
  switch (s.availability) {
    case "available": return s.engine === "apple_foundation_models" ? "Ready — Apple Intelligence on this iPhone" : "Ready — Gemini Nano on this phone";
    case "downloading": return "The phone is still getting its model ready";
    case "downloadable": return "The phone can download its model (Wi-Fi recommended)";
    default:
      if (s.reason === "apple_intelligence_off") return "Turn on Apple Intelligence in iOS Settings to use this";
      if (s.reason === "not_in_this_build") return "Not in this build of ApolloSG";
      return "This phone doesn't have an on-device model ApolloSG can use";
  }
}

async function runOnce(instructions: string, prompt: string, maxOutputTokens: number): Promise<SlmOutcome<string>> {
  if (!(await isSlmEnabled())) return { ok: false, reason: "off" };
  const status = await getSlmStatus();
  if (status.availability !== "available") return { ok: false, reason: status.reason ?? status.availability };
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const timeout = new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error("timeout")), SLM_TIMEOUT_MS); });
    const res = await Promise.race([ApolloSlm.generate({ instructions, prompt, maxOutputTokens, temperature: 0.1 }), timeout]);
    return { ok: true, value: res.text };
  } catch (e) {
    const code = (e as { code?: string })?.code;
    return { ok: false, reason: e instanceof Error && e.message === "timeout" ? "timeout" : code ?? "failed" };
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/** Advisory pre-screen of a message's text. Never changes Apollo's result — see core.ts. */
export async function preScreenMessage(text: string, signals: FixedSignalsView): Promise<SlmOutcome<SlmAdvisory>> {
  const prepared = prepareSlmInput(text);
  if (!prepared) return { ok: false, reason: "empty" };
  const raw = await runOnce(PRE_SCREEN_INSTRUCTIONS, preScreenPrompt(prepared), 320);
  if (!raw.ok) return raw;
  return { ok: true, value: advisoryFor(parsePreScreen(raw.value, prepared), signals) };
}

/** Plain-language re-wording of a settled result, or the reason it was not accepted. */
export async function explainSettledResult(result: SettledResult): Promise<SlmOutcome<string>> {
  const raw = await runOnce(EXPLAIN_INSTRUCTIONS, explainPrompt(result), 200);
  if (!raw.ok) return raw;
  const checked = checkExplanation(raw.value, result);
  return checked.ok ? { ok: true, value: checked.text } : { ok: false, reason: `rejected_${checked.reason}` };
}
