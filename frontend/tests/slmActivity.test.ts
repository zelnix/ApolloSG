import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { runSLM, type SLMAdapter } from "../src/domain/slm/index.ts";
import { LocalLlamaRuntime } from "../src/domain/slm/llamaRnRuntime.ts";
import { slmActivityStatus } from "../src/domain/slm/activityStatus.ts";
import { getSLMActivitySnapshot, setSharedSLM, subscribeSLMActivity } from "../src/domain/slm/sharedRuntime.ts";

const request = { role: "luddish", operation: "explanation", question: "Local response test", evidence: [] } as const;
const answer = { observations: [], contradictions: [], alternativeExplanations: [], verificationSuggestions: [], draftExplanation: null };
const options = { available: true, settingUp: false, testing: false };
const label = () => slmActivityStatus(getSLMActivitySnapshot(), options);
afterEach(() => setSharedSLM(null));

test("an earlier success cannot keep Settings Active after the screenshot's JSON parse failure", async () => {
  let text = JSON.stringify(answer);
  const runtime = new LocalLlamaRuntime("file:///models/a.gguf", "local-test", async () => ({
    completion: async () => ({ text }), release: async () => undefined,
  }));
  setSharedSLM(runtime);
  assert.match(label(), /registered.*not yet confirmed/);
  await runSLM(request, runtime);
  const success = getSLMActivitySnapshot();
  assert.match(label(), /^Active/);
  assert.ok(success.lastSuccessfulInferenceAt);
  text = "No valid object was generated.";
  const failure = await runSLM(request, runtime);
  assert.equal(failure.status, "unavailable");
  if (failure.status !== "completed") assert.match(failure.reason, /json_parse:no_json_object/);
  const failed = getSLMActivitySnapshot();
  assert.equal(failed.latestInference?.status, "unavailable");
  assert.equal(failed.lastSuccessfulInferenceAt, success.lastSuccessfulInferenceAt, "retain historical success as history");
  assert.match(label(), /^Needs attention/);
  assert.doesNotMatch(label(), /^Active/);
  text = JSON.stringify(answer);
  await runSLM(request, runtime);
  assert.match(label(), /^Active/);
  assert.notEqual(getSLMActivitySnapshot(), failed, "stale diagnostic labels no longer match the activity snapshot");
  await runtime.release();
});

test("invalid response contracts revoke Active without retaining model text or evidence", async () => {
  let candidate: unknown = answer;
  const adapter: SLMAdapter = { modelId: "local-test", infer: async () => candidate };
  setSharedSLM(adapter);
  await runSLM(request, adapter);
  candidate = { ...answer, observations: [{ text: "PRIVATE OUTPUT", evidenceIds: ["other-device"] }] };
  await runSLM(request, adapter);
  assert.equal(getSLMActivitySnapshot().latestInference?.status, "invalid_output");
  assert.match(label(), /failed validation/);
  assert.doesNotMatch(JSON.stringify(getSLMActivitySnapshot()), /PRIVATE OUTPUT|other-device|evidence|question/);
});

for (const fail of [false, true]) {
  test(`late ${fail ? "failed" : "successful"} response from a replaced runtime cannot change current status`, async () => {
    let finish!: (value: unknown) => void;
    const old: SLMAdapter = { modelId: "old", infer: () => new Promise(resolve => { finish = resolve; }) };
    const current: SLMAdapter = { modelId: "current", infer: async () => answer };
    setSharedSLM(old);
    const pending = runSLM(request, old);
    setSharedSLM(current);
    const snapshot = getSLMActivitySnapshot();
    finish(fail ? {} : answer);
    await pending;
    assert.equal(getSLMActivitySnapshot(), snapshot);
    assert.equal(snapshot.modelId, "current");
    assert.equal(snapshot.lastSuccessfulInferenceAt, null);
    assert.equal(snapshot.latestInference, null);
    assert.match(label(), /registered.*not yet confirmed/);
  });
}

test("unregistering clears activity and notifies Settings; snapshot reads do not run inference", async () => {
  let calls = 0;
  let notifications = 0;
  const off = subscribeSLMActivity(() => { notifications++; });
  try {
    const adapter: SLMAdapter = { modelId: "local-test", infer: async () => { calls++; return answer; } };
    setSharedSLM(adapter);
    const initial = getSLMActivitySnapshot();
    assert.equal(initial, getSLMActivitySnapshot());
    assert.equal(calls, 0);
    await runSLM(request, adapter);
    setSharedSLM(null);
    assert.equal(getSLMActivitySnapshot().latestInference, null);
    assert.equal(getSLMActivitySnapshot().lastSuccessfulInferenceAt, null);
    assert.match(label(), /Inactive/);
    assert.equal(calls, 1);
    assert.equal(notifications, 3);
  } finally { off(); }
});

test("Settings distinguishes setup, platform availability and an explicit test without background probing", () => {
  setSharedSLM({ modelId: "local-test", infer: async () => answer });
  const snapshot = getSLMActivitySnapshot();
  assert.equal(slmActivityStatus(snapshot, { ...options, settingUp: true }), "Setup in progress");
  assert.equal(slmActivityStatus(snapshot, { ...options, available: false }), "Unavailable on this platform");
  assert.equal(slmActivityStatus(snapshot, { ...options, testing: true }), "Testing local inference…");
  assert.match(slmActivityStatus({ ...snapshot, lastSuccessfulInferenceAt: "2026-11-14T00:01:57Z" }, options), /not yet confirmed/);
});
