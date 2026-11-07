// Gate 8 — Account Guard dashboard + Check Account Alert. Paste or describe a login/MFA/reset/breach alert;
// Apollo distinguishes "something suspicious happened" from "your account is compromised". Never asks for passwords.
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as Crypto from "expo-crypto";
import { Image as ExpoImage } from "expo-image";
import ImageIcon from "lucide-react-native/icons/image";
import KeyRound from "lucide-react-native/icons/key-round";
import X from "lucide-react-native/icons/x";
import React, { useMemo, useState } from "react";
import { Linking, Pressable, Text, TextInput, View } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { markCheckDone } from "@/src/store/checkCompletion";
import { apiPost } from "@/src/api/client";
import { CheckResultScreen } from "@/src/components/CheckResultScreen";
import { InvestigationCheckScreen } from "@/src/components/InvestigationCheckScreen";
import { RecoveryFlow } from "@/src/components/RecoveryFlow";
import { ScreenshotPermissionSheet } from "@/src/components/ScreenshotPermissionSheet";
import { Body, Button, Card, Pill, SectionTitle, toneColor } from "@/src/components/ui";
import { ACCOUNT_PROVIDERS, ALERT_KINDS, analyseAccountAlert, inspectAccountEvidence, type AccountAnalysis, type AccountEvidence, type AccountProvider, type AlertKind } from "@/src/domain/accountAnalysis";
import { SCENT_WINDOW_MS } from "@/src/domain/threatScent";
import { type PatrolEvent, STATE_NAME } from "@/src/domain/types";
import { patrolSafeSummary } from "@/src/domain/investigation";
import { redactUserSecrets } from "@/src/domain/privacy";
import { screenImage } from "@/src/domain/imagePrivacy";
import { buildAccountCheckResult } from "@/src/domain/accountCheckResultAdapter";
import type { OfficialVerdict } from "@/src/domain/officialContacts";
import { emailsIn, lookupOfficialContacts } from "@/src/domain/officialContactsLookup";
import { extractPhoneCandidates } from "@/src/domain/phoneNumbers";
import { contextFromEvent, gateForCategory } from "@/src/domain/higginsHandoff";
import { type RecoveryKind, useApollo } from "@/src/store/ApolloContext";
import { CheckToolHeader } from "@/src/components/CheckToolHeader";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { goBackOrHome } from "@/src/utils/navigation";
import { InfoButton } from "@/src/components/InfoButton";
import { useScreenshotAccess } from "@/src/hooks/useScreenshotAccess";
import { getShareIntake } from "@/src/share/shareIntake";

type Remote = { urls: { url: string; host: string; verdict: "clean" | "malicious" | "unknown"; official: boolean }[] };
type Breach = { status: "not_configured" | "clear" | "found" | "unavailable"; breaches: { name: string; date: string; data: string[] }[]; password_exposed: boolean; detail: string; higgins: { headline: string; exact_response: string; next_action: string } };
const RISK_LABEL = { low: "Low takeover risk", elevated: "Elevated takeover risk", high: "High takeover risk", very_high: "Very high takeover risk" } as const;
const BANK_RE = /commbank|westpac|anz|nab|bank/i;

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  top: { paddingHorizontal: spacing.xl, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingBottom: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 22, color: c.onSurface },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: c.surfaceTertiary },
  content: { paddingHorizontal: spacing.xl, gap: spacing.lg },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: { paddingVertical: spacing.sm, paddingHorizontal: spacing.md, borderRadius: radius.pill, borderWidth: 1, borderColor: c.border, minHeight: 40, justifyContent: "center" },
  chipOn: { borderColor: c.brandPrimary, backgroundColor: c.restingTint },
  chipNo: { borderColor: c.barking, backgroundColor: c.barkingTint },
  chipText: { fontFamily: fonts.textMedium, fontSize: 14, color: c.onSurface },
  input: { minHeight: 48, backgroundColor: c.surfaceTertiary, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontFamily: fonts.text, fontSize: 15, color: c.onSurface },
  verdict: { fontFamily: fonts.displayBold, fontSize: 20, lineHeight: 26, color: c.onSurface },
  why: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface },
  label: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.onSurface },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.md },
  statTitle: { fontFamily: fonts.displayBold, fontSize: 20, color: c.onSurface },
  preview: { width: "100%", height: 180, borderRadius: radius.md, backgroundColor: c.surfaceTertiary },
}));

const UNREADABLE_SCREENSHOT = "Apollo couldn’t read the text in that screenshot. Try a clearer image, or type or paste what it says.";

