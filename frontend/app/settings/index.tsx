import * as Linking from "expo-linking";
import { useRouter } from "expo-router";
import Activity from "lucide-react-native/icons/activity";
import Bell from "lucide-react-native/icons/bell";
import ChevronLeft from "lucide-react-native/icons/chevron-left";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import FileText from "lucide-react-native/icons/file-text";
import LifeBuoy from "lucide-react-native/icons/life-buoy";
import Lock from "lucide-react-native/icons/lock";
import ShieldCheck from "lucide-react-native/icons/shield-check";
import Smartphone from "lucide-react-native/icons/smartphone";
import Users from "lucide-react-native/icons/users";
import React, { useState } from "react";
import { Pressable, ScrollView, Switch, Text, View } from "react-native";
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
import { openPrivacyPolicy } from "@/src/config/privacyPolicy";
import type { NotificationStatus } from "@/src/push/notifications";
import { useApollo } from "@/src/store/ApolloContext";
import { setShowResultReasons, useShowResultReasons } from "@/src/store/resultReasonsStore";
import { fonts, makeStyles, spacing, useTheme } from "@/src/theme";
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
}));

export default function SettingsScreen() {
  const s = useStyles(); const insets = useSafeAreaInsets(); const router = useRouter(); const { colors } = useTheme();
  const { trust, revokeTrust, clearPatrol, notificationStatus, enableNotifications, quietHours, quietNow, setQuietHours, lowPower, setLowPower, notificationPreferences, setNotificationPreferences, showToast } = useApollo();
  const [confirmClear, setConfirmClear] = useState(false); const [preview, setPreview] = useState(false);
  const [showTrust, setShowTrust] = useState(false); const [showShare, setShowShare] = useState(false); const [showAbout, setShowAbout] = useState(false);
  const [showRetrofit, setShowRetrofit] = useState(false);
  const showReasons = useShowResultReasons();

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
