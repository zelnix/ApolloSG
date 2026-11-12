// "Is Apollo this device's call screener?" — asked and answered honestly, in the
// one place a person goes when they care about calls.
//
// Being the default screener is what makes automatic call protection possible at
// all: Android hands every incoming call to the app holding the role, before it
// rings. Until this session the role was only ever offered once, during setup, so
// anyone who skipped it had no way back. It now lives here too.
//
// On iPhone there is nothing to offer. Apple provides no call-screening role to
// any app, so this says so rather than implying Apollo could have it.

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
      ) : null}
    </View>
  );
}
