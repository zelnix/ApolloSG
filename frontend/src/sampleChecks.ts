/**
 * Sample threat data for exercising production processes and functions.
 *
 * This is NOT the preview simulation system. These are real threat examples that go through
 * the real production pipeline — the same on-device analysis, the same Triage, the same
 * Magnum DI investigation where Triage escalates. Nothing is pre-made or simulated.
 *
 * Available in ALL builds (preview and production).
 */

// ── Types ────────────────────────────────────────────────────────────────────

export interface SampleText {
  id: string;
  sender: string;
  text: string;
  app?: string;
  description: string;
}

export interface SampleEmail {
  id: string;
  from: string;
  subject: string;
  body: string;
  description: string;
}

export interface SampleLink {
  id: string;
  url: string;
  description: string;
}

export interface SampleFile {
  id: string;
  name: string;
  mime: string;
  content: string;
  description: string;
}

export interface SampleCall {
  id: string;
  number: string;
  name: string | null;
  description: string;
}

export interface SampleApp {
  id: string;
  appName: string;
  packageId: string;
  developer: string;
  source: string;
  purpose: string;
  permissions: string[];
  description: string;
}

// ── Sample data ──────────────────────────────────────────────────────────────

export const SAMPLE_TEXTS: SampleText[] = [
  {
    id: "sample-txt-delivery-ok",
    sender: "AusPost",
    text: "Your parcel AP88213 was delivered to your front door at 2:14pm. Track future deliveries in the AusPost app you already have.",
    description: "A plain delivery notice: no link, no request, no urgency.",
  },
  {
    id: "sample-txt-bank-verify",
    sender: "+61 448 221 905",
    text: "CommBank: A payment of $920.00 to CRYPTO EXCHANGE LTD is pending. If this wasn't you, cancel it now at http://commbank-cancel.co/stop and confirm your NetBank password.",
    description: "Bank pretext with a lookalike link and a password request.",
  },
  {
    id: "sample-txt-toll-fine",
    sender: "Linkt-Notice",
    text: "LINKT: You have an unpaid toll of $4.85. A $65 fine will be issued today unless you pay at https://linkt-au-pay.top/settle",
    description: "Toll pretext with a same-day fine threat and a lookalike payment link.",
  },
  {
    id: "sample-txt-family",
    sender: "+61 491 570 006",
    text: "Hi mum, I dropped my phone in the sink and this is my new number. I can't get into my banking app - can you pay my rent of $1,480 today and I'll fix it up Friday? Please don't ring, the mic is broken.",
    description: "Family impersonation from a new number asking for a payment.",
  },
  {
    id: "sample-txt-otp",
    sender: "Support",
    text: "Your verification code is 408 221. Reply with this code to confirm you own this number and release your refund.",
    description: "Asks the recipient to reply with a one-time code.",
  },
  {
    id: "sample-txt-investment",
    sender: "+44 7700 900182",
    text: "Hi! Remember me from the trading group? My mentor is up 340% this month on AI coin. Minimum entry is only $250 and I can walk you through the wallet setup on WhatsApp.",
    description: "Investment approach with an outsized return claim.",
  },
];

export const SAMPLE_LINKS: SampleLink[] = [
  { id: "sample-link-known", url: "https://www.servicesaustralia.gov.au/mygov", description: "A well-known Australian government domain." },
  { id: "sample-link-bank-lookalike", url: "http://commbank-cancel.co/stop", description: "A bank-lookalike domain served over plain HTTP." },
  { id: "sample-link-toll", url: "https://linkt-au-pay.top/settle", description: "A toll-payment lookalike on an unusual TLD." },
  { id: "sample-link-shortener", url: "https://bit.ly/3xRq7Kp", description: "A shortened link that hides its destination." },
];

export const SAMPLE_CALLS: SampleCall[] = [
  { id: "sample-call-contact", number: "+61 3 9345 2000", name: "Royal Melbourne Hospital", description: "A listed Australian landline that matches a saved contact." },
  { id: "sample-call-mobile", number: "+61 412 668 341", name: null, description: "An unknown Australian mobile number." },
  { id: "sample-call-spoof-gov", number: "+61 2 6216 1111", name: null, description: "A Canberra landline of the kind used when callers claim to be a government department." },
  { id: "sample-call-international", number: "+234 701 554 2298", name: null, description: "An unexpected international number." },
];

