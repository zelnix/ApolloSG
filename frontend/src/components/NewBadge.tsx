// The "New" mark on a case the person hasn't opened yet (hooks/useNewCases.ts).
import React from "react";
import { StyleSheet, Text, View } from "react-native";

import { fonts, radius, spacing, useTheme } from "@/src/theme";

export function NewBadge({ testID }: { testID?: string }) {
  const { colors } = useTheme();
  return (
    <View style={[st.badge, { backgroundColor: colors.brand }]} testID={testID} accessibilityLabel="New case">
      <Text style={[st.text, { color: colors.onBrandPrimary }]}>New</Text>
    </View>
  );
}

const st = StyleSheet.create({
  badge: { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.pill },
  text: { fontFamily: fonts.textSemibold, fontSize: 10, letterSpacing: 0.3 },
});
