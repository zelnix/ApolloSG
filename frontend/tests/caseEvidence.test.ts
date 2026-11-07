// The Threat Case Evidence tab (domain/caseEvidence.ts): the material facts the case established, strongest first,
// each with who found it first and who confirmed it; what points the other way listed and marked; a block this device
// recorded listed like any other fact; no "Found by" line where the record doesn't say; never the submitted item again.
// Run: cd /app/frontend && node --test tests/caseEvidence.test.ts
import assert from "node:assert/strict";
import test from "node:test";

import { caseFindings } from "../src/domain/caseBriefing.ts";
import { caseEvidence, evidenceTrail, factStrength, provenanceLine } from "../src/domain/caseEvidence.ts";
import type { PatrolEvent } from "../src/domain/types.ts";

function ev(partial: Partial<PatrolEvent> = {}): PatrolEvent {
  return {
    event_id: "e1", device_id: "phone-a", category: "message", state: "growling", status: "active", origin: "user",
    headline: "Message using CommBank's name checked", what_happened: "A text asked you to cancel a payment through a link.",
    why: ["commbank-cancel.co isn't CommBank's domain."], what_to_do: "Don't open the link.",
    indicator_host: "commbank-cancel.co", indicator_digest: null, verified_block: false, adapter_label: "test",
    occurred_at: "2026-10-28T01:12:00.000Z", resolved_at: null, investigation_case_id: "case-1",
    investigation_completed_at: "2026-10-28T01:12:30.000Z", investigation_answered_by: "tc_flyby",
    evidence_provenance: "device_submission", processing_source: "apollosg_servers", evidence_representation: "full_record",
    ...partial,
  } as PatrolEvent;
}

const coverage = { status: "examined", unit: "characters", total: 168, examined: 168, materialGap: false } as never;
const item = (over: Record<string, unknown>) => ({
  id: "EV-1", caseId: "case-1", clientItemId: "c1", displayId: "EV-1", origin: "user_submission", kind: "text", parentId: null,
  availability: "available", mediaType: null, byteLength: null, integrityHash: null, provenance: null, coverage,
  simulation: null, transformations: [], label: "Submitted message text", expiresAt: "2026-10-28T02:00:00Z",
  collectedAt: "2026-10-28T01:12:00.000Z", ...over,
});

const finding = { id: "f1", text: "commbank-cancel.co carries CommBank's name, but it isn't CommBank's domain.", basis: "observation", confidence: "high", evidenceIds: ["EV-1", "EV-2"], sourceIds: [] };
const fact = (over: Record<string, unknown>) => ({
  id: "c1.1", text: "t", stance: "supporting", discoveredBy: "tc_flyby", corroboratedBy: [], weak: false, basis: "observation",
  confidence: "medium", evidenceIds: [], sourceIds: [], findingIds: [], ruleId: null, establishedAt: "2026-10-28T01:12:20Z", simulated: false, ...over,
});
const response = (over: Record<string, unknown> = {}) => ({
  revision: 1, overview: "Concerning.", explanationMarkdown: "", assessment: "concern_found", outcome: "concerning", attention: "review",
  attentionReason: null, findings: [finding], uncertainties: [], scope: "", sourceIds: [], remainingEvidenceIds: [], actions: [],
  recommendedActionId: null, question: null, completion: "complete", ...over,
});
const investigation = (over: Record<string, unknown> = {}, resp: Record<string, unknown> = {}) => ({
  caseId: "case-1", gates: ["text"], status: "complete", createdAt: "2026-10-28T01:12:00Z", completedAt: "2026-10-28T01:12:30Z",
  committedAt: "2026-10-28T01:12:30Z", question: "", sources: [], turns: [], patrolEventId: "e1", answeredBy: "tc_flyby",
  evidenceItems: [item({}), item({ id: "EV-2", displayId: "EV-2", kind: "url", parentId: "EV-1", label: "URL from message", coverage: { status: "examined", unit: "items", total: 1, examined: 1, materialGap: false } }),
    item({ id: "EV-C", clientItemId: "tc-flyby-di-checks", origin: "apollo_inference", kind: "observation", label: "TC Hawkeye fly-by checks" })],
  response: response(resp), ...over,
}) as never;

const build = (e: PatrolEvent, inv: never | null, facts: string[] = [e.headline]) => caseEvidence({ event: e, investigation: inv, trace: null, records: [], facts });

