/** Native-only Luddish startup for pre-production builds.
 * The model is verified in app-private storage before admission.
 * The one instance services Ask Higgins and all investigation roles.
 */
import * as Device from "expo-device";
import { File, FileMode, Paths } from "expo-file-system";
import * as LegacyFileSystem from "expo-file-system/legacy";
import { updateOnDeviceAIDownload } from "./downloadStatus.ts";
import { CANDIDATE_FILE, verifyPrivateGGUF } from "./modelAdmission.ts";

import { getSharedSLM, setSharedSLM } from "./sharedRuntime.ts";
import type { LocalLlamaRuntime } from "./llamaRnRuntime.ts";

let runtime: LocalLlamaRuntime | null = null;
let startup: Promise<boolean> | null = null;
let download: Promise<boolean> | null = null;
const MODEL_DOWNLOAD_URL = "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf";

export function startSharedLuddish(): Promise<boolean> {
  if (runtime) return Promise.resolve(true);
  if (startup) return startup;
  startup = (async () => {
    const file = new File(Paths.document, CANDIDATE_FILE);
    const admitted = await verifyPrivateGGUF({
      uri: file.uri, exists: file.exists, size: file.size,
      open: () => file.open(FileMode.ReadOnly),
    }, Device.totalMemory ?? null);
    if (!admitted.available) return false;
    // Never resolve the llama.rn native binding until the entire local model
    // has passed checksum and device admission.
    const { createLuddishOnDevice } = await import("./llamaRnBinding.native.ts");
    const created = createLuddishOnDevice({
      modelUri: admitted.uri, modelId: admitted.modelId,
      deviceAdmitted: true,
    });
    if (!created) return false;
    runtime = created;
    setSharedSLM(created);
    return true;
  })().catch(() => false).finally(() => { startup = null; });
  return startup;
}

/** Explicit local test provisioning entry point. Requires an already-local
 * selected source URI. No external download or implicit import on boot.
 * Always rehashes the private copy before making a model available.
 */
export async function installPrivateLuddishForTest(sourceUri: string): Promise<boolean> {
  if (runtime || startup) return false;
  const source = new File(sourceUri);
  const dest = new File(Paths.document, CANDIDATE_FILE);
  if (!source.exists || !/^file:\/\/\//.test(sourceUri) ||
      source.uri === dest.uri || dest.exists) return false;
  try {
    source.copy(dest);
    const ok = await startSharedLuddish();
    if (!ok) { if (dest.exists) dest.delete(); }
    return ok;
  } catch {
    try { if (dest.exists) dest.delete(); } catch { /* no data leak */ }
    return false;
  }
}

export async function stopSharedLuddish(): Promise<void> {
  if (startup) await startup;
  const previous = runtime;
  runtime = null;
  if (previous && getSharedSLM() === previous) setSharedSLM(null);
  if (previous) await previous.release();
}

/** Presence only; admission and integrity are checked separately at startup. */
export function isPrivateLuddishModelMissing(): boolean {
  try { return !new File(Paths.document, CANDIDATE_FILE).exists; }
  catch { return false; }
}

