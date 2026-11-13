import assert from "node:assert/strict";
import test from "node:test";
import { createCompatibilityAttempt, SLMCompatibilityTimeout } from "../src/domain/slm/compatibilityAttempt.ts";
import { admitNativeStartup, describeStartupFailure } from "../src/domain/slm/nativeStartup.ts";
import { downloadWithNetworkConsent, ModelDownloadPaused } from "../src/domain/slm/downloadSession.ts";
import { LocalLlamaRuntime, LocalInferenceError } from "../src/domain/slm/llamaRnRuntime.ts";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
async function flush() { for (let i = 0; i < 8; i++) await Promise.resolve(); }
const ready = { compatible: true, reason: "Ready" };
const model = { available: true as const, uri: "file:///private/model.gguf", modelId: "approved-model" };

test("a model download taking over two minutes still reaches verified startup", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const transfer = deferred<boolean>();
  let checks = 0;
  let settled = false;
  const attempt = createCompatibilityAttempt({
    install: () => transfer.promise,
    check: async () => { checks++; return ready; },
  });
  void attempt.result.then(() => { settled = true; });
  t.mock.timers.tick(600000);
  await flush();
  assert.equal(settled, false);
  assert.equal(checks, 0);
  transfer.resolve(true);
  assert.deepEqual(await attempt.result, ready);
  assert.equal(checks, 1);
});

test("native verification receives its own deadline after installation finishes", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const transfer = deferred<boolean>();
  const native = deferred<typeof ready>();
  const attempt = createCompatibilityAttempt({ install: () => transfer.promise, check: () => native.promise });
  t.mock.timers.tick(120001);
  transfer.resolve(true);
  await flush();
  let settled = false;
  void attempt.result.then(() => { settled = true; }, () => { settled = true; });
  t.mock.timers.tick(44999);
  await flush();
  assert.equal(settled, false);
  native.resolve(ready);
  assert.deepEqual(await attempt.result, ready);
});

test("a timed-out native operation stays outstanding until it actually completes", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const native = deferred<typeof ready>();
  const attempt = createCompatibilityAttempt({ check: () => native.promise });
  let workComplete = false;
  void attempt.work.finally(() => { workComplete = true; });
  const rejection = assert.rejects(attempt.result, SLMCompatibilityTimeout);
  t.mock.timers.tick(45000);
  await rejection;
  assert.equal(workComplete, false, "a UI deadline must not permit overlapping native loads");
  native.resolve(ready);
  await attempt.work;
  assert.equal(workComplete, true);
});

test("an incomplete installation cannot run verification or become ready", async () => {
  let checks = 0;
  const failure = { compatible: false, reason: "Model verification failed", diagnosticCode: "invalid_model" };
  const attempt = createCompatibilityAttempt({ install: async () => false,
    installFailure: () => failure, check: async () => { checks++; return ready; } });
  assert.deepEqual(await attempt.result, failure);
  assert.equal(checks, 0);
});

test("successful verification clears its deadline", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const attempt = createCompatibilityAttempt({ check: async () => ready });
  assert.deepEqual(await attempt.result, ready);
  t.mock.timers.tick(1000000);
  assert.deepEqual(await attempt.result, ready);
});

test("file admission failure preserves the actual reason and never loads native bindings", async () => {
  for (const reason of ["model_not_installed", "model_unreadable", "invalid_model", "device_not_admitted"] as const) {
    let bindings = 0;
    const result = await admitNativeStartup(async () => ({ available: false, reason }), async () => {
      bindings++; return () => ({});
    });
    assert.deepEqual(result, { available: false, code: reason });
    assert.equal(bindings, 0);
    assert.ok(describeStartupFailure(reason).length > 0);
  }
});

test("file access exceptions do not expose paths or private error text", async () => {
  const result = await admitNativeStartup(async () => { throw new Error("/private/source-content"); }, async () => () => ({}));
  assert.deepEqual(result, { available: false, code: "model_unreadable" });
  assert.ok(!JSON.stringify(result).includes("source-content"));
});

test("native import failure is distinguishable from a missing model", async () => {
  const stages: string[] = [];
  const result = await admitNativeStartup(async () => model, async () => { throw new Error("native implementation detail"); }, s => stages.push(s));
  assert.deepEqual(result, { available: false, code: "native_binding_unavailable" });
  assert.deepEqual(stages, ["model_integrity", "runtime_registration"]);
});

test("runtime registration rejects null and constructor failure without inventing availability", async () => {
  assert.deepEqual(await admitNativeStartup(async () => model, async () => () => null), {
    available: false, code: "runtime_registration_failed",
  });
  assert.deepEqual(await admitNativeStartup(async () => model, async () => () => { throw new Error("private detail"); }), {
    available: false, code: "runtime_registration_failed",
  });
});

