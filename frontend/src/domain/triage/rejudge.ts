// Past cases judged again under the current rules, on this device, from the original kept here. Mirror of the
// backend's services/triage/rejudge.py. Only a text or email that Higgins Triage judged on this phone and that never
// opened an investigation is re-judged: a case with an investigation shows that investigation's own result. Nothing
// new is looked up and no AI is called. The reputation answers the case recorded are reused as they were: its links'
// result, its numbers' results and the checks that couldn't run. Pure, unit-tested in node.
import { analyseEmail } from "../emailAnalysis.ts";
import { patrolSafeSummary } from "../investigation.ts";
import { analyseMessage } from "../messageAnalysis.ts";
import { NATIVE_PROTECTION_PROVENANCE } from "../nativeClassification.ts";
import { phoneIncompleteChecks, phoneTriageReputation, phoneWhyLines } from "../phoneNumbers.ts";
import { STATE_RANK } from "../stateMachine.ts";
import type { ApolloState, PatrolEvent } from "../types";
import type { OriginalSource } from "../../store/originalSource";
import type { IncompleteCheck } from "./completeness.ts";
import { CATALOGUE_VERSION, type TriageInvestigationRecord, type TriageOutcome } from "./contract.ts";
import type { EmailEvidenceProfile } from "./emailEvidence.ts";
import { evaluateTriage } from "./engine.ts";
import { emailTriageEvidence, messageTriageEvidence } from "./evidence.ts";

/** Runs once per rule catalogue version (and per change to this re-judge). */
export const REJUDGE_VERSION = `${CATALOGUE_VERSION}:1`;
export const REJUDGED_LINE = "Apollo checked this again under its updated rules, using the original kept on this device.";

/** The routed link result the record holds ("… handed to the Link Gate, which found: POSSIBLE_THREAT_IDENTIFIED"). */
function recordedLinkOutcome(t: TriageInvestigationRecord): TriageOutcome | null {
  const route = t.rules.find((r) => (r.ruleId === "MSG-12" || r.ruleId === "EMAIL-09") && r.result === "routed");
  const found = route?.evidence.join(" ").match(/which found: ([A-Z_]+)/)?.[1];
  if (found) return found as TriageOutcome;
  return t.rulesMet.includes("LINK-01") ? "POSSIBLE_THREAT_IDENTIFIED" : null;
}

/** The Link Guard lines the case recorded (linkGuard.ts words): kept as they were, with the state each one set. */
const GUARD: [RegExp, ApolloState][] = [
  [/is a known malicious destination|ends at a known malicious host/, "barking"],
  [/^Displayed link says /, "barking"],
  [/^This link redirects through \d+ different domains/, "growling"],
  [/was only registered \d+ days? ago/, "growling"],
];
function recordedGuard(why: string[]): { state: ApolloState; why: string[] } {
  let state: ApolloState = "resting";
  const kept: string[] = [];
  for (const line of why) {
    const hit = GUARD.find(([re]) => re.test(line));
    if (!hit) continue;
    kept.push(line);
    if (STATE_RANK[hit[1]] > STATE_RANK[state]) state = hit[1];
  }
  return { state, why: kept };
}

const higher = (a: ApolloState, b: ApolloState): ApolloState => (STATE_RANK[b] > STATE_RANK[a] ? b : a);
const field = (src: OriginalSource, label: string) => src.fields?.find((f) => f.label.trim().toLowerCase() === label)?.value ?? "";

/** How an email check is filed (checkEmail and this re-judge). A caution with no warning sign behind it — "check
 *  before you tap", "a good sign, not a guarantee" — is not a detection: when Higgins Triage found no threat and the
 *  Link Guard raised nothing, the email is filed as checked, never as something Apollo is reacting to. */
export function emailPatrolState(state: ApolloState, guardState: ApolloState, outcome: TriageOutcome): ApolloState {
  return state === "ears_up" && guardState === "resting" && outcome === "NO_THREAT_IDENTIFIED" ? "resting" : state;
}

/** A case this re-judge applies to: an on-device Triage of a text or email, with no investigation and not trusted. */
export function rejudgeCandidate(e: PatrolEvent): boolean {
  return (e.category === "message" || e.category === "email") && !!e.triage_investigation && !e.investigation_case_id
    && e.status !== "trusted" && e.evidence_provenance !== NATIVE_PROTECTION_PROVENANCE;
}

