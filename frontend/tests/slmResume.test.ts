import test from "node:test";
import assert from "node:assert/strict";
import { LocalLlamaRuntime } from "../src/domain/slm/llamaRnRuntime.ts";
const request = { role: "tc_hawkeye" as const, operation: "evidence_reasoning" as const, question: "Explain only the supplied evidence", evidence: [{ evidenceId: "E1", text: "Synthetic test evidence" }] };
const response = { text: JSON.stringify({ observations: [], contradictions: [], alternativeExplanations: [], verificationSuggestions: [], draftExplanation: null }) };
const tick = () => new Promise(resolve => setImmediate(resolve));
test("idle warm resume tolerates the actual void-returning native stop API", async () => {
  let stops = 0;
  const runtime = new LocalLlamaRuntime("file:///models/test.gguf", "test", async () => ({ completion: async () => response, stopCompletion: (() => { stops++; }), release: async () => {} }));
  await runtime.prepare(); assert.doesNotThrow(() => runtime.suspend(true)); runtime.suspend(false);
  assert.equal(stops, 0, "an idle app switch must not call native cancellation");
  assert.deepEqual(await runtime.infer(request), JSON.parse(response.text)); await runtime.release();
});
test("void-returning cancellation rejects old work, preserves the slot, and permits fresh work on resume", async () => {
  let resolve!: (value: typeof response) => void; let calls = 0; let stops = 0;
  const runtime = new LocalLlamaRuntime("file:///models/test.gguf", "test", async () => ({ completion: async () => { if (++calls === 1) return new Promise<typeof response>(done => { resolve = done; }); return response; }, stopCompletion: (() => { stops++; }), release: async () => {} }));
  const previous = runtime.infer(request); const rejected = assert.rejects(previous, /expired_or_cancelled/);
  await tick(); assert.doesNotThrow(() => runtime.suspend(true)); runtime.suspend(false);
  const fresh = runtime.infer(request); await tick(); assert.equal(calls, 1);
  resolve(response); await rejected; await fresh; assert.equal(stops, 1); assert.equal(calls, 2); await runtime.release();
});


test("a synchronous native stop failure cannot escape into the AppState callback", async () => {
  let resolve!: (value: typeof response) => void;
  const runtime = new LocalLlamaRuntime("file:///models/test.gguf", "test", async () => ({ completion: async () => new Promise<typeof response>(done => { resolve = done; }), stopCompletion: () => { throw Error("Synthetic released context"); }, release: async () => {} }));
  const work = runtime.infer(request); const rejected = assert.rejects(work, /expired_or_cancelled/);
  await tick(); assert.doesNotThrow(() => runtime.suspend(true)); resolve(response); await rejected;
  runtime.suspend(false); await runtime.release();
});

for (const boundary of ["load", "tokenization"] as const) {
  test(`backgrounding during ${boundary} cannot start stale generation after returning`, async () => {
    let unblock!: () => void; let calls = 0; let counts = 0;
    const barrier = new Promise<void>(done => { unblock = done; });
    const context = { completion: async () => { calls++; return response; }, countFormattedTokens: async () => { if (boundary === "tokenization" && ++counts === 1) await barrier; return 100; }, stopCompletion: () => {}, release: async () => {} };
    const runtime = new LocalLlamaRuntime("file:///models/test.gguf", "test", async () => { if (boundary === "load") await barrier; return context; });
    const work = runtime.infer(request); const rejected = assert.rejects(work, /expired_or_cancelled/);
    await tick(); runtime.suspend(true); runtime.suspend(false); unblock(); await rejected; assert.equal(calls, 0);
    await runtime.infer(request); assert.equal(calls, 1); await runtime.release();
  });
}

test("chat preflight interrupted by backgrounding must be reissued, not silently resumed", async () => {
  let unblock!: () => void;
  const barrier = new Promise<void>(done => { unblock = done; });
  const runtime = new LocalLlamaRuntime("file:///models/test.gguf", "test", async () => { await barrier; return { completion: async () => response, release: async () => {} }; });
  const checking = runtime.canFitAsync(request); const rejected = assert.rejects(checking, /expired_or_cancelled/);
  await tick(); runtime.suspend(true); runtime.suspend(false); unblock(); await rejected; await runtime.release();
});
