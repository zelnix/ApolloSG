// Ask Higgins and a threat's Overview build their report the same way, and say each fact once.
import { test } from "node:test";
import assert from "node:assert/strict";

import { buildReport } from "../src/domain/reportSections.ts";
import { sentences } from "../src/domain/luddish/patterns.ts";

// The Linkt check from the preview, exactly as TC Hawkeye settled it.
const linkt = {
  overview: "What you sent raises a concern: linkt-au-pay.top carries Linkt's name, but it is not Linkt's domain (linkt.com.au). Nothing here proves it's a scam, but don't act on it until you've checked it through a channel you trust.",
  explanationMarkdown: "**What was found**\n- linkt-au-pay.top carries Linkt's name, but it is not Linkt's domain (linkt.com.au).\n\n**What it means**\nApollo's checks established the warning sign above. That's reason to be careful, but not enough to call it a scam.\n\n**How ApolloSG checked**\nTC Hawkeye checked what you sent using Apollo's knowledge base and a targeted web search. Magnum DI's deeper analysis wasn't needed, because it couldn't change the outcome or what to do.",
  attentionReason: "Acting on something with warning signs before checking it is how people lose money or access to their accounts.",
  findings: [{ id: "f1", text: "linkt-au-pay.top carries Linkt's name, but it is not Linkt's domain (linkt.com.au).", basis: "observation" as const, confidence: "medium" as const, evidenceIds: [], sourceIds: [] }],
  uncertainties: [
    "TC Hawkeye's search found no record for linkt-au-pay.top: Apollo's knowledge base has nothing on linkt-au-pay.top.",
    "Not taken further, because it couldn't change the outcome or what to do: impersonation: whether the material genuinely comes from Linkt.",
    "Not taken further, because it couldn't change the outcome or what to do: message and deception analysis of the submitted material (requests, pressure, persuasion, intent).",
  ],
  scope: "TC Hawkeye checked the submitted material using Apollo's knowledge base and a targeted web search. Nothing was opened or fetched from the destination, no one was contacted and no account was accessed.",
  alreadySaid: ["Settled by TC Hawkeye — Established warning signs: its checks found real warning signs, but not enough to call it a scam."],
};

