// app.config.js — single authoritative Expo configuration.
// There is no app.json; this file is the sole config source.
// Expo loads it automatically (https://docs.expo.dev/workflow/configuration/).

const ANDROID_PACKAGE = "app.apollo.hwg";
const IOS_BUNDLE_IDENTIFIER = "app.apollo.hwg";

// ── Expo project identity ──────────────────────────────────────────────────
// Canonical values for the owner's Expo project.
//
// Emergent (or any other build route that targets a *different* Expo project)
// can override all three atomically via environment variables:
//   EAS_PROJECT_OWNER   – Expo account that owns the build project
//   EAS_PROJECT_SLUG    – project slug registered under that account
//   EAS_PROJECT_ID      – the project's UUID (extra.eas.projectId)
const CANONICAL_OWNER      = "zelnixs-team";
const CANONICAL_SLUG       = "apollo-cyber-guard-dog";
const CANONICAL_PROJECT_ID = "b2eb337d-2687-46bf-b1cc-292d30c0b601";

const EAS_OWNER      = process.env.EAS_PROJECT_OWNER || CANONICAL_OWNER;
const EAS_SLUG       = process.env.EAS_PROJECT_SLUG  || CANONICAL_SLUG;
const EAS_PROJECT_ID = process.env.EAS_PROJECT_ID    || CANONICAL_PROJECT_ID;

// Google Play restricted SMS / Call Log permissions — OFF unless explicitly approved (see the plugin header).
const { resolveRestrictedPhonePermissions } = require("./plugins/withRestrictedPhonePermissions");
const restrictedPhonePermissions = resolveRestrictedPhonePermissions();

// Evaluate dynamic values at require-time (all env vars are available).
const appEnvironment = process.env.EXPO_PUBLIC_APP_ENV || "development";
const engine = process.env.EXPO_PUBLIC_ANDROID_ENFORCEMENT_ENGINE || (appEnvironment === "production" ? "guarddog_production" : "legacy");

