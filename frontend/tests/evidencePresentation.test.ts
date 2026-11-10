// The Evidence tab must present captured material, never a reconstruction of the app it came from.
// Run: cd /app/frontend && node --test tests/evidencePresentation.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { describeArtefact, describeRedaction, linksIn, redactView } from "../src/domain/evidencePresentation.ts";

const base = { capturedAt: "2026-06-02T09:28:00.000Z", origin: "this_device" as const };

test("an email capture is presented as an email, headers lifted out of the body", () => {
  const view = describeArtefact({
    ...base, kind: "email",
    text: "From: accounts@civic-plumbing-invoices.com\nSubject: Updated bank details for invoice 4471\n\nHi, our usual account is under audit.\nPlease pay https://pay-civic.example/now today.",
  });
  assert.equal(view.layout, "email");
  assert.equal(view.sender, "accounts@civic-plumbing-invoices.com");
  assert.equal(view.subject, "Updated bank details for invoice 4471");
  assert.match(view.body ?? "", /^Hi, our usual account/);
  assert.doesNotMatch(view.body ?? "", /Subject:/);
  assert.deepEqual(view.links, ["https://pay-civic.example/now"]);
});

test("a message capture is presented as a message thread with the sender it names", () => {
  const view = describeArtefact({ ...base, kind: "text", text: "From AusPost:\nYour parcel AP88213 was delivered." });
  assert.equal(view.layout, "message");
  assert.equal(view.sender, "AusPost");
  assert.equal(view.body, "Your parcel AP88213 was delivered.");
});

test("saved fields are trusted over anything written in the body", () => {
  const view = describeArtefact({
    ...base, kind: "email",
    fields: [{ label: "From", value: "service@real-bank.com" }, { label: "Subject", value: "Statement ready" }],
    text: "From: spoofed@attacker.example\nYour statement is ready.",
  });
  assert.equal(view.sender, "service@real-bank.com");
  assert.match(view.body ?? "", /From: spoofed@attacker.example/); // body shown verbatim, not re-parsed
});

test("a message that merely mentions WhatsApp is still a message, not a chat", () => {
  const view = describeArtefact({ ...base, kind: "text", text: "From +44 7700 900182:\nI can walk you through the wallet setup on WhatsApp." });
  assert.equal(view.layout, "message");
  assert.equal(view.platform, null);
});

test("a capture that names a messaging app is presented as that chat", () => {
  const view = describeArtefact({
    ...base, kind: "text",
    fields: [{ label: "Source app", value: "WhatsApp" }, { label: "From", value: "Chris (Unknown)" }],
    text: "Hey, check this out!",
  });
  assert.equal(view.layout, "chat");
  assert.equal(view.platform, "WhatsApp");
  assert.equal(view.title, "WhatsApp chat");
});

test("a pasted message that declares its app is read as a chat, body intact", () => {
  const view = describeArtefact({
    ...base, kind: "text",
    text: "Source app: WhatsApp\nFrom Unknown (+61 455 019 220):\nHi Mum, my phone is broken. Could you send $1,480 today?",
  });
  assert.equal(view.layout, "chat");
  assert.equal(view.platform, "WhatsApp");
  assert.equal(view.sender, "Unknown (+61 455 019 220)");
  assert.equal(view.body, "Hi Mum, my phone is broken. Could you send $1,480 today?");
});

test("a pasted social post is read as a post", () => {
  const view = describeArtefact({
    ...base, kind: "text",
    text: "Platform: Facebook\nPage: Travel Deals Australia\nPost type: Sponsored\n\nLast minute luxury flights to Bali — $199 return! Claim at https://bali-flights-promo.top/claim",
  });
  assert.equal(view.layout, "post");
  assert.equal(view.sender, "Travel Deals Australia");
  assert.match(view.body ?? "", /^Last minute luxury flights/);
  assert.deepEqual(view.links, ["https://bali-flights-promo.top/claim"]);
});

test("a capture that names a social post is presented as a post", () => {
  const view = describeArtefact({
    ...base, kind: "text",
    fields: [{ label: "Platform", value: "Facebook" }, { label: "Page", value: "Travel Deals Australia" }, { label: "Post type", value: "Sponsored" }],
    text: "Last minute luxury flights to Bali!",
  });
  assert.equal(view.layout, "post");
  assert.equal(view.title, "Facebook post");
  assert.equal(view.sender, "Travel Deals Australia");
});

