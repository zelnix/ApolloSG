import * as Crypto from "expo-crypto";

import { apiGet } from "@/src/api/client";
import { getDeviceIdentity } from "@/src/auth/deviceIdentity";
import { buildGatesOverview, type EmailMonitorCapability } from "@/src/domain/gates";
import { securityAdapter } from "@/src/security/securityAdapter";
import { MessagingSdk } from "@/src/security/messagingSdk";
import { CallSdk } from "@/src/security/callSdk";
import { NativeCallFailed, recordNativeFailure } from "@/src/security/nativeDiagnostics";
import { pendingAttempt, recordAttempt, clearAttempt, type ActionAttempt } from "@/src/settings/recheck";
import { storage } from "@/src/utils/storage";
import { protectionHealthSnapshot, publishProtectionHealth } from "./healthStore";
import { decideSiteRecovery } from "./recoveryPolicy";
import type { HealthTrigger, ProtectionHealthSnapshot } from "./healthTypes";
import { publishCapabilitySnapshot } from "./capabilityClient";

const DESIRED_KEY = "apollo.protection.on";
let inFlight: Promise<ProtectionHealthSnapshot> | null = null;
let promptInFlight: Promise<ActionAttempt> | null = null;

interface GmailStatusResponse {
  connected: boolean; configured: boolean; monitoring_enabled: boolean; monitor_last_checked_at: string | null;
  monitor_last_success_at: string | null; monitor_last_assessment_at: string | null; monitor_last_error_at: string | null; monitor_state: string;
}

async function readEmailCapability(): Promise<EmailMonitorCapability> {
  const identity = await getDeviceIdentity();
  if (!identity) return { checking: false, configured: true, connected: false, monitoringRequested: false, lastCheckedAt: null, lastSuccessAt: null, lastAssessmentAt: null, lastErrorAt: null };
  try {
    const status = await apiGet<GmailStatusResponse>(`/gmail/status?device_id=${identity.deviceId}`);
    return { checking: status.monitor_state === "checking", configured: status.configured, connected: status.connected, monitoringRequested: status.monitoring_enabled, lastCheckedAt: status.monitor_last_checked_at, lastSuccessAt: status.monitor_last_success_at, lastAssessmentAt: status.monitor_last_assessment_at, lastErrorAt: status.monitor_last_error_at };
  } catch {
    // API request failed — this is "unable to verify", NOT "definitely disconnected".
    // We don't have positive evidence that the email monitor is off; we simply couldn't check.
    // lastErrorAt records when the observation failed so freshness logic can distinguish this.
    return { checking: false, configured: true, connected: null, monitoringRequested: false, lastCheckedAt: null, lastSuccessAt: null, lastAssessmentAt: null, lastErrorAt: new Date().toISOString() };
  }
}

async function collect(trigger: HealthTrigger): Promise<ProtectionHealthSnapshot> {
  const current = protectionHealthSnapshot();
  publishProtectionHealth({ ...current, checking: true, trigger, revision: current.revision + 1 });
  // A failed capability read is recorded and reported as unverified — it is never read as
  // "unsupported" (which would claim the device can't do it) or left looking like a pending check.
  let messagingReadFailed = false;
  let callsReadFailed = false;
  const readMessaging = MessagingSdk.getMessagingCapabilities().catch((error) => {
    messagingReadFailed = true;
    recordNativeFailure("getMessagingCapabilities", error instanceof Error ? error.message : String(error));
    return null;
  });
  const readCalls = CallSdk.getCallProtectionCapabilities().catch((error) => {
    callsReadFailed = true;
    recordNativeFailure("getCallProtectionCapabilities", error instanceof Error ? error.message : String(error));
    return null;
  });
  let [capabilities, protection, permissions, network, messaging, calls, email, desiredSetting, privateDns] = await Promise.all([
    securityAdapter.getCapabilities(), securityAdapter.getProtectionStatus(), securityAdapter.getProtectionPermissions(), securityAdapter.getNetworkStatus(),
    readMessaging, readCalls, readEmailCapability(), storage.getItem<boolean>(DESIRED_KEY, false),
    // Android only: Private DNS decides whether Apollo's website checks see the lookups. Elsewhere there
    // is no such setting, so it is left out rather than reported as "couldn't tell".
    securityAdapter.kind === "android" && securityAdapter.getPrivateDnsStatus ? securityAdapter.getPrivateDnsStatus().catch(() => null) : Promise.resolve(null),
  ]);
  const callAutoCheckEnabled = (await storage.getItem("apollo.call.auto_check", null)) === "true";
  // Security rules: only adapters whose platform can report rule state implement this. A missing
  // method means "Apollo cannot observe this here", which the UI states plainly; a failed read is
  // reported by the adapter as unknown. Neither is ever read as "rules are current".
  const ruleBundle = securityAdapter.getRuleBundleStatus
    ? await securityAdapter.getRuleBundleStatus().catch(() => ({
        observable: true, current: null, expiresAt: null,
        detail: "Apollo couldn't read the state of its Threat Domain List. This isn't a confirmation that it's current.",
      }))
    : null;
  // Gate 8 (Account Breach): fetch backend configuration status. Failure → unavailable, never running.
  let breachLookupConfigured = false;
  try { const acctStatus = await apiGet<{ breach_lookup_configured: boolean }>("/account/status"); breachLookupConfigured = acctStatus.breach_lookup_configured === true; } catch { /* treat as unavailable */ }
  const desiredOn = desiredSetting === true;
  let decision = decideSiteRecovery(desiredOn, protection, permissions);
  if (decision === "start_now") {
    // A start that fails (for example, no Threat Domain List it can trust yet) only affects website
    // protection: the reason stays on that reading and every other Gate still gets its fresh reading.
    const startFailure = await securityAdapter.startProtection().then(() => null, (error: unknown) => {
      const message = error instanceof Error && error.message ? error.message : "Website protection couldn't start.";
      recordNativeFailure("startProtection", message);
      return message;
    });
    [capabilities, protection, permissions, network] = await Promise.all([securityAdapter.getCapabilities(), securityAdapter.getProtectionStatus(), securityAdapter.getProtectionPermissions(), securityAdapter.getNetworkStatus()]);
    if (startFailure && !protection.operational) protection = { ...protection, degradedReason: startFailure };
    decision = decideSiteRecovery(desiredOn, protection, permissions);
  }
  const attempt = await pendingAttempt();
  if (attempt?.kind === "restore_site" && Date.parse(attempt.expiresAt ?? "") <= Date.now()) await clearAttempt();
  else if (attempt?.kind === "restore_site" && (trigger === "foreground" || trigger === "boot")) {
    if (decision === "healthy") await clearAttempt(); else if (trigger === "foreground") await clearAttempt();
  }
  const base = { revision: current.revision + 1, checkedAt: new Date().toISOString(), trigger, checking: false, capabilities, protection, permissions, network, ruleBundle };
  const overview = buildGatesOverview({ platform: securityAdapter.kind, checking: false, protection, permissions, capabilities, messaging, calls, network, email, online: network.isInternetReachable !== false, callAutoCheckEnabled, accountBreachConfigured: breachLookupConfigured, desiredSiteOn: desiredOn, messagingReadFailed, callsReadFailed, privateDns });
  const next: ProtectionHealthSnapshot = { ...base, gates: overview.gates, lastCheckFailure: null };
  publishProtectionHealth(next);
  void publishCapabilitySnapshot({ platform: securityAdapter.kind, adapter: securityAdapter.label, online: network.isInternetReachable, gates: overview.gates, capabilities, protection }).catch(() => undefined);
  return next;
}

