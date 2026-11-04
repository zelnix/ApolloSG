import * as Crypto from "expo-crypto";
import { Image } from "expo-image";
import { useLocalSearchParams, useRouter } from "expo-router";
import Trash2 from "lucide-react-native/icons/trash";
import Info from "lucide-react-native/icons/info";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import CirclePlus from "lucide-react-native/icons/circle-plus";
import SendHorizontal from "lucide-react-native/icons/send-horizontal";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, NativeScrollEvent, NativeSyntheticEvent, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { InvestigationView } from "@/src/components/InvestigationView";
import { ResubmitReminder } from "@/src/components/ResubmitReminder";
import type { StoppedCase } from "@/src/investigation/resubmit";
import { AlertsButton } from "@/src/components/AlertsButton";
import { AppMenuButton } from "@/src/components/AppMenu";
import { FitTitle } from "@/src/components/FitTitle";
import { HigginsCheckSheet, type HigginsCheckCategory } from "@/src/components/HigginsCheckSheet";
import { HigginsArtifactInput, type ArtifactResult } from "@/src/components/HigginsArtifactInput";
import type { PreparedImage } from "@/src/components/ImageUploadPrep";
import { saveImageEvidence } from "@/src/store/imageEvidence";
import { saveOriginalSource, type OriginalSourceInput, type OriginalSourceKind } from "@/src/store/originalSource";
import { Sheet } from "@/src/components/Sheet";
import { TypingDots } from "@/src/components/TypingDots";
import { Body, Button, Card, DevTag, Pill } from "@/src/components/ui";
import { clearHandoffTransfers, takeHandoff } from "@/src/domain/handoffTransfer";
import { parseHigginsIssueContext, type HigginsIssueContext } from "@/src/domain/higginsHandoff";
import { redactInvestigationSecrets as redactUserSecrets } from "@/src/domain/privacy";
import { askHiggins, clearHigginsHistory, higginsHistory, isQuoted, rememberHigginsContext, type HigginsChatAction, type HigginsChatMessage } from "@/src/higgins/chatClient";
import { luddishChat } from "@/src/domain/luddish";
import { resolveNavLinks } from "@/src/higgins/appMap";
import { buildDeviceSnapshot, loadSnapshotExtras, type SnapshotExtras } from "@/src/higgins/deviceSnapshot";
import { readDeviceCapabilityState, type DeviceCapabilityReading } from "@/src/security/deviceCapabilityState";
import { useCallScreener } from "@/src/hooks/useCallScreener";
import { clearLocalChat, loadLocalChat, saveLocalChat } from "@/src/higgins/chatMemory";
import { clearStarterMemory, loadStarterMemory, recordStarter, topStarters } from "@/src/higgins/starterMemory";
import { pickQuickQuestions } from "@/src/higgins/quickQuestions";
import { classifyIntent } from "@/src/higgins/intentRouter";
import { detectCheckIntent } from "@/src/higgins/checkIntent";
import { explainIssue, INVESTIGATE_OFFER } from "@/src/higgins/issueExplanation";
import { getProtectionStatus, getGateStatus, getCurrentIssues, getPermissionStatus, getVpnStatus, getNotificationDiagnostic } from "@/src/higgins/diagnosticCore";
import { diagnosticToHigginsMessage, knowledgeToHigginsMessage, clarificationToHigginsMessage, termToHigginsMessage } from "@/src/higgins/localResponder";
import { getNotificationHealth } from "@/src/push/notifications";
import { useInvestigation } from "@/src/investigation/caseStore";
import type { Gate } from "@/src/investigation/types";
import { createCaseInput } from "@/src/investigation/fromContext";
import { rememberCaseForEvent } from "@/src/investigation/caseIndex";
import { useProtectionHealth } from "@/src/protection/healthStore";
import { useApollo } from "@/src/store/ApolloContext";
import { buildDailyActivity } from "@/src/domain/dailyActivity";
import { investigatorName } from "@/src/domain/messageVoice";
import { HigginsAvatar } from "@/src/components/HigginsAvatar";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const WELCOME = "Hello! I'm Higgins.\n\nI'm here to help you understand ApolloSG, explain security alerts, and answer your cyber-safety questions.\n\nWhat can I help you with today?";
const ABOUT = "Higgins is Apollo’s trusted handler, and the savant of this app. He knows every screen, check, protection, setting, flow and privacy rule in ApolloSG, and he knows how scams work. Ask him where something is and he'll take you straight there.\n\nHe answers about this phone from a live reading of what Apollo actually reports — your protections, permissions, threats, alerts and settings — so he never has to guess.\n\nWhat Higgins doesn't do is investigate. TC FlyBy checks evidence quickly against official sources, ApolloSG's knowledge base and a targeted search, and Magnum DI looks deeper only when that could change the answer; Apollo detects and blocks on the device. Higgins explains, guides and hands off.\n\nChatting sends your question and that state reading. It never includes your messages, screenshots, files or secrets.";

