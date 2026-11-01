// Gate 7 — Check This App. Works from what the user tells Apollo (name, source, purpose, permissions,
// what was happening around the install) plus any Security-SDK findings. Never pretends to read other apps.
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import * as Crypto from "expo-crypto";
import X from "lucide-react-native/icons/x";
import Smartphone from "lucide-react-native/icons/smartphone";
import React, { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, AppState, Platform, Pressable, ScrollView, Switch, Text, TextInput, View } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { markCheckDone } from "@/src/store/checkCompletion";
import { apiPost } from "@/src/api/client";
import { CheckResultScreen } from "@/src/components/CheckResultScreen";
import { InvestigationCheckScreen } from "@/src/components/InvestigationCheckScreen";
import { CheckHistoryCard } from "@/src/components/CheckHistoryCard";
import { recordCheck } from "@/src/store/checkHistoryStore";
import { RecoveryFlow } from "@/src/components/RecoveryFlow";
import type { InvestigationResult } from "@/src/domain/investigation";
import { Sheet } from "@/src/components/Sheet";
import { Body, Button, Card, SectionTitle } from "@/src/components/ui";
import { analyseApp, APP_PERMISSIONS, APP_PURPOSES, APP_SOURCES, PERMISSION_INFO, type AppAnalysis, type AppNetwork, type AppPermission, type AppPurpose, type AppSource } from "@/src/domain/appAnalysis";
import { buildPermissionFindings, confirmedResolved, type PermissionFinding } from "@/src/domain/appPermissionFindings";
import { buildAppCheckResult } from "@/src/domain/appCheckResultAdapter";
import { buildAppProfile } from "@/src/domain/triage/appEvidence";
import type { EvidenceProfile } from "@/src/domain/triage/evidenceProfile";
import { contextFromEvent, gateForCategory } from "@/src/domain/higginsHandoff";
import { saveAppReport } from "@/src/store/appReportStore";
import { SCENT_WINDOW_MS } from "@/src/domain/threatScent";
import { STATE_NAME, type PatrolEvent } from "@/src/domain/types";
import { AppDeviceSdk, sdkPermissionsToApp, type InstalledAppRef } from "@/src/security/appDeviceSdk";
import { NativeCallFailed } from "@/src/security/nativeDiagnostics";
import { SourceHero } from "@/src/components/SourceHero";
import { SourcePickerSheet } from "@/src/components/SourcePickerSheet";
import { findSampleApp } from "@/src/sampleChecks";
import { simulation } from "@/src/simulation";
import { useApollo } from "@/src/store/ApolloContext";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { openDeviceSettings, permissionSettings } from "@/src/utils/deviceSettings";
import { goBackOrHome } from "@/src/utils/navigation";
import { InfoButton } from "@/src/components/InfoButton";
import { CheckToolHeader } from "@/src/components/CheckToolHeader";

type Reputation = { remote_access_tool: string | null; known_security_vendor: string | null; impersonates_brand: string | null; official_store: boolean; note: string };
type Remote = { reputation: Reputation; hosts: { host: string; verdict: "clean" | "malicious" | "unknown" }[]; explanation: { summary: string; why: string[]; recommendation: string } | null; assessment: InvestigationResult | null };
const LINKED_CATEGORIES = new Set(["call", "message", "link", "website", "known_threat"]);

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  top: { paddingHorizontal: spacing.xl, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingBottom: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 22, color: c.onSurface },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: c.surfaceTertiary },
  subtitle: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurfaceSecondary, marginBottom: spacing.xs },
  content: { paddingHorizontal: spacing.xl, gap: spacing.lg },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: { paddingVertical: spacing.sm, paddingHorizontal: spacing.md, borderRadius: radius.pill, borderWidth: 1, borderColor: c.border, minHeight: 40, justifyContent: "center" },
  chipOn: { borderColor: c.brandPrimary, backgroundColor: c.restingTint },
  chipWarn: { borderColor: c.growling, backgroundColor: c.growlingTint },
  chipText: { fontFamily: fonts.textMedium, fontSize: 14, color: c.onSurface },
  input: { minHeight: 48, backgroundColor: c.surfaceTertiary, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.lg, fontFamily: fonts.text, fontSize: 15, color: c.onSurface },
  verdict: { fontFamily: fonts.displayBold, fontSize: 20, lineHeight: 26, color: c.onSurface },
  why: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface },
  label: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.onSurface },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.md },
  permRow: { gap: 4, paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: c.border },
  sectionLine: { fontFamily: fonts.text, fontSize: 14, lineHeight: 21, color: c.onSurface },
  sectionHeading: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.muted, marginTop: spacing.xs },
  orDivider: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  orLine: { flex: 1, height: 1, backgroundColor: c.border },
  orText: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.muted },
}));

