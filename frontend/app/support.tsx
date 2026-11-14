// Apollo Support — central place for app/device details, live protection status, current issues,
// Device Checkup history, diagnostics export and support contact (spec: Support Screen Enhancement).
// It DISPLAYS status; it never runs duplicate diagnostics — "Go to Check" sends manual diagnostics
// (including Device Re-check) to the Check tab. Preview builds never show fabricated native data.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import * as Clipboard from "expo-clipboard";
import * as Print from "expo-print";
import * as Sharing from "expo-sharing";
import ArrowRight from "lucide-react-native/icons/arrow-right";
import CircleCheck from "lucide-react-native/icons/circle-check";
import ChevronDown from "lucide-react-native/icons/chevron-down";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import CircleX from "lucide-react-native/icons/circle-x";
import Copy from "lucide-react-native/icons/copy";
import FileDown from "lucide-react-native/icons/file-down";
import Mail from "lucide-react-native/icons/mail";
import RefreshCw from "lucide-react-native/icons/refresh-cw";
import React, { useEffect, useMemo, useState } from "react";
import { Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { apiGet } from "@/src/api/client";
import { Body, Button, Card, Pill, SectionTitle, type Tone } from "@/src/components/ui";
import { useSystemHealth } from "@/src/health/systemHealthCoordinator";
import { providerStatusLines } from "@/src/health/providerStatus";
import type { CheckRow, CheckStatus, FullHealthCheck } from "@/src/health/systemHealthTypes";
import { securityAdapter } from "@/src/security/securityAdapter";
import { getBaseline } from "@/src/store/firstCheckStore";
import { useApollo } from "@/src/store/ApolloContext";
import { collectAppDeviceInfo, UNAVAILABLE } from "@/src/support/supportInfo";
import { openSupportEmail, SUPPORT_RECIPIENT } from "@/src/support/supportEmail";
import { getOrCreateSupportReference, getReferenceHistory, reopenSupportReference, startNewSupportReference } from "@/src/support/supportReference";
import { buildHigginsInfo, buildProtectionRows, buildSupportSummary, renderEmailBody, renderReportHtml, renderSupportSummaryText, type ProtectionState, type SupportProtectionRow } from "@/src/support/supportSummary";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { goBackOrHome } from "@/src/utils/navigation";
import { storage } from "@/src/utils/storage";
import { recentNativeFailures } from "@/src/security/nativeDiagnostics";
import { CloseButton } from "@/src/components/CloseButton";
import { getSharedSLM } from "@/src/domain/slm/sharedRuntime";

const USER_EMAIL_KEY = "apollo.support.user_email.v1";

interface IntelStatus { safe_browsing: { status: string; detail: string }; blocklist: { status: string; entries: number } }
interface DiagnosticCheck { check: string; passed: boolean; detail: string; backend_public_key?: string; pinned_apk_key?: string }
interface DiagnosticResult { diagnostic: string; checks: DiagnosticCheck[] }
const CHECK_LABELS: Record<string, string> = {
  bundle_generation: "Threat Domain List generation",
  threat_domain_entries: "Threat Domain Entries",
  signing_enabled: "Ed25519 signing",
  signature_valid: "Signature self-verify",
  public_key_match: "Public key vs. APK pin",
  schema: "Threat Domain List format",
  expiry: "Threat Domain List expiry",
};
async function fetchRuleDiagnostic(): Promise<DiagnosticResult> {
  const res = await fetch(`${process.env.EXPO_PUBLIC_BACKEND_URL}/api/guarddog/rules/diagnostic`, { headers: { "Accept": "application/json" } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
const STATUS: Record<CheckStatus, string> = { pending: "Could not check", checking: "Checking", healthy: "Working", degraded: "Needs attention", unavailable: "Could not check" };
const RESULT_TEXT = {
  device: { working: "Protection on this device is working.", problem: "Apollo cannot confirm protection right now." },
  backend: { working: "ApolloSG's online services are working.", problem: "ApolloSG's online services need attention. Protection on this device may continue." },
  higgins: { working: "Higgins can complete investigations.", problem: "Higgins cannot complete an investigation right now." },
  report: { working: "Higgins can prepare reports.", problem: "Higgins cannot prepare a report right now." },
} as const;
function statusTone(status: CheckStatus): Tone { return status === "healthy" ? "resting" : status === "degraded" ? "growling" : "unknown"; }
function protectionTone(state: ProtectionState): Tone {
  if (state === "Active and verified" || state === "Active" || state === "Available") return "resting";
  if (state === "Warning") return "growling";
  if (state === "Unverified") return "ears_up";
  return "unknown";
}

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  top: { paddingHorizontal: spacing.xl, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingBottom: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 26, color: c.onSurface },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: c.surfaceTertiary },
  content: { paddingHorizontal: spacing.xl, gap: spacing.lg },
  card: { gap: spacing.md },
  sectionHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.md },
  sectionHeadTitle: { fontFamily: fonts.displayBold, fontSize: 17, color: c.onSurface, flex: 1 },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: spacing.md },
  statusRow: { alignItems: "flex-start", gap: spacing.xs },
  rowLabel: { fontFamily: fonts.textMedium, fontSize: 15, color: c.onSurface },
  label: { fontFamily: fonts.textMedium, fontSize: 15, color: c.onSurface, flex: 1 },
  value: { fontFamily: fonts.textMedium, fontSize: 13, color: c.onSurfaceSecondary, flexShrink: 1, textAlign: "right" },
  detail: { fontFamily: fonts.text, fontSize: 13, lineHeight: 19, color: c.muted },
  refBox: { padding: spacing.md, borderRadius: radius.md, backgroundColor: c.surfaceTertiary, gap: 2 },
  refValue: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface },
  logLine: { fontFamily: fonts.text, fontSize: 12, lineHeight: 18, color: c.onSurfaceSecondary },
  emailInput: { borderWidth: 1, borderColor: c.border, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 10, fontFamily: fonts.text, fontSize: 15, color: c.onSurface, backgroundColor: c.surfaceTertiary },
  inboxRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.sm, paddingHorizontal: spacing.md, borderRadius: radius.md, backgroundColor: c.surfaceTertiary },
  inboxRef: { fontFamily: fonts.textMedium, fontSize: 12, color: c.onSurface },
  inboxReopen: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.brand },
}));

