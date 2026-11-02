// Gate Details — reusable screen for individual Gate information.
// Navigated to from Protection Category → Gates tab → Gate row.
// Shows: Gate name, status, what it does, how it works, current status,
// coverage & limitations, and Higgins-guided troubleshooting.

import { useLocalSearchParams, useRouter } from "expo-router";
import ChevronLeft from "lucide-react-native/icons/chevron-left";
import CircleCheck from "lucide-react-native/icons/circle-check";
import ExternalLink from "lucide-react-native/icons/external-link";
import FileText from "lucide-react-native/icons/file-text";
import Globe from "lucide-react-native/icons/globe";
import Grid2x2 from "lucide-react-native/icons/grid-2x2";
import Info from "lucide-react-native/icons/info";
import Link2 from "lucide-react-native/icons/link-2";
import Mail from "lucide-react-native/icons/mail";
import MessageSquare from "lucide-react-native/icons/message-square";
import Phone from "lucide-react-native/icons/phone";
import RefreshCw from "lucide-react-native/icons/refresh-cw";
import ShieldCheck from "lucide-react-native/icons/shield-check";
import Smartphone from "lucide-react-native/icons/smartphone";
import TriangleAlert from "lucide-react-native/icons/triangle-alert";
import Wifi from "lucide-react-native/icons/wifi";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  AppState,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AppMenuButton } from "@/src/components/AppMenu";

import { Card, Pill } from "@/src/components/ui";
import { WebsiteProtectionNotices } from "@/src/components/WebsiteProtectionNotices";
import type { GateId, GatePresentation, GateStatusLabel } from "@/src/domain/gates";
import { gateTone } from "@/src/domain/gates";
import { GATE_CONTENT } from "@/src/domain/gateContent";
import { userActionRoute } from "@/src/domain/userActions";
import { apolloProtectionExplanation, type ExplanationResult } from "@/src/higgins/protectionExplanation";
import { runProtectionHealthCheck, requestSiteProtectionRecovery } from "@/src/protection/healthCoordinator";
import { useProtectionHealth } from "@/src/protection/healthStore";
import { useApollo } from "@/src/store/ApolloContext";
import { goBackOrHome } from "@/src/utils/navigation";
import { HigginsAvatar } from "@/src/components/HigginsAvatar";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";


// ── Gate icon mapping ───────────────────────────────────────────────────────
const GATE_ICONS: Record<
  GateId,
  React.ComponentType<{ size?: number; color?: string }>
> = {
  site: ShieldCheck,
  link: Link2,
  text: MessageSquare,
  call: Phone,
  email: Mail,
  account: ShieldCheck,
  file: FileText,
  app: Grid2x2,
  device: Smartphone,
  network: Wifi,
};

// ── Higgins Guidance Types ──────────────────────────────────────────────────

interface HigginsGuidance {
  /** Whether to show the troubleshooting card at all. */
  needsGuidance: boolean;
  /** What's wrong — the specific problem. */
  whatsWrong: string;
  /** Why it matters — impact on protection. */
  whyItMatters: string;
  /** What to do — clear instruction. */
  whatToDo: string;
  /** How to confirm — what to check after acting. */
  howToConfirm: string;
  /** Primary action button label. */
  actionLabel: string;
  /** What kind of action to take. */
  actionType: "open_settings" | "navigate" | "retry" | "ask_higgins" | "none";
  /** Navigation route for "navigate" action type. */
  navRoute?: string;
  /** Tone of the guidance card. */
  tone: "warning" | "info" | "success";
}

// ── Higgins Guidance Logic ──────────────────────────────────────────────────

