/**
 * ApolloSG User Guide — searchable, browsable, task-organised guide.
 * Accessible from Help/About in the hamburger menu.
 */
import { useRouter } from "expo-router";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import HelpCircle from "lucide-react-native/icons/life-buoy";
import SearchIcon from "lucide-react-native/icons/search";
import React, { useMemo, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ChildScreenHeader } from "@/src/components/ChildScreenHeader";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

// ── Guide data (mirrors backend user_guide.py — one source of truth) ────────

interface GuideTask {
  id: string; name: string; section: string;
  whatItDoes: string; steps?: string[]; route?: string; routeLabel?: string;
  fallbacks?: string[]; limitations?: string[];
}

const GUIDE: { section: string; tasks: GuideTask[] }[] = [
  { section: "Getting Started", tasks: [
    { id: "getting_started", name: "Getting started", section: "Getting Started", whatItDoes: "Set up ApolloSG: accept the privacy statement, turn on protections, and run your first check.", steps: ["Open ApolloSG.", "Read and accept the privacy statement.", "Choose which protections to turn on.", "Run your first check — tap Check It and pick what to check."], route: "/(tabs)/home", routeLabel: "Home" },
  ]},
  { section: "Sharing", tasks: [
    { id: "sharing", name: "Sharing into ApolloSG", section: "Sharing", whatItDoes: "Send content from another app to ApolloSG for checking, using your phone's Share function.", steps: ["Open the message, link, screenshot or other item in the app you're using.", "Tap Share.", "Choose ApolloSG from the share sheet.", "ApolloSG opens, shows what it received, and waits for you to confirm."], route: "/message", routeLabel: "Check a message", fallbacks: ["If ApolloSG isn't in the Share menu, copy and paste the content instead.", "You can also take a screenshot and check that."] },
    { id: "share_troubleshoot", name: "ApolloSG not in Share menu", section: "Sharing", whatItDoes: "Troubleshoot when ApolloSG doesn't appear in another app's Share menu.", steps: ["Make sure ApolloSG is installed (not just a web shortcut).", "Some apps don't offer Share for every content type — use copy/paste or a screenshot instead.", "On Android, long-press ApolloSG in the share sheet to pin it."] },
  ]},
  { section: "Check It", tasks: [
    { id: "check_it", name: "Check It", section: "Check It", whatItDoes: "The hub for all manual checks: messages, links, emails, files, calls, apps, screenshots, your device and your internet.", route: "/(tabs)/check-it", routeLabel: "Check It" },
    { id: "check_message", name: "Check a message", section: "Check It", whatItDoes: "Check whether a text message or chat message is suspicious.", route: "/message", routeLabel: "Check a message" },
    { id: "check_link", name: "Check a link", section: "Check It", whatItDoes: "Check where a link really goes and whether it's safe.", route: "/check", routeLabel: "Check a link" },
    { id: "check_screenshot", name: "Check a screenshot", section: "Check It", whatItDoes: "Check a screenshot or photo of something suspicious.", route: "/vision", routeLabel: "Check a screenshot" },
    { id: "check_email", name: "Check an email", section: "Check It", whatItDoes: "Check a single email or connect Gmail for ongoing checks.", route: "/email", routeLabel: "Check an email" },
    { id: "check_number", name: "Check a number", section: "Check It", whatItDoes: "Check the reputation of a phone number.", route: "/call-guard", routeLabel: "Check a number" },
    { id: "check_file", name: "Check a file", section: "Check It", whatItDoes: "Check whether a file or attachment is safe.", route: "/file", routeLabel: "Check a file" },
    { id: "check_app", name: "Check an app", section: "Check It", whatItDoes: "Check whether an app is safe.", route: "/app-check", routeLabel: "Check an app" },
  ]},
  { section: "Protections", tasks: [
    { id: "protections", name: "Your protections", section: "Protections", whatItDoes: "See every protection ApolloSG provides and its real status.", route: "/(tabs)/guard", routeLabel: "Your protections" },
  ]},
  { section: "Threats", tasks: [
    { id: "threats", name: "Threats", section: "Threats", whatItDoes: "Every threat Apollo has found or you've checked.", route: "/(tabs)/patrol", routeLabel: "Threats" },
  ]},
  { section: "Ask Higgins", tasks: [
    { id: "ask_higgins", name: "Ask Higgins", section: "Ask Higgins", whatItDoes: "Ask Higgins anything about scams, ApolloSG, or your device's security.", route: "/(tabs)/ask", routeLabel: "Ask Higgins" },
  ]},
  { section: "Privacy", tasks: [
    { id: "privacy", name: "Privacy and personal data", section: "Privacy", whatItDoes: "No account, no email, no ad tracking. Checks run on-device first.", route: "/privacy-data", routeLabel: "What ApolloSG stores" },
  ]},
  { section: "Troubleshooting", tasks: [
    { id: "troubleshoot", name: "General troubleshooting", section: "Troubleshooting", whatItDoes: "Get help with ApolloSG.", route: "/support", routeLabel: "Get help" },
  ]},
];

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  searchWrap: { flexDirection: "row" as const, alignItems: "center" as const, gap: spacing.sm, marginHorizontal: spacing.lg, marginVertical: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: 8, borderRadius: radius.lg, backgroundColor: c.surfaceSecondary, borderWidth: 0.5, borderColor: c.border },
  searchInput: { flex: 1, fontFamily: fonts.text, fontSize: 15, color: c.onSurface, padding: 0 },
  sectionTitle: { fontFamily: fonts.displayBold, fontSize: 13, color: c.onSurfaceSecondary, textTransform: "uppercase" as const, letterSpacing: 0.3, paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.xs },
  card: { marginHorizontal: spacing.lg, borderRadius: radius.lg, backgroundColor: c.surfaceSecondary, borderWidth: 0.25, borderColor: c.border, overflow: "hidden" as const, marginBottom: spacing.sm },
  row: { flexDirection: "row" as const, alignItems: "center" as const, gap: spacing.md, padding: spacing.md, minHeight: 52 },
  divider: { height: 0.5, backgroundColor: c.divider },
  rowBody: { flex: 1, gap: 2 },
  rowName: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.onSurface },
  rowDesc: { fontFamily: fonts.text, fontSize: 12, color: c.onSurfaceSecondary, lineHeight: 17 },
  askRow: { flexDirection: "row" as const, alignItems: "center" as const, justifyContent: "center" as const, gap: spacing.sm, padding: spacing.md, marginHorizontal: spacing.lg, marginTop: spacing.md, marginBottom: spacing.lg, borderRadius: radius.lg, backgroundColor: c.brandPrimary },
  askText: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onBrandPrimary },
  empty: { fontFamily: fonts.text, fontSize: 14, color: c.muted, textAlign: "center" as const, paddingVertical: spacing.xl * 2, paddingHorizontal: spacing.xl },
}));

