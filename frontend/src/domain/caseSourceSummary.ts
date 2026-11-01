// The top card of a case: what started it and when — never what Apollo found (that is the Findings Brief's job).
// The heading comes only from the origin the case recorded when it was opened: the person submitted it, or Apollo
// detected it. When the record doesn't say, the heading says neither. The preview is the material itself, shortened:
// the original kept on the device, else what the case recorded at intake. Pure: no React, no storage.
import { describeArtefact } from "./evidencePresentation.ts";
import { emailLines, emailRecord, isEmailCase, NOT_PROVIDED } from "./emailRecord.ts";
import { CAPABILITY_LABELS } from "./protectionAreas.ts";
import type { GateId } from "./gates";
import type { EvidenceItem, CaseOrigin } from "../investigation/types";
import type { OriginalSource, OriginalSourceKind } from "../store/originalSource";
import type { PatrolEvent } from "./types";

const ORIGIN: Record<CaseOrigin, { heading: string; verb: string }> = {
  user: { heading: "What you submitted", verb: "Submitted" },
  apollo: { heading: "What Apollo detected", verb: "Detected" },
};
const UNRECORDED = { heading: "What started this investigation", verb: "Opened" };

/** The card's heading and the word before its time, from the recorded origin only. */
export function originHeading(origin: CaseOrigin | null | undefined): { heading: string; verb: string } {
  return (origin && ORIGIN[origin]) || UNRECORDED;
}

/** The small picture beside the preview: what kind of material it is. */
export type PreviewIcon = "sms" | "email" | "link" | "call" | "file" | "picture" | "app" | "device" | "item";

export interface SourcePreview {
  /** What the material is, in words ("Message", "Email", "Link"…): read aloud with the picture. */
  kind: string;
  icon: PreviewIcon;
  /** The short summary, one line each: an email's sender and subject, a link, a number. */
  lines: string[];
  /** The same lines in full, never shortened: what the expanded card shows. */
  fullLines: string[];
  /** When an email arrived, as recorded: an ISO time, or the mailbox's own wording. */
  received: string | null;
  /** The material's own text, its line breaks kept. An email's is shown only when the person expands the card, and
   *  without its links (those are on the Evidence tab). */
  body: string | null;
  /** Everything else recorded about the material, shown when the card is expanded (every source type expands).
   *  `time`: the value is a recorded time, shown as a date. */
  details: SourceDetail[];
}

export interface SourceDetail { label: string; value: string; time?: boolean }

const detail = (label: string, value: string | number | null | undefined, time = false): SourceDetail | null => {
  const v = typeof value === "number" ? String(value) : (value ?? "").replace(/\s+/g, " ").trim();
  return v ? { label, value: v, ...(time ? { time } : {}) } : null;
};
/** The type first, then each recorded detail once, leaving out what the summary lines or the text already say. */
const detailsOf = (kind: string, items: (SourceDetail | null)[], shown: string[], body: string | null): SourceDetail[] => {
  const said = [...shown, body ?? ""].join("\n");
  const out = [{ label: "Type", value: kind }, ...items.filter((d): d is SourceDetail => !!d)];
  const seen = new Set<string>();
  return out.filter((d) => {
    const key = `${d.label.toLowerCase()}|${d.value}`;
    if (seen.has(key) || (d.label !== "Type" && said.includes(d.value))) return false;
    seen.add(key);
    return true;
  });
};

const LINK = /\b(?:https?:\/\/|www\.)[^\s<>"'()[\]]+/gi;
/** Text with every web address replaced by "[link]": what an email says, without its links. A full stop or comma
 *  after an address stays with the sentence. */
export function withoutLinks(text: string): string {
  return text.replace(LINK, (url) => `[link]${/[.,;:!?]+$/.exec(url)?.[0] ?? ""}`).replace(/[ \t]{2,}/g, " ");
}

const MAX_LINE = 160;
const clip = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text);
/** A web address on the folded card: shortened in the middle, so where it starts (the website) and where it ends
 *  both stay visible. The full address is on the opened card. */
