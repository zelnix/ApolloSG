// Follow-ups on a finished Magnum DI investigation, Patrol explanations and the health check's AI lines are all
// answered on the device from records — never by Gemini.
// Run: node --test tests/deterministicHiggins.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { investigationFollowUp, isFinished, newItems } from "../src/higgins/followUp.ts";
import { explainIssue } from "../src/higgins/issueExplanation.ts";
import { providerStatusLines } from "../src/health/providerStatus.ts";

const RESPONSE = {
  revision: 1, overview: "The text claiming to be from Australia Post is a delivery scam.", explanationMarkdown: "",
  assessment: "concern_found", attention: "action_needed", attentionReason: "The link leads to a look-alike site.",
  findings: [{ id: "f1", text: "The link domain is not auspost.com.au.", basis: "observation", confidence: "high", evidenceIds: ["e1"], sourceIds: [] }],
  uncertainties: ["Who sent it could not be traced."], scope: "The message text and its link.", sourceIds: [], remainingEvidenceIds: [],
  actions: [{ id: "a1", kind: "instruction", label: "Delete the message", instruction: "Delete it and don't tap the link.", capabilityId: null,
    executionDescriptorId: null, requiresUserGesture: false, sourceIds: [], desiredField: null, desiredValue: null }],
  recommendedActionId: "a1", question: null, completion: "complete",
} as const;
const response = RESPONSE as unknown as Parameters<typeof investigationFollowUp>[0];

test("a follow-up that brings something new is answered from the record and says nothing new was checked", () => {
  for (const [question, label] of [
    ["Is this link safe too? https://auspost-redelivery.top/track", "a link"],
    ["They also emailed me from support@auspost-help.com — is that them?", "an email address"],
    ["A number called me after, 0412 345 678, is that the same scam?", "a phone number"],
  ] as const) {
    const answer = investigationFollowUp(response, [], question);
    assert.ok(answer.answer.startsWith(`You've mentioned something new (${label}) that wasn't part of this investigation.`), question);
    assert.match(answer.answer, /nothing new has been checked/);
    assert.equal(answer.answeredBy, "apollo");
  }
});

test("the same wording as the backend presenter for the common intents", () => {
  assert.equal(investigationFollowUp(response, [], "What should I do?").answer, "What Magnum DI recommends:\n• Delete the message: Delete it and don't tap the link.");
  assert.equal(investigationFollowUp(response, [], "What should I do?", "", "tc_flyby_official").answer, "What TC FlyBy recommends:\n• Delete the message: Delete it and don't tap the link.");
  assert.equal(investigationFollowUp(response, [], "What wasn't established?").answer,
    "What Magnum DI couldn't establish:\n• Who sent it could not be traced.\n\nWhat it checked: The message text and its link.");
  assert.match(investigationFollowUp(response, [], 'I did "Delete the message". Please re-check using the fresh observation Apollo just recorded.').answer, /isn't re-assessed/);
  const unanswered = investigationFollowUp(response, [], "Tell the bank for me");
  assert.equal(unanswered.intent, "unanswered");
  assert.doesNotMatch(unanswered.answer, /Magnum DI will investigate/);
});

test("new items: emails aren't double-counted as links, short numbers aren't phone numbers", () => {
  assert.deepEqual(newItems("from support@auspost-help.com"), ["an email address"]);
  assert.deepEqual(newItems("I lost $250 on 12 May"), []);
  assert.deepEqual(newItems("call +61 412 345 678 or visit www.example.com"), ["a link", "a phone number"]);
});

test("only a complete or partial result with no pending question counts as finished", () => {
  assert.equal(isFinished(response), true);
  assert.equal(isFinished({ ...response, completion: "partial" }), true);
  assert.equal(isFinished({ ...response, completion: "waiting_user", question: { id: "q1" } }), false);
  assert.equal(isFinished(null), false);
});

test("a Patrol explanation lists Apollo's own findings with their provenance", () => {
  const text = explainIssue({
    gate: "link", issue_summary: "Look-alike bank site", assessment_state: "barking",
    findings: [{ summary: "The page copied CommBank's login.", provenance: "observed", status: "confirmed" }],
    uncertainty: ["No protective block was confirmed for this issue."], confirmed_protective_actions: [], user_reported_actions: [],
    available_actions: [{ label: "Use the next action on this result", instruction: "Don't enter your password." }],
  });
  assert.match(text, /^Here's what Apollo recorded about this — explained from Apollo's own findings, with no new analysis:/);
  assert.match(text, /Look-alike bank site — significant concern\./);
  assert.match(text, /• The page copied CommBank's login\. \(observed by Apollo; confirmed\)/);
  assert.match(text, /What you can do:\n• Use the next action on this result: Don't enter your password\./);
});

test("a quiet Patrol state is explained as what the checks found, never as all clear", () => {
  const text = explainIssue({
    gate: "link", issue_summary: "Link checked", assessment_state: "resting", findings: [], uncertainty: [],
    confirmed_protective_actions: [], user_reported_actions: [],
  });
  assert.match(text, /Link checked — no concern found within the checks that completed\./);
  assert.doesNotMatch(text, /all clear/i);
});

test("health check AI lines come from saved records", () => {
  assert.deepEqual(providerStatusLines(null), []);
  assert.deepEqual(providerStatusLines({ keyConfigured: true, lastCall: null }), ["AI service key: set.", "Last AI call: none recorded yet."]);
  const failed = providerStatusLines({ keyConfigured: true, lastCall: { at: "2026-06-02T07:00:00Z", worked: false, failureCode: "provider_configuration", purpose: "investigation" } }, "en-AU");
  assert.match(failed[1], /it failed — the AI service isn't set up correctly — often its billing or key\.$/);
  assert.match(providerStatusLines({ keyConfigured: false, lastCall: null })[0], /not set/);
});
