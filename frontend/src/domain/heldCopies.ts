// How long ApolloSG keeps its own copy of what was checked on this phone: the copied text, an email's body and fields,
// an .eml file and pictures. 24 hours from when the copy was made, then it is deleted — on access and by the clean-up
// sweep (store/heldCopySweep.ts). This is ApolloSG's copy only: the message in Gmail, Messages or any other app is
// never touched. Findings and reports are kept as before. Apollo's own device readings (a network, DNS or call record
// it observed itself) are its records, not a copy of anyone's material, and are not held copies.
// Mirror: backend services/held_copies.py (the server's copy of a message's text). Pure: no React, unit-tested in node.
export const HELD_COPY_HOURS = 24;
export const HELD_COPY_MS = HELD_COPY_HOURS * 60 * 60 * 1000;

/** The kinds of original that are a copy of what the person checked (OriginalSourceKind). */
export const HELD_COPY_KINDS: ReadonlySet<string> = new Set(["email", "text", "link", "website", "screenshot", "file", "app", "account"]);

/** Past its 24 hours — or with no time recorded, so it can't be shown to be within them. */
export function heldCopyExpired(at: string | null | undefined, now: number = Date.now()): boolean {
  const t = Date.parse(at ?? "");
  return !Number.isFinite(t) || now - t >= HELD_COPY_MS;
}

/** A kept original that is a held copy past its 24 hours. */
export function heldCopyDue(original: { kind: string; capturedAt: string }, now: number = Date.now()): boolean {
  return HELD_COPY_KINDS.has(original.kind) && heldCopyExpired(original.capturedAt, now);
}

/** What the Evidence tab says where the original was: ApolloSG deleted its copy 24 hours after it was made. */
export const HELD_COPY_DELETED = "ApolloSG deleted its copy of the original 24 hours after it was checked. What Apollo found is kept above.";
