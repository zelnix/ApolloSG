// Text Guard — SMS-focused guard. Android: optional automatic scanning of new text-message
// notifications via Apollo's opt-in Notification Listener access (READ_SMS is never used here — see
// ApolloSmsListenerService.kt). iOS: Apple gives third-party apps no way to read Messages
// automatically, so the honest paths are pasting a message here, a screenshot, or Share → Apollo where
// the source app offers Share.
// Both platforms run the SAME on-device Text & Message engine + Email/Text Guard link assessment as
// a pasted check (src/store/ApolloContext.checkMessage) — nothing here invents a separate verdict path.
import { useRouter } from "expo-router";
import MessageSquareWarning from "lucide-react-native/icons/message-square-warning";
import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, AppState, Platform, Text, TextInput, View } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { PatrolItem } from "@/src/components/PatrolItem";
import { projectPatrolOutcomes } from "@/src/domain/patrolOutcomes";
import { CheckResultScreen } from "@/src/components/CheckResultScreen";
import { InvestigationCheckScreen } from "@/src/components/InvestigationCheckScreen";
import { RecoveryFlow } from "@/src/components/RecoveryFlow";
import { Sheet } from "@/src/components/Sheet";
import { Body, Button, Card, Pill, SectionTitle } from "@/src/components/ui";
import { STATE_LABEL, STATE_MEANING, STATE_NAME } from "@/src/domain/types";
import { buildMessageCheckResult } from "@/src/domain/messageCheckResultAdapter";
import { contextFromEvent, gateForCategory, messageOriginalEvidence } from "@/src/domain/higginsHandoff";
import { MessagingSdk, type MessagingCapabilities } from "@/src/security/messagingSdk";
import { simulation } from "@/src/simulation";
import { type MessageOutcome, useApollo } from "@/src/store/ApolloContext";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { goBackOrHome } from "@/src/utils/navigation";
import { recordCheck } from "@/src/store/checkHistoryStore";
import { saveCheck } from "@/src/store/savedCheckStore";
import { CheckHistoryCard } from "@/src/components/CheckHistoryCard";
import { InfoButton } from "@/src/components/InfoButton";
import { CloseButton } from "@/src/components/CloseButton";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  top: { paddingHorizontal: spacing.xl, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingBottom: spacing.md },
  title: { fontFamily: fonts.displayBold, fontSize: 22, color: c.onSurface },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: c.surfaceTertiary },
  content: { paddingHorizontal: spacing.xl, gap: spacing.lg },
  iconWell: { width: 36, height: 36, borderRadius: 18, backgroundColor: c.navyTint, alignItems: "center", justifyContent: "center" },
  rowTop: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  cardTitle: { fontFamily: fonts.displayBold, fontSize: 16, color: c.brand },
  input: { minHeight: 48, backgroundColor: c.surfaceTertiary, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontFamily: fonts.text, fontSize: 15, color: c.onSurface },
  multi: { minHeight: 132, textAlignVertical: "top" },
  verdict: { fontFamily: fonts.displayBold, fontSize: 20, lineHeight: 26, color: c.onSurface },
  stateLabel: { fontFamily: fonts.display, fontSize: 15, color: c.onSurface },
  why: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  small: { fontFamily: fonts.text, fontSize: 12, color: c.muted },
}));

