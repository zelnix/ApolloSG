// A finished investigation must become the case's own content — specifics, not placeholders.
// Run: cd /app/frontend && node --test tests/investigationCaseUpdate.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { caseResult } from "../src/domain/caseBriefing.ts";
import { bodyFrom, headlineFrom, investigationPatch } from "../src/domain/investigationCaseUpdate.ts";
import { STATUS_LABELS, isSimulated, settledBy, threatCaseStatus } from "../src/domain/threatCase.ts";

const placeholder = {
  event_id: "ev1", device_id: "d1", category: "message", state: "sniffing", status: "active",
  headline: "Apollo is investigating this",
  what_happened: "Higgins has started an investigation. Nothing has been established yet.",
  why: ["The investigation is still running."],
  what_to_do: "Nothing to do right now. Higgins will tell you as soon as the investigation finishes.",
  indicator_host: null, indicator_digest: null, verified_block: false, adapter_label: "Magnum DI investigation",
  occurred_at: "2026-10-21T03:50:11Z", resolved_at: null, trust_allowed: false, claimed_brand: null, scenario: null,
  investigation_case_id: "case-1", evidence_provenance: "device_submission", processing_source: "apollosg_servers",
  evidence_representation: "privacy_protected_copy",
} as never;

const investigation = (over: Record<string, unknown> = {}) => ({
  caseId: "case-1", gates: ["text"], status: "complete", createdAt: "2026-10-21T03:50:11Z",
  completedAt: "2026-10-21T03:50:41Z", question: "Is this a scam?", sources: [], turns: [], evidenceItems: [],
  patrolEventId: null, committedAt: "2026-10-21T03:50:42Z",
  response: {
    revision: 1,
    overview: "This looks like a CommBank impersonation attempt. The link goes to commbank-cancel.co.",
    explanationMarkdown: "", assessment: "concern_found", attention: "action_needed",
    attentionReason: "The link is not CommBank's domain.",
    findings: [
      { id: "f1", text: "The content presents itself as CommBank but the link goes to commbank-cancel.co.", basis: "observation", confidence: "high", evidenceIds: ["EV-1"], sourceIds: [] },
      { id: "f2", text: "It asks for your NetBank password.", basis: "observation", confidence: "high", evidenceIds: ["EV-1"], sourceIds: [] },
    ],
    uncertainties: ["Whether commbank-cancel.co is live was not checked."],
    scope: "Examined the submitted message.", sourceIds: [], remainingEvidenceIds: [],
    actions: [{ id: "a1", kind: "instruction", label: "Don't open the link", instruction: "Do not open commbank-cancel.co and do not enter any details on it.", capabilityId: null, executionDescriptorId: null, requiresUserGesture: false, sourceIds: [], desiredField: null, desiredValue: null }],
    recommendedActionId: "a1", question: null, completion: "complete",
    ...over,
  },
}) as never;

test("the placeholder is replaced by the actual findings, conclusion and next step", () => {
  const patched = investigationPatch(placeholder, investigation())!;
  assert.ok(patched);
  assert.equal(patched.headline, "This looks like a CommBank impersonation attempt.");
  assert.match(patched.what_happened!, /commbank-cancel\.co/);
  assert.deepEqual(patched.why, [
    "The content presents itself as CommBank but the link goes to commbank-cancel.co.",
    "It asks for your NetBank password.",
  ]);
  assert.equal(patched.what_to_do, "Do not open commbank-cancel.co and do not enter any details on it.");
  assert.equal(patched.state, "barking");
  assert.equal(patched.status, "active");
  // The result is now held in full here; what supplied the evidence is unchanged by the investigation.
  assert.equal(patched.evidence_provenance, "device_submission");
  assert.equal(patched.evidence_representation, "full_record");
  // A placeholder stored before the separated model is read into it: never "server_projected" again.
  const legacy = investigationPatch({ ...(placeholder as object), evidence_provenance: "server_projected", processing_source: undefined, evidence_representation: undefined } as never, investigation())!;
  assert.equal(legacy.evidence_provenance, "device_submission");
  assert.equal(legacy.processing_source, "apollosg_servers");
  assert.equal(legacy.evidence_representation, "full_record");
});

test("a clean investigation closes the case and says nothing needs doing", () => {
  const clean = investigation({
    overview: "Nothing in this message asks for money, credentials or urgent action.",
    assessment: "no_concern_found_within_scope", attention: "none", attentionReason: null,
    findings: [{ id: "f1", text: "The message is a delivery notice with no link and no request.", basis: "observation", confidence: "medium", evidenceIds: ["EV-1"], sourceIds: [] }],
    actions: [], recommendedActionId: null,
  });
  const patched = investigationPatch(placeholder, clean)!;
  assert.equal(patched.state, "resting");
  assert.equal(patched.status, "resolved");
  assert.equal(patched.resolved_at, "2026-10-21T03:50:42Z");
  assert.match(patched.what_to_do!, /Nothing to do/);
});

