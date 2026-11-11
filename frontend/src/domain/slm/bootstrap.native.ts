/** Native On-device AI startup for ApolloSG.
 * The model header and file location are checked before native inference admission.
 * The one instance services Ask Higgins and all investigation roles.
 */
import * as Device from "expo-device";
import * as Network from "expo-network";
import { Alert } from "react-native";
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
    // Resolve native binding only after lightweight local file admission.
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
 * Checks the private copy before making a model available.
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

/** Consent is per download, not a permanent cellular-data permission. */
async function confirmModelNetworkUse(): Promise<boolean> {
  let state: Network.NetworkState;
  try { state = await Network.getNetworkStateAsync(); }
  catch { state = { type: Network.NetworkStateType.UNKNOWN, isConnected: undefined, isInternetReachable: undefined }; }
  if (state.isConnected === false || state.type === Network.NetworkStateType.NONE) {
    Alert.alert("No internet connection", "Connect to Wi-Fi or mobile data to download ApolloSG's On-device AI model.");
    return false;
  }
  if (state.type === Network.NetworkStateType.WIFI) return true;
  return new Promise<boolean>((resolve) => {
    Alert.alert(
      "Download using mobile data?",
      "ApolloSG needs to download its On-device AI model. You're not connected to Wi-Fi. Mobile data may use your allowance or incur charges.",
      [
        { text: "Wait for Wi-Fi", style: "cancel", onPress: () => resolve(false) },
        { text: "Download using mobile data", onPress: () => resolve(true) },
      ],
      { cancelable: false },
    );
  });
}

/** Explicitly consented download to private storage; never runs on startup. */
export function downloadPrivateLuddishForTest(): Promise<boolean> {
  if (download) return download;
  if (runtime) return Promise.resolve(true);
  if (startup) return startup;
  download = (async () => {
    const dest = new File(Paths.document, CANDIDATE_FILE);
    if (dest.exists) {
      updateOnDeviceAIDownload({ phase: "verifying" });
      const ok = await startSharedLuddish();
      updateOnDeviceAIDownload({ phase: ok ? "ready" : "failed", error: ok ? undefined : "Existing On-device AI package failed verification." });
      return ok;
    }
    try {
      if (!await confirmModelNetworkUse()) return false;
      updateOnDeviceAIDownload({ phase: "downloading", receivedBytes: 0, totalBytes: 0, error: undefined });
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
      // Monitor network transitions throughout transfer. A switch away from Wi-Fi
      // pauses the transfer before requesting fresh consent. Never silently spend
      // mobile data because the connection changed mid-download.
      let monitoring = true;
      let networkBusy = false;
      let denied = false;
      const monitor = setInterval(() => {
        if (!monitoring || networkBusy) return;
        networkBusy = true;
        void (async () => {
          try {
            const state = await Network.getNetworkStateAsync();
            if (state.type === Network.NetworkStateType.WIFI && state.isConnected !== false) return;
            await task.pauseAsync();
            if (!monitoring) return;
            const approved = await confirmModelNetworkUse();
            if (!monitoring) return;
            if (!approved) { denied = true; return; }
            // Resume only after explicit consent for the current network.
            await task.resumeAsync();
          } catch {
            denied = true;
            try { await task.pauseAsync(); } catch { /* already stopped */ }
          } finally { networkBusy = false; }
        })();
      }, 1000);
      let result: LegacyFileSystem.FileSystemDownloadResult | undefined;
      try {
        result = await task.downloadAsync() ?? undefined;
      } finally {
        monitoring = false;
        clearInterval(monitor);
      }
      if (denied || !result || result.status < 200 || result.status >= 300) throw new Error(
        denied ? "Download paused. Connect to Wi-Fi and retry." : "Download failed");
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
      // Preserve existing model files on runtime failure; incomplete transfers are
      // rejected by lightweight admission and can be explicitly reinstalled.
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
    // The shared runtime is registered after model file admission.
    const started = await startSharedLuddish();
    mark("runtime_registration");
    if (!started || !getSharedSLM()) {
      mark("failed");
      return { compatible: false, reason: "The required On-device AI model could not be verified or started." };
    }
    // Actually load the native model context. Do not run a synthetic case investigation.
    mark("inference");
    await (getSharedSLM() as LocalLlamaRuntime).prepare();
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
  // Preserve the installed model on runtime failures; only release runtime state.
}
