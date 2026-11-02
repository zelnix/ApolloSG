/**
 * Protection Details — one Device Protection or one Apollo capability on this device.
 *
 * A Device Protection answers, in order: what's its state here (only what a real read said), what
 * changed, what it is and why it matters (Higgins' explanation — pre-written for the common ones,
 * otherwise written once and reused; never per person), what Higgins recommends, and how to check or
 * change it. A setting Apollo can’t read shows “Check manually”; the user can then
 * mark it “Looks good” or “Needs attention” so Apollo reflects their check.
 *
 * Opening a protection clears its "Changed" tag and the Home banner for it.
 */
import { useLocalSearchParams, useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as FS from "expo-file-system/legacy";
import ChevronLeft from "lucide-react-native/icons/chevron-left";
import Info from "lucide-react-native/icons/info";
import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AppMenuButton } from "@/src/components/AppMenu";

import { AlertsButton } from "@/src/components/AlertsButton";
import { Body, Button, Pill, type Tone } from "@/src/components/ui";
import {
  allCapabilityRows, capabilityAdvice, CAPABILITY_CLASS_LABEL, PROTECTION_EVIDENCE_LABEL, protectionStatusLine,
  type DeviceProtectionRow, type ProtectionHealth,
} from "@/src/domain/deviceCapabilities";
import { recentChanges, whatToDoNow } from "@/src/domain/deviceProtectionChanges";
import { deviceProtectionExplanation, ExplanationPending, type ExplanationResult } from "@/src/higgins/protectionExplanation";
import { useApollo } from "@/src/store/ApolloContext";
import { acknowledgeProtectionChanges, useDeviceProtections } from "@/src/store/deviceProtectionStore";
import { loadManualVerdicts, setManualVerdict, clearManualVerdict, type ManualVerdict } from "@/src/store/manualCheckStore";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { openDeviceSettings } from "@/src/utils/deviceSettings";
import { goBackOrHome } from "@/src/utils/navigation";
import Constants from "expo-constants";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.xs },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 18, color: c.onSurface, flex: 1 },

  hero: { paddingHorizontal: spacing.lg, paddingTop: spacing.sm, gap: spacing.xs },
  title: { fontFamily: fonts.displayBold, fontSize: 24, lineHeight: 30, color: c.onSurface },
  subtitle: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurfaceSecondary },

  section: { paddingHorizontal: spacing.lg, marginTop: spacing.xl, gap: spacing.xs },
  sectionTitle: { fontFamily: fonts.displayBold, fontSize: 15, color: c.onSurface },
  text: { fontFamily: fonts.text, fontSize: 15, lineHeight: 23, color: c.onSurfaceSecondary },

  statusCard: { marginHorizontal: spacing.lg, marginTop: spacing.xl, borderRadius: radius.md, borderWidth: 0.5, borderColor: c.border, backgroundColor: c.surfaceSecondary, padding: spacing.lg, gap: spacing.sm },
  statusRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  statusLabel: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.onSurface, flex: 1 },
  attr: { fontFamily: fonts.text, fontSize: 12, lineHeight: 18, color: c.muted },

  step: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.xs },
  stepNum: { fontFamily: fonts.displayBold, fontSize: 14, color: c.brandPrimary, width: 18 },
  stepText: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface, flex: 1 },

  manualNote: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm, marginTop: spacing.md, padding: spacing.md, borderRadius: radius.md, backgroundColor: c.ears_upTint },
  manualNoteText: { fontFamily: fonts.text, fontSize: 13, lineHeight: 19, color: c.onSurface, flex: 1 },
  loadingRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.xs },

  verdictCard: { marginHorizontal: spacing.lg, marginTop: spacing.lg, borderRadius: radius.md, padding: spacing.lg, gap: spacing.md },
  verdictRow: { flexDirection: "row", gap: spacing.sm },
  verdictConfirmed: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  verdictText: { fontFamily: fonts.textMedium, fontSize: 14, lineHeight: 20, color: c.onSurface, flex: 1 },
  verdictTime: { fontFamily: fonts.text, fontSize: 12, color: c.muted },

  actions: { paddingHorizontal: spacing.lg, marginTop: spacing.xl, gap: spacing.sm },
}));

