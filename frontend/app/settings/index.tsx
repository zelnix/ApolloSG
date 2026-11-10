import * as Linking from "expo-linking";
import * as DocumentPicker from "expo-document-picker";
import { useRouter } from "expo-router";
import Activity from "lucide-react-native/icons/activity";
import Bell from "lucide-react-native/icons/bell";
import ChevronLeft from "lucide-react-native/icons/chevron-left";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import FileText from "lucide-react-native/icons/file-text";
import LifeBuoy from "lucide-react-native/icons/life-buoy";
import Lock from "lucide-react-native/icons/lock";
import MessageSquare from "lucide-react-native/icons/message-square";
import Phone from "lucide-react-native/icons/phone";
import ShieldCheck from "lucide-react-native/icons/shield-check";
import Smartphone from "lucide-react-native/icons/smartphone";
import Trash from "lucide-react-native/icons/trash";
import Users from "lucide-react-native/icons/users";
import React, { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { ActivityIndicator, AppState, Platform, Pressable, ScrollView, Switch, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AlertPreviewSheet } from "@/src/components/AlertPreviewSheet";
import { AboutApolloSheet } from "@/src/components/AboutApolloSheet";
import { InfoButton, type ScreenInfo } from "@/src/components/InfoButton";
import { AppMenuButton } from "@/src/components/AppMenu";
import { RetrofitModal } from "@/src/components/RetrofitModal";
import { Sheet } from "@/src/components/Sheet";
import { TimeStepper } from "@/src/components/TimeStepper";
import { Body, Button, Card, Pill } from "@/src/components/ui";
import { APP_VERSION } from "@/src/config/buildInfo";
import { CANDIDATE_FILE } from "@/src/domain/slm/modelAdmission";
import { getOnDeviceAIDownloadState, subscribeOnDeviceAIDownload } from "@/src/domain/slm/downloadStatus";
import { getSLMActivitySnapshot, subscribeSLMActivity } from "@/src/domain/slm/sharedRuntime";
import { openPrivacyPolicy } from "@/src/config/privacyPolicy";
import { apiDelete, apiGet } from "@/src/api/client";
import { confirmDialog } from "@/src/utils/confirmDialog";
import { getDeviceIdentity } from "@/src/auth/deviceIdentity";
import { CallSdk } from "@/src/security/callSdk";
import { MessagingSdk } from "@/src/security/messagingSdk";
import type { NotificationStatus } from "@/src/push/notifications";
import { useApollo } from "@/src/store/ApolloContext";
import { setShowResultReasons, useShowResultReasons } from "@/src/store/resultReasonsStore";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { minimiseApp } from "@/src/utils/minimise";
import { goBackOrHome } from "@/src/utils/navigation";

const ALERT_LABEL: Record<NotificationStatus, string> = { granted: "Allowed", denied: "Not allowed", undetermined: "Not decided", blocked: "Blocked in Settings", unsupported: "Not available here" };
// The voluntary "Support Apollo" contribution card stays feature-gated until the approved copy and real
// public Stripe Payment Links exist. It never unlocks protection or creates a paid security tier.
const SHOW_CONTRIBUTION = false;
const SETTINGS_INFO: ScreenInfo = { title: "About Settings", body: [
  "Manage your protection, alerts, accounts, family, your own data and ApolloSG's privacy choices.",
  "The groups are ordered by what matters most day to day: protection and alerts first, then the people and accounts Apollo watches for you, then your data. App options and the policy documents sit at the bottom.",
  "Changes apply straight away on this device.",
] };

type IconComponent = React.ComponentType<{ size?: number; color?: string }>;
type GroupTone = "protection" | "alerts" | "accounts" | "data" | "app" | "diagnostics" | "help" | "policies";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  top: { paddingHorizontal: spacing.xl, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm, paddingBottom: spacing.md },
  title: { flexShrink: 1, fontFamily: fonts.displayBold, fontSize: 28, color: c.onSurface },
  content: { paddingHorizontal: spacing.xl, gap: spacing.xl, paddingBottom: spacing.xl },
  // ── Group heading: the app's gold uppercase section label, led by a small tinted icon chip ──
  groupHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.md },
  groupIcon: { width: 26, height: 26, borderRadius: 13, alignItems: "center", justifyContent: "center" },
  groupTitle: { flex: 1, fontFamily: fonts.displayBold, fontSize: 13, color: c.brand, letterSpacing: 1.4, textTransform: "uppercase" },
  rowItem: { flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 48, paddingVertical: spacing.sm },
  divider: { borderTopWidth: 1, borderTopColor: c.divider },
  rowLabel: { fontFamily: fonts.textMedium, fontSize: 16, color: c.onSurface },
  rowHint: { fontFamily: fonts.text, fontSize: 13, lineHeight: 18, color: c.muted, marginTop: 2 },
  trustRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: spacing.md, paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: c.divider },
  catRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 44, paddingVertical: spacing.xs, borderTopWidth: 1, borderTopColor: c.divider, opacity: 0.7 },
  footer: { fontFamily: fonts.text, fontSize: 12, color: c.muted, textAlign: "center" },
  // ── inline email account rows ──
  emailRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.md, borderTopWidth: 1, borderTopColor: c.divider },
  emailIconWell: { width: 36, height: 36, borderRadius: 18, backgroundColor: "#FEE2E2", alignItems: "center", justifyContent: "center" },
  emailGmailM: { fontFamily: fonts.displayBold, fontSize: 16, color: "#EA4335" },
  emailInfo: { flex: 1, gap: 1 },
  emailAddr: { fontFamily: fonts.textMedium, fontSize: 14, color: c.onSurface },
  emailMeta: { fontFamily: fonts.text, fontSize: 12, color: c.muted },
  emailRemoveBtn: { width: 40, height: 40, alignItems: "center", justifyContent: "center", borderRadius: 20, backgroundColor: c.surfaceTertiary },
  // ── call/message linking rows ──
  linkRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.md, borderTopWidth: 1, borderTopColor: c.divider },
  linkIconWell: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  linkInfo: { flex: 1, gap: 2 },
  linkTitle: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.onSurface },
  linkStatus: { fontFamily: fonts.text, fontSize: 12, lineHeight: 16, color: c.muted },
  linkReason: { fontFamily: fonts.text, fontSize: 12, lineHeight: 16, color: c.growlingText, marginTop: 2 },
  linkActionBtn: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.md, minHeight: 36, alignItems: "center", justifyContent: "center" },
}));

