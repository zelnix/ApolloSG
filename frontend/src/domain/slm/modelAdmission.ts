/** Fast on-device model admission: private file, plausible size, RAM and GGUF header.
 * Full-file SHA-256 was removed from startup and installation by product decision.
 * Native model loading and the mandatory inference self-test remain fail-closed.
 */
export const CANDIDATE_FILE = "qwen2.5-0.5b-instruct-q4_k_m.gguf";
export const MIN_DEVICE_RAM_BYTES = 3 * 1024 * 1024 * 1024;
const MIN_MODEL_BYTES = 100 * 1024 * 1024;
const MAX_MODEL_BYTES = 1024 * 1024 * 1024;

export interface LocalModelReader {
  readonly uri: string;
  readonly exists: boolean;
  readonly size: number | null;
  open(): { readBytes(length: number): Uint8Array | Promise<Uint8Array>; close(): void };
}
export type ModelAdmission =
  | { available: true; uri: string; modelId: string }
  | { available: false; reason: "model_not_installed" | "model_unreadable" | "device_not_admitted" | "invalid_model" };

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
    const header = await handle.readBytes(4);
    if (header.length !== 4 || header[0] !== 0x47 || header[1] !== 0x47 ||
        header[2] !== 0x55 || header[3] !== 0x46)
      return { available: false, reason: "invalid_model" };
    return { available: true, uri: file.uri, modelId: "Qwen2.5-0.5B-Instruct-Q4_K_M" };
  } catch {
    return { available: false, reason: "model_unreadable" };
  } finally {
    try { handle?.close(); } catch { /* best effort */ }
  }
}
