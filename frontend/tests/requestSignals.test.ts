// Requests are read from what a sentence does, not from the words it contains (src/domain/requestSignals.ts).
// Same corpus as backend/tests/test_request_reading.py — the two readers must agree.
import test from "node:test";
import assert from "node:assert/strict";
import { readRequests, asksToDisclose, type RequestKind } from "../src/domain/requestSignals.ts";

const SAFE: [string, string][] = [
  ["code delivery", "Your Microsoft verification code is 482913. Don't share this code with anyone."],
  ["code delivery with use", "Use 482913 to sign in to your Google Account. Google will never ask you for this code."],
  ["password changed notice", "Your password was changed on 3 May. If this was you, no action is needed. If you didn't make this change, reset your password at account.live.com."],
  ["new sign-in notice", "New sign-in to your account from Chrome on Windows. If it was you, you can ignore this message."],
  ["never share", "Reminder: we will never ask for your password, PIN or one-time code by email or phone. Never share your password."],
  ["discussion", "Five tips for creating a strong password, and why password managers help."],
  ["newsletter", "Read this week's stories. Manage your preferences or unsubscribe at any time."],
];
const SUSPICIOUS: [string, string, RequestKind][] = [
  ["password disclosure", "Your mailbox is full. Reply with your email password so IT can increase your quota.", "secret_request"],
  ["enter password", "Verify your account by entering your password on the secure page below.", "secret_request"],
  ["send code", "We just sent you a 6-digit code. Please send the code back to us to confirm your booking.", "code_request"],
  ["read out code", "Hi, it's Telstra. Read me the verification code we texted you so I can fix your account.", "code_request"],
  ["code then read it back", "I've sent you a six-digit security code, read it back to me so I can fix your account.", "code_request"],
  ["card details", "Your parcel is held. Reply with your card number and CVV to pay the customs fee.", "card_request"],
];

for (const [name, text] of SAFE) test(`not a request to disclose: ${name}`, () => assert.equal(asksToDisclose(readRequests(text)), false, name));
for (const [name, text, kind] of SUSPICIOUS) test(`a real request to disclose: ${name}`, () => {
  const found = readRequests(text);
  assert.equal(found[kind], true, name);
  assert.ok(found.quotes[kind]);
});

test("kinds are told apart", () => {
  assert.ok(readRequests(SAFE[0][1]).code_delivery && readRequests(SAFE[0][1]).negated_advice);
  assert.ok(readRequests(SAFE[2][1]).security_notice && readRequests(SAFE[2][1]).sign_in_request);
  assert.ok(readRequests("Log in to view your statement.").sign_in_request);
  assert.ok(readRequests("Log in within 24 hours or your account will be suspended.").sign_in_request);
  assert.equal(asksToDisclose(readRequests("Log in to view your statement.")), false);
  assert.ok(readRequests("Your payment was declined. Update your payment method to keep watching.").payment_detail_update);
});
