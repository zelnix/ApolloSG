// Shared helpers for the Scam Alerts list and detail screens. Everything here is derived from the
// official-source alert returned by /api/higgins/scams — nothing is invented for display.
import Banknote from "lucide-react-native/icons/banknote";
import Landmark from "lucide-react-native/icons/landmark";
import Laptop from "lucide-react-native/icons/laptop";
import Mail from "lucide-react-native/icons/mail";
import Phone from "lucide-react-native/icons/phone";
import ShieldAlert from "lucide-react-native/icons/shield-alert";
import ShoppingCart from "lucide-react-native/icons/shopping-cart";
import type React from "react";
import * as Localization from "expo-localization";
import { Share } from "react-native";

import { apiGet, apiPost } from "@/src/api/client";
import type { Tone } from "@/src/components/ui";
import { storage } from "@/src/utils/storage";
import { governmentScams, type GovernmentAlert } from "./hubClient";

export interface SharedScamAlert { url: string; from_label: string; title: string; severity: GovernmentAlert["severity"]; region_label: string; source: string; date_label: string; shared_at: string }
/** Send an alert to every linked family device. The server re-reads the facts from its own official snapshot. */
export function shareScamAlertWithFamily(deviceId: string, url: string) {
  return apiPost<{ shared_with: number }>("/family/scam-alerts/share", "family", { device_id: deviceId, url });
}
export function familyScamAlerts(deviceId: string) { return apiGet<SharedScamAlert[]>(`/family/scam-alerts?device_id=${encodeURIComponent(deviceId)}`); }
export const openScamAlert = (router: { push: (href: never) => void }, url: string) => router.push({ pathname: "/higgins/scam/[id]", params: { id: url } } as never);

const REGION_KEY = "apollo.scamAlerts.region";
export const loadRegionFilter = () => storage.getItem<string>(REGION_KEY, "ALL");
export const saveRegionFilter = (id: string) => storage.setItem(REGION_KEY, id);

const EU_MEMBERS = new Set("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split(" "));
/** Home for Scam Alerts: the device's region setting (no location permission). GB is the UK; EU members are the EU. */
export function homeRegion(): string {
  const code = (Localization.getLocales()[0]?.regionCode ?? "AU").toUpperCase();
  return code === "GB" ? "UK" : EU_MEMBERS.has(code) ? "EU" : code;
}
/** An alert belongs in the main list when it applies everywhere or only in the device's own country. */
export const appliesHere = (a: GovernmentAlert, home: string) => a.appliesIn === "everywhere" || a.appliesIn === home;

export const SEVERITY_TONE: Record<GovernmentAlert["severity"], Tone> = { EXTREME: "barking", HIGH: "growling", MODERATE: "ears_up", LOW: "neutral" };
export const SEVERITY_RANK: Record<GovernmentAlert["severity"], number> = { EXTREME: 3, HIGH: 2, MODERATE: 1, LOW: 0 };
export const RELEVANCE_LABEL: Record<GovernmentAlert["australianRelevance"], string> = { confirmed: "Confirmed in Australia", potential: "Could reach Australia", overseas_only: "Overseas only", unknown: "Relevance unknown" };
export const severityLabel = (s: GovernmentAlert["severity"]) => (s === "LOW" ? "Info" : `${s[0]}${s.slice(1).toLowerCase()}`);
export const alertTime = (a: GovernmentAlert) => Date.parse(a.publishedAt ?? a.reportedDate ?? "") || 0;

type Icon = React.ComponentType<{ size?: number; color?: string }>;
const ICON_RULES: [RegExp, Icon][] = [
  [/\b(tax|ato|irs|hmrc|government|centrelink|mygov|police|agency|impersonat)/i, Landmark],
  [/\b(shop|store|deliver|parcel|order|purchase|marketplace|retail)/i, ShoppingCart],
  [/\b(e-?mail|phishing|inbox)/i, Mail],
  [/\b(call|phone|sms|text message|voicemail|whatsapp)/i, Phone],
  [/\b(invest|crypto|bank|payment|money|loan|refund)/i, Banknote],
  [/\b(computer|software|tech support|remote access|malware|laptop|device)/i, Laptop],
];
/** Pick a category icon from the alert's own title/summary keywords. */
export function alertIcon(a: GovernmentAlert): Icon {
  const text = `${a.title} ${a.summary}`;
  return ICON_RULES.find(([re]) => re.test(text))?.[1] ?? ShieldAlert;
}

/** Split an official-source paragraph into bullet points (by line, semicolon or sentence). */
export function toBullets(text: string | null | undefined): string[] {
  if (!text) return [];
  return text.replace(/([.!?])\s+(?=[A-Z])/g, "$1\n").split(/\n+|;\s+/).map((t) => t.replace(/^\s*[-•*]\s*/, "").trim()).filter((t) => t.length > 2);
}

const cache = new Map<string, GovernmentAlert>();
export function rememberAlerts(list: GovernmentAlert[]) { list.forEach((a) => cache.set(a.url, a)); }
/** Find an alert by its official URL — uses the list already loaded, otherwise refetches. */
export async function findAlert(url: string): Promise<GovernmentAlert | null> {
  const hit = cache.get(url);
  if (hit) return hit;
  const result = await governmentScams();
  rememberAlerts([...result.alerts, ...result.emerging]);
  return cache.get(url) ?? null;
}

/** Open the native share sheet with the alert and its official source. Nothing is sent to Apollo. */
export async function shareScamAlert(alert: GovernmentAlert): Promise<void> {
  const headline = (alert.higgins.whatHappened || alert.summary || "").trim();
  const message = [
    `⚠️ Scam alert: ${alert.title}`,
    `Source: ${alert.source} · ${alert.dateLabel}`,
    `Severity: ${severityLabel(alert.severity)} · ${RELEVANCE_LABEL[alert.australianRelevance]}`,
    headline ? `\n${headline}` : "",
    `\nOfficial source: ${alert.url}`,
    `\nShared from ApolloSG Cyber Security.`,
  ].filter(Boolean).join("\n");
  try {
    await Share.share({ title: alert.title, message, url: alert.url }, { subject: `Scam alert: ${alert.title}`, dialogTitle: "Share this scam alert" });
  } catch {
    // Dismissed or rejected by the OS — nothing to do.
  }
}
