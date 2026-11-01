/**
 * One section of the ApolloSG User Guide, as readable prose: each topic's direct answer, its steps,
 * the details, any limitations, and buttons that open the screens it talks about.
 * Opened at a topic (?topic=…) from the guide's list or its search results.
 */
import { useLocalSearchParams, useRouter } from "expo-router";
import ArrowRight from "lucide-react-native/icons/arrow-right";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import React, { useRef, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ChildScreenHeader } from "@/src/components/ChildScreenHeader";
import { USER_GUIDE, guideSection, type GuideTopic } from "@/src/guide/guide";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  summary: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurfaceSecondary, paddingHorizontal: spacing.xl, paddingBottom: spacing.sm },
  topic: { marginHorizontal: spacing.lg, marginTop: spacing.md, padding: spacing.lg, gap: spacing.md, borderRadius: radius.md, backgroundColor: c.surfaceSecondary, borderWidth: 1, borderColor: c.border },
  topicTarget: { borderColor: c.goldBorder, borderWidth: 2 },
  title: { fontFamily: fonts.displayBold, fontSize: 19, lineHeight: 25, color: c.onSurface },
  answer: { fontFamily: fonts.textSemibold, fontSize: 16, lineHeight: 23, color: c.onSurface },
  label: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.muted, textTransform: "uppercase", letterSpacing: 0.4 },
  step: { flexDirection: "row", gap: spacing.sm },
  stepNo: { width: 24, height: 24, borderRadius: radius.pill, backgroundColor: c.brandPrimary, alignItems: "center", justifyContent: "center", marginTop: 1 },
  stepNoText: { fontFamily: fonts.textSemibold, fontSize: 12, color: c.onBrandPrimary },
  body: { flex: 1, fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurfaceSecondary },
  heading: { fontFamily: fonts.textSemibold, fontSize: 15, lineHeight: 21, color: c.onSurface },
  bullet: { flexDirection: "row", gap: spacing.sm, paddingLeft: spacing.xs },
  bulletDot: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.muted },
  note: { flexDirection: "row", gap: spacing.sm, padding: spacing.md, borderRadius: radius.sm, backgroundColor: c.goldTint },
  noteText: { flex: 1, fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurface },
  links: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  link: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 44, paddingHorizontal: spacing.md, borderRadius: radius.pill, borderWidth: 1, borderColor: c.brandPrimary },
  linkText: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.brandPrimary },
  next: { flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 56, marginHorizontal: spacing.lg, marginTop: spacing.xl, paddingHorizontal: spacing.lg, borderRadius: radius.md, borderWidth: 1, borderColor: c.border },
  nextLabel: { fontFamily: fonts.text, fontSize: 12, color: c.muted },
  nextTitle: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.onSurface },
  missing: { fontFamily: fonts.text, fontSize: 15, color: c.onSurfaceSecondary, padding: spacing.xl },
}));

export default function UserGuideSection() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const params = useLocalSearchParams<{ section?: string; topic?: string }>();
  const section = guideSection(params.section);
  const scroll = useRef<ScrollView>(null);
  const [scrolled, setScrolled] = useState(false);

  if (!section) {
    return (
      <View style={s.root} testID="user-guide-section-screen">
        <ChildScreenHeader title="User Guide" testID="user-guide-section-header" />
        <Text style={s.missing}>{"This part of the guide isn't available. Open the User Guide from the ☰ menu to browse every topic."}</Text>
      </View>
    );
  }

  const index = USER_GUIDE.sections.indexOf(section);
  const next = USER_GUIDE.sections[index + 1];
  // Bring the chosen topic to the top once it has been laid out.
  const onTopicLayout = (id: string, y: number) => {
    if (scrolled || id !== params.topic) return;
    setScrolled(true);
    requestAnimationFrame(() => scroll.current?.scrollTo({ y: Math.max(0, y - spacing.md), animated: false }));
  };

  return (
    <View style={s.root} testID="user-guide-section-screen">
      <ChildScreenHeader title={section.title} testID="user-guide-section-header" />
      <ScrollView ref={scroll} contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xl }} testID="user-guide-section-scroll">
        <Text style={s.summary}>{section.summary}</Text>
        {section.topics.map((topic) => (
          <View key={topic.id} style={[s.topic, topic.id === params.topic ? s.topicTarget : null]}
            onLayout={(e) => onTopicLayout(topic.id, e.nativeEvent.layout.y)} testID={`guide-article-${topic.id}`}>
            <TopicBody topic={topic} onOpen={(route) => router.push(route as never)} />
          </View>
        ))}
        {next ? (
          <Pressable style={({ pressed }) => [s.next, { opacity: pressed ? 0.85 : 1 }]} accessibilityRole="button"
            onPress={() => router.replace({ pathname: "/user-guide/[section]", params: { section: next.id } })} testID="user-guide-next-section">
            <View style={{ flex: 1 }}>
              <Text style={s.nextLabel}>Next</Text>
              <Text style={s.nextTitle}>{next.title}</Text>
            </View>
            <ChevronRight size={18} color={colors.onSurfaceSecondary} />
          </Pressable>
        ) : null}
      </ScrollView>
    </View>
  );
}

function TopicBody({ topic, onOpen }: { topic: GuideTopic; onOpen: (route: string) => void }) {
  const s = useStyles();
  const { colors } = useTheme();
  return (
    <>
      <Text style={s.title} accessibilityRole="header">{topic.title}</Text>
      <Text style={s.answer}>{topic.answer}</Text>
      {topic.steps?.length ? (
        <View style={{ gap: spacing.sm }}>
          <Text style={s.label}>Steps</Text>
          {topic.steps.map((step, i) => (
            <View key={i} style={s.step}>
              <View style={s.stepNo}><Text style={s.stepNoText}>{i + 1}</Text></View>
              <Text style={s.body}>{step}</Text>
            </View>
          ))}
        </View>
      ) : null}
      {topic.details?.map((detail) => (
        <View key={detail.heading} style={{ gap: spacing.xs }}>
          <Text style={s.heading}>{detail.heading}</Text>
          <Prose text={detail.text} />
        </View>
      ))}
      {topic.notes?.map((note) => (
        <View key={note} style={s.note}>
          <Text style={s.noteText}>{note}</Text>
        </View>
      ))}
      {topic.links?.length ? (
        <View style={s.links}>
          {topic.links.map((link) => (
            <Pressable key={link.route} style={({ pressed }) => [s.link, { opacity: pressed ? 0.85 : 1 }]} onPress={() => onOpen(link.route)}
              accessibilityRole="button" testID={`guide-link-${topic.id}-${link.route.replace(/[^a-z0-9]+/gi, "-")}`}>
              <Text style={s.linkText}>{link.label}</Text>
              <ArrowRight size={16} color={colors.brandPrimary} />
            </Pressable>
          ))}
        </View>
      ) : null}
    </>
  );
}

/** Paragraphs, with lines starting "• " shown as a list. */
function Prose({ text }: { text: string }) {
  const s = useStyles();
  return (
    <View style={{ gap: spacing.xs }}>
      {text.split("\n").map((line, i) =>
        line.startsWith("• ") ? (
          <View key={i} style={s.bullet}>
            <Text style={s.bulletDot}>•</Text>
            <Text style={s.body}>{line.slice(2)}</Text>
          </View>
        ) : (
          <Text key={i} style={s.body}>{line}</Text>
        ),
      )}
    </View>
  );
}
