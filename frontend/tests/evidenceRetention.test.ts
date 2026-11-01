// Owner's rules (2026-11-01), the phone's side: a saved original is enriched by later headers without losing what it
// holds; the server's copy becomes this phone's own, is read back, and only a complete copy is confirmed.
import assert from "node:assert/strict";
import { test } from "node:test";

import { enrichOriginal, sameOriginal } from "../src/domain/originalMerge.ts";
import { missingParts, originalFromPickup, pickupIdentifiers, savedReport, type PickupOriginal } from "../src/domain/pickupCheck.ts";
import type { OriginalSource } from "../src/store/originalSource";

const PASTED: OriginalSource = {
  kind: "text", capturedAt: "2026-10-30T09:00:00.000Z", origin: "this_device", fields: [{ label: "From", value: "" }],
  text: "Dear customer, your parcel is held. Pay $2.99 at https://auspost-redeliver.top/pay",
};
const HEADERS: OriginalSource = {
  kind: "email", capturedAt: "2026-11-01T09:00:00.000Z", origin: "investigation",
  fields: [{ label: "From", value: "AusPost <track@auspost-help.co>" }, { label: "Subject", value: "Your parcel is held" }, { label: "Received", value: "2026-10-30T08:55:00.000Z" }],
  text: "A different copy of the text", url: "https://auspost-redeliver.top/pay",
};

test("later headers fill in an incomplete saved copy; its own text, time and origin stay exactly as they were", () => {
  const next = enrichOriginal(PASTED, HEADERS);
  assert.equal(next.text, PASTED.text, "the original evidence is preserved");
  assert.equal(next.capturedAt, PASTED.capturedAt);
  assert.equal(next.origin, "this_device");
  assert.equal(next.kind, "email", "headers of an email make a copy saved as plain text an email");
  assert.deepEqual(next.fields, [
    { label: "From", value: "AusPost <track@auspost-help.co>" }, // an empty header is filled in
    { label: "Subject", value: "Your parcel is held" }, { label: "Received", value: "2026-10-30T08:55:00.000Z" },
  ]);
  assert.equal(next.url, HEADERS.url, "a link the copy didn't hold is added");
});

test("a header the saved copy already holds is never overwritten; attachments add up", () => {
  const kept: OriginalSource = { ...HEADERS, fields: [{ label: "From", value: "first@x.co" }, { label: "Attachment", value: "a.pdf" }] };
  const next = enrichOriginal(kept, { ...HEADERS, fields: [{ label: "from", value: "other@y.co" }, { label: "Attachment", value: "a.pdf" }, { label: "Attachment", value: "b.zip" }] });
  assert.deepEqual(next.fields, [{ label: "From", value: "first@x.co" }, { label: "Attachment", value: "a.pdf" }, { label: "Attachment", value: "b.zip" }]);
  assert.ok(sameOriginal(enrichOriginal(next, next), next), "the same supply again changes nothing");
});

const ORIGINALS: PickupOriginal[] = [
  { evidenceId: "ev1", kind: "text", body: "Your parcel is held. Pay now." },
  { evidenceId: "ev2", kind: "url", body: "https://auspost-redeliver.top/pay" },
];
const SOURCE = { type: "text" as const, sender: "track@auspost-help.co", subject: "Your parcel is held", received_at: "2026-10-30T08:55:00+00:00", provider: "Gmail" };

test("what the server kept becomes this phone's original, with the received time exactly as recorded", () => {
  const input = originalFromPickup(ORIGINALS, SOURCE, { email: true, capturedAt: "2026-10-30T09:00:00Z" })!;
  assert.equal(input.kind, "email", "an email case is kept as an email even when the server filed its text as \"text\"");
  assert.equal(input.text, "Your parcel is held. Pay now.");
  assert.equal(input.url, "https://auspost-redeliver.top/pay");
  assert.deepEqual(input.fields?.map((f) => [f.label, f.value]), [["From", "track@auspost-help.co"], ["Subject", "Your parcel is held"], ["Received", "2026-10-30T08:55:00+00:00"], ["Mailbox", "Gmail"]]);
  assert.equal(originalFromPickup([], {}, { email: false, capturedAt: "x" }), null, "nothing kept, nothing saved");
});

test("the server's identifiers come first; this phone's record fills in the rest", () => {
  assert.deepEqual(pickupIdentifiers({ subject: "Server subject" }, { type: "email", subject: "Phone subject", sender: "a@b.co" }),
    { type: "email", sender: "a@b.co", subject: "Server subject" });
});

test("only a complete copy, read back from the phone, is confirmed — the same check the server makes", () => {
  const held = { originals: ORIGINALS, source: SOURCE };
  const saved = enrichOriginal(PASTED, { ...originalFromPickup(ORIGINALS, SOURCE, { email: true, capturedAt: "x" })!, capturedAt: "x", origin: "investigation" });
  const report = savedReport(saved, ORIGINALS, true);
  assert.deepEqual(report, { text: true, link: true, result: true, headers: ["From", "Subject", "Received", "Mailbox"] });
  assert.deepEqual(missingParts(report, held, true), []);
  assert.deepEqual(missingParts(savedReport(null, ORIGINALS, false), held, true), ["the text", "the link", "From", "Subject", "Received", "the result"]);
  assert.deepEqual(missingParts(savedReport({ text: "Pay at https://auspost-redeliver.top/pay", fields: [] }, ORIGINALS, false), { originals: ORIGINALS, source: {} }, false), [],
    "a link inside the saved text counts as saved");
});
