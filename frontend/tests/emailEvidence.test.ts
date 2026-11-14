// Email Evidence & Full Headers — on-device parsing, L1–L4 levels, recorded authentication, signals, re-triage.
// Run: node --test tests/emailEvidence.test.ts
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { test } from "node:test";

import { analyseEmail, parseEmail } from "../src/domain/emailAnalysis.ts";
import { looksLikeRawEmail, parseAuthResults, parseOriginalEmail, utf8ToBinary, binaryToBytes } from "../src/domain/triage/emailOriginal.ts";
import { buildEmailProfile, emailFindings, emailLevelFor, mergeEmailProfiles, sameEmail, upgradeSentence } from "../src/domain/triage/emailEvidence.ts";
import { emailTriageEvidence } from "../src/domain/triage/evidence.ts";
import { evaluateTriage, EMAIL_AUTH_NEEDS_ORIGINAL } from "../src/domain/triage/engine.ts";
import { outcomeLabel } from "../src/domain/triage/contract.ts";
import { headerEvidenceFor, analysisSourceFor } from "../src/domain/triage/emailIntake.ts";
import { buildCallProfile } from "../src/domain/triage/callEvidence.ts";
import { buildAppProfile } from "../src/domain/triage/appEvidence.ts";

const sha = async (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");

const PHISH = [
  "Delivered-To: margaret@gmail.com",
  "Received: by 2002:a05:6a20:1234 with SMTP id abc;",
  "        Tue, 14 Jun 2026 09:12:03 -0700 (PDT)",
  "Return-Path: <bounce@mailer-x.ru>",
  "Received: from mailer-x.ru (mailer-x.ru. [203.0.113.9])",
  "        by mx.google.com with ESMTPS id xyz",
  "        for <margaret@gmail.com>; Tue, 14 Jun 2026 09:12:02 -0700 (PDT)",
  "Authentication-Results: mx.google.com;",
  "       spf=fail (google.com: domain of bounce@mailer-x.ru does not designate 203.0.113.9 as permitted sender) smtp.mailfrom=bounce@mailer-x.ru;",
  "       dkim=none;",
  "       dmarc=fail (p=REJECT sp=REJECT dis=QUARANTINE) header.from=commbank.com.au",
  "Authentication-Results: forged.example; spf=pass smtp.mailfrom=commbank.com.au",
  "From: \"CommBank Security\" <security@commbank.com.au>",
  "Reply-To: verify@commbank-help.co",
  "To: margaret@gmail.com",
  "Subject: =?UTF-8?B?VVJHRU5UOiB2ZXJpZnkgeW91ciBOZXRCYW5rIGFjY291bnQ=?=",
  "Date: Tue, 14 Jun 2026 16:12:01 +0000",
  "Message-ID: <123@mailer-x.ru>",
  "MIME-Version: 1.0",
  "Content-Type: multipart/mixed; boundary=\"b1\"",
  "",
  "--b1",
  "Content-Type: text/plain; charset=utf-8",
  "Content-Transfer-Encoding: quoted-printable",
  "",
  "Dear customer, we detected an unusual sign-in. Log in within 24 hours or your account will be suspended:",
  "http://commbank-secure-verify.co/netbank/login",
  "Please have your password ready.",
  "--b1",
  "Content-Type: application/pdf; name=\"statement.pdf\"",
  "Content-Disposition: attachment; filename=\"statement.pdf\"",
  "Content-Transfer-Encoding: base64",
  "",
  "JVBERi0xLjQKJcfsj6IK",
  "--b1--",
  "",
].join("\r\n");

const GENUINE = [
  "Received: from mail-sor-f41.google.com (mail-sor-f41.google.com. [209.85.220.41])",
  "        by mx.google.com with SMTPS id q; Mon, 13 Jun 2026 20:00:00 -0700 (PDT)",
  "Authentication-Results: mx.google.com; dkim=pass header.i=@abc.net.au header.s=s1 header.b=AbC; spf=pass smtp.mailfrom=news@abc.net.au; dmarc=pass (p=NONE) header.from=abc.net.au",
  "ARC-Seal: i=1; a=rsa-sha256; t=1; cv=none; d=google.com; s=arc-20160816; b=x",
  "DKIM-Signature: v=1; a=rsa-sha256; d=abc.net.au; s=s1; h=from; b=y",
  "From: ABC News <news@abc.net.au>",
  "Subject: Your Thursday briefing",
  "Date: Mon, 13 Jun 2026 20:00:00 -0700",
  "Message-ID: <briefing-1@abc.net.au>",
  "Content-Type: text/html; charset=utf-8",
  "",
  "<p>Good morning. Read the full briefing: <a href=\"https://www.abc.net.au/news/briefing\">here</a></p>",
].join("\r\n");

async function original(text: string) { return parseOriginalEmail(utf8ToBinary(text), sha); }

test("an original .eml is parsed on the device: headers, encoded subject, MIME, fingerprinted attachment", async () => {
  const parsed = await original(PHISH);
  const t = parsed.technical;
  assert.equal(parsed.fullHeaders, true);
  assert.equal(t.subject, "URGENT: verify your NetBank account");
  assert.equal(t.from?.address, "security@commbank.com.au");
  assert.equal(t.replyTo[0].domain, "commbank-help.co");
  assert.equal(t.returnPath, "bounce@mailer-x.ru");
  assert.equal(t.messageId, "<123@mailer-x.ru>");
  assert.equal(t.received.length, 2);
  assert.equal(t.received[1].by, "mx.google.com");
  assert.equal(t.mime.type, "multipart/mixed");
  assert.equal(t.attachments.length, 1);
  assert.equal(t.attachments[0].name, "statement.pdf");
  assert.match(t.attachments[0].sha256 ?? "", /^[a-f0-9]{64}$/);
  assert.ok(t.urls.includes("http://commbank-secure-verify.co/netbank/login"));
  assert.equal(parsed.sha256, await sha(binaryToBytes(utf8ToBinary(PHISH))));
  assert.ok(parsed.bodyText.includes("unusual sign-in"));
});

test("authentication is read from the TOPMOST Authentication-Results and credited to the server that received it", async () => {
  const t = (await original(PHISH)).technical;
  assert.equal(t.recordedAuth?.authservId, "mx.google.com");
  assert.equal(t.recordedAuth?.spf[0].result, "fail");
  assert.equal(t.recordedAuth?.dmarc[0].result, "fail");
  assert.equal(t.recordedAuthConfirmed, true, "mx.google.com is one of the servers that delivered it");
  assert.equal(t.furtherAuthResults, 1, "the forged lower header is counted, never used");
});

test("a server that writes no authserv-id (Microsoft 365) is parsed without losing its first result", () => {
  const auth = parseAuthResults("spf=pass (sender IP is 1.2.3.4) smtp.mailfrom=contoso.com; dkim=pass (signature was verified) header.d=contoso.com;dmarc=pass action=none header.from=contoso.com;compauth=pass reason=100");
  assert.equal(auth.authservId, "unknown");
  assert.equal(auth.spf[0].result, "pass");
  assert.equal(auth.dkim[0].props["header.d"], "contoso.com");
  assert.equal(auth.dmarc[0].result, "pass");
});

test("levels: pasted/screenshot L1, shared L2, original with full headers L3, retrieved from the mailbox L4", () => {
  assert.equal(emailLevelFor("pasted", false), "L1");
  assert.equal(emailLevelFor("screenshot", false), "L1");
  assert.equal(emailLevelFor("shared", false), "L2");
  assert.equal(emailLevelFor("eml_file", true), "L3");
  assert.equal(emailLevelFor("raw_source", true), "L3");
  assert.equal(emailLevelFor("eml_file", false), "L2", "an 'original' with no delivery headers can't be L3");
  assert.equal(emailLevelFor("connected_mailbox", true), "L4");
});

test("L3 profile: recorded results with attribution, statuses, and investigation signals (not proof)", async () => {
  const parsed = await original(PHISH);
  const { raw, fields } = analysisSourceFor(parsed);
  const profile = buildEmailProfile({ via: "eml_file", original: parsed, analysis: analyseEmail(raw, fields, headerEvidenceFor(parsed)), keptOnDevice: true });
  assert.equal(profile.level, "L3");
  assert.equal(profile.label, "L3 — Original Message");
  assert.equal(profile.classifiedBy, "Wright Triage");
  const row = (id: string) => profile.capabilities.find((c) => c.id === id)!;
  assert.equal(row("spf").status, "recorded");
  assert.match(row("spf").value ?? "", /^fail \(mailer-x\.ru\)$/);
  assert.match(row("spf").note ?? "", /Recorded by mx\.google\.com, the mail server that received this email\. ApolloSG reports this result as recorded and didn't re-check it\./);
  assert.equal(row("dkim").value, "none");
  assert.equal(row("original_message").status, "observed");
  assert.equal(row("provider_provenance").status, "unavailable");
  assert.equal(row("received_chain").status, "recorded");
  const ids = profile.signals.map((s) => s.id);
  for (const id of ["reply_to_differs", "return_path_differs", "spf_failed", "dmarc_failed", "message_id_differs"]) assert.ok(ids.includes(id), id);
  assert.ok(!ids.includes("recorder_unconfirmed"));
});

test("L1 profile: no header capability is claimed and authentication says it needs the original", () => {
  const analysis = analyseEmail("From: security@commbank.com.au\nSubject: verify\n\nLog in now http://x.co/login");
  const profile = buildEmailProfile({ via: "pasted", analysis });
  assert.equal(profile.level, "L1");
  assert.equal(profile.auth, null);
  for (const id of ["spf", "dkim", "dmarc", "full_headers", "return_path", "received_chain"]) {
    assert.equal(profile.capabilities.find((c) => c.id === id)?.status, "unavailable", id);
  }
  assert.equal(profile.capabilities.find((c) => c.id === "dmarc")?.note, "Needs the original email with its full headers.");
});

test("a preview inbox email is processed exactly as one retrieved from the mailbox — only tagged Simulated", () => {
  const analysis = analyseEmail("From: security@commbank.com.au\nSubject: verify\n\nLog in now http://x.co/login");
  const sample = buildEmailProfile({ via: "connected_mailbox", analysis, simulated: true });
  const live = buildEmailProfile({ via: "connected_mailbox", analysis });
  assert.equal(sample.simulated, true);
  assert.equal(live.simulated, undefined);
  assert.deepEqual([sample.level, sample.label, sample.viaLabel, sample.capabilities], [live.level, live.label, live.viaLabel, live.capabilities]);
  assert.equal(emailLevelFor("connected_mailbox", false), sample.level);
  // Same level and rules as a shared email without headers, described as what it is: from the mailbox.
  assert.equal(live.level, "L2");
  assert.equal(live.label, "L2 — Mailbox Email");
  assert.match(live.basis, /retrieved the email from your connected mailbox, but not its full headers/);
  assert.equal(live.rank, buildEmailProfile({ via: "shared", analysis }).rank);
  assert.equal(buildEmailProfile({ via: "shared", analysis }).label, "L2 — Shared Email");
});

test("a preview sample caller and app are checked exactly as entered and picked ones — only tagged Simulated", () => {
  const rep = { number: "+61412345678", decision: "review", fraud_score: 60, checked_at: "2026-10-27T10:00:00Z" } as never;
  const call = buildCallProfile({ via: "entered", number: "+61412345678", reputation: rep, simulated: true });
  const liveCall = buildCallProfile({ via: "entered", number: "+61412345678", reputation: rep });
  assert.equal(call.simulated, true);
  assert.equal(liveCall.simulated, undefined);
  assert.deepEqual([call.level, call.label, call.viaLabel, call.capabilities], [liveCall.level, liveCall.label, liveCall.viaLabel, liveCall.capabilities]);
  const appArgs = { via: "picked" as const, name: "QuickSupport", source: "play_store" as const, ticked: [], device: null, analysis: { remoteCapable: true, claimedBrand: null } };
  const app = buildAppProfile({ ...appArgs, simulated: true });
  assert.equal(app.simulated, true);
  assert.deepEqual([app.level, app.label, app.capabilities], [buildAppProfile(appArgs).level, buildAppProfile(appArgs).label, buildAppProfile(appArgs).capabilities]);
});

test("Triage: an L1 email can't present sender authentication as checked — 'No threat found by available checks'", () => {
  const analysis = analyseEmail("From: Coles <receipts@coles.com.au>\nSubject: Your receipt\n\nThanks for shopping with us. Total $64.20.");
  const profile = buildEmailProfile({ via: "pasted", analysis });
  const record = evaluateTriage(emailTriageEvidence({ analysis, profile }));
  assert.equal(record.sourceType, "email");
  assert.equal(record.outcome, "NO_THREAT_IDENTIFIED");
  assert.equal(outcomeLabel(record), "No threat found by available checks");
  assert.ok(record.incompleteChecks?.some((c) => c.check === "sender_authentication" && c.failure === "original_not_provided"));
  const r11 = record.rules.find((r) => r.ruleId === "EMAIL-11")!;
  assert.equal(r11.result, "not_applicable");
  assert.deepEqual(r11.evidence, [EMAIL_AUTH_NEEDS_ORIGINAL]);
  assert.equal(record.coverageGaps.length, 0, "missing headers never makes an email Limited");
});

test("Triage: the L3 original's recorded DMARC failure with a login request meets EMAIL-11, credited to the receiving server", async () => {
  const parsed = await original(PHISH);
  const { raw, fields } = analysisSourceFor(parsed);
  const analysis = analyseEmail(raw, fields, headerEvidenceFor(parsed));
  const profile = buildEmailProfile({ via: "eml_file", original: parsed, analysis });
  const record = evaluateTriage(emailTriageEvidence({ analysis, profile }));
  assert.equal(record.outcome, "POSSIBLE_THREAT_IDENTIFIED");
  const r11 = record.rules.find((r) => r.ruleId === "EMAIL-11")!;
  assert.equal(r11.result, "met");
  assert.match(r11.evidence[0], /recorded by mx\.google\.com \(spf, dmarc\)/);
  assert.equal(record.rules.find((r) => r.ruleId === "EMAIL-08")?.result, "met", "Reply-To to another domain with a login request");
  assert.ok(!record.incompleteChecks?.some((c) => c.check === "sender_authentication"));
});

test("Triage: a genuine L3 newsletter with passing results is not made a threat by authentication alone", async () => {
  const parsed = await original(GENUINE);
  const { raw, fields } = analysisSourceFor(parsed);
  const analysis = analyseEmail(raw, fields, headerEvidenceFor(parsed));
  const profile = buildEmailProfile({ via: "eml_file", original: parsed, analysis });
  assert.equal(profile.auth?.dmarc, "pass");
  assert.deepEqual(profile.auth?.dkimDomains, ["abc.net.au"]);
  assert.equal(profile.signals.length, 0);
  const record = evaluateTriage(emailTriageEvidence({ analysis, profile }));
  assert.equal(record.rules.find((r) => r.ruleId === "EMAIL-12")?.result, "not_met");
  assert.notEqual(record.outcome, "POSSIBLE_THREAT_IDENTIFIED");
});

test("upgrade: L1 → L3 keeps the history and says so; a weaker copy later never downgrades the case", async () => {
  const pastedAnalysis = analyseEmail("Subject: URGENT: verify your NetBank account\n\nDear customer, we detected an unusual sign-in.");
  const l1 = buildEmailProfile({ via: "pasted", analysis: pastedAnalysis, at: "2026-06-14T10:00:00.000Z" });
  const parsed = await original(PHISH);
  const { raw, fields } = analysisSourceFor(parsed);
  const l3 = buildEmailProfile({ via: "eml_file", original: parsed, analysis: analyseEmail(raw, fields, headerEvidenceFor(parsed)), at: "2026-06-14T11:00:00.000Z" });
  const merged = mergeEmailProfiles(l1, l3);
  assert.equal(merged.level, "L3");
  assert.deepEqual(merged.history.map((h) => h.level), ["L1", "L3"]);
  assert.match(upgradeSentence(merged) ?? "", /^Evidence upgraded from L1 — Visual\/Text to L3 — Original Message\./);
  const later = mergeEmailProfiles(merged, buildEmailProfile({ via: "pasted", analysis: pastedAnalysis, at: "2026-06-14T12:00:00.000Z" }));
  assert.equal(later.level, "L3");
  assert.deepEqual(later.history.map((h) => h.level), ["L1", "L3", "L1"]);
});

test("only minimal structured findings may leave the device — no subject, body, names, addresses or header text", async () => {
  const parsed = await original(PHISH);
  const { raw, fields } = analysisSourceFor(parsed);
  const findings = emailFindings(buildEmailProfile({ via: "eml_file", original: parsed, analysis: analyseEmail(raw, fields, headerEvidenceFor(parsed)) }));
  const wire = JSON.stringify(findings);
  for (const secret of ["NetBank", "Dear customer", "security@commbank.com.au", "CommBank Security", "statement.pdf", "margaret", "203.0.113.9", "Received"]) {
    assert.ok(!wire.includes(secret), `findings must not carry ${secret}`);
  }
  assert.equal((findings.auth as { recorded_by: string }).recorded_by, "mx.google.com");
  assert.equal(findings.from_domain, "commbank.com.au");
  assert.deepEqual((findings.attachments as { ext: string }[]).map((a) => a.ext), ["pdf"]);
});

test("pasted original source is recognised; a forwarded copy is not", () => {
  assert.equal(looksLikeRawEmail(PHISH), true);
  assert.equal(looksLikeRawEmail("---------- Forwarded message ---------\nFrom: a@b.com\nSubject: hi\n\nhello"), false);
});

test("sameEmail: an upgrade must be the same email", () => {
  assert.equal(sameEmail({ subject: "Fwd: URGENT: verify your NetBank account" }, { sender: null, subject: "URGENT: verify your NetBank account", text: "" }), true);
  assert.equal(sameEmail({ sender: "a@x.com", subject: "Hello" }, { sender: "b@y.com", subject: "Other", text: "something else entirely" }), false);
  assert.equal(sameEmail({ text: "Dear customer, we detected an unusual sign-in. Log in within 24 hours or" }, { sender: null, subject: null, text: "Dear customer, we detected an unusual sign-in. Log in within 24 hours or your account" }), true);
});

test("sameEmail: a pasted copy (From/Subject inside the text) matches its original once read like the engine reads it", async () => {
  const pasted = "From: CommBank Security <security@commbank.com.au>\nSubject: URGENT: verify your NetBank account\n\nDear customer, we detected an unusual sign-in. Log in within 24 hours or your account will be suspended.";
  const prior = parseEmail(pasted);
  const parsed = await original(PHISH);
  const { fields } = analysisSourceFor(parsed);
  const next = { sender: fields.from, subject: fields.subject, text: parsed.bodyText };
  assert.equal(sameEmail({ sender: prior.fromAddress, subject: prior.subject, text: prior.body }, next), true);
  const other = parseEmail("From: Ann <ann@example.org>\nSubject: Lunch on Friday?\n\nAre you free for lunch on Friday at the usual place near the office?");
  assert.equal(sameEmail({ sender: other.fromAddress, subject: other.subject, text: other.body }, next), false);
});

test("a From line showing the bank's own domain is not taken at face value when DMARC failed", async () => {
  const spoof = PHISH.replace("Reply-To: verify@commbank-help.co\r\n", "").replace(/http:\/\/commbank-secure-verify\.co\/netbank\/login/, "");
  const parsed = await original(spoof);
  const { raw, fields } = analysisSourceFor(parsed);
  const pasted = analyseEmail(raw, fields);
  const read = analyseEmail(raw, fields, headerEvidenceFor(parsed));
  assert.equal(pasted.senderMismatch, false, "on pasted text the official-looking From is all Apollo has");
  assert.equal(read.senderMismatch, true);
  assert.equal(read.scenario, "E01");
  assert.ok(read.why.some((w) => /failed sender authentication/.test(w)));
});
