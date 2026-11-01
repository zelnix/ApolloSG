// Local-only image evidence: the original image (never uploaded) next to the copy Apollo sent.
// Files live in the app's document folder for 24 hours from when they were kept (domain/heldCopies.ts), then both
// pictures are deleted — on access and by the clean-up sweep — and earlier with the case.
import * as FS from "expo-file-system/legacy";
import { Platform } from "react-native";

import { heldCopyExpired } from "@/src/domain/heldCopies";
import { storage } from "@/src/utils/storage";

export interface ImageEvidenceRecord {
  id: string;
  /** Cases this evidence belongs to (Patrol event id and/or investigation case id). */
  caseKeys: string[];
  /** Original image as chosen by the user — on this device only. */
  originalUri: string | null;
  /** Exact copy sent for analysis (cropped and/or credentials blacked out). */
  sentUri: string;
  redactedRegions: number;
  cropped: boolean;
  /** False when on-device text recognition was unavailable, so nothing could be blacked out. */
  checked: boolean;
  createdAt: string;
  /** Set when the user removed the original from this device. */
  originalRemovedAt?: string;
}

const KEY = "apollo.image_evidence.v1";
const DIR = "apollo-evidence";
const listeners = new Set<() => void>();

const evidenceDirUri = () => (FS.documentDirectory ?? "") + DIR + "/";

async function ensureDir() {
  const uri = evidenceDirUri();
  const info = await FS.getInfoAsync(uri);
  if (!info.exists) await FS.makeDirectoryAsync(uri, { intermediates: true });
  return uri;
}

function keepFile(uri: string, name: string): string {
  if (Platform.OS === "web") return uri;
  // We run this synchronously via a void-async wrapper so the caller stays sync-shaped.
  // The copy is awaited internally.
  const ext = uri.split("?")[0].split(".").pop()?.toLowerCase();
  const destName = `${name}.${ext && ext.length <= 4 ? ext : "jpg"}`;
  // Return a promise that resolves to the dest uri — callers await saveImageEvidence which is async.
  return `${(FS.documentDirectory ?? "")}${DIR}/${destName}`;
}

async function keepFileAsync(uri: string, name: string): Promise<string> {
  if (Platform.OS === "web") return uri;
  const dir = await ensureDir();
  const ext = uri.split("?")[0].split(".").pop()?.toLowerCase();
  const destName = `${name}.${ext && ext.length <= 4 ? ext : "jpg"}`;
  const destUri = dir + destName;
  await FS.copyAsync({ from: uri, to: destUri });
  return destUri;
}

async function deleteFile(uri: string | null) {
  if (!uri || Platform.OS === "web" || !uri.startsWith(evidenceDirUri())) return;
  try { await FS.deleteAsync(uri, { idempotent: true }); } catch { /* already gone */ }
}

async function readAll(): Promise<ImageEvidenceRecord[]> {
  try { const parsed = JSON.parse((await storage.getItem(KEY, "[]")) ?? "[]"); return Array.isArray(parsed) ? parsed : []; }
  catch { return []; }
}
async function writeAll(next: ImageEvidenceRecord[]) { await storage.setItem(KEY, JSON.stringify(next)); listeners.forEach((l) => l()); }

export function subscribeImageEvidence(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }

export async function saveImageEvidence(
  prepared: { originalUri: string | null; imageUri: string; redactedRegions: number; cropped: boolean; decision: string },
  caseKeys: (string | null | undefined)[],
): Promise<ImageEvidenceRecord | null> {
  const keys = caseKeys.filter((k): k is string => !!k);
  if (!keys.length) return null;
  try {
    const id = `img_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
    const record: ImageEvidenceRecord = {
      id, caseKeys: keys,
      originalUri: prepared.originalUri ? await keepFileAsync(prepared.originalUri, `${id}_original`) : null,
      sentUri: await keepFileAsync(prepared.imageUri, `${id}_sent`),
      redactedRegions: prepared.redactedRegions, cropped: prepared.cropped,
      checked: true, createdAt: new Date().toISOString(),
    };
    await writeAll([record, ...(await readAll())]);
    return record;
  } catch (e) {
    console.warn("[imageEvidence] could not keep image evidence:", e);
    return null;
  }
}

export async function listImageEvidence(caseKey: string): Promise<ImageEvidenceRecord[]> {
  await sweepImageEvidence();
  return (await readAll()).filter((r) => r.caseKeys.includes(caseKey));
}

/** Deletes every picture kept for more than 24 hours (both the original and the copy that was sent). */
export async function sweepImageEvidence(now: number = Date.now()): Promise<number> {
  const all = await readAll();
  const due = all.filter((r) => heldCopyExpired(r.createdAt, now));
  if (!due.length) return 0;
  for (const r of due) { await deleteFile(r.originalUri); await deleteFile(r.sentUri); }
  await writeAll(all.filter((r) => !due.includes(r)));
  return due.length;
}

/** Deletes only the on-device original; the sent copy and notes stay in the case. */
export async function removeOriginal(id: string) {
  const all = await readAll();
  const r = all.find((x) => x.id === id);
  if (!r?.originalUri) return;
  await deleteFile(r.originalUri);
  await writeAll(all.map((x) => (x.id === id ? { ...x, originalUri: null, originalRemovedAt: new Date().toISOString() } : x)));
}

/** Deletes the evidence files when the case is deleted. */
export async function deleteImageEvidenceFor(caseKey: string) {
  const all = await readAll();
  const [gone, kept] = [all.filter((r) => r.caseKeys.includes(caseKey)), all.filter((r) => !r.caseKeys.includes(caseKey))];
  if (!gone.length) return;
  for (const r of gone) { await deleteFile(r.originalUri); await deleteFile(r.sentUri); }
  await writeAll(kept);
}

export async function clearAllImageEvidence() {
  if (Platform.OS !== "web") {
    try { await FS.deleteAsync(evidenceDirUri(), { idempotent: true }); } catch { /* best effort */ }
  }
  await writeAll([]);
}
