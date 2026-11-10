// How a captured original source is presented in the Evidence tab.
//
// Pure: no React, no storage, no network. The layout and every header fact are derived ONLY from
// what Apollo actually captured — the saved fields, or header lines the captured text itself
// carries. Chrome the source app showed but Apollo never captured (profile photos, "last seen",
// reaction and comment counts) is deliberately absent: the Evidence tab shows evidence, never a
// reconstruction of the app it came from.

import { decodeHtmlEntities } from "../utils/decodeHtmlEntities.ts";
import type { OriginalSource } from "../store/originalSource";

export type EvidenceLayout = "email" | "screenshot" | "message" | "chat" | "post";

export interface EvidenceField { label: string; value: string }

export interface ArtefactView {
  layout: EvidenceLayout;
  /** What this evidence is: "Email", "Screenshot", "Message", "WhatsApp chat", "Facebook post". */
  title: string;
  /** Messaging or social platform named by the capture itself — never guessed from the body. */
  platform: string | null;
  sender: string | null;
  recipient: string | null;
  subject: string | null;
  /** Send/receive time exactly as the capture recorded it. */
  occurredAt: string | null;
  /** Every captured header field, verbatim and in capture order. */
  fields: EvidenceField[];
  attachments: string[];
  /** The artefact text with its header lines lifted out, so a body renders as a body. */
  body: string | null;
  links: string[];
  bannerTitle: string;
  bannerBody: string;
}

/** Messaging apps: a capture that names one is shown as a chat. */
const CHAT_APPS = ["WhatsApp", "Facebook Messenger", "Messenger", "Telegram", "Signal", "iMessage", "WeChat", "Viber", "Snapchat", "Instagram"];
/** Platforms whose posts, pages and ads are shown as a post. */
const POST_PLATFORMS = ["Facebook", "Instagram", "X", "Twitter", "TikTok", "LinkedIn", "YouTube", "Reddit", "Threads", "Marketplace"];

const LABEL = {
  sender: /^(from|sender|number|caller|contact|page|account)$/i,
  recipient: /^(to|recipient|delivered to)$/i,
  subject: /^subject$/i,
  time: /^(received|sent|date|time|occurred|posted)$/i,
  app: /\b(app|platform|service|channel|source|via)\b/i,
  attachment: /^attachment/i,
};

const HEADER_LINE = /^(from|to|reply-to|cc|subject|date|received|sent|source app|app|platform|via|page|account|posted|post type)\s*:\s*(.+)$/i;
/** "From AusPost:" — the shape the message capture writes. */
const FROM_PREFIX = /^from\s+(.+?)\s*:\s*$/i;

