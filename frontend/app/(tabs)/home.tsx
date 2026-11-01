import { useFocusEffect, useRouter } from "expo-router";
import Camera from "lucide-react-native/icons/camera";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import FileText from "lucide-react-native/icons/file-text";
import Globe from "lucide-react-native/icons/globe";
import Mail from "lucide-react-native/icons/mail";
import MessageSquare from "lucide-react-native/icons/message-square";
import Phone from "lucide-react-native/icons/phone";
import Shield from "lucide-react-native/icons/shield";
import ShieldCheck from "lucide-react-native/icons/shield-check";
import Smartphone from "lucide-react-native/icons/smartphone";
import React from "react";
import { Pressable, RefreshControl, ScrollView, Text, useWindowDimensions, View } from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import { runOnJS } from "react-native-reanimated";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { PriorityScamNotice } from "@/src/components/PriorityScamNotice";
import { AlertsButton } from "@/src/components/AlertsButton";
import { AppMenuButton } from "@/src/components/AppMenu";
import { RecoveryBanner, useRecoveryTracker } from "@/src/components/RecoveryBanner";
import { RetrofitModal, hasRetrofitRun } from "@/src/components/RetrofitModal";
import { ServiceBanner } from "@/src/components/ServiceBanner";
import { HigginsFollowUp } from "@/src/components/HigginsFollowUp";
import { ClipboardLinkBanner } from "@/src/components/ClipboardLinkBanner";
import { Body, Button, Card, toneColor } from "@/src/components/ui";
import { PostureSummary, postureColors } from "@/src/components/protection/PostureSummary";
import { buildHomeAttention } from "@/src/domain/homeAttention";
import { buildHomeVoice } from "@/src/domain/higginsHomeVoice";
import { buildHeroBriefs, eventBrief, heroEvents, keptIdentifiers, type KeptIdentifiers } from "@/src/domain/homeHeroBrief";
import { isConsumerPatrolEvent } from "@/src/domain/patrolOutcomes";
import { STATE_LABEL } from "@/src/domain/types";
import type { ApolloState, PatrolEvent, SourceMetadata } from "@/src/domain/types";
import {
  threatCaseStatus,
  STATUS_LABELS,
  STATUS_COLORS,
} from "@/src/domain/threatCase";
import { ProtectionChangeBanner } from "@/src/components/device/ProtectionChangeBanner";
import { getCaseOriginal, subscribeOriginalSource } from "@/src/store/originalSource";
import { NewBadge } from "@/src/components/NewBadge";
import { useNewCases } from "@/src/hooks/useNewCases";
import { useApollo } from "@/src/store/ApolloContext";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { useProtectionPosture } from "@/src/protection/useProtectionPosture";

/** Apollo is an animated character — one state → one GIF.  Matches ApolloHero.tsx. */
const STATE_GIF: Partial<Record<ApolloState, { src: number; label: string }>> = {
  resting:  { src: require("@/assets/images/apollo-patrolling.gif"), label: "Apollo patrolling" },
  sniffing: { src: require("@/assets/images/apollo-sniffing.gif"),   label: "Apollo sniffing" },
  ears_up:  { src: require("@/assets/images/apollo-sniffing.gif"),   label: "Apollo has his ears up" },
  growling: { src: require("@/assets/images/apollo-growling.gif"),    label: "Apollo growling" },
  barking:  { src: require("@/assets/images/apollo-barking.gif"),     label: "Apollo barking" },
  biting:   { src: require("@/assets/images/apollo-barking.gif"),     label: "Apollo blocked a threat" },
};
const FALLBACK_IMAGE = require("@/assets/images/logo.png");
const HERO_BG_IMAGE = require("@/assets/images/hero-bg-patrolling.webp");

// ── Priority threat helpers ──────────────────────────────────────────────────
// "Important for you" is a priority subset of Threats, not an independent store.

