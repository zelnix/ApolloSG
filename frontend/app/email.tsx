// Check Email — Approved screen implementation.
// Matches the approved mock-up: header, description, email card,
// gold Check email CTA, "or" divider, two action cards, recent emails section.
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import Check from "lucide-react-native/icons/check";
import ChevronDown from "lucide-react-native/icons/chevron-down";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import ChevronUp from "lucide-react-native/icons/chevron-up";
import Clock from "lucide-react-native/icons/clock";
import FileText from "lucide-react-native/icons/file-text";
import ImageIcon from "lucide-react-native/icons/image";
import Inbox from "lucide-react-native/icons/inbox";
import Mail from "lucide-react-native/icons/mail";
import Plus from "lucide-react-native/icons/plus";
import Search from "lucide-react-native/icons/search";
import Trash from "lucide-react-native/icons/trash";
import User from "lucide-react-native/icons/user";
import X from "lucide-react-native/icons/x";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { apiDelete, apiGet, apiPost } from "@/src/api/client";
import { CheckResultScreen } from "@/src/components/CheckResultScreen";
import { InvestigationCheckScreen } from "@/src/components/InvestigationCheckScreen";
import { RecoveryFlow } from "@/src/components/RecoveryFlow";
import { Sheet } from "@/src/components/Sheet";
import { Body, Button } from "@/src/components/ui";
import { type EmailAnalysis } from "@/src/domain/emailAnalysis";
import { type PatrolEvent } from "@/src/domain/types";
import { redactUserSecrets } from "@/src/domain/privacy";
import { connectGmailOAuth } from "@/src/domain/gmailConnect";
import { buildEmailCheckResult } from "@/src/domain/emailCheckResultAdapter";
import { contextFromEvent, gateForCategory } from "@/src/domain/higginsHandoff";
import { runProtectionHealthCheck } from "@/src/protection/healthCoordinator";
import { type EmailOutcome, type MessageUrlResult, useApollo } from "@/src/store/ApolloContext";
import { EMAIL_WORDS, upgradeSentence, type EmailEvidenceProfile, type EmailVia } from "@/src/domain/triage/emailEvidence";
import { looksLikeRawEmail } from "@/src/domain/triage/emailOriginal";
import { pickOriginalEmail, readEmailFile, readOriginal, readOriginalText, type OriginalEmail } from "@/src/store/originalEmail";
import { isOriginalEmailFile } from "@/src/share/classifyShare";
import type { EvidencePhoneResult } from "@/src/domain/phoneNumbers";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { CheckToolHeader } from "@/src/components/CheckToolHeader";
import { CheckingModal } from "@/src/components/CheckingModal";
import { cleanEmailForDisplay } from "@/src/domain/emailCleaner";
import { getShareIntake } from "@/src/share/shareIntake";
import { simulation } from "@/src/simulation";
import { SourceHero } from "@/src/components/SourceHero";
import { SourcePickerSheet } from "@/src/components/SourcePickerSheet";
import { recordCheck } from "@/src/store/checkHistoryStore";
import type { OfficialVerdict } from "@/src/domain/officialContacts";
import {
  listEmailAccounts,
  addEmailAccount,
  removeEmailAccount,
  providerLabel,
  type EmailAccount,
} from "@/src/store/emailAccountStore";
import {
  listEmailChecks,
  recordEmailCheck,
  type EmailCheckEntry,
} from "@/src/store/emailCheckHistoryStore";

// ── Constants ──────────────────────────────────────────────────────────────────
const GMAIL_STATUS_UI_TIMEOUT_MS = 8000;

// ── Styles ─────────────────────────────────────────────────────────────────────
const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },

  // Header
  header: { paddingHorizontal: spacing.lg, flexDirection: "row", alignItems: "center", gap: spacing.md },

  // Scroll
  scrollContent: { paddingHorizontal: spacing.lg, gap: spacing.lg },

  // Description
  description: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurfaceSecondary },

  // Email card
  emailCard: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.md, borderWidth: 0.25, borderColor: c.border },
  emailCardHeader: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  emailIconWell: { width: 44, height: 44, borderRadius: 22, backgroundColor: "#DBEAFE", alignItems: "center", justifyContent: "center" },
  emailCardLabel: { fontFamily: fonts.displayBold, fontSize: 17, color: c.onSurface },
  emailInput: { minHeight: 100, backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, fontFamily: fonts.text, fontSize: 16, color: c.onSurface, textAlignVertical: "top" },

  // Gold CTA
  goldBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: c.gold, borderRadius: radius.lg, paddingVertical: 16, paddingHorizontal: spacing.xl, gap: spacing.md, minHeight: 56 },
  goldBtnDisabled: { opacity: 0.45 },
  goldBtnText: { fontFamily: fonts.displayBold, fontSize: 17, color: c.onSurface },

  // Or divider
  orDivider: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.xs },
  orLine: { flex: 1, height: 1, backgroundColor: c.border },
  orText: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.muted },

  // Action cards row
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

  // ── Recent emails dropdown ──
  recentDropdown: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, borderWidth: 0.25, borderColor: c.border, overflow: "hidden" as const },
  recentDropdownToggle: { flexDirection: "row" as const, alignItems: "center" as const, gap: spacing.md, padding: spacing.lg },
  recentDropdownIconWell: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.surfaceTertiary, alignItems: "center" as const, justifyContent: "center" as const },
  recentDropdownTitle: { fontFamily: fonts.displayBold, fontSize: 15, color: c.onSurface, flex: 1 },
  recentDropdownSub: { fontFamily: fonts.text, fontSize: 13, color: c.onSurfaceSecondary, paddingHorizontal: spacing.lg, paddingBottom: spacing.sm },
  // Gmail M icon for action card
  gmailIconM: { fontFamily: fonts.displayBold, fontSize: 20, color: "#EA4335" },

  // Recent emails section
  recentSection: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, borderWidth: 0.25, borderColor: c.border, overflow: "hidden" },
  recentHeader: { paddingHorizontal: spacing.lg, paddingTop: spacing.lg, paddingBottom: spacing.md, gap: 4 },
  recentHeaderTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  recentTitleRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  recentClockWell: { width: 36, height: 36, borderRadius: 18, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  recentTitle: { fontFamily: fonts.displayBold, fontSize: 17, color: c.onSurface },
  seeAllRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  seeAllText: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.brand },
  recentSub: { fontFamily: fonts.text, fontSize: 14, color: c.onSurfaceSecondary, marginLeft: 48 },

  // Email row
  emailRow: { flexDirection: "row", alignItems: "center", paddingVertical: spacing.md, paddingHorizontal: spacing.lg, gap: spacing.md, borderTopWidth: 1, borderTopColor: c.border },
  // Simulated inbox (preview only) — deliberately marked so it can never read as a real mailbox.
  emailRowIconWell: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  emailRowUnknownWell: { backgroundColor: c.surfaceTertiary },
  emailRowContactWell: {},
  emailRowInitial: { fontFamily: fonts.displayBold, fontSize: 18, color: "#FFFFFF" },
  emailRowInfo: { flex: 1, gap: 2 },
  emailRowSender: { fontFamily: fonts.displayBold, fontSize: 16, color: c.onSurface },
  emailRowSubject: { fontFamily: fonts.text, fontSize: 14, color: c.onSurfaceSecondary },
  emailRowDate: { fontFamily: fonts.text, fontSize: 13, color: c.muted, flexShrink: 0 },

  // Account filter pill (inside recent section header)
  accountFilterRow: { flexDirection: "row", alignItems: "center", marginLeft: 48, gap: spacing.sm, marginTop: spacing.xs },
  accountPill: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill, borderWidth: 1, borderColor: c.border, backgroundColor: c.surface },
  accountPillText: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.onSurface },
  accountPillManage: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.brand },

  // Empty recent
  recentEmpty: { padding: spacing.xl, alignItems: "center", gap: spacing.sm },

  // Sheet rows (for account management)
  sheetRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.md },
  sheetIcon: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center", flexShrink: 0 },
  sheetInfo: { flex: 1, gap: 2 },
  sheetEmail: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.onSurface },
  sheetProvider: { fontFamily: fonts.text, fontSize: 13, color: c.muted },
  sheetCheck: { width: 24, height: 24, borderRadius: 12, backgroundColor: c.brand, alignItems: "center", justifyContent: "center" },
  editLabel: { fontFamily: fonts.textSemibold, fontSize: 12, letterSpacing: 1, color: c.muted, textTransform: "uppercase" },
  addInput: { minHeight: 48, backgroundColor: c.surfaceTertiary, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, paddingHorizontal: spacing.lg, fontFamily: fonts.text, fontSize: 15, color: c.onSurface },

  // Inbox picker modal (preserved)
  pickerOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  pickerSheet: { backgroundColor: c.surface, borderTopLeftRadius: radius.xl, borderTopRightRadius: radius.xl, maxHeight: "85%" },
  pickerHandle: { width: 40, height: 4, borderRadius: 2, backgroundColor: c.borderStrong, alignSelf: "center", marginTop: spacing.md },
  pickerHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  pickerTitle: { fontFamily: fonts.displayBold, fontSize: 20, color: c.onSurface },
  pickerAccountTabs: { paddingHorizontal: spacing.lg, paddingBottom: spacing.sm, gap: spacing.sm },
  pickerTab: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.pill, borderWidth: 1, borderColor: c.border, minHeight: 40, alignItems: "center", justifyContent: "center" },
  pickerTabText: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.onSurfaceSecondary },
  pickerCenter: { alignItems: "center", justifyContent: "center", paddingVertical: spacing["2xl"], gap: spacing.sm },
  pickerRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: c.border },
  pickerIconWrap: { width: 40, height: 40, borderRadius: 20, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center", flexShrink: 0 },
  pickerMsgContent: { flex: 1, gap: 2 },
  pickerSender: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface },
  pickerSubject: { fontFamily: fonts.text, fontSize: 14, color: c.onSurface },
  pickerSnippet: { fontFamily: fonts.text, fontSize: 13, lineHeight: 18, color: c.muted },
  pickerAccountLabel: { fontFamily: fonts.text, fontSize: 11, color: c.muted, marginTop: 2 },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: c.surfaceTertiary },
}));

