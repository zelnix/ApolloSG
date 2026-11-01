/**
 * Activity Log — persistent on-device store for Apollo's detection, protection and
 * device-security activity. Entries are immutable once recorded: later findings create
 * linked updates rather than rewriting earlier history.
 *
 * Storage: AsyncStorage, JSON-serialised, keyed by day for efficient reads.
 * Device-isolated: entries never leave this device except through the export function.
 * No AI calls.
 */
import * as Crypto from "expo-crypto";
import AsyncStorage from "@react-native-async-storage/async-storage";

// ── Types ────────────────────────────────────────────────────────────────────

export type ActivityType = "check" | "detection" | "protection_action" | "device_change";
export type ActivityOutcome = "success" | "concern" | "failure" | "blocked" | "change" | "baseline" | "restored";

export interface ActivityEntry {
  id: string;
  type: ActivityType;
  /** When the entry was recorded. */
  timestamp: string;
  title: string;
  detail: string;
  /** Who performed it: "Apollo", "Device protection", "System", "User", or a named provider. */
  actor: string;
  outcome: ActivityOutcome;

  // ── Expansion ──
  expandedDetail?: string;
  limitations?: string[];
  beforeValue?: string;
  afterValue?: string;

  // ── Linking ──
  /** PatrolEvent.event_id when this activity relates to a Threat Case. */
  linkedEventId?: string;

  // ── Provenance ──
  source: "patrol_event" | "protection_health" | "device_posture" | "background_check";
  /** When the change was *detected* (may differ from occurrence time). */
  detectedAt?: string;
  /** When it actually happened (only when the actual time is known). */
  occurredAt?: string;

  // ── Grouping (routine successes) ──
  groupKey?: string;

  // ── Metadata ──
  /** Protection gate id, when applicable. */
  gateId?: string;
  /** Device posture check id, when applicable. */
  checkId?: string;
  /** True only when the action/status is *verified* operational, not merely configured. */
  verified?: boolean;
}

// ── Storage ──────────────────────────────────────────────────────────────────

const PREFIX = "apollo.activity.";
const INDEX_KEY = "apollo.activity.__index";
const MAX_DAYS = 90; // retention: 90 days

/** Day key for a timestamp: "2026-11-01". */
function dayOf(iso: string): string {
  return new Date(iso).toISOString().slice(0, 10);
}

async function dayKeys(): Promise<string[]> {
  try {
    const raw = await AsyncStorage.getItem(INDEX_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch { return []; }
}

async function saveDayKeys(keys: string[]): Promise<void> {
  try { await AsyncStorage.setItem(INDEX_KEY, JSON.stringify(keys)); } catch { /* silent */ }
}

async function dayEntries(day: string): Promise<ActivityEntry[]> {
  try {
    const raw = await AsyncStorage.getItem(PREFIX + day);
    return raw ? (JSON.parse(raw) as ActivityEntry[]) : [];
  } catch { return []; }
}

async function saveDayEntries(day: string, entries: ActivityEntry[]): Promise<void> {
  try { await AsyncStorage.setItem(PREFIX + day, JSON.stringify(entries)); } catch { /* silent */ }
}

// ── Public API ───────────────────────────────────────────────────────────────

/** Record a new activity entry. The entry is immutable once stored. */
export async function recordActivity(entry: Omit<ActivityEntry, "id">): Promise<ActivityEntry> {
  const full: ActivityEntry = { ...entry, id: Crypto.randomUUID() };
  const day = dayOf(full.timestamp);
  const existing = await dayEntries(day);
  existing.push(full);
  await saveDayEntries(day, existing);

  // Update index
  const keys = await dayKeys();
  if (!keys.includes(day)) {
    keys.push(day);
    keys.sort().reverse(); // newest first
    await saveDayKeys(keys);
  }

  // Retention: drop days older than MAX_DAYS
  const cutoff = new Date(Date.now() - MAX_DAYS * 86_400_000).toISOString().slice(0, 10);
  const expired = keys.filter((k) => k < cutoff);
  if (expired.length) {
    for (const k of expired) {
      try { await AsyncStorage.removeItem(PREFIX + k); } catch { /* silent */ }
    }
    await saveDayKeys(keys.filter((k) => k >= cutoff));
  }

  return full;
}

/** Record a batch of activity entries efficiently. */
export async function recordActivities(entries: Omit<ActivityEntry, "id">[]): Promise<void> {
  if (!entries.length) return;
  // Group by day
  const byDay = new Map<string, Omit<ActivityEntry, "id">[]>();
  for (const e of entries) {
    const day = dayOf(e.timestamp);
    const list = byDay.get(day) ?? [];
    list.push(e);
    byDay.set(day, list);
  }
  const keys = await dayKeys();
  for (const [day, batch] of byDay) {
    const existing = await dayEntries(day);
    for (const e of batch) existing.push({ ...e, id: Crypto.randomUUID() });
    await saveDayEntries(day, existing);
    if (!keys.includes(day)) keys.push(day);
  }
  keys.sort().reverse();
  await saveDayKeys(keys);
}

/** Load all activity entries, newest first. */
export async function loadAllActivities(): Promise<ActivityEntry[]> {
  const keys = await dayKeys();
  const all: ActivityEntry[] = [];
  for (const k of keys) {
    const entries = await dayEntries(k);
    all.push(...entries);
  }
  all.sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp));
  return all;
}

/** Delete specific entries by id. Returns the count deleted. Does NOT delete linked Threat Cases. */
export async function deleteActivities(ids: Set<string>): Promise<number> {
  if (!ids.size) return 0;
  const keys = await dayKeys();
  let removed = 0;
  for (const k of keys) {
    const entries = await dayEntries(k);
    const kept = entries.filter((e) => !ids.has(e.id));
    if (kept.length < entries.length) {
      removed += entries.length - kept.length;
      if (kept.length) await saveDayEntries(k, kept);
      else {
        try { await AsyncStorage.removeItem(PREFIX + k); } catch { /* silent */ }
      }
    }
  }
  if (removed) {
    const remaining = await dayKeys();
    const live: string[] = [];
    for (const k of remaining) {
      const entries = await dayEntries(k);
      if (entries.length) live.push(k);
    }
    await saveDayKeys(live);
  }
  return removed;
}

/** Export all entries as a flat array (for inclusion in patrol export). */
export async function exportActivities(): Promise<ActivityEntry[]> {
  return loadAllActivities();
}

/** Remove ALL activity entries. */
export async function clearAllActivities(): Promise<void> {
  const keys = await dayKeys();
  for (const k of keys) {
    try { await AsyncStorage.removeItem(PREFIX + k); } catch { /* silent */ }
  }
  await saveDayKeys([]);
}

// ── Deduplication helper ─────────────────────────────────────────────────────

/** Check if an entry with the given groupKey already exists on this day. */
export async function hasTodayEntry(groupKey: string): Promise<boolean> {
  const today = dayOf(new Date().toISOString());
  const entries = await dayEntries(today);
  return entries.some((e) => e.groupKey === groupKey);
}