function Section({ title, testID, children, defaultOpen = true }: { title: string; testID: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const s = useStyles();
  const { colors } = useTheme();
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Card style={s.card} testID={testID}>
      <Pressable testID={`${testID}-toggle`} accessibilityRole="button" accessibilityState={{ expanded: open }} onPress={() => setOpen((v) => !v)} style={s.sectionHead}>
        <Text style={s.sectionHeadTitle}>{title}</Text>
        {open ? <ChevronDown size={20} color={colors.muted} /> : <ChevronRight size={20} color={colors.muted} />}
      </Pressable>
      {open ? children : null}
    </Card>
  );
}

function ResultRow({ label, result, id }: { label: string; result: CheckRow; id: keyof typeof RESULT_TEXT }) {
  const s = useStyles();
  const sentence = result.status === "checking" ? "Checking current status…" : RESULT_TEXT[id][result.status === "healthy" ? "working" : "problem"];
  return <View testID={`support-${id}-row`}><View style={s.statusRow}><Text style={s.rowLabel} testID={`support-${id}-label`}>{label}</Text><Pill testID={`support-${id}-status`} tone={statusTone(result.status)} label={STATUS[result.status]} /></View><Body testID={`support-${id}-message`}>{sentence}</Body>{result.checkedAt ? <Body style={s.detail}>Checked {new Date(result.checkedAt).toLocaleString()}</Body> : null}</View>;
}