function dayLabel(iso: string): string {
  return new Date(iso).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
}

const HEALTH_PILL: Record<ProtectionHealth, Tone> = {
  protected: "resting", review: "growling", action: "biting", check_manually: "ears_up", unable: "unknown", not_available: "unknown",
};

type ExplanationState = { status: "loading" } | { status: "ready"; result: ExplanationResult } | { status: "none"; message: string } | { status: "failed"; message: string };

/** The reviewed explanation of this protection — from the device's copy, else ApolloSG's backend (once registered). */
function useExplanation(row: DeviceProtectionRow | null, deviceId: string | null): { state: ExplanationState; retry: () => void } {
  const rowId = row?.id;
  const [state, setState] = useState<ExplanationState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!rowId || !deviceId) return;
    let cancelled = false;
    setState({ status: "loading" });
    deviceProtectionExplanation({ id: rowId })
      .then((result) => { if (!cancelled) setState({ status: "ready", result }); })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState(error instanceof ExplanationPending ? { status: "none", message: error.message }
          : { status: "failed", message: "Higgins couldn’t load this explanation right now. Nothing has been made up in its place." });
      });
    return () => { cancelled = true; };
  }, [rowId, deviceId, attempt]);
  return { state, retry: () => setAttempt((n) => n + 1) };
}

