/**
 * Stores user-confirmed verdicts for device settings Apollo can't read programmatically
 * (e.g., "Installing apps from outside the store", "Accessibility access", "Auto Blocker").
 *
 * When a user taps "Looks good" or "Needs attention" on a Check-manually item,
 * the verdict is persisted here and reflected in the device protection UI.
 */
import { storage } from "@/src/utils/storage";

const KEY = "apollo:manual_check_verdicts";

export type ManualVerdict = "safe" | "concern";

export interface ManualCheckEntry {
  verdict: ManualVerdict;
  checkedAt: string;
}

export type ManualCheckVerdicts = Record<string, ManualCheckEntry>;

let cache: ManualCheckVerdicts | null = null;

export async function loadManualVerdicts(): Promise<ManualCheckVerdicts> {
  if (cache) return cache;
  const raw = await storage.getItem<string | null>(KEY, null);
  cache = raw ? JSON.parse(raw) : {};
  return cache!;
}

export async function setManualVerdict(settingId: string, verdict: ManualVerdict): Promise<void> {
  const verdicts = await loadManualVerdicts();
  verdicts[settingId] = { verdict, checkedAt: new Date().toISOString() };
  cache = verdicts;
  await storage.setItem(KEY, JSON.stringify(verdicts));
}

export async function clearManualVerdict(settingId: string): Promise<void> {
  const verdicts = await loadManualVerdicts();
  delete verdicts[settingId];
  cache = verdicts;
  await storage.setItem(KEY, JSON.stringify(verdicts));
}

export function getCachedVerdicts(): ManualCheckVerdicts {
  return cache ?? {};
}