export default function CheckAccount() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const params = useLocalSearchParams<{ text?: string; scent?: string; sharedIntakeId?: string }>();
  const shared = getShareIntake(params.sharedIntakeId);
  const { ready, setupDone, upsertEvent, resolveEvent, deviceId, adapterLabel, showToast, events } = useApollo();
  const [kind, setKind] = useState<AlertKind | null>(null);
  const [provider, setProvider] = useState<AccountProvider>("other");
  const [text, setText] = useState(shared?.text || shared?.webUrl || params.text || "");
  const [sender, setSender] = useState("");
  const [initiated, setInitiated] = useState<boolean | null>(null);
  const [answered, setAnswered] = useState({ initiated: false, repeated: false, location: false });
  const [flags, setFlags] = useState<{ repeated: boolean | null; unusualLocation: boolean | null }>({ repeated: null, unusualLocation: null });
  const [busy, setBusy] = useState(false);
  const [evidenceBusy, setEvidenceBusy] = useState(false);
  const [evidenceReviewed, setEvidenceReviewed] = useState(false);
  const [evidence, setEvidence] = useState<AccountEvidence | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [screenshotUri, setScreenshotUri] = useState<string | null>(null);
  const [result, setResult] = useState<{ submissionId: string; a: AccountAnalysis; event: PatrolEvent | null; remote: Remote | null; linked: PatrolEvent | null; official: OfficialVerdict[] | null } | null>(null);
  const [identifier, setIdentifier] = useState("");
  const [breach, setBreach] = useState<Breach | null>(null);
  const [showSender, setShowSender] = useState(false);

  const openAccount = events.filter((e) => e.category === "account" && e.status === "active" && e.state !== "resting");
  const recentLinked = useMemo(() => { const now = Date.now(); return events.filter((e) => e.state !== "resting" && ["message", "email", "website", "link", "call", "app", "connection"].includes(e.category) && now - Date.parse(e.occurred_at) <= SCENT_WINDOW_MS); }, [events]);
  const dashTone = openAccount.some((e) => e.state === "barking") ? "barking" : openAccount.length ? "growling" : "resting";
  const inspectEvidence = (body = text, visibleSender = sender) => {
    const inspected = inspectAccountEvidence(redactUserSecrets(body), visibleSender);
    setEvidence(inspected); setKind(inspected.kind); setProvider(inspected.provider); setEvidenceReviewed(true); setEvidenceError(null);
    setInitiated(null); setFlags({ repeated: null, unusualLocation: null }); setAnswered({ initiated: false, repeated: false, location: false });
  };
  const launchScreenshotPicker = async () => {
    setEvidenceError(null);
    try {
      const picked = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], allowsEditing: false, quality: 0.9 });
      if (picked.canceled || !picked.assets[0]) return;
      const asset = picked.assets[0]; setScreenshotUri(asset.uri); setEvidenceBusy(true);
      // The screenshot's text is read on this device (credentials removed); the image itself is never sent.
      const screening = await screenImage(asset.uri, "message_screenshot");
      const read = screening.extractedText.trim();
      if (!read) throw new Error(UNREADABLE_SCREENSHOT);
      const from = screening.detectedSender ?? "";
      setText(read); setSender(from); inspectEvidence(read, from);
    } catch (error) { setEvidenceError(error instanceof Error ? error.message : UNREADABLE_SCREENSHOT); }
    finally { setEvidenceBusy(false); }
  };
  const photoAccess = useScreenshotAccess(launchScreenshotPicker);
  const needsInitiated = !!kind && ["mfa_prompt", "login_alert", "password_reset", "password_changed", "recovery_changed"].includes(kind);
  const followUp = !evidenceReviewed ? null : needsInitiated && !answered.initiated ? "initiated" : kind === "mfa_prompt" && !answered.repeated ? "repeated" : kind === "login_alert" && !answered.location ? "location" : null;

  const run = async () => {
    if (!kind || !evidenceReviewed || followUp) return;
    const selectedKind = kind;
    setBusy(true);
    try {
    void markCheckDone("account");
      const safeText = redactUserSecrets(text); if (safeText !== text) setText(safeText);
      const prov = ACCOUNT_PROVIDERS.find((p) => p.id === provider)!;
      const linked = recentLinked.find((e) => e.claimed_brand && ((prov.brand && e.claimed_brand.toLowerCase().includes(prov.brand.toLowerCase())) || (provider === "bank" && BANK_RE.test(e.claimed_brand)))) ?? (initiated === false ? recentLinked[0] ?? null : null);
      const input = { kind: selectedKind, provider, text: safeText.trim() || undefined, sender: sender.trim() || undefined, userInitiated: initiated,
        repeated: flags.repeated === true ? true : undefined, unusualLocation: flags.unusualLocation === true ? true : undefined,
        recentScentCategories: (linked ? recentLinked : []).map((e) => e.category), recentScentBrand: linked?.claimed_brand ?? null };
      let a = analyseAccountAlert(input);
      // The Official Organisation Directory's verdict on the alert's links, numbers and addresses; never changes the outcome.
      const material = `${sender.trim()}\n${safeText}`;
      const officialLookup = lookupOfficialContacts({
        text: material, claimedOrg: a.claimedBrand ?? prov.brand, sites: a.urls,
        phones: extractPhoneCandidates(material), emails: emailsIn(material),
      });
      let remote: Remote | null = null;
      try {
        remote = await apiPost<Remote>("/account/analyse", "account_check", { device_id: deviceId ?? "local-device", kind: selectedKind, provider, sender: sender.trim(), text: safeText.trim(), urls: a.urls, local_state: a.state, scenario: a.scenario, second_opinion: false });
        const bad = remote.urls.find((u) => u.verdict === "malicious");
        if (bad && a.state !== "barking") a = { ...a, state: "barking", why: [...a.why, `The link (${bad.host}) is confirmed dangerous by Apollo's threat intelligence.`], handoff: "web" };
      } catch { /* offline: on-device engine is authoritative */ }
      let event: PatrolEvent | null = null;
      if (a.state !== "resting") {
        event = await upsertEvent({ event_id: Math.random().toString(36).slice(2) + Date.now().toString(36), origin: "user", device_id: deviceId ?? "local", category: "account", state: a.state, status: "active", headline: `Account: ${a.title}${a.providerLabel !== "Other / not sure" ? ` — ${a.providerLabel}` : ""}`, what_happened: patrolSafeSummary(a.verdict), why: a.why, what_to_do: a.recommendation, indicator_host: a.suspiciousUrls[0] ? a.suspiciousUrls[0].replace(/^https?:\/\//i, "").split("/")[0] : null, indicator_digest: null, local_indicator: null, verified_block: false, adapter_label: adapterLabel, occurred_at: new Date().toISOString(), resolved_at: null, trust_allowed: false, claimed_brand: a.claimedBrand, scenario: a.scenario, scent_id: params.scent || linked?.scent_id || linked?.event_id || null }, { kind: "account", fields: [{ label: "Provider", value: prov.label }, ...(sender.trim() ? [{ label: "From", value: sender }] : [])], text: text.trim() ? text : null });
        if (event.state !== a.state) a = { ...a, state: event.state, why: event.why };
      }
      setResult({ submissionId: event?.event_id ?? Crypto.randomUUID(), a, event, remote, linked, official: await officialLookup });
    } finally { setBusy(false); }
  };
  const checkBreach = async () => {
    try { setBreach(await apiPost<Breach>("/account/breach", "breach_check", { device_id: deviceId ?? "local-device", identifier: identifier.trim() })); setIdentifier(""); }
    catch (e) { showToast(e instanceof Error ? e.message : "Couldn't reach the breach service.", "neutral"); }
  };

  if (ready && !setupDone) return <Redirect href="/" />;
  const a = result?.a;
  const recovery = (a?.recoveryKinds.length ? a.recoveryKinds : ["password", "code", "mfa_approved", "locked_out"]) as RecoveryKind[];

  // UNIVERSAL CHECK RESULT — when the account check has produced an outcome
  if (result && a) {
    const model = { ...buildAccountCheckResult({ analysis: a, event: result.event, provider, kind: kind ?? "other", initiated }), official: result.official };
    const askPrompt = `About the account alert I just checked (${model.subject}). ${model.headline} Can you walk me through what Apollo found and what I should do?`;
    const acctActions: { label: string; onPress: () => void; testID: string; variant?: "primary" | "secondary" | "ghost" }[] = [];
    acctActions.push({ testID: "account-open-official", variant: "secondary", label: `Open ${a.providerLabel} safely`, onPress: () => { void Linking.openURL(ACCOUNT_PROVIDERS.find((p) => p.id === provider)?.official[0] ? `https://${ACCOUNT_PROVIDERS.find((p) => p.id === provider)!.official[0]}` : "https://www.google.com"); } });
    if (a.suspiciousUrls.length) {
      a.suspiciousUrls.forEach((u, i) => {
        acctActions.push({ testID: `account-check-link-${i}`, variant: "ghost", label: `Check link: ${u.length > 35 ? u.slice(0, 35) + "\u2026" : u}`, onPress: () => router.push({ pathname: "/check", params: { url: u.startsWith("http") ? u : `https://${u}`, source: "account" } }) });
      });
    }
    if (result.event) {
      acctActions.push({ testID: "account-mark-safe", variant: "ghost", label: "Mark as handled", onPress: () => { void resolveEvent(result.event!); showToast("Marked as handled.", "neutral"); goBackOrHome(router); } });
    }
    acctActions.push({ testID: "account-again", variant: "ghost", label: "Check another alert", onPress: () => { setResult(null); setKind("other"); setProvider("other"); setInitiated(null); } });

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
            actions={acctActions}
          />
        ) : (
          <CheckResultScreen result={model} actions={acctActions} />
        )}
        {a.stayWithMe && result.event ? (
          <RecoveryFlow event={result.event} kinds={recovery} testID="account-recovery" />
        ) : null}
        <ScreenshotPermissionSheet prefix="account" visible={!!photoAccess.permission} canAskAgain={photoAccess.permission?.canAskAgain ?? true}
          checking={photoAccess.checking} onContinue={() => void photoAccess.continueAccess()} onClose={photoAccess.close} />
      </>
    );
  }

  return (
    <View style={s.root}>
      <View style={[s.top, { paddingTop: insets.top + spacing.md }]}>
        <CheckToolHeader
          title="Check an account alert"
          info={{ title: "About account alerts", body: ["Received an unexpected security alert from a service? Paste or describe the alert and Apollo will investigate whether it's genuine or a phishing attempt. TC Hawkeye investigates it first, and Magnum DI looks deeper only if that could change the answer.", "Apollo checks the claimed sender, alert language, embedded links and known phishing patterns. This does not access your accounts — it analyses the alert itself."] }}
          testID="account"
        />
      </View>
      <KeyboardAwareScrollView contentContainerStyle={[s.content, { paddingBottom: insets.bottom + spacing.xl }]} bottomOffset={24} testID="account-scroll">
        <Card testID="account-dashboard" style={{ gap: spacing.sm, borderColor: toneColor(colors, dashTone) }}>
          <View style={s.row}><View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}><KeyRound size={20} color={toneColor(colors, dashTone)} /><Text style={s.statTitle} testID="account-dashboard-title">{openAccount.length ? `${openAccount.length} account${openAccount.length > 1 ? "s" : ""} need${openAccount.length > 1 ? "" : "s"} attention` : "All good"}</Text></View><Pill tone={dashTone} label={STATE_NAME[dashTone]} /></View>
          <Body>{openAccount.length ? "Review the items below through the official app or website — never through the alert itself." : "No unresolved account-security issues."}</Body>
          {openAccount.slice(0, 3).map((e) => (
            <View key={e.event_id} style={s.row} testID={`account-open-${e.event_id}`}>
              <View style={{ flex: 1 }}><Text style={s.label} numberOfLines={1}>{e.headline.replace(/^Account: /, "")}</Text><Body>{e.what_to_do}</Body></View>
              <Button testID={`account-review-${e.event_id}`} variant="secondary" label="Review" onPress={() => router.push({ pathname: "/patrol/[id]", params: { id: e.event_id } })} />
            </View>
          ))}
        </Card>

        {!result ? (
          <>
            <SectionTitle>Start with what you received</SectionTitle>
            <Body>Choose a screenshot, paste the alert, or describe it briefly. Apollo inspects the evidence before asking anything else.</Body>
            <Button testID="account-screenshot" label={evidenceBusy ? "Reading screenshot…" : "Choose alert screenshot"} icon={<ImageIcon size={18} color={colors.onBrandPrimary} />} onPress={() => void photoAccess.start()} disabled={evidenceBusy || busy} />
            {screenshotUri ? <ExpoImage testID="account-screenshot-preview" source={{ uri: screenshotUri }} style={s.preview} contentFit="contain" accessibilityLabel="Account alert screenshot selected for investigation" /> : null}
            <TextInput testID="account-text" style={[s.input, { minHeight: 96 }]} value={text} onChangeText={(value) => { setText(value); setEvidenceReviewed(false); }} placeholder="Paste the alert or describe it briefly" placeholderTextColor={colors.muted} multiline textAlignVertical="top" autoCapitalize="none" autoCorrect={false} />
            <Pressable testID="account-more-details" accessibilityRole="button" onPress={() => setShowSender(!showSender)} style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs, paddingVertical: spacing.xs }}>
              <Text style={{ fontFamily: fonts.textSemibold, fontSize: 14, color: colors.brand }}>{showSender ? "Hide sender details" : "Add sender details"}</Text>
            </Pressable>
            {showSender ? (
              <TextInput testID="account-sender" style={s.input} value={sender} onChangeText={(value) => { setSender(value); setEvidenceReviewed(false); }} placeholder="Visible sender, if shown" placeholderTextColor={colors.muted} autoCapitalize="none" autoCorrect={false} />
            ) : null}
            {evidenceError ? <Card testID="account-evidence-error" style={{ gap: spacing.sm }}><Body>{evidenceError}</Body><Button testID="account-evidence-retry" variant="secondary" label="Try screenshot again" onPress={() => void photoAccess.start()} /></Card> : null}
            <Button testID="account-inspect" variant="secondary" label="Inspect submitted evidence" onPress={() => inspectEvidence()} disabled={evidenceBusy || !(text.trim() || sender.trim())} />
            <Button testID="account-no-evidence" variant="ghost" label="I don't have the alert or screenshot" onPress={() => { setEvidence({ kind: "other", provider: "other", claimedService: null, visibleSender: null, urls: [], requestedActions: [] }); setKind("other"); setProvider("other"); setEvidenceReviewed(true); }} />
            {evidenceReviewed && evidence ? <Card testID="account-evidence" style={{ gap: spacing.xs }}><SectionTitle>Facts found — correct anything below</SectionTitle><Body testID="account-evidence-service">Claimed service: {evidence.claimedService ?? "unknown"}</Body><Body testID="account-evidence-kind">Alert type suggested by wording: {ALERT_KINDS.find((item) => item.id === evidence.kind)?.label ?? "unknown"}</Body><Body testID="account-evidence-sender">Visible sender: {evidence.visibleSender ?? "not supplied"}</Body><Body testID="account-evidence-links">Visible links: {evidence.urls.length ? evidence.urls.join(", ") : "none found"}</Body><Body testID="account-evidence-actions">Requested action: {evidence.requestedActions.join("; ") || "none identified"}</Body><Body>These are claims and visible details, not proof that the sender, service or alert is genuine.</Body><Text style={s.label}>Alert type</Text><View style={s.chips}>{ALERT_KINDS.map((o) => <Pressable key={o.id} testID={`account-kind-${o.id}`} accessibilityRole="radio" accessibilityState={{ checked: kind === o.id }} onPress={() => { setKind(o.id); setInitiated(null); setFlags({ repeated: null, unusualLocation: null }); setAnswered({ initiated: false, repeated: false, location: false }); }} style={[s.chip, kind === o.id && s.chipOn]}><Text style={s.chipText}>{o.label}</Text></Pressable>)}</View><Text style={s.label}>Claimed service</Text><View style={s.chips}>{ACCOUNT_PROVIDERS.map((o) => <Pressable key={o.id} testID={`account-provider-${o.id}`} accessibilityRole="radio" accessibilityState={{ checked: provider === o.id }} onPress={() => setProvider(o.id)} style={[s.chip, provider === o.id && s.chipOn]}><Text style={s.chipText}>{o.label}</Text></Pressable>)}</View></Card> : null}
            {followUp === "initiated" ? <Card testID="account-followup-initiated" style={{ gap: spacing.sm }}><SectionTitle>One question that changes the advice</SectionTitle><Body>Did you request or make this change?</Body><View style={s.chips}>{([["yes", "Yes", true], ["no", "No", false], ["unsure", "Not sure", null]] as const).map(([id, label, value]) => <Pressable key={id} testID={`account-initiated-${id}`} accessibilityRole="button" onPress={() => { setInitiated(value); setAnswered((current) => ({ ...current, initiated: true })); }} style={[s.chip, answered.initiated && initiated === value && (value === false ? s.chipNo : s.chipOn)]}><Text style={s.chipText}>{label}</Text></Pressable>)}</View></Card> : null}
            {followUp === "repeated" ? <Card testID="account-followup-repeated" style={{ gap: spacing.sm }}><SectionTitle>One more question</SectionTitle><Body>Have several approval prompts arrived in a row?</Body><View style={s.chips}>{([["yes", "Yes", true], ["no", "No", false], ["unsure", "Not sure", null]] as const).map(([id, label, value]) => <Pressable key={id} testID={`account-repeated-${id}`} onPress={() => { setFlags((current) => ({ ...current, repeated: value })); setAnswered((current) => ({ ...current, repeated: true })); }} style={[s.chip, answered.repeated && flags.repeated === value && s.chipOn]}><Text style={s.chipText}>{label}</Text></Pressable>)}</View></Card> : null}
            {followUp === "location" ? <Card testID="account-followup-location" style={{ gap: spacing.sm }}><SectionTitle>One more question</SectionTitle><Body>Does the shown device or location make sense for your login?</Body><View style={s.chips}>{([["yes", "Yes", false], ["no", "No", true], ["unsure", "Not sure", null]] as const).map(([id, label, value]) => <Pressable key={id} testID={`account-location-${id}`} onPress={() => { setFlags((current) => ({ ...current, unusualLocation: value })); setAnswered((current) => ({ ...current, location: true })); }} style={[s.chip, answered.location && flags.unusualLocation === value && s.chipOn]}><Text style={s.chipText}>{label}</Text></Pressable>)}</View></Card> : null}
            {recentLinked.length ? <Card style={{ gap: spacing.xs, borderColor: colors.growling }} testID="account-scent-notice"><Text style={s.label}>Threat Scent</Text><Body>Apollo saw {recentLinked.length} suspicious event{recentLinked.length > 1 ? "s" : ""} in the last 30 minutes{recentLinked[0].claimed_brand ? ` (about ${recentLinked[0].claimed_brand})` : ""}. An account alert now will be assessed as part of that sequence.</Body></Card> : null}
            <Button testID="account-run" label={busy ? "Checking…" : "Assess this alert"} onPress={() => void run()} disabled={busy || !evidenceReviewed || !kind || !!followUp} />
          </>
        ) : null}

        <Card style={{ gap: spacing.sm }} testID="account-breach">
          <SectionTitle>Has this email appeared in a breach?</SectionTitle>
          <Body testID="account-breach-policy">Submitting an email address authorises one breach lookup. ApolloSG does not keep the identifier; the breach provider&apos;s configured retention policy still applies.</Body>
          <TextInput testID="account-breach-id" style={s.input} value={identifier} onChangeText={setIdentifier} placeholder="you@example.com" placeholderTextColor={colors.muted} autoCapitalize="none" autoCorrect={false} keyboardType="email-address" />
          <Button testID="account-breach-run" variant="secondary" label="Check breach exposure" onPress={() => void checkBreach()} disabled={!identifier.trim()} />
          {breach ? (
            <View style={{ gap: spacing.xs }} testID="account-breach-result">
              <Pill tone={breach.status === "found" ? (breach.password_exposed ? "growling" : "ears_up") : breach.status === "clear" ? "resting" : "unknown"} label={breach.status === "found" ? (breach.password_exposed ? "Passwords exposed" : "Appears in a breach") : breach.status === "clear" ? "Not found" : breach.status === "not_configured" ? "Not connected" : "Unavailable"} testID="account-breach-status" />
              <Body testID="account-breach-detail">{breach.detail}</Body>
              <Text style={s.label} testID="account-breach-higgins-title">{breach.higgins.headline}</Text>
              <Body testID="account-breach-higgins-response">{breach.higgins.exact_response}</Body>
              <Body testID="account-breach-next-action">Next: {breach.higgins.next_action}</Body>
              <Pressable testID="account-breach-attribution" accessibilityRole="link" onPress={() => void Linking.openURL("https://haveibeenpwned.com/")}>
                <Text style={s.label}>Data source: Have I Been Pwned</Text>
              </Pressable>
              {breach.breaches.slice(0, 5).map((b) => <Body key={b.name}>• {b.name} ({b.date}) — {b.data.join(", ")}</Body>)}
              {breach.status === "found" ? <Body>{breach.password_exposed ? "Change that password everywhere you used it, and turn on two-factor authentication." : "Expect targeted phishing. Turn on two-factor authentication and don't reuse passwords."}</Body> : null}
            </View>
          ) : null}
        </Card>
        <Card style={{ gap: spacing.xs }} testID="account-cannot-see">
          <SectionTitle>What ApolloSG can and can&apos;t see</SectionTitle>
          <Body>Apollo assesses what you submit. Ongoing notification or mailbox access stays off until you explicitly enable it. ApolloSG never asks for or stores your password.</Body>
        </Card>
      </KeyboardAwareScrollView>
      
    </View>
  );
}
