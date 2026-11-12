// Single native-state owner for Call Gate's incoming-call protection setup.
// Role/extension enablement is not proof of individual call enforcement.
import { useCallback, useEffect, useState } from "react";
import { AppState, Platform } from "react-native";
import { CallSdk } from "@/src/security/callSdk";

export type ScreenerState = "held" | "available" | "unsupported" | "ios" | "ios_enabled" | "ios_unavailable" | "unavailable" | "checking";
export interface CallScreener {
  state: ScreenerState;
  detail: string;
  summary: string;
  canRequest: boolean;
  requesting: boolean;
  refresh: () => Promise<void>;
  request: () => Promise<void>;
}
export const SCREENER_SUMMARY: Record<ScreenerState, string> = {
  held: "Enabled — role confirmed",
  available: "Setup required",
  unsupported: "Unavailable",
  ios: "Setup required",
  ios_enabled: "Enabled — extension confirmed",
  ios_unavailable: "Unable to verify",
  unavailable: "Unable to verify",
  checking: "Checking protection…",
};

export function useCallScreener(): CallScreener {
  const [state, setState] = useState<ScreenerState>("checking");
  const [detail, setDetail] = useState("Checking your device's incoming-call protection.");
  const [requesting, setRequesting] = useState(false);

  const refresh = useCallback(async () => {
    if (Platform.OS === "ios") {
      const result = await CallSdk.getCallDirectoryStatus();
      if (result.status !== "ok") {
        setState("ios_unavailable");
        setDetail(result.detail ?? "ApolloSG could not confirm the iPhone Call Directory state.");
      } else if (result.enabled) {
        setState("ios_enabled");
        setDetail("ApolloSG's Call Directory is enabled. Saved blocking and identification lists can be used when loaded. iOS does not confirm individual blocked calls.");
      } else if (result.extensionAvailable) {
        setState("ios");
        setDetail("Turn on ApolloSG in iPhone Settings → Apps → Phone → Call Blocking & Identification. The Settings path may vary by iOS version.");
      } else {
        setState("ios_unavailable");
        setDetail("ApolloSG's Call Directory extension is not available in this build.");
      }
      return;
    }
    if (Platform.OS !== "android") {
      setState("unavailable");
      setDetail("Native incoming-call protection cannot be verified in this preview.");
      return;
    }
    const result = await CallSdk.getCallScreeningRoleStatus();
    if (result.status !== "ok") {
      setState("unavailable");
      setDetail(result.detail ?? "ApolloSG could not read the Android call-screening role.");
    } else if (result.roleHeld) {
      setState("held");
      setDetail("Android confirms ApolloSG holds the call-screening role for eligible incoming calls. This does not confirm that any particular call was blocked.");
    } else if (result.roleAvailable) {
      setState("available");
      setDetail("Enable ApolloSG as the Caller ID & spam app in Android's default app settings.");
    } else {
      setState("unsupported");
      setDetail(result.detail ?? "This device does not support ApolloSG's call-screening role.");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const sub = AppState.addEventListener("change", next => {
      if (next === "active") void refresh();
    });
    return () => sub.remove();
  }, [refresh]);

  const request = useCallback(async () => {
    if (requesting || (Platform.OS !== "android" && Platform.OS !== "ios")) return;
    setRequesting(true);
    try {
      const result = await CallSdk.requestCallScreeningRole();
      if (!result.opened) {
        setDetail(Platform.OS === "ios"
          ? "Open iPhone Settings and enable ApolloSG under Call Blocking & Identification."
          : "Android did not open the call-screening role request. Check Default apps in Settings.");
      }
      // The native role request can complete after the app becomes active; always re-read.
      await refresh();
    } catch {
      setDetail("The protection setup could not be opened. Check your phone's settings and try again.");
    } finally {
      setRequesting(false);
    }
  }, [refresh, requesting]);

  return {
    state, detail, summary: SCREENER_SUMMARY[state],
    canRequest: state === "available" || state === "ios",
    requesting, refresh, request,
  };
}
