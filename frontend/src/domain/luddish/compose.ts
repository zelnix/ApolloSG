// Higgins Luddish L1 — the Luddish Composer. Takes a sealed Evidence Lock and writes Higgins' explanation in five
// parts, each from its own place and never mixed:
//   Finding (what Apollo found) → Meaning (what it means) → Importance (why it matters) → Limitation (how sure
//   Apollo is, and what isn't certain) → Action (what to do).
// Locked wording goes through Grammar & Punctuation (plain swaps, safe splits); Luddish adds only its approved state
// wording (rules.ts). Each part is checked on its own: a part whose plain wording changed anything goes back to
// Apollo's words. A sentence still hard to read is kept exactly and given a plain note beside it (dictionary meanings,
// or the state's "In short" line) — evidence fidelity outranks readability. General knowledge comes alongside,
// labelled, never as a finding. The technical detail is the locked wording itself. The whole explanation then passes
// the Evidence Fidelity Check, or Apollo's wording is used throughout. Pure: no React, no native imports.
import { termsIn, type LuddishTerm } from "./dictionary.ts";
import { canon, checkExplanation, differences, findingDetail, inShort, type CheckedPart, type FidelityFailure, type FidelityResult } from "./fidelity.ts";
import { rewrite } from "./grammar.ts";
import { knowledgeFor, KNOWLEDGE_BY_ID, type KnowledgeEntry } from "./knowledge.ts";
import { lockIntact, type EvidenceLock } from "./lock.ts";
import { grade, readability, TARGET_GRADE } from "./readability.ts";
import { BLOCKED_UNKNOWN_ACTOR, STATE_RULES, variant, type StateId } from "./rules.ts";

export type LuddishPart = CheckedPart;
export interface LuddishExplanation {
  state: StateId;
  label: string;
  /** The one-line answer: Apollo's headline in plain words, or the state's approved finding. */
  brief: LuddishPart;
  /** Apollo's own explanation paragraph, in plain words. */
  explanation: LuddishPart | null;
  findings: LuddishPart[];
  meaning: LuddishPart[];
  importance: LuddishPart | null;
  limitation: LuddishPart[];
  action: LuddishPart[];
  /** Said only when there's nothing to do. */
  noAction: string | null;
  how: LuddishPart | null;
  /** The jargon used, each with its approved meaning (explanatory only). */
  terms: { id: string; term: string; meaning: string }[];
  /** Background from the Knowledge Library, labelled as general knowledge with where it comes from. */
  knowledge: KnowledgeEntry[];
  /** Apollo's locked wording, untouched, with what each piece is. */
  technical: { ref: string; label: string; text: string; detail?: string | null }[];
  /** Who recorded the result, and how sure it said it is overall (as recorded; null when it didn't say). */
  by: string;
  confidence: string | null;
  readability: { before: number; after: number; target: number; met: boolean };
  fidelity: FidelityResult;
  /** What sent the plain wording back to Apollo's own wording (empty when it passed first time). */
  fellBack: FidelityFailure[];
}

/** Jargon worth explaining: not a name people know, not one that already took plain words, not ApolloSG's own. */
export const isJargon = (t: LuddishTerm) => !t.familiar && !t.plain && t.category !== "apollosg";
export const jargonIn = (text: string) => termsIn(text).filter(isJargon);

/** The same point already made by one of `said` (three quarters of its meaning-bearing words). */
export function alreadySaid(text: string, said: readonly string[]): boolean {
  const a = new Set(canon(text));
  if (!a.size) return true;
  return said.some((s) => { const b = new Set(canon(s)); let hit = 0; for (const w of a) if (b.has(w)) hit++; return hit / a.size >= 0.75; });
}

const TECHNICAL_LABEL: Record<string, string> = { headline: "Apollo's answer", finding: "Finding", explanation: "Higgins' explanation", reason: "Why it matters",
  uncertain: "Not certain", action: "What to do", how: "How ApolloSG checked" };

function technical(lock: EvidenceLock): LuddishExplanation["technical"] {
  const out: LuddishExplanation["technical"] = [];
  const add = (ref: string, text: string | null, detail?: string | null) => { if (text) out.push({ ref, label: TECHNICAL_LABEL[ref.split(":")[0]], text, ...(detail ? { detail } : {}) }); };
  add("headline", lock.headline);
  lock.findings.forEach((f, i) => add(`finding:${i}`, f.text, findingDetail(f)));
  add("explanation", lock.explanation);
  add("reason", lock.reason);
  lock.uncertainties.forEach((u, i) => add(`uncertain:${i}`, u));
  lock.actions.forEach((a, i) => add(`action:${i}`, a));
  add("how", lock.how);
  return out;
}

const STATE_KNOWLEDGE: Partial<Record<StateId, string>> = { limited: "limited_result", unknown: "limited_result", unavailable: "limited_result", blocked: "blocked_vs_detected" };

