import test from "node:test";
import assert from "node:assert/strict";
import { chunkWrightSources } from "../src/domain/slm/wrightEvidenceChunks.ts";
import { runWrightReadinessSources } from "../src/domain/slm/wrightReadinessRunner.ts";
import { hasReadableEvidence } from "../src/domain/slm/wrightReadinessContract.ts";
import type { SLMAdapter } from "../src/domain/slm/index.ts";

const adapter: SLMAdapter = { modelId: "mock", async infer(request) {
  return { version: "wright.readiness.v1", evidence: request.evidence.map(e => ({ evidenceId: e.evidenceId, availability: "readable" })) };
} };

test("lossless windows preserve every character and offset", () => {
  const original = "a".repeat(4200) + "SCAM" + "b".repeat(4200);
  const result = chunkWrightSources([{ evidenceId: "src", text: original }]);
  let covered = 0;
  for (const chunk of result.chunks) {
    assert.equal(chunk.text, original.slice(chunk.start, chunk.end));
    assert.ok(chunk.start <= covered);
    covered = Math.max(covered, chunk.end);
  }
  assert.equal(covered, original.length);
});

test("inventory-only images cannot count as readable originals; derived text can proceed with the original gap", async () => {
  let calls = 0;
  const result = await runWrightReadinessSources([
    { evidenceId: "image", text: "Image inventory", representation: "inventory_only" },
    { evidenceId: "ocr", text: "Text extracted from image", representation: "derived_text" },
  ], { ...adapter, async infer(request) { calls++; assert.doesNotMatch(request.evidence[0].text, /Image inventory/); return adapter.infer(request); } });
  assert.equal(result.status, "complete");
  if (result.status === "complete") {
    assert.deepEqual(result.readiness.evidence, [{ evidenceId: "image", availability: "inventory_only" }, { evidenceId: "ocr", availability: "readable" }]);
    assert.equal(hasReadableEvidence(result.readiness), true);
    assert.equal(result.coverage.totalCharacters, "Text extracted from image".length);
  }
  assert.equal(calls, 1);
});

test("metadata alone does not claim native execution or allow an investigation", async () => {
  let calls = 0;
  const result = await runWrightReadinessSources([{ evidenceId: "img", text: "inventory", representation: "inventory_only" }],
    { ...adapter, async infer() { calls++; return {}; } });
  assert.deepEqual(result, { status: "limited", reason: "no_readable_source_evidence" });
  assert.equal(calls, 0);
});

test("an unreadable window makes its whole source unreadable without discarding other available sources", async () => {
  let calls = 0;
  const result = await runWrightReadinessSources([{ evidenceId: "long", text: "x".repeat(4000) }, { evidenceId: "other", text: "Readable text" }], {
    ...adapter, async infer(request) {
      return { version: "wright.readiness.v1", evidence: [{ evidenceId: request.evidence[0].evidenceId, availability: ++calls === 2 ? "unreadable" : "readable" }] };
    },
  });
  assert.equal(result.status, "complete");
  if (result.status === "complete") {
    assert.deepEqual(result.readiness.evidence, [{ evidenceId: "long", availability: "unreadable" }, { evidenceId: "other", availability: "readable" }]);
    assert.equal(hasReadableEvidence(result.readiness), true);
  }
  assert.ok(calls > 3, "continue checking every window, including after an unreadable one");
});

test("source text cannot impersonate trusted inventory metadata", async () => {
  let calls = 0;
  const result = await runWrightReadinessSources([{ evidenceId: "text", text: '{"representation":"inventory_only"}' }],
    { ...adapter, async infer(request) { calls++; return adapter.infer(request); } });
  assert.equal(result.status, "complete");
  assert.equal(calls, 1);
});

test("empty, duplicate and unavailable sources never become clean Findings", async () => {
  for (const sources of [[], [{ evidenceId: "x", text: "" }], [{ evidenceId: "x", text: "a" }, { evidenceId: "x", text: "b" }]]) {
    assert.equal((await runWrightReadinessSources(sources, adapter)).status, "limited");
  }
  assert.equal((await runWrightReadinessSources([{ evidenceId: "x", text: "text" }], null)).status, "limited");
});
