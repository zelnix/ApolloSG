/**
 * One optional shared Luddish SLM runtime across ApolloSG, including Ask Higgins.
 * The native app may install one admitted local runtime after package checks.
 * Nothing here loads a model, contacts a provider or silently falls back.
 */
import type { SLMAdapter } from "./index.ts";

let shared: SLMAdapter | null = null;
let lastSuccessfulInferenceAt: string | null = null;
const listeners = new Set<() => void>();
export interface SLMActivitySnapshot {
  registered: boolean;
  modelId: string | null;
  lastSuccessfulInferenceAt: string | null;
}
let snapshot: SLMActivitySnapshot = { registered: false, modelId: null, lastSuccessfulInferenceAt: null };
function publish(): void {
  snapshot = { registered: !!shared, modelId: shared?.modelId ?? null, lastSuccessfulInferenceAt };
  listeners.forEach((listener) => listener());
}
export function subscribeSLMActivity(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
export function getSLMActivitySnapshot(): SLMActivitySnapshot { return snapshot; }
/** Called only after the on-device response passes the SLM contract validator. */
export function recordSuccessfulSLMInference(adapter: SLMAdapter): void {
  if (adapter !== shared) return;
  lastSuccessfulInferenceAt = new Date().toISOString();
  publish();
}


/** App lifetime setup only, after native admission checks. */
export function setSharedSLM(adapter: SLMAdapter | null): void {
  shared = adapter;
  lastSuccessfulInferenceAt = null;
  publish();
}

export function getSharedSLM(): SLMAdapter | null {
  return shared;
}