/** The case as the current rules judge it from its kept original, or null when nothing would change. */
export function rejudgeEvent(e: PatrolEvent, kept: OriginalSource | null, now: string = new Date().toISOString()): PatrolEvent | null {
  const old = e.triage_investigation;
  const text = kept?.text?.trim();
  if (!rejudgeCandidate(e) || !old || !kept || !text) return null;

  const linkOutcome = recordedLinkOutcome(old);
  const linkRulesMet = linkOutcome === "POSSIBLE_THREAT_IDENTIFIED" ? ["LINK-01"] : [];
  const phones = e.evidence_phones ?? [];
  // The checks that couldn't run stay as recorded; a number's are worked out again from its recorded result.
  const carried: IncompleteCheck[] = (old.incompleteChecks ?? []).filter((c) =>
    c.check === "reputation" || c.check === "final_destination" || (!phones.length && c.check === "number_reputation"));
  const incompleteChecks = [...carried, ...phoneIncompleteChecks(phones)];
  const common = { linkOutcome, linkRulesMet, correlation: old.correlation as never, phoneReputation: phoneTriageReputation(phones), incompleteChecks };
  const guard = recordedGuard(e.why ?? []);
  const sender = field(kept, "from");

  let state: ApolloState;
  let triage: TriageInvestigationRecord;
  let words: Pick<PatrolEvent, "headline" | "what_happened" | "what_to_do" | "claimed_brand" | "scenario">;
  let why: string[];
  if (e.category === "message") {
    const analysis = analyseMessage(sender, text);
    triage = evaluateTriage(messageTriageEvidence({ analysis, ...common }));
    state = higher(analysis.state, guard.state);
    const brand = analysis.signals.claimedBrand;
    const headline = analysis.state !== "resting" ? `${analysis.scenarioTitle}${brand ? ` — claims to be ${brand}` : ""}`
      : guard.why.length ? `Suspicious link detected${e.indicator_host ? `: ${e.indicator_host}` : ""}` : "";
    words = { headline, what_happened: patrolSafeSummary(analysis.state !== "resting" ? analysis.verdict : (guard.why[0] ?? analysis.verdict)),
      what_to_do: analysis.recommendation, claimed_brand: brand, scenario: analysis.scenario };
    why = [...analysis.why, ...guard.why, ...phoneWhyLines(phones)];
  } else {
    const profile = e.evidence_profile?.type === "email" ? e.evidence_profile as EmailEvidenceProfile : null;
    if (!profile) return null;
    const auth = profile.auth;
    const fullHeaders = profile.level === "L3" || profile.level === "L4";
    const analysis = analyseEmail(text, { from: sender, subject: field(kept, "subject") },
      { fullHeaders, auth: fullHeaders && auth ? { spf: auth.spf, dkim: auth.dkim, dmarc: auth.dmarc } : null });
    triage = evaluateTriage(emailTriageEvidence({ analysis, profile, ...common }));
    state = emailPatrolState(higher(analysis.state, guard.state), guard.state, triage.outcome);
    words = { headline: `Email: ${analysis.title}`, what_happened: patrolSafeSummary(analysis.verdict), what_to_do: analysis.recommendation,
      claimed_brand: analysis.claimedBrand, scenario: analysis.scenario };
    why = [...analysis.why, ...guard.why, ...phoneWhyLines(phones)];
  }

  if (triage.outcome === old.outcome && state === e.state) return null;
  const noun = e.category === "email" ? "email" : "text message";
  const resting = state === "resting";
  // A case the person already handled stays handled; a case that is now clear is resolved.
  const handled = e.status === "resolved" && e.state !== "resting";
  return {
    ...e, ...words,
    headline: words.headline || (triage.incompleteChecks?.length ? `Not every check could run on this ${noun}` : `No threat found in this ${noun}`),
    state, why: [REJUDGED_LINE, ...why],
    status: resting || handled ? "resolved" : "active",
    resolved_at: resting || handled ? (e.resolved_at ?? now) : null,
    triage_investigation: { ...triage, rejudgedUnder: REJUDGE_VERSION },
    triage_history: [...(e.triage_history ?? []), old],
  };
}