function getHigginsGuidance(gate: GatePresentation): HigginsGuidance {
  const auto = gate.capability.automatic;
  const isManualOnly = auto?.manualOnly === true;
  const noGuidance: HigginsGuidance = {
    needsGuidance: false,
    whatsWrong: "",
    whyItMatters: "",
    whatToDo: "",
    howToConfirm: "",
    actionLabel: "",
    actionType: "none",
    tone: "success",
  };

  // ── Healthy or manual-only gates: no troubleshooting needed ──
  if (gate.tone === "good") return noGuidance;
  if (gate.statusLabel === "Manual check" && (isManualOnly || !auto)) return noGuidance;
  if (gate.statusLabel === "Check in progress") return noGuidance;

  // ── Permission needed ──
  if (auto?.state === "permission_needed") {
    const permName = getPermissionName(gate.id);
    return {
      needsGuidance: true,
      whatsWrong: `${gate.title} isn't working because ApolloSG doesn't have the ${permName} it needs.`,
      whyItMatters: `Without this permission, Apollo can't ${getProtectionVerb(gate.id)} automatically.`,
      whatToDo: `Open your device settings and grant the ${permName} to ApolloSG. I can take you there.`,
      howToConfirm: "When you come back, I'll check whether the permission has been granted and update the status.",
      actionLabel: "Open device settings",
      actionType: "open_settings",
      tone: "warning",
    };
  }

  // ── Setup needed / not activated ──
  if (auto?.state === "setup_needed" || auto?.state === "not_activated") {
    const isOptional = gate.id === "email" || gate.id === "account";
    return {
      needsGuidance: true,
      whatsWrong: isOptional
        ? `${gate.title} hasn't been set up yet, but it's optional.`
        : `${gate.title} needs initial setup before it can protect automatically.`,
      whyItMatters: isOptional
        ? `You can still use manual checks anytime. Setting up automatic monitoring adds an extra layer of protection.`
        : `Until setup is complete, this protection won't run in the background.`,
      whatToDo: isOptional
        ? `You can set this up whenever you're ready, or continue using manual checks.`
        : `Complete the setup to enable automatic protection.`,
      howToConfirm: "After setup, this screen will update to show the Gate's new status.",
      actionLabel: gate.primaryAction?.label ?? "Set up",
      actionType: gate.primaryAction ? "navigate" : "ask_higgins",
      navRoute: gate.primaryAction ? userActionRoute(gate.primaryAction.id as never) ?? undefined : undefined,
      tone: "info",
    };
  }

  // ── Interrupted (was running, stopped) ──
  if (auto?.state === "interrupted") {
    return {
      needsGuidance: true,
      whatsWrong: `${gate.title} was active but has stopped working. It's not currently protecting your device.`,
      whyItMatters: `While interrupted, Apollo can't ${getProtectionVerb(gate.id)} automatically. Manual checks still work.`,
      whatToDo: auto.limitation ?? "Try restoring this protection. If the problem persists, check your device settings.",
      howToConfirm: "When you return, I'll verify whether the protection has resumed.",
      actionLabel: gate.primaryAction?.label ?? "Restore protection",
      actionType: gate.primaryAction ? "navigate" : "open_settings",
      navRoute: gate.primaryAction ? userActionRoute(gate.primaryAction.id as never) ?? undefined : undefined,
      tone: "warning",
    };
  }

  // ── Off by choice ──
  if (auto?.state === "off_by_choice") {
    return {
      needsGuidance: true,
      whatsWrong: `${gate.title} has been turned off.`,
      whyItMatters: "Automatic protection is not running. You can still use manual checks.",
      whatToDo: "Turn it back on whenever you're ready.",
      howToConfirm: "After enabling, I'll verify the protection is active.",
      actionLabel: gate.primaryAction?.label ?? "Turn on",
      actionType: gate.primaryAction ? "navigate" : "open_settings",
      navRoute: gate.primaryAction ? userActionRoute(gate.primaryAction.id as never) ?? undefined : undefined,
      tone: "info",
    };
  }

  // ── Temporarily unavailable ──
  if (auto?.state === "temporarily_unavailable") {
    return {
      needsGuidance: true,
      whatsWrong: `Apollo cannot confirm whether ${gate.title} is operating right now.`,
      whyItMatters: "This is usually temporary. The protection may still be working, but verification hasn't completed recently.",
      whatToDo: "Try refreshing the status. If the problem persists, it may resolve on its own shortly.",
      howToConfirm: "After refreshing, the status will update if verification succeeds.",
      actionLabel: "Refresh status",
      actionType: "retry",
      tone: "info",
    };
  }

  // ── Unsupported ──
  if (auto?.state === "unsupported") {
    return {
      needsGuidance: true,
      whatsWrong: `${gate.title} is not available on this ${Platform.OS === "ios" ? "iOS" : Platform.OS === "android" ? "Android" : ""} device.`,
      whyItMatters: "This is a platform limitation, not a configuration problem. It cannot be fixed with settings changes.",
      whatToDo: "Manual checks are still available where supported. No action is needed from you.",
      howToConfirm: "",
      actionLabel: "",
      actionType: "none",
      tone: "info",
    };
  }

  // ── Limited coverage (running but restricted) ──
  if (gate.tone === "limited" || gate.tone === "unverified") {
    return {
      needsGuidance: true,
      whatsWrong: auto?.limitation ?? `${gate.title} is running with reduced coverage.`,
      whyItMatters: "Some protection capabilities are restricted. ApolloSG is still working within its available scope.",
      // Only a provider hostname needs changing. A setting Apollo couldn't read may already be Automatic,
      // so the person is never told to set what they may already have set.
      whatToDo: /provider hostname/i.test(auto?.limitation ?? "")
        ? "Set Private DNS to Automatic in your device’s settings, then come back here and ApolloSG will re-check."
        : /dns/i.test(auto?.limitation ?? "")
          ? "Apollo couldn’t read this phone’s Private DNS setting just now. If it’s already set to Automatic, you don’t need to change anything. Apollo checks again when you come back."
          : "Check device settings if you'd like to expand coverage. Otherwise, Apollo continues protecting within its current scope.",
      howToConfirm: "After any changes, return here to see the updated status.",
      actionLabel: "Check device settings",
      actionType: "open_settings",
      tone: "info",
    };
  }

  // ── Action needed (catch-all for tone "action") ──
  if (gate.tone === "action") {
    return {
      needsGuidance: true,
      whatsWrong: gate.currentHelp,
      whyItMatters: `This Gate needs your attention to resume full protection.`,
      whatToDo: auto?.limitation ?? "Review the Gate's requirements and take the suggested action.",
      howToConfirm: "After making changes, return here and I'll verify the status.",
      actionLabel: gate.primaryAction?.label ?? "Open settings",
      actionType: gate.primaryAction ? "navigate" : "open_settings",
      navRoute: gate.primaryAction ? userActionRoute(gate.primaryAction.id as never) ?? undefined : undefined,
      tone: "warning",
    };
  }

  return noGuidance;
}

