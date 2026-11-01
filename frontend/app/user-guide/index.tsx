/**
 * ApolloSG User Guide — plain-English help for every part of the app, with search across
 * titles, headings and body text. Opened from the ☰ menu.
 */
import { useRouter } from "expo-router";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import MessageCircle from "lucide-react-native/icons/message-circle";
import SearchIcon from "lucide-react-native/icons/search";
import X from "lucide-react-native/icons/x";
import React, { useMemo, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ChildScreenHeader } from "@/src/components/ChildScreenHeader";
import { USER_GUIDE, reviewedLabel } from "@/src/guide/guide";
import { highlightParts, searchGuide, searchTerms } from "@/src/guide/search";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const INFO = {
  title: "About the User Guide",
  body: [
    "This guide explains how to use ApolloSG: where things are, what each screen shows and the steps for each task.",
    "Search finds words anywhere in the guide. Tap a topic to read it, then use its buttons to go straight to that screen.",
    "Higgins answers “how do I…” questions from this same guide.",
  ],
};

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  searchBar: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm, marginHorizontal: spacing.lg, marginBottom: spacing.sm,
    paddingHorizontal: spacing.md, minHeight: 48, borderRadius: radius.md, backgroundColor: c.surfaceSecondary, borderWidth: 1, borderColor: c.border,
  },
  searchInput: { flex: 1, fontFamily: fonts.text, fontSize: 16, color: c.onSurface, paddingVertical: spacing.sm },
  clear: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  intro: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurfaceSecondary, paddingHorizontal: spacing.xl, paddingBottom: spacing.sm },
  sectionTitle: { fontFamily: fonts.displayBold, fontSize: 17, color: c.onSurface },
  sectionSummary: { fontFamily: fonts.text, fontSize: 13, lineHeight: 18, color: c.onSurfaceSecondary, marginTop: 2 },
  sectionHead: { paddingHorizontal: spacing.xl, paddingTop: spacing.lg, paddingBottom: spacing.sm },
  card: { marginHorizontal: spacing.lg, borderRadius: radius.md, backgroundColor: c.surfaceSecondary, borderWidth: 1, borderColor: c.border, overflow: "hidden" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, minHeight: 52 },
  divider: { height: 1, backgroundColor: c.divider, marginLeft: spacing.lg },
  rowBody: { flex: 1, gap: 2 },
  rowTitle: { fontFamily: fonts.textSemibold, fontSize: 15, lineHeight: 20, color: c.onSurface },
  rowMeta: { fontFamily: fonts.text, fontSize: 12, color: c.muted },
  rowSnippet: { fontFamily: fonts.text, fontSize: 13, lineHeight: 18, color: c.onSurfaceSecondary },
  mark: { fontFamily: fonts.textSemibold, color: c.onSurface, backgroundColor: c.goldTint },
  resultCount: { fontFamily: fonts.text, fontSize: 13, color: c.muted, paddingHorizontal: spacing.xl, paddingVertical: spacing.sm },
  empty: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurfaceSecondary, textAlign: "center", paddingHorizontal: spacing.xl, paddingVertical: spacing.xl },
  ask: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, minHeight: 48, marginHorizontal: spacing.lg,
    marginTop: spacing.xl, borderRadius: radius.md, backgroundColor: c.brandPrimary, paddingHorizontal: spacing.lg,
  },
  askText: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.onBrandPrimary },
}));

