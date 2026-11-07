// Higgins' plain English is shown only when it passed its Fidelity Check; otherwise Apollo's own wording is shown.
import { test } from "node:test";
import assert from "node:assert/strict";

import { buildReport, plainReport, shownPlainEnglish, stepText } from "../src/domain/reportSections.ts";
import type { HigginsResponse, PlainEnglish } from "../src/investigation/types.ts";

const plain: PlainEnglish = {
  version: 1, renderer: "apollo", mode: "plain",
  result: "Concerning. This uses ANZ's name, but its link goes to anz-secure-login.co, which isn't ANZ's domain.",
  severity: "How serious: you need to act. See what you can do.",
  established: [{ text: "The link anz-secure-login.co was registered 3 days ago.", detail: "Seen directly by TC Hawkeye · High confidence",
    explain: "A domain is the name part of a web or email address, the part that says who runs it.", findingId: "f1" }],
  means: ["To protect your account, don't enter anything on it."], matters: ["Anything typed into that link goes to whoever runs it."],
  todo: ["Don't open anz-secure-login.co and don't enter anything on it."], uncertain: ["Apollo can't confirm who actually sent this."],
  how: ["TC Hawkeye checked the submitted material using official source checks.", "Nothing was opened or fetched from the destination."],
  fidelity: { status: "PASS", failures: [] }, attempts: 1, attemptFailures: [[]],
};

const response: HigginsResponse = {
  revision: 1, overview: "This uses ANZ's name, but its link goes to anz-secure-login.co, which is not ANZ's domain.",
  explanationMarkdown: "**What it means**\nIn order to protect your account, do not enter anything on it.", assessment: "concern_found", outcome: "concerning",
  attention: "action_needed", attentionReason: "Anything typed into that link goes to whoever runs it.",
  findings: [{ id: "f1", text: "The link anz-secure-login.co was registered 3 days ago.", basis: "observation", confidence: "high", evidenceIds: [], sourceIds: [] }],
  uncertainties: ["Apollo is unable to confirm who actually sent this."], scope: "TC Hawkeye checked the submitted material using official source checks.",
  sourceIds: ["s1"], remainingEvidenceIds: [],
  actions: [{ id: "a1", kind: "instruction", label: "Don't use the link", instruction: "Do not open anz-secure-login.co and do not enter anything on it.", capabilityId: null,
    executionDescriptorId: null, requiresUserGesture: false, sourceIds: [], desiredField: null, desiredValue: null }],
  recommendedActionId: "a1", question: null, completion: "complete", plainEnglish: plain,
};

const sources = [
  { id: "s1", url: "https://www.scamwatch.gov.au", title: "Scamwatch", retrievedAt: "2026-06-01T00:00:00Z", retrieval: "fetched" as const, authority: "official" as const, authorityBasis: "" },
  { id: "s2", url: "https://other.example.org", title: "Not cited", retrievedAt: "2026-06-01T00:00:00Z", retrieval: "search_result" as const, authority: "unknown" as const, authorityBasis: "" },
];

test("a passed plain English is shown: answer, severity, every finding with who and how firmly, and the jargon explained", () => {
  const shown = shownPlainEnglish(response);
  assert.ok(shown);
  const r = plainReport(shown, sources, response.sourceIds);
  assert.deepEqual(r.answer, [plain.result]);
  assert.deepEqual(plainReport({ ...shown, subject: "What it is: the ANZ link anz-secure-login.co." }).answer,
    [plain.result, "What it is: the ANZ link anz-secure-login.co."], "the subject line is never dropped");
  assert.equal(r.severity, plain.severity);
  assert.deepEqual(r.found, [{ text: plain.established[0].text, detail: plain.established[0].detail, explain: plain.established[0].explain, category: null }]);
  assert.deepEqual(r.means, [...plain.means, ...plain.matters]);
  assert.deepEqual(r.uncertain, plain.uncertain);
  assert.deepEqual(r.how, [plain.how.join(" ")]);
  assert.deepEqual(r.sources.map((s) => s.id), ["s1"], "only the sources the result relied on");
});

test("a failed check, or no plain English at all, shows Apollo's own wording", () => {
  assert.equal(shownPlainEnglish({ ...response, plainEnglish: { ...plain, mode: "literal", fidelity: { status: "FAIL", failures: [{ code: "FINDING_ALTERED", ref: "finding:0", detail: "" }] } } }), null);
  assert.equal(shownPlainEnglish({ ...response, plainEnglish: { ...plain, fidelity: { status: "FAIL", failures: [] } } }), null);
  assert.equal(shownPlainEnglish({ ...response, plainEnglish: null }), null);
  assert.equal(shownPlainEnglish({ ...response, plainEnglish: undefined }), null);
  const apollo = buildReport({ overview: response.overview, explanationMarkdown: response.explanationMarkdown, findings: response.findings });
  assert.equal(apollo.severity, undefined, "Apollo's own wording has no plain-English severity line");
});

test("a repaired plain English that passed is shown", () => {
  assert.ok(shownPlainEnglish({ ...response, plainEnglish: { ...plain, mode: "repaired", attempts: 2 } }));
});

test("each step uses the plain English when it's shown, else Apollo's wording", () => {
  assert.equal(stepText(response, 0), plain.todo[0]);
  assert.equal(stepText({ ...response, plainEnglish: { ...plain, mode: "literal" } }, 0), response.actions[0].instruction);
  assert.equal(stepText({ ...response, plainEnglish: null }, 0), response.actions[0].instruction);
});
