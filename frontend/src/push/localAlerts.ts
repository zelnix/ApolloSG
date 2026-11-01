// Derive local notifications only from accepted device observations; never create an enforcement claim.
import { incompleteOnly } from "../domain/luddish/present.ts";
import { eventHasPacketProof } from "../domain/packetEvidence.ts";
import { stateHeadline } from "../domain/threatSubject.ts";
import type { PatrolEvent } from "../domain/types";
import type { ProtectionStatus } from "../security/SecurityPlatformAdapter";
import type { LocalAlert } from "./notifications";
import { notificationSummary } from "./notificationText.ts";

export function eventLocalAlert(event: PatrolEvent): LocalAlert | null {
  if (event.status === "resolved" || event.status === "trusted") return null;
  // A check that couldn't run is recorded, never alerted as a threat.
  if (incompleteOnly(event)) return null;

  // Allow notifications for:
  // 1. All background events (existing behaviour)
  // 2. Connection-category events regardless of background flag (existing behaviour)
  // 3. Investigation-based events with actionable findings (barking/biting) — these represent
  //    high-risk email or message investigations that warrant notification even when the check
  //    was initiated manually.
  const isInvestigationFinding = !!event.investigation_case_id && (event.state === "barking" || event.state === "biting");
  if (!event.background && event.category !== "connection" && !isInvestigationFinding) return null;

  // Deep-link straight to this specific Patrol event (focus=alert pre-selects it so Higgins can answer
  // about exactly this finding) — never a generic tab (standing message requirement).
  // The body is a purpose-built short summary, never the full Higgins explanation (that stays in the case).
  const actionUrl = `/patrol/${encodeURIComponent(event.event_id)}?focus=alert`;
  if (event.state === "biting") {
    if (!event.verified_block || event.status !== "blocked" || !eventHasPacketProof(event)) return null;
    return { title: stateHeadline("biting", event), body: notificationSummary(event), channel: "apollo_alerts", actionUrl };
  }
  if (event.state === "barking") return { title: stateHeadline("barking", event), body: notificationSummary(event), channel: "apollo_alerts", actionUrl };
  if (event.state === "growling" || event.state === "ears_up") return { title: stateHeadline(event.state, event), body: notificationSummary(event), channel: "apollo_alerts", actionUrl };
  return null;
}

export function protectionLocalAlert(previous: ProtectionStatus, observed: ProtectionStatus): LocalAlert | null {
  if (previous.operational === observed.operational || previous.requested !== observed.requested) return null;
  // Protection health is the Site Gate — deep-link straight to that gate's details, not the generic tab.
  if (observed.operational && observed.running && observed.lastVerified) return {
    title: "Apollo protection restored", body: "The device has confirmed protection is running again.", channel: "apollo_alerts", actionUrl: "/(tabs)/guard?gate=site",
  };
  if (observed.requested && !observed.operational) return {
    title: "Higgins: Protection needs attention", body: observed.degradedReason ?? "Apollo could not confirm website protection is running. Open Protection to review it.", channel: "apollo_alerts", actionUrl: "/(tabs)/guard?gate=site",
  };
  return null;
}