function getPermissionName(gateId: GateId): string {
  switch (gateId) {
    case "site": return "network/VPN permission";
    case "text": return "notification access permission";
    case "call": return "call screening permission";
    case "network": return "network information permission";
    case "device": return "device access permission";
    default: return "required permission";
  }
}

function getProtectionVerb(gateId: GateId): string {
  switch (gateId) {
    case "site": return "filter dangerous websites";
    case "text": return "screen incoming messages";
    case "call": return "screen incoming calls";
    case "network": return "monitor your internet connection";
    case "email": return "check incoming emails";
    case "device": return "monitor device security";
    default: return "protect automatically";
  }
}

// ── Styles ──────────────────────────────────────────────────────────────────
const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },

  // Header
  headerRow: {
    paddingHorizontal: spacing.lg,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingBottom: spacing.xs,
  },
  backBtn: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  headerTitle: {
    flex: 1,
    fontFamily: fonts.displayBold,
    fontSize: 22,
    color: c.onSurface,
  },

  // Status area
  statusArea: {
    paddingHorizontal: spacing.xl,
    gap: spacing.sm,
    paddingBottom: spacing.md,
  },
  statusRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  modeLabel: {
    fontFamily: fonts.text,
    fontSize: 13,
    color: c.onSurfaceSecondary,
  },
  currentHelp: {
    fontFamily: fonts.text,
    fontSize: 14,
    lineHeight: 20,
    color: c.onSurfaceSecondary,
  },

  // Scroll content
  scrollContent: {
    paddingHorizontal: spacing.xl,
    gap: spacing.lg,
    paddingBottom: spacing["3xl"],
  },

  // Section cards
  sectionCard: {
    gap: spacing.md,
  },
  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  sectionIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
  },
  sectionTitle: {
    fontFamily: fonts.displayBold,
    fontSize: 16,
    color: c.onSurface,
  },
  sectionBody: {
    fontFamily: fonts.text,
    fontSize: 14,
    lineHeight: 21,
    color: c.onSurfaceSecondary,
  },

  // Bullets
  bullet: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    paddingLeft: spacing.xs,
  },
  bulletDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    marginTop: 7,
  },
  bulletText: {
    flex: 1,
    fontFamily: fonts.text,
    fontSize: 14,
    lineHeight: 20,
    color: c.onSurfaceSecondary,
  },

  // Current status card
  statusCard: {
    borderRadius: radius.md,
    padding: spacing.lg,
    gap: spacing.md,
  },
  statusCardTitle: {
    fontFamily: fonts.displayBold,
    fontSize: 15,
    color: c.onSurface,
  },
  statusCardBody: {
    fontFamily: fonts.text,
    fontSize: 14,
    lineHeight: 20,
    color: c.onSurfaceSecondary,
  },
  limitationText: {
    fontFamily: fonts.text,
    fontSize: 13,
    lineHeight: 18,
  },

  // Higgins troubleshooting card
  higginsCard: {
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.md,
  },
  higginsHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  higginsTitleBlock: { flex: 1, gap: 2 },
  higginsTitle: {
    fontFamily: fonts.displayBold,
    fontSize: 15,
    color: c.onSurface,
  },
  higginsSub: {
    fontFamily: fonts.text,
    fontSize: 13,
    color: c.onSurfaceSecondary,
  },
  higginsBody: {
    fontFamily: fonts.text,
    fontSize: 14,
    lineHeight: 21,
    color: c.onSurface,
  },
  higginsEmphasis: {
    fontFamily: fonts.textSemibold,
    fontSize: 14,
    lineHeight: 21,
    color: c.onSurface,
  },

  // Action buttons
  actionBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 2,
    borderRadius: radius.md,
    minHeight: 48,
  },
  actionBtnText: {
    fontFamily: fonts.textSemibold,
    fontSize: 14,
  },
  secondaryBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    minHeight: 44,
    borderWidth: 1,
  },
  secondaryBtnText: {
    fontFamily: fonts.textSemibold,
    fontSize: 13,
  },

  // Verification banner
  verifyBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  verifyText: {
    flex: 1,
    fontFamily: fonts.text,
    fontSize: 13,
    lineHeight: 18,
  },
}));