test("nothing is written when there is no stored response or nothing changed", () => {
  assert.equal(investigationPatch(placeholder, null), null);
  const patched = investigationPatch(placeholder, investigation())!;
  assert.equal(investigationPatch(patched, investigation()), null);
});

test("the case's severity is the case result's, the same one the Findings Brief shows", () => {
  const cases: [string, string, string][] = [
    ["concern_found", "urgent", "barking"],
    ["concern_found", "review", "growling"],
    ["uncertain", "review", "growling"],
    ["no_concern_found_within_scope", "none", "resting"],
  ];
  for (const [assessment, attention, expected] of cases) {
    const inv = investigation({ assessment, attention });
    const patched = investigationPatch(placeholder, inv)!;
    assert.equal(patched.state, expected);
    assert.equal(patched.state, caseResult((inv as { response: never }).response).severity);
  }
});

test("the headline is the first real sentence, never a category name", () => {
  assert.equal(headlineFrom("This is a Linkt toll scam. It asks for your card number."), "This is a Linkt toll scam.");
  assert.equal(headlineFrom("  A single statement with no full stop  "), "A single statement with no full stop");
});

test("the body never repeats the headline sentence", () => {
  const overview = "This looks like an ING impersonation attempt. Don't act on it until you've checked with ING directly.";
  assert.equal(bodyFrom(overview), "Don't act on it until you've checked with ING directly.");
  // A one-sentence conclusion still has to say something.
  assert.equal(bodyFrom("Nothing here needs action."), "Nothing here needs action.");
  const patched = investigationPatch(placeholder, investigation())!;
  assert.ok(!patched.what_happened!.startsWith(patched.headline));
});

test("the case stops saying 'Investigating' once Magnum DI has answered", () => {
  // Still running: the device has no committed answer yet.
  assert.equal(threatCaseStatus(placeholder), "investigating");

  const answered = investigationPatch(placeholder, investigation())!;
  assert.equal(answered.investigation_completed_at, "2026-10-21T03:50:42Z");
  // The pill now reports what the investigation found, not that it is still looking.
  assert.equal(threatCaseStatus(answered), "attention");
  assert.equal(STATUS_LABELS[threatCaseStatus(answered)], "Needs you");

  // Nothing found: the case closes as "No threat".
  const clear = investigationPatch(placeholder, investigation({
    assessment: "no_concern_found_within_scope", attention: "none", findings: [],
    overview: "Nothing in this needs action.",
  }))!;
  assert.equal(threatCaseStatus(clear), "no_threat");
});

test("a finished case records who settled it, for the Threats list badge — never guessed", () => {
  const flyby = investigationPatch(placeholder, { ...(investigation() as object), answeredBy: "tc_flyby_kb" } as never)!;
  assert.equal(flyby.investigation_answered_by, "tc_flyby_kb");
  assert.equal(settledBy(flyby), "TC FlyBy");
  assert.equal(settledBy(investigationPatch(placeholder, { ...(investigation() as object), answeredBy: "magnum_di" } as never)!), "Magnum DI");
  assert.equal(settledBy(investigationPatch(placeholder, investigation())!), null, "not recorded: no badge");
  assert.equal(settledBy(placeholder), null, "still investigating: no badge");
  // A case patched before the record existed picks it up once the stored result has it.
  const before = investigationPatch(placeholder, investigation())!;
  assert.equal(investigationPatch(before, { ...(investigation() as object), answeredBy: "tc_flyby_search" } as never)!.investigation_answered_by, "tc_flyby_search");
});

test("a case is tagged Simulated when an outside source behind it was simulated — never otherwise", () => {
  const live = investigationPatch(placeholder, investigation())!;
  assert.equal(live.investigation_simulated, undefined);
  assert.equal(isSimulated(live), false, "a production result carries no tag");
  const simulated = investigationPatch(placeholder, { ...(investigation() as object), simulated: true } as never)!;
  assert.equal(simulated.investigation_simulated, true);
  assert.equal(isSimulated(simulated), true);
  // The same findings and outcome either way: the tag is the only difference.
  const { investigation_simulated: _tag, ...rest } = simulated;
  assert.deepEqual(rest, live);
  // Picked up by a case patched before the result recorded it, and never dropped once tagged.
  assert.equal(investigationPatch(live, { ...(investigation() as object), simulated: true } as never)!.investigation_simulated, true);
  assert.equal(investigationPatch(simulated, investigation()), null, "still tagged; nothing to change");
  // A preview sample input is tagged through its evidence profile.
  assert.equal(isSimulated({ evidence_profile: { simulated: true } } as never), true);
  assert.equal(isSimulated({ evidence_profile: { simulated: undefined } } as never), false);
});