function InfoRow({ label, value }: { label: string; value: string }) {
  const s = useStyles();
  return <View style={s.row}><Text style={s.label}>{label}</Text><Text style={s.value}>{value}</Text></View>;
}

function recentLogLines(health: FullHealthCheck, firstCheckConcerns: string[], evidenceSummary: string | null): string[] {
  const lines: string[] = [];
  if (health.checkedAt) for (const [id, label] of [["device", "Apollo protection"], ["backend", "Online services"], ["higgins", "Higgins"], ["report", "Reports"]] as const) {
    const row = health[id as "device"]; lines.push(`${new Date(row.checkedAt ?? health.checkedAt!).toLocaleString()} · ${STATUS[row.status].toUpperCase()} · ${label}`);
  }
  for (const concern of firstCheckConcerns) lines.push(`Apollo First Check · ${concern}`);
  // Device capability reads Apollo attempted and could not complete — shown so a failed check is never
  // mistaken for a clean one.
  for (const failure of recentNativeFailures()) {
    lines.push(`${new Date(failure.at).toLocaleString()} · DEVICE READ FAILED · ${failure.operation} · ${failure.detail}`);
  }
  if (evidenceSummary) lines.push(evidenceSummary);
  if (!lines.length) lines.push("No diagnostic events recorded yet. Run a check from the Check tab.");
  return lines;
}

function DiagnosticSection() {
  const s = useStyles();
  const { colors } = useTheme();
  const queryClient = useQueryClient();
  const diag = useQuery({ queryKey: ["guarddog-rule-diagnostic"], queryFn: fetchRuleDiagnostic, staleTime: 120_000, retry: 1 });
  const allPassed = diag.data?.checks.every((c) => c.passed) ?? false;

  return (
    <Section title="Threat Domain List Delivery" testID="support-rule-diagnostic-section" defaultOpen={true}>
      <Body style={s.detail}>
        End-to-end check of how ApolloSG builds and signs its Threat Domain List. Every check must pass for website protection to start on a phone. A list with 0 entries is valid.
      </Body>
      {diag.isLoading ? <Body>Running diagnostic checks…</Body> : diag.isError ? (
        <View style={{ gap: spacing.xs }}>
          <View style={s.statusRow}>
            <Text style={s.rowLabel}>Backend unreachable</Text>
            <Pill tone="barking" label="Failed" />
          </View>
          <Body style={s.detail}>{diag.error instanceof Error ? diag.error.message : "Could not reach the rule diagnostic endpoint."}</Body>
        </View>
      ) : diag.data ? (
        <View style={{ gap: spacing.md }}>
          <View style={s.statusRow}>
            <Text style={s.rowLabel}>Overall</Text>
            <Pill tone={allPassed ? "resting" : "barking"} label={allPassed ? "All checks passed" : "Issues found"} />
          </View>
          {diag.data.checks.map((check) => (
            <View key={check.check} style={{ gap: 2 }} testID={`diag-check-${check.check}`}>
              <View style={[s.row, { gap: spacing.sm }]}>
                {check.passed
                  ? <CircleCheck size={16} color={colors.resting ?? colors.brand} />
                  : <CircleX size={16} color={colors.barking ?? colors.error ?? "#D32F2F"} />}
                <Text style={[s.label, { flex: 1 }]}>{CHECK_LABELS[check.check] ?? check.check}</Text>
                <Pill tone={check.passed ? "resting" : "barking"} label={check.passed ? "Pass" : "Fail"} />
              </View>
              <Body style={s.detail}>{check.detail}</Body>
              {check.backend_public_key && !check.passed ? (
                <Body style={s.detail}>Backend key: {check.backend_public_key}{"\n"}APK pinned:  {check.pinned_apk_key}</Body>
              ) : null}
            </View>
          ))}
        </View>
      ) : null}
      <Button testID="support-rerun-diagnostic" variant="secondary" label={diag.isFetching ? "Running…" : "Re-run diagnostic"} icon={<RefreshCw size={16} color={colors.brand} />} disabled={diag.isFetching} onPress={() => { queryClient.invalidateQueries({ queryKey: ["guarddog-rule-diagnostic"] }); }} />
    </Section>
  );
}

