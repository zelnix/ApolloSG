// One report, two screens: Ask Higgins and a threat's Overview show an investigation the same way, and each fact once.
//   Answer → What was found → What it means → (anything else written) → What isn't certain → How ApolloSG checked.
// The top card already says who settled it and why, so nothing below repeats that. A finding the answer already states
// isn't listed again; "How ApolloSG checked" and "What this covered" are one section; the reasons a question wasn't taken
// further are said once there. Pure: no React, no native imports.
import type { Finding, HigginsResponse, PlainEnglish, SourceReference } from "../investigation/types";
import { plainEvidenceRefs, type EvidenceRef } from "./evidenceRefs.ts";
import { categorize } from "./findingCategorizer.ts";
import { sentences } from "./luddish/patterns.ts";
import { detectOrg, type OrgEntry } from "./orgDirectory.ts";
import { compactUrls } from "./urlPresentation.ts";

/** `explain`: Apollo's fixed explanation of a jargon word in the finding — explanatory, never evidence.
 *  `category`: semantic label assigned by the finding categorizer (e.g. "Fake URL", "Panic Tactics"). */
export interface ReportFinding { text: string; detail: string | null; explain?: string | null; findingId?: string; category?: string | null }
export interface ReportSection { title: string; paragraphs: string[] }
export interface Report {
  answer: string[];
  /** How serious it is, in one fixed line (only in Higgins' plain English). */
  severity?: string | null;
  found: ReportFinding[];
  means: string[];
  more: ReportSection[];
  uncertain: string[];
  how: string[];
  sources: SourceReference[];
  /** Higgins Luddish L1's plain notes beside the answer: approved dictionary meanings, never evidence. */
  notes?: string[];
  /** The impersonated organisation detected from the findings (null when none detected). */
  detectedOrg?: OrgEntry | null;
  /** Organisation-specific recommended actions (empty when no org detected). */
  orgActions?: string[];
}

export interface ReportInput {
  overview: string;
  explanationMarkdown?: string | null;
  attentionReason?: string | null;
  findings?: Finding[];
  /** What was found when there is no investigation (a threat Apollo recorded on its own). */
  fallbackFound?: string[];
  fallbackMeans?: string | null;
  uncertainties?: string[];
  scope?: string | null;
  sources?: SourceReference[];
  sourceIds?: string[];
  /** The case's evidence items, so "How ApolloSG checked" can name an item it refers to by id. */
  evidence?: readonly EvidenceRef[];
  /** Already said in the top card (the settled-by sentence), so never repeated below. */
  alreadySaid?: (string | null | undefined)[];
}

const BASIS: Record<string, string> = { observation: "Observed", user_report: "You reported", inference: "Inferred" };
const CONFIDENCE: Record<string, string> = { high: "High confidence", medium: "Medium confidence", low: "Low confidence" };

/** Markdown to plain text, line by line (bullets kept as "- "). */
function plainLine(line: string): string {
  return line.replace(/^#{1,6}\s*/, "").replace(/\*\*(.+?)\*\*/g, "$1").replace(/\*(.+?)\*/g, "$1").replace(/`(.+?)`/g, "$1")
    .replace(/\[(.+?)\]\((https?:[^)]+)\)/g, "$1 ($2)").trim();
}

interface Block { title: string | null; lines: string[] }

