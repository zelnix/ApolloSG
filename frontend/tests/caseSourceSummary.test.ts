// The case's top card: an email shows only who sent it, its subject and when it arrived; its text waits behind the
// expand button, without its links. Other material shows its own text.
import assert from "node:assert/strict";
import { test } from "node:test";

import { detectionFacts, originHeading, previewFromEvent, previewFromEvidence, previewFromOriginal, shortenMiddle, withoutLinks } from "../src/domain/caseSourceSummary.ts";
import type { EvidenceItem } from "../src/investigation/types";
import type { OriginalSource } from "../src/store/originalSource";
import type { PatrolEvent } from "../src/domain/types";

const EMAIL: OriginalSource = {
  kind: "email", capturedAt: "2026-10-28T09:00:00.000Z", origin: "this_device",
  fields: [
    { label: "From", value: "security@commbank-alerts.co" },
    { label: "Subject", value: "URGENT: unusual sign-in detected" },
    { label: "Received", value: "2026-10-28T08:55:00.000Z" },
  ],
  text: "Dear Customer,\n\nVerify now: http://commbank-secure-verify.co/netbank/login\n\nOr visit www.example-login.co today.\n\nCommBank Security Team",
};

test("an email's summary is From and Subject, with the date it was received", () => {
  const p = previewFromOriginal(EMAIL);
  assert.equal(p.icon, "email");
  assert.deepEqual(p.lines, ["From: security@commbank-alerts.co", "Subject: URGENT: unusual sign-in detected"]);
  assert.equal(p.received, "2026-10-28T08:55:00.000Z");
});

test("an email's full text keeps its words and line breaks but none of its links", () => {
  const body = previewFromOriginal(EMAIL).body ?? "";
  assert.ok(body.startsWith("Dear Customer,\n\nVerify now: [link]"));
  assert.ok(body.includes("Or visit [link] today."));
  assert.ok(!/https?:\/\/|www\./.test(body));
  assert.ok(body.endsWith("CommBank Security Team"));
});

test("an email with no recorded arrival time says so by having none", () => {
  const p = previewFromOriginal({ ...EMAIL, fields: EMAIL.fields!.slice(0, 2) });
  assert.equal(p.received, null);
});

test("an email recorded at intake (no original kept) is summarised the same way", () => {
  const event = {
    event_id: "e1", category: "email", state: "growling",
    source_metadata: { type: "email", sender: "a@b.co", subject: "Hello", url: "https://b.co/x", received_at: "2026-10-28T08:00:00Z", preview: "Click https://b.co/x now" },
  } as unknown as PatrolEvent;
  const p = previewFromEvent(event)!;
  assert.deepEqual(p.lines, ["From: a@b.co", "Subject: Hello"]);
  assert.equal(p.received, "2026-10-28T08:00:00Z");
  assert.equal(p.body, "Click [link] now");
});

test("a text message shows its own words, links and all", () => {
  const p = previewFromOriginal({ kind: "text", capturedAt: "2026-10-28T09:00:00.000Z", origin: "this_device", fields: [], text: "Your parcel is waiting: https://auspost-track.co/x" });
  assert.deepEqual(p.lines, []);
  assert.equal(p.body, "Your parcel is waiting: https://auspost-track.co/x");
  assert.equal(p.received, null);
});

test("withoutLinks replaces web addresses only", () => {
  assert.equal(withoutLinks("Call 13 22 21 or see https://x.co/a?b=1."), "Call 13 22 21 or see [link].");
  assert.equal(withoutLinks("Email me at jo@example.com"), "Email me at jo@example.com");
});

test("every source type has more to show when its card is opened: its lines in full and what else was recorded", () => {
  const question = "I joined a free wifi called 'Airport_Free_WiFi' at the shops and afterwards my banking app asked me to sign in again with my card number and PIN, which it never does";
  const typed = previewFromEvent({ event_id: "e2", category: "message", state: "sniffing",
    source_metadata: { type: "text", url: `https://example.top/${"x".repeat(200)}`, user_question: question } } as unknown as PatrolEvent)!;
  assert.ok(typed.lines[0].includes("…") && !typed.fullLines[0].includes("…"));          // folded: shortened; open: in full
  assert.deepEqual(typed.details.map((d) => d.label), ["Type", "Question asked"]);       // the link is already a line
  assert.equal(typed.details[1].value, question);
  const sms = previewFromOriginal({ kind: "text", capturedAt: "2026-10-28T09:00:00.000Z", origin: "this_device", fields: [{ label: "From", value: "0419 841 238" }], text: "Rebates drop next week. Reply YES." });
  assert.deepEqual(sms.details.map((d) => [d.label, d.value]), [["Type", sms.kind], ["From", "0419 841 238"], ["Captured on this device", "2026-10-28T09:00:00.000Z"]]);
  assert.equal(sms.details[2].time, true);
  const email = previewFromOriginal(EMAIL);
  assert.ok(!email.details.some((d) => /^(From|Subject|Received)$/.test(d.label)));      // already in the summary
});

