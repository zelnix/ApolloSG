import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { findingSentence } from "../src/domain/higginsHomeVoice.ts";
import { eventBrief } from "../src/domain/homeHeroBrief.ts";
import { buildReport, plainReport } from "../src/domain/reportSections.ts";
import type { PatrolEvent } from "../src/domain/types.ts";
import { compactUrl, compactUrls, displayHost, domainOnly } from "../src/domain/urlPresentation.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const EBAY = "https://www.ebay.com.au/sl/sell?mkevt=1&mkpid=2&emsid=e90001.mmslibHeroCta1.lc43a8b15-e76d-3eb8-95e1-b5d6e968e8a3&plmtld";
const REDIRECT = "https://www.ebay.com.au/splashui/challenge?ap=1&appName=orch&ru=https%3A%2F%2Fwww.ebay.com.au%2Fsl%2Fsell%3Fmkpid%3D2%26";

test("ordinary addresses read as the website and a short path", () => {
  assert.equal(compactUrl("https://www.auspost.com.au/parcels-mail/redelivery"), "auspost.com.au/parcels-mail/redelivery");
  assert.equal(compactUrl("http://Example.COM/"), "example.com");
  assert.equal(compactUrl("www.westpac.com.au/personal-banking"), "westpac.com.au/personal-banking");
  assert.equal(displayHost("https://www.auspost.com.au/parcels-mail/redelivery"), "auspost.com.au");
  assert.equal(compactUrls("Go to https://www.auspost.com.au/track today."), "Go to auspost.com.au/track today.");
});

test("an enormous query string is never shown", () => {
  const huge = `https://track.example.com/parcel?${"id=abc123&".repeat(800)}`;
  assert.equal(compactUrl(huge), "track.example.com/parcel…");
  assert.equal(compactUrl(EBAY), "ebay.com.au/sl/sell…");
  assert.ok(compactUrls(`Open ${huge} now`).length < 50);
});

test("a percent-encoded redirect shows only the address it starts from", () => {
  assert.equal(compactUrl(REDIRECT), "ebay.com.au/splashui/challenge…");
  assert.equal(compactUrl("https://go.example.net/https%3A%2F%2Fevil.example%2Flogin"), "go.example.net/…");
  assert.equal(compactUrl("https://l.facebook.com/l.php?u=https%3A%2F%2Fevil.example%2F"), "l.facebook.com/l.php…");
  assert.equal(displayHost(REDIRECT), "ebay.com.au");
});

test("every address in a sentence is shortened, and the sentence keeps its punctuation", () => {
  const sentence = `The link ${EBAY} redirects to ${REDIRECT}. Don't use the link.`;
  assert.equal(compactUrls(sentence), "The link ebay.com.au/sl/sell… redirects to ebay.com.au/splashui/challenge… Don't use the link.");
  assert.equal(domainOnly(sentence), "The link ebay.com.au redirects to ebay.com.au. Don't use the link.");
  assert.equal(compactUrls("See (https://a.example.com/x?y=1), then https://b.example.org."), "See (a.example.com/x…), then b.example.org.");
  assert.equal(compactUrls("Email help@www.example.com instead."), "Email help@www.example.com instead.", "email addresses aren't web addresses");
});

test("a malformed address is still shortened, never printed raw", () => {
  assert.equal(compactUrl("https://exa%mple.com/x?token=1"), "exa%mple.com/x");
  assert.equal(compactUrl("https://..?a=1"), "..");
  assert.equal(displayHost(`https://bad host${"x".repeat(80)}`), "bad host" + "x".repeat(31) + "…");
  assert.equal(compactUrls("Try https://%%%/?q=1 now."), "Try %%%/ now.");
  // The real host is what follows the login part: never the name placed in front of it.
  assert.equal(compactUrl("https://commbank.com.au@evil.example/login"), "evil.example/login");
  assert.equal(compactUrl("https://example.com:8443/a"), "example.com/a");
});

test("legitimate short addresses stay whole", () => {
  assert.equal(compactUrl("https://bit.ly/3xYzAbC"), "bit.ly/3xYzAbC");
  assert.equal(compactUrl("https://linkt.com.au/pay"), "linkt.com.au/pay");
  assert.equal(compactUrl("https://my.gov.au"), "my.gov.au");
  assert.equal(compactUrl("https://www.ato.gov.au/"), "ato.gov.au");
  assert.equal(compactUrls("It goes to linkt.com.au, which is Linkt's domain."), "It goes to linkt.com.au, which is Linkt's domain.");
});

test("Home: web addresses become their website before the sentence is capped", () => {
  const event = {
    event_id: "e1", device_id: "d1", category: "email", state: "barking", status: "active", headline: "", why: [], what_to_do: "",
    indicator_host: null, indicator_digest: null, verified_block: false, adapter_label: "t", evidence_provenance: "local_device",
    occurred_at: "2026-10-26T01:54:00.000Z", resolved_at: null,
    what_happened: `Apollo flagged the link ${EBAY} which redirects to ${REDIRECT}.`,
  } as unknown as PatrolEvent;
  assert.equal(findingSentence(event), "Apollo flagged the link ebay.com.au which redirects to ebay.com.au.");
  const voice = read("../src/domain/higginsHomeVoice.ts");
  assert.match(voice, /const text = domainOnly\(\(event\.what_happened \|\| ""\)\.trim\(\)\);[\s\S]*return cleaned\.charAt\(0\)\.toUpperCase\(\) \+ cleaned\.slice\(1\);/);
  assert.match(voice, /const primaryProblem = domainOnly\(/);
  // "Important for you" and the hero name a link by its website only (homeHeroBrief → shortDomain), never the raw address.
  assert.match(read("../src/domain/homeHeroBrief.ts"), /const host = shortDomain\(m\?\.url \?\? e\.local_indicator \?\? e\.indicator_host\);/);
  assert.equal(eventBrief({ ...event, category: "link", local_indicator: REDIRECT }, new Date(), null, "card").line1.includes("?"), false);
});

test("reports shorten addresses in every section but keep sources whole", () => {
  const source = { id: "s1", url: REDIRECT, title: "eBay", publisher: "eBay" } as never;
  const report = buildReport({
    overview: `The link ${EBAY} redirects to ${REDIRECT}.`,
    explanationMarkdown: `**What it means**\nIt opens ${REDIRECT}.\n\n**Other checks**\nSee https://www.scamwatch.gov.au/types-of-scams?x=1\n\n**How Apollo checked**\nApollo followed ${EBAY}.`,
    findings: [{ text: `Found ${EBAY}`, basis: "observation", confidence: "high" } as never],
    uncertainties: [`The page at ${REDIRECT} wasn't opened.`],
    sources: [source], sourceIds: ["s1"],
  });
  const all = [...report.answer, ...report.found.map((f) => f.text), ...report.means, ...report.more.flatMap((s) => s.paragraphs), ...report.uncertain, ...report.how].join(" ");
  assert.ok(!all.includes("mkevt") && !all.includes("%3A") && !all.includes("https://"), all);
  assert.ok(all.includes("ebay.com.au/sl/sell…") && all.includes("scamwatch.gov.au/types-of-scams…"));
  assert.equal(report.sources[0].url, REDIRECT, "source URLs are untouched");
  const plain = plainReport({ result: `Go to ${EBAY}`, established: [{ text: REDIRECT }], means: [], matters: [], uncertain: [], how: [], todo: [] } as never);
  assert.deepEqual([plain.answer[0], plain.found[0].text], ["Go to ebay.com.au/sl/sell…", "ebay.com.au/splashui/challenge…"]);
});
