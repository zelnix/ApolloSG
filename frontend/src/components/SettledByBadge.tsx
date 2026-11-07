// "Settled by TC Hawkeye" / "Settled by Magnum DI" — who settled a threat's investigation. Shown only once
// the investigation has finished and this device recorded who settled it; never guessed.
import ScanSearch from "lucide-react-native/icons/scan-search";
import Zap from "lucide-react-native/icons/zap";
import React from "react";
import { Text, View } from "react-native";

import { settledBy } from "@/src/domain/threatCase";
import type { PatrolEvent } from "@/src/domain/types";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  badge: { flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start", marginTop: spacing.xs, paddingHorizontal: spacing.sm,
    paddingVertical: 2, borderRadius: radius.pill, backgroundColor: c.goldTint, borderWidth: 0.5, borderColor: c.goldBorder },
  text: { fontFamily: fonts.textSemibold, fontSize: 11, color: c.onSurface },
}));

export function SettledByBadge({ event, testID }: { event: Pick<PatrolEvent, "investigation_completed_at" | "investigation_answered_by">; testID?: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  const settled = settledBy(event);
  if (!settled) return null;
  const Icon = settled === "TC Hawkeye" ? Zap : ScanSearch;
  return (
    <View style={s.badge} testID={testID} accessibilityLabel={`Settled by ${settled}`}>
      <Icon size={11} color={colors.onSurfaceSecondary} />
      <Text style={s.text}>Settled by {settled}</Text>
    </View>
  );
}
