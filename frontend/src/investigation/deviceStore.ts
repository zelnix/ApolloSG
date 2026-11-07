/**
 * Device-permanent investigation store.
 *
 * Completed Magnum DI investigations are committed here once the device has
 * validated that the full response, sources, turns and evidence metadata are
 * present.  This is the ONLY permanent store for completed Threat Cases.
 *
 * The server holds investigation data only while Magnum DI is actively working.
 * After the device confirms a successful local commit the server purges its copy.
 *
 * Storage layout (AsyncStorage):
 *   apollo.device.investigations.index   → DeviceInvestigationMeta[]
 *   apollo.device.investigation.{caseId} → DeviceInvestigation
 */
import { storage } from "@/src/utils/storage";
import type { ServerCopy } from "@/src/domain/serverCopyNote";
import type { EvidenceItem, HigginsResponse, SourceReference, TurnCommit } from "./types";

// ── Public types ────────────────────────────────────────────────────────

export interface DeviceInvestigation {
  /** Server case ID (still used as the canonical key) */
  caseId: string;
  gates: string[];
  status: string;
  createdAt: string;
  completedAt: string;
  /** The user's original question / submission label */
  question: string;
  /** Complete Higgins response — powers Overview tab */
  response: HigginsResponse;
  /** Cited sources — powers Evidence tab */
  sources: SourceReference[];
  /** Follow-up turns — powers History tab */
  turns: TurnCommit[];
  /** Evidence item metadata (content bytes are not stored here) */
  evidenceItems: EvidenceItem[];
  /** Patrol event ID this investigation was projected into */
  patrolEventId: string | null;
  /** ISO timestamp of the local commit */
  committedAt: string;
  /** Who settled the result: "magnum_di" or a TC Hawkeye route ("tc_flyby_official", "tc_flyby_kb", "tc_flyby_search"). */
  answeredBy?: string | null;
  /** The rule that settled it, as one plain sentence. Absent on results saved before it was recorded. */
  settledReason?: import("./types").SettledReason | null;
  /** An outside source behind the result was simulated in the preview. Everything else ran as in production. */
  simulated?: boolean;
  /** When the server's copy of what was sent was removed, or the latest time it will be. Absent on older results. */
  serverCopy?: ServerCopy;
  /** Who started it, as the case recorded: the person ("user") or Apollo ("apollo"). Absent when not recorded. */
  origin?: import("./types").CaseOrigin | null;
}

export interface DeviceInvestigationMeta {
  caseId: string;
  gates: string[];
  status: string;
  createdAt: string;
  completedAt: string;
  committedAt: string;
  headline: string;
  assessment: string;
  attention: string;
  patrolEventId: string | null;
}

// ── Storage keys ────────────────────────────────────────────────────────

const INDEX_KEY = "apollo.device.investigations.index";
const caseKey = (caseId: string) => `apollo.device.investigation.${caseId}`;

// ── Change listeners (same pattern as imageEvidence / originalSource) ───

