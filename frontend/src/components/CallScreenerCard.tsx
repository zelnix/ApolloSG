// Existing Call Gate surface for native incoming-call protection setup.
// Role or extension enabled does not prove an individual call was blocked.

import PhoneIncoming from "lucide-react-native/icons/phone-incoming";
import React from "react";
import { Text, View } from "react-native";

import { useCallScreener } from "@/src/hooks/useCallScreener";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { Body, Button, Pill, type Tone } from "./ui";

const TONE: Record<string, Tone> = {
  held: "neutral",
  ios_enabled: "neutral",
  ios_unavailable: "unknown",
  available: "growling",
  unsupported: "unknown",
  ios: "unknown",
  unavailable: "unknown",
  checking: "neutral",
};

const useStyles = makeStyles((c) => ({
  card: { backgroundColor: c.surfaceSecondary, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.md, borderWidth: 0.25, borderColor: c.border },
  head: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  well: { width: 44, height: 44, borderRadius: 22, backgroundColor: c.navyTint, alignItems: "center", justifyContent: "center" },
  title: { fontFamily: fonts.displayBold, fontSize: 17, color: c.onSurface, flex: 1 },
}));

export function CallScreenerCard({ testID = "call-screener-card" }: { testID?: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  const screener = useCallScreener();

  return (
    <View style={s.card} testID={testID}>
      <View style={s.head}>
        <View style={s.well}><PhoneIncoming size={22} color={colors.brand} /></View>
        <Text style={s.title}>Incoming Call Protection</Text>
      </View>
      <Pill tone={TONE[screener.state]} label={screener.summary} testID={`${testID}-status`} />
      <Body testID={`${testID}-detail`}>{screener.detail}</Body>
      {screener.canRequest ? (
        <>
          <Body>{screener.state === "ios" ? "Enable ApolloSG under Call Blocking & Identification in iPhone Settings." : "Choose ApolloSG as your Caller ID & spam app in Android Settings."}</Body>
          <Button
            testID={`${testID}-request`}
            label={screener.requesting ? "Opening…" : screener.state === "ios" ? "Open iPhone Settings" : "Enable protection"}
            onPress={() => void screener.request()}
            disabled={screener.requesting}
          />
        </>
      ) : (
        <Button testID={testID + "-refresh"} variant="secondary" label="Check status again" onPress={() => void screener.refresh()} />
      )}
    </View>
  );
}
