// Telephone and mobile numbers found inside a threat's original evidence — pure, no I/O.
//
// Candidates are found loosely here and settled by the reputation service, which parses every one
// with libphonenumber: anything that is not a real telephone number (a date, an amount, a reference)
// is rejected there and dropped, rather than being reported as a number Apollo couldn't check.

import type { LookupFailure } from "./reputationLookup.ts";
import { incompleteCheck, type IncompleteCheck } from "./triage/completeness.ts";

export interface EvidencePhoneResult {
  /** Exactly as the number appeared in the material. */
  raw: string;
  /** The number Apollo asked about, as the service normalised it (E.164). */
  number: string;
  /** Reputation decision. "unknown" means no source answered — never that the number is safe. */
  decision: "allow" | "review" | "avoid" | "unknown";
  fraud_score: number | null;
  recent_abuse: boolean | null;
  voip: boolean | null;
  line_type: string | null;
  carrier: string | null;
  country: string | null;
  /** Which source answered. Anything other than a named service means nothing was established. */
  source: "ipqualityscore" | "not_configured" | "unavailable";
  checked_at: string;
  /** Set when the lookup established nothing: how it failed (after the controlled retry), or why the answer was empty.
   *  For a "stale" answer: how the live lookup failed before the last known score was used. */
  lookupFailure?: LookupFailure | null;
  /** "stale" = the live lookup failed and this is the last known score, from `checked_at`. */
  freshness?: "fresh" | "cached" | "stale" | null;
}

const URL_RE = /(?:https?:\/\/|www\.)\S+/gi;
const EMAIL_RE = /[^\s@]+@[^\s@]+\.[^\s@]+/g;
/** A run of digits with phone-style separators. Deliberately loose — the service is the authority. */
const CANDIDATE_RE = /\+?\d(?:[\d\s()-]{4,18})\d/g;
const ISO_DATE = /^\d{4}-\d{1,2}-\d{1,2}$/;
const SHORT_DATE = /^\d{1,2}-\d{1,2}-\d{2,4}$/;

/** Telephone/mobile numbers the material contains, in the order they appear, de-duplicated.
 *  Links and email addresses are removed first so an id inside a URL is never read as a number. */
export function extractPhoneCandidates(text: string, limit = 3): string[] {
  if (!text) return [];
  const cleaned = text.replace(URL_RE, " ").replace(EMAIL_RE, " ");
  const seen = new Set<string>();
  const out: string[] = [];
  for (const match of cleaned.match(CANDIDATE_RE) ?? []) {
    const raw = match.trim().replace(/[\s()-]+$/, "");
    if (ISO_DATE.test(raw) || SHORT_DATE.test(raw)) continue;
    const digits = raw.replace(/\D/g, "");
    // Australian service numbers (13 xx xx) are six digits; everything else needs at least eight.
    const longEnough = digits.length >= 8 || (digits.length === 6 && digits.startsWith("13"));
    if (!longEnough || digits.length > 15) continue;
    if (/^(\d)\1+$/.test(digits)) continue; // 00000000 and friends are never a number to check
    if (seen.has(digits)) continue;
    seen.add(digits);
    out.push(raw);
    if (out.length >= limit) break;
  }
  return out;
}

/** The reputation evidence Triage reads (`phone_reputation`). The worst number that was answered for
 *  speaks for the material; when nothing was answered, the gap is reported as a gap. Null when the
 *  material carries no telephone numbers at all. */
export function phoneTriageReputation(results: EvidencePhoneResult[]): { status: string; verdict?: string; fraud_score?: number } | null {
  if (!results.length) return null;
  const worst = results.find((r) => r.decision === "avoid") ?? results.find((r) => r.decision === "review");
  if (worst) {
    return {
      status: "ok",
      verdict: worst.decision === "avoid" ? "malicious" : "high_risk",
      ...(worst.fraud_score === null ? {} : { fraud_score: worst.fraud_score }),
    };
  }
  if (results.every((r) => r.decision === "unknown")) {
    const failure = results.find((r) => r.lookupFailure)?.lookupFailure;
    return { status: "unavailable", verdict: "unknown", ...(failure ? { failure } : {}) };
  }
  return { status: "ok", verdict: "clean" };
}

/** The number lookups that didn't complete, as incomplete checks: no answer at all, or only the last known score. */
export function phoneIncompleteChecks(results: EvidencePhoneResult[]): IncompleteCheck[] {
  const checks: IncompleteCheck[] = [];
  for (const r of results) {
    const stale = r.decision !== "unknown" && r.freshness === "stale";
    if (r.decision !== "unknown" && !stale) continue;
    const status = stale ? "stale" : "unavailable";
    if (checks.some((c) => c.status === status && c.failure === (r.lookupFailure ?? null) && c.subject === r.number)) continue;
    checks.push({ ...incompleteCheck("number_reputation", r.lookupFailure, { status, source: "ipqs", ...(stale ? { at: r.checked_at } : {}) }), subject: r.number });
  }
  return checks;
}

/** One plain sentence per number: what Apollo asked about and what came back. */
export function phoneFindingLine(r: EvidencePhoneResult): string {
  if (r.decision === "unknown") return `${r.raw} — reputation data was unavailable, so this number was not checked.`;
  const facts = [
    r.fraud_score === null ? null : `fraud score ${r.fraud_score}/100`,
    r.recent_abuse ? "reported for recent abuse" : null,
    r.voip ? "a VOIP number, commonly used to spoof caller ID" : null,
    r.carrier ? `carrier ${r.carrier}` : null,
  ].filter((f): f is string => !!f);
  const verdict = r.decision === "avoid" ? "strong signs of fraud or spam abuse"
    : r.decision === "review" ? "some risk signals — not enough to be certain"
      : "no fraud or abuse signals";
  return `${r.raw} — ${verdict}${facts.length ? ` (${facts.join(", ")})` : ""}${r.freshness === "stale" ? " — the live lookup didn't complete, so this is the result of Apollo's last check" : ""}.`;
}

/** The deterministic findings the case records for flagged numbers in its material. */
export function phoneWhyLines(results: EvidencePhoneResult[]): string[] {
  return results
    .filter((r) => r.decision === "avoid" || r.decision === "review")
    .map((r) => `The number ${r.raw} in this material ${r.decision === "avoid" ? "has strong signs of fraud or spam abuse" : "carries some risk signals"}${r.fraud_score === null ? "" : ` (fraud score ${r.fraud_score}/100)`}.`);
}
