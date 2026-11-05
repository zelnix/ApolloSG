// "How Apollo checks" — the rules every part of Apollo works under, in plain English, in the order a check
// moves through them, plus what each of the five results means. Content: src/domain/howApolloChecks.ts.
import { useLocalSearchParams, useRouter } from "expo-router";
import ChevronLeft from "lucide-react-native/icons/chevron-left";
import ListChecks from "lucide-react-native/icons/list-checks";
import MessageCircle from "lucide-react-native/icons/message-circle";
import ScanSearch from "lucide-react-native/icons/scan-search";
import Shield from "lucide-react-native/icons/shield";
import ShieldCheck from "lucide-react-native/icons/shield-check";
import Zap from "lucide-react-native/icons/zap";
import React, { useCallback, useRef } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AppMenuButton } from "@/src/components/AppMenu";
import { Card, Pill, SectionTitle } from "@/src/components/ui";
import { CHECK_ROLES, HOW_INTRO, OUTCOME_GUIDE, PROMISES, type CheckRoleId } from "@/src/domain/howApolloChecks";
import { outcomeLabel, outcomeTone } from "@/src/domain/messageVoice";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { goBackOrHome } from "@/src/utils/navigation";

const ICONS: Record<CheckRoleId, typeof Shield> = { apollo: Shield, triage: ListChecks, tc_flyby: Zap, magnum: ScanSearch, higgins: MessageCircle };

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.xs },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 18, color: c.onSurface, flex: 1 },
  content: { paddingHorizontal: spacing.lg },
  sections: { gap: spacing.xl },
  intro: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurfaceSecondary },
  step: { flexDirection: "row", gap: spacing.md },
  rail: { alignItems: "center", width: 40 },
  well: { width: 40, height: 40, borderRadius: radius.pill, backgroundColor: c.brand, alignItems: "center", justifyContent: "center" },
  line: { flex: 1, width: 2, backgroundColor: c.goldBorder, marginVertical: spacing.xs },
  stepCard: { flex: 1, gap: spacing.sm, marginBottom: spacing.md },
  stepNumber: { fontFamily: fonts.textSemibold, fontSize: 11, letterSpacing: 1, color: c.muted, textTransform: "uppercase" },
  roleName: { fontFamily: fonts.displayBold, fontSize: 17, color: c.onSurface },
  roleJob: { fontFamily: fonts.textMedium, fontSize: 13, color: c.onSurfaceSecondary },
  ruleRow: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  bullet: { width: 5, height: 5, borderRadius: 3, backgroundColor: c.gold, marginTop: 8 },
  ruleText: { flex: 1, fontFamily: fonts.text, fontSize: 14, lineHeight: 21, color: c.onSurface },
  outcomeRow: { gap: spacing.xs, paddingVertical: spacing.sm, borderBottomWidth: 0.5, borderBottomColor: c.divider },
  outcomeMeaning: { fontFamily: fonts.text, fontSize: 14, lineHeight: 21, color: c.onSurfaceSecondary },
  // The result the person came here to understand.
  outcomeFocus: { backgroundColor: c.goldTint, borderRadius: radius.md, borderBottomWidth: 0, paddingHorizontal: spacing.sm, marginHorizontal: -spacing.sm },
  focusNote: { fontFamily: fonts.textSemibold, fontSize: 12, color: c.onSurface },
  promiseRow: { flexDirection: "row", gap: spacing.md, alignItems: "flex-start", paddingVertical: spacing.xs },
}));

