// The Detailed Findings Brief: the six required headers from the backend's Findings Brief data
// structure (Apollo PRD v2.2 Phase 5) — Finding, Findings Rating, What ApolloSG Found, Why This
// Matters, What Was Verified, Recommended Action. Collapsed by default (progressive disclosure)
// so the everyday mobile report above isn't overwhelmed by it. Nothing here is composed on the
// phone: every value shown is exactly what TC Hawkeye's result already established.
import React from "react";
import { Text, View } from "react-native";

import { CollapsibleSection } from "@/src/components/DiReport";
import type { FindingsBrief as FindingsBriefData } from "@/src/investigation/types";
import { fonts, makeStyles, spacing } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  block: { gap: spacing.xs },
  label: { fontFamily: fonts.textSemibold, fontSize: 12, letterSpacing: 0.4, color: c.muted, textTransform: "uppercase" as const },
  value: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface },
  bulletRow: { flexDirection: "row" as const, gap: spacing.xs, alignItems: "flex-start" as const },
  bulletMark: { fontFamily: fonts.text, fontSize: 15, color: c.onSurfaceSecondary },
  bulletText: { flex: 1, fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurfaceSecondary },
  tag: { fontFamily: fonts.textMedium, fontSize: 13, color: c.brandPrimary },
}));

export function DetailedFindingsBrief({ brief, ids }: { brief: FindingsBriefData; ids: string }) {
  const s = useStyles();
  const primary = brief.recommendedAction.primary;
  const additional = brief.recommendedAction.additional ?? [];
  const whatFound = brief.whatApolloFound ?? [];
  const limitations = brief.whatWasVerified?.limitations ?? [];

  return (
    <CollapsibleSection
      title="Detailed Findings Brief"
      subtitle={`${brief.finding} \u00B7 Findings Rating ${brief.findingsRating}/100`}
      testID={`${ids}-findings-brief`}
    >
      <View style={{ gap: spacing.lg }}>
        <View style={s.block} testID={`${ids}-brief-finding`}>
          <Text style={s.label}>Finding</Text>
          <Text style={s.value}>{brief.finding}</Text>
        </View>

        <View style={s.block} testID={`${ids}-brief-rating`}>
          <Text style={s.label}>Findings Rating</Text>
          <Text style={s.value}>{brief.findingsRating} / 100</Text>
          {brief.taxonomy ? (
            <Text style={s.tag} testID={`${ids}-brief-taxonomy`}>
              {brief.taxonomy.primary.domainName}
              {brief.taxonomy.secondaryDomains.length
                ? ` (also: ${brief.taxonomy.secondaryDomains.map((d) => d.domainName).join(", ")})`
                : ""}
            </Text>
          ) : null}
        </View>

        <View style={s.block} testID={`${ids}-brief-what-found`}>
          <Text style={s.label}>What ApolloSG Found</Text>
          {whatFound.map((item, i) => (
            <View key={i} style={s.bulletRow}>
              <Text style={s.bulletMark}>{"\u2022"}</Text>
              <Text style={s.bulletText}>{item}</Text>
            </View>
          ))}
        </View>

        <View style={s.block} testID={`${ids}-brief-why`}>
          <Text style={s.label}>Why This Matters</Text>
          <Text style={s.value}>{brief.whyThisMatters}</Text>
        </View>

        <View style={s.block} testID={`${ids}-brief-verified`}>
          <Text style={s.label}>What Was Verified</Text>
          {brief.whatWasVerified?.summary ? <Text style={s.value}>{brief.whatWasVerified.summary}</Text> : null}
          {limitations.map((item, i) => (
            <View key={i} style={s.bulletRow}>
              <Text style={s.bulletMark}>{"\u2022"}</Text>
              <Text style={s.bulletText}>{item}</Text>
            </View>
          ))}
        </View>

        <View style={s.block} testID={`${ids}-brief-action`}>
          <Text style={s.label}>Recommended Action</Text>
          {primary ? (
            <Text style={s.value}>{primary.label}{primary.instruction ? `: ${primary.instruction}` : ""}</Text>
          ) : (
            <Text style={s.value}>No action needed.</Text>
          )}
          {additional.map((a, i) => (
            <View key={i} style={s.bulletRow}>
              <Text style={s.bulletMark}>{"\u2022"}</Text>
              <Text style={s.bulletText}>{a.label}{a.instruction ? `: ${a.instruction}` : ""}</Text>
            </View>
          ))}
        </View>
      </View>
    </CollapsibleSection>
  );
}