const listeners = new Set<() => void>();
export function subscribeDeviceInvestigations(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
function notify() { listeners.forEach((l) => l()); }

// ── Index helpers ───────────────────────────────────────────────────────

async function loadIndex(): Promise<DeviceInvestigationMeta[]> {
  const raw = await storage.getItem<string | null>(INDEX_KEY, null).catch(() => null);
  try { return raw ? (JSON.parse(raw) as DeviceInvestigationMeta[]) : []; } catch { return []; }
}

async function saveIndex(index: DeviceInvestigationMeta[]): Promise<void> {
  await storage.setItem(INDEX_KEY, JSON.stringify(index));
}

function metaFrom(inv: DeviceInvestigation): DeviceInvestigationMeta {
  return {
    caseId: inv.caseId,
    gates: inv.gates,
    status: inv.status,
    createdAt: inv.createdAt,
    completedAt: inv.completedAt,
    committedAt: inv.committedAt,
    headline: (inv.response.overview ?? "").slice(0, 160),
    assessment: inv.response.assessment,
    attention: inv.response.attention,
    patrolEventId: inv.patrolEventId,
  };
}

// ── Validation ──────────────────────────────────────────────────────────

/** Returns null if the investigation is complete enough to commit, or an error string. */
export function validateCompleteness(inv: Partial<DeviceInvestigation>): string | null {
  if (!inv.caseId) return "Missing caseId";
  if (!inv.response) return "Missing investigation response";
  if (!inv.response.overview) return "Response has no overview";
  if (!inv.response.assessment) return "Response has no assessment";
  if (!inv.completedAt) return "Missing completedAt timestamp";
  return null;
}

// ── CRUD ────────────────────────────────────────────────────────────────

/**
 * Commit a completed investigation to permanent device storage.
 * Validates completeness before writing.  Idempotent — re-committing
 * the same caseId overwrites the previous snapshot.
 */
export async function commitInvestigation(inv: DeviceInvestigation): Promise<void> {
  const error = validateCompleteness(inv);
  if (error) throw new Error(`Cannot commit investigation: ${error}`);

  // Write the full snapshot
  await storage.setItem(caseKey(inv.caseId), JSON.stringify(inv));

  // Update the index (upsert)
  const index = await loadIndex();
  const existing = index.findIndex((m) => m.caseId === inv.caseId);
  const meta = metaFrom(inv);
  if (existing >= 0) index[existing] = meta;
  else index.unshift(meta); // newest first
  await saveIndex(index);
  notify();
}

/** Retrieve a single completed investigation by caseId. */
export async function getInvestigation(caseId: string): Promise<DeviceInvestigation | null> {
  const raw = await storage.getItem<string | null>(caseKey(caseId), null).catch(() => null);
  try { return raw ? (JSON.parse(raw) as DeviceInvestigation) : null; } catch { return null; }
}

/** List all completed investigation summaries, newest first. */
export async function listInvestigations(): Promise<DeviceInvestigationMeta[]> {
  return loadIndex();
}

/**
 * Delete a completed investigation from permanent device storage.
 * Removes both the full snapshot and the index entry.
 * Caller should also clean up related stores (imageEvidence, originalSource, reportProgress).
 */
export async function deleteInvestigation(caseId: string): Promise<boolean> {
  const index = await loadIndex();
  const filtered = index.filter((m) => m.caseId !== caseId);
  if (filtered.length === index.length) return false; // not found
  await saveIndex(filtered);
  await storage.removeItem(caseKey(caseId)).catch(() => undefined);
  notify();
  return true;
}

/** Check whether a given caseId has a committed local investigation. */
export async function hasInvestigation(caseId: string): Promise<boolean> {
  const raw = await storage.getItem<string | null>(caseKey(caseId), null).catch(() => null);
  return raw !== null;
}

/** The server confirmed it deleted its copy of this check: record when, for the note on the result. */
export async function recordServerCopyRemoved(caseId: string, removedAt: string): Promise<void> {
  const inv = await getInvestigation(caseId);
  if (!inv || inv.serverCopy?.removedAt) return;
  await storage.setItem(caseKey(caseId), JSON.stringify({ ...inv, serverCopy: { leavesBy: inv.serverCopy?.leavesBy ?? null, removedAt } }));
  notify();
}

// ── Confirm-commit queue ────────────────────────────────────────────────
// After committing locally the device must tell the server to purge.
// If the server call fails, the caseId is queued for background retry.

const CONFIRM_QUEUE_KEY = "apollo.device.investigations.confirm_queue";

async function loadConfirmQueue(): Promise<string[]> {
  const raw = await storage.getItem<string | null>(CONFIRM_QUEUE_KEY, null).catch(() => null);
  try { return raw ? (JSON.parse(raw) as string[]) : []; } catch { return []; }
}

async function saveConfirmQueue(queue: string[]): Promise<void> {
  await storage.setItem(CONFIRM_QUEUE_KEY, JSON.stringify(queue));
}

export async function enqueueConfirmCommit(caseId: string): Promise<void> {
  const queue = await loadConfirmQueue();
  if (!queue.includes(caseId)) {
    queue.push(caseId);
    await saveConfirmQueue(queue);
  }
}

export async function dequeueConfirmCommit(caseId: string): Promise<void> {
  const queue = await loadConfirmQueue();
  await saveConfirmQueue(queue.filter((id) => id !== caseId));
}

export async function pendingConfirmCommits(): Promise<string[]> {
  return loadConfirmQueue();
}
