// Shared copy + config for Gates that need an explicit user permission or account connection.
// Used by the setup walkthrough (app/setup-gates.tsx) so every place that asks for the same
// access uses identical plain-English wording and the same ~3-day "Not now" snooze.
// This does NOT change any Gate's underlying architecture or enforcement.
import { Platform } from "react-native";

export type GatePermId = "site" | "text" | "call" | "email";

export interface GatePermCopy {
  id: GatePermId;
  title: string;      // "Website protection"
  short: string;      // one-line purpose
  why: string;        // why the access is needed (plain English, benefit-led)
  enableLabel: string; // "Enable website protection"
  pendingLabel: string; // truthful state when not yet granted: "Permission required" / "Not connected"
  route?: string;     // Gate screen to open for the "enable later" path (site enables inline)
}

export const GATE_PERMISSIONS: Record<GatePermId, GatePermCopy> = {
  site: {
    id: "site", title: "Website protection",
    short: "Blocks known dangerous websites before they load.",
    why: "Android needs your permission to run a private on-device VPN filter. Apollo inspects web traffic locally and never sends your browsing anywhere.",
    enableLabel: "Enable website protection", pendingLabel: "Permission required",
  },
  text: {
    id: "text", title: "Message screening",
    short: "Watches new message alerts for scams and dangerous links.",
    why: "Android needs notification access. Apollo reads only each message notification as it arrives — never your SMS inbox or history — and keeps nothing.",
    enableLabel: "Enable message screening", pendingLabel: "Permission required", route: "/text-guard",
  },
  call: {
    id: "call", title: "Call screening",
    short: "Screens incoming calls and rejects numbers you've blocked or that are known high-risk.",
    why: "Choose ApolloSG for call screening so it can check callers before they ring. On iPhone this is turned on under Phone settings.",
    enableLabel: "Enable call screening", pendingLabel: "Permission required", route: "/call-guard",
  },
  email: {
    id: "email", title: "Email monitoring",
    short: "Checks a connected mailbox for phishing, impersonation and dangerous links.",
    why: "Connect Gmail with read-only access. ApolloSG never sends email on your behalf, and you can disconnect anytime.",
    enableLabel: "Connect your email accounts", pendingLabel: "Not connected", route: "/email",
  },
};

export const GATE_ORDER: GatePermId[] = ["site", "text", "call", "email"];

export const GATE_SNOOZE_MS = 3 * 24 * 60 * 60 * 1000; // resurface after ~3 days if still declined
export const gateSnoozeKey = (id: GatePermId) => `apollo.gate.${id}.snoozeUntil`;

/** Whether this permission/connection is even requestable on the current platform. */
export function gateAppliesToPlatform(id: GatePermId): boolean {
  if (id === "site" || id === "text") return Platform.OS === "android";
  if (id === "call") return Platform.OS === "android" || Platform.OS === "ios";
  return true; // email connection works on any platform
}
