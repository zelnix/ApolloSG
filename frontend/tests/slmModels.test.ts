// Fallback on-device models: what a phone is offered, how a download is verified, and how models are compared.
import assert from "node:assert/strict";
import { test } from "node:test";

import { PRE_SCREEN_CASES, scorePreScreen, summarise, summaryLine } from "../src/slm/benchmark.ts";
import { APACHE_2_0_LICENSE, BUILT_WITH_LLAMA, LLAMA_3_2_LICENSE, LLAMA_3_2_NOTICE } from "../src/slm/licences.ts";
import { FALLBACK_MODELS, MODEL_SOURCES, hashMatches, modelById, modelFit, validSource } from "../src/slm/models.ts";

const GB = 1024 ** 3;
const SRC = { url: "https://models.example.org/qwen.gguf", sha256: "a".repeat(64), bytes: 400 * 1024 ** 2 };
const qwen05 = modelById("qwen2.5-0.5b-instruct-q4km")!;
const qwen15 = modelById("qwen2.5-1.5b-instruct-q4km")!;

test("catalogue: Qwen 0.5B, Llama 1B and Qwen 1.5B, smallest first, none downloadable until hosted", () => {
  assert.deepEqual(FALLBACK_MODELS.map((m) => m.id), ["qwen2.5-0.5b-instruct-q4km", "llama3.2-1b-instruct-q4km", "qwen2.5-1.5b-instruct-q4km"]);
  for (const m of FALLBACK_MODELS) assert.equal(MODEL_SOURCES[m.id], null, `${m.id} has no hosted file yet`);
  assert.equal(modelById("nope"), null);
});

test("a source needs an https URL, a 64-hex SHA-256 and a size", () => {
  assert.equal(validSource(SRC), true);
  assert.equal(validSource({ ...SRC, url: "http://x/y.gguf" }), false);
  assert.equal(validSource({ ...SRC, sha256: "abc" }), false);
  assert.equal(validSource({ ...SRC, bytes: 0 }), false);
  assert.equal(validSource(null), false);
});

test("fit: not offered without a source, with too little or unknown memory, or too little storage", () => {
  assert.deepEqual(modelFit(qwen05, null, 4 * GB, 10 * GB), { ok: false, reason: "not_hosted" });
  assert.deepEqual(modelFit(qwen05, SRC, null, 10 * GB), { ok: false, reason: "memory_unknown" });
  assert.deepEqual(modelFit(qwen05, SRC, 2 * GB, 10 * GB), { ok: false, reason: "too_little_memory" });
  assert.deepEqual(modelFit(qwen15, SRC, 4 * GB, 10 * GB), { ok: false, reason: "too_little_memory" });
  assert.deepEqual(modelFit(qwen05, SRC, 4 * GB, 0.5 * GB), { ok: false, reason: "too_little_storage" });
  assert.deepEqual(modelFit(qwen05, SRC, 4 * GB, 10 * GB), { ok: true });
});

test("hash check: exact match only (case-insensitive); unreadable or malformed never matches", () => {
  assert.equal(hashMatches("a".repeat(64), "A".repeat(64)), true);
  assert.equal(hashMatches("a".repeat(64), "b".repeat(64)), false);
  assert.equal(hashMatches("a".repeat(64), null), false);
  assert.equal(hashMatches("a".repeat(64), "a".repeat(63)), false);
});

test("scoring: verified kinds count; invented quotes and negated asks don't", () => {
  const bank = PRE_SCREEN_CASES.find((c) => c.id === "bank-code")!;
  const good = scorePreScreen(bank, JSON.stringify({ requests: [{ kind: "share_code", quote: "reply with the 6-digit code we just sent you" }, { kind: "send_money", quote: "send $500 now" }] }));
  assert.deepEqual(good.found, ["share_code"]);
  assert.equal(good.truePositives, 1);
  assert.equal(good.missed, 1);       // call_or_reply not found
  assert.equal(good.dropped, 1);      // the invented quote
  const negated = PRE_SCREEN_CASES.find((c) => c.id === "negated")!;
  assert.equal(scorePreScreen(negated, JSON.stringify({ requests: [{ kind: "share_code", quote: "share a code" }] })).falsePositives, 0);
  assert.equal(scorePreScreen(bank, null).ok, false);
});

test("summary: precision, recall, accepted explanations, median time, one-line wording", () => {
  const bank = PRE_SCREEN_CASES.find((c) => c.id === "bank-code")!;
  const s = summarise("Qwen 2.5 0.5B", [scorePreScreen(bank, JSON.stringify({ requests: [{ kind: "share_code", quote: "reply with the 6-digit code we just sent you" }] }))], [
    { raw: "Apollo is growling. Don't reply. Call CommBank on the number on your card.", settled: { stateName: "Growling", verdict: "Asks for a code.", why: [], recommendation: "Don't reply. Call CommBank on the number on your card." } },
    { raw: "This is safe.", settled: { stateName: "Growling", verdict: "Asks for a code.", why: [], recommendation: "Don't reply." } },
    { raw: null, settled: { stateName: "Growling", verdict: "x", why: [], recommendation: "y" } },
  ], [3000, 1000, 2000]);
  assert.equal(s.precision, 1);
  assert.equal(s.recall, 0.5);
  assert.equal(s.explanationsAccepted, 1);
  assert.deepEqual(s.rejections, { reassurance: 1 });
  assert.equal(s.failedCalls, 1);
  assert.equal(s.medianMs, 2000);
  assert.equal(summaryLine(s), "Finds requests 50% · correct 100% · explanations 1/3 · 2.0 s per call · 1 failed");
});


test("licences: every model ships its text; Llama carries the agreement, the credit and the notice", () => {
  for (const m of FALLBACK_MODELS) assert.ok(m.licenceText === "llama_3_2" || m.licenceText === "apache_2_0", m.id);
  assert.equal(modelById("llama3.2-1b-instruct-q4km")!.licenceText, "llama_3_2");
  assert.match(LLAMA_3_2_LICENSE, /^LLAMA 3\.2 COMMUNITY LICENSE AGREEMENT/);
  assert.match(LLAMA_3_2_LICENSE, /prominently display “Built with Llama”/);
  assert.equal(BUILT_WITH_LLAMA, "Built with Llama");
  assert.equal(LLAMA_3_2_NOTICE, "Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright © Meta Platforms, Inc. All Rights Reserved.");
  assert.match(APACHE_2_0_LICENSE, /Apache License\s+Version 2\.0, January 2004/);
});
