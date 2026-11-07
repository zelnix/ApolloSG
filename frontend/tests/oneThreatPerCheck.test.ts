// One check, one entry in Threats. When TC Hawkeye answers before this device's own record reaches the
// server, the server may already have filed a twin for the same check (its own id, naming this device's
// record as client_submission_id). The merge folds the twin into the device's record.
import { test } from "node:test";
import assert from "node:assert/strict";

import { mergeLocalAndRemoteEvents } from "../src/domain/eventMerge.ts";
import type { PatrolEvent } from "../src/domain/types.ts";

function event(over: Partial<PatrolEvent>): PatrolEvent {
  return {
    event_id: "device-record", device_id: "dev-1", category: "message", state: "barking", status: "active",
    headline: "Hi Mum scam", what_happened: "It says it's from a family member and asks for money.", why: ["Family new-number pattern"],
    what_to_do: "Don't send money.", indicator_host: null, indicator_digest: null, local_indicator: null, verified_block: false,
    adapter_label: "Apollo", occurred_at: "2026-10-24T03:19:00.000Z", resolved_at: null, trust_allowed: false,
    evidence_provenance: "local_device", ...over,
  } as PatrolEvent;
}

const device = event({ investigation_case_id: "case-1" });
const twin = event({
  event_id: "server-twin", client_submission_id: "device-record", evidence_provenance: "device_submission",
  processing_source: "apollosg_servers", evidence_representation: "privacy_protected_copy",
  headline: "This matches a known scam", investigation_case_id: "case-1", investigation_completed_at: "2026-10-24T03:19:05.000Z",
});

test("a server twin of this device's record is folded in, not shown twice", () => {
  const { events, superseded } = mergeLocalAndRemoteEvents([device], [twin]);
  assert.deepEqual(events.map((e) => e.event_id), ["device-record"]);
  assert.deepEqual(superseded, ["server-twin"]);
  assert.equal(events[0].headline, "Hi Mum scam", "the device's own detail is kept");
  assert.equal(events[0].investigation_completed_at, "2026-10-24T03:19:05.000Z", "what only the twin knew is kept");
});

test("both copies on the server still give one entry", () => {
  const { events } = mergeLocalAndRemoteEvents([device], [twin, { ...device, evidence_representation: "privacy_summary" }]);
  assert.deepEqual(events.map((e) => e.event_id), ["device-record"]);
});

test("a twin already stored on this device is dropped on the next merge", () => {
  const { events } = mergeLocalAndRemoteEvents([device, twin], []);
  assert.deepEqual(events.map((e) => e.event_id), ["device-record"]);
  assert.equal(events[0].investigation_completed_at, twin.investigation_completed_at);
});

test("separate checks stay separate", () => {
  const other = event({ event_id: "other-check", investigation_case_id: "case-2" });
  const { events } = mergeLocalAndRemoteEvents([device, other], []);
  assert.equal(events.length, 2);
});
