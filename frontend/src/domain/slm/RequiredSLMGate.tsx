/** Global fail-closed admission boundary for all ApolloSG routes.
 * This must mount outside ApolloProvider and the navigation stack.
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { Text, View, Pressable, ScrollView, useWindowDimensions } from "react-native";
import { Image } from "expo-image";
import { PreparingApolloSplash } from "@/src/components/LaunchSplash";
import { startupStage } from "@/src/startup/startupStages";
import { checkRequiredSLMCompatibility, downloadPrivateLuddishForTest, rollbackSLMSetup } from "./bootstrap";
import { createCompatibilityAttempt, SLMCompatibilityTimeout } from "./compatibilityAttempt.ts";
import { getOnDeviceAIDownloadState, subscribeOnDeviceAIDownload } from "./downloadStatus.ts";

type State = { status: "checking" | "ready" | "incompatible"; reason: string; stage?: string; diagnosticCode?: string };

export function RequiredSLMGate({ children }: { children: ReactNode }) {
  const { width, height } = useWindowDimensions();
  const isTablet = Math.min(width, height) >= 600;
  const [state, setState] = useState<State>({ status: "checking", reason: "" });
  const downloadState = useSyncExternalStore(subscribeOnDeviceAIDownload, getOnDeviceAIDownloadState, getOnDeviceAIDownloadState);
  const generation = useRef(0);
  const inFlight = useRef(false);
  const verify = useCallback(async (install = false) => {
    // Never overlap non-cancellable native model verification attempts.
    if (inFlight.current) return;
    inFlight.current = true;
    const attempt = ++generation.current;
    startupStage("on_device_ai", "started");
    setState({ status: "checking", reason: "", stage: install ? "installing" : "hardware" });
    let settled = false;
    let timedOut = false;
    let outstanding: Promise<unknown> | undefined;
    try {
      const { work, result } = createCompatibilityAttempt({
        install: install ? downloadPrivateLuddishForTest : undefined,
        installFailure: () => ({ compatible: false, reason: getOnDeviceAIDownloadState().error ?? "Higgins installation was not completed." }),
        check: () => checkRequiredSLMCompatibility(stage => {
          if (!settled && attempt === generation.current) setState({ status: "checking", reason: "", stage });
        }),
      });
      outstanding = work;
      const admission = await result;
      settled = true;
      if (attempt !== generation.current) return;
      startupStage("on_device_ai", admission.compatible ? "completed" : "failed", admission.compatible ? undefined : "admission_rejected");
      if (!admission.compatible) {
        setState({ status: "incompatible", reason: admission.reason, diagnosticCode: admission.diagnosticCode });
        await rollbackSLMSetup().catch(() => undefined);
      } else setState({ status: "ready", reason: "" });
    } catch (error) {
      if (attempt !== generation.current) return;
      settled = true;
      timedOut = error instanceof SLMCompatibilityTimeout;
      startupStage("on_device_ai", timedOut ? "timed_out" : "failed");
      setState({ status: "incompatible", reason: timedOut
        ? "Device compatibility could not be verified within the startup time limit. ApolloSG has not started protection."
        : "Higgins verification failed." });
      // Timeout does not cancel native loading. Preserve the installed model.
      if (!timedOut) await rollbackSLMSetup().catch(() => undefined);
    } finally {
      settled = true;
      // Normal retries wait for cleanup; timed-out native work still owns its lock.
      if (outstanding) void outstanding.finally(() => { inFlight.current = false; }).catch(() => undefined);
      else inFlight.current = false;
    }
  }, []);
  useEffect(() => {
    void verify();
    return () => { generation.current++; };
  }, [verify]);
  if (state.status === "ready") return <>{children}</>;
  if (state.status === "checking") {
    if (state.stage === "installing") {
      const mb = (bytes: number) => (bytes / (1024 * 1024)).toFixed(1);
      const progress = downloadState.totalBytes > 0
        ? `${mb(downloadState.receivedBytes)} / ${mb(downloadState.totalBytes)} MB`
        : `${mb(downloadState.receivedBytes)} MB`;
      const message = downloadState.phase === "downloading" ? `Downloading Higgins… ${progress}`
        : downloadState.phase === "verifying" ? "Verifying downloaded Higgins model…"
        : downloadState.phase === "registering" ? "Preparing Higgins runtime…" : "Preparing Higgins installation…";
      return <PreparingApolloSplash message={message} />;
    }
    const descriptions: Record<string, string> = {
      hardware: "Checking device hardware", model_integrity: "Verifying Higgins model",
      runtime_registration: "Preparing Higgins runtime", inference: "Loading Higgins model",
    };
    return <PreparingApolloSplash message={"Preparing ApolloSG… " + (descriptions[state.stage ?? ""] ?? "Checking device compatibility")} />;
  }
  return <ScrollView contentContainerStyle={{ flexGrow: 1, backgroundColor: "#FFFFFF", alignItems: "center", justifyContent: "center", paddingHorizontal: 24, paddingVertical: 32 }} testID="slm-admission-error">
    <Image source={isTablet ? require("@/assets/images/splash-full-tablet.webp") : require("@/assets/images/splash-full.webp")}
      style={{ width: "100%", height: Math.min(height * 0.49, isTablet ? 420 : 350) }}
      contentFit="contain" accessibilityLabel="ApolloSG Scam Guard" />
    <View style={{ width: "100%", maxWidth: 460, alignItems: "center", gap: 14, paddingTop: 12 }}>
      <Text style={{ fontSize: 21, fontWeight: "700", color: "#183153", textAlign: "center" }}>ApolloSG needs your attention</Text>
      <Text style={{ fontSize: 15, color: "#183153", textAlign: "center" }}>{state.reason}</Text>
      {state.diagnosticCode ? <Text selectable style={{ fontSize: 12, color: "#42546A", textAlign: "center" }}>Diagnostic: {state.diagnosticCode}</Text> : null}
      <Text style={{ fontSize: 14, color: "#42546A", textAlign: "center" }}>Protection has not started. You can retry the check or install the required Higgins model.</Text>
      <Pressable accessibilityRole="button" style={{ backgroundColor: "#183153", borderRadius: 10, paddingVertical: 14, paddingHorizontal: 22, width: "100%", alignItems: "center" }}
        onPress={() => { void verify(); }}>
        <Text style={{ color: "#FFFFFF", fontWeight: "700" }}>Retry compatibility check</Text>
      </Pressable>
      <Pressable accessibilityRole="button" style={{ borderWidth: 1, borderColor: "#183153", borderRadius: 10, paddingVertical: 14, paddingHorizontal: 18, width: "100%", alignItems: "center" }}
        onPress={() => { void verify(true); }}>
        <Text style={{ color: "#183153", fontWeight: "700", textAlign: "center" }}>Install Higgins and retry</Text>
      </Pressable>
    </View>
  </ScrollView>;
}