function threatSourceIcon(cat: string, meta?: SourceMetadata | null) {
  const t = meta?.type ?? cat;
  switch (t) {
    case "email": return { Icon: Mail, bg: "rgba(220,38,38,0.1)", fg: "#DC2626" };
    case "text": case "message": return { Icon: MessageSquare, bg: "rgba(16,185,129,0.1)", fg: "#10B981" };
    case "screenshot": return { Icon: Camera, bg: "rgba(139,92,246,0.1)", fg: "#8B5CF6" };
    case "link": case "website": return { Icon: Globe, bg: "rgba(220,38,38,0.1)", fg: "#DC2626" };
    case "call": return { Icon: Phone, bg: "rgba(217,119,6,0.1)", fg: "#D97706" };
    case "file": return { Icon: FileText, bg: "rgba(220,38,38,0.1)", fg: "#DC2626" };
    case "app": return { Icon: Smartphone, bg: "rgba(16,185,129,0.1)", fg: "#065F46" };
    default: return { Icon: Shield, bg: "rgba(107,114,128,0.1)", fg: "#374151" };
  }
}

/** Build deduplicated priority threats from real PatrolEvent data. */
function buildPriorityThreats(events: PatrolEvent[]): PatrolEvent[] {
  const active = events
    .filter((e) => !e.resolved_at && (e.state === "barking" || e.state === "growling" || e.state === "ears_up" || e.state === "biting"))
    .sort((a, b) => {
      const rank = (s: string) => (s === "biting" ? 4 : s === "barking" ? 3 : s === "growling" ? 2 : 1);
      const r = rank(b.state) - rank(a.state);
      return r !== 0 ? r : Date.parse(b.occurred_at) - Date.parse(a.occurred_at);
    });
  // Deduplicate by logical issue key
  const seen = new Set<string>();
  const deduped: PatrolEvent[] = [];
  for (const e of active) {
    const key = e.patrol_record?.logicalIssueKey ?? e.event_id;
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(e);
  }
  return deduped.slice(0, 3);
}

