import test from "node:test";
import assert from "node:assert/strict";
import { chunkWrightSources } from "../src/domain/slm/wrightEvidenceChunks.ts";
import { runWrightSemanticSources } from "../src/domain/slm/wrightSemanticRunner.ts";

test("lossless windows preserve every character and offsets", () => {
  const original = "a".repeat(4200) + "SCAM" + "b".repeat(4200);
  const result = chunkWrightSources([{ evidenceId: "src", text: original }]);
  assert.ok(result.chunks.length > 2);
  assert.equal(result.coverage.coveredCharacters, original.length);
  let covered = 0;
  for (const chunk of result.chunks) {
    assert.equal(chunk.text, original.slice(chunk.start, chunk.end));
    assert.ok(chunk.start <= covered);
    covered = Math.max(covered, chunk.end);
  }
  assert.equal(covered, original.length);
});

test("failed inference is limited, never a clean result", async () => {
  const result = await runWrightSemanticSources([{ evidenceId: "src", text: "invoice due tomorrow" }], null);
  assert.equal(result.status, "limited");
  assert.equal(result.coverage.complete, false);
});

test("every window is assessed and cited on-device", async () => {
  let calls = 0;
  const result = await runWrightSemanticSources([{ evidenceId: "src", text: "invoice ".repeat(600) }], {
    modelId: "mock",
    async infer(request) {
      calls++;
      return { version: "wright.semantic.v1", classification: "ambiguous", scamTypes: [],
        intent: "Requests payment", coercion: "uncertain",
        exposure: { payment: "UNKNOWN", credentials: "UNKNOWN", identity: "UNKNOWN", remoteAccess: "UNKNOWN" },
        narrative: "Payment request alone does not establish fraud.", uncertainty: "Sender not verified",
        supportingEvidenceIds: [request.evidence[0].evidenceId] };
    },
  });
  assert.equal(result.status, "complete");
  if (result.status === "complete") {
    assert.equal(result.interpretations.length, calls);
    assert.ok(calls > 1);
    assert.ok(result.interpretations.every(item => item.result.supportingEvidenceIds.includes(item.evidenceId)));
  }
});