/** Explicitly consented download to private storage; never runs on startup. */
export function downloadPrivateLuddishForTest(): Promise<boolean> {
  if (download) return download;
  if (runtime || startup) return Promise.resolve(false);
  updateOnDeviceAIDownload({ phase: "downloading", receivedBytes: 0, totalBytes: 0, error: undefined });
  download = (async () => {
    const dest = new File(Paths.document, CANDIDATE_FILE);
    if (dest.exists) {
      updateOnDeviceAIDownload({ phase: "verifying" });
      const ok = await startSharedLuddish();
      updateOnDeviceAIDownload({ phase: ok ? "ready" : "failed", error: ok ? undefined : "Existing On-device AI package failed verification." });
      return ok;
    }
    try {
      // A single shared download with native byte-progress callbacks.
      const task = LegacyFileSystem.createDownloadResumable(
        MODEL_DOWNLOAD_URL, dest.uri, {},
        ({ totalBytesWritten, totalBytesExpectedToWrite }) => {
          updateOnDeviceAIDownload({
            phase: "downloading",
            receivedBytes: totalBytesWritten,
            totalBytes: totalBytesExpectedToWrite > 0 ? totalBytesExpectedToWrite : 0,
          });
        },
      );
      const result = await task.downloadAsync();
      if (!result || result.status < 200 || result.status >= 300) throw new Error("Download failed");
      updateOnDeviceAIDownload({ phase: "verifying" });
      const admitted = await verifyPrivateGGUF({
        uri: dest.uri, exists: dest.exists, size: dest.size,
        open: () => dest.open(FileMode.ReadOnly),
      }, Device.totalMemory ?? null);
      if (!admitted.available) throw new Error("On-device AI package verification failed: " + admitted.reason);
      updateOnDeviceAIDownload({ phase: "registering" });
      const { createLuddishOnDevice } = await import("./llamaRnBinding.native.ts");
      const created = createLuddishOnDevice({
        modelUri: admitted.uri, modelId: admitted.modelId, deviceAdmitted: true,
      });
      if (!created) throw new Error("On-device AI runtime unavailable");
      runtime = created;
      setSharedSLM(created);
      updateOnDeviceAIDownload({ phase: "ready" });
      return true;
    } catch (e) {
      try { if (dest.exists) dest.delete(); } catch { /* best effort */ }
      updateOnDeviceAIDownload({ phase: "failed", error: e instanceof Error ? e.message : "Download failed" });
      return false;
    }
  })().finally(() => { download = null; });
  return download;
}

/** Compatibility admission before protection setup. The app cannot uninstall
 * itself; rollback is limited to ApolloSG-owned model files and runtime state.
 */
export type SLMCompatibilityStage = "hardware" | "model_integrity" | "runtime_registration" | "inference" | "response_validation" | "complete" | "failed";
export async function checkRequiredSLMCompatibility(
  onStage?: (stage: SLMCompatibilityStage) => void,
): Promise<{ compatible: boolean; reason: string }> {
  const startedAt = Date.now();
  let stage: SLMCompatibilityStage = "hardware";
  const mark = (next: SLMCompatibilityStage) => {
    console.info("[ApolloSG SLM compatibility]", stage, "elapsed_ms", Date.now() - startedAt);
    stage = next;
    onStage?.(next);
  };
  try {
    mark("hardware");
    if (!Device.totalMemory || Device.totalMemory < 3 * 1024 * 1024 * 1024) {
      mark("failed");
      return { compatible: false, reason: "This device does not meet the required memory capacity." };
    }
    mark("model_integrity");
    // The shared runtime is registered after model checksum verification.
    const started = await startSharedLuddish();
    mark("runtime_registration");
    if (!started || !getSharedSLM()) {
      mark("failed");
      return { compatible: false, reason: "The required On-device AI model could not be verified or started." };
    }
    // Native context loading is lazy; inference triggers the actual model load.
    mark("inference");
    const { runSLM } = await import("./index.ts");
    const result = await runSLM({
      role: "case_finding", operation: "case_finding",
      question: "Compatibility self-test. Assess this synthetic, non-user message.",
      evidence: [{ evidenceId: "compatibility-test", text: "Synthetic test: an unknown sender claims to be a bank. No independent checks were performed." }],
    }, getSharedSLM());
    mark("response_validation");
    if (result.status !== "completed" || !result.answer.caseFinding) {
      mark("failed");
      return { compatible: false, reason: "The On-device AI model did not complete its required reasoning test." };
    }
    mark("complete");
    return { compatible: true, reason: "On-device AI compatibility verified." };
  } catch (error) {
    console.warn("[ApolloSG SLM compatibility] failure", stage, "elapsed_ms", Date.now() - startedAt, error);
    mark("failed");
    return { compatible: false, reason: "The On-device AI failed during " + stage + "." };
  }
}

export async function rollbackSLMSetup(): Promise<void> {
  await stopSharedLuddish();
  // Only the model file owned by this app is deleted. No system installation
  // or unrelated user data can be rolled back by an ordinary mobile app.
  try {
    const model = new File(Paths.document, CANDIDATE_FILE);
    if (model.exists) model.delete();
  } catch { /* retain failure as incompatible; no protection activation */ }
}