/** State-based hero card background landscapes */
const STATE_BG: Record<string, any> = {
  resting:  require("@/assets/images/hero-bg-patrolling.webp"),
  sniffing: require("@/assets/images/hero-bg-sniffing.webp"),
  ears_up:  require("@/assets/images/hero-bg-sniffing.webp"),
  growling: require("@/assets/images/hero-bg-growling.webp"),
  barking:  require("@/assets/images/hero-bg-barking.webp"),
  biting:   require("@/assets/images/hero-bg-biting.webp"),
};

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  scroll: { paddingBottom: spacing["3xl"] },

  // ── Branded header ──
  header: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xs },
  headerRow: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between" },
  brandLogo: { height: 36, aspectRatio: 1789 / 537 },
  brandSubtitle: { fontFamily: fonts.text, fontSize: 11, color: c.onSurfaceSecondary, marginTop: 1, letterSpacing: 0.3 },

  // ── Hero status card ──
  heroCard: {
    marginHorizontal: spacing.lg, borderRadius: radius.lg, overflow: "hidden",
    minHeight: 140, backgroundColor: "#E8F5EE",
  },
  // The 3:1 artwork band, pinned to the bottom so it scales with the card's width on any device.
  heroBgBand: { position: "absolute", left: 0, right: 0, bottom: 0 },
  heroBgImage: { width: "100%", aspectRatio: 2000 / 667 },
  heroBandFade: { position: "absolute", top: 0, left: 0, right: 0, height: "55%" },
  heroGradient: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  heroOverlay: {
    padding: spacing.lg, gap: spacing.md, flexDirection: "column",
    alignItems: "stretch",
  },
  heroTopRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  heroDotsRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: spacing.xs, minHeight: 24 },
  heroDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: "rgba(22,34,53,0.25)" },
  heroDotActive: { backgroundColor: c.brand, width: 18 },
  heroDotsLabel: { fontFamily: fonts.text, fontSize: 11, color: c.onSurfaceSecondary, marginLeft: spacing.xs },
  heroInner: { flexDirection: "row", gap: spacing.lg, alignItems: "flex-start" },
  heroContentWrap: { flex: 1, flexShrink: 1 },
  heroImageWrap: { width: 90, height: 90, borderRadius: 45, borderWidth: 2, borderColor: c.gold, overflow: "hidden", backgroundColor: c.surfaceSecondary },
  heroImage: { width: 90, height: 90 },
  heroContent: { flex: 1, flexShrink: 1, gap: spacing.xs },
  heroStatusRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, flexShrink: 1 },
  heroShield: { marginRight: 2 },
  heroStatusText: { fontFamily: fonts.displayBold, fontSize: 17, color: "#1B6B47", flexShrink: 1 },
  // Runs the full width of the card, stopping short of the artwork on the right.
  // Fixed at 3 lines so the hero card never flexes between 2 and 3 lines.
  heroBrief: { gap: 2, paddingRight: spacing.sm, minHeight: 62 },
  heroLine1: { fontFamily: fonts.textSemibold, fontSize: 14, lineHeight: 20, color: c.onSurface },
  heroLine2: { fontFamily: fonts.text, fontSize: 13, lineHeight: 18, color: c.onSurfaceSecondary },

  // ── "Your protection" card: the overall answer, then Apollo's and the device's protections ──
  postureCard: { marginHorizontal: spacing.lg, marginTop: spacing.md, borderRadius: radius.lg, borderWidth: 1, overflow: "hidden" },
  postureTop: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.lg },
  postureHalves: { flexDirection: "row", borderTopWidth: 0.5, borderTopColor: c.divider, backgroundColor: c.surfaceSecondary },
  postureHalf: { flex: 1, flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.md, minHeight: 64 },
  postureHalfDivider: { borderLeftWidth: 0.5, borderLeftColor: c.divider },
  postureHalfIcon: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  postureHalfTitle: { fontFamily: fonts.textSemibold, fontSize: 13, lineHeight: 18, color: c.onSurface },
  postureHalfLine: { fontFamily: fonts.text, fontSize: 12, lineHeight: 16, color: c.onSurfaceSecondary },

  // ── Section headers ──
  sectionHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, marginTop: spacing.md, marginBottom: spacing.sm },
  sectionTitle: { fontFamily: fonts.displayBold, fontSize: 17, color: c.onSurface },
  sectionLink: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.brand },

  // ── Priority alert card ──
  alertCard: {
    marginHorizontal: spacing.lg, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.sm,
    backgroundColor: "rgba(217,83,79,0.06)", borderWidth: 0.25, borderColor: "rgba(217,83,79,0.18)",
  },
  alertTop: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  alertIconWrap: { width: 36, height: 36, borderRadius: 18, backgroundColor: "rgba(217,83,79,0.14)", alignItems: "center", justifyContent: "center" },
  alertBadge: { backgroundColor: "rgba(217,83,79,0.14)", borderRadius: 4, paddingHorizontal: 6, paddingVertical: 2 },
  alertBadgeText: { fontFamily: fonts.textSemibold, fontSize: 10, color: c.barking, letterSpacing: 0.5, textTransform: "uppercase" },
  alertTime: { fontFamily: fonts.text, fontSize: 11, color: c.onSurfaceSecondary, marginLeft: "auto" },
  alertTitle: { fontFamily: fonts.displayBold, fontSize: 15, color: c.onSurface },
  alertDesc: { fontFamily: fonts.text, fontSize: 13, lineHeight: 19, color: c.onSurfaceSecondary },
  alertBtn: {
    borderRadius: radius.sm, borderWidth: 0.25, borderColor: c.barking,
    paddingVertical: spacing.sm, paddingHorizontal: spacing.lg,
    alignItems: "center", alignSelf: "flex-start", marginTop: spacing.xs,
  },
  alertBtnText: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.barking },

  // ── Activity row ──
  activityCard: {
    marginHorizontal: spacing.lg, borderRadius: radius.lg, padding: spacing.lg,
    backgroundColor: c.surfaceSecondary, borderWidth: 0.25, borderColor: c.border,
    flexDirection: "row", alignItems: "center", gap: spacing.md,
  },
  activityIconWrap: { width: 36, height: 36, borderRadius: 18, backgroundColor: c.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  activityContent: { flex: 1, gap: 2 },
  activityText: { fontFamily: fonts.textMedium, fontSize: 14, color: c.onSurface },
  activitySub: { fontFamily: fonts.text, fontSize: 12, color: c.onSurfaceSecondary },
  threatLine1: { fontFamily: fonts.textSemibold, fontSize: 14, lineHeight: 20, color: c.onSurface },
  threatLine2: { fontFamily: fonts.text, fontSize: 13, lineHeight: 18, color: c.onSurfaceSecondary },
  findingLink: { fontFamily: fonts.textSemibold, fontSize: 12, color: c.brand },
}));


