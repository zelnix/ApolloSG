/** Global fail-closed admission boundary for all ApolloSG routes.
 * This must mount outside ApolloProvider and the navigation stack.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { AppState, Text, View, Pressable, ScrollView, useWindowDimensions } from "react-native";
import { Image } from "expo-image";
import { PreparingApolloSplash } from "@/src/components/LaunchSplash";
import { startupStage } from "@/src/startup/startupStages";
import { checkRequiredSLMCompatibility, downloadPrivateLuddishForTest, rollbackSLMSetup } from "./bootstrap";

type State = { status: "checking" | "ready" | "incompatible"; reason: string; stage?: string };

export function RequiredSLMGate({ children }: { children: ReactNode }) {
  const { width, height } = useWindowDimensions();
  const isTablet = Math.min(width, height) >= 600;
  const [state, setState] = useState<State>({ status: "checking", reason: "" });
  const generation = useRef(0);
  const inFlight = useRef(false);
  const verify = useCallback(async (install = false) => {
    // Never overlap non-cancellable native model verification attempts.
    if (inFlight.current) return;
    inFlight.current = true;
    const attempt = ++generation.current;
    startupStage("on_device_ai", "started");
    setState({ status: "checking", reason: "", stage: "hardware" });
    // Model checksum verification and the first native inference can take longer
    // than 45 seconds on real devices. A timer cannot cancel that native work.
    // Keep the protection gate closed until the actual verifier resolves.
    const slowNotice = setTimeout(() => {
      if (attempt === generation.current) {
        setState(current => current.status === "checking"
          ? { ...current, reason: "The first On-device AI check is taking longer than usual. Protection has not started." }
          : current);
      }
    }, 45000);
    try {
      if (install) {
        const installed = await downloadPrivateLuddishForTest();
        if (!installed) {
          if (attempt === generation.current) {
            startupStage("on_device_ai", "failed", "model_install_failed");
            setState({ status: "incompatible", reason: "The required On-device AI model could not be installed." });
          }
          return;
        }
      }
      const admission = await checkRequiredSLMCompatibility(stage => {
        if (attempt === generation.current) setState(current => ({
          status: "checking", reason: current.reason, stage,
        }));
      });
      if (attempt !== generation.current) return;
      startupStage("on_device_ai", admission.compatible ? "completed" : "failed", admission.compatible ? undefined : "admission_rejected");
      if (!admission.compatible) {
        setState({ status: "incompatible", reason: admission.reason });
        void rollbackSLMSetup().catch(() => undefined);
      } else setState({ status: "ready", reason: "" });
    } catch {
      if (attempt !== generation.current) return;
      startupStage("on_device_ai", "failed");
      setState({ status: "incompatible", reason: "Required On-device AI verification failed." });
      void rollbackSLMSetup().catch(() => undefined);
    } finally {
      clearTimeout(slowNotice);
      inFlight.current = false;
    }
  }, []);
  useEffect(() => {
    void verify();
    const subscription = AppState.addEventListener("change", next => {
      if (next === "active" && !inFlight.current) void verify();
    });
    return () => { generation.current++; subscription.remove(); };
  }, [verify]);
  if (state.status === "ready") return <>{children}</>;
  if (state.status === "checking") {
    const descriptions: Record<string, string> = {
      hardware: "Checking device hardware", model_integrity: "Verifying On-device AI model",
      runtime_registration: "Preparing On-device AI runtime", inference: "Loading On-device AI and testing reasoning",
      response_validation: "Validating On-device AI response",
    };
    return <PreparingApolloSplash message={state.reason || ("Preparing ApolloSG… " + (descriptions[state.stage ?? ""] ?? "Checking device compatibility"))} />;
  }
  return <ScrollView contentContainerStyle={{ flexGrow: 1, backgroundColor: "#FFFFFF", alignItems: "center", justifyContent: "center", paddingHorizontal: 24, paddingVertical: 32 }} testID="slm-admission-error">
    <Image source={isTablet ? require("@/assets/images/splash-full-tablet.webp") : require("@/assets/images/splash-full.webp")}
      style={{ width: "100%", height: Math.min(height * 0.49, isTablet ? 420 : 350) }}
      contentFit="contain" accessibilityLabel="ApolloSG Scam Guard" />
    <View style={{ width: "100%", maxWidth: 460, alignItems: "center", gap: 14, paddingTop: 12 }}>
      <Text style={{ fontSize: 21, fontWeight: "700", color: "#183153", textAlign: "center" }}>ApolloSG needs your attention</Text>
      <Text style={{ fontSize: 15, color: "#183153", textAlign: "center" }}>{state.reason}</Text>
      <Text style={{ fontSize: 14, color: "#42546A", textAlign: "center" }}>Protection has not started. You can retry the check or install the required On-device AI model.</Text>
      <Pressable accessibilityRole="button" style={{ backgroundColor: "#183153", borderRadius: 10, paddingVertical: 14, paddingHorizontal: 22, width: "100%", alignItems: "center" }}
        onPress={() => { void verify(); }}>
        <Text style={{ color: "#FFFFFF", fontWeight: "700" }}>Retry compatibility check</Text>
      </Pressable>
      <Pressable accessibilityRole="button" style={{ borderWidth: 1, borderColor: "#183153", borderRadius: 10, paddingVertical: 14, paddingHorizontal: 18, width: "100%", alignItems: "center" }}
        onPress={() => { void verify(true); }}>
        <Text style={{ color: "#183153", fontWeight: "700", textAlign: "center" }}>Install On-device AI and retry</Text>
      </Pressable>
    </View>
  </ScrollView>;
}
