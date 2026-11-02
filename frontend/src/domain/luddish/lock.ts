// Higgins Luddish L1 — the Evidence Lock. What Apollo, TC FlyBy or Magnum DI established is frozen before any language
// stage starts: the state, every finding with who established it and how firmly, what isn't certain, what to do and
// who blocked it. Luddish may explain locked findings; it can't modify, reinterpret, strengthen or weaken them.
// A lock whose fingerprint no longer matches is never explained. Pure: no React, no native imports.
import { fingerprint } from "./patterns.ts";
import type { StateId } from "./rules.ts";

export type Basis = "observed" | "inferred" | "reported" | "recorded";
/** Context that raised a finding's confidence (never evidence): this device's own earlier cases, or ApolloSG's
 *  previous reports from other devices. Kept apart so it never reads as the case's own evidence. */
export type RaisedBy = "this_device" | "previous_reports";

export interface LockedFinding {
  readonly text: string;
  readonly basis: Basis;
  readonly confidence: "high" | "medium" | "low" | null;
  /** Who established it (TC FlyBy, Magnum DI, Apollo), when recorded. */
  readonly by: string | null;
  /** What raised its confidence beyond what the case's own evidence gave it, as the result recorded it. */
  readonly raisedBy: readonly RaisedBy[];
}

export interface EvidenceLock {
  readonly state: StateId;
  readonly subject: string | null;
  /** Apollo's one-line answer, in its own words. */
  readonly headline: string | null;
  readonly findings: readonly LockedFinding[];
  /** Apollo's or Higgins' own explanation paragraph (already approved wording). */
  readonly explanation: string | null;
  /** Why it matters, as Apollo recorded it. */
  readonly reason: string | null;
  readonly uncertainties: readonly string[];
  readonly actions: readonly string[];
  /** How ApolloSG checked, in its own words. */
  readonly how: string | null;
  /** Who actually blocked it (Android, your carrier, Apollo's Site Gate). null: not recorded. */
  readonly blockedBy: string | null;
  /** Who recorded the result (Apollo, TC FlyBy, Magnum DI). */
  readonly by: string | null;
  /** How sure Apollo said it is overall, in its own words ("High"). null: not recorded. */
  readonly confidence: string | null;
  readonly fingerprint: string;
}

export interface LockInput {
  state: StateId;
  subject?: string | null;
  headline?: string | null;
  findings?: { text: string; basis?: Basis | null; confidence?: LockedFinding["confidence"]; by?: string | null; raisedBy?: RaisedBy[] | null }[];
  explanation?: string | null;
  reason?: string | null;
  uncertainties?: string[];
  actions?: string[];
  how?: string | null;
  blockedBy?: string | null;
  by?: string | null;
  confidence?: string | null;
}

const clean = (v: string | null | undefined) => (typeof v === "string" && v.trim() ? v.trim() : null);

function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const v of Object.values(value as Record<string, unknown>)) deepFreeze(v);
  }
  return value;
}

const content = (l: Omit<EvidenceLock, "fingerprint">) => JSON.stringify([l.state, l.subject, l.headline, l.findings, l.explanation, l.reason, l.uncertainties, l.actions, l.how, l.blockedBy, l.by, l.confidence]);

export function lockEvidence(input: LockInput): EvidenceLock {
  const body = {
    state: input.state,
    subject: clean(input.subject),
    headline: clean(input.headline),
    findings: (input.findings ?? []).filter((f) => clean(f.text)).map((f) => ({ text: f.text.trim(), basis: f.basis ?? "recorded", confidence: f.confidence ?? null, by: clean(f.by),
      raisedBy: [...new Set(f.raisedBy ?? [])] })),
    explanation: clean(input.explanation),
    reason: clean(input.reason),
    uncertainties: (input.uncertainties ?? []).map((u) => u.trim()).filter(Boolean),
    actions: (input.actions ?? []).map((a) => a.trim()).filter(Boolean),
    how: clean(input.how),
    blockedBy: clean(input.blockedBy),
    by: clean(input.by),
    confidence: clean(input.confidence),
  };
  return deepFreeze({ ...body, fingerprint: fingerprint(content(body)) });
}

/** The lock is exactly as it was made. */
export function lockIntact(lock: EvidenceLock): boolean {
  return Object.isFrozen(lock) && fingerprint(content(lock)) === lock.fingerprint;
}

/** Every piece of locked wording, for the checks that compare against it. */
export function lockedTexts(lock: EvidenceLock): string[] {
  return [lock.headline, ...lock.findings.map((f) => f.text), lock.explanation, lock.reason, ...lock.uncertainties, ...lock.actions, lock.how]
    .filter((t): t is string => !!t);
}
