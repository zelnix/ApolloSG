// Original email (.eml / raw source / provider original) — read ON THE PHONE by Higgins Triage.
//
// Nothing here sends the email anywhere. Headers and security metadata are extracted on the device; the original
// reaches ApolloSG's servers only when an investigation opens, under the existing evidence and privacy rules.
// Authentication is read exactly as the RECEIVING mail server recorded it (the topmost Authentication-Results
// header) and attributed to that server — ApolloSG never re-checks SPF, DKIM or DMARC itself.
//
// Pure (no Expo imports) so it runs in node tests. Input is a "binary string": one char per byte (0–255).

import { registrableDomain } from "../brand.ts";

export type Hasher = (bytes: Uint8Array) => Promise<string>;

export interface HeaderField { name: string; value: string }
export interface Mailbox { name: string | null; address: string | null; domain: string | null }
export interface ReceivedHop { from: string | null; by: string | null; with: string | null; at: string | null }
export interface AuthEntry { method: "spf" | "dkim" | "dmarc" | "arc"; result: string; props: Record<string, string>; comment: string | null }
/** The topmost Authentication-Results header — written by the server that received the email for you. */
export interface RecordedAuth { authservId: string; spf: AuthEntry[]; dkim: AuthEntry[]; dmarc: AuthEntry[]; arc: AuthEntry[] }
export interface MimePart { path: string; type: string; disposition: string | null; filename: string | null; encoding: string | null; size: number }
export interface AttachmentInfo { name: string; type: string; size: number; sha256: string | null }
export interface EmailTechnical {
  from: Mailbox | null;
  replyTo: Mailbox[];
  returnPath: string | null;
  subject: string | null;
  date: string | null;
  messageId: string | null;
  headerCount: number;
  received: ReceivedHop[];
  recordedAuth: RecordedAuth | null;
  /** The server that wrote `recordedAuth` is one of the servers that delivered the email (top Received hops). */
  recordedAuthConfirmed: boolean;
  /** Further Authentication-Results headers lower in the message — anyone along the way could have written them. */
  furtherAuthResults: number;
  dkimSignatures: { d: string | null; s: string | null }[];
  arc: { sets: number; cv: string | null };
  mime: { type: string; partCount: number; parts: MimePart[] };
  attachments: AttachmentInfo[];
  urls: string[];
  domains: string[];
}
export interface ParsedOriginal { technical: EmailTechnical; bodyText: string; fullHeaders: boolean; sha256: string; byteLength: number }

const MAX_PARTS = 100;
const MAX_DEPTH = 6;
const MAX_HOPS = 30;
const MAX_URLS = 50;
const MAX_HASHED_ATTACHMENTS = 10;
export const MAX_ORIGINAL_BYTES = 10 * 1024 * 1024;

// ── Byte helpers ───────────────────────────────────────────────────────────────
const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

export function b64ToBinary(text: string): string {
  const clean = text.replace(/-/g, "+").replace(/_/g, "/").replace(/[^A-Za-z0-9+/]/g, "");
  // A byte array avoids millions of JS array entries for an embedded image or attachment.
  const out = new Uint8Array(Math.floor(clean.length * 6 / 8));
  let buffer = 0, bits = 0, size = 0;
  for (let i = 0; i < clean.length; i++) {
    buffer = ((buffer << 6) | B64.indexOf(clean[i])) & 0xffffff;
    bits += 6;
    if (bits >= 8) { bits -= 8; out[size++] = (buffer >> bits) & 0xff; }
  }
  return bytesToBinary(out.subarray(0, size));
}

export function binaryToBase64(bin: string): string {
  const out: string[] = [];
  let chunk = "";
  for (let i = 0; i < bin.length; i += 3) {
    const a = bin.charCodeAt(i), b = bin.charCodeAt(i + 1), c = bin.charCodeAt(i + 2);
    const n = (a << 16) | ((b || 0) << 8) | (c || 0);
    chunk += B64[(n >> 18) & 63] + B64[(n >> 12) & 63]
      + (i + 1 < bin.length ? B64[(n >> 6) & 63] : "=") + (i + 2 < bin.length ? B64[n & 63] : "=");
    if (chunk.length >= 0x8000) { out.push(chunk); chunk = ""; }
  }
  if (chunk) out.push(chunk);
  return out.join("");
}

export function binaryToBytes(bin: string): Uint8Array {
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i) & 0xff;
  return bytes;
}

