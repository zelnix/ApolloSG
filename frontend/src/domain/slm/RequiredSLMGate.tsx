/** Global fail-closed admission boundary for all ApolloSG routes.
 * This must mount outside ApolloProvider and the navigation stack.
 */
import { useEffect, useState, type ReactNode } from "react";
import { ActivityIndicator, Text, View, Pressable } from "react-native";
import { checkRequiredSLMCompatibility, rollbackSLMSetup } from "./bootstrap";

type State = { status: "checking" | "ready" | "incompatible"; reason: string };

export function RequiredSLMGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: "checking", reason: "" });
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const admission = await checkRequiredSLMCompatibility();
        if (!admission.compatible) {
          await rollbackSLMSetup();
          if (active) setState({ status: "incompatible", reason: admission.reason });
        } else if (active) setState({ status: "ready", reason: "" });
      } catch {
        await rollbackSLMSetup().catch(() => undefined);
        if (active) setState({ status: "incompatible", reason: "Required on-device AI verification failed." });
      }
    })();
    return () => { active = false; };
  }, []);
  if (state.status === "ready") return <>{children}</>;
  return <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 16 }}>
    {state.status === "checking" ? <>
      <ActivityIndicator accessibilityLabel="Checking required on-device AI" />
      <Text>Checking device compatibility before ApolloSG starts…</Text>
    </> : <>
      <Text style={{ fontSize: 22, fontWeight: "700", textAlign: "center" }}>ApolloSG cannot start on this device</Text>
      <Text style={{ textAlign: "center" }}>{state.reason}</Text>
      <Text style={{ textAlign: "center" }}>No ApolloSG protection has been started. You can remove the app using your device settings.</Text>
      <Pressable accessibilityRole="button" onPress={() => {
        setState({ status: "checking", reason: "" });
        void checkRequiredSLMCompatibility().then(async (admission) => {
          if (!admission.compatible) await rollbackSLMSetup();
          setState({ status: admission.compatible ? "ready" : "incompatible", reason: admission.reason });
        }).catch(() => setState({ status: "incompatible", reason: "Compatibility check failed." }));
      }}><Text style={{ fontWeight: "700" }}>Retry compatibility check</Text></Pressable>
    </>}
  </View>;
}
