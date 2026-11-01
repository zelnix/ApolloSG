// The original source Apollo investigated (exact text / URL / fields / raw device evidence), kept unaltered on this
// device only, one key per case. Kept until the person deletes it, the check, or all their data: no clock deletes it on
// the phone (owner's rule, 2026-11-01). A later supply of headers or text only fills in what the saved copy is missing
// (domain/originalMerge.ts). A note left where an earlier version of ApolloSG deleted a copy after 24 hours is
// replaced by the next copy saved for that case.
import { enrichOriginal, sameOriginal } from "@/src/domain/originalMerge";
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
  /** Where the copy came from: captured on this device, or downloaded from the investigation. */
  origin: "this_device" | "investigation";
}

/** What an earlier version of ApolloSG left where it deleted a held copy after 24 hours: when, and nothing of the copy. */
interface DeletedCopy { deletedAt: string }

const key = (caseKey: string) => `apollo.original.v1.${caseKey}`;
const listeners = new Set<() => void>();
export function subscribeOriginalSource(l: () => void) { listeners.add(l); return () => { listeners.delete(l); }; }

export type OriginalSourceInput = Omit<OriginalSource, "capturedAt" | "origin"> & Partial<Pick<OriginalSource, "capturedAt" | "origin">>;

async function read(caseKey: string): Promise<OriginalSource | DeletedCopy | null> {
  try { const raw = await storage.getItem<string | null>(key(caseKey), null); return raw ? (JSON.parse(raw) as OriginalSource | DeletedCopy) : null; }
  catch { return null; }
}

/** Save the original for these case keys: a new record where none is kept, else the kept one enriched (never replaced). */
export async function saveOriginalSource(caseKeys: (string | null | undefined)[], source: OriginalSourceInput) {
  const record: OriginalSource = { capturedAt: new Date().toISOString(), origin: "this_device", ...source };
  let changed = false;
  try {
    for (const k of caseKeys) {
      if (!k) continue;
      const found = await read(k);
      const next = found && !("deletedAt" in found) ? enrichOriginal(found, record) : record;
      if (found && !("deletedAt" in found) && sameOriginal(found, next)) continue;
      await storage.setItem(key(k), JSON.stringify(next));
      changed = true;
    }
    if (changed) listeners.forEach((l) => l());
  } catch (e) { console.warn("[originalSource] could not save original source:", e); }
}

export async function getOriginalSource(caseKey: string): Promise<OriginalSource | null> {
  const found = await read(caseKey);
  return !found || "deletedAt" in found ? null : found;
}

/** When an earlier version of ApolloSG deleted its copy of this case's original after 24 hours; null when it didn't. */
export async function originalSourceDeletedAt(caseKey: string): Promise<string | null> {
  const found = await read(caseKey);
  return found && "deletedAt" in found ? found.deletedAt : null;
}

export async function deleteOriginalSource(caseKey: string) { await storage.removeItem(key(caseKey)); listeners.forEach((l) => l()); }