export function bytesToBinary(bytes: Uint8Array): string {
  const out: string[] = [];
  for (let i = 0; i < bytes.length; i += 0x8000) out.push(String.fromCharCode(...bytes.subarray(i, i + 0x8000)));
  return out.join("");
}

/** A JS (unicode) string as UTF-8 bytes in a binary string — for pasted raw source. */
export function utf8ToBinary(text: string): string {
  const out: string[] = [];
  for (const ch of text) {
    const cp = ch.codePointAt(0) ?? 0;
    if (cp < 0x80) out.push(String.fromCharCode(cp));
    else if (cp < 0x800) out.push(String.fromCharCode(0xc0 | (cp >> 6), 0x80 | (cp & 63)));
    else if (cp < 0x10000) out.push(String.fromCharCode(0xe0 | (cp >> 12), 0x80 | ((cp >> 6) & 63), 0x80 | (cp & 63)));
    else out.push(String.fromCharCode(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 63), 0x80 | ((cp >> 6) & 63), 0x80 | (cp & 63)));
  }
  return out.join("");
}

/** UTF-8 bytes → text; a byte that isn't valid UTF-8 is kept as its Latin-1 character. */
export function utf8Decode(bin: string): string {
  const out: string[] = [];
  for (let i = 0; i < bin.length; i++) {
    const a = bin.charCodeAt(i);
    const need = a >= 0xf0 && a < 0xf8 ? 3 : a >= 0xe0 ? 2 : a >= 0xc2 && a < 0xe0 ? 1 : 0;
    if (a < 0x80 || !need || i + need >= bin.length + 0) {
      if (a < 0x80 || !need) { out.push(String.fromCharCode(a)); continue; }
    }
    let cp = a & (need === 3 ? 7 : need === 2 ? 15 : 31), ok = i + need < bin.length;
    for (let k = 1; ok && k <= need; k++) {
      const c = bin.charCodeAt(i + k);
      if ((c & 0xc0) !== 0x80) ok = false; else cp = (cp << 6) | (c & 63);
    }
    if (ok) { out.push(String.fromCodePoint(cp)); i += need; } else out.push(String.fromCharCode(a));
  }
  return out.join("");
}

function decodeCharset(bin: string, charset: string | undefined): string {
  const cs = (charset ?? "utf-8").toLowerCase();
  if (/^(us-ascii|ascii|iso-8859-1|latin1|windows-1252|cp1252)$/.test(cs)) return bin;
  return utf8Decode(bin);
}

function qpDecode(text: string): string {
  return text.replace(/=\r?\n/g, "").replace(/=([0-9A-Fa-f]{2})/g, (_m, hex) => String.fromCharCode(parseInt(hex, 16)));
}

/** RFC 2047 encoded words (=?utf-8?B?…?=) and raw UTF-8 in a header value. */
export function headerText(value: string): string {
  return utf8Decode(value).replace(/\?=\s+=\?/g, "?==?").replace(/=\?([^?]+)\?([BbQq])\?([^?]*)\?=/g, (_m, cs: string, enc: string, text: string) => {
    const raw = enc.toUpperCase() === "B" ? b64ToBinary(text) : text.replace(/_/g, " ").replace(/=([0-9A-Fa-f]{2})/g, (_x, hex) => String.fromCharCode(parseInt(hex, 16)));
    return decodeCharset(raw, cs);
  });
}

// ── Headers ────────────────────────────────────────────────────────────────────
export function splitHeaderBody(raw: string): { head: string; body: string } {
  const match = /\r?\n\r?\n/.exec(raw);
  return match ? { head: raw.slice(0, match.index), body: raw.slice(match.index + match[0].length) } : { head: raw, body: "" };
}

export function parseHeaderFields(head: string): HeaderField[] {
  const out: HeaderField[] = [];
  for (const line of head.split(/\r?\n/)) {
    if (/^[ \t]/.test(line) && out.length) { out[out.length - 1].value += " " + line.trim(); continue; }
    const match = /^([!-9;-~]+):[ \t]?(.*)$/.exec(line);
    if (match) out.push({ name: match[1], value: match[2].trim() });
  }
  return out;
}

const all = (fields: HeaderField[], name: string) => fields.filter((f) => f.name.toLowerCase() === name).map((f) => f.value);
const first = (fields: HeaderField[], name: string) => all(fields, name)[0] ?? null;

