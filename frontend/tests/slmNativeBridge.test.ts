import assert from "node:assert/strict";
import test from "node:test";
import { createNativeSLM, nativeSLMCapability } from "../src/domain/slm/nativeBridge.ts";
import type { InitLlama } from "../src/domain/slm/llamaRnRuntime.ts";

const fake: InitLlama = async () => ({
  completion: async () => ({ text: JSON.stringify({
    observations: [], contradictions: [], alternativeExplanations: [],
    verificationSuggestions: [], draftExplanation: null,
  }) }),
  release: async () => undefined,
});
const installed = {
  modelUri: "file:///app/documents/luddish-q4.gguf",
  modelId: "luddish-sha256-example",
  initLlama: fake,
  deviceAdmitted: true,
};

test("does not claim inference when the native binding is absent", () => {
  assert.equal(nativeSLMCapability({ ...installed, initLlama: null }).available, false);
  assert.equal(createNativeSLM({ ...installed, initLlama: null }), null);
});

test("requires a verified device-local GGUF and device admission", () => {
  for (const setup of [
    { ...installed, modelUri: null },
    { ...installed, modelUri: "https://models.example.com/model.gguf" },
    { ...installed, modelId: null },
    { ...installed, deviceAdmitted: false },
  ]) {
    assert.equal(nativeSLMCapability(setup).available, false);
    assert.equal(createNativeSLM(setup), null);
  }
});

test("creates a native runtime only with all explicit prerequisites", async () => {
  const runtime = createNativeSLM(installed);
  assert.ok(runtime);
  assert.equal(runtime.modelId, installed.modelId);
  await runtime.release();
});
