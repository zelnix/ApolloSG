// Past cases judged again under the current rules, on this device, from the kept original (src/domain/triage/rejudge.ts).
import test from "node:test";
import assert from "node:assert/strict";
import { analyseEmail } from "../src/domain/emailAnalysis.ts";
import { analyseMessage } from "../src/domain/messageAnalysis.ts";
import { buildEmailProfile } from "../src/domain/triage/emailEvidence.ts";
import { evaluateTriage } from "../src/domain/triage/engine.ts";
import { emailTriageEvidence, messageTriageEvidence } from "../src/domain/triage/evidence.ts";
import { REJUDGE_VERSION, emailPatrolState, rejudgeCandidate, rejudgeEvent } from "../src/domain/triage/rejudge.ts";
import { REJUDGED_LINE } from "../src/domain/luddish/present.ts";
import type { TriageInvestigationRecord } from "../src/domain/triage/contract.ts";
import type { PatrolEvent } from "../src/domain/types.ts";
import type { OriginalSource } from "../src/store/originalSource.ts";

const NOW = "2026-11-01T03:00:00.000Z";
const kept = (text: string, from = "", subject = ""): OriginalSource => ({
  kind: "text", text, capturedAt: NOW, origin: "this_device",
  fields: [...(from ? [{ label: "From", value: from }] : []), ...(subject ? [{ label: "Subject", value: subject }] : [])],
});
/** What an earlier, broader rule recorded: a Possible Threat for something the current rules read differently. */
const flagged = (t: TriageInvestigationRecord): TriageInvestigationRecord => ({ ...t, outcome: "POSSIBLE_THREAT_IDENTIFIED", rulesMet: ["MSG-02"] });
const event = (over: Partial<PatrolEvent>): PatrolEvent => ({
  event_id: "e1", device_id: "local", category: "message", state: "growling", status: "active", headline: "OTP or security code request",
  what_happened: "x", why: ["Asks for a code"], what_to_do: "Don't reply", indicator_host: null, indicator_digest: null, local_indicator: null,
  verified_block: false, adapter_label: "apollo", occurred_at: "2026-10-30T01:00:00.000Z", resolved_at: null, trust_allowed: false,
  claimed_brand: null, scenario: null, investigation_case_id: null, ...over,
} as PatrolEvent);

const CODE_DELIVERY = "Your Microsoft verification code is 482913. Don't share this code with anyone.";
const CODE_REQUEST = "Hi, it's Telstra. Read me the verification code we texted you so I can fix your account.";

test("a genuine code delivery flagged by the earlier rules is cleared, and the earlier record is kept", () => {
  const now = evaluateTriage(messageTriageEvidence({ analysis: analyseMessage("Microsoft", CODE_DELIVERY) }));
  const old = flagged(now);
  const next = rejudgeEvent(event({ triage_investigation: old }), kept(CODE_DELIVERY, "Microsoft"), NOW);
  assert.ok(next, "the case changes");
  assert.equal(next!.triage_investigation!.outcome, "NO_THREAT_IDENTIFIED");
  assert.equal(next!.triage_investigation!.rejudgedUnder, REJUDGE_VERSION);
  assert.equal(next!.state, "resting");
  assert.equal(next!.status, "resolved");
  assert.equal(next!.resolved_at, NOW);
  assert.equal(next!.why[0], REJUDGED_LINE);
  assert.deepEqual(next!.triage_history, [old], "the earlier judgement stays in the case's history");
  assert.equal(next!.occurred_at, "2026-10-30T01:00:00.000Z", "the first detection time is kept");
});

test("a real request for a code still reads as one: nothing changes", () => {
  const analysis = analyseMessage("+61400000000", CODE_REQUEST);
  const triage = evaluateTriage(messageTriageEvidence({ analysis }));
  assert.equal(triage.outcome, "POSSIBLE_THREAT_IDENTIFIED");
  assert.equal(rejudgeEvent(event({ state: analysis.state, triage_investigation: triage }), kept(CODE_REQUEST, "+61400000000"), NOW), null);
});

test("a recorded threat-list match on the case's link still counts: no lookup is repeated, none is dropped", () => {
  const text = `${CODE_DELIVERY} Details: https://evil-login.example/verify`;
  const analysis = analyseMessage("Microsoft", text);
  const triage = evaluateTriage(messageTriageEvidence({ analysis, linkOutcome: "POSSIBLE_THREAT_IDENTIFIED", linkRulesMet: ["LINK-01"] }));
  assert.equal(triage.outcome, "POSSIBLE_THREAT_IDENTIFIED");
  const why = ["evil-login.example is a known malicious destination — Apollo's threat intelligence confirms it."];
  assert.equal(rejudgeEvent(event({ state: "barking", why, triage_investigation: triage }), kept(text, "Microsoft"), NOW), null);
});

test("only on-device Triage of texts and emails with a kept original, never a case with an investigation", () => {
  const old = flagged(evaluateTriage(messageTriageEvidence({ analysis: analyseMessage("Microsoft", CODE_DELIVERY) })));
  assert.equal(rejudgeEvent(event({ triage_investigation: old, investigation_case_id: "c1" }), kept(CODE_DELIVERY), NOW), null, "its investigation's result stands");
  assert.equal(rejudgeEvent(event({ triage_investigation: old, status: "trusted" }), kept(CODE_DELIVERY), NOW), null);
  assert.equal(rejudgeEvent(event({ triage_investigation: old }), null, NOW), null, "nothing to re-read");
  assert.equal(rejudgeCandidate(event({ category: "website", triage_investigation: old })), false);
  assert.equal(rejudgeCandidate(event({ triage_investigation: null })), false);
});

