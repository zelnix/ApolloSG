// The Findings Brief's last card: "Related cases (N)" — this device's own earlier cases that share the link, number,
// address, message, file or organisation, or are connected events — then ApolloSG's previous reports.
// Context, never evidence (domain/caseHistory.ts). Shared by a Threat Case and Ask Higgins.
import { useRouter } from "expo-router";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import Clock from "lucide-react-native/icons/clock";
import Link2 from "lucide-react-native/icons/link-2";
import React, { useMemo } from "react";
import { Pressable, Text, View } from "react-native";

import { caseHistory, weightLine, type RelatedRow } from "@/src/domain/caseHistory";
import { looksLikeInternalCode } from "@/src/domain/messageVoice";
import { categoryLabel, formatDateTime } from "@/src/domain/threatCase";
import type { PatrolEvent } from "@/src/domain/types";
import type { HigginsResponse } from "@/src/investigation/types";
import { useApollo } from "@/src/store/ApolloContext";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  section: { flexDirection: "row", gap: spacing.md, borderRadius: radius.lg, padding: spacing.md, borderWidth: 0.25, borderColor: c.border, backgroundColor: c.surfaceSecondary },
  circle: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center", backgroundColor: c.surfaceTertiary },
  content: { flex: 1, gap: spacing.xs },
  title: { fontFamily: fonts.displayBold, fontSize: 17, color: c.onSurface },
  sub: { fontFamily: fonts.text, fontSize: 13, lineHeight: 18, color: c.muted },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.md, borderTopWidth: 1, borderTopColor: c.divider, minHeight: 44 },
  rowText: { flex: 1, gap: 2 },
  rowTitle: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface },
  encounterHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: c.divider },
  encounterIcon: { width: 24, height: 24, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: c.surfaceTertiary },
  encounterTitle: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface },
  weight: { fontFamily: fonts.text, fontSize: 13, lineHeight: 18, color: c.onSurfaceSecondary, padding: spacing.sm, borderRadius: radius.md, backgroundColor: c.surfaceTertiary },
  bullet: { flexDirection: "row", gap: spacing.sm },
  dot: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurface },
  item: { flex: 1, fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurface },
}));

function rowTitle(row: RelatedRow): string {
  const e = row.event;
  if (!e) return row.text;
  return e.headline && !looksLikeInternalCode(e.headline) ? e.headline : `${categoryLabel(e.category)} event`;
}

export function RelatedCases({ event, response, ids }: {
  event: PatrolEvent | null | undefined; response: HigginsResponse | null | undefined;
  /** testID prefix: "tc" on a threat, "inv" on Ask Higgins. */
  ids: string;
}) {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const { events } = useApollo();
  const history = useMemo(() => caseHistory(event, events, response), [event, events, response]);
  const weight = weightLine(history.weighted);

  return (
    <View style={s.section} testID={`${ids}-related-cases`}>
      <View style={s.circle}><Link2 size={18} color={colors.onSurfaceSecondary} /></View>
      <View style={s.content}>
        <Text style={s.title}>Related cases ({history.related.length})</Text>
        {history.related.length ? history.related.map((row) => {
          const sub = [row.reason, row.result, row.at ? formatDateTime(row.at) : null].filter(Boolean).join(" · ");
          const body = (
            <>
              <View style={s.rowText}>
                <Text style={s.rowTitle} numberOfLines={2}>{rowTitle(row)}</Text>
                <Text style={s.sub} testID={`${ids}-related-case-${row.key}-reason`}>{sub}</Text>
              </View>
              {row.event ? <ChevronRight size={16} color={colors.muted} /> : null}
            </>
          );
          return row.event ? (
            <Pressable key={row.key} onPress={() => router.push(`/patrol/${encodeURIComponent(row.event!.event_id)}`)} style={s.row}
              accessibilityRole="button" testID={`${ids}-related-case-${row.key}`}>{body}</Pressable>
          ) : <View key={row.key} style={s.row} testID={`${ids}-related-case-${row.key}`}>{body}</View>;
        }) : (
          <Text style={s.sub} testID={`${ids}-related-cases-empty`}>No related cases. Related emails, messages or links on this device will appear here.</Text>
        )}
        {history.encountered.length ? (
          <View style={{ gap: spacing.xs }} testID={`${ids}-encountered`}>
            <View style={s.encounterHead}>
              <View style={s.encounterIcon}><Clock size={12} color={colors.onSurfaceSecondary} /></View>
              <Text style={s.encounterTitle}>Previous reports</Text>
            </View>
            {history.encountered.map((n) => (
              <View key={n.key} style={s.bullet} testID={`${ids}-${n.key}`}>
                <Text style={s.dot}>{"\u2022"}</Text>
                <Text style={s.item}>{n.text}</Text>
              </View>
            ))}
          </View>
        ) : null}
        {weight ? <Text style={s.weight} testID={`${ids}-related-weight`}>{weight}</Text> : null}
      </View>
    </View>
  );
}
