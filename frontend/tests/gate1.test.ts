// Gate 1 scenario benchmark (E01–E13). Run: yarn test:gate1
import assert from "node:assert/strict";
import { test } from "node:test";

import { analyseEmail, parseEmail } from "../src/domain/emailAnalysis.ts";

const FWD = `From: CommBank <security@cb-alerts-secure.top>
Reply-To: help@cb-alerts-secure.top
Subject: Your NetBank access has been restricted
Date: Mon

Dear customer, unusual activity was detected. Verify your account within 24 hours or it will be suspended:
https://netbank-commbank-verify.top/login
CommBank Security Team`;

test("parseEmail reads headers, body and attachments", () => {
  const p = parseEmail(FWD);
  assert.equal(p.fromName, "CommBank"); assert.equal(p.fromAddress, "security@cb-alerts-secure.top"); assert.equal(p.replyTo, "help@cb-alerts-secure.top");
  assert.match(p.subject ?? "", /restricted/); assert.match(p.body, /Dear customer/); assert.ok(!/^From:/m.test(p.body));
  assert.deepEqual(parseEmail("Attachments: Invoice_4471.pdf.exe\n\nSee attached").attachments, ["Invoice_4471.pdf.exe"]);
});
test("E01 acceptance: CommBank impersonation from off-domain sender with login link → barking", () => {
  const r = analyseEmail(FWD);
  assert.equal(r.state, "barking"); assert.equal(r.scenario, "E01"); assert.equal(r.claimedBrand, "CommBank");
  assert.match(r.verdict, /wasn't sent from CommBank/); assert.deepEqual(r.lookalikeUrls, ["https://netbank-commbank-verify.top/login"]); assert.equal(r.handoff.account, true); assert.equal(r.handoff.web, true);
});
test("E11 genuine email from the brand's own domain, links on-domain → ears_up (not resting: has links), resting with no links", () => {
  const r = analyseEmail("From: CommBank <noreply@commbank.com.au>\nSubject: Your statement is ready\n\nYour statement is available in NetBank: https://www.commbank.com.au/netbank");
  assert.equal(r.scenario, "E11"); assert.equal(r.state, "ears_up"); assert.equal(r.lookalikeUrls.length, 0);
  assert.equal(analyseEmail("From: CommBank <noreply@commbank.com.au>\nSubject: Branch hours\n\nOur branch hours change next week.").state, "resting");
});
test("E02 unknown-service account alert with link and supporting context → growling; plain sign-in request alone isn't one; known brand off-domain → barking", () => {
  const r = analyseEmail("From: Support <alerts@service-mail.top>\nSubject: Verify your account\n\nPlease sign in to verify your account within 24 hours or it will be suspended: https://service-mail.top/verify");
  assert.equal(r.scenario, "E02"); assert.equal(r.state, "growling"); assert.equal(r.handoff.account, true);
  const plain = analyseEmail("From: Support <alerts@service-mail.top>\nSubject: Verify your account\n\nPlease sign in to verify your account: https://service-mail.top/verify");
  assert.notEqual(plain.scenario, "E02", "an ordinary sign-in request needs supporting context"); assert.equal(plain.handoff.account, false);
  assert.equal(analyseEmail("From: Microsoft account team <no-reply@ms-security-alerts.com>\nSubject: Unusual sign-in activity\n\nReview the sign-in and secure your account: https://ms-security-alerts.com/review").state, "barking");
});
test("E03 risky attachment from unknown sender → barking; document attachment alone is fine", () => {
  const r = analyseEmail("From: accounts@random-supplier.biz\nSubject: Invoice\nAttachments: Invoice_4471.pdf.exe\n\nPlease find attached.");
  assert.equal(r.scenario, "E03"); assert.equal(r.state, "barking"); assert.deepEqual(r.riskyAttachments, ["Invoice_4471.pdf.exe"]); assert.equal(r.handoff.file, true);
  assert.notEqual(analyseEmail("From: jo@friend.com\nSubject: Agenda\nAttachments: Agenda.pdf\n\nSee attached agenda for Monday.").scenario, "E03");
});
test("E04 invoice with changed bank details → barking", () => {
  const r = analyseEmail("From: accounts@buildco.com.au\nSubject: Invoice 2231 - updated payment details\n\nPlease note our bank account details have changed. New BSB 062-000 account number 1234 5678. Invoice attached.");
  assert.equal(r.scenario, "E04"); assert.equal(r.state, "barking");
});
test("E05 BEC: urgent gift cards from 'CEO' on free webmail → barking", () => {
  const r = analyseEmail("From: Mark Taylor (CEO) <mark.taylor.ceo@gmail.com>\nSubject: Urgent\n\nI need you to urgently buy 5 gift cards for a client and send me the codes. Keep this confidential.");
  assert.equal(r.scenario, "E05"); assert.equal(r.state, "barking");
});
test("E06 asks for a verification code → barking + account handoff", () => {
  const r = analyseEmail("From: PayPal <service@paypal-resolution.top>\nSubject: Confirm your identity\n\nReply with the six-digit code we just sent so we can confirm your identity.");
  assert.equal(r.state, "barking"); assert.ok(["E01", "E06"].includes(r.scenario)); assert.equal(r.handoff.account, true);
});
test("E07 says brand, sent from elsewhere, no clear ask → growling", () => {
  const r = analyseEmail("From: Telstra <news@telstra-updates.club>\nSubject: Our new plans\n\nHave a look at our new mobile plans.");
  assert.equal(r.scenario, "E07"); assert.equal(r.state, "growling");
});
test("E08 reply-to mismatch on an invoice → growling", () => {
  const r = analyseEmail("From: Sam <sam@plumbingco.com.au>\nReply-To: sam.plumbing@outlook.com\nSubject: Invoice 88\n\nPlease pay the attached invoice by Friday.");
  assert.equal(r.scenario, "E08"); assert.equal(r.state, "growling");
});
test("E09 urgent email with links, no brand → growling", () => {
  const r = analyseEmail("From: promo@deals-now.xyz\nSubject: Final notice\n\nYour package will be returned. Act now: https://deals-now.xyz/track");
  assert.equal(r.state, "growling"); assert.ok(["E09", "E02"].includes(r.scenario));
});
test("E12 links from unknown sender, no pressure → ears_up; E13 ordinary email → resting", () => {
  assert.equal(analyseEmail("From: newsletter@localclub.org\nSubject: Newsletter\n\nThis month's newsletter: https://localclub.org/news").state, "ears_up");
  const r = analyseEmail("From: Mum <mum@gmail.com>\nSubject: Dinner\n\nAre you coming Sunday?"); assert.equal(r.state, "resting"); assert.equal(r.scenario, "E13");
});
test("fields override: from/subject passed separately", () => {
  const r = analyseEmail("Verify your account now: https://anz-verify.top/x", { from: "ANZ <alerts@anz-verify.top>", subject: "Account locked" });
  assert.equal(r.state, "barking"); assert.equal(r.claimedBrand, "ANZ");
});