test("each fact says who found it first and who confirmed it — never the item you submitted as a fact", () => {
  const evidence = [
    fact({ id: "c1.1", text: "commbank-cancel.co was registered on 2026-10-20.", weak: true, evidenceIds: ["EV-C"] }),
    fact({ id: "c2.1", text: "commbank-cancel.co isn't one of CommBank's published domains.", confidence: "high", corroboratedBy: ["magnum_di"], findingIds: ["f1"], evidenceIds: ["EV-C", "EV-2"] }),
    fact({ id: "c3.1", text: "It claims a rebate (“Energy Bill Relief”).", discoveredBy: "higgins_triage", corroboratedBy: ["tc_flyby", "magnum_di"], evidenceIds: ["EV-1"] }),
  ];
  const out = build(ev(), investigation({}, { evidence }));
  assert.deepEqual(out.facts.map((f) => provenanceLine(f)), [
    "Found by TC Hawkeye · Confirmed by Magnum DI",
    "Found by Higgins Triage · Confirmed by TC Hawkeye, Magnum DI",
    "Found by TC Hawkeye",
  ]);
  for (const f of out.facts) assert.doesNotMatch(f.text, /you submitted|Submitted message text|checked$/i);
  assert.deepEqual(out.facts[0].basedOn, ["TC Hawkeye's checks", "a link in the message you submitted"]);
  assert.deepEqual(out.facts[1].basedOn, ["the message you submitted"]);
});

test("strongest first: firmer, confirmed by more stages, seen directly; weak signals and side-less facts last", () => {
  const evidence = [
    fact({ id: "a", text: "A weak one.", weak: true }),
    fact({ id: "b", text: "A side-less one.", stance: "neutral" }),
    fact({ id: "c", text: "Points the other way.", stance: "contrary" }),
    fact({ id: "d", text: "Confirmed twice.", corroboratedBy: ["magnum_di"] }),
    fact({ id: "e", text: "Decisive.", confidence: "high" }),
  ];
  const out = build(ev(), investigation({}, { evidence }));
  assert.deepEqual(out.facts.map((f) => f.id), ["e", "d", "c", "b", "a"]);
  assert.ok(factStrength(out.facts[0]) > factStrength(out.facts[1]));
});

test("what points the other way is listed with the rest and marked, never dropped", () => {
  const out = build(ev(), investigation({}, { evidence: [fact({ id: "x", text: "Google Safe Browsing doesn't list commbank-cancel.co.", stance: "contrary" })] }));
  assert.equal(out.facts.length, 1);
  assert.equal(out.facts[0].stance, "contrary");
});

test("a result recorded before the Evidence record: its findings word for word, with no Found by line", () => {
  const inv = investigation();
  const out = build(ev(), inv);
  const found = caseFindings((inv as { response: never }).response);
  assert.deepEqual(out.facts.map((f) => f.text), found.map((f) => f.text));
  assert.equal(out.facts[0].foundBy, null);
  assert.equal(provenanceLine(out.facts[0]), null, "who found it wasn't recorded, so it isn't guessed");
  const twice = build(ev(), investigation({}, { findings: [finding, { ...finding, id: "f2" }] }));
  assert.equal(twice.facts.length, 1, "the same words are listed once");
});

test("a recorded empty Evidence record is not replaced with the findings", () => {
  assert.deepEqual(build(ev(), investigation({}, { evidence: [] })).facts, []);
});

test("no investigation yet: what Higgins Triage recorded, without the case's headline", () => {
  const e = ev({ investigation_case_id: null, investigation_completed_at: null, triage_investigation: { rules: [] } as never });
  const out = build(e, null, [e.headline, "It asks you to reply YES.", "It asks you to reply YES."]);
  assert.deepEqual(out.facts.map((f) => [f.text, provenanceLine(f)]), [["It asks you to reply YES.", "Found by Higgins Triage"]]);
});

test("a block this device recorded is a fact like any other, found by Apollo on this device", () => {
  const enforcement = { enforced_action: "dns_block", destination_domain: "bad.example", result: "connection_dropped", observed_at: "2026-10-28T01:00:00Z",
    mechanism: "local_vpn_dns", confidence: "high" } as never;
  const e = ev({ origin: "apollo", category: "connection", investigation_case_id: null, investigation_completed_at: null, enforcement_evidence: enforcement, verified_block: true });
  const out = build(e, null, [e.headline, "bad.example is on Apollo's blocklist."]);
  assert.equal(out.facts[0].id, "block", "an observed, matched block is the firmest fact");
  assert.equal(out.facts[0].text, "Apollo dns block on bad.example — connection dropped.");
  assert.equal(provenanceLine(out.facts[0]), "Found by Apollo on this device");
  assert.equal(provenanceLine(out.facts[1]), "Found by Apollo on this device");
  const unproved = build({ ...e, verified_block: false }, null, []);
  assert.equal(unproved.facts[0].confidence, "low");
});

