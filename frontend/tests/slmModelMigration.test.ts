import test from "node:test";
import assert from "node:assert/strict";
import { ACTIVE_MODEL, REFERENCE_MODEL, PROPOSED_MODEL } from "../src/domain/slm/modelProfiles.ts";
import { prepareAndRetireReferenceModel } from "../src/domain/slm/modelMigration.ts";

test("Qwen3 is selected with its pinned package, context and memory profile", () => {
  assert.equal(ACTIVE_MODEL, PROPOSED_MODEL);
  assert.equal(ACTIVE_MODEL.contextTokens, 8192);
  assert.ok(ACTIVE_MODEL.expectedBytes! > 1024 ** 3);
});
test("obsolete package removal follows successful loading and names only the private reference file", async () => {
  const events: string[] = [];
  const result = await prepareAndRetireReferenceModel(ACTIVE_MODEL.modelId, async () => { events.push("loaded"); }, filename => events.push(filename));
  assert.deepEqual(events, ["loaded", REFERENCE_MODEL.filename]);
  assert.equal(result.removedLegacy, true);
});
test("failed Qwen3 loading preserves the reference package", async () => {
  let deletes = 0;
  await assert.rejects(prepareAndRetireReferenceModel(ACTIVE_MODEL.modelId, async () => { throw Error("load failed"); }, () => { deletes++; }));
  assert.equal(deletes, 0);
});
test("another loaded runtime cannot retire a package and cleanup failure does not disable Qwen3", async () => {
  let deletes = 0;
  await prepareAndRetireReferenceModel(REFERENCE_MODEL.modelId, async () => {}, () => { deletes++; });
  assert.equal(deletes, 0);
  const result = await prepareAndRetireReferenceModel(ACTIVE_MODEL.modelId, async () => {}, () => { throw Error("busy"); });
  assert.equal(result.cleanupFailed, true);
});
