// Gate 4 — Check This Call. Designed for use under pressure during a live call: big buttons, short
// answers, "Hang Up & Verify" first. No audio is recorded; analysis is from what the user selects
// (plus an optional typed description they provide).
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import React, { useEffect, useState } from "react";
import { Pressable, Switch, Text, TextInput, View } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { CheckResultScreen } from "@/src/components/CheckResultScreen";
import { InvestigationCheckScreen } from "@/src/components/InvestigationCheckScreen";
import { RecoveryFlow } from "@/src/components/RecoveryFlow";
import { Sheet } from "@/src/components/Sheet";
import { PhonePickerSheet } from "@/src/components/PhonePickerSheet";
import { ScreenedCallsList } from "@/src/components/ScreenedCallsList";
import { dlog } from "@/src/utils/dlog";
import { PhonePickers } from "@/src/security/phonePickers";
import { ScreenedCalls } from "@/src/security/screenedCalls";
import { getTrustedCallers, normalizeNumber, trustCaller, untrustCaller } from "@/src/domain/trustedCallers";
import { Body, Button, Card, SectionTitle } from "@/src/components/ui";
import { buildCallCheckResult } from "@/src/domain/callCheckResultAdapter";
import { CALL_ASKS, CALL_CLAIMS, describeCall, type CallAnalysis, type CallAsk, type CallClaim } from "@/src/domain/callAnalysis";
import { contextFromEvent, gateForCategory, issueContext } from "@/src/domain/higginsHandoff";
import { type PatrolEvent } from "@/src/domain/types";
import type { EvidenceProfile } from "@/src/domain/triage/evidenceProfile";
import { useApollo } from "@/src/store/ApolloContext";
import { CheckHistoryCard } from "@/src/components/CheckHistoryCard";
import { SameNumberReminder } from "@/src/components/SameNumberReminder";
import { earlierCheck, type EarlierCheck } from "@/src/domain/sameNumber";
import { getCheckHistory, numberKeyOf, recordCheck } from "@/src/store/checkHistoryStore";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { goBackOrHome } from "@/src/utils/navigation";
import { InfoButton } from "@/src/components/InfoButton";
import { CloseButton } from "@/src/components/CloseButton";
import type { OfficialVerdict } from "@/src/domain/officialContacts";
import { PhoneIdentityCard } from "@/src/components/PhoneIdentityCard";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  top: { paddingHorizontal: spacing.xl, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingBottom: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 22, color: c.onSurface },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: c.surfaceTertiary },
  subtitle: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurfaceSecondary, marginBottom: spacing.xs },
  autoLabel: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.onSurface, flex: 1 },
  content: { paddingHorizontal: spacing.xl, gap: spacing.lg },
  q: { fontFamily: fonts.displayBold, fontSize: 18, color: c.onSurface },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  big: { minHeight: 56, minWidth: "47%", flexGrow: 1, paddingHorizontal: spacing.md, justifyContent: "center", borderRadius: radius.md, borderWidth: 1, borderColor: c.border, backgroundColor: c.surfaceTertiary },
  bigOn: { borderColor: c.brandPrimary, backgroundColor: c.restingTint },
  bigText: { fontFamily: fonts.textSemibold, fontSize: 16, color: c.onSurface },
  chip: { paddingVertical: spacing.sm, paddingHorizontal: spacing.md, borderRadius: radius.pill, borderWidth: 1, borderColor: c.border },
  chipOn: { borderColor: c.brandPrimary, backgroundColor: c.restingTint },
  chipText: { fontFamily: fonts.textMedium, fontSize: 14, color: c.onSurface },
  input: { minHeight: 48, backgroundColor: c.surfaceTertiary, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontFamily: fonts.text, fontSize: 15, color: c.onSurface },
  verdict: { fontFamily: fonts.displayBold, fontSize: 24, lineHeight: 30, color: c.onSurface },
  why: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface },
  small: { fontFamily: fonts.text, fontSize: 12, color: c.muted },
}));

