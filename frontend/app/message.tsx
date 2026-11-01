// Gate 2 — Check a message. Approved screen implementation.
// Header, optional inbox picker (only where READ_SMS is declared — off by default for Play), screenshot,
// typed/pasted text, gold Check message CTA, and the permission-free ways in (Text Guard, Share where offered).
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import { Asset } from "expo-asset";
import { Image as ExpoImage } from "expo-image";
import ChevronDown from "lucide-react-native/icons/chevron-down";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import ChevronUp from "lucide-react-native/icons/chevron-up";
import Clock from "lucide-react-native/icons/clock";
import ImageIcon from "lucide-react-native/icons/image";
import MessageSquare from "lucide-react-native/icons/message-square";
import Search from "lucide-react-native/icons/search";
import User from "lucide-react-native/icons/user";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { AppState, Platform, Pressable, Text, TextInput, View } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { CheckResultScreen } from "@/src/components/CheckResultScreen";
import { InvestigationCheckScreen } from "@/src/components/InvestigationCheckScreen";
import { RecoveryFlow } from "@/src/components/RecoveryFlow";
import { ScreenshotPermissionSheet } from "@/src/components/ScreenshotPermissionSheet";
import { Sheet } from "@/src/components/Sheet";
import { Body, Button, Card } from "@/src/components/ui";
import { STATE_NAME } from "@/src/domain/types";
import { buildMessageCheckResult } from "@/src/domain/messageCheckResultAdapter";
import type { MessageVia } from "@/src/domain/triage/messageEvidence";
import { contextFromEvent, gateForCategory, messageOriginalEvidence } from "@/src/domain/higginsHandoff";
import { screenImage } from "@/src/domain/imagePrivacy";
import { type MessageOutcome, useApollo } from "@/src/store/ApolloContext";
import { CheckHistoryCard } from "@/src/components/CheckHistoryCard";
import { recordCheck } from "@/src/store/checkHistoryStore";
import { saveCheck } from "@/src/store/savedCheckStore";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { goBackOrHome } from "@/src/utils/navigation";
import { CheckToolHeader } from "@/src/components/CheckToolHeader";
import { CheckingModal } from "@/src/components/CheckingModal";
import { useScreenshotAccess } from "@/src/hooks/useScreenshotAccess";
import { redactUserSecrets } from "@/src/domain/privacy";
import { getShareIntake } from "@/src/share/shareIntake";
import { PhonePickers, type RecentSms } from "@/src/security/phonePickers";
import { SourceHero } from "@/src/components/SourceHero";
import { SourcePickerSheet } from "@/src/components/SourcePickerSheet";
import { findSampleText } from "@/src/sampleChecks";
import { simulation } from "@/src/simulation";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  top: { paddingHorizontal: spacing.lg, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingBottom: spacing.md },

  // ── Scroll content ──
  content: { paddingHorizontal: spacing.lg, gap: spacing.lg },

  // ── Description ──
  description: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurfaceSecondary },

  // ── Message card ──
  messageCard: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.md, borderWidth: 0.25, borderColor: c.border },
  messageCardHeader: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  messageIconWell: { width: 44, height: 44, borderRadius: 22, backgroundColor: "#DBEAFE", alignItems: "center", justifyContent: "center" },
  messageCardLabel: { fontFamily: fonts.displayBold, fontSize: 17, color: c.onSurface },
  messageInput: { minHeight: 100, backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontFamily: fonts.text, fontSize: 16, color: c.onSurface, textAlignVertical: "top" },

  // ── Gold CTA ──
  goldBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: c.gold, borderRadius: radius.lg, paddingVertical: 16, paddingHorizontal: spacing.xl, gap: spacing.md, minHeight: 56 },
  goldBtnDisabled: { opacity: 0.45 },
  goldBtnText: { fontFamily: fonts.displayBold, fontSize: 17, color: c.onSurface },

  // ── Or divider ──
  orDivider: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.xs },
  orLine: { flex: 1, height: 1, backgroundColor: c.border },
  orText: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.muted },

  // ── Action cards row ──
  actionCardsRow: { gap: spacing.md },
  actionCard: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.sm, borderWidth: 0.25, borderColor: c.border },
  actionCardHeader: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  actionCardIconWell: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  actionCardTitle: { fontFamily: fonts.displayBold, fontSize: 15, color: c.onSurface, flex: 1 },
  actionCardSub: { fontFamily: fonts.text, fontSize: 13, lineHeight: 18, color: c.onSurfaceSecondary },
  actionCardChevron: { marginLeft: "auto" },

  // ── Expandable enter text link ──
  expandLink: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.sm, paddingHorizontal: spacing.xs },
  expandLinkText: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.brandPrimary, flex: 1 },

  // ── Recent messages section ──
  recentSection: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, borderWidth: 0.25, borderColor: c.border, overflow: "hidden" },
  recentHeader: { paddingHorizontal: spacing.lg, paddingTop: spacing.lg, paddingBottom: spacing.md, gap: 4 },
  recentHeaderTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  recentTitleRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  recentClockWell: { width: 36, height: 36, borderRadius: 18, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  recentTitle: { fontFamily: fonts.displayBold, fontSize: 17, color: c.onSurface },
  seeAllRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  seeAllText: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.brand },
  recentSub: { fontFamily: fonts.text, fontSize: 14, color: c.onSurfaceSecondary, marginLeft: 48 },

  // ── Message row ──
  msgRow: { flexDirection: "row", alignItems: "center", paddingVertical: spacing.md, paddingHorizontal: spacing.lg, gap: spacing.md, borderTopWidth: 1, borderTopColor: c.border },
  msgIconWell: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  msgAlertWell: { backgroundColor: "rgba(217,83,79,0.12)" },
  msgContactWell: { alignItems: "center", justifyContent: "center" },
  msgUnknownWell: { backgroundColor: c.surfaceTertiary },
  msgInitial: { fontFamily: fonts.displayBold, fontSize: 18, color: "#FFFFFF" },
  msgInfo: { flex: 1, gap: 2 },
  msgSender: { fontFamily: fonts.displayBold, fontSize: 16, color: c.onSurface },
  msgPreview: { fontFamily: fonts.text, fontSize: 14, color: c.onSurfaceSecondary, numberOfLines: 1 },
  msgDateCol: { alignItems: "flex-end", gap: 2, flexShrink: 0 },
  msgDate: { fontFamily: fonts.text, fontSize: 13, color: c.muted },
  msgTime: { fontFamily: fonts.text, fontSize: 13, color: c.muted },

  // ── Empty recent ──
  recentEmpty: { padding: spacing.xl, alignItems: "center", gap: spacing.sm },

  // ── Screenshot preview ──
  preview: { width: "100%", height: 180, borderRadius: radius.md, backgroundColor: c.surfaceTertiary },

  // ── Error card ──
  errorCard: { backgroundColor: "rgba(217,83,79,0.08)", borderRadius: radius.lg, padding: spacing.lg, gap: spacing.sm, borderWidth: 1, borderColor: "rgba(217,83,79,0.2)" },
  errorText: { fontFamily: fonts.text, fontSize: 14, color: c.onSurface },

  // ── Progress ──
  progressWrap: { gap: spacing.md, padding: spacing.lg },
  progressRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  stateLabel: { fontFamily: fonts.display, fontSize: 15, color: c.onSurface },
}));