export const SAMPLE_FILES: SampleFile[] = [
  { id: "sample-file-statement", name: "Statement_June.pdf", mime: "application/pdf",
    content: "%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n",
    description: "A small PDF whose content matches its name and type." },
  { id: "sample-file-double-ext", name: "Invoice_4471.pdf.exe", mime: "application/octet-stream",
    content: "MZ\u0090\u0000\u0003\u0000\u0000\u0000This program cannot be run in DOS mode.\n",
    description: "A file named like a PDF whose real content is a Windows program." },
  { id: "sample-file-macro", name: "Payroll_Update.docm", mime: "application/vnd.ms-word.document.macroEnabled.12",
    content: "PK\u0003\u0004macro-enabled document placeholder\n",
    description: "A macro-enabled Word document." },
];

export const SAMPLE_APPS: SampleApp[] = [
  { id: "sample-app-store", appName: "ABC listen", packageId: "au.net.abc.listen", developer: "Australian Broadcasting Corporation",
    source: "play_store", purpose: "game_media", permissions: ["notifications"],
    description: "A mainstream media app from an official store with one ordinary permission." },
  { id: "sample-app-cleaner", appName: "Turbo Battery Saver Pro", packageId: "com.turbo.batterysaver.pro", developer: "TS Mobile Labs",
    source: "browser", purpose: "cleaner", permissions: ["accessibility", "overlay", "sms", "notifications", "device_admin"],
    description: "A 'battery saver' downloaded from a website holding accessibility, overlay, SMS, notification and device-admin access." },
  { id: "sample-app-remote", appName: "QuickAssist Remote", packageId: "com.quickassist.remote", developer: "Unknown",
    source: "message", purpose: "remote_support", permissions: ["screen_share", "accessibility", "files"],
    description: "A remote-support tool sent in a message, with screen sharing and accessibility access." },
];

// ── Lookup helpers ───────────────────────────────────────────────────────────

export type SampleKind = "message" | "email" | "link" | "file" | "call" | "app";

export interface SampleKindDef {
  label: string;
  gate: string;
  path: string;
  items: { id: string; primary: string; secondary?: string; description: string }[];
}

export const SAMPLE_KINDS: Record<SampleKind, SampleKindDef> = {
  message: { label: "Messages", gate: "Text Gate", path: "/message",
    items: SAMPLE_TEXTS.map((m) => ({ id: m.id, primary: m.sender, secondary: m.text.slice(0, 80), description: m.description })) },
  email: { label: "Emails", gate: "Email Gate", path: "/email",
    items: [] }, // Email samples require full inbox simulation — not available standalone
  link: { label: "Links", gate: "Link Gate", path: "/check",
    items: SAMPLE_LINKS.map((x) => ({ id: x.id, primary: x.url, description: x.description })) },
  file: { label: "Files", gate: "File Gate", path: "/file",
    items: SAMPLE_FILES.map((f) => ({ id: f.id, primary: f.name, secondary: f.mime, description: f.description })) },
  call: { label: "Calls", gate: "Call Gate", path: "/call-guard",
    items: SAMPLE_CALLS.map((c) => ({ id: c.id, primary: c.number, secondary: c.name ?? undefined, description: c.description })) },
  app: { label: "Apps", gate: "App Gate", path: "/app-check",
    items: SAMPLE_APPS.map((a) => ({ id: a.id, primary: a.appName, secondary: `${a.developer} · ${a.packageId}`, description: a.description })) },
};

/** Find a sample text by id. Works in all builds. */
export function findSampleText(id: string): SampleText | undefined {
  return SAMPLE_TEXTS.find((t) => t.id === id);
}

/** Find a sample link by id. */
export function findSampleLink(id: string): SampleLink | undefined {
  return SAMPLE_LINKS.find((l) => l.id === id);
}

/** Find a sample file by id. */
export function findSampleFile(id: string): SampleFile | undefined {
  return SAMPLE_FILES.find((f) => f.id === id);
}

/** Find a sample call by id. */
export function findSampleCall(id: string): SampleCall | undefined {
  return SAMPLE_CALLS.find((c) => c.id === id);
}

/** Find a sample app by id. */
export function findSampleApp(id: string): SampleApp | undefined {
  return SAMPLE_APPS.find((a) => a.id === id);
}
