/** Native Higgins startup for ApolloSG.
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
import { LocalInferenceError, type LocalLlamaRuntime } from "./llamaRnRuntime.ts";
import { admitNativeStartup, describeStartupFailure, type NativeStartupFailure } from "./nativeStartup.ts";
import type { SLMAdmissionResult } from "./compatibilityAttempt.ts";
import { downloadWithNetworkConsent, ModelDownloadPaused } from "./downloadSession.ts";

let runtime: LocalLlamaRuntime | null = null;
let startup: Promise<boolean> | null = null;
let download: Promise<boolean> | null = null;
let startupFailure: NativeStartupFailure | null = null;
// Immutable upstream revision, checked against public model metadata on 2026-11-13.
// This pins provenance; lightweight admission is not a full-file checksum proof.
const MODEL_DOWNLOAD_URL = "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-q4_k_m.gguf";

export function startSharedLuddish(onStage?: (stage: "model_integrity" | "runtime_registration") => void): Promise<boolean> {
  if (runtime) return Promise.resolve(true);
  if (startup) return startup;
  startup = (async () => {
    startupFailure = null;
    const result = await admitNativeStartup(async () => {
      const file = new File(Paths.document, CANDIDATE_FILE);
      return verifyPrivateGGUF({ uri: file.uri, exists: file.exists, size: file.size,
        open: () => file.open(FileMode.ReadOnly) }, Device.totalMemory ?? null);
    }, async () => {
      const { createLuddishOnDevice } = await import("./llamaRnBinding.native.ts");
      return model => createLuddishOnDevice({ modelUri: model.uri, modelId: model.modelId, deviceAdmitted: true });
    }, onStage);
    if (!result.available) { startupFailure = result.code; return false; }
    runtime = result.runtime;
    setSharedSLM(result.runtime);
    return true;
  })().catch(() => { startupFailure = "runtime_registration_failed"; return false; }).finally(() => { startup = null; });
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

/** Presence only; lightweight file admission happens at startup. */
export function isPrivateLuddishModelMissing(): boolean {
  try { return !new File(Paths.document, CANDIDATE_FILE).exists; }
  catch { return false; }
}

/** Consent is per download, not a permanent cellular-data permission. */
async function confirmModelNetworkUse(): Promise<Network.NetworkStateType | null> {
  let state: Network.NetworkState;
  try { state = await Network.getNetworkStateAsync(); }
  catch { state = { type: Network.NetworkStateType.UNKNOWN, isConnected: undefined, isInternetReachable: undefined }; }
  if (state.isConnected === false || state.type === Network.NetworkStateType.NONE) {
    Alert.alert("No internet connection", "Connect to Wi-Fi or mobile data to download ApolloSG's Higgins model.");
    return null;
  }
  if (state.type === Network.NetworkStateType.WIFI) return state.type;
  return new Promise<Network.NetworkStateType | null>((resolve) => {
    Alert.alert(
      "Download using mobile data?",
      "ApolloSG needs to download its Higgins model. You're not connected to Wi-Fi. Mobile data may use your allowance or incur charges.",
      [
        { text: "Wait for Wi-Fi", style: "cancel", onPress: () => resolve(null) },
        { text: "Download using mobile data", onPress: () => resolve(state.type ?? Network.NetworkStateType.UNKNOWN) },
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
    startupFailure = null;
    const dest = new File(Paths.document, CANDIDATE_FILE);
    if (dest.exists) {
      updateOnDeviceAIDownload({ phase: "verifying" });
      const admitted = await verifyPrivateGGUF({ uri: dest.uri, exists: true, size: dest.size,
        open: () => dest.open(FileMode.ReadOnly) }, Device.totalMemory ?? null);
      if (admitted.available || admitted.reason === "device_not_admitted") {
        const ok = admitted.available && await startSharedLuddish();
        updateOnDeviceAIDownload({ phase: ok ? "ready" : "failed", error: ok ? undefined
          : startupFailure ? describeStartupFailure(startupFailure) : "The installed model could not run on this device." });
        return ok;
      }
      // Explicit install action: preserve the invalid package for diagnosis and
      // let the next transfer use a clean destination. Never replace a valid model.
      new File(dest.uri).move(new File(Paths.document, CANDIDATE_FILE + ".invalid-" + Date.now()));
    }
    try {
      const approvedNetwork = await confirmModelNetworkUse();
      if (approvedNetwork === null) return false;
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
      const result = await downloadWithNetworkConsent(task, {
        approvedNetwork,
        approveNetwork: confirmModelNetworkUse,
        readNetwork: async () => {
          try {
            const state = await Network.getNetworkStateAsync();
            return state.isConnected === false ? Network.NetworkStateType.NONE : state.type ?? Network.NetworkStateType.UNKNOWN;
          } catch { return Network.NetworkStateType.UNKNOWN; }
        },
      });
      if (result.status < 200 || result.status >= 300) throw new Error("Download failed");
      updateOnDeviceAIDownload({ phase: "verifying" });
      const registered = await startSharedLuddish(stage => {
        updateOnDeviceAIDownload({ phase: stage === "model_integrity" ? "verifying" : "registering" });
      });
      if (!registered) throw new Error("Model setup failed");
      updateOnDeviceAIDownload({ phase: "ready" });
      return true;
    } catch (e) {
      // Preserve existing model files on runtime failure; incomplete transfers are
      // rejected by lightweight admission and can be explicitly reinstalled.
      updateOnDeviceAIDownload({ phase: "failed", error: startupFailure ? describeStartupFailure(startupFailure)
        : e instanceof ModelDownloadPaused ? "Download paused. Connect to Wi-Fi and retry."
        : "The Higgins download did not complete. Check your connection and retry." });
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
): Promise<SLMAdmissionResult> {
  let stage: SLMCompatibilityStage = "hardware";
  const mark = (next: SLMCompatibilityStage) => {
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
    const started = await startSharedLuddish(mark);
    if (!started || !getSharedSLM()) {
      mark("failed");
      const code = startupFailure ?? "runtime_registration_failed";
      return { compatible: false, reason: describeStartupFailure(code), diagnosticCode: code };
    }
    // Actually load the native model context. Do not run a synthetic case investigation.
    mark("inference");
    await (getSharedSLM() as LocalLlamaRuntime).prepare();
    mark("complete");
    return { compatible: true, reason: "Higgins compatibility verified." };
  } catch (error) {
    const failedStage = stage;
    mark("failed");
    return { compatible: false, reason: error instanceof LocalInferenceError && error.stage === "model_load"
      ? "The model file passed initial checks, but Higgins’ native runtime could not load it."
      : "Higgins failed during " + failedStage + ".",
      diagnosticCode: error instanceof LocalInferenceError ? error.stage + ":" + error.code : failedStage + "_failed" };
  }
}

export async function rollbackSLMSetup(): Promise<void> {
  await stopSharedLuddish();
  // Preserve the installed model on runtime failures; only release runtime state.
}