test("a case the person already handled stays handled", () => {
  const text = "Your parcel is held. Reply with your card number and CVV to pay the customs fee.";
  const old = { ...evaluateTriage(messageTriageEvidence({ analysis: analyseMessage("", text) })), outcome: "NO_THREAT_IDENTIFIED" as const, rulesMet: [] };
  const next = rejudgeEvent(event({ triage_investigation: old, state: "ears_up", status: "resolved", resolved_at: "2026-10-30T02:00:00.000Z" }), kept(text), NOW);
  assert.ok(next);
  assert.equal(next!.triage_investigation!.outcome, "POSSIBLE_THREAT_IDENTIFIED");
  assert.equal(next!.status, "resolved");
  assert.equal(next!.resolved_at, "2026-10-30T02:00:00.000Z");
});

test("a case Apollo had already closed is never reopened by a re-judge, even when the current rules find more", () => {
  const text = "Your parcel is held. Reply with your card number and CVV to pay the customs fee.";
  const old = { ...evaluateTriage(messageTriageEvidence({ analysis: analyseMessage("", text) })), outcome: "NO_THREAT_IDENTIFIED" as const, rulesMet: [] };
  const next = rejudgeEvent(event({ triage_investigation: old, state: "resting", status: "resolved", resolved_at: "2026-10-30T02:00:00.000Z" }), kept(text), NOW);
  assert.ok(next);
  assert.equal(next!.status, "resolved");
  assert.equal(next!.resolved_at, "2026-10-30T02:00:00.000Z");
});

test("an original kept for more than 24 hours is gone: the case isn't re-judged from it", () => {
  const old = flagged(evaluateTriage(messageTriageEvidence({ analysis: analyseMessage("Microsoft", CODE_DELIVERY) })));
  const stale = { ...kept(CODE_DELIVERY, "Microsoft"), capturedAt: "2026-10-31T02:59:00.000Z" };
  assert.equal(rejudgeEvent(event({ triage_investigation: old }), stale, NOW), null);
});

test("an email that only mentions a brand is no longer read as that brand", () => {
  const body = "This week at Harvey's Electronics: the new Apple iPhone and Samsung Galaxy are in store. Sign in to your Harvey's account to see member prices.";
  const fields = { from: "Harvey's Electronics <news@harveys-electronics.example>", subject: "New Apple iPhone in store" };
  const analysis = analyseEmail(body, fields);
  assert.equal(analysis.claimedBrand, null, "the retailer speaks as itself");
  const profile = buildEmailProfile({ via: "pasted", analysis });
  const current = evaluateTriage(emailTriageEvidence({ analysis, profile }));
  assert.notEqual(current.outcome, "POSSIBLE_THREAT_IDENTIFIED");
  const old = { ...current, outcome: "POSSIBLE_THREAT_IDENTIFIED" as const, rulesMet: ["EMAIL-01"] };
  const next = rejudgeEvent(event({ category: "email", headline: "Email: Claims to be Apple", claimed_brand: "Apple", evidence_profile: profile, triage_investigation: old }),
    { ...kept(body, fields.from, fields.subject), kind: "email" }, NOW);
  assert.ok(next);
  assert.equal(next!.triage_investigation!.outcome, current.outcome);
  assert.equal(next!.claimed_brand, null);
  assert.ok(!/apple/i.test(next!.headline), next!.headline);
  assert.equal(next!.state, "resting", "a newsletter with its own links is filed as checked, not as something to look at");
  assert.equal(next!.status, "resolved");
});

test("an ordinary sign-in request counts only with supporting context", () => {
  const newsletter = analyseEmail("From: Harvey's Electronics <news@harveys-electronics.example>\nSubject: The new Apple iPhone is in store\n\nSign in to your Harvey's account to see member prices at https://www.harveys-electronics.example/members");
  assert.notEqual(newsletter.scenario, "E02");
  assert.equal(newsletter.handoff.account, false);
  const phish = analyseEmail("From: CommBank <alerts@commbank-notices.example>\nSubject: Verify your account\n\nYour account will be suspended within 24 hours unless you sign in at https://commbank-verify-secure.example/login");
  assert.equal(phish.scenario, "E01");
  assert.equal(phish.state, "barking");
});

test("a caution with no warning sign behind it is filed as checked; a warning or a guard finding never is", () => {
  assert.equal(emailPatrolState("ears_up", "resting", "NO_THREAT_IDENTIFIED"), "resting");
  assert.equal(emailPatrolState("ears_up", "resting", "LIMITED_UNABLE_TO_DETERMINE"), "ears_up");
  assert.equal(emailPatrolState("ears_up", "growling", "NO_THREAT_IDENTIFIED"), "ears_up");
  assert.equal(emailPatrolState("growling", "resting", "NO_THREAT_IDENTIFIED"), "growling");
  assert.equal(emailPatrolState("barking", "resting", "POSSIBLE_THREAT_IDENTIFIED"), "barking");
});
