// The original source Apollo investigated (exact text / URL / fields / raw device evidence), kept unaltered
// on this device only, one key per case. A copy of what the person checked is kept for 24 hours, then deleted
// (domain/heldCopies.ts): reading it past then deletes it and leaves a note of when, so it is never saved again.
// Deleted with the case and on full data wipe.
import { heldCopyDue } from "@/src/domain/heldCopies";
import { storage } from "@/src/utils/storage";

export type OriginalSourceKind = "email" | "text" | "link" | "website" | "screenshot" | "call" | "app" | "file" | "account" | "device" | "network";

export interface OriginalSource {
  kind: OriginalSourceKind;
  /** Exact fields as captured (e.g. From, Subject, Number). */
  fields?: { label: string; value: string }[];
  /** Exact original text/body. */
  text?: string | null;
  /** Exact original link as entered or received. */
  url?: string | null;
  /** Exact raw record reported by the device / OS (network, DNS, enforcement, device signals). */
  data?: unknown;
  capturedAt: string;
  /** Where the copy came from: captured on this device, or downloaded once from the investigation. */
  origin: "this_device" | "investigation";
}

/** What is left where a held copy was deleted: when, and nothing of the copy. */
interface DeletedCopy { deletedAt: string }

const key = (caseKey: string) => `apollo.original.v1.${caseKey}`;
const listeners = new Set<() => void>();
export function subscribeOriginalSource(l: () => void) { listeners.add(l); return () => { listeners.delete(l); }; }

export type OriginalSourceInput = Omit<OriginalSource, "capturedAt" | "origin"> & Partial<Pick<OriginalSource, "capturedAt" | "origin">>;

async function read(caseKey: string): Promise<OriginalSource | DeletedCopy | null> {
  try { const raw = await storage.getItem<string | null>(key(caseKey), null); return raw ? (JSON.parse(raw) as OriginalSource | DeletedCopy) : null; }
  catch { return null; }
}

export async function saveOriginalSource(caseKeys: (string | null | undefined)[], source: OriginalSourceInput) {
  const record: OriginalSource = { capturedAt: new Date().toISOString(), origin: "this_device", ...source };
  if (heldCopyDue(record)) return; // already older than 24 hours: never kept
  try {
    // Kept once per case; a copy deleted after its 24 hours is never saved again.
    for (const k of caseKeys) if (k && !(await read(k))) await storage.setItem(key(k), JSON.stringify(record));
    listeners.forEach((l) => l());
  } catch (e) { console.warn("[originalSource] could not save original source:", e); }
}

export async function getOriginalSource(caseKey: string, now: number = Date.now()): Promise<OriginalSource | null> {
  const found = await read(caseKey);
  if (!found || "deletedAt" in found) return null;
  if (heldCopyDue(found, now)) {
    await storage.setItem(key(caseKey), JSON.stringify({ deletedAt: new Date(now).toISOString() } satisfies DeletedCopy));
    listeners.forEach((l) => l());
    return null;
  }
  return found;
}

/** When ApolloSG deleted its copy of this case's original after 24 hours; null when it never held one, or still does. */
export async function originalSourceDeletedAt(caseKey: string): Promise<string | null> {
  const found = await read(caseKey);
  return found && "deletedAt" in found ? found.deletedAt : null;
}

export async function deleteOriginalSource(caseKey: string) { await storage.removeItem(key(caseKey)); listeners.forEach((l) => l()); }
