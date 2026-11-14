/** Fast on-device model admission: private file, plausible size, RAM and GGUF header.
 * Full-file SHA-256 was removed from startup and installation by product decision.
 * Native model loading remains required before the app starts.
 */
import { ACTIVE_MODEL, type ModelProfile } from "./modelProfiles.ts";
export const CANDIDATE_FILE = ACTIVE_MODEL.filename;
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
  profile: ModelProfile = ACTIVE_MODEL,
): Promise<ModelAdmission> {
  if (!file.exists) return { available: false, reason: "model_not_installed" };
  if (!totalMemory || !Number.isFinite(totalMemory) || totalMemory < profile.minimumTotalRamBytes)
    return { available: false, reason: "device_not_admitted" };
  if (!/^file:\/\/\//i.test(file.uri) || !file.uri.endsWith("/" + profile.filename) ||
      !Number.isFinite(file.size) || file.size === null ||
      file.size < MIN_MODEL_BYTES || file.size > Math.max(MAX_MODEL_BYTES, profile.expectedBytes ?? 0) || (profile.qualification === "pending_physical_qualification" && profile.expectedBytes !== null && file.size !== profile.expectedBytes))
    return { available: false, reason: "invalid_model" };
  let handle: ReturnType<LocalModelReader["open"]> | null = null;
  try {
    handle = file.open();
    const header = await handle.readBytes(4);
    if (header.length !== 4 || header[0] !== 0x47 || header[1] !== 0x47 ||
        header[2] !== 0x55 || header[3] !== 0x46)
      return { available: false, reason: "invalid_model" };
    return { available: true, uri: file.uri, modelId: profile.modelId };
  } catch {
    return { available: false, reason: "model_unreadable" };
  } finally {
    try { handle?.close(); } catch { /* best effort */ }
  }
}
