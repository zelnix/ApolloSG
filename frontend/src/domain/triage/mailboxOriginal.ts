// The provider's exact original is parsed and hashed on the device through the same path as an .eml file.
// No generated headers, reconstructed .eml, or provider results become a synthetic original.
import { b64ToBinary, MAX_ORIGINAL_BYTES } from "./emailOriginal.ts";

export interface MailboxOriginalPayload { raw_base64url?: string | null; original_unavailable_reason?: string | null }

export function mailboxOriginalLimitation(reason: string | null): string | null {
  if (!reason) return null;
  const why = reason === "original_too_large" ? "The original email exceeds the supported 10 MB size."
    : reason === "original_unreadable" ? "The mailbox original could not be read."
    : "The mailbox did not return the original email.";
  return `${why} This check uses the available copy; full-header authentication remains unavailable.`;
}

export async function readMailboxOriginal<T>(payload: MailboxOriginalPayload, parse: (binary: string) => Promise<T>): Promise<{ original: T | null; limitation: string | null }> {
  const raw = payload.raw_base64url;
  if (!raw) return { original: null, limitation: payload.original_unavailable_reason ?? "original_not_provided" };
  if (raw.length > 4 * Math.ceil(MAX_ORIGINAL_BYTES / 3)) return { original: null, limitation: "original_too_large" };
  if (!/^[A-Za-z0-9_-]+={0,2}$/.test(raw) || raw.replace(/=+$/, "").length % 4 === 1)
    return { original: null, limitation: "original_unreadable" };
  const binary = b64ToBinary(raw);
  if (!binary.length || binary.length > MAX_ORIGINAL_BYTES) return { original: null, limitation: "original_too_large" };
  try { return { original: await parse(binary), limitation: null }; }
  catch { return { original: null, limitation: "original_unreadable" }; }
}