test("the trail lists only the stages that happened", () => {
  const triage = { evaluatedAt: "2026-10-28T01:12:01Z" } as never;
  const flyby = { ranAt: "2026-10-28T01:12:10Z", resolved: true } as never;
  const settled = evidenceTrail({ event: ev(), trace: { triage, flyby, magnum: null } as never, records: [] });
  assert.deepEqual(settled.map((s) => `${s.name}: ${s.status}`), ["Higgins Triage: Completed", "TC Hawkeye: Completed"]);
  const escalated = evidenceTrail({
    event: ev({ investigation_answered_by: "magnum" }), trace: { triage, flyby: { ranAt: "2026-10-28T01:12:10Z", resolved: false }, magnum: { at: "2026-10-28T01:12:20Z" } } as never,
    records: [{ status: "success", failureCode: null, simulated: false, occurredAt: "2026-10-28T01:12:20Z" }] as never,
  });
  assert.deepEqual(escalated.map((s) => `${s.name}: ${s.status}`), ["Higgins Triage: Completed", "TC Hawkeye: Escalated to Magnum DI", "Magnum DI: Completed"]);
  const running = evidenceTrail({ event: ev({ investigation_completed_at: null }), trace: null, records: [] });
  assert.deepEqual(running.map((s) => `${s.name}: ${s.status}`), ["TC Hawkeye: In progress"]);
});

test("a message case whose investigation never received the message says it wasn't saved", () => {
  const without = investigation({ evidenceItems: [item({ id: "EV-C", clientItemId: "tc-flyby-di-checks", origin: "apollo_inference", kind: "observation", label: "TC Hawkeye fly-by checks" })] }, { evidence: [] });
  const out = build(ev(), without);
  assert.deepEqual(out.facts, []);
  assert.equal(out.messageNotSaved, true);
  assert.equal(build(ev(), investigation({}, { evidence: [] })).messageNotSaved, false, "the message went with it");
  assert.equal(build(ev({ category: "link" }), without).messageNotSaved, false, "only message cases");
  assert.equal(build(ev({ investigation_case_id: null }), null).messageNotSaved, false, "no investigation, nothing missing");
});

// ── P2 verification: older cases without "found by" gracefully hide the provenance line ──

test("an older investigation with only findings (no evidence array) hides every provenance line", () => {
  // A response recorded BEFORE the Evidence record was introduced: has findings but no evidence array.
  const oldResponse = response({ findings: [
    finding,
    { id: "f2", text: "The link leads to a login page that asks for card details.", basis: "observation", confidence: "medium", evidenceIds: [], sourceIds: [] },
  ] });
  const inv = investigation({}, oldResponse);
  const out = build(ev(), inv);
  // Every fact from earlierFindings has foundBy: null → provenanceLine returns null.
  assert.ok(out.facts.length >= 1, "there are facts from the older response");
  for (const f of out.facts) {
    assert.equal(f.foundBy, null, `fact "${f.text}" must not guess who found it`);
    assert.equal(provenanceLine(f), null, `fact "${f.text}" must hide the provenance line`);
  }
});

test("provenanceLine is null only when foundBy is null; it always shows when foundBy is set", () => {
  // foundBy set: always returns a string.
  assert.equal(typeof provenanceLine({ foundBy: "tc_flyby", confirmedBy: [] }), "string");
  assert.equal(typeof provenanceLine({ foundBy: "higgins_triage", confirmedBy: ["magnum_di"] }), "string");
  assert.equal(typeof provenanceLine({ foundBy: "this_device", confirmedBy: [] }), "string");
  // foundBy null: always returns null.
  assert.equal(provenanceLine({ foundBy: null, confirmedBy: [] }), null);
  assert.equal(provenanceLine({ foundBy: null, confirmedBy: ["magnum_di"] }), null, "confirmedBy alone is not enough");
});

test("an older investigation with a device block: the block shows provenance, the findings don't", () => {
  const enforcement = { enforced_action: "dns_block", destination_domain: "bad.example", result: "connection_dropped", observed_at: "2026-10-28T01:00:00Z",
    mechanism: "local_vpn_dns", confidence: "high" } as never;
  const inv = investigation(); // response without evidence array → earlierFindings path
  const e = ev({ enforcement_evidence: enforcement, verified_block: true });
  const out = build(e, inv);
  const blockFact = out.facts.find((f) => f.id === "block");
  const otherFacts = out.facts.filter((f) => f.id !== "block");
  // The block — recorded by this device — always shows who found it.
  assert.ok(blockFact, "the device block is listed as a fact");
  assert.equal(provenanceLine(blockFact!), "Found by Apollo on this device");
  // Older findings without an evidence record: provenance line hidden.
  for (const f of otherFacts) {
    assert.equal(provenanceLine(f), null, `finding "${f.text}" hides provenance since the old record doesn't say`);
  }
});

