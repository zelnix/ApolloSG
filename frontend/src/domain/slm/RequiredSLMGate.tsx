/** Global fail-closed admission boundary for all ApolloSG routes.
 * This must mount outside ApolloProvider and the navigation stack.
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ActivityIndicator, AppState, Text, View, Pressable } from "react-native";
import { checkRequiredSLMCompatibility, downloadPrivateLuddishForTest, rollbackSLMSetup } from "./bootstrap";

type State = { status: "checking" | "ready" | "incompatible"; reason: string };

export function RequiredSLMGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: "checking", reason: "" });
  const verify = useCallback(async (install = false) => {
    setState({ status: "checking", reason: "" });
    try {
      if (install) await downloadPrivateLuddishForTest();
      const admission = await checkRequiredSLMCompatibility();
      if (!admission.compatible) await rollbackSLMSetup();
      setState({ status: admission.compatible ? "ready" : "incompatible", reason: admission.reason });
    } catch {
      await rollbackSLMSetup().catch(() => undefined);
      setState({ status: "incompatible", reason: "Required on-device AI verification failed." });
    }
  }, []);
  useEffect(() => {
    void verify();
    const subscription = AppState.addEventListener("change", next => {
      if (next === "active") void verify();
    });
    return () => subscription.remove();
  }, [verify]);
  if (state.status === "ready") return <>{children}</>;
  return <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 16 }}>
    {state.status === "checking" ? <>
      <ActivityIndicator accessibilityLabel="Checking required on-device AI" />
      <Text>Checking device compatibility before ApolloSG starts…</Text>
    </> : <>
      <Text style={{ fontSize: 22, fontWeight: "700", textAlign: "center" }}>ApolloSG cannot start on this device</Text>
      <Text style={{ textAlign: "center" }}>{state.reason}</Text>
      <Text style={{ textAlign: "center" }}>No ApolloSG protection has been started. You can remove the app using your device settings.</Text>
      <Pressable accessibilityRole="button" onPress={() => { void verify(true); }}>
        <Text style={{ fontWeight: "700" }}>Install required AI and retry</Text>
      </Pressable>
      <Pressable accessibilityRole="button" onPress={() => { void verify(); }}>
        <Text style={{ fontWeight: "700" }}>Retry compatibility check</Text>
      </Pressable>
    </>}
  </View>;
}
