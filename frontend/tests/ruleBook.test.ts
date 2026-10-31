// The rule book is one shared file (backend/content/rulebook.md). The app renders it word for word, so every
// construct the book uses must come out as clean text — no stray markdown — and the settling rules must be there.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { forPlatform, parseInline, parseRuleBook, plainText, reviewedLabel, sectionsOf, type Block } from "../src/domain/ruleBook.ts";
import { DEVICE_STATUS } from "../src/domain/deviceAnalysis.ts";
import { FILE_SIZE_LIMIT } from "../src/domain/fileInspection.ts";
import { detectCheckIntent } from "../src/higgins/checkIntent.ts";
import { classifyIntent } from "../src/higgins/intentRouter.ts";
import { QUICK_QUESTIONS } from "../src/higgins/quickQuestions.ts";
import { enforceEgress, purposeLimitedUrl, redactInvestigationSecrets } from "../src/domain/privacy.ts";

const BOOK = readFileSync(fileURLToPath(new URL("../../backend/content/rulebook.md", import.meta.url)), "utf8");
/** A section's own text: from its {#id} to the next section (###) or part (##). */
const sectionText = (id: string) => (BOOK.split(`{#${id}}`, 2)[1] ?? "").split(/\n#{2,3} /, 1)[0];
const ASK_HIGGINS = sectionText("ask-higgins");

function texts(blocks: Block[]): string[] {
  return blocks.flatMap((b) => b.kind === "heading" ? [b.text]
    : b.kind === "paragraph" ? [plainText(b.spans)]
    : b.kind === "list" ? b.items.map((i) => plainText(i.spans))
    : b.kind === "table" ? [...b.headers, ...b.rows.flat().map(plainText)] : []);
}

test("inline emphasis: bold, italics and code become styled spans; snake_case stays text", () => {
  assert.deepEqual(parseInline("A **full** match, *partial* and `code`."), [
    { text: "A " }, { text: "full", bold: true }, { text: " match, " }, { text: "partial", italic: true }, { text: " and " }, { text: "code", code: true }, { text: "." }]);
  assert.deepEqual(parseInline("_Last reviewed: 2026-06-01._"), [{ text: "Last reviewed: 2026-06-01.", italic: true }]);
  assert.deepEqual(parseInline("tc_flyby_official and magnum_di"), [{ text: "tc_flyby_official and magnum_di" }]);
});

test("headings carry their {#id}, tables keep headers and rows, nested lists keep their depth", () => {
  const blocks = parseRuleBook("# Title\n\n## Rules {#settling-rules}\n\n| A | B |\n|---|---|\n| **x** | y |\n\n1. One\n   - nested\n2. Two\n\n---\n\nText\nwraps.\n\n#### Stage 1");
  assert.deepEqual(blocks[1], { kind: "heading", level: 2, text: "Rules", id: "settling-rules" });
  assert.equal(blocks[2].kind, "table");
  if (blocks[2].kind === "table") { assert.deepEqual(blocks[2].headers, ["A", "B"]); assert.equal(blocks[2].rows.length, 1); assert.equal(blocks[2].rows[0][0][0].bold, true); }
  assert.equal(blocks[3].kind, "list");
  if (blocks[3].kind === "list") assert.deepEqual(blocks[3].items.map((i) => [i.depth, i.marker]), [[0, "1."], [1, "•"], [0, "2."]]);
  assert.equal(blocks[4].kind, "rule");
  assert.deepEqual(blocks[5], { kind: "paragraph", spans: [{ text: "Text wraps." }], indent: false });
  assert.deepEqual(blocks[6], { kind: "heading", level: 4, text: "Stage 1", id: null });
});

test("the real rule book renders as clean text with every section and the settling rules", () => {
  const blocks = parseRuleBook(BOOK);
  const all = texts(blocks);
  for (const line of all) {
    assert.ok(!/\*\*|\{#|^\||^#+\s|`/.test(line), `unrendered markdown in: ${line}`);
  }
  const headings = blocks.filter((b): b is Extract<Block, { kind: "heading" }> => b.kind === "heading").map((b) => b.text);
  for (const part of ["Apollo detection", "Higgins Triage", "TC FlyBy", "Magnum DI", "Higgins (explanation)", "Ask Higgins", "Privacy and redaction", "knowledge base", "Settling rules"]) {
    assert.ok(headings.some((h) => h.includes(part)), `missing section: ${part}`);
  }
  assert.ok(blocks.some((b) => b.kind === "heading" && b.id === "settling-rules"));
  const settling = blocks.find((b) => b.kind === "table" && b.headers[0] === "Rule ID");
  assert.ok(settling && settling.kind === "table" && settling.rows.length >= 13);
  assert.ok(blocks.filter((b) => b.kind === "table").length >= 5);
});

test("the review date reads as a plain date, and nothing is invented without one", () => {
  assert.equal(reviewedLabel("2026-06-01"), "1 June 2026");
  assert.equal(reviewedLabel(null), null);
  assert.equal(reviewedLabel("soon"), null);
});

test("the Ask Higgins rules in the book match what the device does", () => {
  assert.ok(ASK_HIGGINS, "the book has an Ask Higgins section {#ask-higgins}");
  assert.ok(ASK_HIGGINS.includes(`There are ${QUICK_QUESTIONS.length} quick questions`), "number of quick questions");
  const unclear = classifyIntent("hmm");
  assert.equal(unclear.route, "clarify");
  assert.ok(ASK_HIGGINS.includes(`"${unclear.clarificationQuestion}"`), "the clarifying question, word for word");
  // A check word and a subject word open the matching form; the first subject mentioned wins.
  assert.equal(detectCheckIntent("Can you check this email?")?.category, "email_accounts");
  assert.equal(detectCheckIntent("check the link in this email")?.category, "websites_links");
  assert.equal(detectCheckIntent("Can you check this for me?"), null);
  // Wayfinding goes to Higgins; the device's own state is answered on the device.
  assert.equal(classifyIntent("Where is call screening?").route, "ask_higgins");
  assert.equal(classifyIntent("Is my phone protected?").route, "local_diagnostic");
  for (const form of ["Screenshot or photo", "Websites & Links", "Messages & Calls", "Email & Accounts", "Apps & Files", "Device & Internet"]) {
    assert.ok(ASK_HIGGINS.includes(`| ${form} |`), `form: ${form}`);
  }
});

test("the privacy rules in the book match what the device removes and refuses", () => {
  const privacy = sectionText("privacy");
  assert.ok(privacy, "the book has a Privacy and redaction section {#privacy}");
  // Secrets are replaced with the label the book names; scam evidence (the sender's number) is kept.
  for (const secret of ["my password is hunter22", "123456 is your verification code", "code: 1234", "api_key=abc123secret"]) {
    const out = redactInvestigationSecrets(secret);
    assert.ok(out.includes("[credential redacted]"), `not removed: ${secret}`);
  }
  assert.ok(privacy.includes('"[credential redacted]"'));
  assert.ok(redactInvestigationSecrets("Hi Mum, my new number is 0412 345 678").includes("0412 345 678"));
  // A field outside the allow-list stops the request with the book's message.
  assert.throws(() => enforceEgress("higgins_chat", { message: "hi", contacts: [] }), (error: Error) => privacy.includes(`"${error.message}"`));
  // Links keep their path; secret values and the part after "#" go.
  const link = purposeLimitedUrl("https://user:pw@evil.example/login/page?token=abc&id=7#frag");
  assert.ok(link.includes("/login/page") && !link.includes("abc") && !link.includes("frag") && !link.includes("pw@"));
});

test("the book opens in five parts, each holding closed sections with their own ids, every gate under Protection Gates", () => {
  const { intro, groups } = sectionsOf(parseRuleBook(BOOK));
  assert.ok(intro.some((b) => b.kind === "heading" && b.level === 1), "the intro keeps the title");
  assert.ok(!intro.some((b) => b.kind === "heading" && b.level >= 2));
  assert.deepEqual(groups.map((g) => g.title), ["Protection Gates", "Investigation process", "Privacy and data", "Device protections", "General"]);
  const sections = groups.flatMap((g) => g.sections);
  assert.equal(sections.length, BOOK.split("\n### ").length - 1);
  const ids = sections.map((section) => section.id);
  assert.equal(new Set(ids).size, ids.length, "section ids are unique");
  assert.deepEqual(groups[0].sections.map((s) => s.title), ["How the gates decide (Apollo detection)", "Site Gate", "Link Gate", "Text Gate", "Call Gate",
    "Email Gate", "Account Gate", "File Gate", "App Gate", "Device Gate", "Internet Gate", "Linked events across gates"]);
  assert.deepEqual(groups[3].sections.map((s) => s.id), ["threats-list"]);
  for (const id of ["your-data", "settling-rules", "privacy", "permissions", "scam-alerts", "ask-higgins"]) {
    assert.ok(ids.includes(id), `missing section: ${id}`);
  }
  for (const section of sections) {
    assert.ok(section.blocks.length > 0, `empty section: ${section.title}`);
    assert.notEqual(section.blocks[0].kind, "rule");
    assert.notEqual(section.blocks[section.blocks.length - 1].kind, "rule");
  }
  for (const group of groups) assert.ok(!group.blocks.some((b) => b.kind === "rule"), `stray rule in ${group.title}`);
});

test("each gate lists its rules one per line, code first, grouped by class", () => {
  const { groups } = sectionsOf(parseRuleBook(BOOK));
  const ruleItems = (id: string) => {
    const section = groups.flatMap((g) => g.sections).find((s) => s.id === id)!;
    const items = section.blocks.flatMap((b) => (b.kind === "list" ? b.items.map((i) => plainText(i.spans)) : []))
      .filter((t) => /^[A-Z]+-\d+ · /.test(t));
    const classes = section.blocks.flatMap((b) => (b.kind === "paragraph" ? [plainText(b.spans)] : []))
      .filter((t) => /^(DETECT|CORRELATE|ROUTE|COVERAGE|ENFORCE|EXPLAIN) \(\d+\)$/.test(t));
    return { items, classes };
  };
  const link = ruleItems("link-gate");
  assert.equal(link.items.length, 21);
  assert.ok(link.items[0].startsWith("LINK-01 · "));
  assert.deepEqual(link.classes, ["DETECT (18)", "CORRELATE (1)", "ROUTE (1)", "COVERAGE (1)"]);
  const higgins = ruleItems("higgins-explanation");
  assert.deepEqual(higgins.classes, ["EXPLAIN (11)"]);
  assert.deepEqual(higgins.items.map((t) => t.split(" · ")[0]), Array.from({ length: 11 }, (_, n) => `HIG-${String(n + 1).padStart(2, "0")}`));
  assert.ok(!/(Call|Text|Site|Website) Guard/.test(BOOK), "Gate is the one name");
});

const read = (p: string) => readFileSync(fileURLToPath(new URL(`../${p}`, import.meta.url)), "utf8");

test("the device's own limits in the book match the device", () => {
  const yourData = sectionText("your-data");
  const minutes = Number(/MAX_AGE_MS = (\d+) \* 60 \* 1000/.exec(read("src/higgins/chatMemory.ts"))?.[1]);
  assert.equal(minutes, 60);
  assert.ok(yourData.includes("Up to 1 hour, and at most the last 40 messages") && read("src/higgins/chatMemory.ts").includes(".slice(-40)"));
  const screening = read("modules/apollo-security/android/src/main/java/com/hucentai/apollosecurity/ApolloCallScreeningService.kt");
  const kept = Number(/MAX_SCREENED = (\d+)/.exec(screening)?.[1]);
  const days = Number(/SCREENED_RETENTION_MS = (\d+)L \* 24/.exec(screening)?.[1]);
  const queued = Number(/MAX_PENDING = (\d+)/.exec(screening)?.[1]);
  assert.ok(yourData.includes(`The last ${kept} calls, for up to ${days} days`));
  assert.ok(sectionText("call-gate").includes(`the last ${kept} calls, for up to ${days} days`) && sectionText("call-gate").includes(`queued (up to ${queued})`));
  assert.ok(yourData.includes(`The last ${/HISTORY_CAP = (\d+)/.exec(read("src/store/accountMonitorStore.ts"))?.[1]} scans are kept`));
  assert.ok(sectionText("file-gate").includes(`Files can be up to ${FILE_SIZE_LIMIT / (1024 * 1024)} MB`));
  const snoozeDays = Number(/GATE_SNOOZE_MS = (\d+) \* 24/.exec(read("src/domain/gatePermissions.ts"))?.[1]);
  assert.ok(sectionText("permissions").includes(`after about ${snoozeDays} days`));
});

test("the device results and permission wording in the book are the app's own, word for word", () => {
  const device = sectionText("device-gate");
  for (const status of Object.values(DEVICE_STATUS)) assert.ok(device.includes(`| ${status.title} | ${status.meaning} |`), status.title);
  const permissions = sectionText("permissions");
  const config = read("app.config.js");
  assert.ok(permissions.includes("| Notifications | Receive important threat and family alerts |"));
  for (const key of ["cameraPermission", "photosPermission"]) {
    const wording = new RegExp(`${key}: "([^"]+)"`).exec(config)?.[1];
    assert.ok(wording && permissions.includes(`| ${wording} |`), `${key}: ${wording}`);
  }
  assert.ok(/microphonePermission: false/.test(config) && permissions.includes("**Never asked for:** the microphone"));
});

test("on iPhone and iPad the book leaves out Android-only rules, and keeps the iPhone ones", () => {
  const all = parseRuleBook(BOOK);
  const ios = texts(forPlatform(all, "ios")).join("\n");
  assert.ok(!/Android/.test(ios), "no Android wording on iPhone");
  assert.ok(ios.includes("Apple lets no app screen calls as they arrive"));
  assert.ok(ios.includes("Apple gives apps no way to read Messages"));
  assert.ok(ios.includes("| Camera |") || ios.includes("Scan QR codes and photograph suspicious items for checking"));
  assert.deepEqual(forPlatform(all, "android"), all);
});

test("the book names no AI provider: it speaks of AI tools", () => {
  assert.ok(!/Gemini|Google AI|Google's AI/.test(BOOK));
});
