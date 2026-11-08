/** What the phone's own small language model can do right now. Read from the OS on every call, never cached. */
export type SlmAvailability = "available" | "downloadable" | "downloading" | "unavailable";

/** The OS-provided model behind the module, or "llama_cpp" for ApolloSG's downloaded fallback (see src/slm/models.ts). */
export type SlmEngine = "gemini_nano_mlkit" | "apple_foundation_models" | "llama_cpp" | "none";

export interface SlmNativeStatus {
  availability: SlmAvailability;
  engine: SlmEngine;
  /** Why it isn't available, in the OS's terms (e.g. device_not_eligible, apple_intelligence_off, model_not_ready). */
  reason: string | null;
  /** Android: the Gemini Nano version AICore reports (GenerativeModel.getBaseModelName). iOS: always null — Apple
   *  publishes no model version; the model ships with the OS, so osVersion identifies it. */
  modelName: string | null;
  /** e.g. "Android 16 (API 36)" or "iOS 26.1.0". */
  osVersion: string | null;
  observedAt: string;
}

export interface SlmGenerateInput {
  /** Fixed instructions for the task. Never contains the person's content. */
  instructions: string;
  /** The task input (already redacted on the device). */
  prompt: string;
  maxOutputTokens: number;
  temperature: number;
}

export interface SlmNativeResult {
  text: string;
  engine: SlmEngine;
  /** The model version that answered this call (see SlmNativeStatus). */
  modelName: string | null;
  osVersion: string | null;
  /** Milliseconds the on-device call took. */
  elapsedMs: number;
}
