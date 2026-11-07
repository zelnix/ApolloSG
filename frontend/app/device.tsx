// Gate 7 — Check My Device. Shows only what this platform/build can truthfully see, plus what the user
// reports. Produces a device security status (Protected / Review / Action / Recovery) — never a "full scan".
import { Redirect, useRouter } from "expo-router";
import * as Crypto from "expo-crypto";
import ShieldCheck from "lucide-react-native/icons/shield-check";
import RefreshCw from "lucide-react-native/icons/refresh-cw";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppState, ActivityIndicator, Platform, Pressable, ScrollView, Switch, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { markCheckDone } from "@/src/store/checkCompletion";
import { CheckHistoryCard } from "@/src/components/CheckHistoryCard";
import { recordCheck } from "@/src/store/checkHistoryStore";
import { RecoveryFlow } from "@/src/components/RecoveryFlow";
import { Body, Button, Card, Pill, SectionTitle, toneColor } from "@/src/components/ui";
import { Sheet } from "@/src/components/Sheet";
import { assessDevice, deriveDeviceSecurityChanges, DEVICE_CHANGE_LABEL, DEVICE_STATUS, EMPTY_SIGNALS, SELF_REPORT, type DeviceFinding, type DevicePlatform, type DeviceSecurityChange, type DeviceSignals, type SelfReport } from "@/src/domain/deviceAnalysis";
import { groupByCategory, OUTCOME_LABEL, OUTCOME_TONE, overallState, runDeviceReview, type CheckResult, type ReviewPlatform } from "@/src/domain/deviceReview";
import { detectNativeProtection, summariseCallProtection, summariseMessageProtection } from "@/src/security/nativeProtectionEvidence";
import { deviceCheckEvent } from "@/src/domain/deviceCheckCase";
import { STATE_NAME, type PatrolEvent } from "@/src/domain/types";
import { AppDeviceSdk } from "@/src/security/appDeviceSdk";
import { NativeCallFailed } from "@/src/security/nativeDiagnostics";
import { securityAdapter } from "@/src/security/securityAdapter";
import { desktopHostKind } from "@/src/security/desktopHost";
import { openDesktopSettings } from "@/src/security/DesktopSecurityAdapter";
import { useApollo } from "@/src/store/ApolloContext";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { openDeviceSettings, type SettingsTarget } from "@/src/utils/deviceSettings";
import { CheckToolHeader } from "@/src/components/CheckToolHeader";
import { storage } from "@/src/utils/storage";

const TARGET: Record<string, SettingsTarget> = { D01: "apps", D01b: "apps", D02: "security", D03: "security", D04: "vpn", D05: "accessibility", D06: "apps", D07: "apps", D08: "unknown_sources", D09: "overlay", D10: "notification_access", D11: "developer" };
// Deep-link target for each review check so "Open Settings" lands the person on the right screen.
const REVIEW_TARGET: Record<string, SettingsTarget> = { lock: "security", os_updates: "security", developer_mode: "developer", apollo_protection: "vpn", antivirus: "security", unknown_sources: "unknown_sources", remote_access: "apps", accessibility: "accessibility", unexpected_app: "apps", sensitive_permissions: "apps", notification_access: "notification_access", sharing_services: "security", vpn: "vpn", firewall: "security", management_profile: "security", certificates: "security", encryption: "security", backup: "security" };
// Desktop (Tauri) OS Settings destinations accepted by open_settings_target. Specific review checks map to the
// exact firewall/updates pages; everything else maps its mobile SettingsTarget to the nearest desktop page.
const DESKTOP_TARGET_FOR_SETTINGS: Record<string, string> = { security: "security", developer: "privacy", vpn: "vpn", unknown_sources: "apps", apps: "apps", accessibility: "privacy", notification_access: "notifications" };
const desktopReviewTarget = (checkId: string): string => checkId === "firewall" ? "firewall" : checkId === "os_updates" ? "updates" : checkId === "antivirus" ? "security" : (DESKTOP_TARGET_FOR_SETTINGS[REVIEW_TARGET[checkId]] ?? "security");
const DEVICE_SNAPSHOT_KEY = "apollo.device.signals.v1";
const DEVICE_CHANGELOG_KEY = "apollo.device.changelog.v1";
const SEVERITY_RANK: Record<DeviceFinding["severity"], number> = { high: 2, review: 1, info: 0 };

/** Short "should be" recommendation for each check. Shown prominently so the user knows
 *  what the setting SHOULD look like before they open it. */
const RECOMMENDED: Record<string, string> = {
  lock: "Should be: Enabled with PIN, password or biometric",
  os_updates: "Should be: All updates installed",
  developer_mode: "Should be: Off",
  apollo_protection: "Should be: Running",
  antivirus: "Should be: Active and up to date",
  unknown_sources: "Should be: Off for all apps",
  remote_access: "Should be: No remote-access apps installed",
  accessibility: "Should be: Only genuine accessibility helpers",
  unexpected_app: "Should be: No unrecognised apps",
  sensitive_permissions: "Should be: Reviewed \u2014 revoke access apps don\u2019t need",
  notification_access: "Should be: Only apps you trust",
  sharing_services: "Should be: Off unless needed",
  vpn: "Should be: Only ApolloSG\u2019s VPN active",
  firewall: "Should be: On",
  management_profile: "Should be: None unless from your employer",
  certificates: "Should be: No user-installed certificates",
  encryption: "Should be: On",
  backup: "Should be: Enabled and recent",
};

