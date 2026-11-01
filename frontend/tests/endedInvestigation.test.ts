/**
 * A check's top card and its Threats record once the investigation is over.
 *  - Call screening keeps the number it checked as the case's original: the card shows a Call with that number,
 *    never an empty "Text" item.
 *  - A record still on the "investigating" placeholder ("sniffing") takes the server's final state, even when that
 *    state ranks no higher (resting).
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { previewFromOriginal } from "../src/domain/caseSourceSummary.ts";
import { mergeLocalAndRemoteEvents } from "../src/domain/eventMerge.ts";
import type { PatrolEvent } from "../src/domain/types.ts";
import type { OriginalSource } from "../src/store/originalSource";

test("a checked number shows as a Call with the number", () => {
  const original: OriginalSource = { kind: "call", fields: [{ label: "Number", value: "+61262161111" }], capturedAt: "2026-10-29T04:19:53.000Z", origin: "this_device" };
  const preview = previewFromOriginal(original);
  assert.equal(preview.icon, "call");
  assert.equal(preview.kind, "Call");
  assert.deepEqual(preview.lines, ["Number: +61262161111"]);
  assert.equal(preview.details[0].value, "Call");
});

test("call-guard hands the checked number to the investigation as its original", () => {
  const src = readFileSync("app/call-guard.tsx", "utf8");
  assert.match(src, /original=\{\{ kind: "call", fields: \[\{ label: "Number", value: result\.number \}\]/);
  const flow = readFileSync("src/components/InvestigationFlow.tsx", "utf8");
  assert.match(flow, /saveOriginalSource\(\[state\.caseData\.id\], originalRef\.current\)/);
});

function event(over: Partial<PatrolEvent>): PatrolEvent {
  return {
    event_id: "case-record", device_id: "dev-1", category: "call", state: "sniffing", status: "active",
    headline: "Apollo is investigating this", what_happened: "Higgins has started an investigation.", why: ["The investigation is still running."],
    what_to_do: "Nothing to do right now.", indicator_host: null, indicator_digest: null, local_indicator: null, verified_block: false,
    adapter_label: "Magnum DI", occurred_at: "2026-10-29T04:19:53.000Z", resolved_at: null, trust_allowed: false,
    investigation_case_id: "case-1", evidence_representation: "privacy_protected_copy", ...over,
  } as PatrolEvent;
}

test("the server's final state replaces a local 'investigating' placeholder", () => {
  const remote = event({ state: "resting", status: "resolved", headline: "No scam indicators found", investigation_completed_at: "2026-10-29T04:19:56.000Z" });
  const { events } = mergeLocalAndRemoteEvents([event({})], [remote]);
  assert.equal(events[0].state, "resting");
  assert.equal(events[0].headline, "No scam indicators found");
  assert.equal(events[0].investigation_completed_at, "2026-10-29T04:19:56.000Z");
});

test("an assessed local state still never drops to a lower server state", () => {
  const { events } = mergeLocalAndRemoteEvents([event({ state: "barking" })], [event({ state: "resting" })]);
  assert.equal(events[0].state, "barking");
});
