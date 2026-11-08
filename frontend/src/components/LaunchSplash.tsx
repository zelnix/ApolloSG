// Full-screen ApolloSG launch artwork. Android 12+ and iOS draw only a small centred icon in the native splash,
// so the owner's artwork is shown here, straight after the native splash, then fades away: the portrait
// artwork on phones, the landscape artwork on tablets (shortest side 600pt or more).
import { Image } from "expo-image";
import React, { useEffect, useState } from "react";
import { StyleSheet, Text, useWindowDimensions, View } from "react-native";
import Animated, { runOnJS, useAnimatedStyle, useSharedValue, withDelay, withTiming } from "react-native-reanimated";

import { useApollo } from "@/src/store/ApolloContext";

const PHONE_ARTWORK = require("@/assets/images/splash-full.webp");
const TABLET_ARTWORK = require("@/assets/images/splash-full-tablet.webp");
// The artwork's own white, so the edges around it are invisible in light and dark themes alike.
const ARTWORK_WHITE = "#FFFFFF";
// The artwork stays until ApolloSG has finished starting (its saved state is loaded), so the person never sees
// a half-built screen. It shows for at least MIN_MS (never a flash) and at most MAX_MS (a slow start never
// hides the app), then waits SETTLE_MS for the first screen to draw before fading.
const MIN_MS = 1000;
const MAX_MS = 8000;
const SETTLE_MS = 300;
const FADE_MS = 400;

export function LaunchSplash() {
  const { width, height } = useWindowDimensions();
  const isTablet = Math.min(width, height) >= 600;
  const { ready } = useApollo();
  const [visible, setVisible] = useState(true);
  const [minShown, setMinShown] = useState(false);
  const [timedOut, setTimedOut] = useState(false);
  const opacity = useSharedValue(1);

  useEffect(() => {
    const min = setTimeout(() => setMinShown(true), MIN_MS);
    const max = setTimeout(() => setTimedOut(true), MAX_MS);
    return () => { clearTimeout(min); clearTimeout(max); };
  }, []);

  const done = (ready && minShown) || timedOut;
  useEffect(() => {
    if (!done) return;
    opacity.value = withDelay(SETTLE_MS, withTiming(0, { duration: FADE_MS }, (finished) => { if (finished) runOnJS(setVisible)(false); }));
  }, [done, opacity]);

  const fade = useAnimatedStyle(() => ({ opacity: opacity.value }));
  if (!visible) return null;
  return (
    <Animated.View style={[StyleSheet.absoluteFill, s.root, fade]} pointerEvents="none" testID="launch-splash">
      <Image
        source={isTablet ? TABLET_ARTWORK : PHONE_ARTWORK}
        style={s.art}
        contentFit="contain"
        testID={isTablet ? "launch-splash-tablet" : "launch-splash-phone"}
        accessibilityLabel="ApolloSG Scam Guard. Better Protection. Safer You. Safer Tomorrows."
      />
      <View style={[s.loadingMessage, isTablet && s.loadingMessageTablet]} accessibilityLiveRegion="polite">
        <Text style={s.loadingText} testID="launch-splash-loading-message">Preparing ApolloSG…</Text>
      </View>
    </Animated.View>
  );
}

const s = StyleSheet.create({
  root: { backgroundColor: ARTWORK_WHITE, zIndex: 1000, elevation: 1000 },
  art: { flex: 1, width: "100%" },
  loadingMessage: {
    position: "absolute", bottom: 72, left: 24, right: 24,
    alignItems: "center", justifyContent: "center",
  },
  loadingMessageTablet: { bottom: 96 },
  loadingText: {
    color: "#183153", fontSize: 16, fontWeight: "600",
    textAlign: "center", letterSpacing: 0.2,
  },
});