export default function Home() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { width: screenW } = useWindowDimensions();
  const compact = screenW < 380;
  const { resolution, capabilities, protection, events, showToast, identityReset, reRegisterDevice, refresh, refreshCases } = useApollo();
  const isNew = useNewCases();
  // Pull down to fetch the newest cases now.
  const [pulling, setPulling] = React.useState(false);
  const onPull = React.useCallback(() => {
    setPulling(true);
    void refreshCases().catch(() => undefined).finally(() => setPulling(false));
  }, [refreshCases]);
  // One overall answer, decided by the Protection Posture engine — the Protection screen shows the same one.
  const { posture, apolloLine, deviceLine, health } = useProtectionPosture();
  const posturePalette = postureColors(posture.status, colors);
  const { recovery, dismiss: dismissRecovery } = useRecoveryTracker(protection?.operational);

  // ── Refresh data whenever Home regains focus (e.g. after handling an item) ──
  useFocusEffect(
    React.useCallback(() => {
      void refresh(0);
    }, [refresh])
  );

  // ── Auto-retrofit on first load ──
  const [showRetrofit, setShowRetrofit] = React.useState(false);
  React.useEffect(() => {
    hasRetrofitRun().then((done) => {
      if (!done) setShowRetrofit(true);
    });
  }, []);

  const attention = React.useMemo(
    () => (health.checking ? [] : buildHomeAttention({ gates: health.gates, events })),
    [health.checking, health.gates, events],
  );

  const voice = React.useMemo(
    () => buildHomeVoice({ resolution, attention, gates: health.gates, capabilities }),
    [resolution, attention, health.gates, capabilities],
  );

  // Everything that needs the person right now, as two-line Higgins briefings Apollo cycles through. An email you
  // submitted keeps its sender and subject only in the original on this device, so those are read from there.
  const heroCases = React.useMemo(() => heroEvents(attention, resolution.drivingEvent, resolution.state), [attention, resolution.drivingEvent, resolution.state]);
  // "Important for you" uses the same briefing (with more room), so its cases' kept originals are read too.
  const priorityThreats = React.useMemo(() => buildPriorityThreats(events), [events]);
  // Most recent consumer event for the "Recent activity" section (shown as the same card as "Important for you").
  const recentEvent = React.useMemo(() => events.find(isConsumerPatrolEvent) ?? null, [events]);
  const keptCases = React.useMemo(() => {
    const byId = new Map([...heroCases, ...priorityThreats, ...(recentEvent ? [recentEvent] : [])].map((e) => [e.event_id, e]));
    return [...byId.values()];
  }, [heroCases, priorityThreats, recentEvent]);
  const [kept, setKept] = React.useState<Record<string, KeptIdentifiers | null>>({});
  React.useEffect(() => {
    let active = true;
    const load = () => void Promise.all(keptCases.map(async (e) => {
      const src = await getCaseOriginal([e.event_id, e.investigation_case_id]);
      return [e.event_id, keptIdentifiers(src)] as const;
    })).then((pairs) => { if (active) setKept(Object.fromEntries(pairs)); });
    load();
    const unsubscribe = subscribeOriginalSource(load);
    return () => { active = false; unsubscribe(); };
  }, [keptCases]);
  const heroLines = React.useMemo(
    () => buildHeroBriefs({ voice, attention, drivingEvent: resolution.drivingEvent, state: resolution.state, kept }),
    [voice, attention, resolution.drivingEvent, resolution.state, kept],
  );
  const [heroIndex, setHeroIndex] = React.useState(0);
  React.useEffect(() => { setHeroIndex(0); }, [heroLines.length]);
  React.useEffect(() => {
    if (heroLines.length < 2) return;
    const timer = setInterval(() => setHeroIndex((i) => (i + 1) % heroLines.length), 7000);
    return () => clearInterval(timer);
  }, [heroLines.length]);
  const heroLine = heroLines[Math.min(heroIndex, heroLines.length - 1)] ?? heroLines[0];

  // Swipe left/right to move between the things needing attention.
  const stepHero = React.useCallback((delta: number) => {
    setHeroIndex((i) => {
      const count = heroLines.length;
      if (count < 2) return 0;
      return (i + delta + count) % count;
    });
  }, [heroLines.length]);
  const heroSwipe = React.useMemo(
    () => Gesture.Pan()
      .activeOffsetX([-20, 20])
      .failOffsetY([-14, 14])
      .onEnd((e) => {
        if (e.translationX <= -40) runOnJS(stepHero)(1);
        else if (e.translationX >= 40) runOnJS(stepHero)(-1);
      }),
    [stepHero],
  );

  const state = resolution.state;
  const stateLabel = STATE_LABEL[state] ?? "Apollo is Patrolling";
  const statusColor = toneColor(colors, state);
  const gif = STATE_GIF[state];
  const heroBg = STATE_BG[state] ?? STATE_BG.resting;

  return (
    <View style={s.root}>
      {/* ── Branded Header ── */}
      <View style={[s.header, compact && { paddingHorizontal: spacing.lg }, { paddingTop: insets.top + spacing.sm }]}>
        <View style={s.headerRow}>
          <Image
            source={require("@/assets/images/apollosg-wordmark.png")}
            style={{ width: Math.min(screenW * 0.58, 280) * (screenW < 600 ? 0.75 : 1), aspectRatio: 1200 / 282 }}
            accessibilityLabel="ApolloSG"
            contentFit="contain"
            testID="home-brand-title"
          />
          <View style={{ flexDirection: "row", alignItems: "center", gap: 2 }}>
            <AlertsButton testID="home-alerts" />
            <AppMenuButton testID="home-menu" />
          </View>
        </View>
        <Text style={[s.brandSubtitle, { fontSize: Math.max(9, Math.min(11, screenW * 0.028)) }]}>Better Protection. Safer You. Safer Tomorrows.</Text>
      </View>

      <ScrollView contentContainerStyle={s.scroll} testID="home-scroll" showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={pulling} onRefresh={onPull} tintColor={colors.brand} colors={[colors.brand]} />}>
        {/* ── Hero Status Card ── */}
        <GestureDetector gesture={heroSwipe}>
        <Pressable
          testID="home-hero-card"
          accessibilityRole="button"
          accessibilityLabel={`${stateLabel}. ${heroLine?.line1 ?? ""} ${heroLine?.line2 ?? ""}`.trim()}
          accessibilityHint="Opens the full case"
          onPress={() => { const route = heroLine?.route ?? voice.ctaRoute; return route ? router.push(route as any) : null; }}
          style={[s.heroCard, compact && { marginHorizontal: spacing.lg }]}
        >
          {/* The artwork is a 3:1 landscape. It is laid out as a full-width band pinned to the bottom of
              the card and sized BY ITS OWN PROPORTIONS (aspectRatio), so every device shows the whole
              picture undistorted and uncropped however tall the card grows. A vertical wash blends the
              top of the band into the card colour, and the horizontal wash keeps the text readable. */}
          <View style={s.heroBgBand} pointerEvents="none">
            <Image
              source={heroBg}
              style={s.heroBgImage}
              contentFit="cover"
              testID="home-hero-bg"
            />
            <LinearGradient
              colors={["#E8F5EE", "rgba(232,245,238,0.55)", "transparent"]}
              start={{ x: 0, y: 0 }}
              end={{ x: 0, y: 1 }}
              locations={[0, 0.35, 1]}
              style={s.heroBandFade}
            />
          </View>
          <LinearGradient
            colors={["rgba(232,245,238,0.95)", "rgba(232,245,238,0.72)", "rgba(232,245,238,0.18)", "transparent"]}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 0 }}
            locations={[0, 0.55, 0.85, 1]}
            style={s.heroGradient}
          />
          <View style={[s.heroOverlay, compact && { padding: spacing.md }]}>
            {/* Apollo + his state on one row; the line he's saying runs the full width underneath. */}
            <View style={s.heroTopRow}>
              <View style={[s.heroImageWrap, compact && { width: 68, height: 68, borderRadius: 34 }]}>
                <Image
                  source={gif ? gif.src : FALLBACK_IMAGE}
                  style={[s.heroImage, compact && { width: 68, height: 68 }]}
                  contentFit="cover"
                  autoplay
                  accessibilityLabel={gif?.label ?? "Apollo"}
                  testID="home-hero-gif"
                />
              </View>
              <View style={s.heroStatusRow}>
                <ShieldCheck size={compact ? 14 : 16} color="#FFFFFF" fill={statusColor} style={s.heroShield} />
                <Text style={[s.heroStatusText, compact && { fontSize: 15 }, { color: colors[`${state}Text` as keyof typeof colors] as string || colors.restingText }]} numberOfLines={2}>{stateLabel}</Text>
              </View>
            </View>
            {/* Higgins' two-line briefing: what it is and what was found, then when and what to do. */}
            <View style={s.heroBrief} testID="home-hero-voice">
              {/* Line 1 may wrap on a phone; it's never cut short, so the finding at its end always shows. */}
              <Text style={[s.heroLine1, compact && { fontSize: 13, lineHeight: 18 }]} numberOfLines={3} testID="home-hero-line1">{heroLine?.line1}</Text>
              <Text style={[s.heroLine2, compact && { fontSize: 12, lineHeight: 17 }]} numberOfLines={2} testID="home-hero-line2">{heroLine?.line2}</Text>
            </View>
          </View>
        </Pressable>
        </GestureDetector>
        {heroLines.length > 1 ? (
          <Pressable
            onPress={() => setHeroIndex((i) => (i + 1) % heroLines.length)}
            hitSlop={10}
            accessibilityRole="button"
            accessibilityLabel={`Item ${heroIndex + 1} of ${heroLines.length}. Tap to see the next one.`}
            style={s.heroDotsRow}
            testID="home-hero-dots"
          >
            {heroLines.map((line, i) => (
              <View key={line.id} style={[s.heroDot, i === heroIndex && s.heroDotActive]} />
            ))}
            <Text style={s.heroDotsLabel}>{heroIndex + 1} of {heroLines.length}</Text>
          </Pressable>
        ) : null}

        {/* A Device Protection changed since the person last looked — stays until they open it. */}
        <ProtectionChangeBanner style={{ marginHorizontal: spacing.xl, marginTop: spacing.sm }} testID="home-protection-change" />

        {/* Recovery banner */}
        <View style={{ paddingHorizontal: spacing.xl, marginTop: spacing.sm }}>
          <RecoveryBanner recovery={recovery} onDismiss={dismissRecovery} testID="home-recovery-banner" />
        </View>

        {/* ── Your protection — the overall answer, then Apollo's protections and the device's own ── */}
        <View style={[s.postureCard, { backgroundColor: posturePalette.wash, borderColor: posturePalette.tint }]} testID="home-posture-card">
          <Pressable
            testID="home-posture"
            accessibilityRole="button"
            accessibilityLabel={`Your protection: ${posture.title}. ${posture.reason}`}
            accessibilityHint="Opens Protection"
            onPress={() => router.push("/(tabs)/protection")}
            style={({ pressed }) => [s.postureTop, { opacity: pressed ? 0.85 : 1 }]}
          >
            <View style={{ flex: 1 }}>
              <PostureSummary posture={posture} hideReason testID="home-posture-summary" />
            </View>
            <ChevronRight size={20} color={colors.onSurface} />
          </Pressable>
          <View style={s.postureHalves}>
            <Pressable
              testID="home-protection-card"
              accessibilityRole="button"
              accessibilityLabel={`Apollo protections. ${apolloLine}.`}
              onPress={() => router.push("/(tabs)/protection")}
              style={({ pressed }) => [s.postureHalf, { opacity: pressed ? 0.85 : 1 }]}
            >
              <View style={[s.postureHalfIcon, { backgroundColor: colors.navyTint }]}>
                <ShieldCheck size={18} color={colors.brand} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[s.postureHalfTitle, compact && { fontSize: 12 }]}>Apollo protections</Text>
                <Text style={s.postureHalfLine} testID="home-protection-summary">{apolloLine}</Text>
              </View>
            </Pressable>
            <Pressable
              testID="home-device-card"
              accessibilityRole="button"
              accessibilityLabel={`Device protections. ${deviceLine}.`}
              onPress={() => router.push("/(tabs)/protection?tab=device")}
              style={({ pressed }) => [s.postureHalf, s.postureHalfDivider, { opacity: pressed ? 0.85 : 1 }]}
            >
              <View style={[s.postureHalfIcon, { backgroundColor: colors.goldTint }]}>
                <Smartphone size={18} color={colors.gold} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[s.postureHalfTitle, compact && { fontSize: 12 }]}>Device protections</Text>
                <Text style={s.postureHalfLine} testID="home-device-summary">{deviceLine}</Text>
              </View>
            </Pressable>
          </View>
        </View>

        {/* ── Important For You — priority subset of Threats + one scam alert ── */}
        {(() => {
          // Section shows if there are personal threats OR if PriorityScamNotice will render
          // (PriorityScamNotice handles its own data loading — renders null if no alert)
          return (
            <View>
              <View style={[s.sectionHeader, compact && { paddingHorizontal: spacing.lg }]}>
                <Text style={[s.sectionTitle, compact && { fontSize: 15 }]}>Important for you</Text>
                <Pressable onPress={() => router.push("/(tabs)/patrol")} hitSlop={8}>
                  <Text style={s.sectionLink}>View all</Text>
                </Pressable>
              </View>

              {/* Personal threats first — these take precedence. Each card has the hero's two-line structure, with more
                  room: what it is, where it came from and what was found; then when, and Higgins' recommendation. */}
              {priorityThreats.map((event) => (
                <ThreatCard key={event.event_id} event={event} kept={kept[event.event_id] ?? null} isNew={isNew(event)} compact={compact} testID={`home-threat-${event.event_id}`} />
              ))}

              {/* One highest-priority scam alert — after personal threats */}
              <PriorityScamNotice compact />
            </View>
          );
        })()}

        {/* ── Recent Activity ── */}
        <View>
          <View style={[s.sectionHeader, compact && { paddingHorizontal: spacing.lg }]}>
            <Text style={[s.sectionTitle, compact && { fontSize: 15 }]}>Recent activity</Text>
            <Pressable onPress={() => router.push("/(tabs)/patrol")} hitSlop={8}>
              <Text style={s.sectionLink}>View all</Text>
            </Pressable>
          </View>
          {recentEvent ? (
            <ThreatCard event={recentEvent} kept={kept[recentEvent.event_id] ?? null} isNew={isNew(recentEvent)} compact={compact} testID="home-recent-activity" />
          ) : (
            <View style={s.activityCard} testID="home-no-recent-activity">
              <View style={s.activityIconWrap}>
                <ShieldCheck size={16} color={colors.resting} />
              </View>
              <View style={s.activityContent}>
                <Text style={s.activityText}>No recent activity</Text>
                <Text style={s.activitySub}>Apollo is patrolling quietly. Nothing to report.</Text>
              </View>
            </View>
          )}
        </View>

        {/* ── Utility banners (compact) ── */}
        <View style={{ paddingHorizontal: spacing.lg, gap: spacing.sm, marginTop: spacing.md }}>
          {identityReset ? (
            <Card style={{ gap: spacing.sm, borderColor: colors.barking }} testID="identity-reset-card">
              <Text style={{ fontFamily: fonts.displayBold, fontSize: 15, color: colors.brand }}>ApolloSG needs to re-register this phone</Text>
              <Body testID="identity-reset-why">{identityReset}</Body>
              <Button testID="identity-reset-register" label="Register this phone again" onPress={() => void reRegisterDevice().catch((e: Error) => showToast(e.message, "barking"))} />
            </Card>
          ) : null}
          <ServiceBanner />
          <HigginsFollowUp />
          <ClipboardLinkBanner />
        </View>

      </ScrollView>
      <RetrofitModal visible={showRetrofit} onClose={() => setShowRetrofit(false)} auto />
    </View>
  );
}