/** Step-by-step fix guides for each check. Platform-specific where needed. */
const FIX_GUIDE: Record<string, { android: string[]; ios: string[]; fallback: string[] }> = {
  lock: {
    android: ["Open Settings \u2192 Security & privacy", "Tap \u2018Screen lock\u2019", "Choose PIN, Password or Pattern", "Set a strong code, then confirm it"],
    ios: ["Open Settings \u2192 Face ID & Passcode (or Touch ID & Passcode)", "Tap \u2018Turn Passcode On\u2019", "Choose a 6-digit PIN or tap \u2018Passcode Options\u2019 for more", "Enter and confirm your passcode"],
    fallback: ["Open your device\u2019s security settings", "Enable screen lock with a PIN, password or biometric"],
  },
  os_updates: {
    android: ["Open Settings \u2192 System \u2192 System update", "Tap \u2018Check for update\u2019", "If an update is available, tap \u2018Download and install\u2019", "Restart when prompted"],
    ios: ["Open Settings \u2192 General \u2192 Software Update", "If an update is available, tap \u2018Download and Install\u2019", "Enter your passcode if asked", "Wait for the update to complete"],
    fallback: ["Check for system updates in your device settings", "Install any available updates"],
  },
  developer_mode: {
    android: ["Open Settings \u2192 System \u2192 Developer options", "Toggle \u2018Developer options\u2019 to OFF at the top", "If you don\u2019t see Developer options, it\u2019s already off \u2014 that\u2019s correct"],
    ios: ["Open Settings \u2192 Privacy & Security", "If \u2018Developer Mode\u2019 appears, toggle it OFF", "If you don\u2019t see it, it\u2019s already off \u2014 that\u2019s correct"],
    fallback: ["Open your device settings and disable Developer Mode"],
  },
  unknown_sources: {
    android: ["Open Settings \u2192 Apps \u2192 Special app access", "Tap \u2018Install unknown apps\u2019", "Check EACH app in the list", "Set them all to \u2018Not allowed\u2019"],
    ios: ["iOS blocks unknown sources by default", "No action needed unless you\u2019ve jailbroken your device"],
    fallback: ["Disable installation from unknown sources in your security settings"],
  },
  accessibility: {
    android: ["Open Settings \u2192 Accessibility", "Scroll through \u2018Downloaded services\u2019", "Turn OFF any service you don\u2019t recognise", "Legitimate helpers: TalkBack, Switch Access, Voice Access"],
    ios: ["Open Settings \u2192 Accessibility", "Review each enabled feature", "Disable any you don\u2019t recognise or use"],
    fallback: ["Review accessibility services and disable any you don\u2019t recognise"],
  },
  sensitive_permissions: {
    android: ["Open Settings \u2192 Privacy \u2192 Permission manager", "Tap Camera, then review which apps have access", "Repeat for Microphone, Location and Contacts", "Revoke access from any app that doesn\u2019t need it"],
    ios: ["Open Settings \u2192 Privacy & Security", "Tap Camera, then review which apps have access", "Repeat for Microphone, Location and Contacts", "Toggle OFF any app that doesn\u2019t need it"],
    fallback: ["Review app permissions for camera, microphone and location", "Revoke access from apps that don\u2019t need it"],
  },
  notification_access: {
    android: ["Open Settings \u2192 Apps \u2192 Special app access", "Tap \u2018Notification access\u2019", "Turn OFF any app you don\u2019t trust", "Keep ApolloSG ON if you use text auto-scanning"],
    ios: ["Open Settings \u2192 Notifications", "Review each app\u2019s notification permission", "Disable notifications for apps you don\u2019t trust"],
    fallback: ["Review which apps have notification access and disable untrusted ones"],
  },
  remote_access: {
    android: ["Open Settings \u2192 Apps", "Search for: AnyDesk, TeamViewer, QuickSupport", "If found and you don\u2019t need it, tap \u2018Uninstall\u2019", "If you\u2019re unsure, tap \u2018Disable\u2019 instead"],
    ios: ["Open Settings \u2192 General \u2192 iPhone Storage", "Search for remote access apps (AnyDesk, TeamViewer)", "If found, tap the app \u2192 \u2018Delete App\u2019"],
    fallback: ["Check for and remove remote-access apps you didn\u2019t install"],
  },
  apollo_protection: {
    android: ["Return to ApolloSG\u2019s home screen", "Tap \u2018Start Protection\u2019 if shown", "Grant VPN permission when prompted"],
    ios: ["Return to ApolloSG\u2019s home screen", "Tap \u2018Start Protection\u2019 if shown", "Approve the VPN profile when prompted"],
    fallback: ["Open ApolloSG and start protection from the home screen"],
  },
  encryption: {
    android: ["Open Settings \u2192 Security \u2192 Encryption & credentials", "Check that \u2018Encrypt phone\u2019 shows \u2018Encrypted\u2019", "If not, tap it and follow the prompts (this may take a while)"],
    ios: ["If you have a passcode set, your device is already encrypted", "No further action needed"],
    fallback: ["Enable device encryption in your security settings"],
  },
  backup: {
    android: ["Open Settings \u2192 System \u2192 Backup", "Toggle \u2018Back up to Google Drive\u2019 ON", "Tap \u2018Back up now\u2019 to run an immediate backup"],
    ios: ["Open Settings \u2192 [Your Name] \u2192 iCloud \u2192 iCloud Backup", "Toggle \u2018iCloud Backup\u2019 ON", "Tap \u2018Back Up Now\u2019 to run an immediate backup"],
    fallback: ["Enable automatic backups in your device settings"],
  },
};

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  top: { paddingHorizontal: spacing.xl, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingBottom: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 22, color: c.onSurface },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: c.surfaceTertiary },
  subtitle: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurfaceSecondary, marginBottom: spacing.xs },
  content: { paddingHorizontal: spacing.xl, gap: spacing.lg },
  statusTitle: { fontFamily: fonts.displayBold, fontSize: 24, color: c.onSurface },
  why: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface },
  label: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.onSurface },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.md },
  step: { flexDirection: "row", gap: spacing.sm },
  num: { fontFamily: fonts.displayBold, fontSize: 15, color: c.brandPrimary, width: 20 },
  mono: { fontFamily: fonts.text, fontSize: 12, color: c.onSurfaceSecondary },
  catLabel: { fontFamily: fonts.textSemibold, fontSize: 13, letterSpacing: 0.3, color: c.muted, textTransform: "uppercase" },
  rec: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.brandPrimary, marginTop: spacing.xs },
  settingsLink: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.sm, paddingHorizontal: spacing.sm, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, marginTop: spacing.xs },
  settingsLabel: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.brandPrimary },
  settingsPath: { fontFamily: fonts.text, fontSize: 12, color: c.onSurfaceSecondary, flex: 1 },
  progressTrack: { height: 6, backgroundColor: c.borderStrong, borderRadius: 3, marginTop: spacing.xs, overflow: "hidden" as const },
  progressFill: { height: 6, borderRadius: 3 },
  fixStep: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface, marginBottom: spacing.xs },
}));

