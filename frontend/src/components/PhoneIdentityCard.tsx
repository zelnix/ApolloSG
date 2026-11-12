/**
 * PhoneIdentityCard — Who Called: compact inline card identifying a phone number.
 *
 * Default: single-row summary (icon + entity/number + confidence chip).
 * Expanded on tap: Higgins explanation, evidence, spoofing, detail chips.
 * Designed to sit contextually alongside Higgins' explanation, never dominating it.
 */

import Building from "lucide-react-native/icons/building";
import ChevronDown from "lucide-react-native/icons/chevron-down";
import ChevronUp from "lucide-react-native/icons/chevron-up";
import CircleCheck from "lucide-react-native/icons/circle-check";
import CircleQuestionMark from "lucide-react-native/icons/circle-question-mark";
import Globe from "lucide-react-native/icons/globe";
import Layers from "lucide-react-native/icons/layers";
import Phone from "lucide-react-native/icons/phone";
import ShieldAlert from "lucide-react-native/icons/shield-alert";
import TriangleAlert from "lucide-react-native/icons/triangle-alert";
import React, { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Linking,
  Pressable,
  Text,
  View,
} from "react-native";

import { identifyNumber, type PhoneIdentityResult } from "@/src/api/phoneIdentity";
import { CallerIdentityAvatar } from "@/src/components/CallerIdentityAvatar";
import { callerAvatarForIdentity } from "@/src/domain/callerAvatar";
import { explainIdentity, TIER_LABELS, type IdentityExplanation, type TierExplanation } from "@/src/domain/phoneIdentityExplanation";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

/* ── Confidence display mapping ───────────────────────────────────────────── */

type Confidence = PhoneIdentityResult["association_confidence"];

const CONFIDENCE_LABEL: Record<Confidence, string> = {
  verified: "Verified owner",
  strong: "Strong match",
  possible: "Possible match",
  unknown: "Unknown",
  conflicting: "Conflicting info",
};

/* ── Styles ────────────────────────────────────────────────────────────────── */

