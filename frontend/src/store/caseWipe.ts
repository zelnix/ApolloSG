import { investigationAudit } from "@/src/investigation/auditStore";
// An administrator removed every threat case (services/case_wipe.py). The server records the reset once; each device
// then clears its own copies from before it: Threats, saved checks and reports, check history, device-held
// investigations and the originals kept with them. Anything this device recorded after the reset stays.
import AsyncStorage from "@react-native-async-storage/async-storage";

import type { PatrolEvent } from "@/src/domain/types";
import { clearAllImageEvidence } from "./imageEvidence";
import { clearAllOriginalEmails } from "./originalEmail";
import { deleteAllArchivedEvidence } from "@/src/investigation/evidenceArchive";

export interface CaseWipe { wipeId: string | null; at: string | null }
export const CASE_WIPE_APPLIED_KEY = "apollo.case_wipe.applied.v1";

/** Local stores that hold cases, checks or their originals. */
const CASE_STORE_PREFIXES = [
  "apollo.savedchecks.", "apollo.checkhistory.", "apollo.email_checks.", "apollo.appreports.", "apollo.report_progress.",
  "apollo.original.", "apollo.device.investigation", "apollo.investigation.", "apollo.device.evidenceManifest.",
];

export function isCaseStoreKey(key: string): boolean {
  return CASE_STORE_PREFIXES.some((p) => key.startsWith(p));
}

/** Events from before the reset go; anything recorded after it stays. */
export function eventsAfterWipe(events: PatrolEvent[], at: string): PatrolEvent[] {
  const cut = Date.parse(at);
  return events.filter((e) => Date.parse(e.occurred_at) > cut);
}

export async function clearLocalCaseStores(): Promise<void> {
  await investigationAudit.clear();
  await deleteAllArchivedEvidence();
  await clearAllImageEvidence().catch(() => undefined);
  await clearAllOriginalEmails().catch(() => undefined);
  const keys = (await AsyncStorage.getAllKeys()).filter(isCaseStoreKey);
  if (keys.length) await AsyncStorage.multiRemove(keys);
}
