// Search Threat Cases — the person's OPEN cases, by sender, website or words in the message. Only what this device
// already holds is searched (the case and the original kept on it); nothing is sent anywhere. Closed cases aren't searched.
import { useRouter } from "expo-router";
import ChevronLeft from "lucide-react-native/icons/chevron-left";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import Globe from "lucide-react-native/icons/globe";
import MessageSquare from "lucide-react-native/icons/message-square";
import Search from "lucide-react-native/icons/search";
import UserRound from "lucide-react-native/icons/user-round";
import X from "lucide-react-native/icons/x";
import React, { useEffect, useMemo, useState } from "react";
import { FlatList, Pressable, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { MATCH_LABEL, MIN_QUERY, openCases, searchCases, type CaseMatch, type CaseSearchResult } from "@/src/domain/caseSearch";
import { eventBrief, keptIdentifiers } from "@/src/domain/homeHeroBrief";
import { STATUS_COLORS, STATUS_LABELS, formatDateTime, threatCaseStatus } from "@/src/domain/threatCase";
import { useApollo } from "@/src/store/ApolloContext";
import { getCaseOriginal, subscribeOriginalSource, type OriginalSource } from "@/src/store/originalSource";
import { goBackOrHome } from "@/src/utils/navigation";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const MATCH_ICON: Record<CaseMatch, typeof Globe> = { sender: UserRound, website: Globe, message: MessageSquare };

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", gap: spacing.xs, paddingHorizontal: spacing.sm, paddingBottom: spacing.sm },
  back: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  field: { flex: 1, flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 48, paddingHorizontal: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, backgroundColor: c.surfaceSecondary },
  input: { flex: 1, fontFamily: fonts.text, fontSize: 16, color: c.onSurface, paddingVertical: spacing.sm },
  clear: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  count: { fontFamily: fonts.textMedium, fontSize: 13, color: c.onSurfaceSecondary, paddingHorizontal: spacing.lg, paddingBottom: spacing.sm },
  list: { paddingHorizontal: spacing.lg, gap: spacing.sm },
  card: { flexDirection: "row", alignItems: "flex-start", gap: spacing.md, padding: spacing.md, borderRadius: radius.lg, borderWidth: 0.5, borderColor: c.border, backgroundColor: c.surfaceSecondary },
  icon: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center", backgroundColor: c.navyTint },
  body: { flex: 1, gap: 4 },
  title: { fontFamily: fonts.textSemibold, fontSize: 14, lineHeight: 20, color: c.onSurface },
  match: { fontFamily: fonts.text, fontSize: 13, lineHeight: 18, color: c.onSurfaceSecondary },
  matchLabel: { fontFamily: fonts.textSemibold, color: c.onSurface },
  meta: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: 2 },
  date: { flex: 1, fontFamily: fonts.text, fontSize: 12, color: c.muted },
  pill: { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.pill },
  pillText: { fontFamily: fonts.textSemibold, fontSize: 11 },
  note: { paddingHorizontal: spacing.xl, paddingTop: spacing.xl, gap: spacing.sm },
  noteTitle: { fontFamily: fonts.textSemibold, fontSize: 15, lineHeight: 21, color: c.onSurface, textAlign: "center" },
  noteText: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurfaceSecondary, textAlign: "center" },
}));

