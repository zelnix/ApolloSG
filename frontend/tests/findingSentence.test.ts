import assert from "node:assert/strict";
import test from "node:test";

import { findingSentence } from "../src/domain/higginsHomeVoice.ts";
import type { PatrolEvent } from "../src/domain/types.ts";

function ev(partial: Partial<PatrolEvent>): PatrolEvent {
  return {
    event_id: "e1", device_id: "d1", category: "device", state: "barking", status: "active",
    headline: "", what_happened: "", why: [], what_to_do: "",
    indicator_host: null, indicator_digest: null, verified_block: false, adapter_label: "test",
    evidence_provenance: "local_device",
    occurred_at: "2026-06-10T09:00:00.000Z", resolved_at: null,
    ...partial,
  } as PatrolEvent;
}

test("picks the sentence that states what was found and drops the instructions", () => {
  const stated = findingSentence(ev({
    what_happened: 'This is example data shown in the web preview so you can see how an investigation looks. In it, Apollo found one active management profile, "Acme IT Mobile Device Management" (com.acme.mdm.agent), installed 15 Oct 2026. On Android it is listed under Settings → Security → Device admin apps; on iPhone under Settings → General → VPN & Device Management.',
  }));
  assert.equal(stated, 'Apollo found one active management profile, "Acme IT Mobile Device Management" (com.acme.mdm.agent), installed 15 Oct 2026.');
});

test("instruction-only text yields nothing rather than an instruction in the hero", () => {
  assert.equal(findingSentence(ev({ what_happened: "Open Settings → General and remove the profile." })), null);
});

test("evidence that isn't on this device is never summarised", () => {
  assert.equal(findingSentence(ev({ evidence_representation: "privacy_summary", what_happened: "Apollo found something." })), null);
});

test("a very long sentence is kept whole, never cut short", () => {
  const long = `Apollo found ${"a very suspicious thing ".repeat(20)}somewhere.`;
  assert.equal(findingSentence(ev({ what_happened: long })), long);
});
