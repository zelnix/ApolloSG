// The Original Email viewer's document (Inert Source Principle): the email's own HTML, drawn the way an email client
// showed it — anchor text, buttons, pictures carried inside the email, formatting, tables and layout — but completely
// inert. Nothing in it can navigate, open an app, dial, compose, submit, download or reach the network:
//   • every link keeps its displayed text and look but loses its destination (`href`), so there is nothing to follow;
//   • forms become plain boxes, buttons and fields can't be pressed or typed in;
//   • scripts, frames, plug-ins, media, meta refresh, <base> and outside style sheets are removed;
//   • pictures on the sender's servers are never fetched: each keeps its place as a labelled box, and tracking pixels
//     are left out; only pictures carried inside the email itself (cid:) or written into it (data:) are drawn;
//   • a Content Security Policy that allows nothing but those pictures and inline styles backs all of this up.
// Where each link really goes is kept separately as evidence (`links`: displayed text → actual destination) and is
// shown in the Evidence analysis, never in place of the link's own text.
// Pure: no React Native, unit-tested in node.
import { binaryToBase64, type EmailBody } from "./triage/emailOriginal.ts";

export interface EmailLink { text: string; href: string }

export interface InertEmail {
  /** A complete, self-contained document: no script, no network, nothing that navigates. */
  document: string;
  /** Every destination the email's links and buttons carried, with the text they displayed. */
  links: EmailLink[];
  /** The width the email was laid out for (its widest fixed-width table or block, e.g. 600), or null when it flows. */
  layoutWidth: number | null;
  /** Pictures on outside servers that were not fetched (each different address once). */
  remoteImages: number;
  /** Tracking pixels (tiny or hidden outside pictures) left out. */
  trackingPixels: number;
}

const CSP = [
  "default-src 'none'", "img-src data:", "style-src 'unsafe-inline'", "font-src data:", "script-src 'none'",
  "connect-src 'none'", "media-src 'none'", "object-src 'none'", "frame-src 'none'", "child-src 'none'",
  "form-action 'none'", "base-uri 'none'",
].join("; ");

// Our defaults come first (and with no specificity where the email may style the same thing), so the email's own
// styles win wherever they speak. Only the inert rules are forced.
const BASE_CSS = `
html { background: #FFFFFF; color: #000000; font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; font-size: 14px; -webkit-text-size-adjust: 100%; }
:where(body) { margin: 0; padding: 8px; overflow-wrap: break-word; }
:where(img) { max-width: 100%; height: auto; }
:where(a[data-apollo-link]) { color: #1155CC; text-decoration: underline; }
a, area, button, input, select, textarea, label, summary, details, option { pointer-events: none !important; cursor: default !important; }
* { -webkit-tap-highlight-color: transparent !important; -webkit-touch-callout: none !important; -webkit-user-drag: none !important; }
.apollo-remote-img { display: inline-block; box-sizing: border-box; max-width: 100%; min-width: 24px; min-height: 18px; padding: 4px 6px; border: 1px dashed #B8C0CC; background: #F1F3F6; color: #5A6472; font: 11px/1.3 -apple-system, Helvetica, Arial, sans-serif; text-align: center; vertical-align: middle; overflow: hidden; }
`;

/** Elements kept as they are (attributes filtered). Anything else is unwrapped: its text stays, the tag goes. */
const KEEP = new Set(`div span p br hr a b strong i em u s strike del ins sub sup small big font center blockquote q cite code pre kbd
samp var tt mark abbr acronym address dfn h1 h2 h3 h4 h5 h6 ul ol li dl dt dd table thead tbody tfoot tr td th caption col colgroup
img figure figcaption picture section article header footer nav main aside label button input select option optgroup textarea
fieldset legend style map area wbr nobr bdi bdo time details summary ruby rt rp`.split(/\s+/));
/** Removed with everything inside them. */
const DROP = new Set(["script", "noscript", "iframe", "frame", "frameset", "object", "applet", "template", "title", "xmp",
  "noembed", "noframes", "svg", "math", "video", "audio", "canvas", "dialog", "portal", "plaintext"]);
