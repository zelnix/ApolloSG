/**
 * Native-only llama.rn binding, used only in a custom Expo native build.
 * No runtime is created automatically. The application must first verify the
 * locally installed GGUF and obtain a device admission decision.
 *
 * DO NOT import this module from web/Expo Go entry points.
 */
import { initLlama } from "llama.rn";
import { createNativeSLM, type NativeSLMSetup } from "./nativeBridge.ts";
import type { InitLlama, LocalLlamaRuntime } from "./llamaRnRuntime.ts";

// Keep llama.rn SDK types at the app's native composition boundary. No
// component downstream of SLM should depend on a vendor's types.
const nativeInit: InitLlama = async (params) => {
  const context = await initLlama(params);
  return {
    countFormattedTokens: async (messages, schema) => {
      const formatted = await context.getFormattedChat(messages, null, { jinja: true, enable_thinking: false, response_format: { type: "json_object", schema } });
      return (await context.tokenize(formatted.prompt)).tokens.length;
    },
    stopCompletion: () => context.stopCompletion(),
    completion: async (options) => {
      const result = await context.completion(options);
      return {
        text: result.text, content: result.content,
        stopped_limit: result.stopped_limit, truncated: result.truncated,
        context_full: result.context_full, interrupted: result.interrupted,
      };
    },
    release: async () => {
      await context.release();
    },
  };
};

/**
 * Call only after the app has checked the model's local file, trusted
 * package identity, and runtime/device admission. This module never reads
 * remote URLs, downloads models, or switches to Gemini.
 */
export function createLuddishOnDevice(
  setup: Omit<NativeSLMSetup, "initLlama">,
): LocalLlamaRuntime | null {
  return createNativeSLM({ ...setup, initLlama: nativeInit });
}