export default function CheckCall() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { ready, setupDone, checkCall, resolveEvent, showToast, storage, events } = useApollo();
  const [asks, setAsks] = useState<CallAsk[]>([]);
  const [claim, setClaim] = useState<CallClaim>("unknown");
  const params = useLocalSearchParams<{ number?: string }>();
  const [number, setNumber] = useState(params.number ? String(params.number) : "");
  const [transcript, setTranscript] = useState("");
  const [more, setMore] = useState(!!params.number);
  const [result, setResult] = useState<{ analysis: CallAnalysis; event: PatrolEvent | null; profile?: EvidenceProfile | null; official?: OfficialVerdict[] | null } | null>(null);
  // Stable submission identity — generated once when the check runs, never during render.
  const [submissionId, setSubmissionId] = useState<string | null>(null);
  const [verify, setVerify] = useState(false);
  const [callerPickerOpen, setCallerPickerOpen] = useState(false);
  const canPickPhone = PhonePickers.isSupported("call_log");
  // Permission-free alternative: numbers Android handed to Apollo's call screening.
  const canPickScreened = !canPickPhone && ScreenedCalls.isSupported();
  const [screenedOpen, setScreenedOpen] = useState(false);
  const [autoCheck, setAutoCheck] = useState(false);
  const [trustedList, setTrustedList] = useState<string[]>([]);
  const reloadTrusted = React.useCallback(() => { void getTrustedCallers().then(setTrustedList); }, []);
  useEffect(() => { void storage.getItem("apollo.call.auto_check", null).then((v: string | null) => setAutoCheck(v === "true")); reloadTrusted(); }, [storage, reloadTrusted]);

  const toggle = (id: CallAsk) => setAsks((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : id === "nothing" ? ["nothing"] : [...cur.filter((x) => x !== "nothing"), id]));
  const [historyKey, setHistoryKey] = useState(0);
  // Same Number Reminder: the earlier result for this number from the last 30 days, read before today's check.
  const [earlier, setEarlier] = useState<EarlierCheck | null>(null);
  const run = async () => {
    const checked = number.trim();
    setEarlier(null);
    // What this device held before today's check (today's check must not count as earlier).
    const priorEvents = events;
    const priorHistory = getCheckHistory("call").catch(() => []);
    const r = await checkCall({ asks, claim, number: checked || undefined, transcript: transcript.trim() || undefined });
    const sid = r.event?.event_id ?? `call-${Date.now()}`;
    dlog('CallGuard', 'check complete', { submissionId: sid, eventId: r.event?.event_id, caseId: r.event?.investigation_case_id, state: r.analysis.state });
    const numberKey = checked ? await numberKeyOf(checked).catch(() => null) : null;
    setEarlier(checked ? earlierCheck({ number: checked, key: numberKey, events: priorEvents, history: await priorHistory, now: Date.now() }) : null);
    setSubmissionId(sid);
    setResult(r);
    void recordCheck("call", { at: new Date().toISOString(), state: r.analysis.state, summary: r.analysis.title, ...(numberKey ? { numberKey } : {}) });
    setHistoryKey((k) => k + 1);
  };
  const reset = () => { setResult(null); setSubmissionId(null); setAsks([]); setEarlier(null); };

  if (ready && !setupDone) return <Redirect href="/" />;
  const a = result?.analysis;

  // UNIVERSAL CHECK RESULT — when the manual check has produced an outcome, the entire screen
  // becomes the shared Check Result. ONE Higgins paragraph, ONE items list, ONE actions row.
  if (result && a && submissionId) {
    dlog('CallGuard', 'render', { submissionId, eventId: result.event?.event_id, caseId: result.event?.investigation_case_id });
    const model = { ...buildCallCheckResult({ analysis: a, event: result.event, number, transcript, official: result.official }), evidenceProfile: result.event?.evidence_profile ?? result.profile ?? null };
    const askPrompt = `About the device call I just checked. ${model.headline} Can you walk me through what Apollo found and what I should do?`;
    const actions: { label: string; onPress: () => void; testID: string; variant?: "primary" | "secondary" | "ghost" }[] = [];
    if (a.state === "barking" || a.state === "growling") {
      actions.push({ testID: "call-hangup-verify", variant: "secondary", label: "Show me how to verify safely", onPress: () => setVerify(true) });
    } else {
      actions.push({ testID: "call-verify", variant: "ghost", label: "Show me how to check the caller", onPress: () => setVerify(true) });
    }
    if (number.trim()) {
      if (trustedList.includes(normalizeNumber(number))) {
        actions.push({ testID: "call-untrust-result", variant: "ghost", label: "Trusted — tap to remove", onPress: () => { void untrustCaller(number).then(reloadTrusted); showToast("Removed from trusted numbers.", "neutral"); } });
      } else {
        actions.push({ testID: "call-trust-result", variant: "ghost", label: "Trust this number", onPress: () => { void trustCaller(number).then(reloadTrusted); showToast("Added to trusted numbers — Apollo will stay quiet for it and won't auto-check it.", "resting"); } });
      }
    }
    // Call Screening stays in its own flow — no navigation to App Check or Account Check.
    // The user can open those manually from Check It if needed.
    if (result.event) {
      actions.push({ testID: "call-mark-safe", variant: "ghost", label: "Mark as handled", onPress: () => { void resolveEvent(result.event!); showToast("Marked as handled. This does not verify the caller.", "neutral"); goBackOrHome(router); } });
    }
    actions.push({ testID: "call-again", variant: "ghost", label: "Check another number", onPress: reset });

    const reminder = earlier ? <SameNumberReminder earlier={earlier} testID="call-earlier" /> : null;
    const identityNotice = (
      <>
        {reminder}
        {number.trim() ? <PhoneIdentityCard number={number} testID="call-identity" /> : null}
      </>
    );
    return (
      <>
        {result.event ? (
          <InvestigationCheckScreen
            result={model}
            investigationContext={issueContext({
              ...contextFromEvent(result.event, gateForCategory(result.event.category)),
              original_evidence: [{ kind: "text", value: describeCall({ asks, claim, number, transcript }), label: "Call details" }],
            })}
            investigationQuestion={askPrompt}
            submissionId={submissionId}
            eventId={result.event.event_id}
            caseId={result.event.investigation_case_id ?? null}
            actions={actions}
            notice={identityNotice}
          />
        ) : (
          <CheckResultScreen result={model} actions={actions} notice={identityNotice} />
        )}
        {result.event ? (
          <RecoveryFlow event={result.event} kinds={["password", "code", "money", "card", "app", "remote", "called", "info"]} testID="call-recovery" />
        ) : null}
        <Sheet visible={verify} onClose={() => setVerify(false)} title="Verify the caller independently" testID="verify-caller-sheet">
          <Body testID="verify-caller-text">{a.verifyCaller}</Body>
          <Body>Never verify using a number, link or website the caller gave you.</Body>
          <Button testID="verify-caller-close" variant="ghost" label="Got it" onPress={() => setVerify(false)} />
        </Sheet>
        {canPickPhone ? <PhonePickerSheet visible={callerPickerOpen} mode="calls" onClose={() => { setCallerPickerOpen(false); reloadTrusted(); }} onPickCall={(c) => { setNumber(c.number); setMore(true); }} /> : null}
      </>
    );
  }

  return (
    <View style={s.root}>
      <View style={[s.top, { paddingTop: insets.top + spacing.md }]}>
        <Text style={s.title}>Call screening</Text>
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
          <CloseButton testID="call-close" onPress={() => goBackOrHome(router)} />
          <InfoButton info={{ title: "About call screening", body: ["This screen is designed for use during a live call. Big buttons and short answers help you make decisions under pressure.", "Tell ApolloSG what the caller is asking you to do and it will assess the risk. No audio is recorded — Apollo analyses only what you select or type."] }} testID="call-info" />
        </View>
      </View>
      <KeyboardAwareScrollView contentContainerStyle={[s.content, { paddingBottom: insets.bottom + spacing.xl }]} bottomOffset={24} testID="call-scroll">
        <Text style={s.subtitle}>Assess a live call — big buttons, short answers, no audio recorded.</Text>
        <Card style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm }} testID="call-guard-auto">
          <Text style={s.autoLabel}>Auto-check incoming numbers</Text>
          <Switch testID="call-auto-switch" value={autoCheck} onValueChange={(value) => { setAutoCheck(value); void storage.setItem("apollo.call.auto_check", value ? "true" : "false"); showToast(value ? "Call Gate on — Apollo will check incoming numbers." : "Call Gate off — you can still check numbers manually.", value ? "resting" : "neutral"); }} trackColor={{ true: colors.resting, false: colors.borderStrong }} thumbColor={colors.onSurface} />
        </Card>
        {trustedList.length ? (
          <Card style={{ gap: spacing.sm }} testID="call-trusted-list">
            <SectionTitle>Trusted numbers</SectionTitle>
            <Body>Apollo stays quiet for these numbers and won&apos;t auto-check them.</Body>
            {trustedList.map((num) => (
              <View key={num} style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                <Text style={[s.why, { flex: 1 }]} testID={`call-trusted-${num}`}>{num}</Text>
                <Button testID={`call-untrust-${num}`} variant="ghost" label="Remove" onPress={() => { void untrustCaller(num).then(reloadTrusted); }} />
              </View>
            ))}
          </Card>
        ) : null}
        {canPickPhone || canPickScreened ? (
          <Card style={{ gap: spacing.sm }} testID="call-number-picker">
            <SectionTitle>Who called?</SectionTitle>
            {number.trim() ? <Text style={s.chipText} testID="call-picked-number">Checking: {number}</Text> : <Body>{canPickPhone ? "Pick the caller from your recent calls, or add the number lower down." : "Pick the caller from the calls Apollo screened, or add the number lower down."}</Body>}
            {canPickPhone
              ? <Button testID="call-pick-recent" variant="secondary" label={number.trim() ? "Pick a different caller" : "Pick a recent caller"} onPress={() => setCallerPickerOpen(true)} />
              : <Button testID="call-pick-screened" variant="secondary" label={number.trim() ? "Pick a different caller" : "Pick from calls Apollo screened"} onPress={() => setScreenedOpen(true)} />}
          </Card>
        ) : null}
        <Text style={s.q}>What are they asking you to do?</Text>
        <View style={s.grid}>
          {CALL_ASKS.map((o) => (
            <Pressable key={o.id} testID={`call-ask-${o.id}`} accessibilityRole="button" accessibilityState={{ selected: asks.includes(o.id) }} onPress={() => toggle(o.id)} style={[s.big, asks.includes(o.id) && s.bigOn]}>
              <Text style={s.bigText}>{o.label}</Text>
            </Pressable>
          ))}
        </View>
        <Text style={s.q}>Who do they say they are?</Text>
        <View style={s.grid}>
          {CALL_CLAIMS.map((o) => (
            <Pressable key={o.id} testID={`call-claim-${o.id}`} accessibilityRole="button" accessibilityState={{ selected: claim === o.id }} onPress={() => setClaim(o.id)} style={[s.chip, claim === o.id && s.chipOn]}>
              <Text style={s.chipText}>{o.label}</Text>
            </Pressable>
          ))}
        </View>
        <Button testID="call-check" label="Check with ApolloSG" onPress={() => void run()} disabled={asks.length === 0 && !number.trim()} />
        <Button testID="call-more-toggle" variant="ghost" label={more ? "Hide extra details" : "Add caller number or description (optional)"} onPress={() => setMore((m) => !m)} />
        {more ? (
          <>
            <TextInput testID="call-number" style={s.input} value={number} onChangeText={setNumber} placeholder="Caller number (optional)" placeholderTextColor={colors.muted} keyboardType="phone-pad" />
            <TextInput testID="call-transcript" style={[s.input, { minHeight: 100, textAlignVertical: "top" }]} value={transcript} onChangeText={setTranscript} placeholder="Type what the caller said (optional)" placeholderTextColor={colors.muted} multiline />
          </>
        ) : null}
        <Text style={s.small}>Apollo does not listen to or record calls. It works from what you select here, any text you paste, and your recent ApolloSG events.</Text>
        <Button testID="call-check-number" variant="ghost" label="Just want to check a number? Use Check a Number" onPress={() => router.push("/call-guard")} />
        <CheckHistoryCard gate="call" refreshKey={historyKey} testID="call-history" />
      </KeyboardAwareScrollView>
      {canPickPhone ? <PhonePickerSheet visible={callerPickerOpen} mode="calls" onClose={() => { setCallerPickerOpen(false); reloadTrusted(); }} onPickCall={(c) => { setNumber(c.number); setMore(true); }} /> : null}
      {canPickScreened ? (
        <Sheet visible={screenedOpen} onClose={() => setScreenedOpen(false)} title="Calls Apollo screened" testID="call-screened-sheet">
          <ScreenedCallsList testID="call-screened" actionLabel="Use" onSelect={(n) => { setNumber(n); setMore(true); setScreenedOpen(false); }} />
          <Button testID="call-screened-close" variant="ghost" label="Close" onPress={() => setScreenedOpen(false)} />
        </Sheet>
      ) : null}
    </View>
  );
}