export default function UserGuideScreen() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    if (!search.trim()) return GUIDE;
    const q = search.toLowerCase();
    return GUIDE.map(({ section, tasks }) => ({
      section,
      tasks: tasks.filter((t) => t.name.toLowerCase().includes(q) || t.whatItDoes.toLowerCase().includes(q)),
    })).filter(({ tasks }) => tasks.length > 0);
  }, [search]);

  const openTask = (task: GuideTask) => {
    if (task.route) router.push(task.route as any);
  };

  return (
    <View style={s.root} testID="user-guide-screen">
      <ChildScreenHeader title="User Guide" testID="user-guide-header" />
      <View style={s.searchWrap}>
        <SearchIcon size={18} color={colors.muted} />
        <TextInput style={s.searchInput} placeholder="Search the guide\u2026" placeholderTextColor={colors.muted}
          value={search} onChangeText={setSearch} autoCorrect={false} testID="user-guide-search" />
      </View>
      <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xl }} testID="user-guide-list">
        {filtered.length === 0 ? (
          <Text style={s.empty}>No matching topics. Try asking Higgins instead.</Text>
        ) : filtered.map(({ section, tasks }) => (
          <View key={section}>
            <Text style={s.sectionTitle}>{section}</Text>
            <View style={s.card}>
              {tasks.map((task, i) => (
                <React.Fragment key={task.id}>
                  {i > 0 ? <View style={s.divider} /> : null}
                  <Pressable style={({ pressed }) => [s.row, { opacity: pressed ? 0.85 : 1 }]}
                    onPress={() => openTask(task)} accessibilityRole="button" testID={`guide-task-${task.id}`}>
                    <View style={s.rowBody}>
                      <Text style={s.rowName}>{task.name}</Text>
                      <Text style={s.rowDesc} numberOfLines={2}>{task.whatItDoes}</Text>
                    </View>
                    {task.route ? <ChevronRight size={16} color={colors.onSurfaceSecondary} /> : null}
                  </Pressable>
                </React.Fragment>
              ))}
            </View>
          </View>
        ))}
        <Pressable style={({ pressed }) => [s.askRow, { opacity: pressed ? 0.85 : 1 }]}
          onPress={() => router.push({ pathname: "/(tabs)/ask", params: { prefill: search || "How do I use ApolloSG?" } })}
          accessibilityRole="button" testID="guide-ask-higgins">
          <HelpCircle size={18} color={colors.onBrandPrimary} />
          <Text style={s.askText}>Ask Higgins about this</Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}
