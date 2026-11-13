// Privacy & Data — the authoritative, honest inventory of what Apollo stores, where, and for how long,
// plus the local-wipe used by "Delete My Apollo Data". Deletion is driven by the person's explicit request.
import AsyncStorage from "@react-native-async-storage/async-storage";
import { clearAllImageEvidence } from "@/src/store/imageEvidence";
import { clearAllOriginalEmails } from "@/src/store/originalEmail";
import { deleteAllArchivedEvidence } from "@/src/investigation/evidenceArchive";

export type RetentionLocation = "device" | "service";

export interface RetentionItem {
  key: string; // matches the backend inventory category key where applicable
  label: string;
  where: RetentionLocation;
  what: string; // plain-English description of the data
  retention: string; // honest retention statement
}

// The order here mirrors how the screen reads top-to-bottom. `service` items have live counts from
// the backend `/devices/data-inventory` endpoint; `device` items live only on this device.
export const RETENTION_INVENTORY: RetentionItem[] = [
  { key: "higgins_conversations", label: "Higgins conversations", where: "service",
    what: "Your chat with Higgins and anything you deliberately sent him to look at.",
    retention: "Kept until you clear chat or delete your data. When evidence is sent for a check, that copy on ApolloSG's services is erased within 15 minutes — the original and the redacted copy stay on this device until you delete them." },
  { key: "investigations", label: "Investigations & saved reports", where: "service",
    what: "Checks you ran and the reports Higgins produced.",
    retention: "Kept until you delete a report or delete all your data." },
  { key: "patrol_activity", label: "Patrol activity & records", where: "service",
    what: "A summary of what Apollo noticed during patrol — no browsing history or message content.",
    retention: "Kept until you clear Patrol history or delete all your data." },
  { key: "trusted_links", label: "Trusted links", where: "service",
    what: "Exact links you chose to trust.",
    retention: "Kept until you remove the link or delete all your data." },
  { key: "email_monitoring", label: "Email & account monitoring", where: "service",
    what: "A Gmail read-only connection (if you connected one) and the email addresses you asked Apollo to watch for breaches.",
    retention: "Kept until you disconnect, remove the address, or delete all your data. ApolloSG never stores mailbox passwords." },
  { key: "family", label: "Family links & guardians", where: "service",
    what: "People you paired with to share alerts you deliberately send.",
    retention: "Kept until you unpair or delete all your data." },
  { key: "diagnostics", label: "Diagnostics & app signals", where: "service",
    what: "Device registration, protection-health checks and alert delivery records — no personal content.",
    retention: "Kept until you delete all your data." },
  { key: "case_evidence", label: "Evidence for your cases (this device)", where: "device",
    what: "The original item you submitted and the redacted copy ApolloSG sent for a check — text, links, images, original email files (.eml) and device readings.",
    retention: "Never deleted automatically. Both copies stay on this device until you delete the case, remove the original, or delete all your data." },
  { key: "local_only", label: "On this device only", where: "device",
    what: "Your settings, saved checks, recent-check history and preferences stored only on this device.",
    retention: "Never leaves this device. Erased when you delete all your data or uninstall ApolloSG." },
  { key: "screened_calls", label: "Calls Apollo screened (Android)", where: "device",
    what: "The incoming numbers Android passed to Apollo's call screening, with the time and what ApolloSG did. Apollo never reads your call log.",
    retention: "The last 50 calls, for up to 30 days, on this device only. Clear it on Check a number, or delete all your data." },
];

export interface InventoryCategory { key: string; label: string; count: number }
export interface DataInventory { device_id: string; total: number; categories: InventoryCategory[] }

export interface DeleteDataResult { device_id: string; total: number; removed: Record<string, number>; deleted_at: string }

/** Remove every Apollo-owned value from this device's general storage (AsyncStorage).
 *  Uses getAllKeys so nothing is missed as new keys are added over time. The secure device
 *  identity is cleared separately via clearDeviceIdentity(). */
export async function wipeLocalApolloData(): Promise<void> {
  await deleteAllArchivedEvidence();
  await clearAllImageEvidence().catch(() => undefined);
  await clearAllOriginalEmails().catch(() => undefined);
  try {
    const keys = await AsyncStorage.getAllKeys();
    const apolloKeys = keys.filter((k) => k.startsWith("apollo."));
    if (apolloKeys.length) await AsyncStorage.multiRemove(apolloKeys);
  } catch (e) {
    // A failed local wipe must be visible to the caller's honest state, not silently swallowed.
    throw e instanceof Error ? e : new Error("local wipe failed");
  }
}

export const PENDING_DELETE_KEY = "apollo.privacy.pending_delete.v1";
export const CONFIRM_WORD = "DELETE";