test("a valid admitted model registers exactly the supplied native runtime", async () => {
  const runtime = { modelId: model.modelId };
  const result = await admitNativeStartup(async () => model, async () => admitted => {
    assert.equal(admitted, model);
    return runtime;
  });
  assert.deepEqual(result, { available: true, runtime });
});

function transferFixture() {
  const first = deferred<{ status: number } | undefined>();
  const resumed = deferred<{ status: number } | undefined>();
  const calls = { pause: 0, resume: 0, cancel: 0 };
  const task = {
    downloadAsync: () => first.promise,
    pauseAsync: async () => { calls.pause++; first.resolve(undefined); },
    resumeAsync: () => { calls.resume++; return resumed.promise; },
    cancelAsync: async () => { calls.cancel++; first.resolve(undefined); resumed.resolve(undefined); },
  };
  return { task, first, resumed, calls };
}

test("an explicitly approved cellular download is not repeatedly paused", async t => {
  t.mock.timers.enable({ apis: ["setInterval"] });
  const f = transferFixture();
  let prompts = 0;
  const result = downloadWithNetworkConsent(f.task, { approvedNetwork: "cellular",
    readNetwork: async () => "cellular", approveNetwork: async () => { prompts++; return "cellular"; } });
  for (let i = 0; i < 5; i++) { t.mock.timers.tick(1000); await flush(); }
  assert.equal(f.calls.pause, 0);
  assert.equal(prompts, 0);
  f.first.resolve({ status: 200 });
  assert.deepEqual(await result, { status: 200 });
});

test("a network transition waits for fresh consent and accepts the resumed transfer", async t => {
  t.mock.timers.enable({ apis: ["setInterval"] });
  const f = transferFixture();
  const consent = deferred<string | null>();
  const result = downloadWithNetworkConsent(f.task, { approvedNetwork: "wifi",
    readNetwork: async () => "cellular", approveNetwork: () => consent.promise });
  let settled = false;
  void result.then(() => { settled = true; });
  t.mock.timers.tick(1000); await flush();
  assert.equal(f.calls.pause, 1);
  assert.equal(f.calls.resume, 0);
  assert.equal(settled, false, "Expo's paused original promise is not transfer completion");
  consent.resolve("cellular"); await flush();
  assert.equal(f.calls.resume, 1);
  f.resumed.resolve({ status: 200 });
  assert.deepEqual(await result, { status: 200 });
});

test("denied network consent leaves the transfer paused and cannot produce success", async t => {
  t.mock.timers.enable({ apis: ["setInterval"] });
  const f = transferFixture();
  const result = downloadWithNetworkConsent(f.task, { approvedNetwork: "wifi",
    readNetwork: async () => "cellular", approveNetwork: async () => null });
  const rejection = assert.rejects(result, ModelDownloadPaused);
  t.mock.timers.tick(1000); await rejection;
  assert.equal(f.calls.pause, 1);
  assert.equal(f.calls.resume, 0);
});

test("network monitoring stops when the model transfer completes", async t => {
  t.mock.timers.enable({ apis: ["setInterval"] });
  const f = transferFixture();
  let reads = 0;
  const result = downloadWithNetworkConsent(f.task, { approvedNetwork: "wifi",
    readNetwork: async () => { reads++; return "cellular"; }, approveNetwork: async () => "cellular" });
  f.first.resolve({ status: 200 }); await result;
  t.mock.timers.tick(10000); await flush();
  assert.equal(reads, 0);
  assert.equal(f.calls.pause, 0);
});

test("a failed native pause cancels the transfer before releasing setup", async t => {
  t.mock.timers.enable({ apis: ["setInterval"] });
  const f = transferFixture();
  f.task.pauseAsync = async () => { throw new Error("pause failed"); };
  const result = downloadWithNetworkConsent(f.task, { approvedNetwork: "wifi",
    readNetwork: async () => "cellular", approveNetwork: async () => "cellular" });
  const rejection = assert.rejects(result, /pause failed/);
  t.mock.timers.tick(1000); await rejection;
  assert.equal(f.calls.cancel, 1);
  assert.equal(f.calls.resume, 0);
});

test("known SDK binding failures retain safe actionable codes", async () => {
  for (const [message, code] of [["JSI bindings not installed", "native_bindings_not_installed"],
    ["[RNLlama] Missing JSI bindings: private-list", "native_bindings_incomplete"]]) {
    const runtime = new LocalLlamaRuntime(model.uri, model.modelId, async () => { throw new Error(message); });
    await assert.rejects(runtime.prepare(), error => error instanceof LocalInferenceError && error.stage === "model_load" && error.code === code);
  }
});
