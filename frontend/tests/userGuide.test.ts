// The User Guide screen's search, and Higgins opening a form only when someone wants a check (not "how do I…").
// Run: node --test tests/userGuide.test.ts
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { highlightParts, searchGuide, searchTerms, type UserGuide } from "../src/guide/search.ts";
import { detectCheckIntent } from "../src/higgins/checkIntent.ts";

const guide = JSON.parse(readFileSync("src/guide/userGuide.json", "utf8")) as UserGuide;
const ids = (query: string) => searchGuide(guide, query).map((hit) => hit.topic.id);

test("search finds topics by title, keyword, heading and body text", () => {
  assert.equal(ids("share")[0], "share-into", "title");
  assert.ok(ids("whitelist").includes("trusted-links"), "keyword");
  assert.ok(ids("quiet hours").includes("notifications"), "detail heading");
  assert.ok(ids("Invoice.pdf.exe").includes("check-app-file"), "body text");
  assert.ok(ids("Call Blocking & Identification").includes("call-screening"), "steps");
});

test("search matches as you type and needs every word", () => {
  assert.ok(ids("shar").includes("share-into"));
  assert.ok(ids("delete case").includes("delete-cases"));
  assert.ok(!ids("delete case").includes("share-into"));
  assert.deepEqual(ids("quantum teleporter"), []);
  assert.deepEqual(ids("   "), []);
});

test("a question typed into search still finds the answer", () => {
  assert.equal(ids("How do I share something into ApolloSG?")[0], "share-into");
  assert.equal(ids("how do I delete my data")[0], "delete-data");
});

test("results carry readable text around the match", () => {
  const hit = searchGuide(guide, "double extensions")[0];
  assert.equal(hit.topic.id, "check-app-file");
  assert.match(hit.snippet, /Double extensions/);
  assert.ok(hit.snippet.length <= 160);
});

test("matching words are highlighted", () => {
  const parts = highlightParts("Tap Share, then choose ApolloSG.", searchTerms("share"));
  assert.deepEqual(parts.filter((p) => p.match).map((p) => p.text), ["Share"]);
  assert.equal(parts.map((p) => p.text).join(""), "Tap Share, then choose ApolloSG.");
});

test("every topic can be opened, and every section has topics", () => {
  for (const section of guide.sections) {
    assert.ok(section.topics.length > 0, section.id);
    for (const topic of section.topics) assert.ok(topic.answer.length > 20, topic.id);
  }
});

test("'how do I…' is a question for Higgins; 'I want … checked' opens the form", () => {
  assert.equal(detectCheckIntent("How do I check a phone number?"), null);
  assert.equal(detectCheckIntent("Where do I check a message?"), null);
  assert.equal(detectCheckIntent("I want to check a message")?.category, "messages_calls");
  assert.equal(detectCheckIntent("check this link for me")?.category, "websites_links");
});