// ── Helpers ──────────────────────────────────────────────────────────────────

function getModeLabel(gate: GatePresentation): string {
  const auto = gate.capability.automatic;
  const od = gate.capability.onDemand;
  if (auto && !auto.manualOnly && od) return "Automatic + on-demand";
  if (auto && !auto.manualOnly) return "Automatic protection";
  if (od) return "On-demand check";
  return "Manual check";
}

function getStatusExplanation(gate: GatePresentation): string {
  const auto = gate.capability.automatic;
  switch (gate.statusLabel) {
    case "Watching":
      return "This Gate is actively protecting your device. It is verified, running and monitoring in the background within its supported scope.";
    case "Manual check":
      return "This Gate is ready for you to use whenever you need it. Submit something to check and TC FlyBy will investigate it, with Magnum DI looking deeper only if needed.";
    case "Check in progress":
      return "Apollo is currently verifying this Gate's status. This usually completes quickly.";
    case "Setup required":
      return auto?.state === "permission_needed"
        ? "This Gate needs a device permission to operate. Grant it whenever you're ready — your other protections remain active."
        : "This Gate needs initial setup before it can protect automatically.";
    case "Off":
      return "This Gate has been turned off by choice. You can re-enable it at any time.";
    case "Limited":
      return "This Gate is running but with reduced coverage. Some protection capabilities are restricted by device settings or configuration.";
    case "Action needed":
      return "This Gate was active but has encountered a problem and is not currently protecting. It needs your attention to resume.";
    case "Unavailable":
      return "This Gate isn't supported here. This may be due to operating system restrictions.";
    case "Unable to verify":
      return "Apollo cannot currently confirm whether this Gate is operating. It may still be working, but verification has not completed recently.";
    default:
      return gate.currentHelp;
  }
}

// ── Higgins Troubleshoot Card ───────────────────────────────────────────────

