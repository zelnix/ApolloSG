/**
 * Optional SLM must never hold the native splash or core Apollo startup.
 * Mounts inside the existing ApolloProvider, then waits for ready state before
 * dynamically loading native/model code. Web and release builds stay inert.
 */
import { useEffect, useRef } from "react";
import { Alert, Platform } from "react-native";
import { useRouter } from "expo-router";
import { useApollo } from "@/src/store/ApolloContext";

export function SharedLuddishStartup(): null {
  const { ready } = useApollo();
  const router = useRouter();
  const prompted = useRef(false);
  useEffect(() => {
    if (!ready || (!__DEV__ && process.env.EXPO_PUBLIC_SLM_TEST_MODE !== "true") ||
        (Platform.OS !== "android" && Platform.OS !== "ios")) return;
    let cancelled = false;
    // Defer native module resolution and full-file SHA verification until after
    // Apollo has had a chance to render and dismiss its existing splash.
    const handle = setTimeout(() => {
      if (cancelled) return;
      void import("./bootstrap").then(async (module) => {
        if (cancelled) return;
        const started = await module.startSharedLuddish();
        if (started || cancelled || prompted.current) return;
        if (!(await module.isPrivateLuddishModelMissing()) || cancelled) return;
        prompted.current = true;
        Alert.alert("On-device AI model needed",
          "The Qwen model is not installed (about 491 MB). Download and verify it now using your internet connection? ApolloSG works without it.",
          [{ text: "Later", style: "cancel" },
           { text: "Open Settings", onPress: () => router.push("/settings") },
           { text: "Download & Install", onPress: () => { void module.downloadPrivateLuddishForTest().then((ok) => Alert.alert("On-device AI", ok ? "Model downloaded and verified. Local inference still needs testing." : "Download or verification failed. Check internet access, available storage and device compatibility.")); } }]);
      }).catch(() => undefined);
    }, 1500);
    return () => { cancelled = true; clearTimeout(handle); };
  }, [ready, router]);
  return null;
}
