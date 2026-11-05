// One plain sentence under a finished result naming the rule that settled it, e.g. "Settled by TC FlyBy —
// Known scam, every step: …". Hidden when the person turned it off in Settings, and when the case's
// record doesn't say (never guessed).
import React from "react";
import { Text, View } from "react-native";

import type { SettledReason } from "@/src/investigation/types";
import { useShowResultReasons } from "@/src/store/resultReasonsStore";
import { fonts, makeStyles, spacing } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  wrap: { minHeight: 44, justifyContent: "center", paddingVertical: spacing.xs },
  text: { fontFamily: fonts.text, fontSize: 13, lineHeight: 19, color: c.onSurfaceSecondary },
}));

export function SettledReasonLine({ reason, testID = "settled-reason" }: { reason: Pick<SettledReason, "sentence"> | null | undefined; testID?: string }) {
  const s = useStyles();
  const show = useShowResultReasons();
  if (!reason?.sentence || !show) return null;
  return (
    <View accessibilityRole="text" testID={testID} style={s.wrap}>
      <Text style={s.text}>{reason.sentence}</Text>
    </View>
  );
}