const useStyles = makeStyles((c) => ({
  /* ── Compact (always visible) ──────────────────────────────────────────── */
  compact: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: c.surfaceSecondary,
    borderRadius: radius.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderWidth: 0.5,
    borderColor: c.border,
  },
  compactHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    minHeight: 44,
  },
  compactIcon: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: "center",
    justifyContent: "center",
  },
  compactBody: {
    flex: 1,
    gap: 1,
  },
  compactLabel: {
    fontFamily: fonts.textSemibold,
    fontSize: 11,
    letterSpacing: 0.3,
    textTransform: "uppercase" as const,
    color: c.muted,
  },
  compactEntity: {
    fontFamily: fonts.displayBold,
    fontSize: 15,
    color: c.onSurface,
  },
  compactMuted: {
    flex: 1,
    fontFamily: fonts.text,
    fontSize: 13,
    color: c.muted,
  },
  compactLink: {
    fontFamily: fonts.textSemibold,
    fontSize: 13,
  },
  chipSmall: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    paddingVertical: 3,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.pill,
  },
  chipText: {
    fontFamily: fonts.textSemibold,
    fontSize: 10,
  },

  /* ── Card (wraps compact header + expanded body) ───────────────────────── */
  card: {
    backgroundColor: c.surfaceSecondary,
    borderRadius: radius.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
    borderWidth: 0.5,
    borderColor: c.border,
  },
  expandedBody: {
    gap: spacing.md,
    paddingTop: spacing.sm,
    borderTopWidth: 0.5,
    borderTopColor: c.border,
  },

  /* ── Expanded sections (reused from before, tightened) ─────────────────── */
  badge: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: radius.pill,
    alignSelf: "flex-start",
  },
  badgeText: {
    fontFamily: fonts.textSemibold,
    fontSize: 13,
  },
  description: {
    fontFamily: fonts.text,
    fontSize: 13,
    lineHeight: 19,
    color: c.onSurfaceSecondary,
  },
  spoofing: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: c.growlingWash,
    borderRadius: radius.md,
    padding: spacing.sm,
    borderWidth: 0.5,
    borderColor: c.growling,
  },
  spoofingText: {
    flex: 1,
    fontFamily: fonts.textSemibold,
    fontSize: 12,
    lineHeight: 17,
    color: c.growlingText,
  },
  scamIntel: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: c.barkingWash,
    borderRadius: radius.md,
    padding: spacing.sm,
    borderWidth: 0.5,
    borderColor: c.barking,
  },
  scamText: {
    flex: 1,
    fontFamily: fonts.textSemibold,
    fontSize: 12,
    lineHeight: 17,
    color: c.barkingText,
  },
  evidenceSection: {
    gap: spacing.xs,
  },
  evidenceLabel: {
    fontFamily: fonts.textSemibold,
    fontSize: 11,
    color: c.muted,
    letterSpacing: 0.3,
    textTransform: "uppercase" as const,
  },
  evidenceRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: 2,
  },
  evidenceDot: {
    width: 5,
    height: 5,
    borderRadius: 3,
  },
  evidenceText: {
    flex: 1,
    fontFamily: fonts.text,
    fontSize: 12,
    color: c.onSurfaceSecondary,
  },
  evidenceLink: {
    fontFamily: fonts.text,
    fontSize: 11,
    color: c.brandPrimary,
    textDecorationLine: "underline" as const,
  },
  details: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.xs,
  },
  detailChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingVertical: 3,
    paddingHorizontal: spacing.sm,
    backgroundColor: c.surfaceTertiary,
    borderRadius: radius.sm,
  },
  detailText: {
    fontFamily: fonts.text,
    fontSize: 11,
    color: c.onSurfaceSecondary,
  },
  higginsSection: {
    gap: spacing.xs,
  },
  higginsLabel: {
    fontFamily: fonts.textSemibold,
    fontSize: 11,
    letterSpacing: 0.3,
    textTransform: "uppercase" as const,
    color: c.muted,
  },
  higginsBody: {
    fontFamily: fonts.text,
    fontSize: 13,
    lineHeight: 19,
    color: c.onSurface,
  },
  whatToDo: {
    gap: spacing.xs,
    backgroundColor: c.surfaceTertiary,
    borderRadius: radius.md,
    padding: spacing.sm,
  },
  whatToDoLabel: {
    fontFamily: fonts.textSemibold,
    fontSize: 11,
    letterSpacing: 0.3,
    textTransform: "uppercase" as const,
    color: c.muted,
  },
  whatToDoText: {
    fontFamily: fonts.textSemibold,
    fontSize: 13,
    lineHeight: 19,
    color: c.onSurface,
  },
  freshness: {
    fontFamily: fonts.text,
    fontSize: 10,
    color: c.muted,
    alignSelf: "flex-end",
  },
  /* ── Progressive Intelligence Tiers ────────────────────────────────────── */
  tiersSection: {
    gap: spacing.sm,
  },
  tiersLabel: {
    fontFamily: fonts.textSemibold,
    fontSize: 11,
    letterSpacing: 0.3,
    textTransform: "uppercase" as const,
    color: c.muted,
  },
  tierRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    backgroundColor: c.surfaceTertiary,
    borderRadius: radius.sm,
  },
  tierIcon: {
    width: 24,
    height: 24,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 1,
  },
  tierContent: {
    flex: 1,
    gap: 2,
  },
  tierLabel: {
    fontFamily: fonts.textSemibold,
    fontSize: 11,
    letterSpacing: 0.3,
    textTransform: "uppercase" as const,
  },
  tierHeadline: {
    fontFamily: fonts.text,
    fontSize: 13,
    lineHeight: 18,
    color: c.onSurface,
  },
  tierDetail: {
    fontFamily: fonts.text,
    fontSize: 12,
    lineHeight: 17,
    color: c.onSurfaceSecondary,
  },
  tierQualifier: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    paddingVertical: 2,
    paddingHorizontal: spacing.xs,
    borderRadius: radius.sm,
    alignSelf: "flex-start",
  },
  tierQualifierText: {
    fontFamily: fonts.textSemibold,
    fontSize: 10,
  },
}));