const formatTime = (iso: string) => { try { return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); } catch { return ""; } };

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  // Column: the icon row can never squeeze the words, so nothing in the header is ever truncated.
  header: { paddingHorizontal: spacing.xl, paddingBottom: spacing.md, borderBottomWidth: 1, borderBottomColor: c.border },
  headerRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  headerActions: { flexDirection: "row", alignItems: "center", gap: 2 },
  aboutAvatarImg: { width: "100%", aspectRatio: 0.833, borderRadius: 16, marginBottom: spacing.sm },
  headerText: { flex: 1 },
  name: { fontFamily: fonts.displayBold, fontSize: 28, color: c.onSurface },
  subtitle: { fontFamily: fonts.text, fontSize: 13, color: c.onSurfaceSecondary, marginTop: 2 },
  menuBtn: { width: 34, height: 34, borderRadius: 17, alignItems: "center", justifyContent: "center" },

  list: { paddingHorizontal: spacing.lg, paddingTop: spacing.lg, paddingBottom: 120, gap: spacing.sm },

  rowHiggins: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, maxWidth: "92%", alignSelf: "flex-start" },
  rowUser: { alignSelf: "flex-end", maxWidth: "88%", alignItems: "flex-end" },
  miniAvatar: { marginBottom: 16 },
  bubbleHiggins: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, borderTopLeftRadius: 4, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderWidth: 1, borderColor: c.border, flexShrink: 1 },
  bubbleUser: { backgroundColor: c.brandPrimary, borderRadius: radius.lg, borderTopRightRadius: 4, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  msgHiggins: { fontFamily: fonts.text, fontSize: 16, lineHeight: 24, color: c.onSurface },
  msgUser: { fontFamily: fonts.text, fontSize: 16, lineHeight: 24, color: c.onBrandPrimary },
  time: { fontFamily: fonts.text, fontSize: 11, color: c.muted, marginTop: 3, marginHorizontal: 6 },

  // Destinations Higgins offered for an answer — a tap straight to the screen he named.
  linkRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.sm },
  linkChip: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 36, paddingLeft: spacing.md, paddingRight: spacing.sm, borderRadius: radius.pill, borderWidth: 1, borderColor: c.brandPrimary, backgroundColor: c.surface },
  linkText: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.brandPrimary },

  starters: { gap: spacing.sm, alignSelf: "flex-start", maxWidth: "92%", marginLeft: 34, marginTop: spacing.xs },  starter: { minHeight: 44, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderRadius: radius.pill, borderWidth: 1, borderColor: c.brandPrimary, backgroundColor: c.surface, justifyContent: "center", alignSelf: "flex-start" },
  starterText: { fontFamily: fonts.textMedium, fontSize: 14, color: c.brandPrimary },

  composer: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.sm, backgroundColor: c.glass, borderTopWidth: 1, borderTopColor: c.border },
  clearRow: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: spacing.xs, backgroundColor: c.glass, borderTopWidth: 1, borderTopColor: c.border },
  clearText: { fontFamily: fonts.text, fontSize: 13, color: c.muted },
  repeatRow: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, gap: spacing.sm, alignItems: "center" },
  repeatChip: { maxWidth: 240, minHeight: 36, paddingHorizontal: spacing.md, borderRadius: radius.pill, borderWidth: 1, borderColor: c.border, backgroundColor: c.surfaceSecondary, justifyContent: "center" },
  repeatText: { fontFamily: fonts.textMedium, fontSize: 13, color: c.onSurfaceSecondary },
  input: { flex: 1, minHeight: 48, maxHeight: 120, backgroundColor: c.surfaceTertiary, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontFamily: fonts.text, fontSize: 16, color: c.onSurface },
  send: { width: 48, height: 48, borderRadius: 24, alignItems: "center", justifyContent: "center", backgroundColor: c.brandPrimary },
  attachBtn: { width: 48, height: 48, borderRadius: 24, alignItems: "center", justifyContent: "center" },

  context: { marginHorizontal: spacing.xl, marginTop: spacing.md, gap: spacing.xs, borderColor: c.navyBorder },

  sheetBody: { fontFamily: fonts.text, fontSize: 15, lineHeight: 23, color: c.onSurfaceSecondary },
  welcomePrompt: { fontFamily: fonts.textMedium, fontSize: 15, lineHeight: 22, color: c.onSurfaceSecondary, paddingHorizontal: spacing.xs },
  errorText: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.barkingText },
}));

