/**
 * Shared tab bar for investigation views (Ask Higgins + Threat Cases).
 * Uses plain StyleSheet.create — NOT makeStyles — to guarantee flexDirection: "row"
 * is never stripped by the fit() pipeline on any device or screen size.
 */
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { fonts, useTheme } from "@/src/theme";

export type InvestigationTabId = "overview" | "evidence" | "history" | "di";

const TAB_LABELS: { id: InvestigationTabId; label: string }[] = [
  { id: "overview", label: "Findings Brief" },
  { id: "evidence", label: "Evidence" },
  { id: "history", label: "History" },
  { id: "di", label: "DI" },
];

export function InvestigationTabBar({ active, onChange, testID = "inv-tab-bar" }: {
  active: InvestigationTabId;
  onChange: (id: InvestigationTabId) => void;
  testID?: string;
}) {
  const { colors } = useTheme();
  return (
    <View
      style={[styles.bar, { borderBottomColor: colors.border, backgroundColor: colors.surfaceSecondary }]}
      testID={testID}
    >
      {TAB_LABELS.map(({ id, label }) => {
        const selected = active === id;
        return (
          <Pressable
            key={id}
            style={[styles.tab, selected && { borderBottomColor: colors.brandPrimary }]}
            onPress={() => onChange(id)}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
            testID={`${testID}-${id}`}
          >
            <Text
              style={[
                styles.tabText,
                { color: selected ? colors.onSurface : colors.muted,
                  fontFamily: selected ? fonts.textSemibold : fonts.textMedium },
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

const styles = StyleSheet.create({
  bar: {
    flexDirection: "row",
    flexWrap: "nowrap",
    borderBottomWidth: 1,
  },
  tab: {
    flex: 1,
    paddingVertical: 12,
    paddingHorizontal: 8,
    alignItems: "center",
    borderBottomWidth: 2,
    borderBottomColor: "transparent",
  },
  tabText: {
    fontSize: 14,
  },
});