test("calls, files, apps and links fall back to the message layout", () => {
  for (const kind of ["call", "file", "app", "link", "website", "account", "device", "network"] as const) {
    assert.equal(describeArtefact({ ...base, kind, text: "x" }).layout, "message", `${kind} should use the default layout`);
  }
});

test("a screenshot capture is presented as a screenshot", () => {
  assert.equal(describeArtefact({ ...base, kind: "screenshot" }, true).layout, "screenshot");
});

test("nothing is invented: an empty capture produces empty facts", () => {
  const view = describeArtefact({ ...base, kind: "text" });
  assert.equal(view.sender, null);
  assert.equal(view.subject, null);
  assert.equal(view.occurredAt, null);
  assert.equal(view.body, null);
  assert.deepEqual(view.fields, []);
  assert.deepEqual(view.attachments, []);
});

test("the redacted view hides credentials and keeps the sender and links", () => {
  const view = describeArtefact({
    ...base, kind: "text",
    text: "From +61 448 221 905:\nYour verification code is 884213. Confirm at https://commbank-cancel.co/stop",
  });
  const sent = redactView(view, (v) => v.replace(/code is \d{6}/i, "[credential redacted]"));
  assert.equal(sent.sender, "+61 448 221 905");
  assert.match(sent.body ?? "", /\[credential redacted\]/);
  assert.match(sent.body ?? "", /https:\/\/commbank-cancel\.co\/stop/);
});

test("the banner names the type Apollo captured, not a generic 'message'", () => {
  assert.equal(describeArtefact({ ...base, kind: "link", url: "http://commbank-cancel.co/stop" }).bannerTitle, "This is the original link");
  assert.equal(describeArtefact({ ...base, kind: "call", text: "+61 412 668 341" }).bannerTitle, "This is the original call record");
  assert.equal(describeArtefact({ ...base, kind: "email", text: "hi" }).bannerTitle, "This is the original email");
  assert.equal(describeArtefact({ ...base, kind: "screenshot" }, true).bannerTitle, "This is the original screenshot");
});

test("links are read out of the captured text, trailing punctuation dropped", () => {
  assert.deepEqual(linksIn("Pay at https://linkt-au-pay.top/settle.", null), ["https://linkt-au-pay.top/settle"]);
});

test("the redacted view states exactly what changed — and says so when nothing did", () => {
  const view = describeArtefact({
    ...base, kind: "text",
    text: "From CommBank:\nYour verification code is 884213.",
  });
  const sent = redactView(view, (v) => v.replace(/code is \d{6}/i, "code is [redacted]"));
  const changed = describeRedaction({ original: view, redacted: sent });
  assert.equal(changed.changed, true);
  assert.deepEqual(changed.items, ["the message text"]);

  const clean = describeArtefact({ ...base, kind: "text", text: "From AusPost:\nYour parcel was delivered." });
  const untouched = describeRedaction({ original: clean, redacted: redactView(clean, (v) => v) });
  assert.equal(untouched.changed, false);
  assert.deepEqual(untouched.items, []);

  // A picture with a blacked-out area counts as changed even when no text differs.
  const shot = describeArtefact({ ...base, kind: "screenshot" }, true);
  assert.deepEqual(
    describeRedaction({ original: shot, redacted: shot, blackedOutRegions: 2 }).items,
    ["2 areas of the picture"],
  );
});

test("Gmail share provenance does not hide headers present in shared text", () => {
  const view = describeArtefact({
    ...base, kind: "email",
    fields: [{ label: "Source app", value: "Gmail" }],
    text: "From: Qantas <news@qantas.com>\nSubject: Your latest offers\n\nWelcome to this month's news.",
  });
  assert.equal(view.sender, "Qantas <news@qantas.com>");
  assert.equal(view.subject, "Your latest offers");
  assert.equal(view.fields.find((f) => f.label === "Source app")?.value, "Gmail");
  assert.match(view.body ?? "", /Welcome to this month's news/);
});
