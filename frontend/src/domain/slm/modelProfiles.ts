/** Immutable package provenance. Qualification is separate from package discovery. */
export interface ModelProfile {
  modelId: string; publisher: string; revision: string; filename: string;
  expectedBytes: number | null; sha256: string | null; quantisation: "Q4_K_M";
  contextTokens: number; minimumTotalRamBytes: number; qualification: "reference" | "pending_physical_qualification";
}
export const REFERENCE_MODEL: ModelProfile = {
  modelId: "Qwen2.5-0.5B-Instruct-Q4_K_M", publisher: "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
  revision: "9217f5db79a29953eb74d5343926648285ec7e67", filename: "qwen2.5-0.5b-instruct-q4_k_m.gguf",
  expectedBytes: 491400032, sha256: "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db", quantisation: "Q4_K_M", contextTokens: 4096,
  minimumTotalRamBytes: 3 * 1024 ** 3, qualification: "reference",
};
export const PROPOSED_MODEL: ModelProfile = {
  modelId: "Qwen3-1.7B-Q4_K_M", publisher: "unsloth/Qwen3-1.7B-GGUF",
  revision: "d7f544eead698dbd1f15126ef60b45a1e1933222", filename: "Qwen3-1.7B-Q4_K_M.gguf",
  expectedBytes: 1107409472, sha256: "b139949c5bd74937ad8ed8c8cf3d9ffb1e99c866c823204dc42c0d91fa181897",
  quantisation: "Q4_K_M", contextTokens: 8192,
  // Engineering admission floor, NOT evidence of sufficient available memory.
  minimumTotalRamBytes: 6 * 1024 ** 3, qualification: "pending_physical_qualification",
};
export const profileForModel = (modelId: string): ModelProfile | undefined => [REFERENCE_MODEL, PROPOSED_MODEL].find(p => p.modelId === modelId);
export const ACTIVE_MODEL = PROPOSED_MODEL; // Activated by owner request; physical qualification remains pending.
export const packageUrl = (profile: ModelProfile) => `https://huggingface.co/${profile.publisher}/resolve/${profile.revision}/${profile.filename}`;
export const outputTokens = (operation: string) => operation === "case_finding" ? 1024 : ["escalation_assessment", "evidence_reasoning"].includes(operation) ? 512 : 384;
export const SAMPLING_PROFILES = {
  nonThinking: { temperature: 0.7, top_p: 0.8, top_k: 20, min_p: 0 },
  structuredEvaluation: { temperature: 0.2, top_p: 0.8, top_k: 20, min_p: 0 },
} as const;

export const modelDownloadSizeLabel = (profile: ModelProfile = ACTIVE_MODEL) => profile.expectedBytes === null ? "Size not confirmed" : `${(profile.expectedBytes / 1_000_000_000).toFixed(2)} GB`;
