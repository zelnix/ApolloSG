// "Send to family": only the short summary goes, and a website can't be tapped in the shared text.
import { test } from "node:test";
import assert from "node:assert/strict";

import { involvedIn, summaryText, summaryWire, type FamilySummary } from "../src/domain/familySummary.ts";

const auspost: FamilySummary = {
  eventId: "evt-12345678", state: "barking", result: "Confirmed scam or threat",
  headline: "Apollo's blocklist lists testsafebrowsing.appspot.com as a phishing site.",
  whatHappened: "Apollo's blocklist and Google Safe Browsing list testsafebrowsing.appspot.com as a phishing site. Don't act on it.",
  whatToDo: "Don't open the link.", involved: { label: "Website", value: "testsafebrowsing.appspot.com" },
  caseRef: "TC-2026-F843E", occurredAt: "2026-10-25T06:17:00Z",
};

test("the shared text has the result, what happened, what to do and an untappable website", () => {
  const text = summaryText(auspost, "Oct 25, 2026, 6:17 AM");
  assert.match(text, /^ApolloSG: a threat on my phone\nResult: Confirmed scam or threat\n/);
  assert.match(text, /What to do: Don't open the link\./);
  assert.match(text, /Website involved: testsafebrowsing\[\.\]appspot\[\.\]com \(written so it can't be tapped\)/);
  assert.match(text, /Case TC-2026-F843E · Oct 25, 2026, 6:17 AM/);
  assert.match(text, /The original message, its links and pictures stay on my phone\.$/);
});

test("a call shares its number; a website shares only its address", () => {
  assert.deepEqual(involvedIn({ category: "call", local_indicator: "+61 400 000 000", indicator_host: null }), { label: "Number", value: "+61 400 000 000" });
  assert.deepEqual(involvedIn({ category: "message", indicator_host: "scam.example" }), { label: "Website", value: "scam.example" });
  assert.equal(involvedIn({ category: "device" }), null);
  assert.match(summaryText({ ...auspost, involved: { label: "Number", value: "+61 400 000 000" } }, "now"), /Number involved: \+61 400 000 000\n/);
});

test("the wire carries only the summary fields, each whole", () => {
  const long = { ...auspost, whatHappened: `${"Apollo found a lookalike address. ".repeat(40)}Don't act on it.`, whatToDo: "Don't open the link. ".repeat(30).trim() };
  const wire = summaryWire(long);
  assert.equal(wire.what_happened, long.whatHappened);
  assert.equal(wire.what_to_do, long.whatToDo);
  assert.deepEqual(Object.keys(summaryWire(auspost)).sort(),
    ["case_ref", "event_id", "headline", "involved", "involved_label", "occurred_at", "result", "state", "what_happened", "what_to_do"]);
});