/** The explanation's own sections: a "**Title**" or "# Title" line starts one. */
function blocks(markdown: string): Block[] {
  const out: Block[] = [{ title: null, lines: [] }];
  for (const raw of markdown.split("\n")) {
    const heading = raw.match(/^\s*(?:#{1,6}\s+(.+?)|\*\*(.+?)\*\*\s*(.*))\s*$/);
    if (heading && (heading[1] || (heading[2] && !/[.!?]$/.test(heading[2])))) {
      const title = plainLine(heading[1] ?? heading[2]);
      out.push({ title, lines: heading[3] ? [plainLine(heading[3])] : [] });
    } else if (raw.trim()) {
      out[out.length - 1].lines.push(raw.trim());
    }
  }
  return out.filter((b) => b.title || b.lines.length);
}

const isBullet = (line: string) => /^[-*•]\s+/.test(line);
const unbullet = (line: string) => plainLine(line.replace(/^[-*•]\s+/, ""));

/** Paragraphs of a block; consecutive bullets stay separate items. */
function paragraphs(lines: string[]): string[] {
  return lines.map((l) => (isBullet(l) ? unbullet(l) : plainLine(l))).filter(Boolean);
}

const words = (text: string) => text.toLowerCase().replace(/[’‘]/g, "'").replace(/[^a-z0-9'\s]/g, " ").split(/\s+/).filter(Boolean);
const normal = (text: string) => words(text).join(" ");
const grams = (w: string[], n = 4) => w.length < n ? [w.join(" ")] : Array.from({ length: w.length - n + 1 }, (_, i) => w.slice(i, i + n).join(" "));
// Words that carry no meaning of their own. Negations ("not", "no", "isn't") are kept: they change what's said.
const STOP = new Set(("a an the this that these those it its it's is are was were be been being so to of on in at or and but with for by as " +
  "from your you there there's here what which who how would will can could has have had do does did if then than also just into about").split(" "));
const stem = (w: string) => w.replace(/'s$/, "").replace(/(?<=[a-z]{3})s$/, "");
const meaning = (text: string) => new Set(words(text).filter((w) => !STOP.has(w)).map(stem));
/** Share of `a`'s meaningful words that `b` also has. */
const overlap = (a: Set<string>, b: Set<string>) => { let hit = 0; for (const w of a) if (b.has(w)) hit++; return a.size ? hit / a.size : 0; };
const negated = (m: Set<string>) => [...m].some((w) => w === "not" || w === "no" || w === "never" || w.endsWith("n't"));
/** The same point in other words: three quarters of its meaningful words, and the same yes-or-no. */
const sameMeaning = (a: Set<string>, b: Set<string>) => overlap(a, b) >= 0.75 && negated(a) === negated(b);

class Said {
  private texts: string[] = [];
  private gramSet = new Set<string>();
  private meanings: Set<string>[] = [];
  add(text: string) {
    const n = normal(text); if (!n) return;
    this.texts.push(n);
    for (const g of grams(n.split(" "))) this.gramSet.add(g);
    for (const s of sentences(text)) { const m = meaning(s); if (m.size) this.meanings.push(m); }
  }
  /** Already said word for word, inside something longer. */
  contains(text: string) { const n = normal(text); return !!n && this.texts.some((t) => t.includes(n)); }
  /** Mostly said already: word for word, in other words (three quarters of its meaningful words are in one
   *  sentence already said, or spread across all said entries at 85%), or half or more of its four-word runs have appeared. */
  repeats(text: string) {
    if (this.contains(text)) return true;
    const m = meaning(text);
    if (m.size >= 3 && this.meanings.some((said) => sameMeaning(m, said))) return true;
    // Combined-meaning check: the point is spread across multiple things already said
    if (m.size >= 3 && this.meanings.length > 1) {
      const combined = new Set(this.meanings.flatMap((s) => [...s]));
      if (overlap(m, combined) >= 0.95 && negated(m) === [...this.meanings].some(negated)) return true;
    }
    const g = grams(words(text));
    if (g.length < 2) return false;
    return g.filter((x) => this.gramSet.has(x)).length / g.length >= 0.5;
  }
}

const NOT_TAKEN = /^Not taken further, because (.+?): (.+)$/i;
/** A line about how Apollo checked (it names Apollo's own investigators): it belongs on the DI tab, never under what
 *  isn't certain. Cases settled before the server said these under "How ApolloSG checked", and Magnum DI's own wording. */
const METHOD_LINE = /\b(?:TC Hawkeye|Magnum DI|Higgins Triage)\b/;

/** "impersonation: whether it's from Linkt" reads as "impersonation (whether it's from Linkt)". */
function topic(text: string): string {
  const t = text.trim().replace(/\.$/, "");
  const m = t.match(/^([^:()]{1,40}): (.+)$/);
  return m ? `${m[1]} (${m[2]})` : t;
}

export function buildReport(input: ReportInput): Report {
  const said = new Said();
  for (const line of input.alreadySaid ?? []) if (line) said.add(line);

  const explanation = blocks(input.explanationMarkdown ?? "");
  const section = (re: RegExp) => explanation.filter((b) => b.title && re.test(b.title)).flatMap((b) => paragraphs(b.lines));
  const FOUND = /^what (was|apollo|tc hawkeye|magnum di) found/i, MEANS = /^what it means/i, HOW = /^how apollo(?:sg)? (checked|answered)/i;

  // 1. The answer: Higgins' overview, then anything the explanation says before its first heading.
  const answer: string[] = [];
  for (const para of [input.overview, ...explanation.filter((b) => !b.title).flatMap((b) => paragraphs(b.lines))]) {
    const kept = sentences(para).filter((s) => !said.repeats(s));
    if (kept.length) { answer.push(kept.join(" ")); kept.forEach((s) => said.add(s)); }
  }

  // 2. What was found — each fact once; one the answer already states isn't listed again.
  const candidates: ReportFinding[] = input.findings?.length
    ? input.findings.map((f) => ({ text: plainLine(f.text), detail: [BASIS[f.basis] ?? f.basis, CONFIDENCE[f.confidence] ?? f.confidence].filter(Boolean).join(" · ") || null, findingId: f.id }))
    : [...section(FOUND), ...(input.fallbackFound ?? [])].map((text) => ({ text: plainLine(text), detail: null }));
  const found: ReportFinding[] = [];
  for (const f of candidates) {
    if (!f.text || said.contains(f.text)) continue;
    found.push(f);
    said.add(f.text);
  }

  // 3. What it means — a paragraph that mostly restates what's above is left out.
  const means: string[] = [];
  for (const para of [...section(MEANS), ...(input.fallbackMeans ? [input.fallbackMeans] : []), ...(input.attentionReason ? [input.attentionReason] : [])]) {
    const all = sentences(para);
    const kept = all.filter((s) => !said.repeats(s));
    if (!kept.length || kept.length * 2 <= all.length && all.length > 1) continue;
    means.push(kept.join(" "));
    kept.forEach((s) => said.add(s));
  }

  // Anything else the investigation wrote, under its own heading, once.
  const more: ReportSection[] = [];
  for (const b of explanation) {
    if (!b.title || FOUND.test(b.title) || MEANS.test(b.title) || HOW.test(b.title)) continue;
    const paras = paragraphs(b.lines).filter((p) => !said.repeats(p));
    if (paras.length) { more.push({ title: b.title, paragraphs: paras }); paras.forEach((p) => said.add(p)); }
  }

  // 4. What isn't certain. Questions not taken further, and any line about how Apollo checked, go under how Apollo checked.
  const notTaken = new Map<string, string[]>();
  const method: string[] = [];
  const uncertain: string[] = [];
  for (const raw of input.uncertainties ?? []) {
    const line = plainLine(raw);
    const m = line.match(NOT_TAKEN);
    if (m) { notTaken.set(m[1], [...(notTaken.get(m[1]) ?? []), topic(m[2])]); continue; }
    if (METHOD_LINE.test(line)) { method.push(line); continue; }
    if (!line || said.repeats(line)) continue;
    uncertain.push(line);
    said.add(line);
  }

  // 5. How ApolloSG checked — its method, what it left alone and what it didn't open, in one place.
  const how: string[] = [];
  for (const s of [...section(HOW), input.scope ?? ""].flatMap((p) => sentences(p))) {
    if (said.repeats(s)) continue;
    how.push(s);
    said.add(s);
  }
  for (const [reason, topics] of notTaken) {
    // Said right after the sentence that already gives the reason (in the same or other words), else on its own.
    const why = meaning(reason);
    const at = how.findIndex((s) => { const after = normal(s).split(" because ")[1]; return !!after && sameMeaning(why, meaning(after)); });
    if (at >= 0) how.splice(at + 1, 0, `So these weren't taken further: ${topics.join("; ")}.`);
    else how.push(`Not taken further, because ${reason}: ${topics.join("; ")}.`);
  }
  for (const line of method) if (!said.repeats(line)) { how.push(line); said.add(line); }

  const used = new Set(input.sourceIds ?? []);
  const report = presented({ answer, found, means, more, uncertain, how: how.length ? [how.join(" ")] : [], sources: (input.sources ?? []).filter((s) => used.has(s.id)) }, input.evidence);

  // Post-processing: categorize findings and detect impersonated organisation
  const allText = [...report.answer, ...report.found.map((f) => f.text), ...report.means].join(" ");
  const org = detectOrg(allText);

  // Apply semantic labels to findings
  for (const f of report.found) {
    f.category = categorize(f.text);
  }

  // Generate organisation-specific actions
  if (org) {
    report.detectedOrg = org;
    report.orgActions = [
      `Do not click any links or enter your details.`,
      `Report the message: ${org.reportScam}`,
      `If you already clicked or entered credentials: ${org.ifCompromised}`,
    ];
  }

  return report;
}

/** What people read: web addresses shortened in the prose, and "How ApolloSG checked" naming each item it refers to in
 *  plain words rather than by its evidence reference. Sources keep their addresses whole, and nothing stored (the
 *  evidence, redirect chains, the investigation itself) is touched. */
function presented(report: Report, evidence?: readonly EvidenceRef[]): Report {
  return {
    ...report,
    answer: report.answer.map(compactUrls),
    found: report.found.map((f) => ({ ...f, text: compactUrls(f.text), ...(f.explain ? { explain: compactUrls(f.explain) } : {}) })),
    means: report.means.map(compactUrls),
    more: report.more.map((s) => ({ ...s, paragraphs: s.paragraphs.map(compactUrls) })),
    uncertain: report.uncertain.map(compactUrls),
    how: report.how.map((p) => compactUrls(plainEvidenceRefs(p, evidence))),
  };
}

/** Higgins' plain English, only when it passed its Fidelity Check. Otherwise null, and Apollo's own wording is shown. */
export function shownPlainEnglish(response: Pick<HigginsResponse, "plainEnglish"> | null | undefined): PlainEnglish | null {
  const plain = response?.plainEnglish;
  return plain && plain.mode !== "literal" && plain.fidelity?.status === "PASS" ? plain : null;
}

/** The report from Higgins' checked plain English. The server already said each point once and kept every finding,
 *  so nothing is left out here. */
export function plainReport(plain: PlainEnglish, sources?: SourceReference[], sourceIds?: string[], evidence?: readonly EvidenceRef[]): Report {
  const used = new Set(sourceIds ?? []);
  // A line about how Apollo checked is on the DI tab, never under what isn't certain.
  const method = plain.uncertain.filter((line) => NOT_TAKEN.test(line) || METHOD_LINE.test(line));
  const report = presented({
    // The result, then what the case is about ("What it is: the Stoko email address hello@stoko.com.").
    answer: [plain.result, plain.subject].filter((line): line is string => !!line),
    severity: plain.severity || null,
    found: plain.established.map((item) => ({ text: item.text, detail: item.detail || null, explain: item.explain || null })),
    means: [...plain.means, ...plain.matters],
    more: [],
    uncertain: plain.uncertain.filter((line) => !method.includes(line)),
    how: plain.how.length || method.length ? [[...plain.how, ...method].join(" ")] : [],
    sources: (sources ?? []).filter((s) => used.has(s.id)),
  }, evidence);

  // Post-processing: categorize findings and detect impersonated organisation
  const allText = [...report.answer, ...report.found.map((f) => f.text), ...report.means].join(" ");
  const org = detectOrg(allText);

  for (const f of report.found) {
    f.category = categorize(f.text);
  }

  if (org) {
    report.detectedOrg = org;
    report.orgActions = [
      `Do not click any links or enter your details.`,
      `Report the message: ${org.reportScam}`,
      `If you already clicked or entered credentials: ${org.ifCompromised}`,
    ];
  }

  return report;
}

/** A step of what to do: in Higgins' plain English when it's shown, else Apollo's own wording. */
export function stepText(response: HigginsResponse, index: number): string {
  return shownPlainEnglish(response)?.todo[index] ?? response.actions[index]?.instruction ?? "";
}
