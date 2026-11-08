/**
 * The downloaded fallback model: download (Wi-Fi only, on request), verify, load with llama.cpp, run, delete.
 *
 * - Download only when the person taps it, only on Wi-Fi, and only if the phone has the memory and storage for it
 *   (models.ts modelFit). The file goes to ApolloSG's private documents folder.
 * - Before first use the file's SHA-256 must match MODEL_SOURCES; a mismatch deletes it. Nothing unverified is loaded.
 * - Only one model is kept. The context is loaded on first use and released after a short idle period, so the
 *   memory is given back.
 * - The download fetches a model file from ApolloSG's storage; it sends no message text or personal data.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Device from "expo-device";
import * as FS from "expo-file-system/legacy";
import * as Network from "expo-network";
import type { LlamaContext } from "llama.rn";

import { ApolloSlm } from "@/modules/apollo-slm";

import { FALLBACK_MODELS, MODEL_SOURCES, hashMatches, modelById, modelFit, type FallbackModel, type FallbackModelId, type ModelFit } from "./models.ts";

const STATE_KEY = "apollo.slm.fallback.v1";
const DIR = `${FS.documentDirectory ?? ""}slm/`;
const IDLE_RELEASE_MS = 60_000;

interface StoredState { id: FallbackModelId; verified: boolean }

export type FallbackState =
  | { kind: "none" }
  | { kind: "downloading"; id: FallbackModelId; progress: number }
  | { kind: "ready"; id: FallbackModelId }
  | { kind: "failed"; id: FallbackModelId; reason: string };

const fileFor = (id: FallbackModelId) => `${DIR}${id}.gguf`;

async function readState(): Promise<StoredState | null> {
  try { const raw = await AsyncStorage.getItem(STATE_KEY); return raw ? (JSON.parse(raw) as StoredState) : null; } catch { return null; }
}
async function writeState(s: StoredState | null): Promise<void> {
  if (s) await AsyncStorage.setItem(STATE_KEY, JSON.stringify(s)); else await AsyncStorage.removeItem(STATE_KEY);
}

/** Each model with whether this phone can take it, for the model list. */
export async function fallbackOptions(): Promise<Array<{ model: FallbackModel; fit: ModelFit }>> {
  let free: number | null = null;
  try { free = await FS.getFreeDiskStorageAsync(); } catch { free = null; }
  const memory = Device.totalMemory ?? null;
  return FALLBACK_MODELS.map((model) => ({ model, fit: modelFit(model, MODEL_SOURCES[model.id], memory, free) }));
}

/** The installed, verified fallback model, if any. A missing file clears the record. */
export async function installedFallback(): Promise<FallbackModel | null> {
  const st = await readState();
  if (!st?.verified) return null;
  const info = await FS.getInfoAsync(fileFor(st.id));
  if (!info.exists) { await writeState(null); return null; }
  return modelById(st.id);
}

let active: FS.DownloadResumable | null = null;

/** Downloads and verifies one model, replacing any other. Progress is 0..1. */
export async function downloadFallback(id: FallbackModelId, onProgress: (p: number) => void): Promise<FallbackState> {
  const model = modelById(id);
  const source = MODEL_SOURCES[id];
  if (!model || !source) return { kind: "failed", id, reason: "not_hosted" };
  const fit = (await fallbackOptions()).find((o) => o.model.id === id)?.fit;
  if (!fit?.ok) return { kind: "failed", id, reason: fit && !fit.ok ? fit.reason : "not_hosted" };
  const net = await Network.getNetworkStateAsync().catch(() => null);
  if (net?.type !== Network.NetworkStateType.WIFI) return { kind: "failed", id, reason: "needs_wifi" };

  await deleteFallback();
  await FS.makeDirectoryAsync(DIR, { intermediates: true }).catch(() => undefined);
  const target = fileFor(id);
  await writeState({ id, verified: false });
  active = FS.createDownloadResumable(source.url, target, {}, (p) => {
    const total = p.totalBytesExpectedToWrite > 0 ? p.totalBytesExpectedToWrite : source.bytes;
    onProgress(Math.min(1, p.totalBytesWritten / total));
  });
  try {
    const res = await active.downloadAsync();
    if (!res || res.status !== 200) throw new Error(`http_${res?.status ?? "none"}`);
  } catch (e) {
    await FS.deleteAsync(target, { idempotent: true });
    await writeState(null);
    return { kind: "failed", id, reason: e instanceof Error && e.message.startsWith("http_") ? e.message : "download_failed" };
  } finally {
    active = null;
  }
  const actual = await ApolloSlm.sha256File(target).catch(() => null);
  if (!hashMatches(source.sha256, actual)) {
    await FS.deleteAsync(target, { idempotent: true });
    await writeState(null);
    return { kind: "failed", id, reason: "checksum_mismatch" };
  }
  await writeState({ id, verified: true });
  return { kind: "ready", id };
}

export async function cancelFallbackDownload(): Promise<void> {
  try { await active?.pauseAsync(); } catch { /* already finished */ }
  active = null;
  await deleteFallback();
}

export async function deleteFallback(): Promise<void> {
  await releaseContext();
  await FS.deleteAsync(DIR, { idempotent: true }).catch(() => undefined);
  await writeState(null);
}

// ── Running it ─────────────────────────────────────────────────────────────

let ctx: { id: FallbackModelId; context: LlamaContext } | null = null;
let idleTimer: ReturnType<typeof setTimeout> | null = null;

async function releaseContext(): Promise<void> {
  if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; }
  const c = ctx; ctx = null;
  if (c) await c.context.release().catch(() => undefined);
}

async function contextFor(model: FallbackModel): Promise<LlamaContext> {
  if (ctx?.id === model.id) return ctx.context;
  await releaseContext();
  // Loaded only here: llama.rn reads its native module at import, which web and Expo Go don't have.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { initLlama } = require("llama.rn") as typeof import("llama.rn");
  const context = await initLlama({
    model: fileFor(model.id).replace(/^file:\/\//, ""),
    n_ctx: model.contextTokens,
    n_gpu_layers: 0,   // CPU only: predictable on the mid-range phones this fallback is for.
    use_mlock: false,
  });
  ctx = { id: model.id, context };
  return context;
}

export interface FallbackResult { text: string; elapsedMs: number; modelId: FallbackModelId }

/** One completion with the installed, verified model. Throws if there isn't one. */
export async function generateWithFallback(instructions: string, prompt: string, maxOutputTokens: number, temperature: number, json: boolean): Promise<FallbackResult> {
  const model = await installedFallback();
  if (!model) throw Object.assign(new Error("no_fallback_model"), { code: "SLM_UNAVAILABLE" });
  const started = Date.now();
  const context = await contextFor(model);
  if (idleTimer) clearTimeout(idleTimer);
  try {
    const res = await context.completion({
      messages: [{ role: "system", content: instructions }, { role: "user", content: prompt }],
      n_predict: maxOutputTokens,
      temperature,
      ...(json ? { response_format: { type: "json_object" as const } } : {}),
    });
    return { text: res.content || res.text || "", elapsedMs: Date.now() - started, modelId: model.id };
  } finally {
    idleTimer = setTimeout(() => { void releaseContext(); }, IDLE_RELEASE_MS);
  }
}
