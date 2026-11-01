// The phone's side of the handshake that lets ApolloSG's server delete its copy (backend services/device_pickup.py):
// what the server kept for this phone becomes this phone's own saved original, the phone reads that back from its own
// storage, and only a complete copy is confirmed. Pure: no React, no storage, unit-tested in node.
import type { OriginalSource, OriginalSourceInput, OriginalSourceKind } from "../store/originalSource";
import type { SourceMetadata } from "./types";

export interface PickupOriginal { evidenceId: string; kind: "text" | "url"; body: string }
/** The identifiers ApolloSG recorded at intake, as the server kept them for this phone. */
export type PickupSource = Partial<Pick<SourceMetadata, "type" | "sender" | "reply_to" | "subject" | "received_at" | "provider" | "attachment_names" | "url">>;
/** What this phone says it saved and checked — which parts, never their content. */
export interface SavedParts { text: boolean; link: boolean; result: boolean; headers: string[] }

/** The label each recorded identifier is saved under (the server checks the same labels). */
export const HEADER_LABELS: Record<"sender" | "reply_to" | "subject" | "received_at", string> = {
  sender: "From", reply_to: "Reply-to", subject: "Subject", received_at: "Received",
};
const KINDS: ReadonlySet<string> = new Set<OriginalSourceKind>(["email", "text", "link", "website", "screenshot", "call", "app", "file", "account", "device", "network"]);
const value = (v: string | null | undefined) => (v ?? "").trim() || null;

/** The identifiers a case recorded, with the server's copy first and this phone's record filling the rest. */
export function pickupIdentifiers(server: PickupSource | null | undefined, local: SourceMetadata | null | undefined): PickupSource {
  const out: PickupSource = {};
  for (const k of ["type", "sender", "reply_to", "subject", "received_at", "provider", "url"] as const) {
    const v = value(server?.[k] as string | null | undefined) ?? value(local?.[k] as string | null | undefined);
    if (v) (out as Record<string, string>)[k] = v;
  }
  const names = server?.attachment_names?.length ? server.attachment_names : local?.attachment_names;
  if (names?.length) out.attachment_names = names;
  return out;
}

/** The original this phone keeps from what the server kept for it, or null when it holds nothing to keep. */
export function originalFromPickup(originals: PickupOriginal[], source: PickupSource, opts: { email: boolean; capturedAt: string }): OriginalSourceInput | null {
  const fields = [
    source.sender ? { label: HEADER_LABELS.sender, value: source.sender } : null,
    source.reply_to ? { label: HEADER_LABELS.reply_to, value: source.reply_to } : null,
    source.subject ? { label: HEADER_LABELS.subject, value: source.subject } : null,
    // The time exactly as recorded (an ISO time), so every screen shows the same date.
    source.received_at ? { label: HEADER_LABELS.received_at, value: source.received_at } : null,
    source.provider ? { label: "Mailbox", value: source.provider } : null,
    ...(source.attachment_names ?? []).map((name) => ({ label: "Attachment", value: name })),
  ].filter((f): f is { label: string; value: string } => !!f);
  const texts = originals.filter((o) => o.kind === "text").map((o) => o.body);
  const urls = originals.filter((o) => o.kind === "url").map((o) => o.body);
  if (!texts.length && !urls.length && !fields.length) return null;
  const kind: OriginalSourceKind = opts.email ? "email"
    : source.type && KINDS.has(source.type) ? source.type as OriginalSourceKind : urls.length && !texts.length ? "link" : "text";
  return {
    kind, fields, text: texts.length ? texts.join("\n\n") : null, url: urls.length ? urls.join("\n") : null,
    origin: "investigation", capturedAt: opts.capturedAt,
  };
}

/** What this phone holds, read back from its own storage, of what the server kept for it. */
export function savedReport(local: Pick<OriginalSource, "fields" | "text" | "url"> | null, originals: PickupOriginal[], resultSaved: boolean): SavedParts {
  const urls = originals.filter((o) => o.kind === "url").map((o) => o.body.trim());
  return {
    text: !!local?.text?.trim(),
    link: !!local?.url?.trim() || (urls.length > 0 && urls.every((u) => (local?.text ?? "").includes(u))),
    result: resultSaved,
    headers: [...new Set((local?.fields ?? []).filter((f) => f.value?.trim()).map((f) => f.label.trim()))],
  };
}

/** What is still missing from this phone's copy — the same check the server makes before it deletes its own. */
export function missingParts(report: SavedParts, held: { originals: PickupOriginal[]; source: PickupSource }, needsResult: boolean): string[] {
  const out: string[] = [];
  if (held.originals.some((o) => o.kind === "text") && !report.text) out.push("the text");
  if (held.originals.some((o) => o.kind === "url") && !report.link) out.push("the link");
  const have = new Set(report.headers.map((h) => h.toLowerCase()));
  for (const [k, label] of Object.entries(HEADER_LABELS)) {
    if (held.source[k as keyof typeof HEADER_LABELS] && !have.has(label.toLowerCase())) out.push(label);
  }
  if (needsResult && !report.result) out.push("the result");
  return out;
}