// ── Component ──────────────────────────────────────────────────────────────────
export default function CheckEmail() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const params = useLocalSearchParams<{ text?: string; sharedIntakeId?: string; sample?: string }>();
  const shared = getShareIntake(params.sharedIntakeId);
  const sharedBody = shared?.text || shared?.webUrl || params.text || "";
  const sharedBodyRaw = useRef(sharedBody);         // original for backend
  // A shared original email file (.eml) — read on this device, never uploaded.
  const sharedEml = shared?.files?.find(isOriginalEmailFile) ?? null;
  const autoRan = useRef(false);
  /** The text in the box came from the connected mailbox (until the person edits it). */
  const fromInbox = useRef(false);
  /** When the email picked from the inbox arrived, as the mailbox recorded it. */
  const inboxDate = useRef<string | null>(null);
  const { ready, setupDone, checkEmail, deviceId, showToast, scanGmailInbox } = useApollo();

  // ── Input state ──
  const [fromState, setFrom] = useState("");
  const [subject, setSubject] = useState("");
  const [raw, setRaw] = useState(() => sharedBody ? cleanEmailForDisplay(sharedBody) : "");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{
    submissionId: string;
    a: EmailAnalysis;
    event: PatrolEvent;
    urls: MessageUrlResult[];
    /** Reputation for the telephone/mobile numbers the email itself contains. */
    phones: EvidencePhoneResult[];
    /** The Magnum DI case Apollo opened for this email — null when Triage found no possible threat. */
    caseId: string | null;
    /** Higgins Triage's classification of the evidence (L1–L4), with every earlier level. */
    profile: EmailEvidenceProfile;
    /** What just changed with the evidence: an upgrade, or an original that didn't match. */
    notice: string | null;
    /** The Official Organisation Directory's verdict on its contacts (null: the lookup didn't answer). */
    official?: OfficialVerdict[] | null;
    explanation: null;
    assessment: null;
  } | null>(null);
  const [verify, setVerify] = useState(false);
  const [upgrading, setUpgrading] = useState(false);

  // ── Account state ──
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null);
  const [accountSheetOpen, setAccountSheetOpen] = useState(false);
  const [manageSheetOpen, setManageSheetOpen] = useState(false);
  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [newAccountEmail, setNewAccountEmail] = useState("");

  // ── Recent checks ──
  const [, setRecentChecks] = useState<EmailCheckEntry[]>([]);

  // ── Gmail state (preserved) ──
  const [gmailConnected, setGmailConnected] = useState<boolean | null>(null);
  const [gmailConfigured, setGmailConfigured] = useState(true);
  const [gmailMonitoring, setGmailMonitoring] = useState(false);
  const [gmailAccounts, setGmailAccounts] = useState<{
    email: string;
    monitoring_enabled?: boolean;
    monitor_state?: string;
    monitor_last_success_at?: string | null;
  }[]>([]);
  const [gmailBusy, setGmailBusy] = useState(false);
  const [scanBusy, setScanBusy] = useState(false);

  // ── Inbox picker state (preserved) ──
  type InboxPreview = { id: string; account: string; from: string; subject: string; date: string; snippet: string };
  const [pickerVisible, setPickerVisible] = useState(false);
  const [emailSourcePicker, setEmailSourcePicker] = useState(false);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [pickerMessages, setPickerMessages] = useState<InboxPreview[]>([]);
  const [pickerAccount, setPickerAccount] = useState<string | null>(null);
  const [pickerFetchBusy, setPickerFetchBusy] = useState<string | null>(null);

  // ── Recent inbox emails (shown in the main screen) ──
  type InboxPreviewItem = { id: string; account: string; from: string; subject: string; date: string; snippet: string };
  const [recentInbox, setRecentInbox] = useState<InboxPreviewItem[]>([]);
  const [recentInboxLoading, setRecentInboxLoading] = useState(false);
  const [emailTextOpen, setEmailTextOpen] = useState(false);
  const [recentEmailsOpen, setRecentEmailsOpen] = useState(false);

  const loadRecentInbox = useCallback(async () => {
    if (!deviceId || !gmailConnected) return;
    setRecentInboxLoading(true);
    try {
      const data = await apiGet<{ messages: InboxPreviewItem[] }>(`/gmail/messages?device_id=${deviceId}&limit=5`);
      setRecentInbox(data.messages ?? []);
    } catch { /* unavailable */ }
    finally { setRecentInboxLoading(false); }
  }, [deviceId, gmailConnected]);

  useEffect(() => { if (gmailConnected) void loadRecentInbox(); }, [gmailConnected, loadRecentInbox]);

  // Shared into Apollo from another app (Share → Apollo, or an apollo://email deep link): check it
  // on arrival and show the email that is being checked, so the share always lands in a real check.
  useEffect(() => {
    if (!ready || !setupDone || autoRan.current) return;
    // Sample Check: real production email processing with sample_check provenance.
    if (params.sample) {
      const { findSampleEmail } = require("@/src/sampleChecks") as typeof import("@/src/sampleChecks");
      const sample = findSampleEmail(params.sample);
      if (sample) {
        autoRan.current = true;
        void run({ from: sample.from, subject: sample.subject, raw: `From: ${sample.from}\nSubject: ${sample.subject}\n\n${sample.body}`, via: "pasted", origin: "sample_check" });
        return;
      }
    }
    if (sharedEml) {
      autoRan.current = true;
      void (async () => {
        try {
          const uri = /^[a-z]+:\/\//i.test(sharedEml.path) ? sharedEml.path : `file://${sharedEml.path}`;
          const original = await readOriginal(await readEmailFile({ uri, size: sharedEml.size }));
          await run({ from: "", subject: "", raw: "", via: "eml_file", original });
        } catch (e) {
          showToast(e instanceof Error ? e.message : "ApolloSG couldn\u2019t read that email file.", "growling");
        }
      })();
      return;
    }
    if (!sharedBody.trim()) return;
    autoRan.current = true;
    setEmailTextOpen(true);
    // Send the ORIGINAL raw content to the backend for full analysis.
    void run({ from: "", subject: "", raw: sharedBodyRaw.current, via: "shared" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sharedBody, sharedEml?.path, ready, setupDone, params.sample]);

  // The simulated inbox exists only where the preview cannot reach a real mailbox, and never
  // alongside a connected one.
  // Preview only: never in a production build, and never when a real mailbox is connected.
  const showSimulatedInbox = simulation.included && gmailConnected !== true;

  // ── Derived ──
  const allAccounts = useMemo((): EmailAccount[] => {
    const manual = accounts;
    const gmailMapped: EmailAccount[] = gmailAccounts
      .filter((ga) => !manual.some((m) => m.email.toLowerCase() === ga.email.toLowerCase()))
      .map((ga) => ({
        id: `gmail-${ga.email}`,
        email: ga.email,
        provider: "gmail" as const,
        connected: true,
        addedAt: "",
      }));
    return [...manual, ...gmailMapped];
  }, [accounts, gmailAccounts]);

  const filteredPickerMessages = pickerAccount
    ? pickerMessages.filter((m) => m.account === pickerAccount)
    : pickerMessages;
  const uniquePickerAccounts = [...new Set(pickerMessages.map((m) => m.account).filter(Boolean))];

  // ── Data loading ──
  const refreshAccounts = useCallback(async () => {
    const accts = await listEmailAccounts();
    setAccounts(accts);
  }, []);

  const refreshRecentChecks = useCallback(async () => {
    const checks = await listEmailChecks();
    setRecentChecks(checks);
  }, []);

  useEffect(() => { void refreshAccounts(); void refreshRecentChecks(); }, [refreshAccounts, refreshRecentChecks]);

  // ── Gmail status (preserved) ──
  const refreshGmailStatus = useCallback(async () => {
    if (!deviceId) return;
    setGmailConnected(null);
    let timer: ReturnType<typeof setTimeout> | null = null;
    try {
      const timeout = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error("Gmail status took too long.")), GMAIL_STATUS_UI_TIMEOUT_MS);
      });
      const response = await Promise.race([
        apiGet<{
          connected: boolean;
          configured: boolean;
          monitoring_enabled: boolean;
          accounts?: { email: string; monitoring_enabled: boolean; monitor_state?: string; monitor_last_success_at?: string | null }[];
        }>(`/gmail/status?device_id=${deviceId}`),
        timeout,
      ]);
      setGmailConnected(response.connected);
      setGmailConfigured(response.configured);
      setGmailMonitoring(response.monitoring_enabled);
      setGmailAccounts(response.accounts ?? []);
      if (response.accounts) {
        for (const ga of response.accounts) void addEmailAccount(ga.email, true);
        void refreshAccounts();
      }
    } catch {
      setGmailConnected(false);
    } finally {
      if (timer) clearTimeout(timer);
    }
  }, [deviceId, refreshAccounts]);

  useEffect(() => { void refreshGmailStatus(); }, [refreshGmailStatus]);

  // ── Gmail handlers (preserved) ──
  const connectGmail = async () => {
    if (!deviceId) return;
    setGmailBusy(true);
    try {
      const res = await connectGmailOAuth(deviceId);
      if (res === "connected") {
        await refreshGmailStatus();
        void runProtectionHealthCheck("protection_change");
        showToast("Gmail account connected \u2014 read-only.", "resting");
      } else if (res === "denied") showToast("Gmail connection was cancelled.", "neutral");
      else if (res === "error") showToast("Couldn\u2019t connect Gmail right now.", "growling");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Couldn\u2019t connect Gmail right now.", "growling");
    } finally { setGmailBusy(false); }
  };

  const disconnectGmail = async (email?: string) => {
    if (!deviceId) return;
    const qs = email ? `?device_id=${deviceId}&email=${encodeURIComponent(email)}` : `?device_id=${deviceId}`;
    try { await apiDelete(`/gmail/connection${qs}`); } catch { /* already gone */ }
    void runProtectionHealthCheck("protection_change");
    showToast(email ? `${email} disconnected.` : "Gmail disconnected.", "neutral");
    await refreshGmailStatus();
    void refreshAccounts();
  };

  const toggleGmailMonitoring = async () => {
    if (!deviceId) return;
    const enabled = !gmailMonitoring;
    await apiPost("/gmail/monitoring", "gmail_monitor", { device_id: deviceId, enabled });
    setGmailMonitoring(enabled);
    void runProtectionHealthCheck("protection_change");
    showToast(enabled ? "Ongoing Gmail assessment enabled." : "Ongoing Gmail assessment stopped.", enabled ? "resting" : "neutral");
  };

  const scanInbox = async () => {
    setScanBusy(true);
    try {
      const result = await scanGmailInbox();
      const accepted = result.accepted;
      void runProtectionHealthCheck("protection_change");
      showToast(accepted ? `${accepted} email${accepted === 1 ? "" : "s"} accepted for investigation` : "No new Gmail messages needed investigation", "neutral");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Couldn\u2019t scan your inbox right now.", "growling");
    } finally { setScanBusy(false); }
  };

  // ── Inbox picker (preserved) ──
  const openInboxPicker = useCallback(async () => {
    if (!deviceId) return;
    setPickerVisible(true);
    setPickerLoading(true);
    setPickerMessages([]);
    try {
      const data = await apiGet<{ messages: InboxPreview[]; next_page_token?: string }>(`/gmail/messages?device_id=${deviceId}&limit=30`);
      setPickerMessages(data.messages ?? []);
    } catch {
      showToast("Couldn\u2019t load inbox messages.", "growling");
    } finally { setPickerLoading(false); }
  }, [deviceId, showToast]);

  const selectInboxEmail = useCallback(async (msg: InboxPreview) => {
    if (!deviceId) return;
    setPickerFetchBusy(msg.id);
    try {
      const detail = await apiGet<{ id: string; account: string; from: string; subject: string; date: string; body: string }>(
        `/gmail/message/${msg.id}?device_id=${deviceId}${msg.account ? `&email=${encodeURIComponent(msg.account)}` : ""}`
      );
      setFrom(detail.from || msg.from);
      setSubject(detail.subject || msg.subject);
      setRaw(detail.body || msg.snippet);
      fromInbox.current = true;
      inboxDate.current = detail.date || msg.date || null;
      setPickerVisible(false);
      // Auto-investigate the selected email
      const body = detail.body || msg.snippet;
      const sender = detail.from || msg.from;
      const subj = detail.subject || msg.subject;
      showToast("Email loaded \u2014 investigating\u2026", "neutral");
      // Trigger investigation with the loaded content
      setTimeout(() => {
        setRaw(body);
        setFrom(sender);
        setSubject(subj);
      }, 100);
    } catch {
      showToast("Couldn\u2019t fetch that email.", "growling");
    } finally { setPickerFetchBusy(null); }
  }, [deviceId, showToast]);

  // ── Account management ──
  const handleAddAccount = async () => {
    const email = newAccountEmail.trim();
    if (!email || !email.includes("@") || !email.includes(".")) {
      showToast("Enter a valid email address.", "neutral");
      return;
    }
    await addEmailAccount(email, false);
    setNewAccountEmail("");
    await refreshAccounts();
    showToast(`${email} added.`, "neutral");
  };

  const handleRemoveAccount = async (acct: EmailAccount) => {
    if (acct.connected && acct.provider === "gmail") {
      await disconnectGmail(acct.email);
    } else {
      await removeEmailAccount(acct.id);
      await refreshAccounts();
      showToast(`${acct.email} removed.`, "neutral");
    }
    if (selectedAccount?.toLowerCase() === acct.email.toLowerCase()) setSelectedAccount(null);
  };

  // ── Email check (core logic preserved) ──
  // `source` lets a selected email (e.g. one from the preview's simulated inbox) be checked straight
  // away without waiting for state to settle. The flow below is the ONE real email check: same
  // on-device analysis, same /message/analyse call (real Triage, and real Magnum DI where Triage
  // escalates), same event. There is no separate path for simulated input.
  const showOutcome = (outcome: EmailOutcome, meta: { sender: string; subject: string; account?: string; notice?: string | null }) => {
    const a = outcome.analysis;
    setResult({
      submissionId: outcome.submissionId, a, event: outcome.event, urls: outcome.urls, phones: outcome.phones,
      caseId: outcome.investigationCaseId, profile: outcome.profile, notice: meta.notice ?? null, explanation: null, assessment: null,
      official: outcome.official,
    });
    void recordEmailCheck({
      id: outcome.submissionId,
      at: new Date().toISOString(),
      state: a.state,
      summary: a.title,
      subject: meta.subject || undefined,
      sender: meta.sender || undefined,
      account: meta.account,
      eventId: outcome.event.event_id,
      scenario: a.scenario,
    });
    // An upgrade re-checks the same email in its case — it isn't a new check.
    if (!outcome.upgraded) void recordCheck("email", { at: new Date().toISOString(), state: a.state, summary: a.title });
    void refreshRecentChecks();
  };

  /** Check an original message (an .eml file or pasted original source), read on this device from its real headers.
   *  With `upgradeEventId` it is added to that email's case and re-triaged there. */
  const checkOriginal = async (original: OriginalEmail, via: EmailVia, upgradeEventId?: string) => {
    const outcome = await checkEmail({ from: "", subject: "", raw: "", via, original, upgradeEventId });
    const sender = outcome.analysis.parsed.fromAddress ?? "";
    const subj = outcome.analysis.parsed.subject ?? "";
    setFrom(sender);
    setSubject(subj);
    showOutcome(outcome, {
      sender, subject: subj, account: selectedAccount || undefined,
      notice: outcome.upgradeMismatch ? EMAIL_WORDS.upgradeMismatch : outcome.upgraded ? upgradeSentence(outcome.profile) : null,
    });
  };

  const run = async (source?: { from: string; subject: string; raw: string; via?: EmailVia; original?: OriginalEmail; simulated?: boolean }) => {
    setBusy(true);
    try {
      const rawInput = source?.raw ?? raw;
      const subjectInput = source?.subject ?? subject;
      const from = source?.from ?? fromState;
      const via: EmailVia = source?.via ?? (fromInbox.current ? "connected_mailbox" : "pasted");
      if (source?.original) { await checkOriginal(source.original, via); return; }
      // Pasted original source ("Show original") is read on this device from its real headers and parts.
      if (looksLikeRawEmail(rawInput.slice(0, 65536))) { await checkOriginal(await readOriginalText(rawInput), "raw_source"); return; }
      const safeRaw = redactUserSecrets(rawInput);
      const safeSubject = redactUserSecrets(subjectInput);
      if (safeRaw !== rawInput) setRaw(safeRaw); else if (source) setRaw(rawInput);
      if (safeSubject !== subjectInput) setSubject(safeSubject); else if (source) setSubject(subjectInput);
      if (source) setFrom(source.from);
      // ONE check → ONE patrol record → at most ONE Magnum DI case (opened only where Triage finds a
      // possible threat, and reused when this email correlates with something already investigated).
      const outcome = await checkEmail({
        from, subject: safeSubject, raw: safeRaw, via, simulated: source?.simulated,
        receivedAt: via === "connected_mailbox" && !source?.simulated ? inboxDate.current : null,
        captured: { from, subject: subjectInput, text: rawInput },
      });
      showOutcome(outcome, {
        sender: from.trim() || outcome.analysis.parsed.fromAddress || "",
        subject: safeSubject.trim() || outcome.analysis.parsed.subject || "",
        account: source?.simulated ? simulation.accountLabel : selectedAccount || undefined,
      });
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Couldn\u2019t read that email.", "barking");
    } finally { setBusy(false); }
  };

  /** "Open the original email (.eml)" on the input screen: the file is read on this device, never uploaded. */
  const openOriginal = async () => {
    try {
      const original = await pickOriginalEmail();
      if (original) await run({ from: "", subject: "", raw: "", via: "eml_file", original });
    } catch (e) {
      showToast(e instanceof Error ? e.message : "ApolloSG couldn\u2019t read that email file.", "growling");
    }
  };

  /** "Add the original email (.eml)" on the result: re-triages THIS email's case with the stronger evidence. */
  const addOriginal = async (eventId: string) => {
    try {
      const original = await pickOriginalEmail();
      if (!original) return;
      setUpgrading(true);
      await checkOriginal(original, "eml_file", eventId);
    } catch (e) {
      showToast(e instanceof Error ? e.message : "ApolloSG couldn\u2019t read that email file.", "growling");
    } finally { setUpgrading(false); }
  };

  // ── Navigation ──
  // ── Guards ──
  if (ready && !setupDone) return <Redirect href="/" />;
  const a = result?.a;
  const scent = result?.event?.scent_id ?? result?.event?.event_id ?? "";

  // ════════════════════════════════════════════════════════════════════════════
  // RESULT VIEW
  // ════════════════════════════════════════════════════════════════════════════
  if (result && a) {
    const model = buildEmailCheckResult({
      analysis: a,
      event: result.event,
      from: fromState,
      subject,
      submissionId: result.submissionId,
      urlResults: result.urls,
      phones: result.phones,
      explanation: result.explanation,
      profile: result.profile,
      official: result.official,
    });
    const askPrompt = `About the email I just checked (from ${model.subject}). ${model.headline} Can you walk me through what Apollo found and what I should do?`;
    const emailActions: { label: string; onPress: () => void; testID: string; variant?: "primary" | "secondary" | "ghost" }[] = [];
    if (a.handoff.account) {
      emailActions.push({
        testID: "email-check-account",
        variant: "secondary",
        label: "It\u2019s about my account \u2014 check account alert",
        onPress: () =>
          router.push({ pathname: "/account", params: { text: `${a.parsed.subject ?? ""}\n${a.parsed.body}`.trim().slice(0, 3000), scent } }),
      });
    }
    emailActions.push({
      testID: "email-verify-sender",
      variant: "secondary",
      label: "Show me how to check the sender",
      onPress: () => setVerify(true),
    });
    a.urls.forEach((u, i) => {
      const r = result.urls.find((x) => x.url === u || x.host === u.replace(/^https?:\/\//i, "").split("/")[0]);
      const off = a.lookalikeUrls.includes(u);
      const label =
        r?.verdict === "malicious"
          ? `\u26a0 ${u.length > 35 ? u.slice(0, 35) + "\u2026" : u}`
          : off
            ? `Off-domain: ${u.length > 30 ? u.slice(0, 30) + "\u2026" : u}`
            : `Check: ${u.length > 35 ? u.slice(0, 35) + "\u2026" : u}`;
      emailActions.push({
        testID: `email-check-link-${i}`,
        variant: r?.verdict === "malicious" || off ? "secondary" : "ghost",
        label,
        onPress: () =>
          router.push({ pathname: "/check", params: { url: u.startsWith("http") ? u : `https://${u}`, source: "email" } }),
      });
    });
    if (a.handoff.file) {
      emailActions.push({ testID: "email-check-file", variant: "secondary", label: "Check the attachment with ApolloSG", onPress: () => router.push({ pathname: "/file", params: { source: "email" } }) });
      emailActions.push({ testID: "email-attachment-limitation", variant: "ghost", label: "Note: the file itself was not transferred \u2014 only metadata is checked here", onPress: () => {} });
    }
    emailActions.push({
      testID: "email-again",
      variant: "ghost",
      label: "Check another email",
      onPress: () => {
        setResult(null);
        setRaw("");
        setFrom("");
        setSubject("");
        fromInbox.current = false;
        void refreshRecentChecks();
      },
    });
    const evidence = {
      onAddOriginal: () => void addOriginal(result.event.event_id),
      addingOriginal: upgrading,
      evidenceNotice: result.notice,
    };

    return (
      <>
        {result.caseId ? (
          <InvestigationCheckScreen
            key={result.event.event_id}
            result={model}
            investigationContext={contextFromEvent(result.event, gateForCategory(result.event.category))}
            investigationQuestion={askPrompt}
            submissionId={result.event.event_id}
            eventId={result.event.event_id}
            caseId={result.caseId}
            actions={emailActions}
            {...evidence}
          />
        ) : (
          <CheckResultScreen key={result.event.event_id} result={model} actions={emailActions} {...evidence} />
        )}
        <CheckingModal
          visible={upgrading}
          title="Checking the original email"
          subject={subject.trim() || undefined}
          description={"Higgins Triage is reading its full headers on this device\nand re-checking the email with them."}
        />
        {result.event ? (
          <RecoveryFlow
            event={result.event}
            kinds={["clicked", "password", "code", "money", "card", "info", "download"]}
            linkToCheck={a.urls[0] ?? null}
            testID="email-recovery"
          />
        ) : null}
        <Sheet visible={verify} onClose={() => setVerify(false)} title="Verify the sender safely" testID="email-verify-sheet">
          <Body testID="email-verify-text">{a.verifySender}</Body>
          <Button testID="email-verify-close" variant="ghost" label="Done" onPress={() => setVerify(false)} />
        </Sheet>
      </>
    );
  }

  // ════════════════════════════════════════════════════════════════════════════
  // INPUT VIEW — matches approved mockup
  // ════════════════════════════════════════════════════════════════════════════
  const hasContent = !!(raw.trim());

  // ── Helper: contact initial color ──
  const INITIAL_COLORS = ["#F97316", "#EF4444", "#6366F1", "#3B82F6", "#8B5CF6", "#EC4899", "#14B8A6", "#10B981"];
  const initialColor = (name: string) => INITIAL_COLORS[name.charCodeAt(0) % INITIAL_COLORS.length];

  // ── Helper: extract sender display name ──
  const senderDisplayName = (fromStr: string) => fromStr.replace(/<.*>/, "").trim() || fromStr;

  // ── Helper: is email address (no display name) ──
  const isEmailOnly = (fromStr: string) => /^[^<]*@[^>]*$/.test(fromStr.trim());

  // ── Helper: format date for inbox rows ──
  const formatEmailDate = (iso: string) => {
    try {
      const d = new Date(iso);
      const now = new Date();
      const isToday = d.toDateString() === now.toDateString();
      const yesterday = new Date(now);
      yesterday.setDate(yesterday.getDate() - 1);
      const isYesterday = d.toDateString() === yesterday.toDateString();
      if (isToday) return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", hour12: true });
      if (isYesterday) return "Yesterday";
      return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
    } catch { return ""; }
  };

  // ── Select a recent inbox email → auto-investigate ──
  const selectRecentInboxEmail = (msg: InboxPreviewItem) => {
    void selectInboxEmail(msg);
  };

  // ── Handle Gmail action card press ──

  return (
    <View style={s.root}>
      {/* ── Header ── */}
      <View style={[s.header, { paddingTop: insets.top + spacing.md }]}>
        <CheckToolHeader
          title="Check email"
          info={{
            title: "About email checking",
            body: [
              "Paste a forwarded email, paste its original source (\u201cShow original\u201d), or open the original email file (.eml). Apollo analyses the email for scam indicators, phishing patterns and suspicious links.",
              "With the original email, Higgins Triage also reads its full headers and the sender authentication (SPF, DKIM, DMARC) the receiving mail server recorded. ApolloSG reports those results as recorded and doesn\u2019t re-check them. The original is read and kept on this device \u2014 it isn\u2019t uploaded.",
              "A manual check works without connecting any email account. Account selection is for organising your checks across multiple email addresses.",
            ],
          }}
          testID="email"
        />
      </View>

      <KeyboardAwareScrollView
        testID="email-scroll"
        contentContainerStyle={[s.scrollContent, { paddingTop: spacing.md, paddingBottom: insets.bottom + 100 }]}
        bottomOffset={24}
      >
        <SourceHero
          testID="email-hero"
          title="Pick an email from your inbox"
          caption="Apollo reads the one email you choose and checks the sender, the links and what it is asking you to do."
          actions={[{
            testID: "email-pick-inbox",
            label: busy ? "Checking…" : "Choose an email",
            disabled: busy,
            icon: <Inbox size={20} color={colors.onBrandPrimary} />,
            onPress: () => { if (showSimulatedInbox) { setEmailSourcePicker(true); return; } void openInboxPicker(); },
          }]}
        />

        {/* ── Recent Emails Dropdown (above action cards) ── */}
        <View style={s.recentDropdown} testID="email-recent-section">
          <Pressable
            accessibilityRole="button"
            onPress={() => setRecentEmailsOpen((v) => !v)}
            style={s.recentDropdownToggle}
            testID="email-recent-toggle"
          >
            <View style={s.recentDropdownIconWell}>
              <Clock size={18} color={colors.onSurface} />
            </View>
            <Text style={s.recentDropdownTitle}>Select recent emails</Text>
            {recentEmailsOpen ? <ChevronUp size={18} color={colors.muted} /> : <ChevronDown size={18} color={colors.muted} />}
          </Pressable>

          {recentEmailsOpen ? <>
            <Text style={s.recentDropdownSub}>Tap an email to check it with ApolloSG.</Text>
            {/* Account filter pills */}
            {allAccounts.length > 1 ? (
              <View style={[s.accountFilterRow, { paddingHorizontal: spacing.lg }]}>
                <Pressable accessibilityRole="button" onPress={() => setAccountSheetOpen(true)} style={s.accountPill}>
                  <Text style={s.accountPillText} numberOfLines={1}>{selectedAccount ?? "All accounts"}</Text>
                  <ChevronDown size={14} color={colors.muted} />
                </Pressable>
                <Pressable accessibilityRole="button" onPress={() => setManageSheetOpen(true)} hitSlop={8}>
                  <Text style={s.accountPillManage}>Manage</Text>
                </Pressable>
              </View>
            ) : null}

            {/* Email rows */}
            {gmailConnected && recentInbox.length > 0 ? (
              recentInbox.slice(0, 5).map((msg, i) => {
                const name = senderDisplayName(msg.from);
                const emailOnly = isEmailOnly(msg.from);
                return (
                  <Pressable
                    key={`${msg.account}-${msg.id}`}
                    testID={`email-recent-${i}`}
                    accessibilityRole="button"
                    accessibilityLabel={`Check email from ${name}`}
                    onPress={() => selectRecentInboxEmail(msg)}
                    disabled={!!pickerFetchBusy}
                    style={({ pressed }) => [s.emailRow, { opacity: pressed ? 0.7 : 1 }]}
                  >
                    {pickerFetchBusy === msg.id ? (
                      <View style={[s.emailRowIconWell, s.emailRowUnknownWell]}>
                        <ActivityIndicator size="small" color={colors.brand} />
                      </View>
                    ) : emailOnly ? (
                      <View style={[s.emailRowIconWell, s.emailRowUnknownWell]}>
                        <User size={22} color={colors.muted} />
                      </View>
                    ) : (
                      <View style={[s.emailRowIconWell, s.emailRowContactWell, { backgroundColor: initialColor(name) }]}>
                        <Text style={s.emailRowInitial}>{name.charAt(0).toUpperCase()}</Text>
                      </View>
                    )}
                    <View style={s.emailRowInfo}>
                      <Text style={s.emailRowSender} numberOfLines={1}>{name}</Text>
                      <Text style={s.emailRowSubject} numberOfLines={1}>{msg.subject || "(no subject)"}</Text>
                    </View>
                    <Text style={s.emailRowDate}>{formatEmailDate(msg.date)}</Text>
                    <ChevronRight size={18} color={colors.muted} />
                  </Pressable>
                );
              })
            ) : recentInboxLoading ? (
              <View style={s.recentEmpty}>
                <ActivityIndicator size="small" color={colors.brand} />
                <Body>Loading recent emails\u2026</Body>
              </View>
            ) : gmailConnected ? (
              <View style={s.recentEmpty}>
                <Inbox size={28} color={colors.muted} />
                <Body>No recent emails found.</Body>
              </View>
            ) : (
              <View style={s.recentEmpty}>
                <Mail size={28} color={colors.muted} />
                <Body>{gmailConfigured ? "Connect Gmail to see your recent emails here." : "Paste or forward an email below to check it."}</Body>
                {gmailConfigured && !gmailConnected ? (
                  <Button testID="email-connect-inline" variant="ghost" label={gmailBusy ? "Opening Google\u2026" : "Connect Gmail"} onPress={() => void connectGmail()} disabled={gmailBusy || !deviceId} />
                ) : null}
              </View>
            )}

            {gmailConnected && recentInbox.length > 5 ? (
              <Pressable accessibilityRole="button" onPress={() => void openInboxPicker()} style={[s.emailRow, { justifyContent: "center" }]} hitSlop={8}>
                <Text style={s.seeAllText}>See all</Text>
                <ChevronRight size={16} color={colors.brand} />
              </Pressable>
            ) : null}
          </> : null}
        </View>

        {/* ── Action card ── */}
        <View style={s.actionCardsRow}>
          {/* Take a screenshot */}
          <Pressable
            testID="email-check-screenshot"
            accessibilityRole="button"
            accessibilityLabel="Take a screenshot"
            onPress={() => router.push({ pathname: "/message", params: { openScreenshot: "1", source: "email" } })}
            style={({ pressed }) => [s.actionCard, { opacity: pressed ? 0.85 : 1 }]}
          >
            <View style={s.actionCardHeader}>
              <View style={s.actionCardIconWell}><ImageIcon size={20} color={colors.onSurface} /></View>
              <Text style={s.actionCardTitle}>Take a screenshot</Text>
              <ChevronRight size={18} color={colors.muted} />
            </View>
            <Text style={s.actionCardSub}>Select an image from your device or take a new screenshot.</Text>
          </Pressable>
          {/* Open the original email (.eml) — read on this device, full headers included */}
          <Pressable
            testID="email-open-original"
            accessibilityRole="button"
            accessibilityLabel="Open the original email file"
            disabled={busy}
            onPress={() => void openOriginal()}
            style={({ pressed }) => [s.actionCard, { opacity: pressed ? 0.85 : 1 }]}
          >
            <View style={s.actionCardHeader}>
              <View style={s.actionCardIconWell}><FileText size={20} color={colors.onSurface} /></View>
              <Text style={s.actionCardTitle}>Open the original email (.eml)</Text>
              <ChevronRight size={18} color={colors.muted} />
            </View>
            <Text style={s.actionCardSub}>Lets Higgins Triage read the full headers and the sender authentication the receiving mail server recorded. Read on this device — the file isn&apos;t uploaded.</Text>
          </Pressable>
        </View>

        {/* ── Enter email text (expandable) ── */}
        <Pressable
          accessibilityRole="button"
          onPress={() => setEmailTextOpen((v) => !v)}
          style={s.expandLink}
          testID="email-expand-text"
        >
          <View style={s.emailIconWell}>
            <Mail size={22} color="#1D4ED8" />
          </View>
          <Text style={s.expandLinkText}>Enter email text</Text>
          {emailTextOpen ? <ChevronUp size={18} color={colors.muted} /> : <ChevronDown size={18} color={colors.muted} />}
        </Pressable>
        {emailTextOpen ? (
          <View style={s.emailCard} testID="email-card">
            <TextInput
              testID="email-body"
              style={s.emailInput}
              value={raw}
              onChangeText={(t) => { fromInbox.current = false; setRaw(t); }}
              placeholder="Paste the email (sender, subject, message) or its original source (“Show original”)"
              placeholderTextColor={colors.muted}
              multiline
              textAlignVertical="top"
              autoCapitalize="none"
              autoCorrect={false}
              dataDetectorTypes="none"
            />
          </View>
        ) : null}

        {/* ── Gold CTA: Check email ── */}
        <Pressable
          testID="email-run"
          accessibilityRole="button"
          accessibilityLabel="Check email"
          disabled={busy || !hasContent}
          onPress={() => void run()}
          style={({ pressed }) => [s.goldBtn, (busy || !hasContent) && s.goldBtnDisabled, { opacity: pressed && hasContent ? 0.85 : 1 }]}
        >
          <Search size={22} color={colors.onSurface} />
          <Text style={s.goldBtnText}>{"Check email"}</Text>
        </Pressable>
      </KeyboardAwareScrollView>

      {/* ══════════════════════════════════════════════════════════════════════
       *  SHEETS & MODALS
       * ══════════════════════════════════════════════════════════════════════ */}

      {/* ── Account Selector Sheet ── */}
      <Sheet visible={accountSheetOpen} onClose={() => setAccountSheetOpen(false)} title="Select email account" testID="email-account-sheet">
        <Pressable
          testID="email-account-all"
          accessibilityRole="button"
          onPress={() => { setSelectedAccount(null); setAccountSheetOpen(false); }}
          style={s.sheetRow}
        >
          <View style={s.sheetIcon}><Mail size={20} color={colors.brand} /></View>
          <View style={s.sheetInfo}>
            <Text style={s.sheetEmail}>All email accounts</Text>
            <Text style={s.sheetProvider}>Show checks from all accounts</Text>
          </View>
          {!selectedAccount ? (
            <View style={s.sheetCheck}><Check size={14} color={colors.onBrand} /></View>
          ) : null}
        </Pressable>
        {allAccounts.map((acct) => (
          <Pressable
            key={acct.id}
            testID={`email-account-${acct.email}`}
            accessibilityRole="button"
            onPress={() => { setSelectedAccount(acct.email); setAccountSheetOpen(false); }}
            style={s.sheetRow}
          >
            <View style={s.sheetIcon}><User size={20} color={colors.muted} /></View>
            <View style={s.sheetInfo}>
              <Text style={s.sheetEmail} numberOfLines={1}>{acct.email}</Text>
              <Text style={s.sheetProvider}>{providerLabel(acct.provider)}{acct.connected ? " \u00b7 Connected" : ""}</Text>
            </View>
            {selectedAccount?.toLowerCase() === acct.email.toLowerCase() ? (
              <View style={s.sheetCheck}><Check size={14} color={colors.onBrand} /></View>
            ) : null}
          </Pressable>
        ))}
        {allAccounts.length === 0 ? (
          <Body style={{ paddingVertical: spacing.md, textAlign: "center" }}>No accounts added yet. Tap Manage to add your email addresses.</Body>
        ) : null}
      </Sheet>

      {/* ── Manage Accounts Sheet ── */}
      <Sheet visible={manageSheetOpen} onClose={() => setManageSheetOpen(false)} title="Manage email accounts" testID="email-manage-sheet">
        <ScrollView style={{ maxHeight: 400 }} showsVerticalScrollIndicator={false}>
          {allAccounts.map((acct) => (
            <View key={acct.id} style={s.sheetRow}>
              <View style={s.sheetIcon}><User size={20} color={colors.muted} /></View>
              <View style={s.sheetInfo}>
                <Text style={s.sheetEmail} numberOfLines={1}>{acct.email}</Text>
                <Text style={s.sheetProvider}>{providerLabel(acct.provider)}{acct.connected ? " \u00b7 Connected" : " \u00b7 Manual"}</Text>
              </View>
              <Pressable testID={`email-remove-${acct.email}`} accessibilityRole="button" accessibilityLabel={`Remove ${acct.email}`} onPress={() => void handleRemoveAccount(acct)} hitSlop={8}>
                <Trash size={18} color={colors.error} />
              </Pressable>
            </View>
          ))}
          {allAccounts.length === 0 ? (
            <Body style={{ paddingVertical: spacing.md }}>No email accounts added. Add your email addresses below to organise and filter your checks.</Body>
          ) : null}
          <View style={{ gap: spacing.sm, paddingTop: spacing.lg }}>
            <Text style={s.editLabel}>Add email account</Text>
            <TextInput
              testID="email-add-input"
              style={s.addInput}
              value={newAccountEmail}
              onChangeText={setNewAccountEmail}
              placeholder="your@email.com"
              placeholderTextColor={colors.muted}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="email-address"
              returnKeyType="done"
              onSubmitEditing={() => void handleAddAccount()}
            />
            <Button testID="email-add-account" variant="secondary" icon={<Plus size={18} color={colors.brand} />} label="Add email account" onPress={() => void handleAddAccount()} disabled={!newAccountEmail.trim()} />
          </View>
          {gmailConfigured ? (
            <View style={{ gap: spacing.sm, paddingTop: spacing.lg }}>
              <Text style={s.editLabel}>Gmail integration</Text>
              {gmailConnected ? (
                <>
                  <Body>{gmailAccounts.length} Gmail {gmailAccounts.length === 1 ? "account" : "accounts"} connected (read-only).</Body>
                  <Button testID="email-gmail-scan" variant="secondary" label={scanBusy ? "Scanning\u2026" : "Scan recent Gmail"} icon={scanBusy ? <ActivityIndicator size="small" color={colors.brand} /> : undefined} onPress={() => void scanInbox()} disabled={scanBusy || gmailBusy} />
                  <Button testID="email-gmail-monitoring" variant="ghost" label={gmailMonitoring ? "Stop ongoing monitoring" : "Enable ongoing monitoring"} onPress={() => void toggleGmailMonitoring()} disabled={scanBusy || gmailBusy} />
                  <Button testID="email-gmail-connect-another" variant="ghost" icon={gmailBusy ? <ActivityIndicator size="small" color={colors.brand} /> : <Mail size={16} color={colors.brand} />} label={gmailBusy ? "Opening Google\u2026" : "Connect another Gmail"} onPress={() => void connectGmail()} disabled={gmailBusy} />
                </>
              ) : (
                <>
                  <Body style={{ fontSize: 13 }}>Connect Gmail for read-only access. ApolloSG never asks for or stores your Gmail password.</Body>
                  <Button testID="email-gmail-connect" variant="secondary" icon={gmailBusy ? <ActivityIndicator size="small" color={colors.brand} /> : <Mail size={18} color={colors.brand} />} label={gmailBusy ? "Opening Google\u2026" : "Connect Gmail (read-only)"} onPress={() => void connectGmail()} disabled={gmailBusy || !deviceId} />
                </>
              )}
            </View>
          ) : null}
        </ScrollView>
      </Sheet>

      {/* ── Inbox Picker Modal (preserved) ── */}
      <Modal visible={pickerVisible} transparent animationType="slide" onRequestClose={() => setPickerVisible(false)}>
        <View style={s.pickerOverlay}>
          <Pressable style={{ flex: 1 }} onPress={() => setPickerVisible(false)} accessibilityLabel="Close" />
          <View style={[s.pickerSheet, { paddingBottom: insets.bottom + spacing.md }]}>
            <View style={s.pickerHandle} />
            <View style={s.pickerHeader}>
              <Text style={s.pickerTitle}>Pick an email</Text>
              <Pressable accessibilityRole="button" accessibilityLabel="Close" onPress={() => setPickerVisible(false)} style={s.close}>
                <X size={20} color={colors.onSurface} />
              </Pressable>
            </View>
            {uniquePickerAccounts.length > 1 ? (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.pickerAccountTabs}>
                <Pressable accessibilityRole="button" onPress={() => setPickerAccount(null)} style={[s.pickerTab, !pickerAccount && { backgroundColor: colors.brand }]}>
                  <Text style={[s.pickerTabText, !pickerAccount && { color: colors.onBrand }]}>All accounts</Text>
                </Pressable>
                {uniquePickerAccounts.map((acct) => (
                  <Pressable key={acct} accessibilityRole="button" onPress={() => setPickerAccount(acct)} style={[s.pickerTab, pickerAccount === acct && { backgroundColor: colors.brand }]}>
                    <Text style={[s.pickerTabText, pickerAccount === acct && { color: colors.onBrand }]} numberOfLines={1}>{acct}</Text>
                  </Pressable>
                ))}
              </ScrollView>
            ) : null}
            {pickerLoading ? (
              <View style={s.pickerCenter}>
                <ActivityIndicator color={colors.brand} />
                <Body>Loading inbox\u2026</Body>
              </View>
            ) : filteredPickerMessages.length === 0 ? (
              <View style={s.pickerCenter}>
                <Inbox size={32} color={colors.muted} />
                <Body>No recent emails found.</Body>
              </View>
            ) : (
              <FlatList
                data={filteredPickerMessages}
                keyExtractor={(item) => `${item.account}-${item.id}`}
                contentContainerStyle={{ paddingHorizontal: spacing.lg }}
                renderItem={({ item }) => {
                  const isFetching = pickerFetchBusy === item.id;
                  const senderName = item.from.replace(/<.*>/, "").trim() || item.from;
                  return (
                    <Pressable accessibilityRole="button" testID={`inbox-msg-${item.id}`} onPress={() => void selectInboxEmail(item)} disabled={!!pickerFetchBusy} style={({ pressed }) => [s.pickerRow, { opacity: pressed ? 0.7 : 1 }]}>
                      <View style={s.pickerIconWrap}>
                        {isFetching ? <ActivityIndicator size="small" color={colors.brand} /> : <User size={20} color={colors.muted} />}
                      </View>
                      <View style={s.pickerMsgContent}>
                        <Text style={s.pickerSender} numberOfLines={1}>{senderName}</Text>
                        <Text style={s.pickerSubject} numberOfLines={1}>{item.subject || "(no subject)"}</Text>
                        <Text style={s.pickerSnippet} numberOfLines={2}>{item.snippet}</Text>
                        {uniquePickerAccounts.length > 1 && item.account ? (
                          <Text style={s.pickerAccountLabel}>{item.account}</Text>
                        ) : null}
                      </View>
                      <ChevronRight size={16} color={colors.muted} />
                    </Pressable>
                  );
                }}
              />
            )}
          </View>
        </View>
      </Modal>

      {/* ── Checking overlay modal ── */}
      <CheckingModal
        visible={busy}
        title="Checking email"
        subject={subject.trim() ? subject.trim() : fromState.trim() ? `From: ${fromState.trim()}` : undefined}
        description={"Higgins Triage and TC Hawkeye are checking\nheaders, sender reputation and content\nfor phishing patterns."}
      />
      <SourcePickerSheet
        visible={emailSourcePicker}
        title="Your inbox"
        note="Apollo runs the real email check on whichever one you pick — on-device analysis first, then TC Hawkeye, and Magnum DI only where a deeper look matters."
        preview
        items={simulation.emails.map((x) => ({ id: x.id, primary: x.subject, secondary: x.from, meta: x.probes }))}
        emptyText="There are no emails to choose from here."
        onSelect={(id) => {
          setEmailSourcePicker(false);
          const sim = simulation.emails.find((x) => x.id === id);
          if (sim) void run({ from: sim.from, subject: sim.subject, raw: sim.body, via: "connected_mailbox", simulated: true });
        }}
        onClose={() => setEmailSourcePicker(false)}
        testID="email-source-picker"
      />
    </View>
  );
}