export default function CheckMessage() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const params = useLocalSearchParams<{ text?: string; sender?: string; source?: string; imageUri?: string; openScreenshot?: string; sharedIntakeId?: string; receivedAt?: string; sample?: string }>();
  const shared = getShareIntake(params.sharedIntakeId);
  const sharedText = shared?.text || shared?.webUrl || params.text || "";
  const sharedImage = shared?.files?.find((file) => (file.mimeType ?? "").startsWith("image/"))?.path || params.imageUri || "";
  const { ready, setupDone, deviceId, checkMessage, resolveEvent, showToast } = useApollo();
  const [sender, setSender] = useState(params.sender ? String(params.sender) : "");
  const [messagePicker, setMessagePicker] = useState(false);
  const [samplePicker, setSamplePicker] = useState(false);
  const [text, setText] = useState(String(sharedText));
  // The message exactly as it was checked: an investigation opened from the result carries it as its evidence.
  const [checked, setChecked] = useState<{ text: string; sender: string } | null>(null);
  const [busy, setBusy] = useState<"idle" | "reading" | "checking">("idle");
  const [result, setResult] = useState<MessageOutcome | null>(null);
  const [verify, setVerify] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** The screenshot had no message text Apollo could read — no check was run. */
  const [screenshotError, setScreenshotError] = useState<string | null>(null);
  const [screenshotUri, setScreenshotUri] = useState<string | null>(sharedImage ? String(sharedImage) : null);
  const isEmail = params.source === "email";
  // The inbox picker needs READ_SMS, which a build only declares under the approved switch (off by default).
  const canPickSms = !isEmail && PhonePickers.isSupported("sms");
  // With no inbox picker (and no preview samples) typing or pasting is the main way in, so start open.
  const [manualOpen, setManualOpen] = useState(!canPickSms && !simulation.included);
  const autoRan = useRef(false);
  const autoImage = useRef(false);
  const autoPicker = useRef(false);

  // ── Recent SMS messages ──
  const [recentSms, setRecentSms] = useState<RecentSms[]>([]);
  const loadRecentSms = useCallback(async () => {
    if (!canPickSms) return;
    try {
      const hasPerm = await PhonePickers.hasPermission("sms");
      if (!hasPerm.granted) return;
      const msgs = await PhonePickers.listRecentSms();
      setRecentSms(msgs);
    } catch { /* not available */ }
  }, [canPickSms]);
  useEffect(() => { void loadRecentSms(); }, [loadRecentSms]);
  useEffect(() => {
    const sub = AppState.addEventListener("change", (s) => { if (s === "active") void loadRecentSms(); });
    return () => sub.remove();
  }, [loadRecentSms]);

  // `via` is how the message reached ApolloSG — it sets the evidence level Higgins Triage records for it.
  const run = async (t = text, snd = sender, via: MessageVia = "pasted", receivedAt: string | null = null, simulated = false) => {
    const safeText = redactUserSecrets(t);
    if (!safeText.trim()) return;
    if (safeText !== t) setText(safeText);
    setBusy("checking"); setError(null); setResult(null);
    try { const outcome = await checkMessage(snd, safeText, { via, receivedAt, simulated }); setChecked({ text: safeText, sender: snd }); setResult(outcome); return outcome; } catch (e) { setError(e instanceof Error ? e.message : "Could not check this message."); return null; } finally { setBusy("idle"); }
  };
  useEffect(() => {
    if (sharedText && ready && setupDone && !autoRan.current) {
      autoRan.current = true;
      const fromInbox = params.source === "inbox_picker";
      void run(String(sharedText), params.sender ? String(params.sender) : "", fromInbox ? "inbox" : "shared", fromInbox && params.receivedAt ? String(params.receivedAt) : null);
    }
  }, [sharedText, params.sender, ready, setupDone]); // eslint-disable-line react-hooks/exhaustive-deps
  // A sample chosen from Sample Checks or preview runs exactly as picking from the real inbox does.
  useEffect(() => {
    if (!params.sample || !ready || !setupDone || autoRan.current) return;
    // Try production sample data first, then fall back to preview simulation
    const prodSample = findSampleText(params.sample);
    const m = prodSample
      ? { sender: prodSample.sender, text: prodSample.text }
      : (() => { const sim = simulation.texts.find((x) => x.id === params.sample); return sim ? { sender: sim.sender, text: sim.text } : undefined; })();
    if (!m) return;
    autoRan.current = true;
    setSender(m.sender); setText(m.text);
    void run(m.text, m.sender, "inbox", null, true);
  }, [params.sample, ready, setupDone]); // eslint-disable-line react-hooks/exhaustive-deps

  /** The phone reads the screenshot's text (credentials removed) and the ordinary message check runs on that
   *  text. The picture itself never leaves the device; only Magnum DI's one investigation call may follow. */
  const readScreenshot = async (uri: string) => {
    setBusy("reading"); setError(null); setScreenshotError(null); setResult(null); setScreenshotUri(uri);
    try {
      const screening = await screenImage(uri, "message_screenshot");
      const read = screening.extractedText.trim();
      if (!read) {
        setBusy("idle");
        setScreenshotError(screening.previewNotice
          ? "This preview can’t run on-device text recognition, so no text was read from this screenshot and nothing was checked. On a phone build Apollo reads it on your device. Try a preview sample screenshot, or type or paste the message."
          : screening.status === "ocr_unavailable"
          ? "Apollo can’t read text from screenshots here because on-device text recognition isn’t available. Nothing was checked. Type or paste the message instead."
          : "Apollo couldn’t find any message text in this screenshot, so nothing was checked. Try a clearer screenshot, or type or paste the message.");
        return;
      }
      const from = screening.detectedSender ?? "";
      setSender(from); setText(read); setManualOpen(true);
      await run(read, from, "screenshot");
    } catch {
      setBusy("idle");
      setScreenshotError("Apollo couldn’t read that screenshot, so nothing was checked. Try another screenshot, or type or paste the message.");
    }
  };
  const launchScreenshotPicker = async () => {
    try {
      const picked = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], allowsEditing: false, quality: 0.9 });
      if (picked.canceled || !picked.assets[0]) return;
      await readScreenshot(picked.assets[0].uri);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not open your screenshots."); setBusy("idle"); }
  };
  const photoAccess = useScreenshotAccess(launchScreenshotPicker);
  // Preview only: a sample screenshot whose text is known stands in for the device's text recogniser.
  const checkSampleScreenshot = async (id: string) => {
    setSamplePicker(false);
    const sample = simulation.screenshots.find((x) => x.id === id);
    if (!sample) return;
    try {
      const asset = Asset.fromModule(sample.asset);
      await asset.downloadAsync();
      const uri = asset.localUri ?? asset.uri;
      simulation.registerImage(uri, sample.id);
      await readScreenshot(uri);
    } catch { setScreenshotError("ApolloSG couldn’t open that sample screenshot. Try another one."); }
  };
  useEffect(() => {
    if (params.openScreenshot !== "1" || !ready || !setupDone || autoPicker.current) return;
    autoPicker.current = true; void photoAccess.start();
  }, [params.openScreenshot, ready, setupDone, photoAccess]);
  // Screenshot shared from another app (Share → Apollo): read it as soon as the screen opens.
  useEffect(() => {
    if (!sharedImage || !deviceId || autoImage.current) return;
    autoImage.current = true;
    void readScreenshot(String(sharedImage));
  }, [sharedImage, deviceId]); // eslint-disable-line react-hooks/exhaustive-deps

  const [historyKey, setHistoryKey] = useState(0);

  useEffect(() => { if (result?.analysis) { void recordCheck("message", { at: new Date().toISOString(), state: result.analysis.state, summary: result.analysis.scenarioTitle }); setHistoryKey((k) => k + 1); } }, [result]);

  if (ready && !setupDone) return <Redirect href="/" />;
  const a = result?.analysis;

  // UNIVERSAL CHECK RESULT — when the message check has produced an outcome, the entire screen
  // becomes the shared Check Result. ONE Higgins paragraph, ONE items list, ONE actions row.
  if (result && a) {
    const model = { ...buildMessageCheckResult({ analysis: a, event: result.event, sender, explanation: result.explanation, urlResults: result.urls, phones: result.phones, official: result.official }), evidenceProfile: result.event?.evidence_profile ?? result.profile ?? null };
    const askPrompt = `About the message I just checked (from ${model.subject}). ${model.headline} Can you walk me through what Apollo found and what I should do?`;
    const msgActions: { label: string; onPress: () => void; testID: string; variant?: "primary" | "secondary" | "ghost" }[] = [];
    msgActions.push({ testID: "message-verify-sender", variant: "secondary", label: "Show me how to check the sender", onPress: () => setVerify(true) });
    if (a.signals.loginRequest || a.signals.codeRequest || /password|sign[- ]?in|login|account/i.test(text)) {
      msgActions.push({ testID: "message-check-account", variant: "secondary", label: "It's about my account \u2014 check account alert", onPress: () => router.push({ pathname: "/account", params: { text, scent: result.event?.scent_id ?? result.event?.event_id ?? "" } }) });
    }
    a.signals.urls.forEach((u, i) => {
      const r = result.urls.find((x) => x.url.replace(/\/$/, "").includes(u.replace(/^https?:\/\//i, "").replace(/\/$/, "")));
      const label = r?.verdict === "malicious" ? `\u26a0 ${u.length > 35 ? u.slice(0, 35) + "\u2026" : u}` : `Check: ${u.length > 35 ? u.slice(0, 35) + "\u2026" : u}`;
      msgActions.push({ testID: `message-check-link-${i}`, variant: r?.verdict === "malicious" ? "secondary" : "ghost", label, onPress: () => router.push({ pathname: "/check", params: { url: u.startsWith("http") ? u : `https://${u}`, source: "message", scent: result.event?.scent_id ?? result.event?.event_id ?? "" } }) });
    });
    if (result.event) {
      msgActions.push({ testID: "message-mark-safe", variant: "ghost", label: "Mark as handled", onPress: () => { void resolveEvent(result.event!); showToast("Marked as handled.", "neutral"); goBackOrHome(router); } });
    }
    msgActions.push({ testID: "message-save", variant: "ghost", label: saved ? "Saved \u2713 \u2014 View saved checks" : "Save this check", onPress: () => { if (saved) { router.push("/saved-checks"); return; } void saveCheck({ id: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`, gate: "message", title: a.scenarioTitle, subject: sender || "Sender not supplied", state: a.state, stateName: STATE_NAME[a.state], summary: result.explanation?.summary ?? a.verdict, recommendation: result.explanation?.recommendation ?? a.recommendation, sections: [{ title: "Why", lines: result.explanation?.why?.length ? result.explanation.why : a.why }, { title: "Signals Apollo saw", lines: a.signalLabels }, { title: "Links in this message", lines: a.signals.urls }] }).then(() => { setSaved(true); showToast("Saved. Find it under Saved checks.", "neutral"); }); } });
    msgActions.push({ testID: "message-again", variant: "ghost", label: "Check another message", onPress: () => { setResult(null); setText(""); setSender(""); setScreenshotUri(null); } });

    return (
      <>
        {result.event ? (
          <InvestigationCheckScreen
            result={model}
            investigationContext={{
              ...contextFromEvent(result.event, gateForCategory(result.event.category)),
              // The same material ApolloSG's own investigation of a message receives: its text and its links.
              original_evidence: checked ? messageOriginalEvidence(checked.sender, checked.text, a.signals.urls) : [],
            }}
            investigationQuestion={askPrompt}
            submissionId={result.event.event_id}
            eventId={result.event.event_id}
            caseId={result.event.investigation_case_id ?? null}
            actions={msgActions}
          />
        ) : (
          <CheckResultScreen result={model} actions={msgActions} />
        )}
        {result.event ? (
          <RecoveryFlow event={result.event} kinds={["called", "clicked", "password", "code", "money", "info", "app"]} linkToCheck={a.signals.urls[0] ?? null} testID="message-recovery" />
        ) : null}
        <Sheet visible={verify} onClose={() => setVerify(false)} title={a.signals.callbackRequest ? (a.signals.claimedBrand?.toLowerCase() === "paypal" ? "Check PayPal independently" : "Check the account independently") : "Verify the sender"} testID="verify-sender-sheet">
          <Body>{a.verifySender}</Body>
          <Body>Never verify using a number, link or email that only appears in the suspicious message.</Body>
          <Button testID="verify-sender-close" variant="ghost" label="Got it" onPress={() => setVerify(false)} />
        </Sheet>
        <ScreenshotPermissionSheet prefix="message" visible={!!photoAccess.permission} canAskAgain={photoAccess.permission?.canAskAgain ?? true}
          checking={photoAccess.checking} onContinue={() => void photoAccess.continueAccess()} onClose={photoAccess.close} />
      </>
    );
  }

  // ── Helper: contact initial color ──
  const INITIAL_COLORS = ["#6366F1", "#8B5CF6", "#EC4899", "#F97316", "#14B8A6", "#3B82F6", "#10B981", "#EF4444"];
  const initialColor = (name: string) => INITIAL_COLORS[name.charCodeAt(0) % INITIAL_COLORS.length];

  // ── Helper: format date for recent message rows ──
  const formatMsgDate = (ts: number) => {
    const d = new Date(ts);
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    const isYesterday = d.toDateString() === yesterday.toDateString();
    const datePart = isToday ? "Today" : isYesterday ? "Yesterday" : d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
    const timePart = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", hour12: true });
    return { datePart, timePart };
  };

  // ── Helper: determine if address is a phone number ──
  const isPhoneNumber = (addr: string) => /^\+?\d[\d\s\-()]{5,}$/.test(addr.trim());

  // ── Tap recent message → auto-investigate ──
  const checkRecentMessage = (msg: RecentSms) => {
    setSender(msg.address);
    setText(msg.body);
    void run(msg.body, msg.address, "inbox", msg.date ? new Date(msg.date).toISOString() : null);
  };

  return (
    <View style={s.root}>
      <View style={[s.top, { paddingTop: insets.top + spacing.md }]}>
        <CheckToolHeader
          title={params.source === "email" ? "Email monitoring" : "Check a message"}
          info={{ title: params.source === "email" ? "About email monitoring" : "About message screening", body: ["Paste any message and Apollo will check it using local scam detection and link and public evidence checks. TC FlyBy investigates it first, and Magnum DI looks deeper only if that could change the answer. Higgins explains the result.", "Apollo checks claimed identity, pressure tactics, embedded links and sender reputation. Raw content is discarded after the assessment."] }}
          testID="message"
        />
      </View>

      <KeyboardAwareScrollView contentContainerStyle={[s.content, { paddingBottom: insets.bottom + 100 }]} bottomOffset={24} testID="message-scroll">
        {/* Inbox picker — only when this build can actually read SMS, or preview samples exist. Never a dead option. */}
        {canPickSms || simulation.included ? (
          <SourceHero
            testID="message-hero"
            title="Pick a message from this device"
            caption="Apollo reads the one message you choose — never your inbox or your history."
            actions={[{
              testID: "message-pick-sms",
              label: "Choose a message",
              icon: <MessageSquare size={20} color={colors.onBrandPrimary} />,
              onPress: () => {
                if (canPickSms) { router.push("/message-picker"); return; }
                setMessagePicker(true);
              },
            }]}
          />
        ) : null}

        {/* ── Screenshot action card ── */}
        <View style={s.actionCardsRow}>
          {/* Take a screenshot */}
          <Pressable
            testID="message-screenshot"
            accessibilityRole="button"
            accessibilityLabel="Take a screenshot"
            onPress={() => void photoAccess.start()}
            disabled={busy !== "idle"}
            style={({ pressed }) => [s.actionCard, busy !== "idle" && { opacity: 0.5 }, { opacity: pressed && busy === "idle" ? 0.85 : 1 }]}
          >
            <View style={s.actionCardHeader}>
              <View style={s.actionCardIconWell}><ImageIcon size={20} color={colors.onSurface} /></View>
              <Text style={s.actionCardTitle}>Take a screenshot</Text>
              <ChevronRight size={18} color={colors.muted} />
            </View>
            <Text style={s.actionCardSub}>Choose a screenshot of the message. Apollo reads its text on this device — the picture itself isn’t sent.</Text>
          </Pressable>
          {simulation.included ? (
            <Button testID="message-sample-screenshot" variant="ghost" label="Use a preview sample screenshot" disabled={busy !== "idle"} onPress={() => setSamplePicker(true)} />
          ) : null}
        </View>

        {/* ── Screenshot with no readable text: nothing was checked; pick another or type it ── */}
        {screenshotError ? (
          <View style={s.errorCard} testID="message-screenshot-error">
            <Text style={s.errorText}>{screenshotError}</Text>
            <Button testID="message-screenshot-again" variant="secondary" label="Choose another screenshot" onPress={() => void photoAccess.start()} />
            <Button testID="message-type-instead" variant="ghost" label="Type or paste the message" onPress={() => { setScreenshotError(null); setScreenshotUri(null); setManualOpen(true); }} />
          </View>
        ) : null}

        {/* ── Enter message text (expandable) ── */}
        <Pressable
          accessibilityRole="button"
          onPress={() => setManualOpen((v) => !v)}
          style={s.expandLink}
          testID="message-expand-text"
        >
          <View style={s.messageIconWell}>
            <MessageSquare size={22} color="#1D4ED8" />
          </View>
          <Text style={s.expandLinkText}>Enter message text</Text>
          {manualOpen ? <ChevronUp size={18} color={colors.muted} /> : <ChevronDown size={18} color={colors.muted} />}
        </Pressable>
        {manualOpen ? (
          <View style={s.messageCard} testID="message-card">
            <TextInput
              testID="message-text"
              style={s.messageInput}
              value={text}
              onChangeText={setText}
              placeholder="Enter or paste message text here"
              placeholderTextColor={colors.muted}
              multiline
              autoCorrect={false}
              dataDetectorTypes="none"
            />
          </View>
        ) : null}

        {/* ── Screenshot preview ── */}
        {screenshotUri ? <ExpoImage testID="message-screenshot-preview" source={{ uri: screenshotUri }} style={s.preview} contentFit="contain" accessibilityLabel="Screenshot selected for investigation" /> : null}

        {/* ── Gold CTA: Check message ── */}
        <Pressable
          testID="message-check"
          accessibilityRole="button"
          accessibilityLabel="Check message"
          disabled={!text.trim() || busy !== "idle"}
          onPress={() => void run()}
          style={({ pressed }) => [s.goldBtn, (!text.trim() || busy !== "idle") && s.goldBtnDisabled, { opacity: pressed && text.trim() && busy === "idle" ? 0.85 : 1 }]}
        >
          <Search size={22} color={colors.onSurface} />
          <Text style={s.goldBtnText}>{"Check message"}</Text>
        </Pressable>

        {/* ── Error ── */}
        {error ? (
          <View style={s.errorCard} testID="message-error">
            <Text style={s.errorText}>{error}</Text>
            <Button testID="message-retry" variant="secondary" label="Try again" onPress={() => void run()} />
          </View>
        ) : null}

        {/* ── Progress handled by CheckingModal ── */}

        {/* ── Other ways in when Apollo can't open the inbox (no READ_SMS) ── */}
        {!canPickSms && !isEmail ? (
          <Card testID="message-other-ways" style={{ gap: spacing.sm }}>
            {Platform.OS === "android" ? <>
              <Body testID="message-other-ways-textguard">Text Gate can check new texts as they arrive, using notification access you turn on in Android&apos;s settings.</Body>
              <Button testID="message-open-textguard" variant="secondary" label="Set up Text Gate" onPress={() => router.push("/text-guard")} />
            </> : null}
            <Body testID="message-other-ways-share">You can also copy a message and paste it above, or use a screenshot. If the app the message is in offers Share, you can share it straight to ApolloSG.</Body>
          </Card>
        ) : null}

        {/* ── Recent Messages Section (inbox picker builds only) ── */}
        {canPickSms ? (
        <View style={s.recentSection} testID="message-recent-section">
          {/* Header */}
          <View style={s.recentHeader}>
            <View style={s.recentHeaderTop}>
              <View style={s.recentTitleRow}>
                <View style={s.recentClockWell}>
                  <Clock size={18} color={colors.onSurface} />
                </View>
                <Text style={s.recentTitle}>Recent messages</Text>
              </View>
              {recentSms.length > 0 ? (
                <Pressable accessibilityRole="button" onPress={() => canPickSms ? router.push("/message-picker") : undefined} style={s.seeAllRow} hitSlop={8}>
                  <Text style={s.seeAllText}>See all</Text>
                  <ChevronRight size={16} color={colors.brand} />
                </Pressable>
              ) : null}
            </View>
            <Text style={s.recentSub}>Tap a message to check it with ApolloSG.</Text>
          </View>

          {/* Message rows */}
          {recentSms.length > 0 ? (
            recentSms.slice(0, 5).map((msg, i) => {
              const isNumber = isPhoneNumber(msg.address);
              const { datePart, timePart } = formatMsgDate(msg.date);
              return (
                <Pressable
                  key={`${msg.address}-${msg.date}-${i}`}
                  testID={`message-recent-${i}`}
                  accessibilityRole="button"
                  accessibilityLabel={`Check message from ${msg.address}`}
                  onPress={() => checkRecentMessage(msg)}
                  style={({ pressed }) => [s.msgRow, { opacity: pressed ? 0.7 : 1 }]}
                >
                  {isNumber ? (
                    <View style={[s.msgIconWell, s.msgUnknownWell]}>
                      <User size={22} color={colors.muted} />
                    </View>
                  ) : (
                    <View style={[s.msgIconWell, s.msgContactWell, { backgroundColor: initialColor(msg.address) }]}>
                      <Text style={s.msgInitial}>{msg.address.charAt(0).toUpperCase()}</Text>
                    </View>
                  )}
                  <View style={s.msgInfo}>
                    <Text style={s.msgSender} numberOfLines={1}>{msg.address}</Text>
                    <Text style={s.msgPreview} numberOfLines={1}>{msg.body}</Text>
                  </View>
                  <View style={s.msgDateCol}>
                    <Text style={s.msgDate}>{datePart}</Text>
                    <Text style={s.msgTime}>{timePart}</Text>
                  </View>
                  <ChevronRight size={18} color={colors.muted} />
                </Pressable>
              );
            })
          ) : (
            <View style={s.recentEmpty}>
              <MessageSquare size={28} color={colors.muted} />
              <Body>Recent messages will appear here when SMS permission is granted.</Body>
            </View>
          )}
        </View>
        ) : null}

        <CheckHistoryCard gate="message" refreshKey={historyKey} testID="message-history" />
      </KeyboardAwareScrollView>

      <ScreenshotPermissionSheet prefix="message" visible={!!photoAccess.permission} canAskAgain={photoAccess.permission?.canAskAgain ?? true}
        checking={photoAccess.checking} onContinue={() => void photoAccess.continueAccess()} onClose={photoAccess.close} />

      <SourcePickerSheet
        visible={messagePicker}
        title="Your messages"
        note="Apollo runs the real message check on whichever one you pick."
        preview
        items={simulation.texts.map((m) => ({ id: m.id, primary: m.sender, secondary: m.text, meta: m.probes }))}
        emptyText="There are no messages to choose from here."
        onSelect={(id: string) => {
          setMessagePicker(false);
          const m = simulation.texts.find((x) => x.id === id);
          if (!m) return;
          setSender(m.sender); setText(m.text);
          void run(m.text, m.sender, "inbox", null, true);
        }}
        onClose={() => setMessagePicker(false)}
        testID="message-source-picker"
      />

      <SourcePickerSheet
        visible={samplePicker}
        title="Sample screenshots"
        note="Apollo reads the text each sample is known to show, then runs the real message check on it."
        preview
        items={simulation.screenshots.map((x) => ({ id: x.id, primary: x.label, meta: x.probes }))}
        emptyText="There are no sample screenshots here."
        onSelect={(id: string) => void checkSampleScreenshot(id)}
        onClose={() => setSamplePicker(false)}
        testID="message-sample-picker"
      />

      {/* ── Checking overlay modal ── */}
      <CheckingModal
        visible={busy !== "idle"}
        title={busy === "reading" ? "Reading message" : "Checking message"}
        subject={sender.trim() ? `From: ${sender.trim()}` : undefined}
        description={busy === "reading" ? "Reading the visible text and links…" : "Higgins Triage and TC FlyBy are checking\nwording, scam patterns and reputation signals."}
      />
    </View>
  );
}
