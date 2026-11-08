/** Strict private-device admission for the first benchmark GGUF.
 * No downloads, external storage permissions, trust-on-first-use or cloud hash.
 * Fail closed; model candidate is NOT yet approved for production.
 */
import { StreamingSha256 } from "./streamingSha256.ts";

export const CANDIDATE_FILE = "qwen2.5-0.5b-instruct-q4_k_m.gguf";
export const CANDIDATE_SHA256 = "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db";
export const MIN_DEVICE_RAM_BYTES = 3 * 1024 * 1024 * 1024;
const MIN_MODEL_BYTES = 100 * 1024 * 1024;
const MAX_MODEL_BYTES = 1024 * 1024 * 1024;
const CHUNK_BYTES = 128 * 1024;

export interface LocalModelReader {
  readonly uri: string;
  readonly exists: boolean;
  readonly size: number | null;
  open(): { readBytes(length: number): Uint8Array | Promise<Uint8Array>; close(): void };
}
export type ModelAdmission =
  | { available: true; uri: string; modelId: string }
  | { available: false; reason: "model_not_installed" | "model_unreadable" | "device_not_admitted" | "checksum_failed" | "invalid_model" };

const tick = () => new Promise<void>(resolve => setTimeout(resolve, 0));

export async function verifyPrivateGGUF(
  file: LocalModelReader,
  totalMemory: number | null,
): Promise<ModelAdmission> {
  if (!file.exists) return { available: false, reason: "model_not_installed" };
  if (!totalMemory || !Number.isFinite(totalMemory) || totalMemory < MIN_DEVICE_RAM_BYTES)
    return { available: false, reason: "device_not_admitted" };
  if (!/^file:\/\/\//i.test(file.uri) || !file.uri.endsWith("/" + CANDIDATE_FILE) ||
      !Number.isFinite(file.size) || file.size === null ||
      file.size < MIN_MODEL_BYTES || file.size > MAX_MODEL_BYTES)
    return { available: false, reason: "invalid_model" };
  let handle: ReturnType<LocalModelReader["open"]> | null = null;
  try {
    handle = file.open();
    const hasher = new StreamingSha256();
    let pos = 0, chunks = 0;
    while (pos < file.size) {
      const length = Math.min(CHUNK_BYTES, file.size - pos);
      const chunk = await handle.readBytes(length);
      if (chunk.length !== length) return { available: false, reason: "model_unreadable" };
      hasher.update(chunk);
      pos += chunk.length;
      // Yield to mobile UI periodically while keeping peak JS RAM bounded.
      if (++chunks % 32 === 0) await tick();
    }
    if (hasher.digestHex() !== CANDIDATE_SHA256)
      return { available: false, reason: "checksum_failed" };
    return { available: true, uri: file.uri, modelId: "Qwen2.5-0.5B-Instruct-Q4_K_M-sha256:" + CANDIDATE_SHA256 };
  } catch {
    return { available: false, reason: "model_unreadable" };
  } finally {
    try { handle?.close(); } catch { /* best effort close */ }
  }
}