const URL_IN_TEXT = /https?:\/\/[^\s"'<>)\]]+/g;

/** Links inside captured material. Reading, not interpreting: the text contains these verbatim. */
export function linksIn(...values: (string | null | undefined)[]): string[] {
  const found: string[] = [];
  for (const v of values) if (v) found.push(...(v.match(URL_IN_TEXT) ?? []));
  return [...new Set(found.map((u) => u.replace(/[.,;:]$/, "")))];
}

/** Header lines the captured text itself carries. Parsing is reading — every value is in the bytes.
 *  HTML entities are decoded since email text may have been partially processed upstream. */
function parseHeaders(text: string | null | undefined): { fields: EvidenceField[]; body: string | null } {
  if (!text) return { fields: [], body: null };
  const lines = text.split("\n");
  const fields: EvidenceField[] = [];
  let i = 0;
  for (; i < lines.length; i += 1) {
    const line = lines[i].trim();
    if (!line) { if (fields.length) continue; break; }
    const header = line.match(HEADER_LINE);
    if (header) { fields.push({ label: titleCase(header[1]), value: decodeHtmlEntities(header[2].trim()) }); continue; }
    const fromPrefix = line.match(FROM_PREFIX);
    if (fromPrefix && !fields.some((f) => /^from$/i.test(f.label))) { fields.push({ label: "From", value: decodeHtmlEntities(fromPrefix[1].trim()) }); continue; }
    break;
  }
  const body = lines.slice(i).join("\n").trim();
  return { fields, body: body || null };
}

function titleCase(label: string): string {
  const lower = label.toLowerCase();
  if (lower === "reply-to") return "Reply-to";
  if (lower === "cc") return "CC";
  if (lower === "source app") return "Source app";
  if (lower === "post type") return "Post type";
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

function valueOf(fields: EvidenceField[], label: RegExp): string | null {
  return fields.find((f) => label.test(f.label.trim()))?.value.trim() || null;
}

/** The header fields a kept original records: its saved fields, else the header lines its own text carries. */
export function headerFields(src: Pick<OriginalSource, "fields" | "text">): EvidenceField[] {
  const parsed = parseHeaders(src.text).fields;
  const saved = src.fields ?? [];
  // A capture may carry provenance (e.g. "Source app: Gmail") without the
  // email headers. Do not let that one saved field hide captured From/Subject.
  return [...saved, ...parsed.filter((f) => !saved.some((x) => x.label.trim().toLowerCase() === f.label.trim().toLowerCase()))];
}

/** The platform named BY THE CAPTURE. A scam message that merely mentions WhatsApp is still an SMS. */
function capturedPlatform(fields: EvidenceField[]): string | null {
  const stated = valueOf(fields, LABEL.app);
  if (!stated) return null;
  const known = [...CHAT_APPS, ...POST_PLATFORMS].find((p) => new RegExp(`\\b${p}\\b`, "i").test(stated));
  return known ?? stated;
}

const KIND_TITLE: Record<string, string> = {
  email: "Email", text: "Message", link: "Link", website: "Website", screenshot: "Screenshot",
  call: "Call", app: "App", file: "File", account: "Account", device: "Device record", network: "Network record",
};

const BANNER_NOUN: Record<EvidenceLayout, string> = {
  email: "email", screenshot: "screenshot", message: "message", chat: "chat message", post: "post",
};
/** For types that use the default layout, the banner names the type Apollo actually captured. */
const KIND_NOUN: Record<string, string> = {
  text: "message", call: "call record", link: "link", website: "website record", file: "file",
  app: "app details", account: "account details", device: "device record", network: "network record",
};

/** Derive the presentation for a captured source. `hasImage` says whether an image copy was kept. */
export function describeArtefact(src: OriginalSource, hasImage = false): ArtefactView {
  const parsed = parseHeaders(src.text);
  // Saved fields win over parsed ones: they came straight from the mailbox/OS, not from the body.
  const fields = headerFields(src);
  const platform = capturedPlatform(fields);
  const isChatApp = !!platform && CHAT_APPS.some((p) => new RegExp(`\\b${p}\\b`, "i").test(platform));
  const isPostPlatform = !!platform && POST_PLATFORMS.some((p) => new RegExp(`\\b${p}\\b`, "i").test(platform));
  const saysPost = fields.some((f) => /\b(post|page|ad|sponsored|reel|story|marketplace|feed)\b/i.test(`${f.label} ${f.value}`));

  const layout: EvidenceLayout =
    src.kind === "email" ? "email"
      : src.kind === "screenshot" || (hasImage && !src.text && !src.url) ? "screenshot"
        : isPostPlatform && saysPost ? "post"
          : isChatApp ? "chat"
            : "message";

  const title = layout === "chat" ? `${platform} chat`
    : layout === "post" ? `${platform} post`
      : KIND_TITLE[src.kind] ?? "Evidence";

  const banner = layout === "message" ? (KIND_NOUN[src.kind] ?? "material") : BANNER_NOUN[layout];
  return {
    layout, title, platform,
    sender: valueOf(fields, LABEL.sender),
    recipient: valueOf(fields, LABEL.recipient),
    subject: valueOf(fields, LABEL.subject),
    occurredAt: valueOf(fields, LABEL.time),
    fields,
    attachments: fields.filter((f) => LABEL.attachment.test(f.label.trim())).map((f) => f.value),
    body: decodeHtmlEntities(src.fields?.length ? (src.text?.trim() || "") : (parsed.body || "")) || null,
    links: linksIn(src.text, src.url),
    bannerTitle: `This is the original ${banner}`,
    bannerBody: `You are viewing the exact ${banner} ${src.origin === "this_device" ? "as captured on this device" : "ApolloSG received for this investigation"}. It is stored only on this device and has not been modified.`,
  };
}

/** The same artefact as the copy that left this phone: credentials removed, everything else intact.
 *  The redactor is passed in so this module stays pure and testable. */
export function redactView(view: ArtefactView, redact: (value: string) => string): ArtefactView {
  return {
    ...view,
    sender: view.sender ? redact(view.sender) : null,
    subject: view.subject ? redact(view.subject) : null,
    body: view.body ? redact(view.body) : null,
    fields: view.fields.map((f) => ({ label: f.label, value: redact(f.value) })),
    attachments: view.attachments.map(redact),
  };
}

/** Exactly what is different about the copy that left this phone — so the Redacted view can state
 *  it on sight instead of looking identical to the original. `changed: false` means nothing in this
 *  material needed hiding; it is never presented as "redacted" in that case. */
export function describeRedaction(args: {
  original: ArtefactView;
  redacted: ArtefactView;
  url?: string | null;
  sentUrl?: string | null;
  blackedOutRegions?: number;
  cropped?: boolean;
}): { changed: boolean; items: string[] } {
  const items: string[] = [];
  const { original, redacted } = args;
  if (original.body !== redacted.body) items.push("the message text");
  if (original.subject !== redacted.subject) items.push("the subject line");
  if (original.sender !== redacted.sender) items.push("the sender line");
  if (original.fields.some((f, i) => f.value !== redacted.fields[i]?.value)) items.push("one or more captured header fields");
  if (args.url && args.sentUrl && args.url !== args.sentUrl) items.push("part of the link");
  const regions = args.blackedOutRegions ?? 0;
  if (regions > 0) items.push(`${regions} area${regions === 1 ? "" : "s"} of the picture`);
  if (args.cropped) items.push("the part of the picture that was cropped away");
  return { changed: items.length > 0, items: Array.from(new Set(items)) };
}