function ResultCard({ result, original }: { result: CaseSearchResult; original: OriginalSource | null }) {
  const s = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const { event, match, excerpt } = result;
  const Icon = MATCH_ICON[match];
  const status = threatCaseStatus(event);
  const brief = eventBrief(event, new Date(), keptIdentifiers(original), "card");
  const id = `case-search-result-${event.event_id}`;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${brief.line1} ${MATCH_LABEL[match]}: ${excerpt}. ${STATUS_LABELS[status]}.`}
      accessibilityHint="Opens the full case"
      onPress={() => router.push(`/patrol/${encodeURIComponent(event.event_id)}` as never)}
      style={({ pressed }) => [s.card, { opacity: pressed ? 0.85 : 1 }]}
      testID={id}
    >
      <View style={s.icon}><Icon size={18} color={colors.brand} /></View>
      <View style={s.body}>
        <Text style={s.title} numberOfLines={3} testID={`${id}-title`}>{brief.line1}</Text>
        <Text style={s.match} numberOfLines={3} testID={`${id}-match`}>
          <Text style={s.matchLabel}>{MATCH_LABEL[match]}: </Text>{excerpt}
        </Text>
        <View style={s.meta}>
          <Text style={s.date} numberOfLines={1}>{formatDateTime(event.occurred_at)}</Text>
          <View style={[s.pill, { backgroundColor: STATUS_COLORS[status].bg }]}>
            <Text style={[s.pillText, { color: STATUS_COLORS[status].text }]}>{STATUS_LABELS[status]}</Text>
          </View>
          <ChevronRight size={16} color={colors.muted} />
        </View>
      </View>
    </Pressable>
  );
}

export default function CaseSearchScreen() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { events } = useApollo();
  const [query, setQuery] = useState("");
  const cases = useMemo(() => openCases(events), [events]);

  // The original each open case keeps on this device — its sender, subject and full text are only there.
  const [originals, setOriginals] = useState<Record<string, OriginalSource | null>>({});
  useEffect(() => {
    let active = true;
    const load = () => void Promise.all(cases.map(async (e) => {
      const src = await getCaseOriginal([e.event_id, e.investigation_case_id]);
      return [e.event_id, src] as const;
    })).then((pairs) => { if (active) setOriginals(Object.fromEntries(pairs)); });
    load();
    const unsubscribe = subscribeOriginalSource(load);
    return () => { active = false; unsubscribe(); };
  }, [cases]);

  const searching = query.trim().length >= MIN_QUERY;
  const results = useMemo(() => (searching ? searchCases(cases, query, originals) : []), [searching, cases, query, originals]);

  return (
    <View style={s.root} testID="case-search-screen">
      <View style={[s.header, { paddingTop: insets.top + spacing.sm }]}>
        <Pressable accessibilityRole="button" accessibilityLabel="Back" onPress={() => goBackOrHome(router)} style={s.back} testID="case-search-back">
          <ChevronLeft size={24} color={colors.onSurface} />
        </Pressable>
        <View style={s.field}>
          <Search size={18} color={colors.muted} />
          <TextInput
            value={query}
            onChangeText={setQuery}
            placeholder="Sender, website or words"
            placeholderTextColor={colors.muted}
            autoFocus
            autoCapitalize="none"
            autoCorrect={false}
            returnKeyType="search"
            accessibilityLabel="Search your open cases by sender, website or words in the message"
            style={s.input}
            testID="case-search-input"
          />
          {query ? (
            <Pressable accessibilityRole="button" accessibilityLabel="Clear search" onPress={() => setQuery("")} hitSlop={8} style={s.clear} testID="case-search-clear">
              <X size={18} color={colors.muted} />
            </Pressable>
          ) : null}
        </View>
      </View>

      {searching && results.length ? (
        <Text style={s.count} testID="case-search-count">
          {results.length} open {results.length === 1 ? "case matches" : "cases match"}
        </Text>
      ) : null}

      <FlatList
        data={results}
        keyExtractor={(r) => r.event.event_id}
        renderItem={({ item }) => <ResultCard result={item} original={originals[item.event.event_id] ?? null} />}
        contentContainerStyle={[s.list, { paddingBottom: insets.bottom + spacing.xl }]}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        testID="case-search-results"
        ListEmptyComponent={(
          <View style={s.note}>
            {!cases.length ? (
              <Text style={s.noteText} testID="case-search-none-open">You have no open Threat Cases to search.</Text>
            ) : searching ? (
              <>
                <Text style={s.noteTitle} testID="case-search-empty">No open cases match “{query.trim()}”.</Text>
                <Text style={s.noteText}>Try part of the sender&apos;s name or number, the website, or a word from the message.</Text>
              </>
            ) : (
              <>
                <Text style={s.noteTitle} testID="case-search-hint">Search your {cases.length} open {cases.length === 1 ? "case" : "cases"}</Text>
                <Text style={s.noteText}>Type a sender, a website, or words from the message. Closed cases aren&apos;t included.</Text>
              </>
            )}
          </View>
        )}
      />
    </View>
  );
}
