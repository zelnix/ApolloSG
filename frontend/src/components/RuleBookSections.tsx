// The rule book as closed sections under its parts: the intro stays open, each part (Protection Gates,
// Investigation process…) is a heading, and each section under it (Link Gate, TC Hawkeye, Privacy…) opens with a tap
// on its title. "Open all" / "Close all" open or close every section at once.
import ChevronDown from "lucide-react-native/icons/chevron-down";
import ChevronUp from "lucide-react-native/icons/chevron-up";
import React, { useRef, useState } from "react";
import { LayoutAnimation, Pressable, Text, View } from "react-native";

import { RuleBookView } from "@/src/components/RuleBookView";
import type { Block, RuleBookGroup, RuleBookSection } from "@/src/domain/ruleBook";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  root: { gap: spacing.md },
  tools: { flexDirection: "row", justifyContent: "flex-end", marginTop: -spacing.sm },
  toolButton: { minHeight: 44, paddingHorizontal: spacing.sm, justifyContent: "center" },
  toolText: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.brandPrimary },
  groups: { gap: spacing.xl },
  group: { gap: spacing.sm },
  groupTitle: { fontFamily: fonts.displayBold, fontSize: 21, lineHeight: 27, color: c.onSurface },
  card: { borderWidth: 1, borderColor: c.divider, borderRadius: radius.md, backgroundColor: c.surface, overflow: "hidden" },
  header: { minHeight: 56, flexDirection: "row", alignItems: "center", gap: spacing.md, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  title: { flex: 1, fontFamily: fonts.displayBold, fontSize: 17, lineHeight: 23, color: c.onSurface },
  body: { paddingHorizontal: spacing.lg, paddingBottom: spacing.lg },
}));

export function RuleBookSections({ intro, groups, initiallyOpen, onInitialSectionY }: {
  intro: Block[];
  groups: RuleBookGroup[];
  /** Opened from a result's "See the rule": that section starts open. */
  initiallyOpen?: string;
  /** y of the initially open section's card, relative to this view — for opening the book at that section. */
  onInitialSectionY?: (y: number) => void;
}) {
  const s = useStyles();
  const { colors } = useTheme();
  const sections: RuleBookSection[] = groups.flatMap((group) => group.sections);
  const [open, setOpen] = useState<Set<string>>(() => new Set(initiallyOpen ? [initiallyOpen] : []));
  const allOpen = sections.length > 0 && sections.every((section) => open.has(section.id));
  // The card's y is relative to its part, and the part's to the list, so the three add up to the y in this view.
  const listY = useRef(0);
  const groupY = useRef<Record<string, number>>({});
  const cardY = useRef<number | null>(null);
  const initialGroup = groups.find((group) => group.sections.some((section) => section.id === initiallyOpen))?.id;
  const report = () => {
    if (!onInitialSectionY || !initialGroup || cardY.current === null) return;
    onInitialSectionY(listY.current + (groupY.current[initialGroup] ?? 0) + cardY.current);
  };

  const change = (next: Set<string>) => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setOpen(next);
  };
  const toggle = (id: string) => {
    const next = new Set(open);
    if (next.has(id)) next.delete(id); else next.add(id);
    change(next);
  };

  return (
    <View style={s.root} testID="rule-book">
      {intro.length ? <RuleBookView blocks={intro} testID="rule-book-intro" /> : null}
      <View style={s.tools}>
        <Pressable testID="rule-book-toggle-all" accessibilityRole="button" style={({ pressed }) => [s.toolButton, { opacity: pressed ? 0.7 : 1 }]}
          onPress={() => change(allOpen ? new Set() : new Set(sections.map((section) => section.id)))}>
          <Text style={s.toolText}>{allOpen ? "Close all" : "Open all"}</Text>
        </Pressable>
      </View>
      <View style={s.groups} collapsable={false} onLayout={(e) => { listY.current = e.nativeEvent.layout.y; report(); }}>
        {groups.map((group) => (
          <View key={group.id} style={s.group} collapsable={false} testID={`rule-book-group-${group.id}`}
            onLayout={(e) => { groupY.current[group.id] = e.nativeEvent.layout.y; if (group.id === initialGroup) report(); }}>
            <Text style={s.groupTitle} accessibilityRole="header" testID={`rule-book-group-title-${group.id}`}>{group.title}</Text>
            {group.blocks.length ? <RuleBookView blocks={group.blocks} testID={`rule-book-group-intro-${group.id}`} /> : null}
            {group.sections.map((section) => {
              const expanded = open.has(section.id);
              const Chevron = expanded ? ChevronUp : ChevronDown;
              return (
                <View key={section.id} style={s.card} collapsable={false}
                  onLayout={section.id === initiallyOpen ? (e) => { cardY.current = e.nativeEvent.layout.y; report(); } : undefined}>
                  <Pressable testID={`rule-book-section-${section.id}`} accessibilityRole="button" accessibilityState={{ expanded }}
                    accessibilityHint={expanded ? "Closes this part of the rule book" : "Opens this part of the rule book"}
                    onPress={() => toggle(section.id)} style={({ pressed }) => [s.header, { opacity: pressed ? 0.7 : 1 }]}>
                    <Text style={s.title} accessibilityRole="header">{section.title}</Text>
                    <Chevron size={20} color={colors.muted} />
                  </Pressable>
                  {expanded ? (
                    <View style={s.body} testID={`rule-book-section-body-${section.id}`}>
                      <RuleBookView blocks={section.blocks} testID={`rule-book-blocks-${section.id}`} />
                    </View>
                  ) : null}
                </View>
              );
            })}
          </View>
        ))}
      </View>
    </View>
  );
}