export default function CapabilityDetailScreen() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { showToast, deviceId } = useApollo();
  const assessment = useDeviceProtections();

  const capability = assessment ? allCapabilityRows(assessment.reading.view).find((r) => r.id === id) ?? null : null;
  const protectionRow = assessment?.reading.view.deviceProtects.find((r) => r.id === id) ?? null;
  const changes = assessment ? recentChanges(assessment.changes, Date.now()).filter((c) => c.protectionId === id).slice(0, 5) : [];
  const explanation = useExplanation(protectionRow, deviceId);

  // Opening a protection is what clears its "Changed" tag and the Home banner.
  const hasAssessment = assessment !== null;
  useEffect(() => { if (hasAssessment) void acknowledgeProtectionChanges(String(id)); }, [hasAssessment, id]);

  const row = capability ?? protectionRow;
  const statusLabel = capability ? CAPABILITY_CLASS_LABEL[capability.klass] : protectionRow?.stateLabel ?? "";
  const guidance = protectionRow?.guidance ?? null;
  const action = capability?.action ?? guidance?.action ?? null;
  const manual = protectionRow?.health === "check_manually" || protectionRow?.health === "unable";

  // Manual-check verdict: user can mark unreadable settings as "safe" or "concern"
  const [manualVerdict, setManualVerdictState] = useState<ManualVerdict | null>(null);
  const [verdictTime, setVerdictTime] = useState<string | null>(null);
  useEffect(() => {
    if (!manual) return;
    void loadManualVerdicts().then((v) => {
      const entry = v[String(id)];
      if (entry) { setManualVerdictState(entry.verdict); setVerdictTime(entry.checkedAt); }
    });
  }, [manual, id]);

  const handleVerdict = async (verdict: ManualVerdict) => {
    await setManualVerdict(String(id), verdict);
    setManualVerdictState(verdict);
    setVerdictTime(new Date().toISOString());
    showToast(verdict === "safe" ? "Marked as checked — looks good" : "Marked as needing attention", "neutral");
  };

  const handleClearVerdict = async () => {
    await clearManualVerdict(String(id));
    setManualVerdictState(null);
    setVerdictTime(null);
    setVerifyResult(null);
  };

  // ── Screenshot verification flow ────────────────────────────────────────
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<{ confirmed: boolean; summary: string; advice: string | null } | null>(null);

  const BASE_URL = Constants.expoConfig?.extra?.EXPO_BACKEND_URL ?? "";

  const pickAndVerify = useCallback(async () => {
    try {
      // Ask for photo library permission
      let perm = await ImagePicker.getMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (!perm.granted) {
          showToast("Photo library access is needed to verify the setting.", "neutral");
          return;
        }
      }

      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        quality: 0.7,
        base64: false,
      });
      if (result.canceled || !result.assets?.[0]?.uri) return;

      setVerifying(true);
      setVerifyResult(null);

      // Read image as base64
      let imageBase64: string;
      if (Platform.OS === "web") {
        const resp = await fetch(result.assets[0].uri);
        const blob = await resp.blob();
        imageBase64 = await new Promise<string>((resolve) => {
          const reader = new FileReader();
          reader.onloadend = () => resolve((reader.result as string).split(",")[1]);
          reader.readAsDataURL(blob);
        });
      } else {
        imageBase64 = await FS.readAsStringAsync(result.assets[0].uri, { encoding: FS.EncodingType.Base64 });
      }

      const expectedState = guidance?.recommended ?? "disabled or off";
      const response = await fetch(`${BASE_URL}/api/protections/device/verify-screenshot`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          setting_id: String(id),
          setting_name: protectionRow?.title ?? String(id),
          expected_state: expectedState,
          image_base64: imageBase64,
          device_id: deviceId,
        }),
      });

      if (!response.ok) {
        setVerifyResult({ confirmed: false, summary: "Verification request failed.", advice: "Try again in a moment." });
        return;
      }

      const data = await response.json();
      setVerifyResult({ confirmed: data.confirmed, summary: data.summary, advice: data.advice });

      // Auto-save verdict if AI confirms
      if (data.confirmed) {
        await handleVerdict("safe");
      }
    } catch (err) {
      setVerifyResult({ confirmed: false, summary: "Something went wrong reading the screenshot.", advice: "Try again." });
    } finally {
      setVerifying(false);
    }
  }, [id, protectionRow, guidance, deviceId, BASE_URL]);

  return (
    <View style={s.root} testID="capability-detail-screen">
      <View style={{ paddingTop: insets.top }}>
        <View style={s.header}>
          <Pressable accessibilityRole="button" accessibilityLabel="Back" testID="capability-back" onPress={() => goBackOrHome(router)} style={{ width: 44, height: 44, alignItems: "center", justifyContent: "center" }}>
            <ChevronLeft size={24} color={colors.onSurface} />
          </Pressable>
          <Text style={s.headerTitle} numberOfLines={1}>{capability ? "What ApolloSG can use" : "Device Protection"}</Text>
          <AlertsButton testID="capability-alerts" />
          <AppMenuButton testID="capability-menu" />
        </View>
      </View>

      <ScrollView contentContainerStyle={{ paddingBottom: spacing["3xl"] }} showsVerticalScrollIndicator={false}>
        {!row ? (
          <View style={s.section}>
            <Body testID="capability-missing">
              {!assessment ? "Reading this device…" : "ApolloSG doesn’t have anything by that name. Go back to Device Protections and tap the row you want."}
            </Body>
          </View>
        ) : protectionRow ? (
          <>
            <View style={s.hero}>
              <Text style={s.title} testID="capability-title">{protectionRow.title}</Text>
              <Text style={s.subtitle}>{protectionRow.subtitle}</Text>
            </View>

            <View style={s.statusCard} testID="capability-status">
              <View style={s.statusRow}>
                <Text style={s.statusLabel}>On this device</Text>
                <Pill tone={HEALTH_PILL[protectionRow.health]} label={protectionRow.stateLabel} compact testID="capability-status-pill" />
              </View>
              <Text style={s.text} testID="capability-status-detail">{protectionStatusLine(protectionRow)}</Text>
              <Text style={s.attr} testID="capability-evidence">
                {PROTECTION_EVIDENCE_LABEL[protectionRow.evidence]} · {protectionRow.evidence === "apollo_verified" ? "Reported by" : "Provided by"} {protectionRow.attributedTo}
              </Text>
              {protectionRow.evidenceLine ? <Text style={s.attr}>{protectionRow.evidenceLine}</Text> : null}
            </View>

            {changes.length ? (
              <View style={s.section} testID="capability-changes">
                <Text style={s.sectionTitle}>What changed</Text>
                {changes.map((change) => (
                  <View key={change.id} style={{ gap: 2 }}>
                    <Text style={s.text}>{dayLabel(change.at)} — {change.text}</Text>
                    <Text style={s.text} testID={`capability-change-todo-${change.id}`}>
                      <Text style={{ fontFamily: fonts.textSemibold }}>Higgins: </Text>{whatToDoNow(change)}
                    </Text>
                  </View>
                ))}
                <Text style={s.attr}>Apollo reports what it saw change on this device, not who changed it or why.</Text>
              </View>
            ) : null}

            {explanation.state.status === "ready" ? (
              <>
                <View style={s.section} testID="capability-what">
                  <Text style={s.sectionTitle}>What it is</Text>
                  <Text style={s.text}>{explanation.state.result.explanation.what}</Text>
                </View>
                <View style={s.section} testID="capability-why">
                  <Text style={s.sectionTitle}>Why it matters</Text>
                  <Text style={s.text}>{explanation.state.result.explanation.why}</Text>
                </View>
                <View style={s.section} testID="capability-protects-against">
                  <Text style={s.sectionTitle}>What it protects you against</Text>
                  <Text style={s.text}>{explanation.state.result.explanation.protectsAgainst}</Text>
                  <Text style={s.attr} testID="capability-explanation-source">Explanation reviewed by Apollo.</Text>
                </View>
              </>
            ) : (
              <View style={s.section} testID="capability-explanation">
                <Text style={s.sectionTitle}>What it is</Text>
                {explanation.state.status === "loading" ? (
                  <View style={s.loadingRow}>
                    <ActivityIndicator size="small" color={colors.brandPrimary} />
                    <Text style={s.text}>Higgins is getting the explanation…</Text>
                  </View>
                ) : explanation.state.status === "none" ? (
                  <Text style={s.text} testID="capability-explanation-none">{explanation.state.message}</Text>
                ) : (
                  <>
                    <Text style={s.text} testID="capability-explanation-failed">{explanation.state.message}</Text>
                    <Button testID="capability-explanation-retry" variant="ghost" label="Try again" onPress={explanation.retry} />
                  </>
                )}
              </View>
            )}

            {guidance ? (
              <View style={s.section}>
                <Text style={s.sectionTitle}>What Higgins recommends</Text>
                <Text style={s.text} testID="capability-advice">{guidance.recommended}</Text>
              </View>
            ) : null}

            {guidance?.steps.length ? (
              <View style={s.section} testID="capability-steps">
                <Text style={s.sectionTitle}>{manual ? "How to check it yourself" : "How to change it"}</Text>
                {guidance.steps.map((step, i) => (
                  <View key={i} style={s.step}>
                    <Text style={s.stepNum}>{i + 1}</Text>
                    <Text style={s.stepText}>{step}</Text>
                  </View>
                ))}
                {manual ? (
                  manualVerdict ? (
                    <View style={[s.verdictCard, { backgroundColor: manualVerdict === "safe" ? colors.restingTint : colors.ears_upTint }]} testID="capability-verdict-confirmed">
                      <View style={[s.verdictConfirmed, { flexDirection: "row" }]}>
                        <Text style={s.verdictText}>
                          {manualVerdict === "safe"
                            ? (verifyResult?.confirmed ? "Higgins confirmed this looks good." : "You checked this and it looks good.")
                            : "You flagged this as needing attention."}
                        </Text>
                      </View>
                      {verifyResult?.summary ? <Text style={s.text}>{verifyResult.summary}</Text> : null}
                      {verdictTime ? <Text style={s.verdictTime}>Checked {dayLabel(verdictTime)}</Text> : null}
                      <Pressable onPress={handleClearVerdict} testID="capability-verdict-clear">
                        <Text style={[s.verdictTime, { textDecorationLine: "underline" }]}>Re-check</Text>
                      </Pressable>
                    </View>
                  ) : verifying ? (
                    <View style={[s.verdictCard, { backgroundColor: colors.surfaceSecondary }]} testID="capability-verdict-verifying">
                      <View style={[s.verdictConfirmed, { flexDirection: "row" }]}>
                        <ActivityIndicator size="small" color={colors.brandPrimary} />
                        <Text style={s.verdictText}>Higgins is checking your screenshot…</Text>
                      </View>
                    </View>
                  ) : verifyResult && !verifyResult.confirmed ? (
                    <View style={[s.verdictCard, { backgroundColor: colors.ears_upTint }]} testID="capability-verdict-not-confirmed">
                      <Text style={[s.verdictText, { fontFamily: fonts.textSemibold }]}>Higgins couldn’t confirm this setting</Text>
                      <Text style={s.text}>{verifyResult.summary}</Text>
                      {verifyResult.advice ? <Text style={s.text}>{verifyResult.advice}</Text> : null}
                      <View style={[s.verdictRow, { flexDirection: "row" }]}>
                        <Button
                          testID="capability-verdict-retry-screenshot"
                          label="Send another screenshot"
                          onPress={() => { void pickAndVerify(); }}
                          size="small"
                        />
                        <Button
                          testID="capability-verdict-manual-concern"
                          label="Needs attention"
                          variant="ghost"
                          onPress={() => { void handleVerdict("concern"); }}
                          size="small"
                        />
                      </View>
                    </View>
                  ) : (
                    <View style={[s.verdictCard, { backgroundColor: colors.ears_upTint }]} testID="capability-verdict-ask">
                      <Text style={s.verdictText}>
                        Apollo can’t read this setting directly. Take a screenshot showing it, and Higgins will check it for you.
                      </Text>
                      <View style={[s.verdictRow, { flexDirection: "row" }]}>
                        <Button
                          testID="capability-verdict-safe"
                          label="Send screenshot to verify"
                          onPress={() => { void pickAndVerify(); }}
                          size="small"
                        />
                        <Button
                          testID="capability-verdict-concern"
                          label="Needs attention"
                          variant="ghost"
                          onPress={() => { void handleVerdict("concern"); }}
                          size="small"
                        />
                      </View>
                    </View>
                  )
                ) : null}
              </View>
            ) : null}
          </>
        ) : capability ? (
          <>
            <View style={s.hero}>
              <Text style={s.title} testID="capability-title">{capability.title}</Text>
            </View>

            <View style={s.section}>
              <Text style={s.sectionTitle}>What it does</Text>
              <Text style={s.text} testID="capability-what">{capability.what}</Text>
            </View>

            <View style={s.section}>
              <Text style={s.sectionTitle}>How it helps protect you</Text>
              <Text style={s.text} testID="capability-benefit">{capability.benefit}</Text>
            </View>

            <View style={s.statusCard} testID="capability-status">
              <View style={s.statusRow}>
                <Text style={s.statusLabel}>Current status</Text>
                <Pill
                  tone={capability.klass === "apollo_can_use" ? "resting" : capability.klass === "permission_required" ? "ears_up" : capability.klass === "unknown" ? "growling" : "unknown"}
                  label={statusLabel}
                  compact
                  testID="capability-status-pill"
                />
              </View>
              <Text style={s.text} testID="capability-status-detail">{capability.detail}</Text>
              {capability.attributedTo !== "Apollo" ? <Text style={s.attr}>Reported by {capability.attributedTo}</Text> : null}
            </View>

            <View style={s.section}>
              <Text style={s.sectionTitle}>What you should do</Text>
              <Text style={s.text} testID="capability-advice">
                {capabilityAdvice(capability) ?? "Nothing. ApolloSG is already using this whenever it checks something for you."}
              </Text>
            </View>
          </>
        ) : null}

        {row ? (
          <View style={s.actions}>
            {row.id === "au_carrier_scam_blocking" ? (
              <Button
                testID="capability-carrier-warning"
                label="I got a ‘Potential Fraud’ warning"
                onPress={() => router.push({ pathname: "/call-guard", params: { carrierWarning: "potential_fraud" } })}
              />
            ) : null}
            {action ? (
              <Button
                testID="capability-open-settings"
                label={Platform.OS === "web" ? `Show me where: ${action.label}` : action.label}
                onPress={() => { void openDeviceSettings(action.target, action.path, (m) => showToast(m, "neutral")); }}
              />
            ) : null}
            <Button
              testID="capability-ask-higgins"
              variant="ghost"
              label="Ask Higgins about this"
              onPress={() => router.push({ pathname: "/(tabs)/ask", params: { prompt: `Can you explain “${row.title}” on my phone? ApolloSG says its status is “${statusLabel}”. What does that mean for me and should I do anything?` } })}
            />
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}