export default function SettingsScreen() {
  const s = useStyles(); const insets = useSafeAreaInsets(); const router = useRouter(); const { colors } = useTheme();
  const { trust, revokeTrust, clearPatrol, notificationStatus, enableNotifications, quietHours, quietNow, setQuietHours, lowPower, setLowPower, notificationPreferences, setNotificationPreferences, showToast } = useApollo();
  const [confirmClear, setConfirmClear] = useState(false); const [preview, setPreview] = useState(false);
  const [showTrust, setShowTrust] = useState(false); const [showShare, setShowShare] = useState(false); const [showAbout, setShowAbout] = useState(false);
  const [showRetrofit, setShowRetrofit] = useState(false);
  const showReasons = useShowResultReasons();
  const slmActivity = useSyncExternalStore(subscribeSLMActivity, getSLMActivitySnapshot, getSLMActivitySnapshot);
  const aiDownload = useSyncExternalStore(subscribeOnDeviceAIDownload, getOnDeviceAIDownloadState, getOnDeviceAIDownloadState);
  const aiDownloadActive = ["downloading", "verifying", "registering"].includes(aiDownload.phase);
  const [slmInstalling, setSlmInstalling] = useState(false);
  const slmTestAvailable = Platform.OS === "android" &&
    (__DEV__ || process.env.EXPO_PUBLIC_SLM_TEST_MODE === "true");
  const installSlmModel = useCallback(async () => {
    if (!slmTestAvailable || slmInstalling) return;
    setSlmInstalling(true);
    try {
      const selection = await DocumentPicker.getDocumentAsync({
        type: "application/octet-stream", copyToCacheDirectory: true, multiple: false,
      });
      if (selection.canceled || !selection.assets?.length) return;
      const selected = selection.assets[0];
      if (selected.name !== CANDIDATE_FILE) {
        showToast("Select the approved On-device AI package.", "growling");
        return;
      }
      const { installPrivateLuddishForTest } = await import("@/src/domain/slm/bootstrap");
      const installed = await installPrivateLuddishForTest(selected.uri);
      showToast(installed
        ? "Model verified and runtime registered. Local inference is not yet confirmed."
        : "Model installation failed. Check the file checksum, available memory and existing model.",
        installed ? "neutral" : "growling");
    } catch {
      showToast("Could not import the model from your device.", "growling");
    } finally {
      setSlmInstalling(false);
    }
  }, [slmTestAvailable, slmInstalling, showToast]);

  // ── Linked email accounts ──
  interface LinkedEmail { email: string; connected_at?: string }
  const [linkedEmails, setLinkedEmails] = useState<LinkedEmail[]>([]);
  const [emailsLoading, setEmailsLoading] = useState(true);
  const [emailBusy, setEmailBusy] = useState(false);

  const loadLinkedEmails = useCallback(async () => {
    try {
      const id = await getDeviceIdentity();
      if (!id?.deviceId) { setEmailsLoading(false); return; }
      const data = await apiGet<{ accounts?: LinkedEmail[]; connected?: boolean }>(`/gmail/status?device_id=${id.deviceId}`);
      setLinkedEmails(data.accounts ?? (data.connected ? [{ email: "Connected account" }] : []));
    } catch { setLinkedEmails([]); }
    finally { setEmailsLoading(false); }
  }, []);

  useEffect(() => { void loadLinkedEmails(); }, [loadLinkedEmails]);

  const removeEmail = useCallback((email: string) => {
    confirmDialog(
      "Remove email account?",
      `ApolloSG will lose read-only access to ${email}. You can reconnect at any time from Email accounts.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Remove",
          style: "destructive",
          onPress: async () => {
            setEmailBusy(true);
            try {
              const id = await getDeviceIdentity();
              if (!id?.deviceId) return;
              const qs = email !== "Connected account"
                ? `?device_id=${id.deviceId}&email=${encodeURIComponent(email)}`
                : `?device_id=${id.deviceId}`;
              await apiDelete(`/gmail/connection${qs}`);
              showToast("Email account removed.");
              await loadLinkedEmails();
            } catch {
              showToast("Could not remove the account. Please try again.");
            } finally {
              setEmailBusy(false);
            }
          },
        },
      ],
    );
  }, [loadLinkedEmails, showToast]);

  // ── Call & message linking ──
  type LinkState = "linked" | "not_linked" | "unavailable" | "loading";
  const [callState, setCallState] = useState<LinkState>("loading");
  const [msgState, setMsgState] = useState<LinkState>("loading");
  const [callReason, setCallReason] = useState<string | null>(null);
  const [msgReason, setMsgReason] = useState<string | null>(null);
  const [linkBusy, setLinkBusy] = useState(false);

  const readLinkStates = useCallback(async () => {
    // ── Call screening ──
    if (Platform.OS === "android" || Platform.OS === "ios") {
      try {
        const caps = await CallSdk.getCallProtectionCapabilities();
        if (caps.callScreening === "supported") setCallState("linked");
        else if (caps.callScreening === "permission_required") { setCallState("not_linked"); setCallReason(null); }
        else { setCallState("unavailable"); setCallReason(Platform.OS === "ios" ? "Call Blocking & Identification is managed in iPhone Settings > Phone." : "Call screening is not supported on this device."); }
      } catch { setCallState("unavailable"); setCallReason("Apollo could not read call screening status."); }
    } else {
      setCallState("unavailable");
      setCallReason("Call screening requires a phone. It is not available in this preview.");
    }

    // ── Message screening ──
    if (Platform.OS === "android") {
      try {
        const caps = await MessagingSdk.getMessagingCapabilities();
        if (caps.smsFiltering === "supported") setMsgState("linked");
        else if (caps.smsFiltering === "permission_required") { setMsgState("not_linked"); setMsgReason(null); }
        else { setMsgState("unavailable"); setMsgReason("Message screening is not supported on this device."); }
      } catch { setMsgState("unavailable"); setMsgReason("Apollo could not read message screening status."); }
    } else if (Platform.OS === "ios") {
      setMsgState("unavailable");
      setMsgReason("Apple does not let apps read message notifications. You can share or paste a message into Apollo instead.");
    } else {
      setMsgState("unavailable");
      setMsgReason("Message screening requires a phone. It is not available in this preview.");
    }
  }, []);

  useEffect(() => { void readLinkStates(); }, [readLinkStates]);

  // Re-read after returning from system settings
  useEffect(() => {
    const sub = AppState.addEventListener("change", (st) => { if (st === "active") void readLinkStates(); });
    return () => sub.remove();
  }, [readLinkStates]);

  const linkCalls = useCallback(async () => {
    setLinkBusy(true);
    try {
      if (Platform.OS === "ios") {
        await Linking.openSettings();
        showToast("Open Phone > Call Blocking & Identification and enable ApolloSG.", "neutral");
      } else {
        const r = await CallSdk.requestCallScreeningRole();
        if (r.held) { showToast("Call screening linked.", "resting"); }
        else { showToast("Open the prompt and choose ApolloSG for call screening.", "neutral"); }
      }
      // State will re-read on foreground return
    } catch { showToast("Could not open call screening settings.", "growling"); }
    finally { setLinkBusy(false); }
  }, [showToast]);

  const unlinkCalls = useCallback(() => {
    confirmDialog(
      "Unlink call screening?",
      Platform.OS === "ios"
        ? "To stop ApolloSG screening calls, open iPhone Settings > Phone > Call Blocking & Identification and turn off ApolloSG."
        : "To stop ApolloSG screening calls, choose a different caller ID & spam app in your phone's settings.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Open Settings",
          onPress: () => {
            if (Platform.OS === "ios") void Linking.openSettings();
            else void CallSdk.requestCallScreeningRole();
          },
        },
      ],
    );
  }, []);

  const linkMessages = useCallback(async () => {
    setLinkBusy(true);
    try {
      await MessagingSdk.openSmsListenerSettings();
      showToast("Enable notification access for ApolloSG.", "neutral");
    } catch { showToast("Could not open notification access settings.", "growling"); }
    finally { setLinkBusy(false); }
  }, [showToast]);

  const unlinkMessages = useCallback(() => {
    confirmDialog(
      "Unlink message screening?",
      "To stop ApolloSG reading message notifications, open Settings > Apps > Special access > Notification access and turn off ApolloSG.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Open Settings",
          onPress: () => { void MessagingSdk.openSmsListenerSettings(); },
        },
      ],
    );
  }, []);

  // Each group carries its own colour so the list is scannable at a glance. These are navigational
  // category colours (see theme.ts) — never Apollo's security-state colours.
  const TONE: Record<GroupTone, { fg: string; bg: string }> = {
    protection: { fg: colors.groupProtection, bg: colors.groupProtectionTint },
    alerts: { fg: colors.groupAlerts, bg: colors.groupAlertsTint },
    accounts: { fg: colors.groupAccounts, bg: colors.groupAccountsTint },
    data: { fg: colors.groupData, bg: colors.groupDataTint },
    app: { fg: colors.groupApp, bg: colors.groupAppTint },
    diagnostics: { fg: colors.groupDiagnostics, bg: colors.groupDiagnosticsTint },
    help: { fg: colors.groupHelp, bg: colors.groupHelpTint },
    policies: { fg: colors.groupPolicies, bg: colors.groupPoliciesTint },
  };
  const Group = ({ icon: Icon, title, tone, testID, children }: { icon: IconComponent; title: string; tone: GroupTone; testID: string; children: React.ReactNode }) => (
    <View testID={testID}>
      <View style={s.groupHead}>
        <View style={[s.groupIcon, { backgroundColor: TONE[tone].bg }]}><Icon size={15} color={TONE[tone].fg} /></View>
        <Text style={s.groupTitle}>{title}</Text>
      </View>
      <Card testID={`${testID}-card`}>{children}</Card>
    </View>
  );
  const NavRow = ({ label, hint, onPress, testID, first }: { label: string; hint?: string; onPress: () => void; testID: string; first?: boolean }) => (
    <Pressable testID={testID} accessibilityRole="button" accessibilityLabel={label} onPress={onPress} style={[s.rowItem, !first && s.divider]}>
      <View style={{ flex: 1 }}><Text style={s.rowLabel}>{label}</Text>{hint ? <Text style={s.rowHint}>{hint}</Text> : null}</View>
      <ChevronRight size={20} color={colors.muted} />
    </Pressable>
  );
  const SwitchRow = ({ label, hint, value, onValueChange, testID, first }: { label: string; hint?: string; value: boolean; onValueChange: (v: boolean) => void; testID: string; first?: boolean }) => (
    <View style={[s.rowItem, !first && s.divider]}>
      <View style={{ flex: 1 }}><Text style={s.rowLabel}>{label}</Text>{hint ? <Text style={s.rowHint} numberOfLines={1}>{hint}</Text> : null}</View>
      <Switch testID={testID} value={value} onValueChange={onValueChange} trackColor={{ true: colors.resting, false: colors.borderStrong }} thumbColor={colors.onSurface} />
    </View>
  );

  return <View style={s.root} testID="settings-screen">
    <View style={[s.top, { paddingTop: insets.top + spacing.md }]}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Back"
        testID="settings-back"
        onPress={() => goBackOrHome(router)}
        style={{ width: 44, height: 44, alignItems: "center", justifyContent: "center", marginLeft: -spacing.sm }}
      >
        <ChevronLeft size={24} color={colors.onSurface} />
      </Pressable>
      <Text style={[s.title, { flex: 1 }]} testID="settings-title">Settings</Text>
      <InfoButton info={SETTINGS_INFO} testID="settings-info" />
      <AppMenuButton testID="settings-menu" />
    </View>
    <ScrollView contentContainerStyle={[s.content, { paddingBottom: insets.bottom + spacing.xl }]} testID="settings-scroll">

      {/* 1 ── What is protecting you */}
      <Group icon={ShieldCheck} title="Protection" tone="protection" testID="settings-protection">
        <NavRow first label="View all protections" hint="Every Apollo protection, its status, coverage and setup" onPress={() => router.push("/gates")} testID="settings-view-gates" />

        {/* ── Call screening link ── */}
        <View style={s.linkRow} testID="settings-call-link">
          <View style={[s.linkIconWell, { backgroundColor: callState === "linked" ? colors.restingTint : callState === "unavailable" ? colors.surfaceTertiary : colors.growlingTint }]}>
            <Phone size={18} color={callState === "linked" ? colors.resting : callState === "unavailable" ? colors.muted : colors.growlingText} />
          </View>
          <View style={s.linkInfo}>
            <Text style={s.linkTitle}>Call screening</Text>
            <Text style={s.linkStatus}>
              {callState === "loading" ? "Checking…" : callState === "linked" ? "Linked — ApolloSG screens incoming calls" : callState === "not_linked" ? "Not linked" : "Not available"}
            </Text>
            {callState === "unavailable" && callReason ? <Text style={s.linkReason}>{callReason}</Text> : null}
          </View>
          {callState === "loading" ? <ActivityIndicator size="small" color={colors.brand} /> : null}
          {callState === "not_linked" ? (
            <Pressable testID="settings-call-link-btn" accessibilityRole="button" accessibilityLabel="Link call screening" onPress={() => void linkCalls()} disabled={linkBusy} style={({ pressed }) => [s.linkActionBtn, { backgroundColor: colors.brandPrimary, opacity: pressed ? 0.7 : 1 }]}>
              <Text style={{ fontFamily: fonts.textSemibold, fontSize: 13, color: colors.onBrandPrimary }}>Link</Text>
            </Pressable>
          ) : null}
          {callState === "linked" ? (
            <Pressable testID="settings-call-unlink-btn" accessibilityRole="button" accessibilityLabel="Unlink call screening" onPress={unlinkCalls} style={({ pressed }) => [s.linkActionBtn, { backgroundColor: colors.surfaceTertiary, opacity: pressed ? 0.7 : 1 }]}>
              <Text style={{ fontFamily: fonts.textSemibold, fontSize: 13, color: colors.onSurface }}>Unlink</Text>
            </Pressable>
          ) : null}
        </View>

        {/* ── Message screening link ── */}
        <View style={s.linkRow} testID="settings-msg-link">
          <View style={[s.linkIconWell, { backgroundColor: msgState === "linked" ? colors.restingTint : msgState === "unavailable" ? colors.surfaceTertiary : colors.growlingTint }]}>
            <MessageSquare size={18} color={msgState === "linked" ? colors.resting : msgState === "unavailable" ? colors.muted : colors.growlingText} />
          </View>
          <View style={s.linkInfo}>
            <Text style={s.linkTitle}>Message screening</Text>
            <Text style={s.linkStatus}>
              {msgState === "loading" ? "Checking…" : msgState === "linked" ? "Linked — ApolloSG watches message notifications" : msgState === "not_linked" ? "Not linked" : "Not available"}
            </Text>
            {msgState === "unavailable" && msgReason ? <Text style={s.linkReason}>{msgReason}</Text> : null}
          </View>
          {msgState === "loading" ? <ActivityIndicator size="small" color={colors.brand} /> : null}
          {msgState === "not_linked" ? (
            <Pressable testID="settings-msg-link-btn" accessibilityRole="button" accessibilityLabel="Link message screening" onPress={() => void linkMessages()} disabled={linkBusy} style={({ pressed }) => [s.linkActionBtn, { backgroundColor: colors.brandPrimary, opacity: pressed ? 0.7 : 1 }]}>
              <Text style={{ fontFamily: fonts.textSemibold, fontSize: 13, color: colors.onBrandPrimary }}>Link</Text>
            </Pressable>
          ) : null}
          {msgState === "linked" ? (
            <Pressable testID="settings-msg-unlink-btn" accessibilityRole="button" accessibilityLabel="Unlink message screening" onPress={unlinkMessages} style={({ pressed }) => [s.linkActionBtn, { backgroundColor: colors.surfaceTertiary, opacity: pressed ? 0.7 : 1 }]}>
              <Text style={{ fontFamily: fonts.textSemibold, fontSize: 13, color: colors.onSurface }}>Unlink</Text>
            </Pressable>
          ) : null}
        </View>
      </Group>

      {/* 2 ── How Apollo reaches you */}
      <Group icon={Bell} title="Alerts" tone="alerts" testID="settings-alerts-group">
        <View style={s.rowItem}>
          <View style={{ flex: 1, gap: spacing.xs }}>
            <Text style={s.rowLabel}>Important security alerts</Text>
            <Pill tone={notificationStatus === "granted" ? "resting" : notificationStatus === "unsupported" ? "unknown" : "growling"} label={ALERT_LABEL[notificationStatus]} testID="settings-push-status" />
            <Text style={s.rowHint}>Permission alone does not prove an alert was delivered.</Text>
          </View>
        </View>
        {notificationStatus === "denied" || notificationStatus === "undetermined" ? <Button testID="settings-push-enable" variant="secondary" label="Allow security alerts" onPress={() => void enableNotifications()} /> : null}
        {notificationStatus === "blocked" ? <Button testID="settings-push-settings" variant="secondary" label="Open notification settings" onPress={() => void Linking.openSettings()} /> : null}
        <NavRow label="Notification check" hint="See whether alerts can reach this device, and send a test alert" onPress={() => router.push("/notification-check")} testID="settings-notification-check" />
        <View style={[s.rowItem, s.divider]}><View style={{ flex: 1 }}><Text style={s.rowLabel}>Preview an alert</Text><Text style={s.rowHint}>See exactly how an alert looks on this device</Text></View><Button testID="settings-alert-preview" variant="ghost" label="Preview" onPress={() => setPreview(true)} /></View>
        <SwitchRow label="Quiet hours" hint="Hold gentle alerts until the morning, then show each one. Urgent threat and family alerts still come through at once." value={quietHours.enabled} onValueChange={(value) => void setQuietHours({ ...quietHours, enabled: value })} testID="settings-quiet-switch" />
        {quietHours.enabled ? <View style={{ gap: spacing.sm, paddingBottom: spacing.sm }}><View style={{ flexDirection: "row", gap: spacing.md }}><TimeStepper testID="settings-quiet-start" label="From" minutes={quietHours.start_minutes} onChange={(minutes) => void setQuietHours({ ...quietHours, start_minutes: minutes })} /><TimeStepper testID="settings-quiet-end" label="Until" minutes={quietHours.end_minutes} onChange={(minutes) => void setQuietHours({ ...quietHours, end_minutes: minutes })} /></View><Pill tone={quietNow ? "unknown" : "resting"} label={quietNow ? "Quiet hours are active" : "Quiet hours are not active now"} testID="settings-quiet-now" /></View> : null}

        {/* Notification categories */}
        <View style={[s.rowItem, s.divider]}>
          <View style={{ flex: 1 }}>
            <Text style={s.rowLabel}>Notification categories</Text>
            <Text style={s.rowHint}>Choose which types of alerts ApolloSG sends you. Critical alerts cannot be turned off.</Text>
          </View>
        </View>
        {/* Always-on categories */}
        <View style={s.catRow}>
          <View style={{ flex: 1 }}>
            <Text style={s.rowLabel}>Barking</Text>
            <Text style={s.rowHint} numberOfLines={1}>Active threats needing immediate attention</Text>
          </View>
          <Pill tone="barking" label="Always on" testID="settings-cat-barking" />
        </View>
        <View style={s.catRow}>
          <View style={{ flex: 1 }}>
            <Text style={s.rowLabel}>Biting</Text>
            <Text style={s.rowHint} numberOfLines={1}>Confirmed protective blocks Apollo enforced</Text>
          </View>
          <Pill tone="barking" label="Always on" testID="settings-cat-biting" />
        </View>
        {/* Configurable categories */}
        <SwitchRow label="Sniffing &amp; Growling" hint="Cases with a link straight to the investigation" value={notificationPreferences.sniffing_growling} onValueChange={(v) => void setNotificationPreferences({ sniffing_growling: v })} testID="settings-cat-sniffing-growling" />
        <SwitchRow label="New Scam Alerts" hint="New advisories from official sources" value={notificationPreferences.scam_alerts} onValueChange={(v) => void setNotificationPreferences({ scam_alerts: v })} testID="settings-cat-scam-alerts" />
        <SwitchRow label="Learn with Higgins" hint="New learning content from Higgins" value={notificationPreferences.learn_with_higgins} onValueChange={(v) => void setNotificationPreferences({ learn_with_higgins: v })} testID="settings-cat-learn-higgins" />
      </Group>

      {/* 3 ── The accounts and people Apollo watches for you */}
      <Group icon={Users} title="Accounts &amp; family" tone="accounts" testID="settings-accounts">
        <NavRow first label="Email accounts" hint="Connect or disconnect Gmail accounts for email checking" onPress={() => router.push("/settings/email-accounts")} testID="settings-email-accounts" />
        {/* Inline connected accounts with remove */}
        {emailsLoading ? (
          <View style={[s.emailRow, { justifyContent: "center" }]} testID="settings-emails-loading">
            <ActivityIndicator size="small" color={colors.brand} />
          </View>
        ) : linkedEmails.length > 0 ? (
          linkedEmails.map((acct, i) => (
            <View key={acct.email} style={s.emailRow} testID={`settings-linked-email-${i}`}>
              <View style={s.emailIconWell}>
                <Text style={s.emailGmailM}>M</Text>
              </View>
              <View style={s.emailInfo}>
                <Text style={s.emailAddr} numberOfLines={1}>{acct.email}</Text>
                <Text style={s.emailMeta}>
                  {"Gmail · Read-only"}
                  {acct.connected_at ? ` · ${new Date(acct.connected_at).toLocaleDateString()}` : ""}
                </Text>
              </View>
              <Pressable
                testID={`settings-remove-email-${i}`}
                accessibilityRole="button"
                accessibilityLabel={`Remove ${acct.email}`}
                onPress={() => removeEmail(acct.email)}
                disabled={emailBusy}
                style={({ pressed }) => [s.emailRemoveBtn, { opacity: pressed ? 0.6 : 1 }]}
              >
                {emailBusy ? <ActivityIndicator size="small" color={colors.error} /> : <Trash size={16} color={colors.error} />}
              </Pressable>
            </View>
          ))
        ) : null}
        <NavRow label="Family sharing" hint="Choose a trusted person for alerts you deliberately share" onPress={() => router.push("/family")} testID="settings-family" />
        <Pressable testID="settings-trust" accessibilityRole="button" accessibilityLabel="Trusted links" onPress={() => setShowTrust((v) => !v)} style={[s.rowItem, s.divider]}>
          <View style={{ flex: 1 }}><Text style={s.rowLabel}>Trusted links</Text><Text style={s.rowHint}>Trust applies to one exact link and never overrides a confirmed threat.</Text></View>
          <Pill tone="neutral" label={String(trust.length)} testID="settings-trust-count" /><ChevronRight size={20} color={colors.muted} />
        </Pressable>
        {showTrust ? (trust.length === 0 ? <Body testID="settings-trust-empty" style={{ paddingTop: spacing.sm }}>No trusted links.</Body> : trust.map((entry) => <View key={entry.trust_id} style={s.trustRow} testID={`settings-trust-${entry.trust_id}`}><View style={{ flex: 1 }}><Text style={s.rowLabel}>{entry.indicator_host}</Text><Body>Exact link · {new Date(entry.created_at).toLocaleDateString()}</Body></View><Button testID={`settings-revoke-${entry.trust_id}`} variant="secondary" label="Remove" onPress={() => revokeTrust(entry)} /></View>)) : null}
      </Group>

      {/* 4 ── The person's own data */}
      <Group icon={Lock} title="Your data" tone="data" testID="settings-privacy">
        <NavRow first label="My personal data" hint="Add your names, numbers, emails and addresses so Apollo can protect them" onPress={() => router.push("/settings/personal-data")} testID="settings-personal-data" />
        <NavRow label="What ApolloSG stores" hint="See everything ApolloSG holds and delete all your data" onPress={() => router.push("/privacy-data")} testID="settings-privacy-data" />
        <NavRow label="Clear Patrol history" hint="Hide local summaries and ask the service to hide synced ones" onPress={() => setConfirmClear(true)} testID="settings-clear-patrol" />
      </Group>

      {/* 5 ── This app on this device */}
      <Group icon={Smartphone} title="App" tone="app" testID="settings-preferences">
        <SwitchRow first label="Battery saver" hint="Reduces animation and checks status less often. It does not change the protection status." value={lowPower} onValueChange={(value) => void setLowPower(value)} testID="settings-lowpower-switch" />
        <SwitchRow label="Show why each result was settled" hint="One line naming what settled it" value={showReasons} onValueChange={(value) => void setShowResultReasons(value)} testID="settings-result-reasons-switch" />
        <View testID="settings-slm-info" style={[s.rowItem, s.divider, { alignItems: "flex-start" }]}>
          <View style={{ flex: 1, gap: spacing.xs }}>
            <Text style={s.rowLabel}>On-device AI</Text>
            <Text style={s.rowHint}>Engine: On-device AI (local, optional)</Text>
            <Text style={s.rowHint}>On-device AI version: ODAI-Q2.5-0.5B-Q4KM-v1</Text>
            <Text style={s.rowHint}>AI package: verified local installation</Text>
            <Text style={s.rowHint} testID="settings-slm-status">Status: {aiDownloadActive ? "Setup in progress" : !slmTestAvailable ? "Disabled in this build" : slmActivity.lastSuccessfulInferenceAt ? "Active — local inference confirmed" : slmActivity.registered ? "Runtime registered — inference not yet confirmed" : "Inactive — no runtime registered"}</Text>
            <Text style={s.rowHint}>Loaded model: {slmActivity.modelId ?? "None confirmed"}</Text>
            <Text style={s.rowHint}>Last verified local inference: {slmActivity.lastSuccessfulInferenceAt ? new Date(slmActivity.lastSuccessfulInferenceAt).toLocaleString() : "Never in this app session"}</Text>
            <Text style={s.rowHint}>Activity is confirmed only after a native model response passes the On-device AI output contract. This does not establish that Higgins displayed the model's wording. No background inference test is performed.</Text>
          </View>
        </View>
        {slmTestAvailable && !slmActivity.registered ? (
          <Pressable testID="settings-download-slm" accessibilityRole="button"
            accessibilityLabel="Download and install On-device AI model"
            disabled={slmInstalling || aiDownloadActive}
            onPress={() => {
              if (aiDownloadActive) return;
              confirmDialog("Download On-device AI model?",
                "Download approximately 491 MB from the official AI package source and verify it on this device? Mobile data charges may apply.",
                [{ text: "Cancel", style: "cancel" }, { text: "Download & Install", onPress: () => {
                  setSlmInstalling(true);
                  void import("@/src/domain/slm/bootstrap").then(m => m.downloadPrivateLuddishForTest())
                    .then(ok => showToast(ok ? "On-device AI model verified and registered." :
                      "Download or verification failed. Check storage, network and device compatibility.",
                      ok ? "neutral" : "growling"))
                    .catch(() => showToast("On-device AI model download failed.", "growling"))
                    .finally(() => setSlmInstalling(false));
                } }]);
            }}
            style={[s.rowItem, s.divider]}>
            <View style={{ flex: 1 }}>
              <Text style={s.rowLabel}>{aiDownloadActive ? "On-device AI setup in progress" : "Download On-device AI"}</Text>
              <Text style={s.rowHint}>Approximately 491 MB. Downloads only with your permission.</Text>
              {aiDownloadActive ? <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.sm }}><ActivityIndicator size="small" /><Text style={s.rowHint}>{aiDownload.phase === "downloading" ? (aiDownload.totalBytes > 0 ? `Downloading ${Math.min(100, Math.round(100 * aiDownload.receivedBytes / aiDownload.totalBytes))}% · ${(aiDownload.receivedBytes / 1048576).toFixed(0)} of ${(aiDownload.totalBytes / 1048576).toFixed(0)} MB` : `Downloading · ${(aiDownload.receivedBytes / 1048576).toFixed(0)} MB received`) : aiDownload.phase === "verifying" ? "Verifying download…" : "Setting up On-device AI…"}</Text></View> : null}
              {aiDownload.phase === "failed" ? <Text style={s.rowHint}>Previous setup failed: {aiDownload.error ?? "Unknown error"}</Text> : null}
            </View>
            <ChevronRight size={20} color={colors.muted} />
          </Pressable>
        ) : null}
        {slmTestAvailable ? (
          <Pressable testID="settings-install-slm" accessibilityRole="button"
            accessibilityLabel="Install On-device AI from device"
            disabled={slmInstalling || aiDownloadActive || slmActivity.registered}
            onPress={() => void installSlmModel()}
            style={[s.rowItem, s.divider, { opacity: slmInstalling || aiDownloadActive || slmActivity.registered ? 0.5 : 1 }]}>
            <View style={{ flex: 1 }}>
              <Text style={s.rowLabel}>{slmInstalling ? "Verifying model…" :
                slmActivity.registered ? "Model runtime registered" : "Install On-device AI Model"}</Text>
              <Text style={s.rowHint}>Select the approved GGUF file on your phone. It is copied into private storage and verified.</Text>
            </View>
          </Pressable>
        ) : null}
        <NavRow label="Minimise ApolloSG" hint="Move ApolloSG to the background" onPress={() => void minimiseApp(showToast)} testID="settings-minimise" />
        <NavRow label="Retrofit new enhancements" hint="Apply the latest reporting format to all past investigations" onPress={() => setShowRetrofit(true)} testID="settings-retrofit" />
      </Group>

      {/* 6 ── Diagnostics */}
      <Group icon={Activity} title="Diagnostics" tone="diagnostics" testID="settings-diagnostics">
        <NavRow first label="Feed health" hint="Sync status of each government scam and cyber-security feed" onPress={() => router.push("/settings/feed-health")} testID="settings-feed-health" />
        <NavRow label="Debug logs" hint="Investigation flow traces — view and export" onPress={() => router.push("/settings/debug-logs")} testID="settings-debug-logs" />
      </Group>

      {/* 7 ── Help */}
      <Group icon={LifeBuoy} title="Help &amp; about" tone="help" testID="settings-help">
        <NavRow first label="Get help with ApolloSG" hint="App details, protection issues, device checkup and support email" onPress={() => router.push("/support")} testID="settings-open-support" />
        <Pressable testID="settings-share" accessibilityRole="button" accessibilityLabel="How to share into ApolloSG" onPress={() => setShowShare((v) => !v)} style={[s.rowItem, s.divider]}>
          <View style={{ flex: 1 }}><Text style={s.rowLabel}>How to share into ApolloSG</Text></View><ChevronRight size={20} color={colors.muted} />
        </Pressable>
        {showShare ? <Body testID="settings-share-help" style={{ paddingBottom: spacing.sm }}>Many messaging, mail and browser apps offer Share — tap it, then choose ApolloSG. Not every app does; if yours doesn&apos;t, copy and paste the text or use a screenshot. ApolloSG always waits for you to confirm before it checks anything you share.</Body> : null}
        <NavRow label="About ApolloSG" hint="Meet Apollo and Higgins, your protections, privacy and more" onPress={() => setShowAbout(true)} testID="settings-about-apollo" />
      </Group>

      {/* 8 ── The documents, last: read occasionally, never urgent */}
      <Group icon={FileText} title="Policies &amp; assurance" tone="policies" testID="settings-policies">
        <NavRow first label="Privacy policy" hint="The full policy, on our website" onPress={openPrivacyPolicy} testID="settings-privacy-policy" />
        <NavRow label="Privacy statement" hint="What ApolloSG stores, shares and why" onPress={() => router.push("/privacy-disclosure")} testID="settings-privacy-disclosure" />
        <NavRow label="Third-party services" hint="External services, what they receive and HWG accountability" onPress={() => router.push("/third-party-register")} testID="settings-third-party" />
        <NavRow label="Compliance matrix" hint="Standards, application controls and operational assurance" onPress={() => router.push("/compliance-matrix")} testID="settings-compliance-matrix" />
      </Group>

      {SHOW_CONTRIBUTION ? <View testID="settings-contribution"><Card><Body>Apollo protects everyone. If you believe in the mission, help keep Apollo on watch.</Body></Card></View> : null}

      <Text style={s.footer} testID="settings-footer">{`ApolloSG ${APP_VERSION} · No account · No advertising tracking`}</Text>
    </ScrollView>
    <AlertPreviewSheet visible={preview} onClose={() => setPreview(false)} />
    <AboutApolloSheet visible={showAbout} onClose={() => setShowAbout(false)} />
    <RetrofitModal visible={showRetrofit} onClose={() => setShowRetrofit(false)} />
    <Sheet visible={confirmClear} onClose={() => setConfirmClear(false)} title="Clear Patrol history?" testID="clear-sheet"><Body>This hides Patrol items on this device and asks the service to hide synced summaries. Trusted links are kept.</Body><Button testID="clear-confirm" variant="danger" label="Clear history" onPress={() => { setConfirmClear(false); void clearPatrol(); }} /><Button testID="clear-cancel" variant="ghost" label="Keep history" onPress={() => setConfirmClear(false)} /></Sheet>
  </View>;
}