/** Their content is raw text, not markup: it runs to the matching close tag. */
const RAW_TEXT = new Set(["script", "style", "title", "textarea", "xmp", "iframe", "noembed", "noframes", "noscript", "plaintext"]);
const VOID = new Set(["br", "hr", "img", "input", "col", "area", "wbr", "embed", "link", "meta", "base", "source", "track", "param", "keygen"]);
const ATTRS = new Set(`style class id dir lang title align valign bgcolor color face size width height border cellpadding cellspacing
colspan rowspan nowrap alt role span start type value checked selected disabled readonly placeholder label headers scope abbr summary
frame rules hspace vspace clear noshade compact reversed cols rows multiple maxlength open datetime text link vlink alink char charoff
axis bordercolor`.split(/\s+/));

import { decodeHtmlEntities as decodeEntities } from "@/src/utils/decodeHtmlEntities";
export { decodeEntities };

const escapeText = (v: string) => v.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const escapeAttr = (v: string) => escapeText(v).replace(/"/g, "&quot;");
const squash = (v: string) => v.replace(/[\s\u00a0\u200b-\u200d\u00ad\u034f]+/g, " ").trim();

const TOKEN = /<!--[\s\S]*?(?:-->|$)|<!\[CDATA\[[\s\S]*?(?:\]\]>|$)|<![^>]*>|<\?[^>]*>|<(\/?)([a-zA-Z][a-zA-Z0-9:_-]*)((?:[^>"']|"[^"]*"|'[^']*')*)>/g;
const ATTR = /([^\s"'>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;

function parseAttrs(raw: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const m of raw.matchAll(ATTR)) {
    const name = m[1].toLowerCase();
    if (!out.has(name)) out.set(name, m[2] ?? m[3] ?? m[4] ?? "");
  }
  return out;
}

interface Context { inline: Map<string, string>; remote: Set<string>; pixels: number }

/** Outside addresses in CSS (backgrounds, fonts, imports) become nothing; pictures carried in the email stay. */
function cleanCss(css: string, ctx: Context): string {
  return css
    .replace(/\/\*[\s\S]*?(?:\*\/|$)/g, "")
    .replace(/\\([0-9a-fA-F]{1,6})\s?/g, (_m, h: string) => { const n = parseInt(h, 16); return n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : ""; })
    .replace(/\\([^0-9a-fA-F"'\n])/g, "$1")
    .replace(/@import[^;]*;?/gi, "")
    .replace(/url\s*\(\s*(?:"([^"]*)"|'([^']*)'|([^)]*))\s*\)/gi, (_m, a?: string, b?: string, c?: string) => {
      const url = (a ?? b ?? c ?? "").trim();
      if (/^data:image\//i.test(url)) return `url("${url.replace(/["\\<>]/g, "")}")`;
      const cid = /^cid:(.+)$/i.exec(url);
      if (cid && ctx.inline.has(cid[1])) return `url("${ctx.inline.get(cid[1])}")`;
      if (url) ctx.remote.add(url);
      return "none";
    })
    .replace(/(?:image-set|-webkit-image-set|src)\s*\(/gi, "none(")
    .replace(/expression\s*\(/gi, "none(")
    .replace(/(?:-moz-binding|behavior)\s*:[^;}]*/gi, "")
    .replace(/javascript\s*:/gi, "");
}

const px = (v: string | undefined) => (v && /^\d+(\.\d+)?$/.test(v.trim()) ? `${v.trim()}px` : v && /^\d+(\.\d+)?%$/.test(v.trim()) ? v.trim() : null);
const dimension = (attr: string | undefined, style: string, prop: "width" | "height"): number | null => {
  const fromStyle = new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*(\\d+(?:\\.\\d+)?)px`, "i").exec(style)?.[1];
  const value = fromStyle ?? (attr && /^\d+(\.\d+)?$/.test(attr.trim()) ? attr.trim() : null);
  return value == null ? null : Number(value);
};

/** The kept attributes, rebuilt and quoted. `style` is cleaned; anything that names a destination or runs is gone. */
function keptAttrs(attrs: Map<string, string>, ctx: Context, skip: string[] = []): string {
  let out = "";
  for (const [name, raw] of attrs) {
    if (skip.includes(name)) continue;
    if (name === "background") { const url = decodeEntities(raw).trim(); if (url && !/^data:image\//i.test(url)) ctx.remote.add(url); continue; }
    if (!ATTRS.has(name) && !/^aria-[a-z-]+$/.test(name)) continue;
    const value = name === "style" ? cleanCss(decodeEntities(raw), ctx) : decodeEntities(raw);
    out += ` ${name}="${escapeAttr(value)}"`;
  }
  return out;
}

/** An outside picture: its place and its words (alt text), never its content. */
function placeholder(attrs: Map<string, string>, ctx: Context): string {
  const style = cleanCss(decodeEntities(attrs.get("style") ?? ""), ctx);
  const size = [px(attrs.get("width")) ? `width:${px(attrs.get("width"))}` : "", px(attrs.get("height")) ? `height:${px(attrs.get("height"))}` : ""].filter(Boolean).join(";");
  const alt = squash(decodeEntities(attrs.get("alt") ?? ""));
  const keep = keptAttrs(attrs, ctx, ["style", "width", "height", "alt", "type", "value", "src", "class"]);
  return `<span class="apollo-remote-img" role="img" aria-label="${escapeAttr(alt || "Picture not loaded")}"${keep} style="${escapeAttr([size, style].filter(Boolean).join(";"))}">${escapeText(alt || "Picture not loaded")}</span>`;
}

/** An <img>: drawn from the email itself when it carries the picture; otherwise a placeholder, or nothing for a pixel. */
function image(attrs: Map<string, string>, ctx: Context): string {
  const src = decodeEntities(attrs.get("src") ?? "").trim();
  if (/^data:image\//i.test(src)) return `<img src="${escapeAttr(src)}"${keptAttrs(attrs, ctx, ["src"])}>`;
  const cid = /^cid:(.+)$/i.exec(src);
  if (cid && ctx.inline.has(cid[1])) return `<img src="${ctx.inline.get(cid[1])}"${keptAttrs(attrs, ctx, ["src"])}>`;
  const style = decodeEntities(attrs.get("style") ?? "");
  const w = dimension(attrs.get("width"), style, "width");
  const h = dimension(attrs.get("height"), style, "height");
  const hidden = /display\s*:\s*none|visibility\s*:\s*hidden/i.test(style);
  if (src && (hidden || (w != null && h != null && w <= 2 && h <= 2) || w === 0 || h === 0)) { ctx.pixels += 1; return ""; }
  if (src) ctx.remote.add(src);
  return placeholder(attrs, ctx);
}

/** Sanitise the email's HTML into the inert viewer document. Null when the email has no usable HTML body. */
export function inertEmail(body: Pick<EmailBody, "html" | "inline">): InertEmail | null {
  const html = body.html ?? "";
  if (!html.trim()) return null;
  const ctx: Context = {
    inline: new Map(body.inline.map((p) => [p.cid, `data:${p.type};base64,${binaryToBase64(p.bin)}`])), remote: new Set(), pixels: 0,
  };
  const links: EmailLink[] = [];
  const open: { href: string; text: string[] }[] = [];
  let bodyAttrs = "";
  let out = "";
  let skip: { name: string; depth: number } | null = null;
  let last = 0;

  const text = (segment: string) => {
    if (skip || !segment) return;
    for (const l of open) l.text.push(decodeEntities(segment));
    // A stray "<" in text is written as text, so the only markup in the document is the markup built here.
    out += segment.replace(/<(?=[a-zA-Z/!?])/g, "&lt;");
  };
  const closeLink = () => {
    const l = open.pop();
    if (!l) return;
    const shown = squash(l.text.join(""));
    if (!links.some((x) => x.href === l.href && x.text === shown)) links.push({ text: shown, href: l.href });
  };

  TOKEN.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = TOKEN.exec(html))) {
    text(html.slice(last, m.index));
    last = TOKEN.lastIndex;
    const name = m[2]?.toLowerCase();
    if (!name) continue; // comments (incl. Outlook's conditional blocks), doctype, CDATA, processing instructions
    const closing = m[1] === "/";

    if (skip) {
      if (name === skip.name) skip.depth += closing ? -1 : VOID.has(name) ? 0 : 1;
      if (skip.depth <= 0) skip = null;
      continue;
    }
    if (!closing && RAW_TEXT.has(name)) {
      const end = new RegExp(`</${name}\\s*>`, "i").exec(html.slice(last));
      const inner = end ? html.slice(last, last + end.index) : html.slice(last);
      last = end ? last + end.index + end[0].length : html.length;
      TOKEN.lastIndex = last;
      if (name === "style") out += `<style>${cleanCss(inner, ctx).replace(/<\/?style/gi, "")}</style>`;
      else if (name === "textarea") out += `<textarea readonly tabindex="-1"${keptAttrs(parseAttrs(m[3]), ctx, ["readonly"])}>${escapeText(decodeEntities(inner))}</textarea>`;
      continue;
    }
    if (DROP.has(name)) { if (!closing && !VOID.has(name) && !/\/\s*$/.test(m[3])) skip = { name, depth: 1 }; continue; }

    const attrs = closing ? new Map<string, string>() : parseAttrs(m[3]);
    if (name === "body") { if (!closing) bodyAttrs = keptAttrs(attrs, ctx); continue; }
    if (name === "form") { out += closing ? "</div>" : `<div${keptAttrs(attrs, ctx)}>`; continue; }
    if (name === "input" && (attrs.get("type") ?? "").toLowerCase() === "image") { out += image(attrs, ctx); continue; }
    if (!KEEP.has(name)) continue; // html, head, meta, link, base, embed, source, unknown and Office tags: the tag goes, its text stays

    if (closing) {
      if (VOID.has(name)) continue;
      if (name === "a") closeLink();
      out += `</${name}>`;
      continue;
    }
    const href = decodeEntities(attrs.get("href") ?? "").trim();
    const destination = href && !href.startsWith("#") ? href : null;
    switch (name) {
      case "img":
        if (open.length) { const alt = squash(decodeEntities(attrs.get("alt") ?? "")); for (const l of open) l.text.push(alt ? ` [picture: ${alt}] ` : " [picture] "); }
        out += image(attrs, ctx);
        break;
      case "a":
        out += `<a${destination ? ' data-apollo-link=""' : ""}${keptAttrs(attrs, ctx)}>`;
        if (destination) open.push({ href: destination, text: [] });
        break;
      case "area":
        if (destination) links.push({ text: squash(decodeEntities(attrs.get("alt") ?? "")), href: destination });
        out += `<area${keptAttrs(attrs, ctx)}>`;
        break;
      case "button": out += `<button type="button" tabindex="-1"${keptAttrs(attrs, ctx, ["type"])}>`; break;
      case "input": out += `<input readonly tabindex="-1"${keptAttrs(attrs, ctx, ["readonly"])}>`; break;
      case "select": out += `<select tabindex="-1"${keptAttrs(attrs, ctx)}>`; break;
      case "details": out += `<details open${keptAttrs(attrs, ctx, ["open"])}>`; break;
      default: out += `<${name}${keptAttrs(attrs, ctx)}>`;
    }
  }
  text(html.slice(last));
  while (open.length) closeLink();

  const visible = /<(img|span class="apollo-remote-img")/.test(out) || squash(decodeEntities(out.replace(/<style>[\s\S]*?<\/style>/g, "").replace(/<[^>]+>/g, " "))).length > 0;
  if (!visible) return null;
  const document = `<!doctype html><html><head><meta charset="utf-8">`
    + `<meta http-equiv="Content-Security-Policy" content="${CSP}">`
    + `<meta name="referrer" content="no-referrer">`
    + `<meta name="format-detection" content="telephone=no, email=no, address=no, date=no">`
    + `<meta name="viewport" content="width=device-width, initial-scale=1">`
    + `<style>${BASE_CSS}</style></head><body${bodyAttrs}>${out}</body></html>`;
  return { document, links, layoutWidth: layoutWidth(out), remoteImages: ctx.remote.size, trackingPixels: ctx.pixels };
}

const LAYOUT_TAGS = /<(table|td|th|div|center|img|span class="apollo-remote-img")\b[^>]*>/g;

/** The widest fixed width the email's own layout asks for — how wide an email client lays it out before fitting it. */
function layoutWidth(markup: string): number | null {
  let widest = 0;
  for (const [tag] of markup.matchAll(LAYOUT_TAGS)) {
    const attr = /\swidth="(\d{3,4})(?:px)?"/.exec(tag)?.[1];
    const style = /style="[^"]*?(?:^|[;\s"])(?:min-)?width:\s*(\d{3,4})px/.exec(tag)?.[1];
    for (const v of [attr, style]) if (v && Number(v) <= 1200) widest = Math.max(widest, Number(v));
  }
  return widest || null;
}

/** The document fitted to the width it is shown in, the way a phone's email app shrinks a wide email to the screen. */
export function fittedEmail(email: Pick<InertEmail, "document" | "layoutWidth">, viewWidth: number): string {
  if (!email.layoutWidth || viewWidth <= 0) return email.document;
  const zoom = Math.max(0.4, Math.min(1, viewWidth / (email.layoutWidth + 16)));
  return zoom >= 1 ? email.document : email.document.replace("</head>", `<style>html { zoom: ${zoom.toFixed(3)}; }</style></head>`);
}

/** Apply a text redaction function to the visible text content of an inert email document, preserving the HTML
 *  structure, tag attributes, style blocks and layout. Only text nodes (the words on screen) are decoded, redacted
 *  and re-encoded; everything else passes through unchanged. This lets the Redacted tab look identical to the
 *  Original tab except for the specific content the redactor masks.
 *  Pure: no DOM, unit-tested in node. */
export function redactInertEmail(email: InertEmail, redact: (text: string) => string): InertEmail {
  const doc = email.document;
  let result = "";
  let i = 0;

  while (i < doc.length) {
    if (doc[i] === "<") {
      // Inside a tag: copy verbatim until ">"
      const tagEnd = doc.indexOf(">", i);
      if (tagEnd === -1) { result += doc.slice(i); break; }
      const tag = doc.slice(i, tagEnd + 1);
      result += tag;
      i = tagEnd + 1;

      // <style> content is CSS, not user-visible text: skip until </style>
      if (/^<style[\s>]/i.test(tag)) {
        const close = doc.indexOf("</style>", i);
        if (close === -1) { result += doc.slice(i); break; }
        result += doc.slice(i, close);
        i = close; // closing tag picked up on next iteration
      }
      continue;
    }

    // Text node: everything up to the next tag
    const nextTag = doc.indexOf("<", i);
    const segment = nextTag === -1 ? doc.slice(i) : doc.slice(i, nextTag);

    if (segment) {
      const decoded = decodeEntities(segment);
      const redacted = redact(decoded);
      // Fast path: nothing changed → reuse original segment (avoids unnecessary re-encoding differences
      // like &amp; → & → &amp; round-trip when the text has no credentials to mask)
      result += decoded === redacted ? segment : escapeText(redacted);
    }

    i = nextTag === -1 ? doc.length : nextTag;
  }

  return { ...email, document: result };
}

/** "Links, buttons and pictures in this email are shown as they appeared but can't be opened…" — what the viewer did. */
export function inertEmailNote(email: Pick<InertEmail, "remoteImages" | "trackingPixels">): string {
  const parts = ["Shown as it appeared. Links, buttons and pictures in it can't be opened from here."];
  if (email.remoteImages) parts.push(`${email.remoteImages === 1 ? "1 picture" : `${email.remoteImages} pictures`} on the sender's servers ${email.remoteImages === 1 ? "wasn't" : "weren't"} loaded, so nothing was fetched.`);
  if (email.trackingPixels) parts.push(`${email.trackingPixels === 1 ? "1 tracking pixel was" : `${email.trackingPixels} tracking pixels were`} left out.`);
  return parts.join(" ");
}