export default function TextGuard() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { checkMessage, resolveEvent, showToast, events } = useApollo();

  // Automatic scanning status (Android: NotificationListenerService grant; iOS: honestly unsupported).
  const [caps, setCaps] = useState<MessagingCapabilities | null>(null);
  const [openingSettings, setOpeningSettings] = useState(false);
  const [capsReadFailed, setCapsReadFailed] = useState(false);
  // A failed capability read leaves caps null AND records that the read failed, so the screen can say
  // "couldn't check" rather than implying automatic scanning is simply unavailable.
  const refreshCaps = useCallback(() => {
    void MessagingSdk.getMessagingCapabilities()
      .then((value) => { setCaps(value); setCapsReadFailed(false); })
      .catch(() => { setCaps(null); setCapsReadFailed(true); });
  }, []);
  useEffect(() => { refreshCaps(); }, [refreshCaps]);
  useEffect(() => {
    const sub = AppState.addEventListener("change", (st) => { if (st === "active") refreshCaps(); });
    return () => sub.remove();
  }, [refreshCaps]);
  const smsOn = caps?.smsFiltering === "supported";
  const smsSupported = caps?.smsFiltering !== "unsupported";

  const turnOn = async () => {
    setOpeningSettings(true);
    try {
      const r = await MessagingSdk.openSmsListenerSettings();
      if (r.opened) showToast("Settings opened. Turn on ApolloSG under notification access, then come back.", "neutral");
    } finally { setOpeningSettings(false); }
  };

  // Manual paste fallback — the primary path on iOS, and the backup everywhere else.
  const [sender, setSender] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<MessageOutcome | null>(null);
  const [verify, setVerify] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [historyKey, setHistoryKey] = useState(0);

  // `source` lets a direct selection be checked immediately; the flow below is the same real
  // check a pasted or shared message runs (checkMessage → Triage → Magnum DI only if Triage escalates).
  const runWith = async (source?: { sender: string; text: string }) => {
    if (source) { setSender(source.sender); setText(source.text); }
    setBusy(true); setError(null);
    try { setResult(await checkMessage(source?.sender ?? sender, source?.text ?? text, { via: "pasted", simulated: !!source })); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not check this message."); }
    finally { setBusy(false); }
  };

  const run = async () => {
    if (!text.trim()) return;
    setBusy(true); setError(null); setResult(null);
    try { setResult(await checkMessage(sender, text)); } catch (e) { setError(e instanceof Error ? e.message : "Could not check this message."); } finally { setBusy(false); }
  };

  const recent = events.filter((e) => e.category === "message" && e.state !== "resting").slice(0, 5);
  const a = result?.analysis;

  useEffect(() => {
    if (result?.analysis) {
      void recordCheck("text", { at: new Date().toISOString(), state: result.analysis.state, summary: result.analysis.scenarioTitle });
      setHistoryKey((k) => k + 1);
    }
  }, [result]);

  // UNIVERSAL CHECK RESULT — when the text check has produced an outcome, the entire screen
  // becomes the shared Check Result. ONE Higgins paragraph, ONE items list, ONE actions row.
  if (result && a) {
    const model = { ...buildMessageCheckResult({ analysis: a, event: result.event ?? null, sender, explanation: result.explanation ?? null, urlResults: result.urls ?? [], phones: result.phones ?? [], official: result.official }), evidenceProfile: result.event?.evidence_profile ?? result.profile ?? null };
    const askPrompt = `About the text I just checked (from ${model.subject}). ${model.headline} Can you walk me through what Apollo found and what I should do?`;
    const textActions: { label: string; onPress: () => void; testID: string; variant?: "primary" | "secondary" | "ghost" }[] = [];
    textActions.push({ testID: "textguard-verify-sender", variant: "secondary", label: "Show me how to check the sender", onPress: () => setVerify(true) });
    a.signals.urls.forEach((u: string, i: number) => {
      textActions.push({ testID: `textguard-check-link-${i}`, variant: "ghost", label: `Check: ${u.length > 35 ? u.slice(0, 35) + "\u2026" : u}`, onPress: () => router.push({ pathname: "/check", params: { url: u.startsWith("http") ? u : `https://${u}`, source: "message" } }) });
    });
    if (result.event) {
      textActions.push({ testID: "textguard-mark-safe", variant: "ghost", label: "Mark as handled", onPress: () => { void resolveEvent(result.event!); showToast("Marked as handled.", "neutral"); goBackOrHome(router); } });
    }
    textActions.push({
      testID: "textguard-save", variant: "ghost",
      label: saved ? "Saved \u2713 \u2014 View saved checks" : "Save this check",
      onPress: () => {
        if (saved) { router.push("/saved-checks"); return; }
        void saveCheck({ id: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`, gate: "text", title: a.scenarioTitle, subject: sender || "Sender not supplied", state: a.state, stateName: STATE_NAME[a.state], summary: result.explanation?.summary ?? a.verdict, recommendation: result.explanation?.recommendation ?? a.recommendation, sections: [{ title: "Why", lines: result.explanation?.why?.length ? result.explanation.why : a.why }, { title: "Signals", lines: a.signalLabels }, { title: "Links", lines: a.signals.urls }] }).then(() => { setSaved(true); showToast("Saved. Find it under Saved checks.", "neutral"); });
      },
    });
    textActions.push({ testID: "textguard-again", variant: "ghost", label: "Check another message", onPress: () => { setResult(null); setText(""); setSender(""); setSaved(false); } });

    return (
      <>
        {result.event ? (
          <InvestigationCheckScreen
            result={model}
            investigationContext={{
              ...contextFromEvent(result.event, gateForCategory(result.event.category)),
              // The message exactly as it was checked goes with the investigation, so its Evidence tab has it.
              original_evidence: messageOriginalEvidence(sender, text, a.signals.urls),
            }}
            investigationQuestion={askPrompt}
            submissionId={result.event.event_id}
            eventId={result.event.event_id}
            actions={textActions}
          />
        ) : (
          <CheckResultScreen result={model} actions={textActions} />
        )}
        {result.event ? <RecoveryFlow event={result.event} kinds={["clicked", "password", "code", "money", "info", "app"]} linkToCheck={a.signals.urls[0] ?? null} testID="textguard-recovery" /> : null}
        <Sheet visible={verify} onClose={() => setVerify(false)} title="Verify the sender" testID="textguard-verify-sheet">
          <Body>{a.verifySender}</Body>
          <Body>Never verify using a number, link or email that only appears in the suspicious message.</Body>
          <Button testID="textguard-verify-close" variant="ghost" label="Got it" onPress={() => setVerify(false)} />
        </Sheet>
      </>
    );
  }

  return (
    <View style={s.root}>
      <View style={[s.top, { paddingTop: insets.top + spacing.md }]}>
        <Text style={s.title}>Message screening</Text>
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
          <CloseButton testID="textguard-close" onPress={() => goBackOrHome(router)} />
          <InfoButton info={{ title: "About message screening", body: ["Apollo investigates pasted texts and chosen screenshots using local scam detection and link and public evidence checks: TC Hawkeye first, and Magnum DI only if a deeper look could change the answer.", ...(Platform.OS === "android" ? ["Apollo can also automatically scan new text-message notifications from your chosen messaging app as they arrive. Apollo never reads your SMS inbox or message history."] : []), "Raw content is discarded after the assessment; provider-side retention follows the configured AI provider policy."] }} testID="textguard-info" />
        </View>
      </View>
      <KeyboardAwareScrollView contentContainerStyle={[s.content, { paddingBottom: insets.bottom + spacing.xl }]} bottomOffset={24} testID="textguard-scroll">
        <Body testID="textguard-intro">Apollo investigates pasted texts and chosen screenshots using local scam detection and link and public evidence checks: TC Hawkeye first, and Magnum DI only if a deeper look could change the answer. Raw content is not retained by ApolloSG.</Body>

        <Card style={{ gap: spacing.sm }} testID="textguard-auto-card">
          <View style={s.rowTop}>
            <View style={s.iconWell}><MessageSquareWarning size={18} color={colors.brand} /></View>
            <Text style={[s.cardTitle, { flex: 1 }]}>Automatic scanning</Text>
            <Pill tone={capsReadFailed ? "unknown" : smsOn ? "resting" : smsSupported ? "growling" : "unknown"}
              label={capsReadFailed ? "Couldn't check" : smsOn ? "On" : smsSupported ? "Off" : "Not available"} testID="textguard-auto-status" />
          </View>
          {capsReadFailed ? (
            <Body testID="textguard-auto-detail">ApolloSG asked this device whether automatic scanning is on and the read failed, so it can&apos;t say either way. Nothing here confirms texts are being scanned. Pull down to try again, or paste a text below.</Body>
          ) : Platform.OS === "android" ? (
            smsOn ? (
              <Body testID="textguard-auto-detail">Apollo checks new text-message notifications from your chosen messaging app as they arrive. Notification text is sent for the same purpose-limited assessment as a manual check, then discarded. Apollo never reads your SMS inbox or message history.</Body>
            ) : (
              <>
                <Body testID="textguard-auto-detail">Turning this on authorises ongoing assessment of new notifications from your chosen messaging app. Apollo reads only each notification as it arrives, never your SMS inbox or history, and does not retain the raw notification text.</Body>
                <Button testID="textguard-turn-on" variant="secondary" label={openingSettings ? "Opening…" : "Turn on notification access"} onPress={() => void turnOn()} disabled={openingSettings} />
              </>
            )
          ) : (
            <Body testID="textguard-auto-detail">Apple doesn&apos;t let apps read your Messages automatically — there&apos;s no setting ApolloSG can turn on for this. Paste a suspicious text below or use a screenshot. If the app it&apos;s in offers Share, you can share it to ApolloSG.</Body>
          )}
        </Card>

        {recent.length ? (
          <View>
            <SectionTitle>Recently flagged from your messages</SectionTitle>
            <View testID="textguard-recent">
              {projectPatrolOutcomes(recent).map((outcome, i, list) => <PatrolItem key={outcome.outcomeId} outcome={outcome} isLast={i === list.length - 1} />)}
            </View>
          </View>
        ) : null}

        <simulation.Picker
          testID="textguard-simulated"
          title="Simulated messages"
          note="This is NOT your real message list and no texts are read from this device. These samples exist so the real message check can be exercised in the preview. Apollo runs his own checks on whichever you pick and decides the outcome himself."
          disabled={busy}
          items={simulation.texts.map((m) => ({ id: m.id, primary: m.sender, secondary: m.text, probes: m.probes }))}
          onSelect={(id: string) => { const m = simulation.texts.find((x) => x.id === id); if (m) void runWith({ sender: m.sender, text: m.text }); }}
        />

        <View>
          <SectionTitle>Paste a message</SectionTitle>
          <Card style={{ gap: spacing.md }} testID="textguard-paste-card">
            <TextInput testID="textguard-sender" style={s.input} value={sender} onChangeText={setSender} placeholder="Sender (number, name or handle) — optional" placeholderTextColor={colors.muted} autoCorrect={false} />
            <TextInput testID="textguard-text" style={[s.input, s.multi]} value={text} onChangeText={setText} placeholder="Paste the text message here" placeholderTextColor={colors.muted} multiline autoCorrect={false} />
            <Button testID="textguard-check" label={busy ? "Sniffing…" : "Check message"} onPress={() => void run()} disabled={!text.trim() || busy} />
            <Button testID="textguard-check-screenshot" variant="secondary" label="Investigate a message screenshot" onPress={() => router.push({ pathname: "/message", params: { openScreenshot: "1", source: "text-guard" } })} />
            <Text style={s.small} testID="textguard-privacy">Submitting content authorises one purpose-limited investigation. Request copies close immediately and never later than 15 minutes. Ongoing notification checks require the separate opt-in above.</Text>
          </Card>
        </View>

        {error ? <Card testID="textguard-error"><Body>{error}</Body></Card> : null}
        {busy ? (
          <Card style={{ flexDirection: "row", alignItems: "center", gap: spacing.md }} testID="textguard-sniffing">
            <ActivityIndicator color={colors.sniffing} /><View style={{ flex: 1 }}><Text style={s.stateLabel}>{STATE_LABEL.sniffing}</Text><Body>{STATE_MEANING.sniffing}</Body></View>
          </Card>
        ) : null}

        <CheckHistoryCard gate="text" refreshKey={historyKey} testID="textguard-history" />
      </KeyboardAwareScrollView>
    </View>
  );
}
