/** Global fail-closed admission boundary for all ApolloSG routes.
 * This must mount outside ApolloProvider and the navigation stack.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { AppState, Text, View, Pressable } from "react-native";
import { PreparingApolloSplash } from "@/src/components/LaunchSplash";
import { startupStage } from "@/src/startup/startupStages";
import { checkRequiredSLMCompatibility, downloadPrivateLuddishForTest, rollbackSLMSetup } from "./bootstrap";

type State = { status: "checking" | "ready" | "incompatible"; reason: string; stage?: string };

export function RequiredSLMGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: "checking", reason: "" });
  const generation = useRef(0);
  const verify = useCallback(async (install = false) => {
    const attempt = ++generation.current;
    startupStage("on_device_ai", "started");
    setState({ status: "checking", reason: "", stage: "hardware" });
    let deadline: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => {
      deadline = setTimeout(() => reject(new Error("timeout")), install ? 120000 : 45000);
    });
    try {
      const admission = await Promise.race([timeout, (async () => {
        if (install) {
          const installed = await downloadPrivateLuddishForTest();
          if (!installed) return { compatible: false, reason: "The required On-device AI model could not be installed." };
        }
        return checkRequiredSLMCompatibility(stage => {
          if (attempt === generation.current) setState({ status: "checking", reason: "", stage });
        });
      })()]);
      if (attempt !== generation.current) return;
      startupStage("on_device_ai", admission.compatible ? "completed" : "failed", admission.compatible ? undefined : "admission_rejected");
      if (!admission.compatible) {
        setState({ status: "incompatible", reason: admission.reason });
        void rollbackSLMSetup().catch(() => undefined);
      } else setState({ status: "ready", reason: "" });
    } catch (error) {
      if (attempt !== generation.current) return;
      startupStage("on_device_ai", error instanceof Error && error.message === "timeout" ? "timed_out" : "failed");
      setState({ status: "incompatible", reason: error instanceof Error && error.message === "timeout"
        ? "Device compatibility could not be verified within the startup time limit. ApolloSG has not started protection."
        : "Required On-device AI verification failed." });
      void rollbackSLMSetup().catch(() => undefined);
    } finally {
      if (deadline) clearTimeout(deadline);
    }
  }, []);
  useEffect(() => {
    void verify();
    const subscription = AppState.addEventListener("change", next => {
      if (next === "active") void verify();
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
    return <PreparingApolloSplash message={"Preparing ApolloSG… " + (descriptions[state.stage ?? ""] ?? "Checking device compatibility")} />;
  }
  return <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 16 }}>
      <Text style={{ fontSize: 22, fontWeight: "700", textAlign: "center" }}>ApolloSG cannot start on this device</Text>
      <Text style={{ textAlign: "center" }}>{state.reason}</Text>
      <Text style={{ textAlign: "center" }}>No ApolloSG protection has been started. You can remove the app using your device settings.</Text>
      <Pressable accessibilityRole="button" onPress={() => { void verify(true); }}>
        <Text style={{ fontWeight: "700" }}>Install required On-device AI and retry</Text>
      </Pressable>
      <Pressable accessibilityRole="button" onPress={() => { void verify(); }}>
        <Text style={{ fontWeight: "700" }}>Retry compatibility check</Text>
      </Pressable>
  </View>;
}
