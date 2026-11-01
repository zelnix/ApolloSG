// The artefact as it appears in a shared evidence pack (PDF), laid out the same way the Evidence
// tab lays it out on screen — so what a bank or the police reads matches what the person saw.
//
// Pure: no printing, no files, no React. Only what Apollo captured is rendered; the sent copy is
// derived with the same redaction the investigation received.
import { describeArtefact } from "./evidencePresentation.ts";
import { NOT_PROVIDED } from "./emailRecord.ts";
import type { OriginalSource } from "../store/originalSource";

export const esc = (v: string) => v.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

/** The CSS the artefact blocks need, appended to the pack's stylesheet. */
export const ARTEFACT_CSS = `
    .artefact { border: 1px solid #CBD5E0; border-radius: 8px; overflow: hidden; margin: 6px 0; }
    .ahead { display: flex; gap: 10px; align-items: center; padding: 10px 12px; background: #F1F5F9; border-bottom: 1px solid #E2E8F0; }
    .avatar { width: 28px; height: 28px; border-radius: 14px; background: #E2E8F0; color: #0B1220; font-size: 13px; font-weight: 600; text-align: center; line-height: 28px; }
    .aname { font-size: 13px; font-weight: 600; color: #0B1220; }
    .ameta { font-size: 11px; color: #4A5568; }
    .abody { padding: 12px; }
    .asubject { font-size: 14px; font-weight: 700; color: #0B1220; margin-bottom: 6px; }
    .atext { font-size: 12px; line-height: 1.6; color: #0B1220; white-space: pre-wrap; word-break: break-word; }
    .bubble { display: inline-block; max-width: 92%; background: #F1F5F9; border-radius: 10px; padding: 10px 12px; font-size: 12px; line-height: 1.6; color: #0B1220; white-space: pre-wrap; word-break: break-word; }
    .aattach { margin-top: 8px; padding-top: 8px; border-top: 1px solid #E2E8F0; font-size: 11px; color: #4A5568; }`;

/** The original source, in the layout its type calls for, plus the headers and the sent copy. */
export function buildOriginalSourceHtml(src: OriginalSource, redact: (value: string) => string): string {
  const v = describeArtefact(src);
  const sent = v.body ? redact(v.body) : null;
  const avatar = (v.sender ?? v.platform ?? "").trim().charAt(0).toUpperCase() || "·";
  const head = (name: string, sub: string) => `<div class="ahead"><div class="avatar">${esc(avatar)}</div><div><div class="aname">${esc(name)}</div>${sub ? `<div class="ameta">${esc(sub)}</div>` : ""}</div></div>`;

  let artefact: string;
  if (v.layout === "email") {
    artefact = `${head(v.sender ?? `From: ${NOT_PROVIDED}`, [v.recipient ? `To: ${v.recipient}` : null, v.occurredAt ?? `Received: ${NOT_PROVIDED}`].filter(Boolean).join(" · "))}
      <div class="abody">
        <div class="asubject">${esc(v.subject ?? `Subject: ${NOT_PROVIDED}`)}</div>
        ${v.body ? `<div class="atext">${esc(v.body)}</div>` : '<div class="ameta">No message body was captured.</div>'}
        ${v.attachments.length ? `<div class="aattach">Attachments (${v.attachments.length}): ${esc(v.attachments.join(", "))}</div>` : ""}
      </div>`;
  } else if (v.layout === "post") {
    artefact = `${head(v.sender ?? v.platform ?? `Account: ${NOT_PROVIDED}`, [v.platform, v.occurredAt].filter(Boolean).join(" · "))}
      <div class="abody">${v.body ? `<div class="atext">${esc(v.body)}</div>` : ""}${src.url ? `<div class="ameta">${esc(src.url)}</div>` : ""}</div>`;
  } else if (v.layout === "screenshot") {
    artefact = '<div class="abody"><div class="ameta">The captured image is reproduced under &ldquo;Image evidence&rdquo; below.</div></div>';
  } else {
    const attribution = v.sender ?? v.platform ?? null;
    const body = v.body ?? src.url ?? null;
    artefact = `${attribution ? head(attribution, v.platform ?? v.title) : ""}
      <div class="abody">
        ${v.occurredAt ? `<div class="ameta">${esc(v.occurredAt)}</div>` : ""}
        ${body ? `<div class="bubble">${esc(body)}</div>` : '<div class="ameta">No content was captured for this item.</div>'}
        ${src.data !== undefined && src.data !== null ? `<pre class="srctext">${esc(JSON.stringify(src.data, null, 2))}</pre>` : ""}
      </div>`;
  }

  const parts = [
    `<h2>Original ${esc(v.title.toLowerCase())}, as captured</h2>`,
    `<div class="artefact">${artefact}</div>`,
    `<div class="srcnote">Captured ${esc(new Date(src.capturedAt).toLocaleString())} · ${src.origin === "this_device" ? "on this device" : "from the investigation"} · kept on the device only · shown unaltered</div>`,
  ];
  if (v.fields.length) {
    parts.push('<h2>Headers as captured</h2><table class="fields">');
    for (const f of v.fields) parts.push(`<tr><td class="flabel">${esc(f.label)}</td><td class="fvalue">${esc(f.value)}</td></tr>`);
    parts.push("</table>");
  }
  if (v.links.length) parts.push(`<h2>Links in this material</h2><ul>${v.links.map((u) => `<li>${esc(u)}</li>`).join("")}</ul>`);
  if (sent && sent !== v.body) {
    parts.push("<h2>Copy sent for investigation</h2>");
    parts.push(`<div class="srcbox"><pre class="srctext">${esc(sent)}</pre></div>`);
    parts.push('<div class="srcnote">Passwords, PINs and verification codes were removed before this copy left the device. Everything else is unchanged.</div>');
  }
  return parts.join("\n");
}