/* ── Tier dot colour ──────────────────────────────────────────────────────── */

function tierDotColor(sourceType: string, colors: ReturnType<typeof useTheme>["colors"]): string {
  if (sourceType === "tier_1_official") return colors.resting;
  if (sourceType === "tier_2_government" || sourceType === "tier_3_regulatory") return colors.info;
  if (sourceType === "tier_4_web") return colors.growling;
  return colors.muted;
}

/* ── Component ─────────────────────────────────────────────────────────────── */

interface Props {
  /** Phone number to identify (E.164 or local). */
  number: string;
  /** 2-letter country code hint for local numbers. */
  country?: string;
  testID?: string;
}

export function PhoneIdentityCard({ number, country, testID }: Props) {
  const s = useStyles();
  const { colors } = useTheme();
  const [result, setResult] = useState<PhoneIdentityResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [expanded, setExpanded] = useState(false);

  const stripped = number?.replace(/[\s\-()]/g, "") ?? "";
  const valid = stripped.length >= 7;

  useEffect(() => {
    if (!number || !valid) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setResult(null);
    identifyNumber(number, country)
      .then((r) => { if (!cancelled) setResult(r); })
      .catch((e) => {
        const msg = e instanceof Error ? e.message : "Could not identify this number.";
        console.warn("[PhoneIdentityCard] identifyNumber failed:", msg);
        if (!cancelled) setError(msg);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [number, country, valid, attempt]);

  if (!number || !valid) return null;

  /* Loading state — compact spinner */
  if (loading) {
    return (
      <View style={s.compact} testID={testID}>
        <ActivityIndicator size="small" color={colors.muted} />
        <Text style={s.compactLabel}>Who Called</Text>
        <Text style={s.compactMuted}>Looking up…</Text>
      </View>
    );
  }

  /* Error / no result — compact retry */
  if (error || !result) {
    return (
      <View style={s.compact} testID={testID}>
        <View style={[s.compactIcon, { backgroundColor: colors.unknownTint }]}>
          <CircleQuestionMark size={14} color={colors.unknownText} />
        </View>
        <Text style={s.compactLabel}>Who Called</Text>
        <Text style={s.compactMuted} numberOfLines={1}>Lookup unavailable</Text>
        <Pressable onPress={() => setAttempt((a) => a + 1)} hitSlop={8}
          accessibilityRole="button" accessibilityLabel="Retry identity lookup">
          <Text style={[s.compactLink, { color: colors.brandPrimary }]}>Retry</Text>
        </Pressable>
      </View>
    );
  }

  const { associated_entity, association_confidence, evidence, number_type, network, geographic, freshness } = result;
  const badgeColors = confidenceBadgeColors(association_confidence, colors);
  const ConfidenceIcon = confidenceIcon(association_confidence);
  const explanation = explainIdentity(result);
  const Chevron = expanded ? ChevronUp : ChevronDown;

  return (
    <View style={s.card} testID={testID}>
      {/* ─ Compact header: always visible, tap to expand ─ */}
      <Pressable
        style={s.compactHeader}
        onPress={() => setExpanded((v) => !v)}
        accessibilityRole="button"
        accessibilityLabel={expanded ? "Collapse Who Called details" : "Expand Who Called details"}
      >
        <CallerIdentityAvatar kind={callerAvatarForIdentity(result)} />
        <View style={s.compactBody}>
          <Text style={s.compactLabel}>Who Called</Text>
          <Text style={s.compactEntity} numberOfLines={1} testID={testID ? `${testID}-entity` : undefined}>
            {associated_entity ?? "Unknown caller"}
          </Text>
        </View>
        <View style={[s.chipSmall, { backgroundColor: badgeColors.tint }]}>
          <ConfidenceIcon size={10} color={badgeColors.fg} />
          <Text style={[s.chipText, { color: badgeColors.fg }]}>{CONFIDENCE_LABEL[association_confidence]}</Text>
        </View>
        <Chevron size={16} color={colors.muted} />
      </Pressable>

      {/* ─ Expanded detail: only when tapped ─ */}
      {expanded ? (
        <View style={s.expandedBody}>
          {/* Higgins says */}
          <View style={s.higginsSection}>
            <Text style={s.higginsLabel}>Higgins says</Text>
            <Text style={s.higginsBody} testID={testID ? `${testID}-headline` : undefined}>{explanation.headline}</Text>
            <Text style={s.description}>{explanation.body}</Text>
          </View>

          {/* What to do */}
          <View style={s.whatToDo}>
            <Text style={s.whatToDoLabel}>What to do</Text>
            <Text style={s.whatToDoText} testID={testID ? `${testID}-advice` : undefined}>{explanation.whatToDo}</Text>
          </View>

          {/* Spoofing awareness */}
          {explanation.spoofing ? (
            <View style={s.spoofing} testID={testID ? `${testID}-spoofing` : undefined}>
              <TriangleAlert size={14} color={colors.growlingText} />
              <Text style={s.spoofingText}>{explanation.spoofing}</Text>
            </View>
          ) : null}

          {/* Known impersonation */}
          {explanation.impersonationWarning ? (
            <View style={s.scamIntel} testID={testID ? `${testID}-impersonation` : undefined}>
              <ShieldAlert size={14} color={colors.barkingText} />
              <Text style={s.scamText}>{explanation.impersonationWarning}</Text>
            </View>
          ) : null}

          {/* Scam intel */}
          {explanation.scamWarning ? (
            <View style={s.scamIntel} testID={testID ? `${testID}-scam` : undefined}>
              <ShieldAlert size={14} color={colors.barkingText} />
              <Text style={s.scamText}>{explanation.scamWarning}</Text>
            </View>
          ) : null}

          {/* Evidence sources */}
          {evidence.length > 0 ? (
            <View style={s.evidenceSection}>
              <Text style={s.evidenceLabel}>Sources</Text>
              {evidence.map((e, i) => (
                <View key={`${e.source}-${i}`} style={s.evidenceRow}>
                  <View style={[s.evidenceDot, { backgroundColor: tierDotColor(e.source_type, colors) }]} />
                  <Text style={s.evidenceText} numberOfLines={1}>{e.publisher}{e.claim !== e.publisher ? ` — ${e.claim}` : ""}</Text>
                  {e.source.startsWith("http") ? (
                    <Pressable onPress={() => Linking.openURL(e.source)} accessibilityRole="link" hitSlop={8}>
                      <Text style={s.evidenceLink}>View</Text>
                    </Pressable>
                  ) : null}
                </View>
              ))}
            </View>
          ) : null}

          {/* Progressive Intelligence Tiers */}
          {explanation.tiers.length > 0 ? (
            <View style={s.tiersSection} testID={testID ? `${testID}-tiers` : undefined}>
              <Text style={s.tiersLabel}>How Apollo investigated</Text>
              {explanation.tiers.map((tier, i) => (
                <TierRow key={`${tier.tier}-${i}`} tier={tier} colors={colors} s={s} testID={testID ? `${testID}-tier-${tier.tier}` : undefined} />
              ))}
            </View>
          ) : null}

          {/* Detail chips */}
          <View style={s.details}>
            {number_type ? <View style={s.detailChip}><Text style={s.detailText}>{number_type}</Text></View> : null}
            {network ? <View style={s.detailChip}><Text style={s.detailText}>{network}</Text></View> : null}
            {geographic ? <View style={s.detailChip}><Text style={s.detailText}>{geographic}</Text></View> : null}
          </View>

          {freshness ? (
            <Text style={s.freshness}>
              {freshness === "fresh" ? "Just checked" : freshness === "cached" ? "Cached result" : "Stale — rechecking soon"}
            </Text>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

/* ── Helpers ───────────────────────────────────────────────────────────────── */

function confidenceBadgeColors(confidence: Confidence, colors: ReturnType<typeof useTheme>["colors"]) {
  switch (confidence) {
    case "verified":
      return { tint: colors.restingTint, fg: colors.restingText };
    case "strong":
      return { tint: "rgba(79,175,131,0.12)", fg: colors.restingText };
    case "possible":
      return { tint: colors.growlingWash, fg: colors.growlingText };
    case "unknown":
      return { tint: colors.unknownTint, fg: colors.unknownText };
    case "conflicting":
      return { tint: colors.barkingTint, fg: colors.barkingText };
  }
}

function confidenceIcon(confidence: Confidence) {
  switch (confidence) {
    case "verified": return CircleCheck;
    case "strong": return CircleCheck;
    case "possible": return CircleQuestionMark;
    case "unknown": return CircleQuestionMark;
    case "conflicting": return TriangleAlert;
  }
}

/* ── Tier row component ───────────────────────────────────────────────────── */

const TIER_ICONS: Record<string, typeof Globe> = {
  geographic: Globe,
  number_block: Layers,
  caller: Phone,
};

function tierConfidenceColors(confidence: string, colors: ReturnType<typeof useTheme>["colors"]) {
  switch (confidence) {
    case "high":
      return { tint: colors.restingTint, fg: colors.restingText };
    case "medium":
      return { tint: "rgba(79,175,131,0.12)", fg: colors.restingText };
    case "low":
    default:
      return { tint: colors.unknownTint, fg: colors.unknownText };
  }
}

function TierRow({ tier, colors, s, testID }: {
  tier: TierExplanation;
  colors: ReturnType<typeof useTheme>["colors"];
  s: ReturnType<typeof useStyles>;
  testID?: string;
}) {
  const Icon = TIER_ICONS[tier.tier] ?? Globe;
  const badgeColors = tierConfidenceColors(tier.confidence, colors);
  const label = TIER_LABELS[tier.tier] ?? tier.tier;

  return (
    <View style={s.tierRow} testID={testID}>
      <View style={[s.tierIcon, { backgroundColor: badgeColors.tint }]}>
        <Icon size={13} color={badgeColors.fg} />
      </View>
      <View style={s.tierContent}>
        <Text style={[s.tierLabel, { color: badgeColors.fg }]}>{label}</Text>
        <Text style={s.tierHeadline}>{tier.headline}</Text>
        {tier.location ? <Text style={s.tierDetail}>Location: {tier.location}</Text> : null}
        {tier.detail ? <Text style={s.tierDetail}>{tier.detail}</Text> : null}
        {tier.businessUnits.length > 0 ? (
          <View style={{ gap: 2, marginTop: 2 }}>
            {tier.tier === "caller" ? (
              <Text style={[s.tierLabel, { marginBottom: 2, color: colors.onSurfaceSecondary }]}>What to do</Text>
            ) : null}
            {tier.businessUnits.map((bu, i) => (
              <Text key={i} style={s.tierDetail}>{"\u2022"} {bu}</Text>
            ))}
          </View>
        ) : null}
        {tier.callback ? <Text style={[s.tierDetail, { fontFamily: fonts.textSemibold }]}>Callback: {tier.callback}</Text> : null}
        {tier.callbackNote ? <Text style={[s.tierDetail, { fontStyle: "italic" }]}>{tier.callbackNote}</Text> : null}
        <View style={[s.tierQualifier, { backgroundColor: badgeColors.tint }]}>
          <Text style={[s.tierQualifierText, { color: badgeColors.fg }]}>{tier.qualifier}</Text>
        </View>
      </View>
    </View>
  );
}