const LONG = "https://commbank-secure-login-verify.xyz/netbank/account/verify/identity?session=abc123&step=2";

test("a link case's top card shows the web address itself, shortened in the middle; opened, it shows in full", () => {
  const p = previewFromOriginal({ kind: "link", url: LONG, capturedAt: "2026-10-28T09:00:00.000Z", origin: "this_device" });
  assert.equal(p.icon, "link");
  assert.equal(p.lines.length, 1);
  assert.ok(p.lines[0].startsWith("https://commbank-secure-login"), p.lines[0]);
  assert.ok(p.lines[0].endsWith("step=2"), p.lines[0]);
  assert.ok(p.lines[0].includes("…") && p.lines[0].length <= 56);
  assert.deepEqual(p.fullLines, [LONG]);
  assert.equal(shortenMiddle("https://x.co/a"), "https://x.co/a");
});

test("a link case with only its evidence list names the address, never the label 'checked link'", () => {
  const item = (label: string) => ({ id: "e1", kind: "url", origin: "user_submission", parentId: null, label, provenance: null }) as unknown as EvidenceItem;
  const named = previewFromEvidence([item(shortenMiddle(LONG, 80))])!;
  assert.equal(named.kind, "Link");
  assert.ok(named.lines[0].startsWith("https://commbank-secure-login"));
  assert.deepEqual(previewFromEvidence([item("checked link")])!.lines, []);
  assert.deepEqual(previewFromEvidence([item("Submitted message text")])!.lines, []);
});

// ── originHeading: older cases with no recorded origin ──────────────────────

test("originHeading returns 'What started this investigation' when no origin was recorded", () => {
  const fromNull = originHeading(null);
  assert.equal(fromNull.heading, "What started this investigation");
  assert.equal(fromNull.verb, "Opened");
  // undefined is the same: the field simply wasn't set on the case.
  const fromUndefined = originHeading(undefined);
  assert.equal(fromUndefined.heading, "What started this investigation");
  assert.equal(fromUndefined.verb, "Opened");
});

test("originHeading returns the right heading for user-submitted and Apollo-detected cases", () => {
  assert.deepEqual(originHeading("user"), { heading: "What you submitted", verb: "Submitted" });
  assert.deepEqual(originHeading("apollo"), { heading: "What Apollo detected", verb: "Detected" });
});

// ── detectionFacts: older cases with limited or no metadata ──────────────────

test("detectionFacts omits 'From' and 'Reason' for an older case with no sender and no triage outcome", () => {
  // An older case with no source_metadata, no triage_investigation, no evidence_provenance.
  // A message-category event still carries "Type: SMS" and "Detected by" from the capability map — those are always
  // derived from the category, not from optional metadata. But "From" and "Reason" are absent.
  const bare = {
    event_id: "e-old", category: "message", state: "sniffing",
    source_metadata: undefined, triage_investigation: undefined, evidence_provenance: undefined,
  } as unknown as PatrolEvent;
  const facts = detectionFacts(bare);
  assert.ok(!facts.some((f) => f.id === "from"), "no sender → no 'From' fact");
  assert.ok(!facts.some((f) => f.id === "reason"), "no triage outcome → no 'Reason' fact");
  // "Type" and "Detected by" still appear because they're derived from the event's category.
  assert.ok(facts.some((f) => f.id === "type"), "type is inferred from category");
  assert.ok(facts.some((f) => f.id === "detected_by"), "detected-by is inferred from category");
});

test("detectionFacts gracefully shows only what the event actually carries", () => {
  // A case that has a sender: "From" appears alongside type and detected-by.
  const withSender = {
    event_id: "e2", category: "message", state: "growling",
    source_metadata: { sender: "0412 345 678" },
  } as unknown as PatrolEvent;
  const facts = detectionFacts(withSender);
  assert.ok(facts.some((f) => f.id === "from" && f.value === "0412 345 678"), "sender is shown");
  assert.ok(facts.some((f) => f.id === "type"), "type is inferred");
  // A case with no recognisable category has no "detected by" or "type".
  const unknownCategory = {
    event_id: "e3", category: "unknown_future_type", state: "sniffing",
    source_metadata: undefined,
  } as unknown as PatrolEvent;
  const unknownFacts = detectionFacts(unknownCategory);
  assert.ok(!unknownFacts.some((f) => f.id === "detected_by"), "unknown category → no detected-by");
  assert.ok(!unknownFacts.some((f) => f.id === "type"), "unknown category → no type");
  assert.equal(unknownFacts.length, 0, "a completely unrecognised event carries no detection facts");
});

