import { QueryClientProvider } from "@tanstack/react-query";
import { useFonts } from "expo-font";
import * as Linking from "expo-linking";
import { Stack, useRouter } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { LogBox, Platform, View } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { KeyboardProvider } from "react-native-keyboard-controller";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { ErrorBoundary } from "@/src/components/error-boundary";
import { LaunchSplash } from "@/src/components/LaunchSplash";
import { SafeStartScreen } from "@/src/components/SafeStartScreen";
import { ToastHost } from "@/src/components/Toast";
import { apiPostEmpty } from "@/src/api/client";
import { markAlertOpened } from "@/src/push/alertLog";
import { ensureNotificationChannels, loadNotifications } from "@/src/push/notifications";
import { queryClient } from "@/src/query-client";
import { getSecurityBootError } from "@/src/security/securityBoot";
import { ShareIntakeListener } from "@/src/share/ShareIntakeListener";
import { MODAL_ROUTES } from "@/src/navigation/modalRoutes";
import { ApolloProvider } from "@/src/store/ApolloContext";
import { loadPersonalData } from "@/src/store/personalDataStore";
import { startDeviceProtectionMonitor } from "@/src/store/deviceProtectionStore";
import { useTheme } from "@/src/theme";
import { installTwelveHourClock } from "@/src/utils/twelveHourClock";

// Every time Apollo shows is on the 12-hour clock, in this device's own time zone.
installTwelveHourClock();

// Production: suppress LogBox entirely. Development: keep it active for diagnosis.
if (!__DEV__) LogBox.ignoreAllLogs(true);
void SplashScreen.preventAutoHideAsync().catch(() => {});

// Security boot boundary: if any security selector failed validation during module evaluation, the app
// must not mount. Evaluated once — configuration is baked into the build.
const SECURITY_BOOT_ERROR = getSecurityBootError();

// Local alert handler and channels are set up before a device observation can schedule an alert.
// Expo Go and web do not provide the native notification integration required here.
const Notifications = loadNotifications();
if (Notifications) {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({ shouldShowAlert: true, shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }),
  });
  if (Platform.OS === "android") void ensureNotificationChannels().catch(() => undefined);
}

// A tap is the one honest proof an alert arrived. Local alerts carry their log id; alerts sent from
// Apollo's servers carry their alert key in the deep link, which is reported back so the delivery
// ledger can say "opened on this device" instead of only "accepted for delivery".
function recordOpened(data: Record<string, unknown> | undefined, url: string | undefined) {
  const localId = typeof data?.alert_id === "string" ? data.alert_id : null;
  if (localId) void markAlertOpened(localId).catch(() => undefined);
  const key = url?.match(/[?&]a=([^&]+)/)?.[1];
  if (key) void apiPostEmpty(`/push/alerts/${encodeURIComponent(decodeURIComponent(key))}/opened`, `opened-${key}`).catch(() => undefined);
}

/** A notification is usually about a case the server just filed: fetch the cases now so it is on screen. */
function fetchCasesNow() {
  void queryClient.invalidateQueries({ queryKey: ["patrol"] });
  void queryClient.invalidateQueries({ queryKey: ["patrol-removed"] });
}

function openFromNotification(router: ReturnType<typeof useRouter>, data: Record<string, unknown> | undefined) {
  fetchCasesNow();
  const url = (data?.deeplink ?? data?.action_url) as string | undefined;
  recordOpened(data, url);
  if (!url) return;
  if (url.startsWith("http")) void Linking.openURL(url);
  else router.push(url as never);
}

export default function RootLayout() {
  const { colors } = useTheme();
  const router = useRouter();
  const [loaded] = useFonts({
    "Outfit-500": require("../assets/fonts/Outfit-500.ttf"),
    "Outfit-600": require("../assets/fonts/Outfit-600.ttf"),
    "Outfit-700": require("../assets/fonts/Outfit-700.ttf"),
    "Geist-400": require("../assets/fonts/Geist-400.ttf"),
    "Geist-500": require("../assets/fonts/Geist-500.ttf"),
    "Geist-600": require("../assets/fonts/Geist-600.ttf"),
  });
  useEffect(() => { if (loaded) void SplashScreen.hideAsync().catch(() => {}); }, [loaded]);
  // Pre-load the user's personal data into memory so the redaction engine can use it synchronously.
  useEffect(() => { void loadPersonalData().catch(() => undefined); }, []);
  // Device Protections: read and compare this device's settings on open and on return to Apollo.
  useEffect(() => { if (!SECURITY_BOOT_ERROR) startDeviceProtectionMonitor(); }, []);

  useEffect(() => {
    if (!Notifications || SECURITY_BOOT_ERROR) return;
    // Warm tap (app open / backgrounded)
    const tapSub = Notifications.addNotificationResponseReceivedListener((response) => {
      openFromNotification(router, response.notification.request.content.data as Record<string, unknown>);
    });
    // Arrived while Apollo is open
    const receivedSub = Notifications.addNotificationReceivedListener(() => fetchCasesNow());
    // Cold start tap (app was killed)
    void Notifications.getLastNotificationResponseAsync().then((response) => {
      if (response) openFromNotification(router, response.notification.request.content.data as Record<string, unknown>);
    });
    return () => { tapSub.remove(); receivedSub.remove(); };
  }, [router]);

  if (!loaded) return <View style={{ flex: 1, backgroundColor: colors.surface }} />;
  // Fail closed, visibly: no providers, no navigation, no protection start-up behind this screen.
  if (SECURITY_BOOT_ERROR) return <SafeStartScreen error={SECURITY_BOOT_ERROR} />;

  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <GestureHandlerRootView style={{ flex: 1, backgroundColor: colors.surface }}>
          <SafeAreaProvider>
            <KeyboardProvider>
              <ApolloProvider>
                <StatusBar style="dark" />
                {/* Tablet/desktop: readable column width on wide windows (phones unaffected). Navigation stays identical across form factors. */}
                <View style={{ flex: 1, width: "100%", maxWidth: 1180, alignSelf: "center" }}>
                <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.surface } }}>
                  <Stack.Screen name="index" />
                  <Stack.Screen name="onboarding" />
                  <Stack.Screen name="setup-gates" />
                  <Stack.Screen name="first-check" />
                  <Stack.Screen name="(tabs)" />
                  <Stack.Screen name="higgins/history" />
                  <Stack.Screen name="higgins/learning" />
                  <Stack.Screen name="higgins/learning/[slug]" />
                  <Stack.Screen name="higgins/scams" />
                  <Stack.Screen name="higgins/scam/[id]" />
                  <Stack.Screen name="gates" />
                  {MODAL_ROUTES.map((name) => <Stack.Screen key={name} name={name} options={{ presentation: "modal" }} />)}
                </Stack>
                </View>
                <ShareIntakeListener />
                <ToastHost />
                <LaunchSplash />
              </ApolloProvider>
            </KeyboardProvider>
          </SafeAreaProvider>
        </GestureHandlerRootView>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
