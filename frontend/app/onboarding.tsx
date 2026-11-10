import { useRouter } from "expo-router";
import Eye from "lucide-react-native/icons/eye";
import Lock from "lucide-react-native/icons/lock";
import ShieldCheck from "lucide-react-native/icons/shield-check";
import React, { useState } from "react";
import { Alert, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { BrandBanner } from "@/src/components/BrandBanner";
import { SetupProgress } from "@/src/components/SetupProgress";
import { Body, Button, Card, Pill } from "@/src/components/ui";
import { PRIVACY_POLICY_SUMMARY } from "@/src/domain/privacy";
import { STATE_LABEL, STATE_MEANING, STATE_NAME, type ApolloState } from "@/src/domain/types";
import { useApollo } from "@/src/store/ApolloContext";
import { fonts, makeStyles, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  content: { paddingHorizontal: spacing.xl, gap: spacing.lg },
  title: { fontFamily: fonts.displayBold, fontSize: 34, color: c.onSurface, letterSpacing: -0.5, lineHeight: 40 },
  stateRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.md, paddingVertical: spacing.sm },
  stateText: { flex: 1, gap: 2 },
  stateName: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.onSurface },
  bullet: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  footer: { paddingHorizontal: spacing.xl, paddingTop: spacing.md, gap: spacing.sm },
  note: { fontFamily: fonts.text, fontSize: 12, color: c.muted, textAlign: "center" },
}));

const STATES: ApolloState[] = ["resting", "ears_up", "growling", "barking", "biting"];

export default function Onboarding() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { adapterLabel } = useApollo();
  const [checkingCompatibility, setCheckingCompatibility] = useState(false);
  const [compatibilityMessage, setCompatibilityMessage] = useState("");
  const checkCompatibility = async () => {
    if (checkingCompatibility) return;
    setCheckingCompatibility(true);
    try {
      const slm = await import("@/src/domain/slm/bootstrap");
      const result = await slm.checkRequiredSLMCompatibility();
      setCompatibilityMessage(result.reason);
      if (result.compatible) router.push("/privacy-disclosure");
      else Alert.alert("Device not compatible", result.reason + " ApolloSG setup cannot continue.");
    } catch {
      setCompatibilityMessage("Required On-device AI compatibility check failed.");
      Alert.alert("Device not compatible", "ApolloSG setup cannot continue without the required On-device AI.");
    } finally { setCheckingCompatibility(false); }
  };

  return (
    <View style={s.root} testID="initial-onboarding-root">
      <View style={{ paddingTop: insets.top + spacing.md }}><SetupProgress step={1} /></View>
      <ScrollView contentContainerStyle={[s.content, { paddingTop: spacing.lg, paddingBottom: spacing.xl }]} testID="onboarding-screen">
        <BrandBanner testID="onboarding-banner" />
        <Text style={s.title}>Meet Apollo, your calm protector for the links you tap.</Text>
        <Body>Apollo checks dangerous links, suspicious websites and known online threats. It tells you exactly what it can see, and never pretends to protect what it can&apos;t.</Body>

        <Card>
          {STATES.map((st) => (
            <View key={st} style={s.stateRow}>
              <Pill tone={st} label={STATE_NAME[st]} />
              <View style={s.stateText}>
                <Text style={s.stateName}>{STATE_LABEL[st]}</Text>
                <Body>{STATE_MEANING[st]}</Body>
              </View>
            </View>
          ))}
        </Card>

        <Card>
          <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.md }}>
            <Lock size={18} color={colors.resting} />
            <Text style={s.stateName}>Privacy first</Text>
          </View>
          {PRIVACY_POLICY_SUMMARY.map((line) => (
            <View key={line} style={[s.bullet, { marginBottom: spacing.sm }]}>
              <Eye size={14} color={colors.muted} style={{ marginTop: 4 }} />
              <Body style={{ flex: 1 }}>{line}</Body>
            </View>
          ))}
        </Card>

      </ScrollView>
      <View style={[s.footer, { paddingBottom: insets.bottom + spacing.lg }]}>
        <Button testID="onboarding-start-button" label={checkingCompatibility ? "Checking device…" : "Check compatibility & continue"} onPress={checkCompatibility} icon={<ShieldCheck size={18} color={colors.onBrandPrimary} />} />
        {compatibilityMessage ? <Text style={s.note}>{compatibilityMessage}</Text> : null}
        <Text style={s.note}>ApolloSG requires a working On-device AI model before setup can continue.</Text>
      </View>
    </View>
  );
}