test("each fact appears once: the finding the answer states, the rule's restatement and the repeated scope are gone", () => {
  const r = buildReport(linkt);
  assert.deepEqual(r.answer, [linkt.overview]);
  assert.deepEqual(r.found, [], "the only finding is already in the answer");
  assert.deepEqual(r.means, [linkt.attentionReason], "'What it means' kept only what the Settled-by line doesn't say");
  assert.deepEqual(r.uncertain, [], "how Apollo checked is on the DI tab, never under what isn't certain");
  assert.equal(r.how.length, 1);
  const how = r.how[0];
  assert.match(how, /^TC Hawkeye checked what you sent using Apollo's knowledge base and a targeted web search\. Magnum DI's deeper analysis wasn't needed/);
  assert.match(how, /So these weren't taken further: impersonation \(whether the material genuinely comes from Linkt\); message and deception analysis/);
  assert.match(how, /no account was accessed\. TC Hawkeye's search found no record for linkt-au-pay\.top: Apollo's knowledge base has nothing on linkt-au-pay\.top\.$/);
  assert.equal((how.match(/couldn't change the outcome/g) ?? []).length, 1, "the reason is said once");
  assert.equal((how.match(/targeted web search/g) ?? []).length, 1, "'What this covered' merged into 'How ApolloSG checked'");
});

// The AusPost link check from the preview: an official source already lists it (stored with the older wording).
const auspost = {
  overview: "Apollo's blocklist and Google Safe Browsing lists testsafebrowsing.appspot.com as a phishing (social engineering) site. Don't act on it — if you need to, contact AusPost yourself.",
  explanationMarkdown: "**What was found**\n- Apollo's blocklist and Google Safe Browsing lists testsafebrowsing.appspot.com as a phishing (social engineering) site.\n\n**What it means**\nAn official safety source has already identified this as dangerous, so there's nothing left to weigh up: acting on it would put your money, accounts or device at risk.\n\n**How ApolloSG checked**\nTC Hawkeye settled this with official source checks. Magnum DI's deeper analysis wasn't needed, because the result above already settles what to do.",
  attentionReason: "An official source has already identified it as dangerous, so acting on it puts your money or accounts at risk.",
  uncertainties: ["Not taken further, because the official result already settles what to do: impersonation: whether the material genuinely comes from AusPost."],
  scope: "TC Hawkeye checked the submitted material using official source checks. Nothing was opened or fetched from the destination, no one was contacted and no account was accessed.",
};

test("the same point in other words is said once: 'What it means' and the reason a question wasn't taken further", () => {
  const r = buildReport(auspost);
  assert.deepEqual(r.means, ["An official safety source has already identified this as dangerous, so there's nothing left to weigh up: acting on it would put your money, accounts or device at risk."]);
  const how = r.how[0];
  assert.match(how, /because the result above already settles what to do\. So these weren't taken further: impersonation \(whether the material genuinely comes from AusPost\)\./);
  assert.equal((how.match(/settles what to do/g) ?? []).length, 1, "the reason is said once");
});

test("a negation is never merged into the statement it contradicts", () => {
  const r = buildReport({ overview: "Apollo found the link on an official safety list of phishing sites.", attentionReason: "Apollo found the link was not on any official safety list of phishing sites." });
  assert.equal(r.means.length, 1);
});


test("a finding the answer doesn't state is listed, with how it was established", () => {
  const r = buildReport({ ...linkt, findings: [...linkt.findings, { id: "f2", text: "The domain was registered 3 days ago.", basis: "observation", confidence: "high", evidenceIds: [], sourceIds: [] }] });
  assert.deepEqual(r.found, [{ text: "The domain was registered 3 days ago.", detail: "Observed · High confidence", findingId: "f2", category: "Fake URL" }]);
});

test("a threat with no investigation uses what Apollo recorded, still once each", () => {
  const r = buildReport({ overview: "Apollo blocked a suspicious connection.", fallbackFound: ["Apollo blocked a suspicious connection.", "The address is on Apollo's blocklist."], fallbackMeans: "Nothing reached your device from it." });
  assert.deepEqual(r.answer, ["Apollo blocked a suspicious connection."]);
  assert.deepEqual(r.found, [{ text: "The address is on Apollo's blocklist.", detail: null, category: "Known Threat" }]);
  assert.deepEqual(r.means, ["Nothing reached your device from it."]);
  assert.deepEqual(r.how, []);
});

test("other sections an investigation writes keep their heading; sources are the ones it used", () => {
  const r = buildReport({
    overview: "This matches a known toll scam.",
    explanationMarkdown: "**What Apollo's knowledge base adds** (general knowledge, not evidence about what you sent)\n- Toll scams ask you to pay a small fee.",
    sources: [{ id: "s1", url: "https://scamwatch.gov.au", title: "Scamwatch", retrievedAt: "", retrieval: "fetched", authority: "official", authorityBasis: "" },
              { id: "s2", url: "https://x.example", title: "X", retrievedAt: "", retrieval: "fetched", authority: "unknown", authorityBasis: "" }],
    sourceIds: ["s1"],
  });
  assert.deepEqual(r.more, [{ title: "What Apollo's knowledge base adds", paragraphs: ["(general knowledge, not evidence about what you sent)", "Toll scams ask you to pay a small fee."] }]);
  assert.deepEqual(r.sources.map((s) => s.id), ["s1"]);
});

test("sentences split at a full stop followed by a space, never inside an address", () => {
  assert.deepEqual(sentences("It is not linkt.com.au. Check it."), ["It is not linkt.com.au.", "Check it."]);
});

test("How ApolloSG checked names each item in plain words, never by its evidence reference", () => {
  const id = "3f2a9c1e-1111-2222-3333-444455556666";
  const scope = `Examined: the question you asked (4 words); evidence ${id} · kind=text · Call details (6 words). No website was opened, no sender was contacted and no account was accessed.`;
  const r = buildReport({ overview: "A caller asked for a code.", scope });
  const how = r.how.join(" ");
  assert.ok(!how.includes(id) && !how.includes("kind=") && !how.includes("evidence "), how);
  assert.match(how, /Examined: the question you asked \(4 words\); the call details \(6 words\)\./);
  // A bare id is named from the case's own items; one it doesn't know is still never shown as a code.
  const bare = buildReport({ overview: "x", scope: `Magnum DI examined evidence ${id} and [${id.replace("3f2a", "9d8e")}].`, evidence: [{ id, label: "Submitted message text", kind: "text" }] });
  assert.equal(bare.how.join(" "), "Magnum DI examined the submitted message text and an item in this case.");
  const kindOnly = buildReport({ overview: "x", scope: `[evidence ${id} · kind=image] was read directly.` });
  assert.equal(kindOnly.how.join(" "), "The picture you sent was read directly.");
});
