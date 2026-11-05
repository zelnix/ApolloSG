// Higgins Luddish L1 — the Luddish Rules: one approved set of words for every state ApolloSG reports. A state is
// taken only from what Apollo recorded, never inferred, and never made stronger or weaker. Each sentence has approved
// variations that say exactly the same thing, so Higgins doesn't sound robotic; a variation never changes the
// evidence, how sure Apollo is or how serious it is. A step of what to do says "Do not" in full, like a warning.
// Pure: no React, no native imports.
import { fingerprint } from "./patterns.ts";

export type StateId =
  | "safe" | "threat" | "likely_scam" | "concern" | "suspicious" | "worth_a_look" | "checking"
  | "limited" | "unknown" | "unavailable" | "not_checked" | "failed" | "blocked" | "handled";

export interface StateRule {
  id: StateId;
  label: string;
  /** How strong a concern the state claims (0 none … 5 confirmed). null: it claims nothing about a threat. */
  strength: number | null;
  /** Approved variations of the finding, each saying exactly the same. `{actor}` is who did it (blocked only). */
  finding: readonly string[];
  means: readonly string[];
  matters: string | null;
  limitation: string | null;
  action: string | null;
  /** Said only when there's nothing to do. */
  noAction: string | null;
  /** Words this state's wording may never use: they'd claim a stronger or weaker state. */
  never: readonly string[];
}

const CAUTION = "Treat this with caution.";

export const STATE_RULES: Readonly<Record<StateId, StateRule>> = {
  safe: { id: "safe", label: "This appears safe and legitimate", strength: 0,
    finding: ["No threat was found in the checks that completed.", "The checks that completed found no threat."],
    means: ["Nothing in the checks Apollo completed points to a scam or a threat.", "None of the checks Apollo completed points to a scam or a threat."],
    matters: null, limitation: "This isn't a guarantee: it covers only the checks that completed.", action: null,
    noAction: "You don't need to do anything about this.", never: ["safe", "genuine", "legitimate", "trustworthy", "guaranteed", "definitely"] },
  worth_a_look: { id: "worth_a_look", label: "Something here is worth a look", strength: 1,
    finding: ["Apollo noticed something worth a look."], means: ["It isn't a concern on its own, but it's worth knowing about."],
    matters: null, limitation: "It isn't a warning sign by itself.", action: null, noAction: "You don't need to do anything right now.",
    never: ["safe", "scam", "threat", "dangerous", "confirmed"] },
  suspicious: { id: "suspicious", label: "This is suspicious — check before you act", strength: 2,
    finding: ["Apollo found a possible concern.", "Apollo found something that could be a concern."],
    means: ["Something here could be a warning sign, but it isn't proof of a scam.", "Something here could be a warning sign. It isn't proof of a scam."],
    matters: "Warning signs are worth checking before you act.", limitation: "This is a warning sign, not proof.",
    action: "Check it another way before you act on it.", noAction: null, never: ["safe", "confirmed", "proven", "definitely"] },
  concern: { id: "concern", label: "This is suspicious — exercise caution", strength: 3,
    finding: ["Apollo found a concern.", "Apollo's checks found a concern."],
    means: ["Something Apollo checked needs your attention before you act on it.", "Before you act on this, something Apollo checked needs your attention."],
    matters: "Acting on it before you've checked could put your money, details or phone at risk.", limitation: "A concern isn't proof of a scam.",
    action: "Do not act on it until you've checked it another way.", noAction: null, never: ["safe", "confirmed", "proven", "definitely"] },
  likely_scam: { id: "likely_scam", label: "This is a scam — do not engage", strength: 4,
    finding: ["The evidence points to a scam."], means: ["It's very likely a scam, though Apollo can't be certain."],
    matters: "Scams like this aim to get money, passwords or personal details.", limitation: "This is a strong warning, not proof.",
    action: "Do not reply, tap links, call numbers in it or pay anything.", noAction: null, never: ["safe", "confirmed", "proven"] },
  threat: { id: "threat", label: "This is a confirmed scam or threat", strength: 5,
    finding: ["Apollo's checks confirmed this is a scam or a threat."], means: ["Treat it as a scam."],
    matters: "Acting on it could cost you money, passwords or personal details.", limitation: null,
    action: "Do not use anything in it. If you've already acted on it, contact your bank or the organisation using details you find yourself.",
    noAction: null, never: ["safe", "maybe", "probably"] },
  checking: { id: "checking", label: "Apollo is still looking", strength: null,
    finding: ["Apollo is looking closer."], means: ["Apollo hasn't finished checking, so there's no answer yet."],
    matters: null, limitation: "Nothing has been decided yet.", action: null, noAction: null, never: ["safe", "scam", "confirmed", "threat"] },
  limited: { id: "limited", label: "Apollo couldn't complete all checks", strength: null,
    finding: ["Apollo couldn't complete every check."], means: ["Some checks couldn't run, so Apollo can't give a full answer."],
    matters: "What wasn't checked could still matter.", limitation: "Apollo can't say it's a threat, and it can't say it isn't.",
    action: CAUTION, noAction: null, never: ["safe", "confirmed", "definitely"] },
  unknown: { id: "unknown", label: "Apollo couldn't fully determine the risk", strength: null,
    finding: ["Apollo couldn't determine whether this is a scam."], means: ["There isn't enough evidence to say either way."],
    matters: "What couldn't be established could still matter.", limitation: "I don't have enough evidence to determine that.",
    action: CAUTION, noAction: null, never: ["safe", "confirmed", "definitely"] },
  unavailable: { id: "unavailable", label: "This check was unavailable", strength: null,
    finding: ["This check couldn't be done right now."], means: ["The service Apollo uses for it didn't answer, so nothing was learnt from it."],
    matters: null, limitation: "Apollo couldn't complete this check.", action: null, noAction: null, never: ["safe", "clear", "confirmed"] },
  not_checked: { id: "not_checked", label: "Not checked", strength: null,
    finding: ["This wasn't checked."], means: ["Apollo didn't run this check here, so it tells you nothing either way."],
    matters: null, limitation: "Nothing was found because nothing was checked.", action: null, noAction: null, never: ["safe", "clear", "confirmed"] },
  failed: { id: "failed", label: "Check failed", strength: null,
    finding: ["This check failed."], means: ["Something went wrong while checking, so there's no result from it."],
    matters: null, limitation: "Apollo couldn't complete this check.", action: "Try the check again later.", noAction: null, never: ["safe", "clear", "confirmed"] },
  blocked: { id: "blocked", label: "Blocked", strength: null,
    finding: ["{actor} blocked it.", "It was blocked by {actor}."], means: ["It was stopped before it could reach you."],
    matters: null, limitation: null, action: null, noAction: "You don't need to do anything about what was blocked.", never: [] },
  handled: { id: "handled", label: "Handled", strength: null,
    finding: ["You've marked this as handled."], means: ["Apollo keeps the record, but it no longer needs your attention."],
    matters: null, limitation: null, action: null, noAction: "There's nothing more you need to do.", never: [] },
};

