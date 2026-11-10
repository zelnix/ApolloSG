/**
 * Optional SLM must never hold the native splash or core Apollo startup.
 * Mounts inside the existing ApolloProvider, then waits for ready state before
 * dynamically loading native/model code. Web and release builds stay inert.
 */
import { useEffect } from "react";
import { Platform } from "react-native";
import { useApollo } from "@/src/store/ApolloContext";

export function SharedLuddishStartup(): null {
  const { ready } = useApollo();
  useEffect(() => {
    if (!ready || (!__DEV__ && process.env.EXPO_PUBLIC_SLM_TEST_MODE !== "true") ||
        (Platform.OS !== "android" && Platform.OS !== "ios")) return;
    let cancelled = false;
    // Defer native module resolution and full-file SHA verification until after
    // Apollo has had a chance to render and dismiss its existing splash.
    const handle = setTimeout(() => {
      if (cancelled) return;
      void import("./bootstrap").then(async (module) => {
        if (!cancelled) await module.startSharedLuddish();
      }).catch(() => undefined);
    }, 1500);
    return () => { cancelled = true; clearTimeout(handle); };
  }, [ready]);
  return null;
}
