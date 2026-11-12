// Identity illustration only: never authenticates a live caller or invents a business logo.
// Actual contact photos require explicit device permission and an on-device contacts source.
import Building from "lucide-react-native/icons/building";
import ShieldAlert from "lucide-react-native/icons/shield-alert";
import React from "react";
import { Text, View } from "react-native";
import { makeStyles, useTheme } from "@/src/theme";

export type CallerAvatarKind = "unknown" | "business_association" | "risk_warning";

const useStyles = makeStyles((c) => ({
  circle: { width: 40, height: 40, borderRadius: 20, alignItems: "center" as const, justifyContent: "center" as const, backgroundColor: c.surfaceTertiary },
  business: { backgroundColor: c.navyTint },
  risk: { backgroundColor: c.barkingTint },
}));

export function CallerIdentityAvatar({ kind, testID }: { kind: CallerAvatarKind; testID?: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  return (
    <View testID={testID} accessibilityLabel={kind === "business_association" ? "Business association, not verified caller identity" : kind === "risk_warning" ? "Call warning" : "Unknown caller"} style={[s.circle, kind === "business_association" ? s.business : kind === "risk_warning" ? s.risk : null]}>
      {kind === "business_association" ? <Building size={20} color={colors.brand} /> : kind === "risk_warning" ? <ShieldAlert size={20} color={colors.barkingText} /> : <Text style={{ color: colors.muted, fontSize: 20, fontWeight: "600" }}>?</Text>}
    </View>
  );
}
