/**
 * Required SLM compatibility is checked at onboarding before activation.
 * Mounts inside the existing ApolloProvider, then waits for ready state before
 * dynamically loading native/model code. All pre-production native builds use the model.
 */
import { useEffect, useRef } from "react";
import { Alert, Platform } from "react-native";
import { useRouter } from "expo-router";
import { useApollo } from "@/src/store/ApolloContext";
import { getOnDeviceAIDownloadState } from "./downloadStatus";

export function SharedLuddishStartup(): null {
  const { ready } = useApollo();
  const router = useRouter();
  const prompted = useRef(false);
  useEffect(() => {
    if (!ready || (Platform.OS !== "android" && Platform.OS !== "ios")) return;
    let cancelled = false;
    // Defer native module resolution and full-file SHA verification until after
    // Apollo has had a chance to render and dismiss its existing splash.
    const handle = setTimeout(() => {
      if (cancelled) return;
      void import("./bootstrap").then(async (module) => {
        if (cancelled) return;
        const started = await module.startSharedLuddish();
        if (started || cancelled || prompted.current || ["downloading", "verifying", "registering"].includes(getOnDeviceAIDownloadState().phase)) return;
        if (cancelled) return;
        prompted.current = true;
        Alert.alert("ApolloSG requires on-device AI",
          "ApolloSG cannot activate on this device until the local AI model is installed and verified. If the device cannot run it, setup cannot continue.",
          [{ text: "Exit setup", style: "cancel", onPress: () => router.replace("/onboarding") },
           { text: "Install required AI", onPress: () => { router.push("/settings"); void module.downloadPrivateLuddishForTest(); } }]);
      }).catch(() => undefined);
    }, 1500);
    return () => { cancelled = true; clearTimeout(handle); };
  }, [ready, router]);
  return null;
}