export default function Ask() {
  const s = useStyles(); const { colors } = useTheme(); const insets = useSafeAreaInsets(); const router = useRouter();
  const { deviceId, events, resolution, trust, adapterLabel, network, notificationStatus, quietHours, quietNow, lowPower } = useApollo();
  const health = useProtectionHealth();
  const callScreener = useCallScreener();
  const params = useLocalSearchParams<{ context?: string; prompt?: string; autoSend?: string; handoffId?: string; operationId?: string; resumeCaseId?: string; scamTitle?: string; scamSource?: string; scamUrl?: string; scamSummary?: string; screenshotUri?: string; screenshotName?: string; screenshotType?: string }>();
  const { state, start, ask, retry, cancel, remove, attach, retryDelete } = useInvestigation(params.operationId ? String(params.operationId) : null);
  const [text, setText] = useState(""); const [activeContext, setActiveContext] = useState<HigginsIssueContext | null>(null); const [investigationMode, setInvestigationMode] = useState(false);
  const [chatMessages, setChatMessages] = useState<HigginsChatMessage[]>([]); const [chatBusy, setChatBusy] = useState(false); const [chatError, setChatError] = useState<string | null>(null); const [lastAction, setLastAction] = useState<HigginsChatAction | null>(null);
  const [routeError, setRouteError] = useState<string | null>(null); const [aboutOpen, setAboutOpen] = useState(false); const [confirmClear, setConfirmClear] = useState(false);
  const [starters, setStarters] = useState<string[]>([]);
  // Offered after Higgins explains an issue from Apollo's own findings: a separate, explicit Magnum DI investigation.
  const [issueOffer, setIssueOffer] = useState<{ context: HigginsIssueContext; question: string } | null>(null);
  const [rotation, setRotation] = useState(0);
  const [snapshotExtras, setSnapshotExtras] = useState<SnapshotExtras | null>(null);
  const [capabilityReading, setCapabilityReading] = useState<DeviceCapabilityReading | null>(null);
  // Higgins check flow state
  const [checkSheetOpen, setCheckSheetOpen] = useState(false);
  const [artifactCategory, setArtifactCategory] = useState<HigginsCheckCategory | null>(null);
  const [artifactSheetOpen, setArtifactSheetOpen] = useState(false);
  const [artifactQuestion, setArtifactQuestion] = useState("");
  const conversationId = useRef(Crypto.randomUUID()); const seenRoute = useRef<string | null>(null); const scrollRef = useRef<ScrollView>(null); const inputRef = useRef<TextInput>(null); const contextRecorded = useRef<string | null>(null); const stick = useRef(true);
  const caseBusy = state.phase === "creating" || state.phase === "working" || state.phase === "reconnecting" || state.phase === "waiting_device";
  const busy = caseBusy || chatBusy;
  // Higgins speaks Luddish (L1): plain words, the evidence unchanged. An answer in a source's own words stays as it is.
  const shownChat = useMemo(() => new Map(chatMessages.filter((m) => m.role === "higgins" && !m.quoted).map((m) => [m.id, luddishChat(m.content)])), [chatMessages]);
  const latestUserMessage = useMemo(() => [...chatMessages].reverse().find((message) => message.role === "user")?.content ?? "", [chatMessages]);

  useEffect(() => {
    if (!deviceId) return;
    void loadLocalChat().then(setChatMessages).catch(() => undefined);
    void loadStarterMemory().then((entries) => setStarters(topStarters(entries))).catch(() => undefined);
    void loadSnapshotExtras().then(setSnapshotExtras).catch(() => undefined);
    void readDeviceCapabilityState().then(setCapabilityReading).catch(() => undefined);
    void higginsHistory(deviceId).catch(() => undefined); // server keeps only five-minute content and non-content receipts
  }, [deviceId]);
  useEffect(() => { const caseId = params.resumeCaseId ? String(params.resumeCaseId) : ""; if (!caseId || caseId === seenRoute.current) return; seenRoute.current = caseId; setInvestigationMode(true); router.setParams({ resumeCaseId: "" }); void attach(caseId); }, [params.resumeCaseId, attach, router]);
  useEffect(() => { if (!params.handoffId && params.prompt && !investigationMode) { setText(redactUserSecrets(String(params.prompt))); router.setParams({ prompt: "" }); } }, [params.prompt, params.handoffId, investigationMode, router]);

  // Stage 13: Receive screenshot evidence from Check tab → start Magnum investigation.
  // The screenshot is evidence, not a local verdict — it goes directly to Magnum DI.
  const screenshotHandled = useRef<string | null>(null);
  useEffect(() => {
    const uri = params.screenshotUri ? String(params.screenshotUri) : "";
    if (!uri || !deviceId || screenshotHandled.current === uri) return;
    screenshotHandled.current = uri;
    const question = params.prompt ? redactUserSecrets(String(params.prompt)).trim() : "Investigate this screenshot — is this a scam or legitimate?";
    const name = params.screenshotName ? String(params.screenshotName) : "screenshot.jpg";
    const type = params.screenshotType ? String(params.screenshotType) : "image/jpeg";
    router.setParams({ screenshotUri: "", screenshotName: "", screenshotType: "", prompt: "" });
    setInvestigationMode(true); setText(""); setRouteError(null); setChatError(null); setLastAction(null);
    const operationId = Crypto.randomUUID(); router.setParams({ operationId });
    const input = { gate: null as Gate | null, question, submissions: [] as { clientItemId: string; kind: "text" | "url"; value: string; label: string }[], initialFindingRefs: [] as string[], initialFindings: [] as string[] };
    void start(input, [{ uri, name, mediaType: type }], operationId);
  }, [params.screenshotUri, params.screenshotName, params.screenshotType, params.prompt, deviceId, router, start]);

  const autoSent = useRef<string | null>(null);
  const pendingImageEvidence = useRef<PreparedImage | null>(null);
  const pendingOriginal = useRef<OriginalSourceInput | null>(null);
  const caseId = state.caseData?.id;
  useEffect(() => {
    const original = pendingOriginal.current;
    if (caseId && original) { pendingOriginal.current = null; void saveOriginalSource([caseId], original); }
    const prepared = pendingImageEvidence.current;
    if (!caseId || !prepared) return;
    pendingImageEvidence.current = null;
    void saveImageEvidence(prepared, [caseId]);
  }, [caseId]);
  useEffect(() => {
    if (!deviceId || health.checking || !health.checkedAt || contextRecorded.current === health.checkedAt) return;
    contextRecorded.current = health.checkedAt;
    const on = health.gates.filter((gate) => gate.resolved.coverageState === "active_verified" && gate.resolved.isAutomatic).length; const attention = health.gates.filter((gate) => gate.tone === "action").map((gate) => gate.title);

    // Improvement 6: Enrich Higgins context with daily activity for natural conversation
    const dailyActivity = buildDailyActivity(events);
    const activitySuffix = dailyActivity.eventCount > 0
      ? ` Today: ${dailyActivity.summary}`
      : " No significant activity recorded today.";

    void rememberHigginsContext({ category: "protection_state", provenance: "device_observation", observedAt: health.checkedAt, summary: `${on} automatic protections are on.${attention.length ? ` Needs attention: ${attention.join(", ")}.` : ""}${activitySuffix}` }).catch(() => undefined);
  }, [deviceId, health, events]);

  const scrollToEnd = useCallback((force = false) => { if (force || stick.current) requestAnimationFrame(() => scrollRef.current?.scrollToEnd({ animated: true })); }, []);

  // ── Scroll-to-top-of-answer ────────────────────────────────────────────
  // When Higgins replies the viewport lands at the TOP of the new answer.
  // A persistent interval re-applies the position every 100 ms so that
  // late layout passes (link chips, spacer resize, font load) can never
  // push the view back to the bottom.  The interval is cleared when the
  // user drags or after 4 s as a safety net.
  const rowY = useRef<Record<string, number>>({});
  const rowH = useRef<Record<string, number>>({});
  const topTarget = useRef<string | null>(null);
  const scrollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const viewportH = useRef(0);
  const lastAnswerId = useRef<string | null>(null);
  const [spacer, setSpacer] = useState(0);

  const clearScrollTimer = useCallback(() => {
    if (scrollTimer.current) { clearInterval(scrollTimer.current); scrollTimer.current = null; }
  }, []);

  const applyTop = useCallback(() => {
    const id = topTarget.current;
    if (!id) return;
    const y = rowY.current[id];
    if (y === undefined) return;
    scrollRef.current?.scrollTo({ y: Math.max(y - spacing.sm, 0), animated: false });
  }, []);

  const refreshSpacer = useCallback(() => {
    const id = lastAnswerId.current;
    if (!id || viewportH.current === 0) { setSpacer(0); return; }
    setSpacer(Math.max(0, Math.round(viewportH.current - (rowH.current[id] ?? 0) - spacing.xl * 2)));
  }, []);

  const noteRow = useCallback((id: string, y: number, height: number) => {
    rowY.current[id] = y;
    rowH.current[id] = height;
    if (id === lastAnswerId.current) refreshSpacer();
    if (topTarget.current === id) applyTop();
  }, [applyTop, refreshSpacer]);

  // Derive target synchronously.
  const derivedTarget = React.useMemo(() => {
    const last = chatMessages[chatMessages.length - 1];
    return !investigationMode && last?.role === "higgins" ? last.id : null;
  }, [chatMessages, investigationMode]);

  if (derivedTarget !== lastAnswerId.current) {
    lastAnswerId.current = derivedTarget;
    if (!derivedTarget) {
      topTarget.current = null;
      clearScrollTimer();
    } else if (stick.current) {
      topTarget.current = derivedTarget;
    }
  }

  useEffect(() => {
    refreshSpacer();
    if (!topTarget.current) return;
    // Start a persistent interval that keeps the answer at the top.
    clearScrollTimer();
    applyTop();
    scrollTimer.current = setInterval(applyTop, 100);
    // Safety: stop after 4 s even if the user hasn't dragged.
    const safety = setTimeout(() => { clearScrollTimer(); }, 4000);
    return () => { clearScrollTimer(); clearTimeout(safety); };
  }, [derivedTarget, applyTop, refreshSpacer, clearScrollTimer]);

  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => { const { layoutMeasurement, contentOffset, contentSize } = e.nativeEvent; stick.current = contentOffset.y + layoutMeasurement.height >= contentSize.height - 140; };

  const startInvestigation = useCallback((message: string, context?: HigginsIssueContext | null) => {
    const clean = redactUserSecrets(message).trim(); if (!clean || busy || !deviceId) return;
    setInvestigationMode(true); setText(""); setRouteError(null); setChatError(null); setLastAction(null);
    const { input, files } = createCaseInput(context ?? activeContext, clean); const operationId = Crypto.randomUUID(); router.setParams({ operationId });
    void start(input, files, operationId).then((created) => { if (created && (context ?? activeContext)?.event_id) void rememberCaseForEvent((context ?? activeContext)!.event_id!, created.id); });
  }, [activeContext, busy, deviceId, router, start]);

  // Higgins is the savant of Apollo: every question goes up with a live, state-only
  // reading of this device, so he answers from what is actually true here.
  const snapshot = useMemo(() => buildDeviceSnapshot({
    health, events, trustCount: trust.length, notificationStatus, quietHours, quietNow, lowPower,
    adapterLabel, network, callScreener: callScreener.state === "checking" ? null : `${callScreener.summary} — ${callScreener.detail}`,
    extras: snapshotExtras ?? undefined, capabilities: capabilityReading,
  }), [health, events, trust.length, notificationStatus, quietHours, quietNow, lowPower, adapterLabel, network, callScreener.state, callScreener.summary, callScreener.detail, snapshotExtras, capabilityReading]);
  const snapshotRef = useRef(snapshot);
  snapshotRef.current = snapshot;

  const sendToHiggins = useCallback((message: string, appendUser: boolean) => {
    setChatBusy(true); setChatError(null); setLastAction(null); stick.current = true;
    const turnId = Crypto.randomUUID();
    const previousTurnIds = [...new Set(chatMessages.map((item) => item.turnId))].slice(-8);
    if (appendUser) {
      const optimistic: HigginsChatMessage = { id: Crypto.randomUUID(), turnId, role: "user", content: message, createdAt: new Date().toISOString(), conversationId: conversationId.current };
      setChatMessages((current) => { const next = [...current, optimistic]; void saveLocalChat(next); return next; });
    }
    void askHiggins(message, conversationId.current, turnId, previousTurnIds, snapshotRef.current).then((reply) => {
      const links = resolveNavLinks(reply.navigation);
      setChatMessages((current) => { const next = [...current, { id: Crypto.randomUUID(), turnId: reply.turnId, role: "higgins" as const, content: `${reply.answer}${reply.clarification ? `\n\n${reply.clarification}` : ""}`, createdAt: new Date().toISOString(), conversationId: reply.conversationId, links: links.length ? links : undefined, ...(isQuoted(reply) ? { quoted: true } : {}) }]; void saveLocalChat(next); return next; });
      setLastAction(reply.suggestedActions[0] ?? null);
    }).catch(() => setChatError("Higgins couldn't answer right now. No investigation was started.")).finally(() => setChatBusy(false));
  }, [chatMessages]);

  // ── Local-first intent handler ──
  // Handles local_diagnostic and local_knowledge intents entirely on-device.
  // Returns true if the message was handled locally, false if it should go to the API.
  const handleLocalIntent = useCallback((message: string): boolean => {
    const decision = classifyIntent(
      message,
      chatMessages.map((m) => m.content).slice(-5),
      investigationMode || !!state.caseData,
    );

    if (decision.route === "local_diagnostic" && decision.diagnosticIntent) {
      // Handled entirely on-device — Magnum DI is never contacted
      let result;
      switch (decision.diagnosticIntent) {
        case "protection_status":
        case "device_health":
          result = getProtectionStatus(health);
          break;
        case "site_gate_status":
          result = getGateStatus(health, "site");
          break;
        case "call_gate_status":
          result = getGateStatus(health, "call");
          break;
        case "text_gate_status":
          result = getGateStatus(health, "text");
          break;
        case "app_gate_status":
          result = getGateStatus(health, "app");
          break;
        case "vpn_status":
          result = getVpnStatus(health);
          break;
        case "permission_status":
          result = getPermissionStatus(health.permissions);
          break;
        case "notification_status":
          // Async — need to fetch notification health first
          void (async () => {
            const nh = await getNotificationHealth();
            const nr = getNotificationDiagnostic(nh);
            const msg = diagnosticToHigginsMessage(nr, conversationId.current);
            setChatMessages((current) => { const next = [...current, msg]; void saveLocalChat(next); return next; });
          })();
          return true;
        case "current_issues":
          result = getCurrentIssues(health, { events, resolution });
          break;
        case "last_check":
          result = getProtectionStatus(health); // Last check time is part of protection status
          break;
        case "help_navigation":
          // Use knowledge responder
          const navMsg = knowledgeToHigginsMessage("help_navigation", conversationId.current);
          setChatMessages((current) => { const next = [...current, navMsg]; void saveLocalChat(next); return next; });
          return true;
        default:
          result = getProtectionStatus(health);
      }

      const higginsMsg = diagnosticToHigginsMessage(result, conversationId.current);
      setChatMessages((current) => { const next = [...current, higginsMsg]; void saveLocalChat(next); return next; });
      return true;
    }

    if (decision.route === "local_knowledge" && decision.knowledgeIntent) {
      const higginsMsg = knowledgeToHigginsMessage(decision.knowledgeIntent, conversationId.current);
      setChatMessages((current) => { const next = [...current, higginsMsg]; void saveLocalChat(next); return next; });
      return true;
    }

    if (decision.route === "local_knowledge" && decision.termId) {
      const termMsg = termToHigginsMessage(decision.termId, conversationId.current);
      setChatMessages((current) => { const next = [...current, termMsg]; void saveLocalChat(next); return next; });
      return true;
    }

    if (decision.route === "clarify" && decision.clarificationQuestion) {
      const clarifyMsg = clarificationToHigginsMessage(decision.clarificationQuestion, conversationId.current);
      setChatMessages((current) => { const next = [...current, clarifyMsg]; void saveLocalChat(next); return next; });
      return true;
    }

    // route === "investigation" / "ask_higgins" or unhandled → send to the Higgins API
    return false;
  }, [chatMessages, health, investigationMode, state.caseData, events, resolution]);

  const submit = (message: string) => {
    const clean = redactUserSecrets(message).trim(); if (!clean || busy || !deviceId) return;
    stick.current = true; // sending means "follow the conversation", wherever it was scrolled to
    setIssueOffer(null);
    // Active investigation → route to investigation case directly
    if (investigationMode || activeContext || state.caseData) { setText(""); if (state.caseData) void ask(clean); else startInvestigation(clean, activeContext); return; }

    // Add the user's message optimistically
    const userMsg: HigginsChatMessage = { id: Crypto.randomUUID(), turnId: Crypto.randomUUID(), role: "user", content: clean, createdAt: new Date().toISOString(), conversationId: conversationId.current };
    setChatMessages((current) => { const next = [...current, userMsg]; void saveLocalChat(next); return next; });
    setText("");

    // "Check this email / message / call / link / app / photo" → open the matching input form.
    // Decided on-device; the person still supplies the artifact and submits it for the real check.
    const checkIntent = detectCheckIntent(clean);
    if (checkIntent) {
      const ack: HigginsChatMessage = { id: Crypto.randomUUID(), turnId: Crypto.randomUUID(), role: "higgins", content: checkIntent.acknowledgement, createdAt: new Date().toISOString(), conversationId: conversationId.current };
      setChatMessages((current) => { const next = [...current, ack]; void saveLocalChat(next); return next; });
      setArtifactQuestion(clean);
      setArtifactCategory(checkIntent.category);
      setArtifactSheetOpen(true);
      void recordStarter(clean).then((entries) => setStarters(topStarters(entries))).catch(() => undefined);
      return;
    }

    // Route through intent classifier — local-first
    const handledLocally = handleLocalIntent(clean);
    if (!handledLocally) {
      // Send to Higgins API (which may escalate to Magnum DI)
      sendToHiggins(clean, false); // false = don't re-append user message
    }
    void recordStarter(clean).then((entries) => setStarters(topStarters(entries))).catch(() => undefined);
  };
  const retryLast = () => { if (!deviceId || chatBusy || !latestUserMessage) return; sendToHiggins(latestUserMessage, false); };

  // Auto-feed a scam alert (or any card context) into the chat so Higgins can reply right away.
  // The incoming `scamTitle` / `scamSource` / `scamUrl` / `scamSummary` are composed into the
  // person's first message to Higgins. Guarded so a stale tab navigation can't re-send.
  useEffect(() => {
    if (!deviceId || busy || investigationMode) return;
    const title = params.scamTitle ? String(params.scamTitle).trim() : "";
    if (!title) return;
    const key = `${title}::${params.scamSource ?? ""}`;
    if (autoSent.current === key) return;
    autoSent.current = key;
    const source = params.scamSource ? String(params.scamSource).trim() : "";
    const url = params.scamUrl ? String(params.scamUrl).trim() : "";
    const summary = params.scamSummary ? String(params.scamSummary).trim() : "";
    const lines = [
      `I just read this scam alert and I want to understand it:`,
      `• Title: ${title}`,
      source ? `• Source: ${source}` : "",
      summary ? `• What the source says: ${summary}` : "",
      url ? `• Official source: ${url}` : "",
      ``,
      `Can you explain what this scam is, how it works, and how I stay safe from it?`,
    ].filter(Boolean);
    const prompt = redactUserSecrets(lines.join("\n")).trim();
    // Clear the params immediately so a tab switch / rerender doesn't re-send.
    router.setParams({ scamTitle: "", scamSource: "", scamUrl: "", scamSummary: "" });
    if (prompt) sendToHiggins(prompt, true);
  }, [params.scamTitle, params.scamSource, params.scamUrl, params.scamSummary, deviceId, busy, investigationMode, router, sendToHiggins]);

  useEffect(() => {
    const id = params.handoffId ? String(params.handoffId) : ""; if (!id || id === seenRoute.current || !deviceId) return; seenRoute.current = id;
    const transfer = takeHandoff(id); const context = transfer?.context ?? (params.context ? parseHigginsIssueContext(String(params.context)) : null); router.setParams({ handoffId: "", context: "", prompt: "" });
    if (!context) { setRouteError("ApolloSG could not prepare this issue for Higgins. Return to the result and try again."); return; }
    const question = transfer?.question ?? redactUserSecrets(String(params.prompt ?? "")).trim();
    if (context.case_id) { setActiveContext(context); setInvestigationMode(true); void attach(context.case_id).then((opened) => { if (opened && question) void ask(question); }); return; }
    // Explaining a Patrol finding, an incident or a Device Check result: Apollo's own findings, in fixed wording.
    // No Gemini call and no investigation — Magnum DI only investigates if the person taps the offer below.
    const asked = question || "Explain this issue and what I should do next.";
    const now = new Date().toISOString();
    const exchange: HigginsChatMessage[] = [
      { id: Crypto.randomUUID(), turnId: Crypto.randomUUID(), role: "user", content: asked, createdAt: now, conversationId: conversationId.current },
      { id: Crypto.randomUUID(), turnId: Crypto.randomUUID(), role: "higgins", content: explainIssue(context), createdAt: now, conversationId: conversationId.current },
    ];
    setActiveContext(null); setInvestigationMode(false); stick.current = true;
    setChatMessages((current) => { const next = [...current, ...exchange]; void saveLocalChat(next); return next; });
    setIssueOffer({ context, question: asked });
  }, [params.handoffId, params.context, params.prompt, deviceId, router, attach, ask]);

  const deleteInvestigation = async () => { clearHandoffTransfers(); setActiveContext(null); setRouteError(null); setInvestigationMode(false); await remove(); };
  const clearChat = async () => { if (!deviceId || chatBusy) return; await Promise.all([clearHigginsHistory(deviceId), clearLocalChat(), clearStarterMemory()]); setChatMessages([]); setStarters([]); setLastAction(null); setIssueOffer(null); setChatError(null); conversationId.current = Crypto.randomUUID(); };
  const newQuestion = () => { if (busy) return; setActiveContext(null); setInvestigationMode(false); void remove(); };
  // The quiet note above the conversation reopens a stopped investigation with its Resubmit ready.
  const openStopped = (stopped: StoppedCase) => {
    if (busy) return;
    setActiveContext(null); setRouteError(null); setChatError(null); setLastAction(null); setInvestigationMode(true);
    void attach(stopped.caseId, stopped.jobId);
  };

  // ── Higgins check flow handlers ─────────────────────────────────────────
  const handleCheckCategorySelect = useCallback((category: HigginsCheckCategory) => {
    setArtifactQuestion("");
    setArtifactCategory(category);
    setArtifactSheetOpen(true);
  }, []);

  const handleArtifactSubmit = useCallback((result: ArtifactResult) => {
    setArtifactSheetOpen(false);
    setArtifactCategory(null);
    setArtifactQuestion("");
    if (!deviceId) return;

    // Build submissions from the artifact
    const submissions: { clientItemId: string; kind: "text" | "url"; value: string; label: string }[] = [];
    if (result.textContent) {
      if (result.category === "websites_links") {
        submissions.push({ clientItemId: Crypto.randomUUID(), kind: "url", value: result.textContent, label: "URL" });
      } else {
        // Named for what it is, never for the category it was chosen under ("messages calls" read as the message itself).
        submissions.push({ clientItemId: Crypto.randomUUID(), kind: "text", value: result.textContent, label: "submitted message" });
      }
    }

    // Determine the gate
    const gate = result.gate;

    // Build the question
    const question = redactUserSecrets(result.question).trim();
    if (!question) return;

    // Start investigation directly through Higgins
    setInvestigationMode(true);
    setText("");
    setRouteError(null);
    setChatError(null);
    setLastAction(null);
    const operationId = Crypto.randomUUID();
    router.setParams({ operationId });

    const input = {
      gate,
      question,
      submissions,
      initialFindingRefs: [] as string[],
      // How the check was started is workflow metadata, not an Apollo observation — it is not evidence.
      initialFindings: [] as string[],
    };

    // For screenshots with an image, include the file (the analysis copy); keep original + copy as local evidence.
    pendingImageEvidence.current = result.preparedImage;
    const KIND: Record<string, OriginalSourceKind> = { websites_links: "link", messages_calls: "text", email_accounts: "email", apps_files: "file", device_internet: "device", screenshot: "screenshot" };
    pendingOriginal.current = result.textContent
      ? (result.category === "websites_links" ? { kind: "link", url: result.textContent } : { kind: KIND[result.category] ?? "text", text: result.textContent })
      // An image-only submission still has a real original: the picture kept on this device.
      : result.imageUri ? { kind: "screenshot" } : null;
    const files = result.imageUri
      ? [{ uri: result.imageUri, name: "screenshot.jpg", mediaType: "image/jpeg" }]
      : [];

    void start(input, files, operationId);
  }, [deviceId, router, start]);

  const caseStatus = state.phase === "answered" ? `${investigatorName(state.caseData?.answeredBy)} has finished this investigation.` : state.phase === "waiting_user" ? "Magnum DI needs one answer from you" : state.phase === "failed" ? `Investigation incomplete${state.error ? ` — ${state.error}` : ""}.${state.failure || state.caseData ? " Retry available." : ""}` : state.phase === "expired" ? "Server copy cleaned up. Saved findings shown from this device." : caseBusy ? "Apollo is investigating…" : "Investigation findings are saved to this device.";
  const showWelcome = !investigationMode && chatMessages.length === 0;
  // Twenty ideas in the space of four: a fresh handful is drawn every few seconds, with
  // whatever this person has asked before kept at the front. Rotation stops as soon as a
  // conversation starts, so nothing moves under a thumb that is already reaching for it.
  const welcomeStarters = useMemo(() => {
    const own = starters.slice(0, 2);
    return [...own, ...pickQuickQuestions(4 - own.length, own)];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [starters, rotation]);
  // Pills only change on screen mount — no auto-rotation interval.
  const showRepeatRow = !investigationMode && chatMessages.length > 0 && !text.trim() && starters.length > 0;

  return <View style={s.root} testID="higgins-screen">
    <View style={{ paddingTop: insets.top + spacing.md }}>
      <View style={s.header} testID="higgins-header">
        <View style={s.headerRow}>
          <HigginsAvatar size={42} />
          <View style={s.headerText}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
              <FitTitle text="Ask Higgins" style={s.name} />
            </View>
          </View>
          <View style={s.headerActions}>
            <AlertsButton testID="higgins-alerts" />
            <Pressable testID="higgins-header-info" accessibilityRole="button" accessibilityLabel="About Higgins" hitSlop={8} style={s.menuBtn} onPress={() => setAboutOpen(true)}><Info size={17} color={colors.onSurface} /></Pressable>
            <AppMenuButton testID="higgins-app-menu" />
          </View>
        </View>
        <Text style={s.subtitle}>{investigationMode ? "Working with Apollo on this issue" : "Apollo’s trusted handler"}</Text>
      </View>
    </View>

    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"} keyboardVerticalOffset={0}>
      {activeContext ? <Card style={s.context} testID="ask-active-issue"><Pill tone={activeContext.assessment_state} label={`${activeContext.gate.toUpperCase()} GATE`} testID="ask-active-gate" /><Body testID="ask-active-summary">{activeContext.issue_summary}</Body>{state.caseData ? <Body testID="ask-handoff-reference">Case reference: {state.caseData.id.slice(0, 8)}</Body> : null}<Button testID="ask-new-conversation" variant="ghost" label="Back to chat" onPress={newQuestion} disabled={busy} /></Card> : null}
      <ResubmitReminder openCaseId={investigationMode ? caseId ?? null : null} disabled={busy} onOpen={openStopped} />

      <ScrollView ref={scrollRef} contentContainerStyle={s.list} testID="ask-messages" keyboardShouldPersistTaps="handled" scrollEventThrottle={64} onScroll={onScroll}
        onLayout={(e) => { viewportH.current = e.nativeEvent.layout.height; refreshSpacer(); }}
        onScrollBeginDrag={() => { topTarget.current = null; clearScrollTimer(); }}
        onContentSizeChange={() => {
          // When holding the answer at the top, re-apply on every layout pass.
          if (topTarget.current) { applyTop(); return; }
          // Only auto-scroll-to-end for investigation mode or if the user was
          // already at the bottom.  Never for regular chat answers.
          if (investigationMode) scrollToEnd(true);
          else scrollToEnd(false);
        }}>
        {showWelcome ? <>
          <Text style={s.welcomePrompt} testID="higgins-welcome">What can I help you with? Ask me anything, or tap ⓘ to learn what I do.</Text>
          <View style={s.starters} testID="ask-suggestions">
            {welcomeStarters.map((question, index) => <Pressable key={question} testID={`ask-suggestion-${index}`} style={s.starter} accessibilityRole="button" onPress={() => submit(question)} disabled={busy}><Text style={s.starterText} numberOfLines={2}>{question}</Text></Pressable>)}
          </View>
        </> : null}

        {!investigationMode ? chatMessages.map((message) => message.role === "user"
          ? <View key={message.id} testID={`ask-chat-${message.id}`} style={s.rowUser} onLayout={(e) => noteRow(message.id, e.nativeEvent.layout.y, e.nativeEvent.layout.height)}><View style={s.bubbleUser}><Text style={s.msgUser}>{message.content}</Text></View><Text style={s.time}>{formatTime(message.createdAt)}</Text></View>
          : <View key={message.id} testID={`ask-chat-${message.id}`} style={s.rowHiggins} onLayout={(e) => noteRow(message.id, e.nativeEvent.layout.y, e.nativeEvent.layout.height)}>
              <HigginsAvatar size={26} style={s.miniAvatar} />
              <View style={{ flexShrink: 1 }}>
                <View style={s.bubbleHiggins}><Text style={s.msgHiggins}>{shownChat.get(message.id) ?? message.content}</Text></View>
                {message.links?.length ? <View style={s.linkRow} testID={`ask-links-${message.id}`}>
                  {message.links.map((link, index) => <Pressable key={link.route} testID={`ask-link-${message.id}-${index}`} accessibilityRole="button" accessibilityLabel={`Open ${link.label}`} style={s.linkChip} onPress={() => router.push(link.route as never)}>
                    <Text style={s.linkText} numberOfLines={1}>{link.label}</Text>
                    <ChevronRight size={15} color={colors.brandPrimary} />
                  </Pressable>)}
                </View> : null}
                <Text style={s.time}>{formatTime(message.createdAt)}</Text>
              </View>
            </View>) : null}

        {!investigationMode && chatBusy ? <View style={s.rowHiggins} testID="ask-chat-progress">
          <HigginsAvatar size={26} style={s.miniAvatar} />
          <View style={s.bubbleHiggins}><TypingDots /></View>
        </View> : null}

        {!investigationMode && chatError ? <View style={s.rowHiggins} testID="ask-chat-error"><View style={[s.bubbleHiggins, { borderColor: colors.barking }]}><Text style={s.errorText}>{chatError}</Text><Button testID="ask-chat-retry" variant="ghost" label="Try again" onPress={retryLast} /></View></View> : null}

        {!investigationMode && lastAction?.destination === "higgins_case" && latestUserMessage ? <Card testID="ask-investigation-offer" style={{ marginTop: spacing.xs }}><Body>{lastAction.purpose}</Body><Button testID="ask-start-investigation" label={lastAction.label} onPress={() => startInvestigation(latestUserMessage)} /></Card> : null}
        {!investigationMode && issueOffer ? <Card testID="ask-issue-investigate-offer" style={{ marginTop: spacing.xs }}><Body>{INVESTIGATE_OFFER}</Body><Button testID="ask-issue-investigate" label="Ask Apollo to investigate" disabled={busy} onPress={() => { const offer = issueOffer; setIssueOffer(null); setActiveContext(offer.context); startInvestigation(offer.question, offer.context); }} /></Card> : null}

        {investigationMode ? <InvestigationView state={state} onAnswer={(answer) => void ask(answer)} onRetry={() => void retry()} onCancel={() => void cancel()} testID="ask-investigation" onAction={(action, outcome) => { if (outcome.kind === "observed") void ask(`I did "${action.label}". Please re-check using the fresh observation Apollo just recorded.`); }} /> : null}
        {routeError ? <Card style={s.context} testID="ask-error-card"><Text style={s.errorText} testID="ask-error">{routeError}</Text></Card> : null}
        {/* A stopped case already shows its own Resubmit (with Magnum DI's pause); this covers a case that never opened. */}
        {investigationMode && state.phase === "failed" && !state.caseData ? <Button testID="ask-retry-button" label={caseBusy ? "Retrying…" : "Retry"} disabled={caseBusy} onPress={() => void retry()} style={{ marginTop: spacing.md }} /> : null}
        {investigationMode && state.undeleted ? <Button testID="ask-retry-delete" variant="ghost" label="Try deleting again" onPress={() => void retryDelete()} /> : null}
        {investigationMode ? <Button testID="ask-clear-temporary-history" label="Clear this investigation" variant="ghost" onPress={() => void deleteInvestigation()} /> : null}
        {investigationMode ? <Text testID="ask-processing-state" style={[s.subtitle, { paddingHorizontal: spacing.lg, paddingTop: spacing.xs }]}>{caseStatus}</Text> : null}
        {spacer > 0 ? <View style={{ height: spacer }} testID="ask-top-spacer" /> : null}
      </ScrollView>

      {showRepeatRow ? <ScrollView horizontal showsHorizontalScrollIndicator={false} keyboardShouldPersistTaps="handled" contentContainerStyle={s.repeatRow} testID="higgins-repeat-row">
        {starters.map((question, index) => <Pressable key={question} testID={`higgins-repeat-${index}`} style={s.repeatChip} accessibilityRole="button" accessibilityLabel={`Ask again: ${question}`} onPress={() => submit(question)} disabled={busy}><Text style={s.repeatText} numberOfLines={1}>{question}</Text></Pressable>)}
      </ScrollView> : null}

      {/* Notifications: the bell in the header carries the "notifications are off" warning dot. */}

      {!investigationMode && chatMessages.length > 0 ? (
        <Pressable testID="higgins-clear-chat" accessibilityRole="button" onPress={() => setConfirmClear(true)} style={s.clearRow}>
          <Trash2 size={14} color={colors.muted} />
          <Text style={s.clearText}>Clear conversation</Text>
        </Pressable>
      ) : null}

      <View style={[s.composer, { paddingBottom: Math.max(insets.bottom, spacing.sm) }]}>
        <Pressable testID="ask-check-button" accessibilityRole="button" accessibilityLabel="Submit something for Higgins to check" onPress={() => setCheckSheetOpen(true)} disabled={busy} style={[s.attachBtn, { opacity: busy ? 0.5 : 1 }]}><CirclePlus size={24} color={colors.brandPrimary} /></Pressable>
        <TextInput ref={inputRef} testID="ask-input" style={s.input} value={text} onChangeText={setText} placeholder={investigationMode ? state.phase === "waiting_user" ? "Answer Higgins' question…" : "Ask about this investigation…" : "Message Higgins…"} placeholderTextColor={colors.muted} multiline returnKeyType="send" blurOnSubmit onSubmitEditing={() => submit(text)} onFocus={() => { if (!topTarget.current) scrollToEnd(true); }} />
        <Pressable testID="ask-send-button" accessibilityRole="button" accessibilityLabel="Send message to Higgins" onPress={() => submit(text)} disabled={busy || !text.trim()} style={[s.send, { opacity: busy || !text.trim() ? 0.5 : 1 }]}>{busy ? <ActivityIndicator color={colors.onBrandPrimary} /> : <SendHorizontal size={20} color={colors.onBrandPrimary} />}</Pressable>
      </View>
    </KeyboardAvoidingView>

    <HigginsCheckSheet visible={checkSheetOpen} onClose={() => setCheckSheetOpen(false)} onSelect={handleCheckCategorySelect} />
    <HigginsArtifactInput visible={artifactSheetOpen} category={artifactCategory} initialQuestion={artifactQuestion || text} onClose={() => { setArtifactSheetOpen(false); setArtifactCategory(null); setArtifactQuestion(""); }} onSubmit={handleArtifactSubmit} />

    <Sheet visible={aboutOpen} onClose={() => setAboutOpen(false)} title="About Higgins" testID="higgins-about-sheet">
      <Image source={require("../../assets/images/higgins-apollo-portrait.png")} style={s.aboutAvatarImg} contentFit="contain" accessibilityLabel="Higgins with Apollo" />
      <Text style={s.sheetBody}>{WELCOME}{"\n\n"}{ABOUT}</Text>
    </Sheet>

    <Sheet visible={confirmClear} onClose={() => setConfirmClear(false)} title="Clear chat history?" testID="higgins-clear-sheet">
      <Text style={s.sheetBody}>This permanently deletes your conversation with Higgins on this device. This cannot be undone.</Text>
      <Button testID="higgins-clear-confirm" label="Delete chat history" onPress={() => { setConfirmClear(false); void clearChat(); }} />
      <Button testID="higgins-clear-cancel" variant="ghost" label="Cancel" onPress={() => setConfirmClear(false)} />
    </Sheet>
  </View>;
}