/** "It was blocked." when nobody recorded who blocked it: Apollo never claims a block it didn't make. */
export const BLOCKED_UNKNOWN_ACTOR = "It was blocked.";

// ── ApolloSG's states, mapped exactly. Anything not listed is "unknown": a state is never guessed. ──
const PATROL: Record<string, StateId> = { resting: "safe", sniffing: "checking", ears_up: "worth_a_look", growling: "suspicious", barking: "concern", biting: "blocked" };
const TONE: Record<string, StateId> = { ...PATROL, neutral: "unknown" };
const CHECK_STATUS: Record<string, StateId> = { clear: "safe", concern: "concern", incomplete: "limited", unavailable: "unavailable", not_configured: "not_checked", error: "failed", not_performed: "not_checked" };
const OUTCOME: Record<string, StateId> = { no_scam_indicators: "safe", concerning: "concern", likely_scam: "likely_scam", confirmed_threat: "threat", unable_to_determine: "unknown" };
const ASSESSMENT: Record<string, StateId> = { concern_found: "concern", no_concern_found_within_scope: "safe", uncertain: "unknown" };
const TRIAGE: Record<string, StateId> = { possible_threat: "suspicious", no_threat: "safe", limited: "limited" };

const pickFrom = (table: Record<string, StateId>) => (value: string | null | undefined): StateId => (value && table[value]) || "unknown";
export const stateFromPatrol = pickFrom(PATROL);
export const stateFromTone = pickFrom(TONE);
export const stateFromCheckStatus = pickFrom(CHECK_STATUS);
export const stateFromOutcome = pickFrom(OUTCOME);
export const stateFromAssessment = pickFrom(ASSESSMENT);
export const stateFromTriage = pickFrom(TRIAGE);

/** Never a stronger state than the one recorded: a proposed state that claims more than `recorded` is refused. */
export function noStronger(recorded: StateId, proposed: StateId): StateId {
  const a = STATE_RULES[recorded].strength, b = STATE_RULES[proposed].strength;
  if (b === null || a === null) return recorded;
  return b > a ? recorded : proposed;
}

/** One approved variation, chosen the same way every time for the same case (seeded), so a case reads consistently. */
export function variant(options: readonly string[], seed: string): string {
  if (!options.length) return "";
  return options[parseInt(fingerprint(seed), 16) % options.length];
}