function HigginsTroubleshootCard({
  gate,
  guidance,
  onRefresh,
  refreshing,
  justVerified,
  previousStatus,
}: {
  gate: GatePresentation;
  guidance: HigginsGuidance;
  onRefresh: () => void;
  refreshing: boolean;
  justVerified: boolean;
  previousStatus: GateStatusLabel | null;
}) {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();

  const isFixed = justVerified && gate.tone === "good" && previousStatus !== null && previousStatus !== "Watching";
  const isStillBroken = justVerified && gate.tone !== "good" && previousStatus !== null;

  const handleAction = useCallback(() => {
    if (guidance.actionType === "open_settings") {
      Linking.openSettings();
    } else if (guidance.actionType === "navigate" && guidance.navRoute) {
      router.push(guidance.navRoute as never);
    } else if (guidance.actionType === "navigate" && gate.primaryAction?.id === "restore_site") {
      // "Turn on website protection" — no navigation route, trigger VPN permission request directly.
      void requestSiteProtectionRecovery().then(() => onRefresh());
    } else if (guidance.actionType === "retry") {
      onRefresh();
    } else if (guidance.actionType === "ask_higgins") {
      router.push({
        pathname: "/(tabs)/ask",
        params: {
          prompt: `Help me fix my ${gate.title} protection. Status: ${gate.statusLabel}. ${gate.currentHelp}`,
        },
      });
    }
  }, [guidance, gate, router, onRefresh]);

  // ── Success after verification ──
  if (isFixed) {
    return (
      <View
        style={[s.higginsCard, { backgroundColor: "rgba(46,125,50,0.08)" }]}
        testID="gate-higgins-success"
      >
        <View style={s.higginsHeader}>
          <HigginsAvatar size={44} />
          <View style={s.higginsTitleBlock}>
            <Text style={s.higginsTitle}>Higgins</Text>
            <Text style={[s.higginsSub, { color: colors.restingText }]}>
              Protection restored
            </Text>
          </View>
        </View>
        <View style={s.verifyBanner}>
          <CircleCheck size={20} color={colors.restingText} />
          <Text style={[s.verifyText, { color: colors.restingText }]}>
            {gate.title} is now working correctly. Your protection has been verified.
          </Text>
        </View>
      </View>
    );
  }

  // ── Healthy gate — simple reassurance ──
  if (!guidance.needsGuidance) {
    return (
      <View
        style={[s.higginsCard, { backgroundColor: "rgba(46,125,50,0.06)" }]}
        testID="gate-higgins-healthy"
      >
        <View style={s.higginsHeader}>
          <HigginsAvatar size={44} />
          <View style={s.higginsTitleBlock}>
            <Text style={s.higginsTitle}>Higgins</Text>
            <Text style={[s.higginsSub, { color: colors.restingText }]}>
              All clear
            </Text>
          </View>
        </View>
        <Text style={s.higginsBody}>
          {gate.title} is working as expected. No issues detected and no action needed from you.
        </Text>
      </View>
    );
  }

  // ── Still broken after verification ──
  const stillBrokenNote = isStillBroken
    ? "The status hasn't changed yet. The setting may need a moment to take effect, or a different action may be needed."
    : null;

  // ── Guidance card with troubleshooting ──
  const bgColor =
    guidance.tone === "warning"
      ? "rgba(211,47,47,0.06)"
      : "rgba(22,34,53,0.04)";

  return (
    <View
      style={[s.higginsCard, { backgroundColor: bgColor }]}
      testID="gate-higgins-troubleshoot"
    >
      <View style={s.higginsHeader}>
        <HigginsAvatar size={44} />
        <View style={s.higginsTitleBlock}>
          <Text style={s.higginsTitle}>Higgins</Text>
          <Text
            style={[
              s.higginsSub,
              {
                color:
                  guidance.tone === "warning"
                    ? colors.barkingText
                    : colors.onSurfaceSecondary,
              },
            ]}
          >
            {guidance.tone === "warning"
              ? "Needs your attention"
              : "Suggestion"}
          </Text>
        </View>
      </View>

      {/* What's wrong */}
      <Text style={s.higginsBody}>{guidance.whatsWrong}</Text>

      {/* Why it matters */}
      <Text style={s.higginsBody}>{guidance.whyItMatters}</Text>

      {/* What to do */}
      {guidance.whatToDo ? (
        <Text style={s.higginsEmphasis}>{guidance.whatToDo}</Text>
      ) : null}

      {/* Still broken note */}
      {stillBrokenNote ? (
        <View
          style={[
            s.verifyBanner,
            { backgroundColor: "rgba(230,138,0,0.08)" },
          ]}
        >
          <TriangleAlert size={16} color={colors.ears_upText} />
          <Text style={[s.verifyText, { color: colors.ears_upText }]}>
            {stillBrokenNote}
          </Text>
        </View>
      ) : null}

      {/* Primary action button */}
      {guidance.actionLabel && guidance.actionType !== "none" ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={guidance.actionLabel}
          testID="gate-higgins-action"
          onPress={handleAction}
          disabled={refreshing}
          style={({ pressed }) => [
            s.actionBtn,
            {
              backgroundColor:
                guidance.tone === "warning" ? colors.brand : colors.gold,
              opacity: pressed ? 0.82 : refreshing ? 0.6 : 1,
            },
          ]}
        >
          {refreshing ? (
            <ActivityIndicator size="small" color={colors.onBrand} />
          ) : guidance.actionType === "open_settings" ? (
            <ExternalLink size={16} color={colors.onBrand} />
          ) : guidance.actionType === "retry" ? (
            <RefreshCw size={16} color={colors.onBrand} />
          ) : null}
          <Text style={[s.actionBtnText, { color: colors.onBrand }]}>
            {guidance.actionLabel}
          </Text>
        </Pressable>
      ) : null}

      {/* How to confirm */}
      {guidance.howToConfirm ? (
        <Text
          style={{
            fontFamily: fonts.text,
            fontSize: 12,
            lineHeight: 16,
            color: colors.muted,
          }}
        >
          {guidance.howToConfirm}
        </Text>
      ) : null}

      {/* Secondary: Ask Higgins for more help (always available for problem gates) */}
      {guidance.actionType !== "ask_higgins" && guidance.needsGuidance ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Ask Higgins for more help"
          testID="gate-ask-higgins-secondary"
          onPress={() =>
            router.push({
              pathname: "/(tabs)/ask",
              params: {
                prompt: `My ${gate.title} protection shows "${gate.statusLabel}". ${gate.currentHelp} ${guidance.whatsWrong} Can you help me understand and fix this?`,
              },
            })
          }
          style={({ pressed }) => [
            s.secondaryBtn,
            {
              borderColor: colors.border,
              opacity: pressed ? 0.82 : 1,
            },
          ]}
        >
          <Text style={[s.secondaryBtnText, { color: colors.onSurface }]}>
            Ask Higgins for more help
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}

// ── Main Screen ─────────────────────────────────────────────────────────────

export default function GateDetailsScreen() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const health = useProtectionHealth();
  const params = useLocalSearchParams<{ gate?: string; category?: string }>();

  const gateId = (params.gate ?? "site") as GateId;
  const categoryId = params.category ?? "websites_links";

  const [refreshing, setRefreshing] = useState(false);
  const [justVerified, setJustVerified] = useState(false);
  const [previousStatus, setPreviousStatus] = useState<GateStatusLabel | null>(null);
  const appStateRef = useRef(AppState.currentState);
  const gateStatusRef = useRef<GateStatusLabel | null>(null);

  // Find the gate from health store
  const gate = useMemo(() => {
    if (health.checking) return null;
    return health.gates.find((g) => g.id === gateId) ?? null;
  }, [health.checking, health.gates, gateId]);

  // Track gate status for verification
  useEffect(() => {
    if (gate) {
      gateStatusRef.current = gate.statusLabel;
    }
  }, [gate]);

  // Listen for app returning to foreground (user came back from settings)
  useEffect(() => {
    const subscription = AppState.addEventListener("change", (nextState) => {
      if (
        appStateRef.current.match(/inactive|background/) &&
        nextState === "active"
      ) {
        // User returned from settings — trigger a health refresh
        const currentStatus = gateStatusRef.current;
        if (currentStatus && currentStatus !== "Watching") {
          setPreviousStatus(currentStatus);
          setRefreshing(true);
          runProtectionHealthCheck("foreground")
            .then(() => {
              setJustVerified(true);
            })
            .finally(() => {
              setRefreshing(false);
            });
        }
      }
      appStateRef.current = nextState;
    });
    return () => subscription.remove();
  }, []);

  // Manual refresh handler
  const handleRefresh = useCallback(() => {
    if (refreshing) return;
    const currentStatus = gateStatusRef.current;
    setPreviousStatus(currentStatus);
    setRefreshing(true);
    setJustVerified(false);
    runProtectionHealthCheck("user_action")
      .then(() => {
        setJustVerified(true);
      })
      .finally(() => {
        setRefreshing(false);
      });
  }, [refreshing]);

  const content = GATE_CONTENT[gateId];
  const Icon = GATE_ICONS[gateId] ?? ShieldCheck;

  // Apollo's one fixed explanation of this protection — the same text for everyone, no AI call.
  // Fetched once this install has its device identity (a cold deep link can arrive before it).
  const { deviceId } = useApollo();
  const [explanation, setExplanation] = useState<ExplanationResult | null>(null);
  useEffect(() => {
    if (!deviceId) return;
    let cancelled = false;
    setExplanation(null);
    apolloProtectionExplanation(gateId)
      .then((result) => { if (!cancelled) setExplanation(result); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [gateId, deviceId]);

  // Loading / not found
  if (health.checking || !gate) {
    return (
      <View style={s.root} testID="gate-details-screen">
        <View style={{ paddingTop: insets.top + spacing.md }}>
          <View style={s.headerRow}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Back"
              testID="gate-details-back"
              onPress={() => goBackOrHome(router)}
              style={s.backBtn}
            >
              <ChevronLeft size={24} color={colors.onSurface} />
            </Pressable>
            <Text style={s.headerTitle}>Gate Details</Text>
            <AppMenuButton testID="gate-details-menu" />
          </View>
        </View>
        <View
          style={{
            flex: 1,
            alignItems: "center",
            justifyContent: "center",
            paddingHorizontal: spacing.xl,
          }}
        >
          {refreshing ? (
            <ActivityIndicator size="large" color={colors.brand} />
          ) : (
            <Text
              style={{
                fontFamily: fonts.text,
                fontSize: 15,
                color: colors.onSurfaceSecondary,
                textAlign: "center",
              }}
            >
              {health.checking
                ? "Checking protection status…"
                : "Gate not found."}
            </Text>
          )}
        </View>
      </View>
    );
  }

  const tone = gateTone(gate.tone);
  const modeLabel = getModeLabel(gate);
  const statusExplanation = getStatusExplanation(gate);
  const hasLimitation = !!gate.capability.automatic?.limitation;
  const guidance = getHigginsGuidance(gate);

  return (
    <View style={s.root} testID="gate-details-screen">
      {/* ── Header ── */}
      <View style={{ paddingTop: insets.top + spacing.md }}>
        <View style={s.headerRow}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Back to Gates"
            testID="gate-details-back"
            onPress={() =>
              router.push(
                `/protection-details?category=${categoryId}&tab=gates` as never,
              )
            }
            style={s.backBtn}
          >
            <ChevronLeft size={24} color={colors.onSurface} />
          </Pressable>
          <Text style={s.headerTitle}>
            {gate.title}
          </Text>
          <AppMenuButton testID="gate-details-menu" />
        </View>

        {/* Status + mode */}
        <View style={s.statusArea}>
          <View style={s.statusRow}>
            <Pill tone={tone} label={gate.statusLabel} />
            <Text style={s.modeLabel}>{modeLabel}</Text>
          </View>
          <Text style={s.currentHelp}>{gate.currentHelp}</Text>
        </View>
      </View>

      {/* ── Scrollable content ── */}
      <ScrollView
        testID="gate-details-scroll"
        contentContainerStyle={[
          s.scrollContent,
          { paddingBottom: insets.bottom + spacing["3xl"], paddingTop: spacing.sm },
        ]}
        showsVerticalScrollIndicator={false}
      >
        {/* Higgins guidance — shown first when there's an issue */}
        {gateId === "site" ? <WebsiteProtectionNotices protection={health.protection} testID="gate-site-notices" /> : null}
        {(guidance.needsGuidance || justVerified) ? (
          <HigginsTroubleshootCard
            gate={gate}
            guidance={guidance}
            onRefresh={handleRefresh}
            refreshing={refreshing}
            justVerified={justVerified}
            previousStatus={previousStatus}
          />
        ) : null}

        {/* What this Gate does */}
        <Card style={s.sectionCard} testID="gate-what-it-does">
          <View style={s.sectionHeader}>
            <View
              style={[
                s.sectionIcon,
                { backgroundColor: colors.surfaceTertiary },
              ]}
            >
              <Icon size={18} color={colors.brand} />
            </View>
            <Text style={s.sectionTitle}>What this Gate does</Text>
          </View>
          <Text style={s.sectionBody}>{content.whatItDoes}</Text>
        </Card>

        {/* Why it matters — Apollo's fixed explanation */}
        {explanation ? (
          <Card style={s.sectionCard} testID="gate-why-it-matters">
            <View style={s.sectionHeader}>
              <View style={[s.sectionIcon, { backgroundColor: colors.surfaceTertiary }]}>
                <ShieldCheck size={18} color={colors.brand} />
              </View>
              <Text style={s.sectionTitle}>Why it matters</Text>
            </View>
            <Text style={s.sectionBody}>{explanation.explanation.why}</Text>
            <Text style={[s.sectionBody, { marginTop: spacing.sm }]}>
              <Text style={{ fontFamily: fonts.textSemibold, color: colors.onSurface }}>Protects you against: </Text>
              {explanation.explanation.protectsAgainst}
            </Text>
          </Card>
        ) : null}

        {/* How this Gate works */}
        <Card style={s.sectionCard} testID="gate-how-it-works">
          <View style={s.sectionHeader}>
            <View
              style={[
                s.sectionIcon,
                { backgroundColor: "rgba(22,34,53,0.12)" },
              ]}
            >
              <Info size={18} color={colors.brand} />
            </View>
            <Text style={s.sectionTitle}>How this Gate works</Text>
          </View>
          {content.howItWorks.map((bullet, i) => (
            <View key={i} style={s.bullet}>
              <View
                style={[s.bulletDot, { backgroundColor: colors.brand }]}
              />
              <Text style={s.bulletText}>{bullet}</Text>
            </View>
          ))}
        </Card>

        {/* Current protection status */}
        <Card style={s.sectionCard} testID="gate-current-status">
          <View style={s.sectionHeader}>
            <View
              style={[
                s.sectionIcon,
                {
                  backgroundColor:
                    gate.tone === "action"
                      ? "rgba(211,47,47,0.10)"
                      : gate.tone === "good"
                        ? "rgba(46,125,50,0.10)"
                        : colors.surfaceTertiary,
                },
              ]}
            >
              {gate.tone === "action" ? (
                <TriangleAlert size={18} color={colors.barkingText} />
              ) : (
                <ShieldCheck
                  size={18}
                  color={
                    gate.tone === "good" ? colors.restingText : colors.brand
                  }
                />
              )}
            </View>
            <Text style={s.sectionTitle}>Current protection status</Text>
          </View>
          <Text style={s.sectionBody}>{statusExplanation}</Text>

          {hasLimitation ? (
            <View
              style={[
                s.statusCard,
                { backgroundColor: "rgba(230,138,0,0.08)" },
              ]}
            >
              <Text style={s.statusCardTitle}>Current limitation</Text>
              <Text
                style={[
                  s.limitationText,
                  { color: colors.ears_upText },
                ]}
              >
                {gate.capability.automatic?.limitation}
              </Text>
            </View>
          ) : null}
        </Card>

        {/* Coverage */}
        <Card style={s.sectionCard} testID="gate-coverage">
          <View style={s.sectionHeader}>
            <View
              style={[
                s.sectionIcon,
                { backgroundColor: colors.surfaceTertiary },
              ]}
            >
              <Globe size={18} color={colors.brand} />
            </View>
            <Text style={s.sectionTitle}>What it protects</Text>
          </View>
          {content.coverage.map((bullet, i) => (
            <View key={i} style={s.bullet}>
              <View
                style={[s.bulletDot, { backgroundColor: colors.restingText }]}
              />
              <Text style={s.bulletText}>{bullet}</Text>
            </View>
          ))}
        </Card>

        {/* Limitations */}
        <Card style={s.sectionCard} testID="gate-limitations">
          <View style={s.sectionHeader}>
            <View
              style={[
                s.sectionIcon,
                { backgroundColor: "rgba(230,138,0,0.08)" },
              ]}
            >
              <TriangleAlert size={18} color={colors.ears_upText} />
            </View>
            <Text style={s.sectionTitle}>Limitations</Text>
          </View>
          {content.limitations.map((bullet, i) => (
            <View key={i} style={s.bullet}>
              <View
                style={[
                  s.bulletDot,
                  { backgroundColor: colors.ears_upText },
                ]}
              />
              <Text style={s.bulletText}>{bullet}</Text>
            </View>
          ))}
        </Card>

        {/* Higgins reassurance for healthy gates (shown at bottom) */}
        {!guidance.needsGuidance && !justVerified ? (
          <HigginsTroubleshootCard
            gate={gate}
            guidance={guidance}
            onRefresh={handleRefresh}
            refreshing={refreshing}
            justVerified={false}
            previousStatus={null}
          />
        ) : null}
      </ScrollView>
    </View>
  );
}
