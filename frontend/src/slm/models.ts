/**
 * Fallback on-device models, for phones without a built-in model (no Gemini Nano, no Apple Intelligence).
 *
 * ApolloSG downloads one of these only when the person asks, over Wi-Fi, and runs it with llama.cpp (llama.rn).
 * The file is checked against its pinned SHA-256 before it is ever loaded; a file that doesn't match is deleted.
 * Pure: no React Native imports, so the rules run under `node --test`.
 *
 * WHERE THE FILES COME FROM: ApolloSG's own storage, not Hugging Face directly — a third-party link can change or
 * vanish, and the hash would no longer match. Fill MODEL_SOURCES from `node scripts/slm-model-manifest.mjs <file>`
 * after downloading the GGUF named in `upstream`. Until a model has a source, it is listed but can't be downloaded.
 */

export type FallbackModelId = "qwen2.5-0.5b-instruct-q4km" | "qwen2.5-1.5b-instruct-q4km" | "llama3.2-1b-instruct-q4km";

export interface FallbackModel {
  id: FallbackModelId;
  label: string;
  family: "Qwen" | "Llama";
  /** Where the owner gets the file to host (Hugging Face repo / file). */
  upstream: { repo: string; file: string };
  licence: string;
  /** Which licence text (licences.ts) ships with it. */
  licenceText: "apache_2_0" | "llama_3_2";
  /** Approximate download size, shown before downloading; the real size comes from MODEL_SOURCES. */
  approxBytes: number;
  /** Total phone memory below which the model isn't offered: it would be too slow or be killed by the OS. */
  minTotalMemoryBytes: number;
  /** Context window ApolloSG loads it with. Prompts are capped at SLM_MAX_INPUT_CHARS, well inside this. */
  contextTokens: number;
}

const GB = 1024 ** 3;
const MB = 1024 ** 2;

export const FALLBACK_MODELS: readonly FallbackModel[] = [
  {
    id: "qwen2.5-0.5b-instruct-q4km", label: "Qwen 2.5 0.5B (small)", family: "Qwen",
    upstream: { repo: "Qwen/Qwen2.5-0.5B-Instruct-GGUF", file: "qwen2.5-0.5b-instruct-q4_k_m.gguf" },
    licence: "Apache-2.0", licenceText: "apache_2_0", approxBytes: 400 * MB, minTotalMemoryBytes: 3 * GB, contextTokens: 2048,
  },
  {
    id: "llama3.2-1b-instruct-q4km", label: "Llama 3.2 1B", family: "Llama",
    upstream: { repo: "bartowski/Llama-3.2-1B-Instruct-GGUF", file: "Llama-3.2-1B-Instruct-Q4_K_M.gguf" },
    licence: "Llama 3.2 Community License", licenceText: "llama_3_2", approxBytes: 810 * MB, minTotalMemoryBytes: 4 * GB, contextTokens: 2048,
  },
  {
    id: "qwen2.5-1.5b-instruct-q4km", label: "Qwen 2.5 1.5B", family: "Qwen",
    upstream: { repo: "Qwen/Qwen2.5-1.5B-Instruct-GGUF", file: "qwen2.5-1.5b-instruct-q4_k_m.gguf" },
    licence: "Apache-2.0", licenceText: "apache_2_0", approxBytes: 1120 * MB, minTotalMemoryBytes: 6 * GB, contextTokens: 2048,
  },
];

export interface ModelSource {
  /** HTTPS URL on ApolloSG's own storage. */
  url: string;
  /** Lower-case hex SHA-256 of the exact file. */
  sha256: string;
  bytes: number;
}

/** Filled in by the owner once each file is hosted. null = listed, not downloadable. */
export const MODEL_SOURCES: Record<FallbackModelId, ModelSource | null> = {
  "qwen2.5-0.5b-instruct-q4km": null,
  "llama3.2-1b-instruct-q4km": null,
  "qwen2.5-1.5b-instruct-q4km": null,
};

export function modelById(id: string): FallbackModel | null {
  return FALLBACK_MODELS.find((m) => m.id === id) ?? null;
}

export function validSource(s: ModelSource | null | undefined): s is ModelSource {
  return !!s && /^https:\/\//.test(s.url) && /^[0-9a-f]{64}$/.test(s.sha256) && Number.isFinite(s.bytes) && s.bytes > 0;
}

export type ModelFit =
  | { ok: true }
  | { ok: false; reason: "not_hosted" | "too_little_memory" | "too_little_storage" | "memory_unknown" };

/** Whether this phone can take the model. Unknown memory is not "enough": the model isn't offered. */
export function modelFit(m: FallbackModel, source: ModelSource | null, totalMemoryBytes: number | null, freeStorageBytes: number | null): ModelFit {
  if (!validSource(source)) return { ok: false, reason: "not_hosted" };
  if (totalMemoryBytes == null || !Number.isFinite(totalMemoryBytes)) return { ok: false, reason: "memory_unknown" };
  if (totalMemoryBytes < m.minTotalMemoryBytes) return { ok: false, reason: "too_little_memory" };
  // Keep 500 MB free after the download so the phone isn't left full.
  if (freeStorageBytes != null && freeStorageBytes < source.bytes + 500 * MB) return { ok: false, reason: "too_little_storage" };
  return { ok: true };
}

export const FIT_TEXT: Record<Exclude<ModelFit, { ok: true }>["reason"], string> = {
  not_hosted: "Not available to download yet",
  too_little_memory: "This phone doesn't have enough memory for it",
  too_little_storage: "Not enough free storage on this phone",
  memory_unknown: "ApolloSG couldn't read this phone's memory, so it isn't offered",
};

export function formatBytes(n: number): string {
  return n >= GB ? `${(n / GB).toFixed(1)} GB` : `${Math.round(n / MB)} MB`;
}

/** Normalises a hash for comparison; anything that isn't 64 hex characters never matches. */
export function hashMatches(expected: string, actual: string | null | undefined): boolean {
  const a = String(actual ?? "").trim().toLowerCase();
  return /^[0-9a-f]{64}$/.test(a) && a === expected.trim().toLowerCase();
}
