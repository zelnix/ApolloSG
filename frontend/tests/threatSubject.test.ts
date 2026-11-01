import assert from "node:assert/strict";
import test from "node:test";

import { shortDomain, stateHeadline, subjectDescriptor, threatSubject } from "../src/domain/threatSubject.ts";
import type { PatrolEvent } from "../src/domain/types.ts";

function ev(partial: Partial<PatrolEvent>): PatrolEvent {
  return {
    event_id: "e1", device_id: "d1", category: "website", state: "growling", status: "active",
    headline: "", what_happened: "", why: [], what_to_do: "",
    indicator_host: null, indicator_digest: null, verified_block: false,
    adapter_label: "test", occurred_at: new Date().toISOString(), resolved_at: null,
    ...partial,
  } as PatrolEvent;
}

test("shortDomain reduces a link to its recognisable host", () => {
  assert.equal(shortDomain("https://www.paypal-secure.top/login?x=1"), "paypal-secure.top");
  assert.equal(shortDomain("PayPal-Secure.TOP"), "paypal-secure.top");
  assert.equal(shortDomain(""), null);
  assert.equal(shortDomain(null), null);
});

test("shortDomain keeps non-host text as given", () => {
  assert.equal(shortDomain("Acme IT Mobile Device Management"), "Acme IT Mobile Device Management");
});

test("website events name the domain", () => {
  const subject = threatSubject(ev({ category: "website", local_indicator: "https://paypal-secure.top/login" }));
  assert.deepEqual(subject, { kind: "website", name: "paypal-secure.top" });
  assert.equal(stateHeadline("growling", ev({ category: "website", indicator_host: "paypal-secure.top" })),
    "Apollo is growling at paypal-secure.top");
});

test("email, message, call and file events name their source", () => {
  assert.equal(subjectDescriptor(threatSubject(ev({ category: "email", source_metadata: { type: "email", sender: "billing@acme.co" } }))!),
    "the email from billing@acme.co");
  assert.equal(subjectDescriptor(threatSubject(ev({ category: "message", claimed_brand: "AusPost" }))!),
    "the text from AusPost");
  assert.equal(subjectDescriptor(threatSubject(ev({ category: "call", local_indicator: "+61 412 345 678" }))!),
    "the call from +61 412 345 678");
  assert.equal(subjectDescriptor(threatSubject(ev({ category: "file", source_metadata: { type: "file", attachment_names: ["invoice.exe"] } }))!),
    "the file invoice.exe");
});

test("no recorded identifier yields no subject and the plain state line", () => {
  const device = ev({ category: "device", state: "barking", headline: "Device management profile is active" });
  assert.equal(threatSubject(device), null);
  assert.equal(stateHeadline("barking", device), "Apollo is barking");
  assert.equal(stateHeadline("growling", null), "Apollo is growling");
});

test("long identifiers are kept whole, never cut short", () => {
  const long = "a".repeat(80) + "@example.com";
  const subject = threatSubject(ev({ category: "email", source_metadata: { type: "email", sender: long } }))!;
  assert.equal(subject.name, long);
});

test("row labels name the kind of thing for lists", async () => {
  const { subjectRowLabel } = await import("../src/domain/threatSubject.ts");
  assert.equal(subjectRowLabel(ev({ category: "call", local_indicator: "+61 412 345 678" })), "Caller: +61 412 345 678");
  assert.equal(subjectRowLabel(ev({ category: "website", indicator_host: "paypal-secure.top" })), "paypal-secure.top");
  assert.equal(subjectRowLabel(ev({ category: "device", headline: "Device management profile is active" })), null);
});