/** Pasted text that is a raw message source ("Show original"), not a forwarded copy. */
export function looksLikeRawEmail(text: string): boolean {
  const { head } = splitHeaderBody(text.replace(/^\s+/, ""));
  if (!/^[!-9;-~]+:/.test(head.split(/\r?\n/)[0] ?? "")) return false;
  const names = new Set(parseHeaderFields(head).map((f) => f.name.toLowerCase()));
  return names.size >= 4 && names.has("from") && (names.has("received") || names.has("authentication-results") || names.has("dkim-signature"));
}

function parseMailbox(value: string): Mailbox | null {
  const v = headerText(value).trim();
  if (!v) return null;
  const angle = /^(.*)<([^<>]*)>\s*$/.exec(v);
  let name: string | null, address: string | null;
  if (angle) {
    name = angle[1].trim().replace(/^"|"$/g, "").trim() || null;
    address = angle[2].trim() || null;
  } else {
    const found = /[^\s<>"(),]+@[^\s<>"(),]+/.exec(v);
    address = found ? found[0] : null;
    name = found ? v.replace(found[0], "").replace(/[()"]/g, "").trim() || null : v;
  }
  const domain = address && address.includes("@") ? address.split("@").pop()!.toLowerCase() : null;
  return { name, address, domain };
}

function parseMailboxList(value: string): Mailbox[] {
  return (value.match(/(?:"[^"]*"|<[^>]*>|[^,])+/g) ?? []).map(parseMailbox).filter((m): m is Mailbox => !!m);
}

function isoOrRaw(value: string): string | null {
  const text = value.trim();
  if (!text) return null;
  const time = Date.parse(text.replace(/\s*\([^)]*\)\s*$/, ""));
  return Number.isFinite(time) ? new Date(time).toISOString() : text.slice(0, 80);
}

function parseReceived(value: string): ReceivedHop {
  const semi = value.lastIndexOf(";");
  const route = semi >= 0 ? value.slice(0, semi) : value;
  const pick = (re: RegExp) => re.exec(route)?.[1]?.toLowerCase() ?? null;
  return { from: pick(/\bfrom\s+([^\s;()]+)/i), by: pick(/\bby\s+([^\s;()]+)/i), with: pick(/\bwith\s+([^\s;()]+)/i), at: semi >= 0 ? isoOrRaw(value.slice(semi + 1)) : null };
}

/** Parse one Authentication-Results header as the server that wrote it recorded it (RFC 8601). */
export function parseAuthResults(value: string): RecordedAuth {
  const segments = value.split(";");
  // Some servers (Microsoft 365) write no authserv-id: the first segment is already a result.
  const authservId = /^\s*(spf|dkim|dmarc|arc)\s*=/i.test(segments[0] ?? "") ? "unknown" : (segments.shift() ?? "").trim().split(/\s+/)[0] || "unknown";
  const out: RecordedAuth = { authservId, spf: [], dkim: [], dmarc: [], arc: [] };
  for (const segment of segments) {
    const match = /^\s*(spf|dkim|dmarc|arc)\s*=\s*([a-z]+)/i.exec(segment);
    if (!match) continue;
    const method = match[1].toLowerCase() as AuthEntry["method"];
    const props: Record<string, string> = {};
    for (const p of segment.matchAll(/([a-z]+\.[a-z-]+)=("[^"]*"|[^\s;]+)/gi)) props[p[1].toLowerCase()] = p[2].replace(/^"|"$/g, "");
    out[method].push({ method, result: match[2].toLowerCase(), props, comment: /\(([^)]*)\)/.exec(segment)?.[1]?.trim() ?? null });
  }
  return out;
}

function parseParams(value: string): { value: string; params: Record<string, string> } {
  const parts = value.match(/(?:"[^"]*"|[^;])+/g) ?? [""];
  const params: Record<string, string> = {};
  for (const p of parts.slice(1)) {
    const match = /^\s*([^=\s]+)\s*=\s*(.*)$/.exec(p);
    if (!match) continue;
    const rfc2231 = /^([^*]+)\*(?:\d+)?(\*)?$/.exec(match[1]);
    const key = (rfc2231 ? rfc2231[1] : match[1]).toLowerCase();
    let val = match[2].trim().replace(/^"|"$/g, "");
    if (rfc2231?.[2]) val = utf8Decode(val.replace(/^[^']*'[^']*'/, "").replace(/%([0-9A-Fa-f]{2})/g, (_m, hex) => String.fromCharCode(parseInt(hex, 16))));
    params[key] = rfc2231 ? (params[key] ?? "") + val : val;
  }
  return { value: (parts[0] ?? "").trim().toLowerCase(), params };
}

// ── MIME ───────────────────────────────────────────────────────────────────────
interface Walk {
  parts: MimePart[]; texts: { type: string; text: string }[]; attachments: { name: string; type: string; bin: string }[];
  /** Pictures carried inside the message itself (Content-ID), which its HTML shows as cid: images. */
  inline: InlineImage[];
}
export interface InlineImage { cid: string; type: string; bin: string }

function splitMultipart(body: string, boundary: string): string[] {
  const delimiter = `--${boundary}`;
  const parts: string[] = [];
  let current: string[] | null = null;
  for (const line of body.split(/\r?\n/)) {
    if (line.startsWith(delimiter)) {
      if (current) parts.push(current.join("\r\n"));
      if (line.startsWith(`${delimiter}--`)) return parts;
      current = [];
      continue;
    }
    current?.push(line);
  }
  if (current?.length) parts.push(current.join("\r\n"));
  return parts;
}

function walk(fields: HeaderField[], body: string, path: string, depth: number, w: Walk): void {
  if (w.parts.length >= MAX_PARTS) return;
  const ct = parseParams(first(fields, "content-type") ?? "text/plain");
  const type = ct.value || "text/plain";
  const disposition = parseParams(first(fields, "content-disposition") ?? "");
  const encoding = (first(fields, "content-transfer-encoding") ?? "").trim().toLowerCase() || null;
  const filename = disposition.params.filename ? headerText(disposition.params.filename) : ct.params.name ? headerText(ct.params.name) : null;
  if (type.startsWith("multipart/") && ct.params.boundary && depth < MAX_DEPTH) {
    w.parts.push({ path, type, disposition: null, filename: null, encoding, size: body.length });
    splitMultipart(body, ct.params.boundary).forEach((chunk, i) => {
      const { head, body: inner } = splitHeaderBody(chunk);
      walk(parseHeaderFields(head), inner, `${path}.${i + 1}`, depth + 1, w);
    });
    return;
  }
  const decoded = encoding === "base64" ? b64ToBinary(body) : encoding === "quoted-printable" ? qpDecode(body) : body;
  const dispositionValue = disposition.value || null;
  w.parts.push({ path, type, disposition: dispositionValue, filename, encoding, size: decoded.length });
  const cid = first(fields, "content-id")?.trim().replace(/^<|>$/g, "");
  if (cid && type.startsWith("image/")) w.inline.push({ cid, type, bin: decoded });
  const attachment = dispositionValue === "attachment" || type === "message/rfc822" || (!!filename && !type.startsWith("text/"));
  if (attachment) w.attachments.push({ name: filename ?? (type === "message/rfc822" ? "attached message.eml" : "unnamed attachment"), type, bin: decoded });
  else if (type === "text/plain" || type === "text/html") w.texts.push({ type, text: decodeCharset(decoded, ct.params.charset) });
}

function htmlToText(html: string): string {
  return html.replace(/<(script|style)[\s\S]*?<\/\1>/gi, " ").replace(/<br\s*\/?>|<\/(p|div|tr|li|h\d)>/gi, "\n").replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"").replace(/&#39;/g, "'")
    .replace(/&#(\d+);/g, (_m, n) => String.fromCharCode(Number(n))).replace(/[ \t]+/g, " ").replace(/\n\s*\n+/g, "\n\n").trim();
}

const URL_RE = /https?:\/\/[^\s<>"')\]]+/gi;
const hostOf = (url: string) => /^https?:\/\/([^/?#:]+)/i.exec(url)?.[1]?.toLowerCase() ?? null;
const domainOf = (value: string | null | undefined) => (value ? value.replace(/^.*@/, "").replace(/[>\s].*$/, "").toLowerCase() || null : null);

/** Read an original message on the device. `raw` is a binary string of the exact bytes received. */
export async function parseOriginalEmail(raw: string, hash: Hasher): Promise<ParsedOriginal> {
  const { head, body } = splitHeaderBody(raw);
  const fields = parseHeaderFields(head);
  const w: Walk = { parts: [], texts: [], attachments: [], inline: [] };
  walk(fields, body, "1", 0, w);

  const plain = w.texts.filter((t) => t.type === "text/plain").map((t) => t.text).join("\n\n").trim();
  const html = w.texts.filter((t) => t.type === "text/html").map((t) => t.text).join("\n");
  const bodyText = plain || htmlToText(html);
  const hrefs = [...html.matchAll(/href\s*=\s*["']([^"']+)["']/gi)].map((m) => m[1]).filter((u) => /^https?:\/\//i.test(u));
  const urls = [...new Set([...(bodyText.match(URL_RE) ?? []), ...hrefs].map((u) => u.replace(/[.,;]+$/, "")))].slice(0, MAX_URLS);

  const authHeaders = all(fields, "authentication-results");
  const recordedAuth = authHeaders.length ? parseAuthResults(authHeaders[0]) : null;
  const arcSeals = all(fields, "arc-seal");
  const topArc = arcSeals.map((v) => ({ i: Number(/\bi=(\d+)/.exec(v)?.[1] ?? 0), cv: /\bcv=(\w+)/i.exec(v)?.[1]?.toLowerCase() ?? null })).sort((a, b) => b.i - a.i)[0];
  const from = first(fields, "from") ? parseMailbox(first(fields, "from")!) : null;
  const replyTo = first(fields, "reply-to") ? parseMailboxList(first(fields, "reply-to")!) : [];
  const returnPath = first(fields, "return-path")?.replace(/[<>]/g, "").trim() || null;
  const messageId = first(fields, "message-id")?.trim() || null;
  const dkimSignatures = all(fields, "dkim-signature").map((v) => ({ d: /\bd=([^;\s]+)/.exec(v)?.[1]?.toLowerCase() ?? null, s: /\bs=([^;\s]+)/.exec(v)?.[1] ?? null }));
  const received = all(fields, "received").slice(0, MAX_HOPS).map(parseReceived);
  const deliveringHosts = received.slice(0, 3).map((h) => h.by).filter((h): h is string => !!h);
  const recordedAuthConfirmed = !!recordedAuth && recordedAuth.authservId !== "unknown" && deliveringHosts.some((by) => sameOrg(by, recordedAuth.authservId));

  const attachments: AttachmentInfo[] = [];
  for (const [index, a] of w.attachments.entries()) {
    attachments.push({ name: a.name, type: a.type, size: a.bin.length, sha256: index < MAX_HASHED_ATTACHMENTS ? await hash(binaryToBytes(a.bin)) : null });
  }
  const recordedDomains = recordedAuth ? [...recordedAuth.spf, ...recordedAuth.dkim, ...recordedAuth.dmarc].flatMap((e) => [e.props["smtp.mailfrom"], e.props["header.d"], e.props["header.from"]].map(domainOf)) : [];
  const domains = [...new Set([from?.domain, ...replyTo.map((r) => r.domain), domainOf(returnPath), ...dkimSignatures.map((d) => d.d), ...recordedDomains,
    domainOf(messageId), ...urls.map(hostOf)].filter((d): d is string => !!d))].slice(0, 30);

  const technical: EmailTechnical = {
    from, replyTo, returnPath,
    subject: first(fields, "subject") ? headerText(first(fields, "subject")!) : null,
    date: first(fields, "date") ? isoOrRaw(first(fields, "date")!) : null,
    messageId, headerCount: fields.length, received, recordedAuth, recordedAuthConfirmed,
    furtherAuthResults: Math.max(0, authHeaders.length - 1),
    dkimSignatures, arc: { sets: arcSeals.length, cv: topArc?.cv ?? null },
    mime: { type: w.parts[0]?.type ?? "text/plain", partCount: w.parts.length, parts: w.parts.slice(0, 40) },
    attachments, urls, domains,
  };
  return { technical, bodyText, fullHeaders: received.length > 0 && !!from && (!!messageId || !!technical.date), sha256: await hash(binaryToBytes(raw)), byteLength: raw.length };
}

/** The message's own bodies, decoded: its HTML part (as an email client would show it), its plain-text part, and the
 *  pictures carried inside it. Nothing is fetched or rewritten here. */
export interface EmailBody { html: string | null; plain: string | null; inline: InlineImage[] }

export function readEmailBody(raw: string): EmailBody {
  const { head, body } = splitHeaderBody(raw);
  const w: Walk = { parts: [], texts: [], attachments: [], inline: [] };
  walk(parseHeaderFields(head), body, "1", 0, w);
  const html = w.texts.filter((t) => t.type === "text/html").map((t) => t.text).join("\n").trim();
  const plain = w.texts.filter((t) => t.type === "text/plain").map((t) => t.text).join("\n\n").trim();
  return { html: html || null, plain: plain || null, inline: w.inline };
}

/** Same organisation: the registrable domains match (mail.example.com.au ~ example.com.au). */
export function sameOrg(a: string | null | undefined, b: string | null | undefined): boolean {
  return !!a && !!b && registrableDomain(a.toLowerCase()) === registrableDomain(b.toLowerCase());
}