/** One case as Home shows it — in "Important for you" and in "Recent activity" alike: what it is, where it came from
 *  and what was found; then when, and Higgins' recommendation; its status and "View threat". */
function ThreatCard({ event, kept, isNew, compact, testID }: { event: PatrolEvent; kept: KeptIdentifiers | null; isNew: boolean; compact: boolean; testID: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const si = threatSourceIcon(event.category, event.source_metadata);
  const IconEl = si.Icon;
  const status = threatCaseStatus(event);
  const statusColor = STATUS_COLORS[status];
  const brief = eventBrief(event, new Date(), kept, "card");
  return (
    <Pressable
      testID={testID}
      onPress={() => router.push(`/patrol/${encodeURIComponent(event.event_id)}` as any)}
      accessibilityRole="button"
      accessibilityLabel={`${isNew ? "New. " : ""}${brief.line1} ${brief.line2} ${STATUS_LABELS[status]}.`}
      accessibilityHint="Opens the full case"
      style={[s.activityCard, compact && { marginHorizontal: spacing.lg, padding: spacing.md }, { marginBottom: spacing.sm, alignItems: "flex-start" }]}
    >
      <View style={[s.activityIconWrap, compact && { width: 28, height: 28, borderRadius: 14 }, { backgroundColor: si.bg }]}>
        <IconEl size={compact ? 14 : 16} color={si.fg} />
      </View>
      <View style={{ flex: 1, gap: spacing.xs }}>
        <Text style={[s.threatLine1, compact && { fontSize: 13, lineHeight: 18 }]} numberOfLines={4} testID={`${testID}-line1`}>{brief.line1}</Text>
        <Text style={[s.threatLine2, compact && { fontSize: 12, lineHeight: 17 }]} numberOfLines={3} testID={`${testID}-line2`}>{brief.line2}</Text>
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: 2 }}>
          {isNew ? <NewBadge testID={`${testID}-new`} /> : null}
          <View style={{ paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.pill, backgroundColor: statusColor.bg }}>
            <Text style={{ fontFamily: fonts.textSemibold, fontSize: 10, color: statusColor.text }} testID={`${testID}-status`}>{STATUS_LABELS[status]}</Text>
          </View>
          <View style={{ flex: 1 }} />
          <Text style={s.findingLink}>View threat</Text>
          <ChevronRight size={14} color={colors.brand} />
        </View>
      </View>
    </Pressable>
  );
}
