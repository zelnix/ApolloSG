// Gate 7 — jump the user to the relevant OS settings page. Android exposes specific settings intents;
// iOS only lets an app open its own settings page, so we open Settings and show the path to follow.
import { Linking, Platform } from "react-native";
import type { AppPermission } from "@/src/domain/appAnalysis";

export type SettingsTarget = "apps" | "accessibility" | "vpn" | "security" | "unknown_sources" | "overlay" | "notification_access" | "all_files" | "developer" | "private_dns" | "device_admin";

/** Primary intent for each target. */
const ANDROID_INTENT: Record<SettingsTarget, string> = {
  apps: "android.settings.MANAGE_APPLICATIONS_SETTINGS",
  accessibility: "android.settings.ACCESSIBILITY_SETTINGS",
  vpn: "android.settings.VPN_SETTINGS",
  security: "android.settings.SECURITY_SETTINGS",
  device_admin: "android.app.action.MANAGE_DEVICE_ADMINS",
  unknown_sources: "android.settings.MANAGE_UNKNOWN_APP_SOURCES",
  overlay: "android.settings.action.MANAGE_OVERLAY_PERMISSION",
  notification_access: "android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS",
  all_files: "android.settings.MANAGE_ALL_FILES_ACCESS_PERMISSION",
  developer: "android.settings.APPLICATION_DEVELOPMENT_SETTINGS",
  private_dns: "android.settings.PRIVATE_DNS_SETTINGS",
};

/**
 * Fallback chains for targets where the primary intent may not exist on every device.
 * Each entry is [intent, remainingPath | null]. null means "we reached the exact page".
 */
const FALLBACK_CHAINS: Partial<Record<SettingsTarget, Array<[string, string | null]>>> = {
  device_admin: [
    ["android.app.action.MANAGE_DEVICE_ADMINS", null],
    ["android.settings.SECURITY_SETTINGS", "More security settings \u2192 Device admin apps"],
  ],
  private_dns: [
    ["android.settings.PRIVATE_DNS_SETTINGS", null],
    ["android.settings.APN_SETTINGS", "Private DNS"],
    ["android.settings.WIRELESS_SETTINGS", "More connection settings \u2192 Private DNS"],
  ],
  vpn: [
    ["android.settings.VPN_SETTINGS", null],
    ["android.settings.WIRELESS_SETTINGS", "More connection settings \u2192 VPN"],
  ],
  all_files: [
    ["android.settings.MANAGE_ALL_FILES_ACCESS_PERMISSION", null],
    ["android.settings.MANAGE_APPLICATIONS_SETTINGS", "Special access \u2192 All files access"],
  ],
  unknown_sources: [
    ["android.settings.MANAGE_UNKNOWN_APP_SOURCES", null],
    ["android.settings.MANAGE_APPLICATIONS_SETTINGS", "Special access \u2192 Install unknown apps"],
  ],
  overlay: [
    ["android.settings.action.MANAGE_OVERLAY_PERMISSION", null],
    ["android.settings.MANAGE_APPLICATIONS_SETTINGS", "Special access \u2192 Display over other apps"],
  ],
  notification_access: [
    ["android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS", null],
    ["android.settings.MANAGE_APPLICATIONS_SETTINGS", "Special access \u2192 Notification access"],
  ],
};

/**
 * Try a chain of intents from most-specific to least. Returns null if the exact page opened,
 * or a string describing the remaining navigation the user must do.
 */
async function tryIntentChain(chain: Array<[string, string | null]>): Promise<string | null> {
  for (const [intent, remaining] of chain) {
    try { await Linking.sendIntent(intent); return remaining; } catch { /* intent not available */ }
  }
  return "the setting you need";
}

/**
 * Android has no public intent for the Private DNS screen on every phone, so this tries several
 * intents from most-specific to least-specific, including Samsung-specific fallbacks.
 * Returns which one opened, so the caller can show the remaining path.
 */
export async function openPrivateDnsSettings(): Promise<"private_dns" | "network" | "settings" | "failed"> {
  if (Platform.OS !== "android") return "failed";
  const remaining = await tryIntentChain(FALLBACK_CHAINS.private_dns!);
  if (remaining === null) return "private_dns";
  if (remaining !== "the setting you need") return "network";
  try { await Linking.openSettings(); return "settings"; } catch { return "failed"; }
}

export async function openDeviceSettings(target: SettingsTarget, path: string, toast: (m: string) => void) {
  try {
    if (Platform.OS === "android" && target === "private_dns") {
      if ((await openPrivateDnsSettings()) !== "private_dns") toast(`Then go to: ${path}`);
      return;
    }
    if (Platform.OS === "android") {
      const chain = FALLBACK_CHAINS[target];
      if (chain) {
        const remaining = await tryIntentChain(chain);
        if (remaining !== null && remaining !== "the setting you need") {
          toast(`Then go to: ${remaining}`);
        } else if (remaining === "the setting you need") {
          toast(`Open Settings on your device: ${path}`);
        }
        return;
      }
      // No fallback chain — try the single intent directly
      await Linking.sendIntent(ANDROID_INTENT[target]);
      return;
    }
    if (Platform.OS === "ios") { toast(`In Settings go to: ${path}`); await Linking.openSettings(); return; }
    // Desktop (Windows/macOS): no supported deep link — show the path to follow.
    toast(`On your device: ${path}`);
  } catch { toast(`Open Settings on your device: ${path}`); }
}

/** The closest supported Android settings destination for reviewing one permission on one app, plus the
 *  remaining navigation step (RN can open the broader/special-access screen, not an app-specific toggle,
 *  so we always tell the user what to tap next). `appName` is woven into the guidance. */
export function permissionSettings(id: AppPermission, appName: string): { target: SettingsTarget; label: string; path: string } {
  const app = appName.trim() || "this app";
  switch (id) {
    case "overlay": return { target: "overlay", label: "Display over other apps", path: `Settings → Apps → Special access → Display over other apps → ${app}` };
    case "notifications": return { target: "notification_access", label: "Notification access", path: `Settings → Apps → Special access → Notification access → ${app}` };
    case "accessibility": return { target: "accessibility", label: "Accessibility", path: `Settings → Accessibility → ${app} → turn off` };
    case "vpn": return { target: "vpn", label: "VPN", path: `Settings → Network → VPN → ${app} → remove` };
    case "device_admin": return { target: "device_admin", label: "Device admin apps", path: `Settings → Security → More security settings → Device admin apps → ${app} → deactivate` };
    case "install_apps": return { target: "unknown_sources", label: "Install unknown apps", path: `Settings → Apps → Special access → Install unknown apps → ${app} → turn off` };
    case "files": return { target: "all_files", label: "All-files access", path: `Settings → Apps → Special access → All files access → ${app}` };
    default: return { target: "apps", label: "App permissions", path: `Settings → Apps → ${app} → Permissions` };
  }
}