function Section({ title, lines, styles: s, testID }: { title: string; lines: string[]; styles: ReturnType<typeof useStyles>; testID: string }) {
  if (!lines.length) return null;
  return <View style={{ gap: 2 }} testID={testID}><Text style={s.sectionHeading}>{title}</Text>{lines.map((l, i) => <Text key={i} style={s.sectionLine} testID={`${testID}-${i}`}>• {l}</Text>)}</View>;
}

export default function CheckApp() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const params = useLocalSearchParams<{ name?: string; source?: AppSource; scent?: string; sample?: string }>();
  const { ready, setupDone, upsertEvent, resolveEvent, deviceId, adapterLabel, showToast, events } = useApollo();
  const [name, setName] = useState(params.name ?? "");
  const [developer, setDeveloper] = useState("");
  const [source, setSource] = useState<AppSource>(params.source ?? "not_sure");
  const [purpose, setPurpose] = useState<AppPurpose>("other");
  const [perms, setPerms] = useState<AppPermission[]>([]);
  const [ctx, setCtx] = useState({ promptedByCaller: false, promptedByMessageOrSite: false, intentional: false, accessGrantedNow: false });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ submissionId: string; a: AppAnalysis; event: PatrolEvent | null; remote: Remote | null; linked: PatrolEvent | null; sdk: Awaited<ReturnType<typeof AppDeviceSdk.getInstalledAppAssessment>> | null; profile: EvidenceProfile } | null>(null);
  const [permSheet, setPermSheet] = useState<AppPermission | null>(null);
  // Pick-from-installed-apps (Android): list launchable apps so the person doesn't have to type the name.
  const [pickerOpen, setPickerOpen] = useState(false);
  const [installedApps, setInstalledApps] = useState<InstalledAppRef[] | null>(null);
  const [appPicker, setAppPicker] = useState(false);
  const [appsLoading, setAppsLoading] = useState(false);
  const [pickedPackage, setPickedPackage] = useState<string | null>(null);
  // Set when a simulated app has been filled in and the ordinary check should run once the fields land.
  const [autoRun, setAutoRun] = useState<string | null>(null);
  // The fields came from a preview sample app: checked exactly as a picked app, only tagged Simulated.
  const [sampled, setSampled] = useState(false);
  const [appQuery, setAppQuery] = useState("");
  const [actionGuidance, setActionGuidance] = useState<string | null>(null);
  const [showMoreFields, setShowMoreFields] = useState(false);
  const [verifyNote, setVerifyNote] = useState<string | null>(null);
  const [savedState, setSavedState] = useState<"idle" | "saved">("idle");
  const awaitingReturn = React.useRef(false);
  const showSettings = (analysis: AppAnalysis) => {
    const [label, path] = settingsFor(analysis);
    awaitingReturn.current = true;
    if (Platform.OS === "web") setActionGuidance(`${label}: ${path}`);
    else void openDeviceSettings(label, path, (message) => showToast(message, "neutral"));
  };
  const canPickApps = Platform.OS === "android";
  const openPicker = async () => {
    setPickerOpen(true);
    if (installedApps !== null || appsLoading) return;
    setAppsLoading(true);
    try { const list = await AppDeviceSdk.listInstalledApps(); setInstalledApps(list); }
    catch (error) {
      // A failed read is not an empty device. Say so and leave the manual entry available.
      setInstalledApps(null);
      showToast(error instanceof NativeCallFailed
        ? "ApolloSG couldn't read the list of installed apps from this device. Type the app name instead."
        : "ApolloSG couldn't read the list of installed apps. Type the app name instead.", "growling");
    }
    finally { setAppsLoading(false); }
  };
  const pickApp = (app: InstalledAppRef) => { setName(app.appName); setPickedPackage(app.packageId); setSource("not_sure"); setPerms([]); setPickerOpen(false); setAppQuery(""); setSampled(false); };
  // A sample app fills the same answers a person would give, exactly as the installed-apps sheet does.
  const applySampleApp = (id: string) => {
    const prodSample = findSampleApp(id);
    const a = prodSample
      ? { appName: prodSample.appName, developer: prodSample.developer, packageId: prodSample.packageId, source: prodSample.source, purpose: prodSample.purpose, permissions: prodSample.permissions }
      : simulation.apps.find((x) => x.id === id);
    if (!a) return;
    setName(a.appName); setDeveloper(a.developer); setPickedPackage(a.packageId);
    setSource(a.source); setPurpose(a.purpose); setPerms(a.permissions);
    setSampled(true);
    setAutoRun(a.appName);
  };
  // A sample chosen from Sample Checks (or preview) runs exactly as picking it here does.
  const sampleRan = React.useRef(false);
  useEffect(() => {
    if (!params.sample || !ready || !setupDone || sampleRan.current) return;
    sampleRan.current = true;
    applySampleApp(params.sample);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.sample, ready, setupDone]);
  const filteredApps = (installedApps ?? []).filter((a) => a.appName.toLowerCase().includes(appQuery.trim().toLowerCase()));

  // Threat Scent: non-resting events from other gates inside the window (call → link → download → install).
  const recentLinked = useMemo(() => { const now = Date.now(); return events.filter((e) => e.state !== "resting" && LINKED_CATEGORIES.has(e.category) && now - Date.parse(e.occurred_at) <= SCENT_WINDOW_MS); }, [events]);

  // A simulated app selection fills the same answers a person would give, then runs the ordinary check.
  useEffect(() => {
    if (!autoRun || name !== autoRun || busy) return;
    setAutoRun(null);
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, name]);

  const run = async () => {
    setBusy(true);
    try {
    void markCheckDone("app");
      let network: AppNetwork | null = null;
      let sdk: Awaited<ReturnType<typeof AppDeviceSdk.getInstalledAppAssessment>> = null;
      try {
        sdk = await AppDeviceSdk.getInstalledAppAssessment((pickedPackage ?? name).trim());
      } catch {
        // Apollo could not read the app's real details from this device. The check continues from what
        // the person entered, and that limitation is stated rather than hidden.
        showToast("Apollo couldn't read this app's details from the device. This check uses only the details you entered.", "growling");
      }
      if (sdk?.network) network = sdk.network;
      // Phase A: observed facts from the native SDK override guesses — install source when the person wasn't sure,
      // and the app's actual permissions (plus remote-access capability) are added to what they ticked.
      const observedSource: AppSource = sdk && source === "not_sure" ? sdk.installSource : source;
      const nativeRequested = sdkPermissionsToApp(sdk?.requestedPermissions ?? sdk?.permissions ?? []);
      const observedPerms: AppPermission[] = sdk ? Array.from(new Set([...perms, ...nativeRequested, ...(sdk.remoteAccessCapability ? ["screen_share" as const] : [])])) : perms;
      if (sdk) { setSource(observedSource); setPerms(observedPerms); }
      const context = { ...ctx, recentScentCategories: recentLinked.map((e) => e.category) };
      let a = analyseApp({ name: name.trim(), developer: developer.trim() || undefined, source: observedSource, purpose, permissions: observedPerms, context, network });
      let remote: Remote | null = null;
      try {
        remote = await apiPost<Remote>("/app/analyse", "app_check", { device_id: deviceId ?? "local-device", name: name.trim(), developer: developer.trim() || null, source: observedSource, purpose, permissions: observedPerms, hosts: network?.hosts ?? [], local_state: a.state, scenario: a.scenario, second_opinion: false });
        const bad = remote.hosts.filter((h) => h.verdict === "malicious").length;
        if (bad && a.state !== "barking") a = { ...a, state: "barking", title: "Dangerous destination observed", verdict: `${bad} destination${bad > 1 ? "s have" : " has"} a malicious reputation. This does not prove the app is malicious or that Apollo blocked its traffic.`, why: [...a.why, "Threat intelligence identified a destination associated with this app as malicious."], handoff: "network" };
      } catch { /* offline: on-device engine is authoritative */ }
      // Higgins Triage's classification of what ApolloSG had for this app: what was entered, or what this phone said.
      const profile = buildAppProfile({
        via: pickedPackage ? "picked" : params.name ? "linked" : "typed", name: name.trim(), developer: developer.trim() || null,
        source: observedSource, ticked: perms, device: sdk ?? null, analysis: a,
        badDestinations: remote?.hosts.filter((h) => h.verdict === "malicious").length ?? 0,
        simulated: sampled,
      });
      let event: PatrolEvent | null = null;
      const linked = recentLinked.find((e) => (ctx.promptedByCaller && e.category === "call") || (ctx.promptedByMessageOrSite && e.category !== "call")) ?? (a.remoteCapable || a.scenario === "A16" ? recentLinked[0] : null) ?? null;
      if (a.state !== "resting") {
        event = await upsertEvent({ event_id: Math.random().toString(36).slice(2) + Date.now().toString(36), origin: "user", device_id: deviceId ?? "local", category: "app", state: a.state, status: "active", headline: `App: ${a.title}`, what_happened: a.verdict, why: a.why, what_to_do: a.recommendation, indicator_host: null, indicator_digest: null, local_indicator: a.technical[0], verified_block: false, adapter_label: adapterLabel, occurred_at: new Date().toISOString(), resolved_at: null, trust_allowed: false, claimed_brand: a.claimedBrand, scenario: a.scenario, scent_id: params.scent || linked?.scent_id || linked?.event_id || null, evidence_profile: profile }, { kind: "app", fields: [{ label: "App", value: name.trim() }, ...(developer.trim() ? [{ label: "Developer", value: developer.trim() }] : []), { label: "Install source", value: observedSource }, ...(observedPerms.length ? [{ label: "Permissions", value: observedPerms.join(", ") }] : [])], data: sdk ?? null });
        if (event.state !== a.state) a = { ...a, state: event.state, why: event.why };
      }
      setResult({ submissionId: event?.event_id ?? Crypto.randomUUID(), a, event, remote, linked, sdk: sdk ?? null, profile });
    } finally { setBusy(false); }
  };
  const settingsFor = (a: AppAnalysis) => (a.permissionNotes.some((n) => n.id === "accessibility" && !n.expected) ? (["accessibility", "Settings → Accessibility"] as const) : (["apps", "Settings → Apps → the app"] as const));

  const [historyKey, setHistoryKey] = useState(0);
  useEffect(() => { if (result?.a) { void recordCheck("app", { at: new Date().toISOString(), state: result.a.state, summary: result.a.title }); setHistoryKey((k) => k + 1); } }, [result]);

  const findings = useMemo<PermissionFinding[]>(() => (result?.a ? buildPermissionFindings(result.a.permissionNotes, result.sdk) : []), [result]);
  // Re-verify on return: if the person went to Settings from a finding, re-read this app's permission
  // states when Apollo comes back and report the change honestly (confirmed off / couldn't confirm).
  useEffect(() => {
    const sub = AppState.addEventListener("change", (st) => {
      if (st !== "active" || !awaitingReturn.current) return;
      awaitingReturn.current = false;
      if (Platform.OS !== "android" || !pickedPackage || !result) { setVerifyNote("ApolloSG can't re-read this app's live permissions on this build, so it couldn't confirm the change. Check the screen you just left."); return; }
      void AppDeviceSdk.getInstalledAppAssessment(pickedPackage).then((sdk) => {
        if (!sdk) { setVerifyNote("Apollo couldn't confirm the change — it can't read this app's permissions right now."); return; }
        const resolved = confirmedResolved(buildPermissionFindings(result.a.permissionNotes, result.sdk), buildPermissionFindings(result.a.permissionNotes, sdk));
        setResult((cur) => (cur ? { ...cur, sdk } : cur));
        setVerifyNote(resolved.length ? `Apollo confirmed: ${resolved.map((f) => f.label).join(", ")} ${resolved.length > 1 ? "are" : "is"} now off for this app.` : "ApolloSG re-checked this app. No change to its access was confirmed.");
      }).catch(() => setVerifyNote("ApolloSG tried to re-read this app's permissions and the device read failed, so it couldn't confirm the change."));
    });
    return () => sub.remove();
  }, [pickedPackage, result]);

  const reviewPermission = (f: PermissionFinding) => {
    const ps = permissionSettings(f.id, name);
    setActionGuidance(`To review ${f.label}: ${ps.path}`);
    awaitingReturn.current = true;
    if (Platform.OS !== "web") void openDeviceSettings(ps.target, ps.path, (m) => showToast(m, "neutral"));
  };

  if (ready && !setupDone) return <Redirect href="/" />;
  const a = result?.a;
  const canRun = name.trim().length > 0 && !busy;
  const appLabel = result?.sdk?.appName || name || "This app";
  const sourceLabel = APP_SOURCES.find((x) => x.id === source)?.label ?? "an unknown source";

  // UNIVERSAL CHECK RESULT — when the app check has produced an outcome, the entire screen
  // becomes the shared Check Result with gate-specific actions.
  if (result && a) {
    const model = { ...buildAppCheckResult({ analysis: a, event: result.event, appName: appLabel, submissionId: result.submissionId }), evidenceProfile: result.event?.evidence_profile ?? result.profile };
    const askPrompt = `About the app I just checked (${model.subject}). ${model.headline} Can you walk me through what Apollo found and what I should do?`;
    const appActions: { label: string; onPress: () => void; testID: string; variant?: "primary" | "secondary" | "ghost" }[] = [];
    if (a.state !== "resting") {
      appActions.push({ testID: "app-open-settings", variant: a.state === "barking" ? "secondary" : "secondary", label: Platform.OS === "web" ? "Show Settings steps" : a.state === "barking" ? "Open removal settings" : "Open app settings", onPress: () => showSettings(a) });
    }
    // Permission review actions
    if (findings.filter((f) => f.actionable).length) {
      appActions.push({ testID: "app-review-perms", variant: "secondary", label: "Review permissions one by one", onPress: () => { const first = findings.find((f) => f.actionable); if (first) reviewPermission(first); } });
    }
    if (a.state !== "resting" || a.remoteCapable || findings.length > 0) {
      appActions.push({ testID: "app-check-device", variant: "ghost", label: "Check the rest of this device", onPress: () => router.push("/device") });
    }
    if (result.event) {
      appActions.push({ testID: "app-keep", variant: "ghost", label: "Mark as handled", onPress: () => { void resolveEvent(result.event!); setResult({ ...result, event: { ...result.event!, status: "resolved" } }); } });
    }
    appActions.push({ testID: "app-save-report", variant: "ghost", label: savedState === "saved" ? "Saved \u2713 \u2014 View saved checks" : "Save this check", onPress: () => { if (savedState === "saved") { router.push("/saved-checks"); return; } void saveAppReport({ id: Crypto.randomUUID(), appLabel, state: a.state, stateName: STATE_NAME[a.state], title: a.title, verdict: a.verdict, recommendation: a.recommendation, scenario: a.scenario, riskScore: a.riskScore, identity: [], permissions: findings.map((f) => `${f.label}: ${f.statusLabel}`), why: a.why, network: [], reputation: result.remote?.reputation.note ?? null, evidence: [], coverage: [] }).then(() => { setSavedState("saved"); showToast("Saved. Find it under Saved checks.", "neutral"); }); } });
    appActions.push({ testID: "app-again", variant: "ghost", label: "Check another app", onPress: () => { setResult(null); setName(""); setDeveloper(""); setPerms([]); setPickedPackage(null); setActionGuidance(null); setVerifyNote(null); setSavedState("idle"); } });

    return (
      <>
        {result.event ? (
          <InvestigationCheckScreen
            result={model}
            investigationContext={contextFromEvent(result.event, gateForCategory(result.event.category))}
            investigationQuestion={askPrompt}
            submissionId={result.event.event_id}
            eventId={result.event.event_id}
            caseId={result.event.investigation_case_id ?? null}
            actions={appActions}
          />
        ) : (
          <CheckResultScreen result={model} actions={appActions} />
        )}
        {a.stayWithMe && result.event ? <RecoveryFlow event={result.event} kinds={["remote", "banking_during_access", "password", "code", "accessibility"]} testID="app-recovery" /> : result.event ? <RecoveryFlow event={result.event} kinds={["remote", "accessibility", "profile", "password", "banking_during_access", "money"]} testID="app-recovery" /> : null}
        {verifyNote ? <Card testID="app-verify-note"><Body>{verifyNote}</Body></Card> : null}
        <Card testID="app-capability-evidence-note" style={{ gap: spacing.xs }}><Body>An inactive or dormant app keeps those capabilities until you revoke them. Only uninstalling or disabling the app fully removes its access.</Body></Card>
        {actionGuidance ? <Card testID="app-action-guidance" style={{ gap: spacing.xs }}><SectionTitle>Next step in Settings</SectionTitle><Body>{actionGuidance}</Body><Button testID="app-action-guidance-close" variant="ghost" label="Hide" onPress={() => setActionGuidance(null)} /></Card> : null}
        <Sheet visible={!!permSheet} onClose={() => setPermSheet(null)} title={permSheet ? PERMISSION_INFO[permSheet].label : ""} testID="app-perm-sheet">
          {permSheet ? <Body testID="app-perm-plain">{PERMISSION_INFO[permSheet].plain}</Body> : null}
          <Button testID="app-perm-close" variant="ghost" label="Done" onPress={() => setPermSheet(null)} />
        </Sheet>
      </>
    );
  }
  return (
    <View style={s.root}>
      <View style={[s.top, { paddingTop: insets.top + spacing.md }]}>
        <CheckToolHeader
          title="Check an app"
          info={{ title: "About app checking", body: ["Enter any app name and Apollo will research its safety, permissions, publisher reputation and known issues.", "Apollo checks app store listings, publisher history, permission requests and community reports. This is a research check — Apollo does not scan installed apps directly."] }}
          testID="app-check"
        />
      </View>
      <KeyboardAwareScrollView contentContainerStyle={[s.content, { paddingBottom: insets.bottom + spacing.xl }]} bottomOffset={24} testID="app-scroll">
        {!result ? (
          <>
            <SourceHero
              testID="app-hero"
              title="Pick an app from this device"
              caption="Apollo checks the app's source, its stated permissions and what it says it does. Nothing is installed or changed."
              actions={[{
                testID: "app-pick-installed",
                label: appsLoading ? "Reading your apps…" : "Choose an installed app",
                disabled: busy || appsLoading,
                icon: <Smartphone size={20} color={colors.onBrandPrimary} />,
                onPress: () => { if (canPickApps) { void openPicker(); return; } setAppPicker(true); },
              }]}
            />

            {/* ── Or divider ── */}
            <View style={s.orDivider}>
              <View style={s.orLine} />
              <Text style={s.orText}>or enter manually</Text>
              <View style={s.orLine} />
            </View>

            {/* ── Manual app name entry (secondary) ── */}
            <TextInput testID="app-name" style={s.input} value={name} onChangeText={(t) => { setName(t); setPickedPackage(null); }} maxLength={120} placeholder="App name" placeholderTextColor={colors.muted} autoCapitalize="words" autoCorrect={false} />
            <Button testID="app-run" label={busy ? "Sniffing…" : "Check with ApolloSG"} onPress={() => void run()} disabled={!canRun} />
            {recentLinked.length ? <Card style={{ gap: spacing.xs, borderColor: colors.growling }} testID="app-scent-notice"><Text style={s.label}>Threat Scent</Text><Body>Apollo saw {recentLinked.length} suspicious event{recentLinked.length > 1 ? "s" : ""} in the last 30 minutes ({[...new Set(recentLinked.map((e) => e.category))].join(", ")}). An app installed now will be assessed as part of that sequence.</Body></Card> : null}
            <Pressable testID="app-more-details" accessibilityRole="button" onPress={() => setShowMoreFields(!showMoreFields)} style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs, paddingVertical: spacing.xs }}>
              <Text style={{ fontFamily: fonts.textSemibold, fontSize: 14, color: colors.brand }}>{showMoreFields ? "Hide details" : "Add more details"}</Text>
            </Pressable>
            {showMoreFields ? (
              <>
                <Text style={s.label}>Developer (if shown)</Text>
                <TextInput testID="app-developer" style={s.input} value={developer} onChangeText={setDeveloper} maxLength={120} placeholder="Optional" placeholderTextColor={colors.muted} autoCapitalize="words" autoCorrect={false} />
                <Text style={s.label}>Where did it come from?</Text>
                <View style={s.chips}>{APP_SOURCES.map((o) => <Pressable key={o.id} testID={`app-source-${o.id}`} accessibilityRole="button" onPress={() => setSource(o.id)} style={[s.chip, source === o.id && s.chipOn]}><Text style={s.chipText}>{o.label}</Text></Pressable>)}</View>
                <Text style={s.label}>What does it say it does?</Text>
                <View style={s.chips}>{APP_PURPOSES.map((o) => <Pressable key={o.id} testID={`app-purpose-${o.id}`} accessibilityRole="button" onPress={() => setPurpose(o.id)} style={[s.chip, purpose === o.id && s.chipOn]}><Text style={s.chipText}>{o.label}</Text></Pressable>)}</View>
                <Text style={s.label}>What can it access? (Settings → Apps → Permissions)</Text>
                <View style={s.chips}>{APP_PERMISSIONS.map((p) => <Pressable key={p} testID={`app-perm-${p}`} accessibilityRole="button" onPress={() => setPerms((cur) => (cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]))} onLongPress={() => setPermSheet(p)} style={[s.chip, perms.includes(p) && s.chipWarn]}><Text style={s.chipText}>{PERMISSION_INFO[p].label}</Text></Pressable>)}</View>
                <Body>Hold a permission to see what it means.</Body>
                <Text style={s.label}>What was happening around the install?</Text>
                <View style={s.row}><Text style={[s.why, { flex: 1 }]}>Someone on a phone call told me to install it</Text><Switch testID="app-ctx-caller" value={ctx.promptedByCaller} onValueChange={(v) => setCtx((c) => ({ ...c, promptedByCaller: v }))} trackColor={{ true: colors.growling, false: colors.borderStrong }} thumbColor={colors.onSurface} /></View>
                <View style={s.row}><Text style={[s.why, { flex: 1 }]}>A message, website or download led me to it</Text><Switch testID="app-ctx-message" value={ctx.promptedByMessageOrSite} onValueChange={(v) => setCtx((c) => ({ ...c, promptedByMessageOrSite: v }))} trackColor={{ true: colors.growling, false: colors.borderStrong }} thumbColor={colors.onSurface} /></View>
                <View style={s.row}><Text style={[s.why, { flex: 1 }]}>I sought this app out myself (e.g. I called my own IT provider)</Text><Switch testID="app-ctx-intentional" value={ctx.intentional} onValueChange={(v) => setCtx((c) => ({ ...c, intentional: v }))} trackColor={{ true: colors.resting, false: colors.borderStrong }} thumbColor={colors.onSurface} /></View>
                <View style={s.row}><Text style={[s.why, { flex: 1 }]}>Someone is connected to / controlling my phone through it</Text><Switch testID="app-ctx-access" value={ctx.accessGrantedNow} onValueChange={(v) => setCtx((c) => ({ ...c, accessGrantedNow: v }))} trackColor={{ true: colors.barking, false: colors.borderStrong }} thumbColor={colors.onSurface} /></View>
              </>
            ) : null}
            <Button testID="app-open-saved" variant="ghost" label="Saved checks" onPress={() => router.push("/saved-checks")} />
          </>
        ) : null}
        <CheckHistoryCard gate="app" refreshKey={historyKey} testID="app-history" />
      </KeyboardAwareScrollView>
      <Sheet visible={pickerOpen} onClose={() => { setPickerOpen(false); setAppQuery(""); }} title="Pick an installed app" testID="app-picker-sheet">
        <TextInput testID="app-picker-search" style={s.input} value={appQuery} onChangeText={setAppQuery} placeholder="Search your apps" placeholderTextColor={colors.muted} autoCapitalize="none" autoCorrect={false} />
        {appsLoading ? <View style={{ paddingVertical: spacing.lg, alignItems: "center" }}><ActivityIndicator color={colors.gold} /></View>
          : (installedApps?.length ?? 0) === 0 ? <Body testID="app-picker-empty">ApolloSG can&apos;t list installed apps on this build. Type the app name instead — this feature needs a production build.</Body>
          : <ScrollView style={{ maxHeight: 360 }} testID="app-picker-list" keyboardShouldPersistTaps="handled" nestedScrollEnabled>
              {filteredApps.length === 0 ? <Body>No apps match “{appQuery}”.</Body> : filteredApps.map((app) => (
                <Pressable key={app.packageId} testID={`app-picker-${app.packageId}`} accessibilityRole="button" onPress={() => pickApp(app)} style={({ pressed }) => [s.permRow, { paddingVertical: spacing.md, opacity: pressed ? 0.7 : 1 }]}>
                  <Text style={s.label}>{app.appName}</Text>
                  <Text style={s.why} numberOfLines={1}>{app.packageId}</Text>
                </Pressable>
              ))}
            </ScrollView>}
        <Button testID="app-picker-close" variant="ghost" label="Close" onPress={() => { setPickerOpen(false); setAppQuery(""); }} />
      </Sheet>
      <SourcePickerSheet
        visible={appPicker}
        title="Installed apps"
        note="Each one stands in for an app and its stated permissions. Apollo runs the real app check on whichever you pick."
        preview={simulation.included}
        error={simulation.included ? null : Platform.OS === "android" ? "ApolloSG can't list installed apps on this build. Type the app name below instead — this needs a production build." : "Your device doesn't let apps see what else is installed. Type the app name below instead."}
        items={simulation.apps.map((a) => ({ id: a.id, primary: a.appName, secondary: `${a.developer} · ${a.packageId}`, meta: a.probes }))}
        emptyText="There are no apps to choose from here."
        onSelect={(id: string) => {
          setAppPicker(false);
          applySampleApp(id);
        }}
        onClose={() => setAppPicker(false)}
        testID="app-source-picker"
      />
    </View>
  );
}
