/**
 * One optional shared Luddish SLM runtime across ApolloSG, including Ask Higgins.
 * The native app may install an admitted, checksum-verified local runtime once.
 * Nothing here loads a model, contacts a provider or silently falls back.
 */
import type { SLMAdapter } from "./index.ts";

let shared: SLMAdapter | null = null;

/** App lifetime setup only, after native admission checks. */
export function setSharedSLM(adapter: SLMAdapter | null): void {
  shared = adapter;
}

export function getSharedSLM(): SLMAdapter | null {
  return shared;
}
