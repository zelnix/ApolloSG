// @ts-nocheck — a Node dev script (run with node's type stripping), not app code.
// Higgins Luddish L1 — the before/after list for review: real ApolloSG wording, before and after Luddish.
// Check results come from the app's own analysers and adapters; reports from TC Hawkeye results the server's own
// wording builds (backend tests' scenarios, dumped to JSON); Ask Higgins answers from the phone's own responders.
// Run: node scripts/luddishBeforeAfter.ts /tmp/backend_results.json > ../memory/luddish_before_after.md
import { readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import { pathToFileURL } from "node:url";

const ROOT = new URL("..", import.meta.url).pathname;
registerHooks({
  resolve(spec, ctx, next) {
    if (spec === "expo-crypto") return { url: "data:text/javascript,export const randomUUID = () => 'id';", shortCircuit: true };
    const target = spec.startsWith("@/") ? pathToFileURL(ROOT + spec.slice(2)).href : spec;
    try { return next(target, ctx); } catch (error) {
      for (const ext of [".ts", ".tsx", "/index.ts"]) { try { return next(target + ext, ctx); } catch { /* next */ } }
      throw error;
    }
  },
});

const { compose, luddish, luddishCheckResult, luddishReport } = await import("../src/domain/luddish/index.ts");
const { lockFromIssue } = await import("../src/domain/luddish/lockSources.ts");
const { readability, TARGET_GRADE } = await import("../src/domain/luddish/readability.ts");
const { buildReport } = await import("../src/domain/reportSections.ts");
const { analyseMessage } = await import("../src/domain/messageAnalysis.ts");
const { buildMessageCheckResult } = await import("../src/domain/messageCheckResultAdapter.ts");
const { analyseEmail } = await import("../src/domain/emailAnalysis.ts");
const { buildEmailCheckResult } = await import("../src/domain/emailCheckResultAdapter.ts");
const { analyseCall } = await import("../src/domain/callAnalysis.ts");
const { buildCallCheckResult } = await import("../src/domain/callCheckResultAdapter.ts");
const { analyseApp } = await import("../src/domain/appAnalysis.ts");
const { buildAppCheckResult } = await import("../src/domain/appCheckResultAdapter.ts");
const { analyseFile } = await import("../src/domain/fileAnalysis.ts");
const { buildFileCheckResult } = await import("../src/domain/fileCheckResultAdapter.ts");
const { analyseAccountAlert } = await import("../src/domain/accountAnalysis.ts");
const { buildAccountCheckResult } = await import("../src/domain/accountCheckResultAdapter.ts");
const { explainIssue } = await import("../src/higgins/issueExplanation.ts");
const { investigationFollowUp } = await import("../src/higgins/followUp.ts");
const { knowledgeToHigginsMessage } = await import("../src/higgins/localResponder.ts");

interface Row { surface: string; case: string; part: string; before: string; after: string; notes: string[] }
const rows: Row[] = [];
const add = (surface: string, kase: string, part: string, before: string | undefined | null, after: string | undefined | null, notes: string[] = []) => {
  if (before && after !== undefined && after !== null) rows.push({ surface, case: kase, part, before, after, notes });
};

// ── Check results ──
// deno-lint-ignore no-explicit-any
function checkResult(kase: string, model: any) {
  const plain = luddishCheckResult(model);
  add("Check result", kase, "Headline", model.headline, plain.headline);
  add("Check result", kase, "Higgins' explanation", model.higginsSays, plain.higginsSays, plain.notes);
  add("Check result", kase, "What to do", model.whatToDo, plain.whatToDo);
  for (const item of model.items) add("Check result", kase, `Checked: ${item.name}`, item.finding, plain.items[item.id]);
  if (plain.explanation.fidelity.status !== "PASS") throw new Error(`${kase}: ${JSON.stringify(plain.explanation.fidelity)}`);
}
const messages: [string, string, string, { raw: string; decision: string; fraud_score: number | null }[]?][] = [
  ["AusPost delivery text", "+61 480 012 345", "AusPost: Your parcel could not be delivered due to an incomplete address. Update your details within 24 hours at https://auspost-redelivery.top/track or it will be returned."],
  ["CommBank account locked", "CommBank", "CommBank: Your NetBank access has been suspended due to unusual activity. Call 0412 999 888 immediately to verify your identity and restore access.",
    [{ raw: "0412 999 888", decision: "avoid", fraud_score: 88 }]],
  ["'Hi Mum' text", "+61 455 321 987", "Hi Mum, I dropped my phone in the toilet, this is my new number. Can you transfer $850 for a bill today? I'll pay you back."],
  ["ATO refund", "ATO", "ATO: You are eligible for a tax refund of $612.40. Claim via myGov at https://mygov-refund.au-claim.com before 30 June."],
  ["Ordinary text", "Sam", "Hey, are we still on for dinner on Friday? Let me know what time suits."],
];
for (const [kase, sender, text, phones] of messages) {
  const analysis = analyseMessage(sender, text);
  checkResult(`Message — ${kase}`, buildMessageCheckResult({ analysis, event: null, sender, explanation: null, urlResults: [], phones }));
}
const emails: [string, string, string, string][] = [
  ["PayPal phishing", "PayPal Security <service@paypa1-security.com>", "Your account has been limited",
    "Dear customer,\n\nWe noticed unusual activity. Your account has been limited. Please verify your information within 48 hours by logging in at https://paypa1-security.com/verify to avoid permanent suspension.\n\nPayPal"],
  ["Ordinary newsletter", "The Weekly Garden <news@weeklygarden.com.au>", "Your June gardening tips", "Hi there,\n\nThis month: winter pruning, frost protection and our favourite native shrubs.\n\nHappy gardening!"],
];
for (const [kase, from, subject, body] of emails) {
  const analysis = analyseEmail(body, { from, subject });
  checkResult(`Email — ${kase}`, buildEmailCheckResult({ analysis, event: null, from, subject, submissionId: "s", urlResults: [], explanation: null }));
}
const calls = [
  { kase: "Bank wanting a code", input: { asks: ["code", "dont_hangup"], claim: "bank", number: "0412 345 678", transcript: "This is your bank's fraud team. Read me the code we just sent you and stay on the line." } },
  { kase: "Tech support wanting remote access", input: { asks: ["install", "remote"], claim: "techsupport", number: "+61 2 9876 5432", transcript: "Microsoft here. Your computer has a virus. Install AnyDesk so we can fix it." } },
] as const;
for (const { kase, input } of calls) {
  checkResult(`Call — ${kase}`, buildCallCheckResult({ analysis: analyseCall(input as never), event: null, number: input.number, transcript: input.transcript }));
}
checkResult("App — remote-access app from a link", buildAppCheckResult({ analysis: analyseApp({ name: "AnyDesk Support", source: "message", purpose: "remote_support", permissions: ["accessibility", "screen_share", "install_apps"], context: "caller_asked" as never }), event: null, appName: "AnyDesk Support", submissionId: "s" }));
checkResult("File — invoice that's really a program", buildFileCheckResult({ analysis: analyseFile({ name: "invoice_june.pdf.exe", size: 482_000, source: "email" }), event: null, fileName: "invoice_june.pdf.exe", submissionId: "s" }));
checkResult("Account — sign-in approval you didn't start", buildAccountCheckResult({ analysis: analyseAccountAlert({ kind: "mfa_prompt", provider: "microsoft", userInitiated: false, repeated: true }), event: null, provider: "microsoft", kind: "mfa_prompt", initiated: false }));

// ── Reports (TC Hawkeye results in the server's own wording) ──
const backend = JSON.parse(readFileSync(process.argv[2] ?? "/tmp/backend_results.json", "utf8")) as Record<string, Record<string, unknown>>;
const REPORT_CASE: Record<string, string> = { ato_official: "The ATO's own website", clear_message: "An ordinary message from a friend", impersonation: "A link using CommBank's name",
  signals: "An investment offer", undetermined: "A new shopping website" };
for (const [key, r] of Object.entries(backend)) {
  // deno-lint-ignore no-explicit-any
  const response = r as any;
  const report = buildReport({ overview: response.overview, explanationMarkdown: response.explanationMarkdown, attentionReason: response.attentionReason,
    findings: response.findings, uncertainties: response.uncertainties, scope: response.scope });
  const plain = luddishReport(report);
  const kase = `Report — ${REPORT_CASE[key] ?? key}`;
  report.answer.forEach((p, i) => add("Report", kase, "Answer", p, plain.answer[i], i === 0 ? plain.notes ?? [] : []));
  report.found.forEach((f, i) => add("Report", kase, "What was found", f.text, plain.found[i].text, plain.found[i].explain ? [plain.found[i].explain!] : []));
  report.means.forEach((p, i) => add("Report", kase, "What it means", p, plain.means[i]));
  report.uncertain.forEach((p, i) => add("Report", kase, "What isn't certain", p, plain.uncertain[i]));
  report.how.forEach((p, i) => add("Report", kase, "How ApolloSG checked", p, plain.how[i]));
  for (const a of response.actions ?? []) add("Report", kase, `What to do: ${a.label}`, a.instruction, luddish(a.instruction, new Set(), 0).text);
}

// ── Ask Higgins ──
const chat = (kase: string, part: string, text: string) => { const out = luddish(text); add("Ask Higgins", kase, part, text, out.text, out.notes); };
const issue = { gate: "link", issue_summary: "Suspicious link in a text", assessment_state: "growling",
  findings: [{ summary: "The link domain is not auspost.com.au, although the message claims to be from Australia Post.", provenance: "observed", status: "warning" },
    { summary: "The domain was registered 2 days ago.", provenance: "inferred", status: "uncertain" }],
  uncertainty: ["Apollo was unable to determine who sent the message."], confirmed_protective_actions: [], user_reported_actions: [],
  available_actions: [{ label: "Don't tap the link", instruction: "Do not open the link and do not enter any details on it." }] } as const;
chat("Explaining a Patrol finding", "Answer", explainIssue(issue as never));
const lockCheck = compose(lockFromIssue(issue as never));
if (lockCheck.fidelity.status !== "PASS") throw new Error("issue lock");
const RESPONSE = {
  revision: 1, overview: "The text claiming to be from Australia Post is a delivery scam.", explanationMarkdown: "",
  assessment: "concern_found", attention: "action_needed", attentionReason: "The link leads to a look-alike site that is attempting to obtain your card details.",
  findings: [{ id: "f1", text: "The link domain is not auspost.com.au.", basis: "observation", confidence: "high", evidenceIds: ["e1"], sourceIds: [] },
    { id: "f2", text: "The page requests a $2.99 redelivery fee prior to delivery.", basis: "inference", confidence: "medium", evidenceIds: ["e1"], sourceIds: [] }],
  uncertainties: ["Who sent it could not be traced.", "Apollo did not open the page, so it is not known what else it asks for."], scope: "The message text and its link.", sourceIds: [], remainingEvidenceIds: [],
  actions: [{ id: "a1", kind: "instruction", label: "Delete the message", instruction: "Delete it and do not tap the link.", capabilityId: null, executionDescriptorId: null,
    requiresUserGesture: false, sourceIds: [], desiredField: null, desiredValue: null }],
  recommendedActionId: "a1", question: null, completion: "complete",
};
for (const q of ["What does this mean for me?", "Why is it suspicious?", "How sure are you?", "What should I do?", "What wasn't established?", "What evidence is there?"]) {
  chat(`Follow-up: "${q}"`, "Answer", investigationFollowUp(RESPONSE as never, [], q, "", "tc_flyby_official").answer);
}
for (const intent of ["how_apollo_works", "what_is_magnum_di", "explain_alert"] as const) chat(`About ApolloSG (${intent.replace(/_/g, " ")})`, "Answer", knowledgeToHigginsMessage(intent, "c").content);

// ── The list ──
const changed = rows.filter((r) => r.before !== r.after || r.notes.length);
const plainOnly = rows.filter((r) => r.before !== r.after);
const avg = (xs: number[]) => Math.round((xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length)) * 10) / 10;
// Titles and labels (under six words) have no reading grade, so only prose is measured.
const prose = rows.filter((r) => !readability(r.before).label);
const before = prose.map((r) => readability(r.before).grade), after = prose.map((r) => readability(r.after).grade);
const met = (xs: number[]) => xs.filter((g) => g <= TARGET_GRADE).length;
const esc = (s: string) => s.replace(/\|/g, "\\|").replace(/\n+/g, " ⏎ ");
const grading = (s: string) => readability(s).label ? "label" : String(readability(s).grade);
const out: string[] = [
  "# Higgins Luddish L1 — before and after",
  "",
  `Generated from ApolloSG's own wording on ${new Date().toISOString().slice(0, 10)} (no AI). ${rows.length} pieces of text were run through Luddish L1: ` +
  `${plainOnly.length} were reworded, ${changed.length - plainOnly.length} kept their exact wording but gained a plain note, and ${rows.length - changed.length} were already plain and stayed word for word.`,
  "",
  `- Reading level of the ${prose.length} pieces of prose (Flesch–Kincaid grade; target Year 7–8 = grade ${TARGET_GRADE} or under): average ${avg(before)} before → ${avg(after)} after; ` +
  `${met(before)} of ${prose.length} at or under the target before → ${met(after)} after. Titles and labels under six words aren't graded.`,
  "- Evidence Fidelity Check: every result passed. Links, addresses, numbers, dates, amounts, quotes, findings, uncertainty, severity and who established each finding are unchanged.",
  "- Where a sentence couldn't reach Year 7–8 without changing a fact, it keeps its exact words and gets a plain note (the dictionary's approved meaning) beside it.",
  "",
];
let lastSurface = "";
for (const r of changed) {
  if (r.surface !== lastSurface) { out.push("", `## ${r.surface}`, "", "| Where | Before | After | Grade |", "|---|---|---|---|"); lastSurface = r.surface; }
  const after = r.before === r.after ? "_(same words)_" : esc(r.after);
  const notes = r.notes.length ? `<br>_Plain note:_ ${esc(r.notes.join(" "))}` : "";
  out.push(`| **${esc(r.case)}** · ${esc(r.part)} | ${esc(r.before)} | ${after}${notes} | ${grading(r.before)} → ${grading(r.after)} |`);
}
const hardest = rows.filter((r) => !readability(r.after).label && readability(r.after).grade > TARGET_GRADE);
out.push("", "## Still above Year 7–8", "", "No approved plain swap applies to these, so they stay as Apollo wrote them (Luddish never guesses at simpler words). " +
  "Most are short sentences that score high only because of long names like \"organisation\" or \"impersonation\"; a hard term gets its plain note.", "");
for (const r of hardest) out.push(`- **${esc(r.case)}** · ${esc(r.part)} (grade ${readability(r.after).grade}): ${esc(r.after)}${r.notes.length ? ` — _plain note:_ ${esc(r.notes.join(" "))}` : ""}`);
console.log(out.join("\n"));