export default function SupportScreen() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { adapterLabel, protection, showToast } = useApollo();
  const health = useSystemHealth();

  const [moreDetails, setMoreDetails] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [userEmail, setUserEmail] = useState("");
  useEffect(() => { void storage.getItem<string | null>(USER_EMAIL_KEY, null).then((v) => { if (v) setUserEmail(v); }); }, []);

  const appDevice = useQuery({ queryKey: ["support-app-device"], queryFn: collectAppDeviceInfo, staleTime: 300_000 });
  const net = useQuery({ queryKey: ["support-net"], queryFn: () => securityAdapter.getNetworkStatus(), staleTime: 30_000 });
  const evidence = useQuery({ queryKey: ["support-evidence"], queryFn: () => securityAdapter.getEnforcementEvidence(), staleTime: 60_000 });
  const perms = useQuery({ queryKey: ["support-perms"], queryFn: () => securityAdapter.getProtectionPermissions(), staleTime: 60_000 });
  const firstCheck = useQuery({ queryKey: ["support-firstcheck"], queryFn: getBaseline, staleTime: 30_000 });
  const intel = useQuery({ queryKey: ["support-intel-status"], queryFn: () => apiGet<IntelStatus>("/intel/status"), staleTime: 60_000 });
  const reference = useQuery({ queryKey: ["support-reference"], queryFn: getOrCreateSupportReference });
  const history = useQuery({ queryKey: ["support-reference-history"], queryFn: getReferenceHistory });

  const protectionRows = useMemo<SupportProtectionRow[]>(() => buildProtectionRows(
    protection, net.data ?? null, evidence.data ?? [],
    { safeBrowsing: (intel.data?.safe_browsing.status as "ok" | "not_configured" | "unavailable" | undefined) ?? null, blocklistEntries: intel.data?.blocklist.entries ?? null },
  ), [protection, net.data, evidence.data, intel.data]);

  const higgins = useMemo(() => buildHigginsInfo(health.checkedAt ? health : null, firstCheck.data ?? null), [health, firstCheck.data]);
  const missingPerms = (perms.data ?? []).filter((p) => p.status === "denied" || p.status === "blocked");

  const summary = useMemo(() => appDevice.data ? buildSupportSummary(appDevice.data.app, appDevice.data.device, protectionRows, higgins) : null, [appDevice.data, protectionRows, higgins]);
  const ref = reference.data ?? null;
  const ready = !!summary && !!ref;

  const copySummary = async () => { if (!ready) return; await Clipboard.setStringAsync(renderSupportSummaryText(summary!, ref!)); showToast("Support summary copied.", "resting"); };
  const exportReport = async () => {
    if (!ready) return;
    const html = renderReportHtml(summary!, ref!);
    if (Platform.OS === "web") { await Print.printAsync({ html }); return; }
    const { uri } = await Print.printToFileAsync({ html });
    if (await Sharing.isAvailableAsync()) await Sharing.shareAsync(uri, { mimeType: "application/pdf", UTI: "com.adobe.pdf", dialogTitle: "ApolloSG Higgins Diagnostic Report" });
    else await Print.printAsync({ uri });
    showToast("Diagnostic report ready to share.", "resting");
  };
  const emailSupport = async () => {
    if (!ready) return;
    const outcome = await openSupportEmail(ref!, renderEmailBody(summary!, ref!), userEmail || null);
    if (outcome === "unavailable") { await Clipboard.setStringAsync(renderSupportSummaryText(summary!, ref!)); showToast(`No email app found. Summary copied — paste it into an email to ${SUPPORT_RECIPIENT}.`, "neutral"); }
    else showToast(userEmail ? "Review the draft, then send. A copy will reach your email too." : "Review the draft, then send it when you're ready.", "resting");
  };
  const newRequest = async () => { await startNewSupportReference(); await reference.refetch(); await history.refetch(); showToast("Started a new support request.", "neutral"); };
  const reopen = async (ref: string) => { await reopenSupportReference(ref); await reference.refetch(); showToast("Reopened that request — the email and report will reuse its reference.", "resting"); };

  const verifiedEvidence = (evidence.data ?? []).filter((e) => e.result === "verified").sort((a, b) => b.observedAt.localeCompare(a.observedAt))[0] ?? null;

  return <View style={s.root} testID="support-screen">
    <View style={[s.top, { paddingTop: insets.top + spacing.md }]}>
      <Text style={s.title} testID="support-title">Support</Text>
      <CloseButton testID="support-close" label="Close Support" onPress={() => goBackOrHome(router)} />
    </View>
    <ScrollView contentContainerStyle={[s.content, { paddingBottom: insets.bottom + spacing.xl }]} testID="support-scroll">

      {/* 1. App & Device Details */}
      <Section title="App & Device Details" testID="support-app-device-section">
        {appDevice.data ? <>
          <InfoRow label="App Version" value={appDevice.data.app.version} />
          <View style={s.row}><Text style={s.label}>Build</Text><Text style={s.value} testID="support-build">{appDevice.data.app.build}</Text></View>
          <View style={s.row}><Text style={s.label}>Build ID</Text><Text style={s.value}>{appDevice.data.app.buildId}</Text></View>
          <InfoRow label="Update ID" value={appDevice.data.app.updateId} />
          <View style={s.row}><Text style={s.label}>Environment</Text><Text style={s.value} testID="support-environment">{appDevice.data.app.environment}{appDevice.data.app.nativeBuild ? "" : " · preview"}</Text></View>
          <InfoRow label="Device" value={appDevice.data.device.name} />
          <InfoRow label="Device Type" value={appDevice.data.device.deviceType} />
          <InfoRow label="Operating System" value={`${appDevice.data.device.os} ${appDevice.data.device.osVersion}`} />
          <InfoRow label="Architecture" value={appDevice.data.device.architecture} />
          <InfoRow label="App first installed" value={appDevice.data.app.installedAt} />
          <InfoRow label="Bundle published" value={appDevice.data.app.bundlePublishedAt} />
          <InfoRow label="Last native update" value={appDevice.data.app.lastNativeUpdateAt} />
          {!appDevice.data.app.nativeBuild ? <Body style={s.detail}>This preview doesn&apos;t include native build metadata. A native ApolloSG build shows real build numbers and install dates.</Body> : null}
          <Button testID="support-more-details" variant="ghost" label={moreDetails ? "Hide extra details" : "More details"} onPress={() => setMoreDetails((v) => !v)} />
          {moreDetails ? <View style={s.card} testID="support-more-details-panel">
            <View style={s.row}><Text style={s.label}>Version</Text><Text style={s.value} testID="support-version">{appDevice.data.app.version}</Text></View>
            <View style={s.row}><Text style={s.label}>Security adapter</Text><Text style={s.value} testID="support-adapter">{adapterLabel}</Text></View>
            <View style={s.row}><Text style={s.label}>Google Safe Browsing</Text><Pill testID="support-safe-browsing-status" tone={intel.data?.safe_browsing.status === "ok" ? "resting" : "unknown"} label={intel.isLoading ? "Checking" : intel.data?.safe_browsing.status === "ok" ? "Available" : intel.data?.safe_browsing.status === "not_configured" ? "Not configured" : "Unavailable"} /></View>
            <View style={s.row}><Text style={s.label}>Apollo threat list</Text><Text style={s.value} testID="support-blocklist-count">{intel.data?.blocklist.entries ?? "—"} entries</Text></View>
          </View> : null}
        </> : <Body>Reading app and device details…</Body>}
      </Section>

      {/* Higgins is the required on-device AI; this view reports facts without running inference. */}
      <Section title="Higgins" testID="support-slm-section">
        <Body style={s.detail}>These are local runtime facts, not an inference benchmark. Installing an APK does not install a model. No cloud response proves Higgins inference.</Body>
        <InfoRow label="Native platform" value={Platform.OS === "android" || Platform.OS === "ios" ? (appDevice.data?.app.nativeBuild ? "Native app" : "Not verified") : "Not supported in this preview"} />
        <InfoRow label="Higgins startup policy" value={Platform.OS === "android" || Platform.OS === "ios" ? "Required on this device" : "Unavailable on this platform"} />
        <InfoRow label="Higgins version" value="ODAI-Q2.5-0.5B-Q4KM-v1" />
        <InfoRow label="Model installed" value="Not verified" />
        <InfoRow label="Model SHA-256" value="Not verified" />
        <InfoRow label="Model loaded" value={getSharedSLM() ? "Runtime registered" : "No runtime registered"} />
        <InfoRow label="Native inference" value="Not verified" />
        <Body style={s.detail} testID="support-slm-explanation">Higgins is the on-device AI and uses Luddish to explain the findings. Model verification, native loading and a successful local response are separate checks. A registered runtime or conversational response alone does not prove successful local inference.</Body>
      </Section>

      {/* 2. Protection & Services */}
      <Section title="Protection & Services" testID="support-protection-section">
        <Body style={s.detail}>Live states from ApolloSG&apos;s native telemetry. A reachable service or enabled setting is not the same as a verified block — only &quot;Active and verified&quot; reflects OS-confirmed enforcement.</Body>
        {protectionRows.map((p) => (
          <View key={p.label} testID={`support-protection-${p.label.replace(/[^a-z]+/gi, "-").toLowerCase()}`}>
            <View style={s.statusRow}><Text style={s.rowLabel}>{p.label}</Text><Pill tone={protectionTone(p.state)} label={p.state} /></View>
            <Body style={s.detail}>{p.detail}</Body>
          </View>
        ))}
      </Section>

      {/* 2b. Rule Bundle Delivery Diagnostic */}
      <DiagnosticSection />

      {/* 3. Current Issues & Higgins */}
      <Section title="Protection Issues & Device Checkup" testID="support-issues-section">
        <InfoRow label="Last Device Checkup" value={higgins.lastCheckAt} />
        <InfoRow label="Last result" value={higgins.result} />
        {higgins.warnings.length ? <View style={{ gap: 2 }} testID="support-warnings">{higgins.warnings.map((w, i) => <Body key={i} style={s.detail}>• {w}</Body>)}</View> : <Body style={s.detail}>No active warnings recorded.</Body>}
        {missingPerms.length ? <View testID="support-missing-perms" style={{ gap: 2 }}><Text style={s.label}>Missing permissions</Text>{missingPerms.map((p) => <Body key={p.id} style={s.detail}>• {p.title}: {p.why}</Body>)}</View> : null}
        {health.checkedAt ? <>
          <ResultRow id="device" label="Apollo protection" result={health.device} />
          <ResultRow id="backend" label="ApolloSG services" result={health.backend} />
          <ResultRow id="higgins" label="Higgins investigations" result={health.higgins} />
          {providerStatusLines(health.provider).map((line) => <Body key={line} style={s.detail} testID="support-higgins-provider">{line}</Body>)}
          <ResultRow id="report" label="Higgins reports" result={health.report} />
        </> : <Body style={s.detail}>No recent verified results. Run a check in the Check tab.</Body>}
        <Button testID="support-go-to-check" label="Ask Higgins" icon={<ArrowRight size={18} color={colors.onBrandPrimary} />} onPress={() => router.push("/(tabs)/ask")} />
      </Section>

      {/* 4. App Logs & Diagnostics */}
      <Section title="App Logs & Diagnostics" testID="support-logs-section" defaultOpen={false}>
        <Button testID="support-view-logs" variant="ghost" label={showLogs ? "Hide recent activity" : "View recent activity"} onPress={() => setShowLogs((v) => !v)} />
        {showLogs ? <View testID="support-logs-panel" style={{ gap: 4 }}>
          {recentLogLines(health, firstCheck.data?.concerns ?? [], verifiedEvidence ? `${new Date(verifiedEvidence.observedAt).toLocaleString()} · VERIFIED BLOCK · ${verifiedEvidence.destination?.domain ?? verifiedEvidence.destination?.ip ?? "destination"}` : null).map((line, i) => <Text key={i} style={s.logLine}>{line}</Text>)}
          <Body style={s.detail}>Only status, counts and dates are shown — no credentials, tokens or browsing history.</Body>
        </View> : null}
        <Button testID="support-copy-summary" variant="secondary" label="Copy Support Summary" icon={<Copy size={18} color={colors.brand} />} disabled={!ready} onPress={() => void copySummary()} />
        <Button testID="support-export-report" variant="secondary" label="Export Higgins Diagnostic Report" icon={<FileDown size={18} color={colors.brand} />} disabled={!ready} onPress={() => void exportReport()} />
      </Section>

      {/* 5. Contact Apollo Support */}
      <Section title="Contact ApolloSG Support" testID="support-contact-section">
        <Body>Prepare an email to ApolloSG support. Your email app opens with everything filled in — you review and send it yourself. Nothing is sent automatically and logs are never attached unless you attach them.</Body>
        {ref ? <View style={s.refBox} testID="support-reference-box"><Text style={s.detail}>Support reference</Text><Text style={s.refValue} testID="support-reference">{ref}</Text></View> : null}
        <View style={{ gap: 4 }}>
          <Text style={s.label}>Your email (optional — for a copy)</Text>
          <TextInput testID="support-user-email" value={userEmail} onChangeText={(t) => { setUserEmail(t); void storage.setItem(USER_EMAIL_KEY, t.trim()); }} placeholder="you@example.com" placeholderTextColor={colors.muted} autoCapitalize="none" keyboardType="email-address" autoCorrect={false} style={s.emailInput} />
          <Body style={s.detail}>Add your address and ApolloSG will CC you, so a copy lands in your inbox as well as your Sent folder.</Body>
        </View>
        <Button testID="support-email" label="Email ApolloSG Support" icon={<Mail size={18} color={colors.onBrandPrimary} />} disabled={!ready} onPress={() => void emailSupport()} />
        <Button testID="support-new-request" variant="ghost" label="Start a new support request" onPress={() => void newRequest()} />
        {history.data && history.data.length > 1 ? <View testID="support-inbox" style={{ gap: spacing.xs }}>
          <Text style={s.label}>Past requests</Text>
          {history.data.filter((h) => h.reference !== ref).slice(0, 6).map((h) => (
            <Pressable key={h.reference} testID={`support-inbox-${h.reference}`} accessibilityRole="button" onPress={() => void reopen(h.reference)} style={({ pressed }) => [s.inboxRow, { opacity: pressed ? 0.7 : 1 }]}>
              <View style={{ flex: 1 }}><Text style={s.inboxRef} numberOfLines={1}>{h.reference}</Text><Text style={s.detail}>{new Date(h.createdAt).toLocaleString()}</Text></View>
              <Text style={s.inboxReopen}>Reopen</Text>
            </Pressable>
          ))}
        </View> : null}
        <Body style={s.detail}>Reusing this screen keeps the same reference. Starting a new request creates a fresh one. Tap a past request to reopen it.</Body>
      </Section>

    </ScrollView>
  </View>;
}
