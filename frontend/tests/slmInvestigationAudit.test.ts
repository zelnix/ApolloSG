import assert from "node:assert/strict";
import test from "node:test";
import { createInvestigationAudit, engineHistory, mergeSlmStages, slmHistory, type SlmStage } from "../src/domain/investigationAudit.ts";
function harness() {
  const data = new Map<string, string>(); let owner: string | null = "device-A";
  const audit = createInvestigationAudit({ getItem: async (k, f) => data.get(k) ?? f, setItem: async (k, v) => { data.set(k, v); return true; } }, async () => owner);
  return { audit, data, setOwner: (id: string | null) => { owner = id; } };
}
const requested: SlmStage = { caseId: "case-A", caseRevision: 1, requestId: "request-A", role: "tc_hawkeye", status: "requested", requestedAt: "2026-11-14T10:00:00Z" };
test("request alone never claims native engagement or returned output", () => {
  const events = slmHistory([requested]); assert.equal(events.length, 1); assert.match(events[0].title, /requested$/);
  assert.equal(slmHistory([{ ...requested, requestedAt: null }]).length, 0);
});
test("retains exact advisory output and recorded timestamps after reopening", async () => {
  const { audit } = harness(); const token = (await audit.open("case-A"))!;
  const output = { observations: [{ text: "A renewal is offered", evidenceIds: ["E-1"] }] };
  await audit.stage(token, requested);
  await audit.stage(token, { ...requested, status: "returned", startedAt: "2026-11-14T10:00:01Z", returnedAt: "2026-11-14T10:00:03Z", output });
  const saved = await audit.get("case-A"); assert.deepEqual(saved?.stages[0].output, output); assert.equal(saved?.stages.length, 1);
  assert.deepEqual(slmHistory(saved!.stages).map(e => e.at), [requested.requestedAt, "2026-11-14T10:00:01Z", "2026-11-14T10:00:03Z"]);
  assert.equal(await audit.get("case-B"), null);
});
test("owner changes fence callbacks and prevent cross-device reads", async () => {
  const h = harness(); const token = (await h.audit.open("case-A"))!; await h.audit.stage(token, requested); h.setOwner("device-B");
  assert.equal(await h.audit.get("case-A"), null); await h.audit.stage(token, { ...requested, status: "accepted" });
  h.setOwner("device-A"); assert.equal((await h.audit.get("case-A"))?.stages[0].status, "requested");
});
test("deleting an uncommitted case rejects late inference and snapshot writes", async () => {
  const h = harness(); const token = (await h.audit.open("case-A"))!; await h.audit.remove("case-A");
  await h.audit.stage(token, requested); await h.audit.snapshot(token, null, []);
  assert.equal(await h.audit.get("case-A"), null); assert.equal(await h.audit.isCurrent(token), false);
});
test("privacy wipe fences callbacks even after storage keys are removed", async () => {
  const h = harness(); const token = (await h.audit.open("case-A"))!;
  await h.audit.stage(token, requested); await h.audit.clear(); h.data.clear();
  await h.audit.stage(token, requested); await h.audit.snapshot(token, null, []); assert.equal(await h.audit.get("case-A"), null);
});
test("server receipts merge with native output without downgrading accepted state", () => {
  const stages = mergeSlmStages([{ ...requested, caseRevision: undefined, status: "accepted", acceptedAt: "2026-11-14T10:00:05Z" }], [{ ...requested, status: "returned", output: { draftExplanation: "Recorded wording" }, returnedAt: "2026-11-14T10:00:03Z" }]);
  assert.equal(stages.length, 1); assert.equal(stages[0].status, "accepted"); assert.deepEqual(stages[0].output, { draftExplanation: "Recorded wording" });
  assert.equal(stages[0].startedAt, undefined); assert.ok(!slmHistory(stages).some(e => /engaged$/.test(e.title)));
});


test("live cases without a patrol event still expose recorded engine history", () => {
  assert.deepEqual(engineHistory(null, []), []);
  const entries = engineHistory(null, [{ investigationId: "case-A", engine: "Magnum DI", environment: "test", mode: "Live", simulated: false, status: "failed", failureCode: "provider_timeout", occurredAt: "2026-11-14T10:00:00Z", request: {}, notice: null }]);
  assert.equal(entries[0].title, "Magnum DI did not finish");
  assert.equal(entries[0].at, "2026-11-14T10:00:00Z");
});