const ADDRESS = /^(?:[a-z][a-z0-9+.-]*:\/\/|www\.)\S+$|^[^\s/@]+\.[a-z]{2,}(?:[/?#]\S*)?$/i;
export const isAddress = (line: string): boolean => ADDRESS.test(line.trim());
export const ADDRESS_LINE = 56;
export function shortenMiddle(text: string, max = ADDRESS_LINE): string {
  if (text.length <= max) return text;
  const head = Math.ceil((max - 1) * 0.6);
  return `${text.slice(0, head)}…${text.slice(text.length - (max - 1 - head))}`;
}
const shortLine = (line: string) => (ADDRESS.test(line) ? shortenMiddle(line) : clip(line, MAX_LINE));
/** A label that only says what kind of thing it is ("checked link"), never the thing itself. */
const GENERIC_LABEL = /^(?:checked|submitted|url from) (?:link|number|message|url)(?: text)?$/i;
/** Text as it was written: its line breaks kept, runs of spaces and blank lines closed up. */
const asWritten = (text: string) => text.replace(/\r\n?/g, "\n").split("\n").map((l) => l.replace(/[ \t]+/g, " ").trim()).filter(Boolean).join("\n");
/** The one-line parts, each once, and the text itself. `dedupe`: a part the text already holds is left to the text
 *  (an email's sender and subject always stay, since its text is folded away). */
const compose = (head: (string | null | undefined)[], text?: string | null, dedupe = true) => {
  const body = text ? asWritten(text) : "";
  const parts = [...new Set(head.map((l) => (l ?? "").replace(/\s+/g, " ").trim()).filter(Boolean))]
    .filter((l) => !dedupe || !body.includes(clip(l, MAX_LINE).replace(/…$/, ""))).slice(0, 3);
  return { lines: parts.map(shortLine), fullLines: parts, body: body || null };
};

const ICON_OF_KIND: Record<OriginalSourceKind, PreviewIcon> = {
  email: "email", text: "sms", link: "link", website: "link", screenshot: "picture", call: "call", app: "app", file: "file",
  account: "item", device: "device", network: "device",
};
const SHOWN_FIELD = /^(from|sender|number|caller|contact|subject)$/i;

/** Text as written with its paragraphs kept: blank lines between paragraphs stay (one each). */
const asParagraphs = (text: string) => text.replace(/\r\n?/g, "\n").split("\n").map((l) => l.replace(/[ \t]+/g, " ").trim()).join("\n")
  .replace(/\n{3,}/g, "\n\n").trim();
/** An email's summary is its sender and subject only ("Not provided" where not recorded); its text (links removed)
 *  waits behind the expand button. */
const emailPreview = (head: string[], text: string | null | undefined) => {
  const { lines, fullLines } = compose(head, null, false);
  return { lines, fullLines, body: text ? asParagraphs(withoutLinks(text)) || null : null };
};
const TIME_FIELD = /^(received|date|sent|time|captured|when)$/i;

/** The original kept on the device, shortened: an email's sender and subject, a link, and the text as written.
 *  `event`: the case's record, which says whether it is an email and fills in what the kept copy doesn't hold. */
export function previewFromOriginal(src: OriginalSource, hasImage = false, event?: PatrolEvent | null): SourcePreview {
  const view = describeArtefact(src, hasImage);
  const body = view.body ?? null;
  const icon = view.layout === "screenshot" ? "picture" : ICON_OF_KIND[src.kind] ?? "item";
  const recorded = [
    ...view.fields.map((f) => detail(f.label.trim(), f.value, TIME_FIELD.test(f.label.trim()))),
    detail("Link", src.url),
    detail(src.origin === "this_device" ? "Captured on this device" : "Received by ApolloSG", src.capturedAt, true),
  ];
  if (view.layout === "email" || (view.layout !== "screenshot" && isEmailCase(event, src))) {
    const record = emailRecord(event, src);
    const p = emailPreview(emailLines(record), body);
    return { kind: "Email", icon: "email", ...p, received: record.received, details: detailsOf("Email", recorded, [...p.fullLines, record.received ?? ""], null) };
  }
  const url = src.url && !(body ?? "").includes(src.url) ? src.url : null;
  const fields = body || url ? [] : view.fields.filter((f) => !SHOWN_FIELD.test(f.label.trim())).slice(0, 2).map((f) => `${f.label}: ${f.value}`);
  const head = src.kind === "call" ? [view.sender, url, ...fields] : [url, ...fields];
  const c = compose(head, body);
  return { kind: view.title, icon, ...c, received: null, details: detailsOf(view.title, recorded, c.fullLines, c.body) };
}

const EVENT_KIND: Record<string, { kind: string; icon: PreviewIcon }> = {
  message: { kind: "Message", icon: "sms" }, text: { kind: "Message", icon: "sms" }, email: { kind: "Email", icon: "email" },
  link: { kind: "Link", icon: "link" }, website: { kind: "Website", icon: "link" }, known_threat: { kind: "Website", icon: "link" },
  connection: { kind: "Connection", icon: "device" }, network: { kind: "Connection", icon: "device" }, call: { kind: "Call", icon: "call" },
  app: { kind: "App", icon: "app" }, file: { kind: "File", icon: "file" }, screenshot: { kind: "Picture", icon: "picture" },
  account: { kind: "Account alert", icon: "item" }, device: { kind: "Device check", icon: "device" }, protection: { kind: "Protection", icon: "device" },
};

/** The kind of material, as the case recorded it. A file check is named from its file evidence: its case is filed
 *  under the Link Gate's category. */
function eventType(event: PatrolEvent): string {
  return event.evidence_profile?.type === "file" ? "file" : event.source_metadata?.type ?? event.category;
}

/** What the case recorded at intake about its material — the sender, subject, link, number and text — when no
 *  original is kept. */
export function previewFromEvent(event: PatrolEvent): SourcePreview | null {
  const m = event.source_metadata;
  const type = eventType(event);
  const indicator = !m?.url ? (event.local_indicator ?? event.indicator_host) : null;
  const email = isEmailCase(event);
  const record = emailRecord(event, null);
  const { lines, fullLines, body } = email
    ? emailPreview(emailLines(record), m?.preview)
    : compose([m?.url, m?.attachment_names?.[0], m?.preview ? null : indicator], m?.preview);
  if (!lines.length && !body) return null;
  const info = email ? EVENT_KIND.email : EVENT_KIND[type] ?? EVENT_KIND[event.category] ?? { kind: "Item", icon: "item" as const };
  const received = email ? record.received : null;
  const details = detailsOf(info.kind, [
    detail("From", m?.sender), detail("Subject", m?.subject), detail("Reply-to", m?.reply_to), detail("Link", m?.url),
    detail("Website", event.indicator_host ?? event.local_indicator), detail("Attachments", m?.attachment_names?.join(", ")),
    detail("Pictures", m?.image_count), detail("Question asked", m?.user_question), detail("App", m?.provider),
    detail("Received", m?.received_at, true),
  ], [...fullLines, received ?? ""], email ? null : body);
  return { ...info, lines, fullLines, body, received, details };
}

const ITEM_KIND: Record<string, { kind: string; icon: PreviewIcon }> = {
  text: { kind: "Text", icon: "sms" }, url: { kind: "Link", icon: "link" }, image: { kind: "Picture", icon: "picture" },
  document: { kind: "File", icon: "file" }, file: { kind: "File", icon: "file" }, attachment: { kind: "File", icon: "file" },
};

/** The investigation's own evidence list, when nothing else is kept: what kind of material arrived, and its name.
 *  `email`: the case is about an email — it is shown as one, with "Not provided" for what wasn't recorded. */
export function previewFromEvidence(items: EvidenceItem[], email = false): SourcePreview | null {
  const first = items.find((e) => e.origin === "user_submission" || e.origin === "device_observation");
  if (!first) return null;
  if (email) {
    const p = emailPreview(emailLines(emailRecord(null, null)), null);
    return { kind: "Email", icon: "email", ...p, received: null, details: detailsOf("Email", [detail("Collected", first.collectedAt, true)], p.fullLines, null) };
  }
  const info = ITEM_KIND[first.kind] ?? { kind: "Item", icon: "item" as const };
  // The item's name: its file name, or the address or text it was labelled with — never a label that only names its kind.
  const name = first.provenance?.originalFilename ?? (GENERIC_LABEL.test(first.label.trim()) ? null : first.label);
  const c = compose([name]);
  return { ...info, ...c, received: null, details: detailsOf(info.kind, [detail("Collected", first.collectedAt, true)], c.fullLines, c.body) };
}

// ── What Apollo detected: who it came from, what it was, what caught it and why ──

export interface DetectionFact { id: "from" | "type" | "detected_by" | "reason"; label: string; value: string }

const TYPE_LABEL: Record<string, string> = {
  email: "Email", link: "Link", website: "Website", known_threat: "Website", connection: "Connection", network: "Connection",
  call: "Call", app: "App", file: "File", screenshot: "Picture", account: "Account alert", device: "Device check", protection: "Protection",
};

/** The protection that caught it, by the name the app gives it. */
const CAPABILITY_OF: Record<string, GateId> = {
  message: "text", text: "text", email: "email", call: "call", link: "link", website: "site", known_threat: "site",
  connection: "network", network: "network", app: "app", file: "file", device: "device", protection: "device", account: "account",
};

const SCAM_KINDS = new Set(["message", "text", "email", "call"]);

/** Why Apollo opened the case, in a few words, from what it recorded — never worked out from anything else. */
function detectionReason(event: PatrolEvent): string | null {
  const outcome = event.triage_investigation?.outcome;
  if (event.category === "known_threat" || event.enforcement_evidence || event.evidence_provenance === "dns_observation") return "Known threat listing";
  if (outcome === "POSSIBLE_THREAT_IDENTIFIED") return SCAM_KINDS.has(eventType(event)) || SCAM_KINDS.has(event.category) ? "Potential scam pattern" : "Possible threat";
  if (outcome === "LIMITED_UNABLE_TO_DETERMINE") return "Couldn't be fully checked";
  return null;
}

/** The facts under "What Apollo detected": From · Type · Detected by · Reason — each only when the case recorded it. */
export function detectionFacts(event: PatrolEvent, original?: OriginalSource | null): DetectionFact[] {
  const m = event.source_metadata;
  const type = eventType(event);
  const email = isEmailCase(event, original);
  const from = email ? emailRecord(event, original).sender ?? NOT_PROVIDED : m?.sender?.trim()
    || original?.fields?.find((f) => /^(from|sender|number|caller)$/i.test(f.label.trim()))?.value?.trim()
    || (event.category === "call" ? event.local_indicator?.trim() : null);
  const provider = m?.provider?.trim();
  const kind = email ? "Email" : type === "text" || type === "message"
    ? (provider && !/\b(sms|messages?)\b/i.test(provider) ? provider : "SMS")
    : TYPE_LABEL[type] ?? TYPE_LABEL[event.category] ?? null;
  const capability = CAPABILITY_OF[email ? "email" : event.evidence_provenance === "dns_observation" ? "website" : type] ?? CAPABILITY_OF[event.category];
  const by = event.evidence_provenance === "native_protection" ? provider || "Your device's built-in protection"
    : capability ? CAPABILITY_LABELS[capability] : null;
  const facts: (DetectionFact | null)[] = [
    from ? { id: "from", label: "From", value: from } : null,
    kind ? { id: "type", label: "Type", value: kind } : null,
    by ? { id: "detected_by", label: "Detected by", value: by } : null,
    ((reason) => (reason ? { id: "reason" as const, label: "Reason", value: reason } : null))(detectionReason(event)),
  ];
  return facts.filter((f): f is DetectionFact => !!f);
}
