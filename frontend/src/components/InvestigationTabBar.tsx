/**
 * Shared tab bar for investigation views (Ask Higgins + Threat Cases).
 * Uses makeStaticStyles — theme-aware colors without fit() responsive scaling —
 * to guarantee flexDirection: "row" is never stripped on any device or screen size.
 */
import React from "react";
import { Pressable, Text, View } from "react-native";
import { fonts, makeStaticStyles } from "@/src/theme";

export type InvestigationTabId = "overview" | "evidence" | "history" | "di";

const TAB_LABELS: { id: InvestigationTabId; label: string }[] = [
  { id: "overview", label: "Findings" },
  { id: "evidence", label: "Evidence" },
  { id: "history", label: "History" },
  { id: "di", label: "DI" },
];

export function InvestigationTabBar({ active, onChange, testID = "inv-tab-bar" }: {
  active: InvestigationTabId;
  onChange: (id: InvestigationTabId) => void;
  testID?: string;
}) {
  const s = useStyles();
  return (
    <View style={s.bar} testID={testID}>
      {TAB_LABELS.map(({ id, label }) => {
        const selected = active === id;
        return (
          <Pressable
            key={id}
            style={[s.tab, selected && s.tabActive]}
            onPress={() => onChange(id)}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
            testID={`${testID}-${id}`}
          >
            <Text
              style={[
                s.tabText,
                selected ? s.tabTextSelected : s.tabTextDefault,
              ]}
              numberOfLines={1}
            >
              {label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const useStyles = makeStaticStyles((c) => ({
  bar: {
    flexDirection: "row" as const,
    flexWrap: "nowrap" as const,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
    backgroundColor: c.surfaceSecondary,
  },
  tab: {
    flex: 1,
    paddingVertical: 12,
    paddingHorizontal: 8,
    alignItems: "center" as const,
    borderBottomWidth: 2,
    borderBottomColor: "transparent",
  },
  tabActive: {
    borderBottomColor: c.brandPrimary,
  },
  tabText: {
    fontSize: 14,
  },
  tabTextSelected: {
    color: c.onSurface,
    fontFamily: fonts.textSemibold,
  },
  tabTextDefault: {
    color: c.muted,
    fontFamily: fonts.textMedium,
  },
}));