export function compose(lock: EvidenceLock, literal = false): LuddishExplanation {
  const rule = STATE_RULES[lock.state];
  const seed = lock.fingerprint;
  const plainAllowed = !literal && lockIntact(lock);
  const explained = new Set<string>();
  const said: string[] = [];

  /** A sentence still hard to read keeps its words; the jargon in it is explained beside it, else "In short". */
  const noteFor = (text: string, inShortToo: boolean): string | null => {
    if (!plainAllowed) return null;
    const hard = readability(text).hard;
    if (!hard.length) return null;
    const terms = hard.flatMap(jargonIn).filter((t, i, all) => !explained.has(t.id) && all.findIndex((x) => x.id === t.id) === i).slice(0, 2);
    terms.forEach((t) => explained.add(t.id));
    if (terms.length) return terms.map((t) => t.meaning).join(" ");
    return inShortToo ? inShort(variant(rule.means, seed)) : null;
  };
  const evidence = (ref: string, text: string, opts: { inShort?: boolean; detail?: string | null } = {}): LuddishPart => {
    // A headline and a step of what to do are warnings: they keep every "not" in full.
    const plain = plainAllowed ? rewrite(text, ref === "headline" || ref.startsWith("action:")) : text;
    const shown = differences(text, plain).length ? text : plain; // any change to the evidence: Apollo's words
    said.push(shown);
    return { ref, text: shown, source: "evidence", note: noteFor(shown, !!opts.inShort), ...(opts.detail !== undefined ? { detail: opts.detail } : {}) };
  };
  const fromRule = (ref: string, text: string | null, onlyIfNew = false): LuddishPart | null => {
    if (!text || (onlyIfNew && alreadySaid(text, said))) return null;
    said.push(text);
    return { ref, text, source: "rule", note: null };
  };
  const stateFinding = variant(rule.finding, seed);
  const finding = stateFinding.includes("{actor}") ? (lock.blockedBy ? stateFinding.replace("{actor}", lock.blockedBy) : BLOCKED_UNKNOWN_ACTOR) : stateFinding;

  // Finding
  const brief = lock.headline ? evidence("headline", lock.headline, { inShort: true }) : fromRule("state", finding)!;
  const findings = lock.findings.map((f, i) => evidence(`finding:${i}`, f.text, { detail: findingDetail(f) }));
  const explanation = lock.explanation ? evidence("explanation", lock.explanation, { inShort: true }) : null;
  // Meaning
  const meaning = [fromRule("means", variant(rule.means, seed), true)].filter((p): p is LuddishPart => !!p);
  // Importance
  const importance = lock.reason ? evidence("reason", lock.reason) : fromRule("matters", rule.matters, true);
  // Limitation
  const limitation = [...lock.uncertainties.map((u, i) => evidence(`uncertain:${i}`, u)), fromRule("limitation", rule.limitation, true)]
    .filter((p): p is LuddishPart => !!p);
  // Action
  const action = lock.actions.length ? lock.actions.map((a, i) => evidence(`action:${i}`, a)) : [fromRule("action", rule.action)].filter((p): p is LuddishPart => !!p);
  const noAction = !lock.actions.length && !rule.action ? rule.noAction : null;
  const how = lock.how ? evidence("how", lock.how) : null;

  // The words explained, and the background that goes with them — never part of the findings.
  const evidenceText = [brief, explanation, ...findings, importance, ...limitation, ...action, how].filter((p): p is LuddishPart => !!p && p.source === "evidence").map((p) => p.text).join(" ");
  const terms = jargonIn(evidenceText).map((t) => ({ id: t.id, term: t.term, meaning: t.meaning }));
  const knowledge = knowledgeFor(termsIn(evidenceText).filter((t) => t.category !== "apollosg").map((t) => t.id));
  const stateEntry = STATE_KNOWLEDGE[lock.state] ? KNOWLEDGE_BY_ID[STATE_KNOWLEDGE[lock.state]!] : null;
  if (stateEntry && !knowledge.includes(stateEntry)) knowledge.push(stateEntry);

  const lockedText = technical(lock).map((t) => t.text).join(" ");
  const after = readability(evidenceText || brief.text);
  const ex: LuddishExplanation = {
    state: lock.state, label: rule.label, brief, explanation, findings, meaning, importance, limitation, action, noAction, how,
    terms, knowledge, technical: technical(lock), by: lock.by ?? "Apollo", confidence: lock.confidence,
    readability: { before: grade(lockedText || brief.text), after: after.grade, target: TARGET_GRADE, met: after.met },
    fidelity: { status: "PASS", failures: [] }, fellBack: [],
  };
  ex.fidelity = checkExplanation(lock, ex);
  // Anything wrong, anywhere: Apollo's own wording throughout (checked again, so a broken lock still shows as FAIL).
  if (ex.fidelity.status === "FAIL" && !literal) return { ...compose(lock, true), fellBack: ex.fidelity.failures };
  return ex;
}
