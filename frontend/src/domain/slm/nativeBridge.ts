/**
 * Explicit llama.rn native binding for ApolloSG.
 *
 * Keep the native dependency at the composition root. The shared SLM domain
 * stays importable in Node tests, web and Expo Go without inventing inference.
 * Only the native development/production build may provide this binding.
 */
import { LocalLlamaRuntime, type InitLlama } from "./llamaRnRuntime.ts";

export interface NativeSLMCapability {
  available: boolean;
  reason?: "native_binding_missing" | "model_not_installed" | "invalid_configuration";
}

export interface NativeSLMSetup {
  /** A GGUF file on THIS device, verified and selected by the app. */
  modelUri: string | null;
  /** Hash-qualified, trusted model identity established by model management. */
  modelId: string | null;
  /** Real llama.rn's initLlama, explicitly imported by a native-only entry point. */
  initLlama?: InitLlama | null;
  /** Admission by platform code; false unless device is known to have enough resources. */
  deviceAdmitted: boolean;
}

export function nativeSLMCapability(setup: NativeSLMSetup): NativeSLMCapability {
  if (!setup.initLlama) return { available: false, reason: "native_binding_missing" };
  if (!setup.modelUri) return { available: false, reason: "model_not_installed" };
  if (!setup.modelId || !/^file:\/\/\/.*\.gguf$/i.test(setup.modelUri) ||
      !setup.deviceAdmitted) {
    return { available: false, reason: "invalid_configuration" };
  }
  return { available: true };
}

/** Constructs one shared local runtime; never attempts download or Gemini. */
export function createNativeSLM(setup: NativeSLMSetup): LocalLlamaRuntime | null {
  if (!nativeSLMCapability(setup).available) return null;
  return new LocalLlamaRuntime(
    setup.modelUri!, setup.modelId!, setup.initLlama!,
  );
}
