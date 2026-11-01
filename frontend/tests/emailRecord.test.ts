// Owner's rule (2026-11-01): Home and the Threat Case show the same email record — that it is an email, its sender,
// subject and received date — and "Not provided" (never "Not captured") where it was genuinely not recorded. An email
// never falls back to the SMS icon.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { detectionFacts, previewFromEvent, previewFromEvidence, previewFromOriginal } from "../src/domain/caseSourceSummary.ts";
import { emailLines, emailRecord, isEmailCase, NOT_PROVIDED } from "../src/domain/emailRecord.ts";
import { enrichMetadata } from "../src/domain/eventMerge.ts";
import { eventBrief, keptIdentifiers } from "../src/domain/homeHeroBrief.ts";
import type { EvidenceItem } from "../src/investigation/types";
import type { OriginalSource } from "../src/store/originalSource";
import type { PatrolEvent } from "../src/domain/types";

const NOW = new Date(2026, 10, 1, 18, 0);
const event = (over: Partial<PatrolEvent>): PatrolEvent => ({
  event_id: "e1", device_id: "d1", category: "email", state: "growling", status: "active", origin: "apollo",
  headline: "x", what_happened: "", why: [], what_to_do: "", indicator_host: null, indicator_digest: null,
  verified_block: false, adapter_label: "Apollo", occurred_at: new Date(2026, 10, 1, 9, 0).toISOString(), resolved_at: null, ...over,
} as PatrolEvent);

test("an email with nothing recorded says Not provided for its sender, subject and received date", () => {
  const p = previewFromEvent(event({ source_metadata: { type: "email", preview: "Click here" } }))!;
  assert.equal(p.icon, "email");
  assert.equal(p.kind, "Email");
  assert.deepEqual(p.lines, [`From: ${NOT_PROVIDED}`, `Subject: ${NOT_PROVIDED}`]);
  assert.equal(p.received, null, "the card then reads \"Received: Not provided\"");
  assert.equal(NOT_PROVIDED, "Not provided");
});

test("an email case filed as text by the server is still shown as an email, never with the SMS icon", () => {
  const filedAsText = event({ category: "email", source_metadata: { type: "text", sender: "a@b.co", preview: "Pay now" } });
  const p = previewFromEvent(filedAsText)!;
  assert.equal(p.icon, "email");
  assert.deepEqual(p.lines, ["From: a@b.co", `Subject: ${NOT_PROVIDED}`]);
  const facts = Object.fromEntries(detectionFacts(filedAsText).map((f) => [f.id, f.value]));
  assert.equal(facts.type, "Email", "never \"SMS\"");
  const keptAsText: OriginalSource = { kind: "text", capturedAt: "2026-11-01T00:00:00Z", origin: "investigation", fields: [{ label: "Subject", value: "Parcel" }], text: "Pay now" };
  assert.equal(previewFromOriginal(keptAsText, false, filedAsText).icon, "email", "a copy kept as text, for an email case");
  const evidence = [{ id: "ev1", origin: "user_submission", kind: "text", label: "checked message", collectedAt: "2026-11-01T00:00:00Z" }] as unknown as EvidenceItem[];
  assert.equal(previewFromEvidence(evidence, isEmailCase(null, null, ["email"]))!.icon, "email", "only the evidence list, from an Email Gate case");
  assert.equal(previewFromEvidence(evidence)!.icon, "sms", "a text message still shows as one");
});

test("an email with no sender recorded says so in its facts", () => {
  const facts = Object.fromEntries(detectionFacts(event({ source_metadata: { type: "email", subject: "Hi" } })).map((f) => [f.id, f.value]));
  assert.equal(facts.from, NOT_PROVIDED);
});

test("Home and the Threat Case read the same record: the kept copy first, then the case", () => {
  const original: OriginalSource = {
    kind: "email", capturedAt: "2026-11-01T00:00:00Z", origin: "this_device",
    fields: [{ label: "Subject", value: "Kept subject" }, { label: "Received", value: new Date(2026, 9, 31, 7, 30).toISOString() }], text: "Body",
  };
  const ev = event({ source_metadata: { type: "email", sender: "case@sender.co", subject: "Case subject" } });
  const record = emailRecord(ev, original);
  assert.deepEqual(record, { sender: "case@sender.co", subject: "Kept subject", received: original.fields![1].value });
  const card = previewFromOriginal(original, false, ev);
  assert.deepEqual(card.lines, emailLines(record));
  assert.equal(card.received, record.received);
  const home = eventBrief(ev, NOW, keptIdentifiers(original));
  assert.match(home.line1, /^Email: \u201CKept subject\u201D from case@sender\.co, /);
  assert.match(home.line2, /^Received: 31 Oct, 7:30 am\. /, "the same received date the Threat Case shows");
});

test("a pasted email's header lines count as its recorded headers", () => {
  const pasted: OriginalSource = { kind: "email", capturedAt: "x", origin: "this_device", text: "From: Bank <alerts@bank-secure.co>\nSubject: Verify now\n\nDear customer" };
  assert.deepEqual(emailRecord(null, pasted), { sender: "Bank <alerts@bank-secure.co>", subject: "Verify now", received: null });
});

test("syncing fills in identifiers this phone didn't record, and never overwrites the ones it did", () => {
  assert.deepEqual(enrichMetadata({ type: "email", sender: "phone@x.co", subject: null }, { type: "text", sender: "server@x.co", subject: "Server subject", preview: "text" }),
    { type: "email", sender: "phone@x.co", subject: "Server subject", preview: "text" });
  assert.deepEqual(enrichMetadata(null, { type: "email", sender: "s@x.co" }), { type: "email", sender: "s@x.co" });
});

test("no screen says \"not captured\" for a missing sender, account or date", () => {
  for (const path of ["src/components/evidence/ArtefactLayouts.tsx", "src/domain/evidencePackHtml.ts", "src/components/report/SourceSummaryCard.tsx", "src/domain/caseSourceSummary.ts", "src/domain/homeHeroBrief.ts"]) {
    const code = readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
    assert.doesNotMatch(code, /not captured|not recorded"/i, path);
  }
});
