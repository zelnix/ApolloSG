import { useSyncExternalStore } from "react";

import type { ProtectionHealthSnapshot } from "./healthTypes";
import { onProtectionHealthUpdate } from "@/src/store/activityRecorder";

const IDS = ["site", "text", "call", "email", "link", "file", "app", "device", "account", "network"] as const;
const TITLES: Record<(typeof IDS)[number], string> = { site: "Site protection", text: "Text protection", call: "Call protection", email: "Email checks", link: "Link checks", file: "File checks", app: "App checks", device: "Device checks", account: "Account checks", network: "Internet checks" };

let snapshot: ProtectionHealthSnapshot = {
  revision: 0, checkedAt: null, trigger: null, checking: false, capabilities: [], protection: null, permissions: [], network: null, ruleBundle: null, lastCheckFailure: null,
  gates: IDS.map((id) => ({ id, title: TITLES[id], purpose: "ApolloSG is preparing this protection.", currentHelp: "Checking current status.", statusLabel: "Check in progress" as const, tone: "neutral" as const, capability: { automatic: { kind: (id === "site" ? "enforcement" : "event_driven") as "enforcement" | "event_driven", state: "checking" as const }, onDemand: id === "site" ? undefined : { state: "ready" as const, action: { id: "open_check_it", label: "Open Check It" } } }, resolved: { coverageState: "unknown" as const, isAutomatic: id === "site" || id === "network" } })),
};
const listeners = new Set<() => void>();

export function protectionHealthSnapshot(): ProtectionHealthSnapshot { return snapshot; }
export function publishProtectionHealth(next: ProtectionHealthSnapshot): void {
  snapshot = next;
  listeners.forEach((listener) => listener());
  // Record activity for the Patrol History unified timeline
  try { onProtectionHealthUpdate(next); } catch { /* non-fatal: activity logging must never break the health pipeline */ }
}
export function subscribeProtectionHealth(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
export function useProtectionHealth(): ProtectionHealthSnapshot {
  return useSyncExternalStore(subscribeProtectionHealth, protectionHealthSnapshot, protectionHealthSnapshot);
}