export function runProtectionHealthCheck(trigger: HealthTrigger): Promise<ProtectionHealthSnapshot> {
  if (inFlight) return inFlight;
  inFlight = collect(trigger).catch((err) => {
    // The check failed. The previous readings stay on screen because they are the last real
    // observations Apollo has — but the failure is recorded on the snapshot so the Protection screen
    // says the check didn't run, rather than presenting an old reading as the current one.
    const current = protectionHealthSnapshot();
    const reason = err instanceof NativeCallFailed
      ? "ApolloSG asked this device for its protection state and the read failed."
      : err instanceof Error && err.message
        ? `ApolloSG couldn't complete the protection check (${err.message}).`
        : "ApolloSG couldn't complete the protection check and the reason could not be determined.";
    const failed: ProtectionHealthSnapshot = {
      ...current, checking: false, revision: current.revision + 1,
      lastCheckFailure: { at: new Date().toISOString(), trigger, reason },
    };
    publishProtectionHealth(failed);
    console.warn("[ProtectionHealth] check failed, keeping last observation:", err);
    return failed;
  }).finally(() => { inFlight = null; });
  return inFlight;
}

export async function requestSiteProtectionRecovery(): Promise<ActionAttempt> {
  if (promptInFlight) return promptInFlight;
  const request = (async (): Promise<ActionAttempt> => {
    const existing = await pendingAttempt();
    if (existing?.kind === "restore_site" && Date.parse(existing.expiresAt ?? "") > Date.now()) return existing;
    const startedAt = new Date().toISOString();
    const attempt: ActionAttempt = { id: Crypto.randomUUID(), kind: "restore_site", caseId: null, planId: null, descriptorId: "permission.vpn_config", startedAt, expiresAt: new Date(Date.now() + 2 * 60 * 1000).toISOString(), returnedAt: null, status: "requested" };
    await recordAttempt(attempt); await storage.setItem(DESIRED_KEY, "true");
    const result = await securityAdapter.requestProtectionPermission("vpn_config");
    if (result.status === "granted" || result.requestState === "already_granted") {
      // Permission exists — now actually (re)start the VPN service. Without this,
      // a previously-granted-but-stopped VPN stays stopped because the permission
      // check alone doesn't restart it.
      try { await securityAdapter.startProtection(); } catch (e) { console.warn("[ProtectionRecovery] startProtection failed after permission grant:", e); }
      await storage.setItem(DESIRED_KEY, "true"); await clearAttempt(); await runProtectionHealthCheck("protection_change"); return { ...attempt, status: "returned", returnedAt: new Date().toISOString() };
    }
    if (result.requestState === "launch_failed" || result.requestState === "unsupported" || !result.canAskAgain) { await clearAttempt(); await runProtectionHealthCheck("user_action"); return { ...attempt, status: "failed" }; }
    const opened: ActionAttempt = { ...attempt, status: "opened" }; await recordAttempt(opened); return opened;
  })().finally(() => { promptInFlight = null; });
  promptInFlight = request; return request;
}

export async function completeSiteProtectionAttempt(attempt: ActionAttempt): Promise<boolean> {
  if (attempt.kind !== "restore_site" || Date.parse(attempt.expiresAt ?? "") <= Date.now()) { await clearAttempt(); return false; }
  const next = await runProtectionHealthCheck("foreground"); return next.protection?.operational === true;
}