// Direct object export with standard { expo: { ... } } wrapper — compatible with
// both Expo's config loader and the Emergent build pipeline which serializes this
// to app.json and expects json.expo.extra to exist during its cleanup step.
module.exports = {
  expo: {
  // ── core identity ────────────────────────────────────────────────────
  name: "ApolloSG",
    owner: EAS_OWNER,
    slug: EAS_SLUG,
    version: "1.1.0",
    orientation: "default",
    icon: "./assets/images/icon.png",
    scheme: "apollo",
    userInterfaceStyle: "light",
    backgroundColor: "#F5F7FA",

    // ── iOS ──────────────────────────────────────────────────────────────
    ios: {
      buildNumber: "2",
      supportsTablet: true,
      bundleIdentifier: IOS_BUNDLE_IDENTIFIER,
      infoPlist: {
        // Export compliance: iOS uses only system-provided encryption (Keychain via
        // SecureStore, HTTPS/TLS, CryptoKit SHA-256 hashing, WebRTC DTLS/SRTP).
        // No custom or proprietary encryption algorithms. Android's AES/GCM-NoPadding
        // (Keystore-backed) in ApolloSmsListenerService is Android-only and does not
        // affect the iOS encryption classification. All usage qualifies as exempt under
        // Apple's export compliance categories.
        ITSAppUsesNonExemptEncryption: false,
        NSLocationWhenInUseUsageDescription: "Check whether your Wi-Fi connection is secured",
      },
      entitlements: {
        "com.apple.developer.networking.wifi-info": true,
      },
      privacyManifests: {
        NSPrivacyAccessedAPITypes: [
          { NSPrivacyAccessedAPIType: "NSPrivacyAccessedAPICategoryUserDefaults", NSPrivacyAccessedAPITypeReasons: ["CA92.1"] },
          { NSPrivacyAccessedAPIType: "NSPrivacyAccessedAPICategoryFileTimestamp", NSPrivacyAccessedAPITypeReasons: ["C617.1"] },
        ],
        // What leaves the phone and is kept beyond the request (Apple's definition of "collected"): all linked to
        // the random device ID, used only to run the app, never for tracking or advertising. Content sent for a
        // check is processed for that request only (copies closed within 15 minutes), so it is not listed.
        NSPrivacyCollectedDataTypes: [
          "NSPrivacyCollectedDataTypeDeviceID",
          "NSPrivacyCollectedDataTypeEmailAddress",
          "NSPrivacyCollectedDataTypePhoneNumber",
          "NSPrivacyCollectedDataTypeName",
          "NSPrivacyCollectedDataTypeOtherUserContent",
          "NSPrivacyCollectedDataTypeOtherDiagnosticData",
          // How many times each feature was used (counts only), for the admin Devices list.
          "NSPrivacyCollectedDataTypeProductInteraction",
        ].map((type) => ({
          NSPrivacyCollectedDataType: type,
          NSPrivacyCollectedDataTypeLinked: true,
          NSPrivacyCollectedDataTypeTracking: false,
          NSPrivacyCollectedDataTypePurposes: ["NSPrivacyCollectedDataTypePurposeAppFunctionality"],
        })),
        NSPrivacyTracking: false,
      },
    },

    // ── Android ──────────────────────────────────────────────────────────
    android: {
      adaptiveIcon: {
        foregroundImage: "./assets/images/adaptive-icon.png",
        backgroundColor: "#F5F7FA",
      },
      package: ANDROID_PACKAGE,
      googleServicesFile: "./google-services.json",
      softwareKeyboardLayoutMode: "pan",
      permissions: [
        "android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION",
        "android.permission.ACCESS_NETWORK_STATE",
        "android.permission.INTERNET",
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.CAMERA",
      ],
      // Google Play: never ship what Apollo doesn't use. Expo's template adds "Display over other apps";
      // Apollo only checks whether OTHER apps hold it, so it is stripped from every build.
      blockedPermissions: ["android.permission.SYSTEM_ALERT_WINDOW"],
    },

    // ── Web ──────────────────────────────────────────────────────────────
    web: {
      bundler: "metro",
      output: "single",
      themeColor: "#F5F7FA",
      backgroundColor: "#F5F7FA",
      favicon: "./assets/images/favicon.png",
    },

    // ── Plugins ──────────────────────────────────────────────────────────
    plugins: [
      "./plugins/withEasAppExtensionsDedupe",
      "./plugins/withNativeDependencyGuard",
      "./modules/apollo-family-assist/plugin/withApolloFamilyAssist",
      "expo-router",
      ["expo-notifications", { sounds: ["./assets/sounds/apollo_bark.wav", "./assets/sounds/apollo_chime.wav"] }],
      // Native splash on white, the same white as the full-screen launch artwork (src/components/LaunchSplash.tsx) that follows it on phones and tablets.
      ["expo-splash-screen", { image: "./assets/images/splash-logo.png", imageWidth: 288, resizeMode: "contain", backgroundColor: "#FFFFFF" }],
      "expo-font",
      "expo-asset",
      "expo-image",
      "expo-secure-store",
      "expo-web-browser",
      "expo-status-bar",
      "./plugins/withApolloShareIntake",
      ["expo-share-intent", {
        iosAppGroupIdentifier: "group.app.apollo.hwg.apollo",
        iosShareExtensionBundleIdentifier: "app.apollo.hwg.shareextension",
        iosShareExtensionName: "Apollo Share Extension",
        iosActivationRules: {
          NSExtensionActivationSupportsWebURLWithMaxCount: 1,
          NSExtensionActivationSupportsText: true,
          NSExtensionActivationSupportsImageWithMaxCount: 10,
          NSExtensionActivationSupportsFileWithMaxCount: 10,
        },
        androidIntentFilters: ["text/*", "image/*", "application/*"],
        androidMultiIntentFilters: ["*/*"],
      }],
      "./plugins/withApolloSiteGuard",
      "./plugins/withApolloCallGuard",
      "./plugins/withApolloTextGuard",
      "./plugins/withGuardDogEngine",
      "./plugins/withRestrictedPhonePermissions",
      "expo-sharing",
      ["expo-camera", { cameraPermission: "Scan QR codes and photograph suspicious items for checking", microphonePermission: false, recordAudioAndroid: false }],
      // Same camera wording as expo-camera: both plugins write NSCameraUsageDescription, so they must agree.
      ["expo-image-picker", { photosPermission: "Choose screenshots to verify settings or check for scams", cameraPermission: "Scan QR codes and photograph suspicious items for checking", microphonePermission: false }],
      // Alert sounds play only while Apollo is open: no background music-player service (a Play declaration Apollo can't justify).
      ["expo-audio", { microphonePermission: false, enableBackgroundPlayback: false }],
      ["expo-build-properties", { android: { minSdkVersion: 26 }, ios: { deploymentTarget: "16.4" } }],
      "expo-ocr-kit",
      // On-device fallback model runtime (llama.cpp). iOS memory entitlements stay off until the App ID has them;
      // the fallback models are sized to run without them.
      ["llama.rn", { enableEntitlements: false, enableOpenCL: false }],
    ],

    // ── Updates (EAS Update) ─────────────────────────────────────────────
    updates: {
      url: `https://u.expo.dev/${EAS_PROJECT_ID}`,
    },
    runtimeVersion: {
      policy: "appVersion",
    },

    // ── Experiments ──────────────────────────────────────────────────────
    experiments: {
      typedRoutes: true,
    },

    // ── Extra ────────────────────────────────────────────────────────────
    extra: {
      pirServer: { url: "" },
      // Which restricted pickers this build declares. Both false unless the approved build switch is set.
      restrictedPhonePermissions: { callLog: restrictedPhonePermissions.callLog, sms: restrictedPhonePermissions.sms },
      eas: {
        build: {
          experimental: {
            ios: {
              appExtensions: [
                { targetName: "ApolloFamilyAssistBroadcast", bundleIdentifier: "app.apollo.hwg.familyassistbroadcast", entitlements: { "com.apple.security.application-groups": ["group.app.apollo.hwg.apollo"] } },
                { targetName: "ApolloShareExtension", bundleIdentifier: "app.apollo.hwg.shareextension", entitlements: { "com.apple.security.application-groups": ["group.app.apollo.hwg.apollo"] } },
                { targetName: "ApolloContentBlocker", bundleIdentifier: "app.apollo.hwg.contentblocker", entitlements: { "com.apple.security.application-groups": ["group.app.apollo.hwg.apollo"] } },
                { targetName: "ApolloCallDirectory", bundleIdentifier: "app.apollo.hwg.calldirectory", entitlements: { "com.apple.security.application-groups": ["group.app.apollo.hwg.apollo"] } },
                { targetName: "ApolloMessageFilter", bundleIdentifier: "app.apollo.hwg.messagefilter", entitlements: { "com.apple.security.application-groups": ["group.app.apollo.hwg.apollo"] } },
                // Live caller ID (plugins/withLiveCallerID.js) is out of the build until Apple approves its
                // entitlement and a private lookup server exists. Re-add the plugin and this target together.
              ],
            },
          },
        },
        projectId: EAS_PROJECT_ID,
      },
      guardDogProduction: {
        ruleBundleUrl: process.env.EXPO_PUBLIC_GUARDDOG_RULE_BUNDLE_URL || null,
        controlledHost: process.env.EXPO_PUBLIC_GUARDDOG_CONTROLLED_HOST || null,
        controlledIpv4: process.env.EXPO_PUBLIC_GUARDDOG_CONTROLLED_IPV4 || null,
        controlledUrl: process.env.EXPO_PUBLIC_GUARDDOG_CONTROLLED_URL || null,
        rulesetId: process.env.EXPO_PUBLIC_GUARDDOG_RULESET_ID || "",
        dedupeWindowMs: Number(process.env.EXPO_PUBLIC_GUARDDOG_DEDUPE_WINDOW_MS || "2000"),
      },
    },
  },
};
