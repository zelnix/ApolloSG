/**
 * PhoneIdentityCard — displays who a phone number belongs to.
 *
 * Shows: associated entity, confidence badge, evidence sources, spoofing awareness.
 * Designed to sit inside the Check a Number result screen (call-guard.tsx).
 */

import Building from "lucide-react-native/icons/building";
import CircleCheck from "lucide-react-native/icons/circle-check";
import CircleQuestionMark from "lucide-react-native/icons/circle-question-mark";
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

const CONFIDENCE_DESCRIPTION: Record<Confidence, string> = {
  verified: "This number is published on the organisation's own website.",
  strong: "Multiple independent sources associate this number with this organisation.",
  possible: "One or more sources mention this number, but it hasn't been confirmed on official channels.",
  unknown: "Apollo couldn't determine who this number belongs to from its available sources.",
  conflicting: "Different sources name different organisations for this number. Treat the caller's identity as unverified.",
};

/* ── Styles ────────────────────────────────────────────────────────────────── */

const useStyles = makeStyles((c) => ({
  card: {
    backgroundColor: c.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.md,
    borderWidth: 0.5,
    borderColor: c.border,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  iconWell: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
  },
  headerText: {
    flex: 1,
    gap: 2,
  },
  title: {
    fontFamily: fonts.displayBold,
    fontSize: 14,
    letterSpacing: 0.5,
    textTransform: "uppercase" as const,
    color: c.muted,
  },
  entity: {
    fontFamily: fonts.displayBold,
    fontSize: 18,
    color: c.onSurface,
  },
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
    fontSize: 14,
    lineHeight: 20,
    color: c.onSurfaceSecondary,
  },
  spoofing: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: c.growlingWash,
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 0.5,
    borderColor: c.growling,
  },
  spoofingText: {
    flex: 1,
    fontFamily: fonts.textSemibold,
    fontSize: 13,
    lineHeight: 18,
    color: c.growlingText,
  },
  scamIntel: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: c.barkingWash,
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 0.5,
    borderColor: c.barking,
  },
  scamText: {
    flex: 1,
    fontFamily: fonts.textSemibold,
    fontSize: 13,
    lineHeight: 18,
    color: c.barkingText,
  },
  evidenceSection: {
    gap: spacing.xs,
  },
  evidenceLabel: {
    fontFamily: fonts.textSemibold,
    fontSize: 12,
    color: c.muted,
    letterSpacing: 0.3,
    textTransform: "uppercase" as const,
  },
  evidenceRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.xs,
  },
  evidenceDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  evidenceText: {
    flex: 1,
    fontFamily: fonts.text,
    fontSize: 13,
    color: c.onSurfaceSecondary,
  },
  evidenceLink: {
    fontFamily: fonts.text,
    fontSize: 12,
    color: c.brandPrimary,
    textDecorationLine: "underline" as const,
  },
  details: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
  },
  detailChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingVertical: 4,
    paddingHorizontal: spacing.sm,
    backgroundColor: c.surfaceTertiary,
    borderRadius: radius.sm,
  },
  detailText: {
    fontFamily: fonts.text,
    fontSize: 12,
    color: c.onSurfaceSecondary,
  },
  loadingWrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.lg,
  },
  loadingText: {
    fontFamily: fonts.text,
    fontSize: 14,
    color: c.muted,
  },
  freshness: {
    fontFamily: fonts.text,
    fontSize: 11,
    color: c.muted,
    alignSelf: "flex-end",
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

  useEffect(() => {
    if (!number || number.replace(/[\s\-()]/g, "").length < 7) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    identifyNumber(number, country)
      .then((r) => { if (!cancelled) setResult(r); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : "Could not identify this number."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [number, country]);

  if (loading) {
    return (
      <View style={s.card} testID={testID}>
        <View style={s.loadingWrap}>
          <ActivityIndicator size="small" color={colors.muted} />
          <Text style={s.loadingText}>Identifying number…</Text>
        </View>
      </View>
    );
  }

  if (error || !result) return null;

  const { associated_entity, association_confidence, evidence, scam_intel, known_impersonation, number_type, network, geographic, freshness } = result;

  const badgeColors = confidenceBadgeColors(association_confidence, colors);
  const ConfidenceIcon = confidenceIcon(association_confidence);

  return (
    <View style={s.card} testID={testID}>
      {/* Header: icon + entity name */}
      <View style={s.header}>
        <View style={[s.iconWell, { backgroundColor: badgeColors.tint }]}>
          {associated_entity ? (
            <Building size={20} color={badgeColors.fg} />
          ) : (
            <CircleQuestionMark size={20} color={colors.muted} />
          )}
        </View>
        <View style={s.headerText}>
          <Text style={s.title}>Caller identity</Text>
          <Text style={s.entity} testID={testID ? `${testID}-entity` : undefined}>
            {associated_entity ?? "Unknown caller"}
          </Text>
        </View>
      </View>

      {/* Confidence badge */}
      <View style={[s.badge, { backgroundColor: badgeColors.tint }]}>
        <ConfidenceIcon size={14} color={badgeColors.fg} />
        <Text style={[s.badgeText, { color: badgeColors.fg }]} testID={testID ? `${testID}-confidence` : undefined}>
          {CONFIDENCE_LABEL[association_confidence]}
        </Text>
      </View>

      {/* Description */}
      <Text style={s.description}>{CONFIDENCE_DESCRIPTION[association_confidence]}</Text>

      {/* Spoofing awareness (always shown for identified numbers) */}
      {associated_entity && association_confidence !== "verified" ? (
        <View style={s.spoofing} testID={testID ? `${testID}-spoofing` : undefined}>
          <TriangleAlert size={16} color={colors.growlingText} />
          <Text style={s.spoofingText}>
            Caller ID can be spoofed. Even when a number is associated with an organisation, verify the caller independently before sharing sensitive information.
          </Text>
        </View>
      ) : null}

      {/* Known impersonation warning */}
      {known_impersonation ? (
        <View style={s.scamIntel} testID={testID ? `${testID}-impersonation` : undefined}>
          <ShieldAlert size={16} color={colors.barkingText} />
          <Text style={s.scamText}>
            This number is not published by the organisation it claims to be from. It may be spoofing a legitimate organisation.
          </Text>
        </View>
      ) : null}

      {/* Scam intel */}
      {scam_intel ? (
        <View style={s.scamIntel} testID={testID ? `${testID}-scam` : undefined}>
          <ShieldAlert size={16} color={colors.barkingText} />
          <Text style={s.scamText}>{scam_intel}</Text>
        </View>
      ) : null}

      {/* Evidence sources */}
      {evidence.length > 0 ? (
        <View style={s.evidenceSection}>
          <Text style={s.evidenceLabel}>Sources</Text>
          {evidence.map((e, i) => (
            <View key={`${e.source}-${i}`} style={s.evidenceRow}>
              <View style={[s.evidenceDot, { backgroundColor: tierDotColor(e.source_type, colors) }]} />
              <Text style={s.evidenceText} numberOfLines={1}>
                {e.publisher}{e.claim !== e.publisher ? ` — ${e.claim}` : ""}
              </Text>
              {e.source.startsWith("http") ? (
                <Pressable onPress={() => Linking.openURL(e.source)} accessibilityRole="link" hitSlop={8}>
                  <Text style={s.evidenceLink}>View</Text>
                </Pressable>
              ) : null}
            </View>
          ))}
        </View>
      ) : null}

      {/* Detail chips */}
      <View style={s.details}>
        {number_type ? <View style={s.detailChip}><Text style={s.detailText}>{number_type}</Text></View> : null}
        {network ? <View style={s.detailChip}><Text style={s.detailText}>{network}</Text></View> : null}
        {geographic ? <View style={s.detailChip}><Text style={s.detailText}>{geographic}</Text></View> : null}
      </View>

      {/* Freshness indicator */}
      {freshness ? (
        <Text style={s.freshness}>
          {freshness === "fresh" ? "Just checked" : freshness === "cached" ? "Cached result" : "Stale — rechecking soon"}
        </Text>
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
