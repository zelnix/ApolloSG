/** What the phone's own small language model can do right now. Read from the OS on every call, never cached. */
export type SlmAvailability = "available" | "downloadable" | "downloading" | "unavailable";

/** The OS-provided model behind the module. ApolloSG ships no model weights of its own. */
export type SlmEngine = "gemini_nano_mlkit" | "apple_foundation_models" | "none";

export interface SlmNativeStatus {
  availability: SlmAvailability;
  engine: SlmEngine;
  /** Why it isn't available, in the OS's terms (e.g. device_not_eligible, apple_intelligence_off, model_not_ready). */
  reason: string | null;
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
  /** Milliseconds the on-device call took. */
  elapsedMs: number;
}
