/** Global fail-closed admission boundary for all ApolloSG routes.
 * This must mount outside ApolloProvider and the navigation stack.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { AppState, Text, View, Pressable } from "react-native";
import { PreparingApolloSplash } from "@/src/components/LaunchSplash";
import { checkRequiredSLMCompatibility, downloadPrivateLuddishForTest, rollbackSLMSetup } from "./bootstrap";

type State = { status: "checking" | "ready" | "incompatible"; reason: string };

export function RequiredSLMGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: "checking", reason: "" });
  const generation = useRef(0);
  const verify = useCallback(async (install = false) => {
    const attempt = ++generation.current;
    setState({ status: "checking", reason: "" });
    let deadline: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => {
      deadline = setTimeout(() => reject(new Error("timeout")), install ? 120000 : 45000);
    });
    try {
      const admission = await Promise.race([timeout, (async () => {
        if (install) {
          const installed = await downloadPrivateLuddishForTest();
          if (!installed) return { compatible: false, reason: "The required on-device AI model could not be installed." };
        }
        return checkRequiredSLMCompatibility();
      })()]);
      if (attempt !== generation.current) return;
      if (!admission.compatible) {
        setState({ status: "incompatible", reason: admission.reason });
        void rollbackSLMSetup().catch(() => undefined);
      } else setState({ status: "ready", reason: "" });
    } catch (error) {
      if (attempt !== generation.current) return;
      setState({ status: "incompatible", reason: error instanceof Error && error.message === "timeout"
        ? "Device compatibility could not be verified within the startup time limit. ApolloSG has not started protection."
        : "Required on-device AI verification failed." });
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
    return <PreparingApolloSplash message="Preparing ApolloSG… Checking device compatibility" />;
  }
  return <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 16 }}>
      <Text style={{ fontSize: 22, fontWeight: "700", textAlign: "center" }}>ApolloSG cannot start on this device</Text>
      <Text style={{ textAlign: "center" }}>{state.reason}</Text>
      <Text style={{ textAlign: "center" }}>No ApolloSG protection has been started. You can remove the app using your device settings.</Text>
      <Pressable accessibilityRole="button" onPress={() => { void verify(true); }}>
        <Text style={{ fontWeight: "700" }}>Install required AI and retry</Text>
      </Pressable>
      <Pressable accessibilityRole="button" onPress={() => { void verify(); }}>
        <Text style={{ fontWeight: "700" }}>Retry compatibility check</Text>
      </Pressable>
  </View>;
}
