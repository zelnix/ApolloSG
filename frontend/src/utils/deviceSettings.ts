// Gate 7 — jump the user to the relevant OS settings page. Android exposes specific settings intents;
// iOS only lets an app open its own settings page, so we open Settings and show the path to follow.
import { Linking, Platform } from "react-native";
import type { AppPermission } from "@/src/domain/appAnalysis";

export type SettingsTarget = "apps" | "accessibility" | "vpn" | "security" | "unknown_sources" | "overlay" | "notification_access" | "all_files" | "developer" | "private_dns";

const ANDROID_INTENT: Record<SettingsTarget, string> = {
  apps: "android.settings.MANAGE_APPLICATIONS_SETTINGS",
  accessibility: "android.settings.ACCESSIBILITY_SETTINGS",
  vpn: "android.settings.VPN_SETTINGS",
  security: "android.settings.SECURITY_SETTINGS",
  unknown_sources: "android.settings.MANAGE_UNKNOWN_APP_SOURCES",
  overlay: "android.settings.action.MANAGE_OVERLAY_PERMISSION",
  notification_access: "android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS",
  all_files: "android.settings.MANAGE_ALL_FILES_ACCESS_PERMISSION",
  developer: "android.settings.APPLICATION_DEVELOPMENT_SETTINGS",
  private_dns: "android.settings.PRIVATE_DNS_SETTINGS",
};

/**
 * Android has no public intent for the Private DNS screen on every phone, so this tries several
 * intents from most-specific to least-specific, including Samsung-specific fallbacks.
 * Returns which one opened, so the caller can show the remaining path.
 */
export async function openPrivateDnsSettings(): Promise<"private_dns" | "network" | "settings" | "failed"> {
  if (Platform.OS !== "android") return "failed";
  // 1. Direct Private DNS intent (Android 14+ / API 34+)
  try { await Linking.sendIntent(ANDROID_INTENT.private_dns); return "private_dns"; } catch { /* not on this device */ }
  // 2. "More connection settings" on Samsung (contains Private DNS, VPN, Ethernet)
  try { await Linking.sendIntent("android.settings.APN_SETTINGS"); return "network"; } catch { /* not on this device */ }
  // 3. General network & internet / connections screen
  try { await Linking.sendIntent("android.settings.WIRELESS_SETTINGS"); return "network"; } catch { /* not on this device */ }
  try { await Linking.openSettings(); return "settings"; } catch { return "failed"; }
}

export async function openDeviceSettings(target: SettingsTarget, path: string, toast: (m: string) => void) {
  try {
    if (Platform.OS === "android" && target === "private_dns") {
      if ((await openPrivateDnsSettings()) !== "private_dns") toast(`Then go to: ${path}`);
      return;
    }
    if (Platform.OS === "android") { await Linking.sendIntent(ANDROID_INTENT[target]); return; }
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
    case "device_admin": return { target: "security", label: "Device admin", path: `Settings → Security → Device admin apps → ${app} → deactivate` };
    case "install_apps": return { target: "unknown_sources", label: "Install unknown apps", path: `Settings → Apps → Special access → Install unknown apps → ${app} → turn off` };
    case "files": return { target: "all_files", label: "All-files access", path: `Settings → Apps → Special access → All files access → ${app}` };
    default: return { target: "apps", label: "App permissions", path: `Settings → Apps → ${app} → Permissions` };
  }
}

