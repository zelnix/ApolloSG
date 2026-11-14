import assert from "node:assert/strict";
import test from "node:test";
import { analyseEmail } from "../src/domain/emailAnalysis.ts";
import { extractSignals } from "../src/domain/messageAnalysis.ts";
import { readRequests } from "../src/domain/requestSignals.ts";
import { evaluateTriage } from "../src/domain/triage/engine.ts";
import { buildEmailProfile } from "../src/domain/triage/emailEvidence.ts";
import { emailTriageEvidence } from "../src/domain/triage/evidence.ts";
import { gateCheckResult } from "../src/domain/gateCheckResult.ts";
import { needsYou, caseCardText } from "../src/domain/caseBriefing.ts";
import { threatCaseStatus } from "../src/domain/threatCase.ts";
import { caseAuditTrail } from "../src/domain/caseAuditTrail.ts";
import { rejudgeEvent } from "../src/domain/triage/rejudge.ts";
import type { PatrolEvent } from "../src/domain/types.ts";
import type { OriginalSource } from "../src/store/originalSource.ts";

// Synthetic notification: no personal evidence or live account links.
const text = "You allowed account-tools.example access to some of your Google Account data person@gmail.com. If you didn't allow account-tools.example access to some of your Google Account data, someone else may be trying to access your Google Account data. Take a moment now to check your account activity and secure your account. Check activity. To make changes at any time to the access that account-tools.example has to your data, go to your Google Account. You received this email to let you know about important changes to your Google Account and services.";
const fields = { from: "Google <no-reply@accounts.google.com>", subject: "Security alert" };
const analysis = () => analyseEmail(text, fields);
const record = () => evaluateTriage(emailTriageEvidence({ analysis: analysis(), profile: buildEmailProfile({ via: "pasted", analysis: analysis() }) }));
const event = (over: Partial<PatrolEvent> = {}): PatrolEvent => ({
  event_id: "local-email", device_id: "this-device", category: "email", state: "barking", status: "active", origin: "apollo",
  headline: "Account alert", what_happened: "Old heuristic warning", why: ["Real account alerts never need you to log in through the email."],
  what_to_do: "Check your account", occurred_at: "2026-11-13T23:00:00Z", resolved_at: null,
  verified_block: false, evidence_profile: buildEmailProfile({ via: "pasted", analysis: analysis() }), triage_investigation: record(), ...over,
} as PatrolEvent);

test("account access notice is not a request to log in or disclose secrets", () => {
  const asks = readRequests(text);
  assert.equal(asks.security_notice, true);
  assert.equal(asks.sign_in_request, false);
  assert.equal(asks.secret_request, false);
  assert.equal(analysis().scenario, "E14");
  assert.equal(analysis().state, "ears_up");
  assert.deepEqual(analysis().urls, ["account-tools.example"]);
  assert.equal(record().outcome, "NO_THREAT_IDENTIFIED");
});

test("email addresses are not link destinations; explicit deceptive URLs remain visible", () => {
  assert.deepEqual(extractSignals("", "Contact person@gmail.com, first.last@accounts.google.com or first.last+alerts@accounts.google.com").urls, []);
  const urls = extractSignals("", "https://accounts.google.com@evil.example/login and https://evil.example/?to=person@gmail.com").urls;
  assert.ok(urls.some((url) => url.includes("evil.example")));
  assert.ok(urls.some((url) => url.startsWith("https://evil.example/")));
});

test("a security notice does not cancel an appended password or code request", () => {
  for (const attack of ["Reply with your password now.", "Send me the verification code we texted you."]) {
    const a = analyseEmail(`${text} ${attack}`, fields);
    assert.equal(a.state, "barking");
    assert.equal(evaluateTriage(emailTriageEvidence({ analysis: a, profile: buildEmailProfile({ via: "pasted", analysis: a }) })).outcome, "POSSIBLE_THREAT_IDENTIFIED");
  }
  assert.equal(readRequests("Please sign in to verify your account at https://evil.example/login").sign_in_request, true);
});

test("recorded clean checks govern Findings and attention without authenticating the sender", () => {
  const e = event();
  const result = gateCheckResult(e);
  assert.ok(result);
  assert.equal(result.label, "Not fully checked");
  assert.match(result.report.found[0].text, /none matched/);
  assert.match(result.report.uncertain.join(" "), /do not establish authenticity/);
  assert.doesNotMatch(JSON.stringify(result.report), /Real account alerts never|why this is a scam/);
  assert.equal(caseCardText(e, "Old scam title").title, result.label);
  assert.equal(needsYou(e), false);
  assert.equal(threatCaseStatus(e), "not_fully_checked");
  const trail = caseAuditTrail({ event: e, investigation: null, trace: null, records: [], verdict: null });
  assert.deepEqual(trail.map((entry) => entry.title), ["Case created", "Higgins Triage completed"]);
  assert.equal(trail[0].at, e.occurred_at);
  assert.equal(trail[1].at, e.triage_investigation!.evaluatedAt);
});

test("committed investigations, matched Gate rules and recorded malicious links retain precedence", () => {
  assert.equal(gateCheckResult(event({ investigation_case_id: "committed-case" })), null);
  assert.equal(gateCheckResult(event({ patrol_record: { investigationCaseId: "case" } as PatrolEvent["patrol_record"] })), null);
  assert.equal(gateCheckResult(event({ verified_block: true })), null);
  assert.equal(gateCheckResult(event({ triage_investigation: { ...record(), rulesMet: ["EMAIL-01"] } }))?.admission, "investigate");
  assert.equal(gateCheckResult(event({ why: ["evil.example is a known malicious destination — confirmed."] })), null);
  assert.equal(gateCheckResult(event({ why: ["Displayed link says google.com but goes to evil.example"] })), null);
});

test("re-reading the original corrects an old warning while retaining its prior record and source", () => {
  const old = { ...record(), outcome: "POSSIBLE_THREAT_IDENTIFIED" as const, rulesMet: ["EMAIL-01"] };
  const source: OriginalSource = { kind: "email", text, capturedAt: "2026-11-13T23:00:00Z", origin: "this_device", fields: [{ label: "From", value: fields.from }, { label: "Subject", value: fields.subject }] };
  const before = JSON.stringify(source);
  const next = rejudgeEvent(event({ triage_investigation: old }), source, "2026-11-14T00:00:00Z");
  assert.ok(next);
  assert.equal(next.state, "resting");
  assert.equal(next.triage_investigation!.outcome, "NO_THREAT_IDENTIFIED");
  assert.deepEqual(next.triage_history, [old]);
  assert.equal(JSON.stringify(source), before);
});

test("a different mailer or link domain alone is a verification concern, not a scam assertion", () => {
  const newsletter = analyseEmail("Our new products are available at https://click.mailchimp.com/catalogue", { from: "Apple <news@campaign.example>" });
  assert.equal(newsletter.state, "growling");
  assert.doesNotMatch(newsletter.verdict, /wasn't sent from Apple|scam/);
  const signIn = analyseEmail("Please sign in to your account at https://portal.example/login", { from: "Microsoft <no-reply@microsoft.com>" });
  assert.equal(signIn.state, "growling");
  assert.doesNotMatch(signIn.why.join(" "), /Real account alerts never/);
});


test("a case linked to an investigation through its Patrol record is not rejudged", () => {
  const source: OriginalSource = { kind: "email", text, capturedAt: "2026-11-13T23:00:00Z", origin: "this_device" };
  assert.equal(rejudgeEvent(event({ patrol_record: { investigationCaseId: "case" } as PatrolEvent["patrol_record"] }), source), null);
});