export default function CheckDevice() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { ready, setupDone, upsertEvent, deviceId, adapterLabel, showToast, protection, permissions, verifyNow } = useApollo();
  const platform: DevicePlatform = Platform.OS === "ios" ? "ios" : Platform.OS === "android" ? "android" : "web";
  // On a desktop (Tauri) host Platform.OS is "web", but the host can observe Windows/macOS settings — review as that OS.
  const hostKind = desktopHostKind();
  const [signals, setSignals] = useState<DeviceSignals>(EMPTY_SIGNALS(hostKind ?? platform));
  const [self, setSelf] = useState<SelfReport>({});
  const [event, setEvent] = useState<PatrolEvent | null>(null);
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(true);
  const [changes, setChanges] = useState<DeviceSecurityChange[]>([]);
  const [changeLog, setChangeLog] = useState<DeviceSecurityChange[]>([]);
  const [logReviewOnly, setLogReviewOnly] = useState(false);
  const [settingsGuidance, setSettingsGuidance] = useState<string | null>(null);
  const [checkSequence, setCheckSequence] = useState(0);
  // ── Recheck investigation state ──
  type RecheckPhase = "idle" | "investigating" | "briefing";
  const [recheckPhase, setRecheckPhase] = useState<RecheckPhase>("idle");
  const [briefing, setBriefing] = useState<{ headline: string; findings: string[]; action: string | null; overall: string } | null>(null);
  // Which user-initiated check produced the briefing on screen. Background refreshes never change it,
  // so a refresh while the briefing is open can never file a second patrol entry.
  const [briefingRun, setBriefingRun] = useState<number | null>(null);
  const notifyRun = useRef(0);

  const refreshDevice = useCallback(async (notify = false) => {
    setChecking(true);
    if (notify) { notifyRun.current += 1; setRecheckPhase("investigating"); }
    try {
      const collectSignals = hostKind && securityAdapter.getDeviceSecuritySignals ? securityAdapter.getDeviceSecuritySignals() : AppDeviceSdk.getDeviceSecuritySignals(platform);
      const [nextSignals, recent, previousRaw] = await Promise.all([collectSignals, AppDeviceSdk.getRecentAppSecurityEvents(), storage.getItem<string | null>(DEVICE_SNAPSHOT_KEY, null), verifyNow()]);
      // Augment signals with native OS/OEM protection detection (detection only, no classifications).
      try {
        const nativeCaps = await detectNativeProtection();
        const callSummary = summariseCallProtection(nativeCaps);
        const msgSummary = summariseMessageProtection(nativeCaps);
        nextSignals.nativeCallProtection = { active: callSummary.hasNativeProtection, activeProviders: callSummary.activeProviders, detail: callSummary.detail };
        nextSignals.nativeMessageProtection = { active: msgSummary.hasNativeProtection, activeProviders: msgSummary.activeProviders, detail: msgSummary.detail };
      } catch { /* Detection failure is not a check failure. */ }
      const previous = previousRaw ? JSON.parse(previousRaw) as DeviceSignals : null;
      const observedChanges = deriveDeviceSecurityChanges(previous, nextSignals, new Date().toISOString(), protection?.running === true);
      setSignals(nextSignals);
      setChanges([...recent, ...observedChanges].filter((item, index, all) => all.findIndex((candidate) => candidate.eventType === item.eventType && candidate.appName === item.appName) === index));
      await storage.setItem(DEVICE_SNAPSHOT_KEY, JSON.stringify(nextSignals));
      // Dated log of security/privacy/protection setting changes. Apollo-caused changes keep their
      // "apollo" attribution; everything else is "user_or_unknown". Newest first, capped at 50.
      if (observedChanges.length) {
        const priorRaw = await storage.getItem<string | null>(DEVICE_CHANGELOG_KEY, null);
        const prior = priorRaw ? JSON.parse(priorRaw) as DeviceSecurityChange[] : [];
        const merged = [...observedChanges, ...prior].slice(0, 50);
        await storage.setItem(DEVICE_CHANGELOG_KEY, JSON.stringify(merged));
        setChangeLog(merged);
      }
      void markCheckDone("device");
    } catch (error) {
      // A failed read is reported as a failed read. Apollo does not grade the device from signals it
      // never managed to collect, and it names what went wrong.
      const detail = error instanceof NativeCallFailed
        ? "ApolloSG asked this device for its security signals and the read failed, so this check did not run."
        : error instanceof Error && error.message
          ? `ApolloSG couldn't complete the device check (${error.message}).`
          : "ApolloSG couldn't complete the device check and the reason could not be determined.";
      if (notify) {
        setBriefing({ headline: "Device check didn't run", findings: [detail, "Nothing here says the device is clear — the check was not completed."], action: null, overall: "error" });
        setBriefingRun(notifyRun.current);
        setRecheckPhase("briefing");
      } else {
        showToast(detail, "growling");
      }
    } finally { setChecking(false); setCheckSequence((value) => value + 1); }
  }, [platform, hostKind, showToast, verifyNow, protection?.running, storage]);
  useEffect(() => { void refreshDevice(false); }, [refreshDevice]);
  useEffect(() => { void storage.getItem<string | null>(DEVICE_CHANGELOG_KEY, null).then((raw) => { if (raw) setChangeLog(JSON.parse(raw) as DeviceSecurityChange[]); }); }, [storage]);
  const context = useMemo(() => ({
    protection: protection ? { requested: protection.requested, operational: protection.operational, degradedReason: protection.degradedReason,
      permissionIssues: permissions.filter((permission) => permission.status === "denied" || permission.status === "blocked").map((permission) => permission.title), checkedAt: protection.checkedAt } : null,
    recentChanges: changes,
  }), [changes, permissions, protection]);
  const result = useMemo(() => assessDevice(signals, self, context), [signals, self, context]);
  const meta = DEVICE_STATUS[result.status];
  // Cross-platform Security & Privacy Review — every applicable setting gets an explicit outcome.
  const reviewPlatform: ReviewPlatform | null = hostKind ?? (platform === "web" ? null : platform);
  const review = useMemo(() => reviewPlatform ? runDeviceReview({ platform: reviewPlatform, signals, self, protection: context.protection }) : null, [reviewPlatform, signals, self, context.protection]);
  const reviewGroups = useMemo(() => review ? groupByCategory(review) : [], [review]);

  // ── Build Higgins' investigation briefing after a user-initiated recheck ──
  useEffect(() => {
    if (recheckPhase !== "investigating" || checking) return;
    // Check just completed — build the briefing from the review results.
    const findings: string[] = [];
    let actionItem: string | null = null;
    let overallLabel = "clear";

    if (review) {
      const actionResults = review.results.filter((r) => r.outcome === "action");
      const reviewResults = review.results.filter((r) => r.outcome === "review");
      const checkedResults = review.results.filter((r) => r.outcome === "checked");
      const manualResults = review.results.filter((r) => r.outcome === "manual" || r.outcome === "unavailable");

      if (checkedResults.length > 0) {
        findings.push(`${checkedResults.length} ${checkedResults.length === 1 ? "setting is" : "settings are"} correctly configured.`);
      }
      if (actionResults.length > 0) {
        overallLabel = "action";
        for (const r of actionResults) findings.push(`${r.title} needs attention — ${r.risk || "action required"}.`);
        actionItem = actionResults[0].settings ?? actionResults[0].risk ?? `${actionResults[0].title} needs to be fixed.`;
      }
      if (reviewResults.length > 0) {
        if (overallLabel === "clear") overallLabel = "review";
        for (const r of reviewResults) findings.push(`${r.title} could be improved — ${r.risk || "worth reviewing"}.`);
        if (!actionItem) actionItem = reviewResults[0].settings ?? reviewResults[0].risk ?? `Review ${reviewResults[0].title}.`;
      }
      if (manualResults.length > 0) {
        findings.push(`${manualResults.length} ${manualResults.length === 1 ? "setting" : "settings"} could not be determined — Higgins can help you check ${manualResults.length === 1 ? "it" : "them"} manually.`);
      }
    } else {
      // No review available (web or unsupported platform).
      const actionFindings = result.findings.filter((f) => f.severity === "high");
      const reviewFindings = result.findings.filter((f) => f.severity === "review");
      if (actionFindings.length > 0) {
        overallLabel = "action";
        for (const f of actionFindings) findings.push(`${f.title}: ${f.plain}`);
        actionItem = actionFindings[0].action;
      }
      if (reviewFindings.length > 0) {
        if (overallLabel === "clear") overallLabel = "review";
        for (const f of reviewFindings) findings.push(`${f.title}: ${f.plain}`);
        if (!actionItem) actionItem = reviewFindings[0].action;
      }
      if (!findings.length) findings.push("No concerns were identified within what this platform allows Apollo to check.");
    }

    const headline = overallLabel === "clear"
      ? "Your device looks good"
      : overallLabel === "action"
        ? `${review ? review.results.filter((r) => r.outcome === "action").length : result.findings.filter((f) => f.severity === "high").length} ${overallLabel === "action" ? "item" : "items"} need${overallLabel === "action" ? "s" : ""} your attention`
        : "A few settings are worth reviewing";

    setBriefing({ headline, findings, action: actionItem, overall: overallLabel });
    setBriefingRun(notifyRun.current);
    setRecheckPhase("briefing");
  }, [recheckPhase, checking, review, result]);

  // ── A completed device check is a case ──
  // Every USER-INITIATED check files its own patrol entry, so the full trail is in patrol history.
  // All checks of this device share one case key, so Threats shows ONE device-check case with the
  // latest result instead of a new case per check. Background refreshes (simply opening this screen)
  // are not checks the person asked for and are never recorded.
  const [historyKey, setHistoryKey] = useState(0);
  const recordedRun = useRef<number | null>(null);
  useEffect(() => {
    if (recheckPhase !== "briefing" || !briefing || checking || briefingRun === null) return;
    if (recordedRun.current === briefingRun) return;
    recordedRun.current = briefingRun;
    const checkedAt = new Date().toISOString();
    const event = deviceCheckEvent({
      eventId: Crypto.randomUUID(), deviceId, briefing, adapterLabel, checkedAt,
      platformLabel: hostKind ? `${hostKind} desktop` : platform === "web" ? "this browser" : platform,
    });
    void upsertEvent(event, {
      kind: "device",
      fields: [
        { label: "Checked", value: new Date(checkedAt).toLocaleString() },
        { label: "Device", value: hostKind ?? platform },
        { label: "Result", value: briefing.headline },
      ],
      text: briefing.findings.join("\n"),
      data: review ? { overall: review.overall, results: review.results } : { state: result.state, findings: result.findings },
    }).catch(() => undefined);
    // Check history records the SAME user-initiated checks as Patrol — never a background refresh,
    // so "Checked today" on the Device screen can only mean a check the person actually ran.
    void recordCheck("device", { at: checkedAt, state: review ? overallState(review.overall) : result.state, summary: briefing.headline });
    setHistoryKey((k) => k + 1);
  }, [recheckPhase, briefing, briefingRun, checking, deviceId, adapterLabel, hostKind, platform, review, result, upsertEvent]);

  const openCheck = (r: CheckResult) => {
    if (!r.settings) return;
    if (hostKind) void openDesktopSettings(desktopReviewTarget(r.id)).catch(() => setSettingsGuidance(`${r.title}: ${r.settings}`));
    else if (platform === "web") setSettingsGuidance(`${r.title}: ${r.settings}`);
    else void openDeviceSettings(REVIEW_TARGET[r.id] ?? "security", r.settings, (m) => showToast(m, "neutral"));
  };
  const anySelf = Object.values(self).some(Boolean);

  // ── Guided "Fix it" flow ──
  const [fixingCheck, setFixingCheck] = useState<CheckResult | null>(null);
  const pendingVerifyRef = useRef<string | null>(null);
  const [fixProgress, setFixProgress] = useState<Record<string, "pending" | "verified" | "still_wrong">>({});

  // When user returns from Settings, automatically re-check and verify
  useEffect(() => {
    const sub = AppState.addEventListener("change", (nextState) => {
      if (nextState === "active" && pendingVerifyRef.current) {
        void refreshDevice(false);
      }
    });
    return () => sub.remove();
  }, [refreshDevice]);

  // After a re-check completes, verify whether the pending fix worked
  useEffect(() => {
    const id = pendingVerifyRef.current;
    if (!id || !review) return;
    const updated = review.results.find((r) => r.id === id);
    if (!updated) return;
    pendingVerifyRef.current = null;
    if (updated.outcome === "checked") {
      setFixProgress((prev) => ({ ...prev, [id]: "verified" }));
      showToast(`\u2705 ${updated.title} is now correct!`, "resting");
    } else {
      setFixProgress((prev) => ({ ...prev, [id]: "still_wrong" }));
      showToast(`${updated.title} still needs attention \u2014 try the steps again or ask Higgins.`, "growling");
    }
  }, [checkSequence, review, showToast]);

  const startFix = (r: CheckResult) => { setFixingCheck(r); };
  const confirmAndOpenSettings = () => {
    if (!fixingCheck) return;
    pendingVerifyRef.current = fixingCheck.id;
    setFixProgress((prev) => ({ ...prev, [fixingCheck.id]: "pending" }));
    openCheck(fixingCheck);
    setFixingCheck(null);
  };

  // Progress counter
  const totalActionable = review?.results.filter((r) => r.outcome === "action" || r.outcome === "review").length ?? 0;
  const fixedCount = Object.values(fixProgress).filter((v) => v === "verified").length;

  const save = async () => {
    setSaving(true);
    try {
      const ev = await upsertEvent({ event_id: Math.random().toString(36).slice(2) + Date.now().toString(36), origin: "user", device_id: deviceId ?? "local", category: "device", state: result.state, status: "active", headline: `Device: ${meta.title}`, what_happened: result.summary, why: result.findings.map((f) => `${f.title}: ${f.plain}`), what_to_do: result.recoverySteps[0] ?? result.findings[0]?.action ?? "Review the items ApolloSG listed.", indicator_host: null, indicator_digest: null, verified_block: false, adapter_label: adapterLabel, occurred_at: new Date().toISOString(), resolved_at: null, trust_allowed: false, claimed_brand: null, scenario: result.findings[0]?.id ?? "D00" }, { kind: "device", data: { platform, signals, selfReport: self } });
      setEvent(ev);
      showToast("Saved to Patrol. ApolloSG will stay with you.", "neutral");
    } finally { setSaving(false); }
  };
  const open = (f: DeviceFinding) => {
    const dynamic: SettingsTarget | null = f.id.includes("vpn_change") ? "vpn" : f.id.includes("profile_change") ? "security" : f.id.includes("service_enabled") ? "accessibility" : null;
    if (platform === "web") setSettingsGuidance(`${f.title}: ${f.settings}`);
    else void openDeviceSettings(dynamic ?? TARGET[f.id] ?? (f.id === "D12" || f.id === "D13" ? "vpn" : "apps"), f.settings, (m) => showToast(m, "neutral"));
  };
  const openChange = (change: DeviceSecurityChange) => {
    const target: SettingsTarget = change.eventType === "vpn_change" ? "vpn" : change.eventType === "profile_change" ? "security" : change.eventType === "service_enabled" ? "accessibility" : "apps";
    const label = DEVICE_CHANGE_LABEL[change.eventType];
    if (platform === "web") setSettingsGuidance(`${label}: open the matching settings screen to confirm this change.`);
    else void openDeviceSettings(target, label, (m) => showToast(m, "neutral"));
  };
  const firstAction = [...result.findings].sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity])[0] ?? null;

  if (ready && !setupDone) return <Redirect href="/" />;

  return (
    <View style={s.root}>
      <View style={[s.top, { paddingTop: insets.top + spacing.md }]}>
        <CheckToolHeader
          title="Check my device"
          info={{ title: "About device monitoring", body: ["Apollo checks your device's security settings — screen lock, biometrics, OS updates, developer options, unknown sources and more.", "These checks run locally on your device. Apollo reports what it can observe and explains what each setting means for your safety."] }}
          testID="device"
        />
      </View>
      <ScrollView contentContainerStyle={[s.content, { paddingBottom: insets.bottom + spacing.xl }]} testID="device-scroll">
        <Text style={s.subtitle}>Checks your device security settings, app permissions and Apollo protection health.</Text>

        {/* ── Recheck: Investigation in progress ── */}
        {recheckPhase === "investigating" ? (
          <Card testID="device-investigating" style={{ gap: spacing.md, borderColor: colors.brandPrimary }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
              <ActivityIndicator size="small" color={colors.brandPrimary} />
              <Text style={[s.statusTitle, { flex: 1 }]}>Checking device</Text>
            </View>
            <Body>Apollo is reviewing your device settings, permissions and protection health. If anything needs investigating, TC Hawkeye checks it first and Magnum DI looks deeper only if needed. This takes a moment.</Body>
          </Card>
        ) : null}

        {/* ── Recheck: Higgins' investigation briefing ── */}
        {recheckPhase === "briefing" && briefing ? (
          <Card testID="device-briefing" style={{ gap: spacing.sm, borderColor: briefing.overall === "clear" ? colors.resting : briefing.overall === "action" ? colors.growling : colors.warning }}>
            <SectionTitle>Higgins</SectionTitle>
            <Text style={s.statusTitle} testID="device-briefing-headline">{briefing.headline}</Text>
            {briefing.findings.map((f, i) => (
              <View key={i} style={{ flexDirection: "row", gap: spacing.xs, alignItems: "flex-start" }}>
                <Text style={[s.why, { lineHeight: 22 }]}>{"\u2022"}</Text>
                <Text style={[s.why, { flex: 1, lineHeight: 22 }]}>{f}</Text>
              </View>
            ))}
            {briefing.action ? (
              <Body testID="device-briefing-action">{briefing.overall === "action" ? `I'd start with this: ${briefing.action}` : `Worth reviewing: ${briefing.action}`}</Body>
            ) : (
              <Body testID="device-briefing-action">No action needed right now. Apollo will keep watching.</Body>
            )}
            <Button testID="device-briefing-view-full" variant="ghost" label="View full device review" onPress={() => { setRecheckPhase("idle"); }} />
          </Card>
        ) : null}

        <Card testID="device-status" style={{ borderColor: toneColor(colors, review ? overallState(review.overall) : result.state), gap: spacing.sm }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}><ShieldCheck size={22} color={toneColor(colors, review ? overallState(review.overall) : result.state)} /><Pill tone={review ? overallState(review.overall) : result.state} label={review ? review.overallLabel : STATE_NAME[result.state]} testID="device-state" /></View>
          <Text style={s.statusTitle} testID="device-status-title">{review ? review.overallLabel : meta.title}</Text>
          <Text style={s.why} testID="device-summary">{review ? review.summary : result.summary}</Text>
          {review ? <Body testID="device-coverage">{review.coverage.automated} of {review.coverage.total} settings checked automatically here; Higgins can help with the rest below.</Body> : <Body>{result.findings.length ? "Tap each item in the review below to see exactly what to do." : meta.meaning}</Body>}
        </Card>
        {settingsGuidance ? <Card testID="device-settings-guidance" style={{ gap: spacing.sm }}><SectionTitle>Settings steps</SectionTitle><Body>{settingsGuidance}</Body><Button testID="device-settings-guidance-close" variant="ghost" label="Hide instructions" onPress={() => setSettingsGuidance(null)} /></Card> : null}
        {changeLog.length ? (
          <Card testID="device-change-log" style={{ gap: spacing.sm }}>
            <SectionTitle>Recent security setting changes</SectionTitle>
            <Body>Changes Apollo has observed to security, privacy or protection settings. Changes ApolloSG made for its own protection are tagged “ApolloSG”. Tap any entry to open the matching settings screen.</Body>
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              <Button testID="device-log-filter-all" variant={logReviewOnly ? "ghost" : "secondary"} label="All" onPress={() => setLogReviewOnly(false)} />
              <Button testID="device-log-filter-review" variant={logReviewOnly ? "secondary" : "ghost"} label="Review only" onPress={() => setLogReviewOnly(true)} />
            </View>
            {(() => { const shown = (logReviewOnly ? changeLog.filter((c) => c.attributedTo !== "apollo") : changeLog).slice(0, 8); return shown.length ? shown.map((change, i) => (
              <Pressable key={`${change.eventType}-${change.occurredAt}-${i}`} testID={`device-change-${i}`} accessibilityRole="button" accessibilityHint="Opens the matching settings screen to confirm this change" onPress={() => openChange(change)} style={({ pressed }) => [{ flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.xs, opacity: pressed ? 0.7 : 1 }]}>
                <View style={{ flex: 1 }}>
                  <Text style={[s.why, { fontFamily: fonts.textSemibold }]}>{DEVICE_CHANGE_LABEL[change.eventType]}{change.appName ? `: ${change.appName}` : ""}</Text>
                  <Text style={s.mono}>{new Date(change.occurredAt).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</Text>
                </View>
                <Pill tone={change.attributedTo === "apollo" ? "resting" : "growling"} label={change.attributedTo === "apollo" ? "ApolloSG" : "Review"} testID={`device-change-${i}-tag`} />
              </Pressable>
            )) : <Body testID="device-log-empty">No changes need review.</Body>; })()}
          </Card>
        ) : null}

        <Card testID="device-protection-health" style={{ gap: spacing.sm, borderColor: result.protectionHealth.status === "active" ? colors.resting : result.protectionHealth.status === "unavailable" ? colors.border : colors.growling }}>
          <View style={s.row}><SectionTitle>Apollo protection health</SectionTitle><Pill testID="device-protection-health-status" tone={result.protectionHealth.status === "active" ? "resting" : result.protectionHealth.status === "unavailable" ? "unknown" : "growling"} label={result.protectionHealth.status === "active" ? "Active" : result.protectionHealth.status === "off" ? "Off" : result.protectionHealth.status === "needs_attention" ? "Needs attention" : "Unavailable"} /></View>
          <Text style={s.label} testID="device-protection-health-title">{result.protectionHealth.title}</Text>
          <Body testID="device-protection-health-detail">{result.protectionHealth.detail}</Body>
        </Card>

        {result.recoverySteps.length ? (
          <Card style={{ gap: spacing.sm, borderColor: colors.barking }} testID="device-recovery">
            <SectionTitle>Stay with me — do these in order</SectionTitle>
            {result.recoverySteps.map((st, i) => <View key={i} style={s.step}><Text style={s.num}>{i + 1}</Text><Text style={[s.why, { flex: 1 }]} testID={`device-recovery-step-${i}`}>{st}</Text></View>)}
            <Body>ApolloSG can&apos;t tell whether anything was taken — only that the access was risky. Don&apos;t assume the worst, but do the steps.</Body>
          </Card>
        ) : null}

        {reviewGroups.length ? (
          <View style={{ gap: spacing.md }} testID="device-review">
            <SectionTitle>Security & privacy review</SectionTitle>
            {totalActionable > 0 ? (
              <Card style={{ gap: spacing.sm, borderColor: fixedCount >= totalActionable ? colors.resting : colors.growling }} testID="device-fix-progress">
                <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                  <View style={{ flex: 1 }}>
                    <Text style={s.label}>{fixedCount >= totalActionable ? "All items fixed!" : `${fixedCount} of ${totalActionable} fixed`}</Text>
                    <View style={s.progressTrack}><View style={[s.progressFill, { width: `${totalActionable > 0 ? Math.round((fixedCount / totalActionable) * 100) : 0}%` as any, backgroundColor: fixedCount >= totalActionable ? colors.resting : colors.growling }]} /></View>
                  </View>
                  <Pill tone={fixedCount >= totalActionable ? "resting" : "growling"} label={fixedCount >= totalActionable ? "\u2705 Done" : `${totalActionable - fixedCount} left`} />
                </View>
              </Card>
            ) : null}
            {reviewGroups.map((group) => (
              <View key={group.category} style={{ gap: spacing.sm }} testID={`device-review-cat-${group.category}`}>
                <Text style={s.catLabel}>{group.label}</Text>
                {group.results.map((r) => {
                  const tone = OUTCOME_TONE[r.outcome];
                  const rec = RECOMMENDED[r.id];
                  const progress = fixProgress[r.id];
                  const needsFix = r.outcome === "action" || r.outcome === "review" || r.outcome === "manual";
                  const guide = FIX_GUIDE[r.id];
                  return (
                    <Card key={r.id} style={{ gap: spacing.xs, borderColor: progress === "verified" ? colors.resting : toneColor(colors, tone) }} testID={`device-check-${r.id}`}>
                      <View style={s.row}>
                        <Text style={[s.label, { flex: 1 }]}>{r.title}</Text>
                        {progress === "verified" ? <Pill tone="resting" label={"\u2705 Fixed"} testID={`device-check-${r.id}-fixed`} /> : progress === "still_wrong" ? <Pill tone="barking" label={"\u274c Still wrong"} testID={`device-check-${r.id}-still`} /> : <Pill tone={tone} label={OUTCOME_LABEL[r.outcome]} testID={`device-check-${r.id}-outcome`} />}
                      </View>
                      {rec ? <Text style={s.rec} testID={`device-check-${r.id}-rec`}>{rec}</Text> : null}
                      {r.risk ? <Text style={s.why}>{r.risk}</Text> : null}
                      {r.remediation && r.outcome !== "checked" ? <Text style={s.why}>{r.remediation}</Text> : null}
                      <Text style={s.mono}>{r.evidence}{r.verifiedBy === "user_confirmed" ? " \u00b7 You confirmed this." : r.verifiedBy === "observation" ? " \u00b7 Verified by Apollo." : ""}</Text>
                      {needsFix && guide ? (
                        <Button testID={`device-check-${r.id}-fix`} variant={r.outcome === "action" ? "danger" : "secondary"} label={progress === "still_wrong" ? "Try again" : "Fix it"} onPress={() => startFix(r)} />
                      ) : r.settings ? (
                        <Pressable testID={`device-check-${r.id}-open`} accessibilityRole="button" onPress={() => openCheck(r)} style={({ pressed }) => [s.settingsLink, { opacity: pressed ? 0.7 : 1 }]}>
                          <Text style={s.settingsLabel}>{platform === "web" && !hostKind ? "Show Settings steps" : "Open Settings"}</Text>
                          <Text style={s.settingsPath}>{r.settings}</Text>
                        </Pressable>
                      ) : null}
                    </Card>
                  );
                })}
              </View>
            ))}
          </View>
        ) : null}

        <Card testID="device-higgins" style={{ gap: spacing.sm, borderColor: colors.navyBorder }}>
          <SectionTitle>Higgins</SectionTitle>
          <Body testID="device-higgins-explanation">{firstAction ? `${firstAction.title} is the first item to review. ${firstAction.action}` : "Apollo did not identify a meaningful concern within the signals this platform exposes. The visibility limits below still apply."}</Body>
          {firstAction ? <Button testID="device-higgins-open-settings" label={platform === "web" ? "Show relevant Settings steps" : "Open relevant Settings"} onPress={() => open(firstAction)} /> : null}
          <Button testID="device-higgins-recheck" variant="secondary" icon={<RefreshCw size={17} color={colors.brand} />} label={recheckPhase === "investigating" ? "Checking device\u2026" : "Recheck device"} onPress={() => void refreshDevice(true)} disabled={recheckPhase === "investigating"} />
          <Button testID="device-ask-higgins" variant="ghost" label="Ask Higgins about my device" onPress={() => router.push({ pathname: "/(tabs)/ask", params: { prompt: review ? `My device security review says: ${review.summary} What should I do first?` : `My device assessment says: ${result.summary} How do I keep my phone secure?` } })} />
          <Body testID="device-higgins-tampering-rule">Apollo reports suspected tampering only when a specific high-confidence configuration or permission change was observed. A stopped service or missing permission alone is a protection gap, not proof of tampering.</Body>
        </Card>

        <Card style={{ gap: spacing.sm }} testID="device-self-report">
          <SectionTitle>Tell Higgins what you&apos;ve noticed</SectionTitle>
          <Body>{platform === "ios" ? "You and Higgins review iPhone profiles and app access together, alongside Apollo's automatic checks." : signals.thirdPartyAccessibilityServices === null ? "Tell Higgins what you've noticed and he'll check it with you, alongside Apollo's automatic checks." : "Higgins keeps your report distinct from the results Apollo observed automatically."}</Body>
          {SELF_REPORT.filter((o) => !(platform === "ios" && o.id === "unknownSourcesOn")).map((o) => (
            <View key={o.id} style={s.row}><Text style={[s.why, { flex: 1 }]}>{o.label}</Text><Switch testID={`device-self-${o.id}`} value={!!self[o.id]} onValueChange={(v) => setSelf((c) => ({ ...c, [o.id]: v }))} trackColor={{ true: o.id === "managementExpected" ? colors.resting : colors.growling, false: colors.borderStrong }} thumbColor={colors.onSurface} /></View>
          ))}
          <Body testID="device-self-report-applied">{anySelf ? "What you've told Higgins is already included in the review above." : "Switch anything on and it goes straight into the review above — there is nothing else to submit."}</Body>
        </Card>

        <Card style={{ gap: spacing.xs }} testID="device-cannot-see">
          <SectionTitle>Where Higgins can help</SectionTitle>
          {result.cannotSee.length ? result.cannotSee.map((c, i) => <Body key={i} testID={`device-cannot-${i}`}>• {c}</Body>) : <Body>Everything above was read straight from your device.</Body>}
          <Body>For anything your device keeps private from apps, Higgins walks you through it so nothing is left unchecked.</Body>
        </Card>

        <Card style={{ gap: spacing.sm }} testID="device-actions">
          {result.status !== "protected" && !event ? <Button testID="device-save" label={saving ? "Saving\u2026" : "Save to Patrol & stay with me"} onPress={() => void save()} disabled={saving} /> : null}
          {event ? <RecoveryFlow event={event} kinds={["remote", "banking_during_access", "accessibility", "profile", "password", "code"]} testID="device-recovery-flow" /> : null}
          <Button testID="device-check-app" variant="secondary" label="Check a specific app" onPress={() => router.push("/app-check")} />
        </Card>
        <CheckHistoryCard gate="device" refreshKey={historyKey} testID="device-history" />
      </ScrollView>

      {/* ── Guided Fix Sheet ── */}
      <Sheet visible={!!fixingCheck} onClose={() => setFixingCheck(null)} title={`Fix: ${fixingCheck?.title ?? ""}`} testID="device-fix-sheet">
        {fixingCheck ? (
          <>
            {RECOMMENDED[fixingCheck.id] ? <Text style={s.rec}>{RECOMMENDED[fixingCheck.id]}</Text> : null}
            <SectionTitle>Steps</SectionTitle>
            {(FIX_GUIDE[fixingCheck.id]?.[platform === "android" ? "android" : platform === "ios" ? "ios" : "fallback"] ?? FIX_GUIDE[fixingCheck.id]?.fallback ?? []).map((step, i) => (
              <Text key={i} style={s.fixStep}>{i + 1}. {step}</Text>
            ))}
            <Body>When you return, ApolloSG will re-check this setting automatically.</Body>
            <Button testID="device-fix-open-settings" variant="primary" label="Open Settings now" onPress={confirmAndOpenSettings} />
            <Button testID="device-fix-cancel" variant="ghost" label="Cancel" onPress={() => setFixingCheck(null)} />
          </>
        ) : null}
      </Sheet>
    </View>
  );
}