export default function HowApolloChecks() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  // Opened from "What does this mean?" beside a result: go straight to the results, with that one highlighted.
  const { outcome: focus } = useLocalSearchParams<{ outcome?: string }>();
  const scrollRef = useRef<ScrollView>(null);
  const contentRef = useRef<View>(null);
  const outcomesRef = useRef<View>(null);
  const userScrolled = useRef(false);
  // Re-measured whenever the content above changes height (fonts loading, text wrapping), until the
  // person scrolls themselves.
  const goToFocus = useCallback(() => {
    if (!focus || userScrolled.current || !outcomesRef.current || !contentRef.current) return;
    outcomesRef.current.measureLayout(contentRef.current, (_x, y) => scrollRef.current?.scrollTo({ y: Math.max(0, y - spacing.md), animated: false }), () => undefined);
  }, [focus]);

  return (
    <View style={s.root} testID="how-checks-screen">
      <View style={{ paddingTop: insets.top }}>
        <View style={s.header}>
          <Pressable accessibilityRole="button" accessibilityLabel="Back" testID="how-checks-back" onPress={() => goBackOrHome(router)}
            style={{ width: 44, height: 44, alignItems: "center", justifyContent: "center" }}>
            <ChevronLeft size={24} color={colors.onSurface} />
          </Pressable>
          <Text style={s.headerTitle} accessibilityRole="header">How Apollo checks</Text>
          <AppMenuButton testID="how-checks-menu" />
        </View>
      </View>
      <ScrollView ref={scrollRef} contentContainerStyle={[s.content, { paddingTop: spacing.md, paddingBottom: insets.bottom + spacing["3xl"] }]} testID="how-checks-scroll"
        onContentSizeChange={goToFocus} onScrollBeginDrag={() => { userScrolled.current = true; }}>
        <View ref={contentRef} collapsable={false} style={s.sections}>
        <Text style={s.intro} testID="how-checks-intro">{HOW_INTRO}</Text>

        <View>
          <SectionTitle>Who does what</SectionTitle>
          {CHECK_ROLES.map((role, i) => {
            const Icon = ICONS[role.id];
            const last = i === CHECK_ROLES.length - 1;
            return (
              <View key={role.id} style={s.step} testID={`how-checks-role-${role.id}`}>
                <View style={s.rail}>
                  <View style={s.well}><Icon size={20} color={colors.gold} /></View>
                  {last ? null : <View style={s.line} />}
                </View>
                <Card style={s.stepCard}>
                  <Text style={s.stepNumber}>Step {i + 1}</Text>
                  <View>
                    <Text style={s.roleName}>{role.name}</Text>
                    <Text style={s.roleJob}>{role.job}</Text>
                  </View>
                  {role.rules.map((rule) => (
                    <View key={rule} style={s.ruleRow}>
                      <View style={s.bullet} />
                      <Text style={s.ruleText}>{rule}</Text>
                    </View>
                  ))}
                </Card>
              </View>
            );
          })}
        </View>

        <View testID="how-checks-outcomes" ref={outcomesRef} collapsable={false} onLayout={goToFocus}>
          <SectionTitle>What the results mean</SectionTitle>
          <Card style={{ paddingVertical: spacing.sm }}>
            {OUTCOME_GUIDE.map((item, i) => (
              <View key={item.outcome} style={[s.outcomeRow, i === OUTCOME_GUIDE.length - 1 && { borderBottomWidth: 0 }, item.outcome === focus && s.outcomeFocus]}
                testID={`how-checks-outcome-${item.outcome}`} accessibilityState={{ selected: item.outcome === focus }}>
                <Pill label={outcomeLabel(item.outcome) ?? ""} tone={outcomeTone(item.outcome)} />
                <Text style={s.outcomeMeaning}>{item.meaning}</Text>
                {item.outcome === focus ? <Text style={s.focusNote} testID="how-checks-outcome-focus">This is the result you were looking at.</Text> : null}
              </View>
            ))}
          </Card>
        </View>

        <View testID="how-checks-promises">
          <SectionTitle>ApolloSG&apos;s promises</SectionTitle>
          {PROMISES.map((promise) => (
            <View key={promise} style={s.promiseRow}>
              <ShieldCheck size={18} color={colors.restingText} />
              <Text style={s.ruleText}>{promise}</Text>
            </View>
          ))}
        </View>


        </View>
      </ScrollView>
    </View>
  );
}
