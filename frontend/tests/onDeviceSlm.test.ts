// On-device SLM: advisory only. Quotes must be the message's own words, negated asks don't count, the SLM can't move
// a result, and a re-wording that reassures, adds a link/number or dismisses the advice is rejected.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  advisoryFor, checkExplanation, extractJsonObject, locateQuote, parsePreScreen, prepareSlmInput, SLM_MAX_INPUT_CHARS,
  type SettledResult,
} from "../src/slm/core.ts";

const MSG = "CommBank: Your account is locked. Verify within 24 hours or it will be closed. Pay the $2 fee at commbank-help.xyz and reply with the code we sent.";

test("JSON is pulled out of fenced or chatty replies; junk gives null", () => {
  assert.deepEqual(extractJsonObject('Sure!\n```json\n{"a":{"b":"}"}}\n```'), { a: { b: "}" } });
  assert.equal(extractJsonObject("no json here"), null);
  assert.equal(extractJsonObject("{broken"), null);
});

test("quotes are matched verbatim (case/space-insensitive); short quotes prove nothing", () => {
  assert.ok(locateQuote(MSG, "verify   WITHIN 24 hours") >= 0);
  assert.equal(locateQuote(MSG, "send gift cards"), -1);
  assert.equal(locateQuote(MSG, "Pay"), -1);
});

test("pre-screen keeps verified pointers and drops invented ones", () => {
  const raw = JSON.stringify({
    requests: [
      { kind: "send_money", quote: "Pay the $2 fee" },
      { kind: "share_code", quote: "reply with the code we sent" },
      { kind: "remote_access", quote: "install AnyDesk now" },      // not in the message
      { kind: "bogus_kind", quote: "Your account is locked" },     // unknown kind
    ],
    organisation: { name: "CommBank", quote: "CommBank: Your account is locked" },
    urgency: { quote: "Verify within 24 hours" },
  });
  const r = parsePreScreen(raw, MSG);
  assert.equal(r.dropped, 2);
  assert.deepEqual(r.hints.map((h) => h.type === "request" ? h.kind : h.type), ["send_money", "share_code", "organisation", "urgency"]);
});

test("a negated ask is not a request", () => {
  const text = "CommBank will never ask you to share a code. Your statement is ready.";
  const r = parsePreScreen(JSON.stringify({ requests: [{ kind: "share_code", quote: "share a code" }] }), text);
  assert.equal(r.hints.length, 0);
  assert.equal(r.dropped, 1);
});

test("an organisation the text doesn't name is dropped", () => {
  const r = parsePreScreen(JSON.stringify({ organisation: { name: "Westpac", quote: "Your account is locked" } }), MSG);
  assert.equal(r.hints.length, 0);
});

test("advisory only shows what the fixed rules missed, and never changes the result", () => {
  const pre = parsePreScreen(JSON.stringify({ requests: [{ kind: "send_money", quote: "Pay the $2 fee" }, { kind: "share_code", quote: "reply with the code we sent" }] }), MSG);
  const covered = advisoryFor(pre, { paymentRequest: true, codeRequest: true });
  assert.equal(covered.extra.length, 0);
  assert.equal(covered.suggestFullCheck, false);
  const missed = advisoryFor(pre, { paymentRequest: true });
  assert.deepEqual(missed.extra.map((h) => h.type === "request" && h.kind), ["share_code"]);
  assert.equal(missed.suggestFullCheck, true);
  assert.equal(missed.changedResult, false);
  assert.equal("state" in missed, false);
});

test("input: credentials removed, whitespace collapsed, length capped", () => {
  assert.ok(prepareSlmInput("x ".repeat(5000)).length <= SLM_MAX_INPUT_CHARS);
  assert.equal(prepareSlmInput("  a \n\n b  "), "a b");
});

const SETTLED: SettledResult = {
  stateName: "Growling",
  verdict: "This message asks for a code and uses a link that isn't CommBank's.",
  why: ["Asks for a code", "Link isn't the bank's own"],
  recommendation: "Don't reply or tap the link. Call CommBank on the number on your card.",
};

test("a faithful re-wording is accepted", () => {
  const r = checkExplanation("Apollo is growling at this one. It asks for a code and the link isn't CommBank's own. Please don't reply or tap it — call CommBank on the number on your card.", SETTLED);
  assert.equal(r.ok, true);
});

test("negated reassurance is fine; plain reassurance is rejected", () => {
  assert.equal(checkExplanation("This message isn't safe to answer. Call CommBank on the number on your card.", SETTLED).ok, true);
  assert.deepEqual(checkExplanation("It's probably safe, but call CommBank to be sure.", SETTLED), { ok: false, reason: "reassurance" });
  assert.deepEqual(checkExplanation("This looks genuine.", SETTLED), { ok: false, reason: "reassurance" });
});

test("new links, new numbers and dismissals are rejected", () => {
  assert.deepEqual(checkExplanation("Call CommBank at commbank.com.au instead.", SETTLED), { ok: false, reason: "new_link" });
  assert.deepEqual(checkExplanation("Call CommBank on 13 22 21.", SETTLED), { ok: false, reason: "new_number" });
  assert.deepEqual(checkExplanation("You can ignore this warning.", SETTLED), { ok: false, reason: "dismissal" });
  assert.deepEqual(checkExplanation("   ", SETTLED), { ok: false, reason: "empty" });
});