export default function UserGuideScreen() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const searching = query.trim().length > 0;
  const terms = useMemo(() => searchTerms(query), [query]);
  const hits = useMemo(() => (searching ? searchGuide(USER_GUIDE, query) : []), [query, searching]);

  const openTopic = (section: string, topic: string) => router.push({ pathname: "/user-guide/[section]", params: { section, topic } });
  const askHiggins = () => router.push({ pathname: "/(tabs)/ask", params: query.trim() ? { prompt: query.trim() } : {} });

  return (
    <View style={s.root} testID="user-guide-screen">
      <ChildScreenHeader title="User Guide" testID="user-guide-header" info={INFO} />
      <View style={s.searchBar}>
        <SearchIcon size={18} color={colors.muted} />
        <TextInput style={s.searchInput} placeholder="Search the guide — e.g. share, delete, call" placeholderTextColor={colors.muted}
          value={query} onChangeText={setQuery} autoCorrect={false} autoCapitalize="none" returnKeyType="search"
          accessibilityLabel="Search the User Guide" testID="user-guide-search" />
        {searching ? (
          <Pressable style={s.clear} onPress={() => setQuery("")} hitSlop={8} accessibilityRole="button" accessibilityLabel="Clear search" testID="user-guide-search-clear">
            <X size={18} color={colors.muted} />
          </Pressable>
        ) : null}
      </View>
      <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xl }} keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag" testID="user-guide-list">
        {searching ? (
          hits.length ? (
            <>
              <Text style={s.resultCount} testID="user-guide-result-count">
                {hits.length === 1 ? "1 topic" : `${hits.length} topics`} for “{query.trim()}”
              </Text>
              <View style={s.card}>
                {hits.map(({ section, topic, snippet }, i) => (
                  <React.Fragment key={topic.id}>
                    {i > 0 ? <View style={s.divider} /> : null}
                    <Pressable style={({ pressed }) => [s.row, { opacity: pressed ? 0.85 : 1 }]} onPress={() => openTopic(section.id, topic.id)}
                      accessibilityRole="button" accessibilityLabel={`${topic.title}. ${section.title}.`} testID={`guide-result-${topic.id}`}>
                      <View style={s.rowBody}>
                        <Text style={s.rowTitle}><Highlighted text={topic.title} terms={terms} /></Text>
                        <Text style={s.rowSnippet} numberOfLines={3}><Highlighted text={snippet} terms={terms} /></Text>
                        <Text style={s.rowMeta}>{section.title}</Text>
                      </View>
                      <ChevronRight size={16} color={colors.onSurfaceSecondary} />
                    </Pressable>
                  </React.Fragment>
                ))}
              </View>
            </>
          ) : (
            <Text style={s.empty} testID="user-guide-no-results">
              Nothing in the guide matches “{query.trim()}”. Try a different word, or ask Higgins.
            </Text>
          )
        ) : (
          <>
            <Text style={s.intro}>Plain-English help for every part of ApolloSG. Reviewed {reviewedLabel()}.</Text>
            {USER_GUIDE.sections.map((section) => (
              <View key={section.id} testID={`guide-section-${section.id}`}>
                <View style={s.sectionHead}>
                  <Text style={s.sectionTitle} accessibilityRole="header">{section.title}</Text>
                  <Text style={s.sectionSummary}>{section.summary}</Text>
                </View>
                <View style={s.card}>
                  {section.topics.map((topic, i) => (
                    <React.Fragment key={topic.id}>
                      {i > 0 ? <View style={s.divider} /> : null}
                      <Pressable style={({ pressed }) => [s.row, { opacity: pressed ? 0.85 : 1 }]} onPress={() => openTopic(section.id, topic.id)}
                        accessibilityRole="button" testID={`guide-topic-${topic.id}`}>
                        <Text style={[s.rowTitle, { flex: 1 }]}>{topic.title}</Text>
                        <ChevronRight size={16} color={colors.onSurfaceSecondary} />
                      </Pressable>
                    </React.Fragment>
                  ))}
                </View>
              </View>
            ))}
          </>
        )}
        <Pressable style={({ pressed }) => [s.ask, { opacity: pressed ? 0.85 : 1 }]} onPress={askHiggins} accessibilityRole="button" testID="guide-ask-higgins">
          <MessageCircle size={18} color={colors.onBrandPrimary} />
          <Text style={s.askText}>{searching ? "Ask Higgins about this" : "Ask Higgins a question"}</Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}

function Highlighted({ text, terms }: { text: string; terms: string[] }) {
  const s = useStyles();
  return (
    <>
      {highlightParts(text, terms).map((part, i) => (part.match ? <Text key={i} style={s.mark}>{part.text}</Text> : part.text))}
    </>
  );
}
