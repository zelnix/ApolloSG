// Finding categorizer: assigns a semantic label to each finding based on its text content.
// Labels are displayed as bold prefixes in the Findings tab (e.g., "Fake Domain: commbank-cancel.co carries...").
// A label follows the finding's RESULT, never just its topic (owner, 2026-11-08): the same check reads
// "Fake Domain" when the address isn't the organisation's and "Official Domain" when it is; "Known Threat" when a
// list names the address and "Not on Threat Lists" when none does. A check that couldn't be completed is said so,
// never dressed as a result. Pure: no React, no native imports.

interface CategoryRule {
  /** The label when the finding states the check's plain result ("...is the official domain", "...lists it as phishing"). */
  label: string;
  /** Patterns that trigger this category (checked against lowercase text; "a.*b" = both a and b, any order). */
  patterns: string[];
  /** Only trigger if none of these words appear (to avoid false positives). */
  excludes?: string[];
  /** The label when the finding says the check came out the other way ("isn't the official domain", "isn't listed"):
   *  read for a negation (NEGATED) and, where given, these extra words. */
  negated?: { label: string; also?: string[] };
}

/** "isn't", "is not", "not listed", "no scam warning", "never flagged", "nothing found"... */
const NEGATED = /\b(?:isn't|is not|aren't|are not|wasn't|was not|weren't|were not|doesn't|does not|not|no|none|never|nothing)\b/;

// Order matters: the first matching rule wins, so the specific comes before the general ("Safe Browsing lists this
// domain" is a threat-list finding, not a domain one; "registered 3 days ago" is about age, not ownership).
const CATEGORIES: CategoryRule[] = [
  {
    // "Google Safe Browsing was unavailable for this link." / "...couldn't be checked." — nothing was found either way.
    label: "Check Not Completed",
    patterns: ["unavailable", "couldn't be checked", "could not be checked", "couldn't be completed", "could not be completed",
      "couldn't be read", "could not be read", "timed out", "couldn't be reached", "could not be reached"],
  },
  {
    // "example.test was registered on 2026-06-01 (4 days before this check)." — when, not whose.
    label: "Domain Age",
    patterns: ["was registered", "registered on", "registered less than", "registration record", "newly registered",
      "days before this check", "days ago", "hours ago", "weeks ago"],
  },
  {
    label: "Known Threat",
    negated: { label: "Not on Threat Lists" },
    patterns: ["blocklist", "threat list", "safe browsing", "phishtank", "openphish", "spamhaus", "reported as",
      "previously reported", "known scam", "known phishing", "scam warning", "investor alert"],
  },
  {
    // "The TLS certificate for example.gov.au is issued for example.gov.au by Let's Encrypt and is valid."
    label: "Valid Certificate",
    negated: { label: "Certificate Problem", also: ["invalid", "expired", "mismatch", "self-signed", "revoked"] },
    patterns: ["tls certificate", "ssl certificate", "security certificate", "certificate for"],
  },
  {
    label: "Official Domain",
    negated: { label: "Fake Domain", also: ["lookalike", "fake", "unofficial", "mismatch", "carries", "puts"] },
    patterns: ["domain", "isn't an official", "not an official", "official url", "official web address", "lookalike",
      "official domain", "doesn't match", "carries the name", "fake website", "unofficial"],
  },
  {
    label: "Unsecured Link",
    patterns: ["http:// instead of https", "http rather than https", "not using https", "insecure link",
      "unencrypted", "no tls", "no ssl"],
  },
  {
    label: "Credential Harvesting",
    patterns: ["password", "pin or sign-in", "credentials", "login details", "netbank password",
      "client number", "asking for your", "enter your details", "harvesting"],
  },
  {
    label: "Urgency Tactics",
    patterns: ["within 24 hours", "immediately", "will be suspended", "will be permanently",
      "urgent", "act now", "right away", "account will be", "must confirm", "must verify",
      "presses you to act", "pressure word"],
  },
  {
    label: "Panic Tactics",
    patterns: ["payment of $", "transaction of $", "purchase of $", "charge of $", "debit of",
      "crypto exchange", "unauthorised", "unusual sign-in", "suspicious activity",
      "pretend a large", "trick you into"],
  },
  {
    label: "Sender Mismatch",
    patterns: ["sender", "display name", "from address", "reply-to", "sent from a different",
      "doesn't match the claimed", "email address doesn't", "not from the organisation"],
  },
  {
    label: "Suspicious Link",
    patterns: ["redirect", "shortened url", "link goes to", "link leads to", "url shortener",
      "suspicious link", "link doesn't go"],
  },
  {
    label: "Impersonation",
    patterns: ["impersonat", "pretending to be", "posing as", "claims to be from",
      "branded as", "uses the name", "fake branding"],
  },
  {
    label: "Scam Pattern",
    patterns: ["scam indicator", "scam pattern", "multiple.*indicator", "coherent pattern",
      "consistent with scam", "common scam"],
  },
  {
    label: "Official Verification",
    patterns: ["official phone", "official address", "verified email",
      "spf pass", "dkim pass", "dmarc pass", "authentication pass"],
  },
  {
    label: "No Suspicious Demands",
    patterns: ["does not ask for", "doesn't ask for", "no suspicious demand",
      "no request for password", "no sensitive info", "simply asks", "asks for nothing"],
  },
];

/** Every label a finding can carry, for tests and callers that list them. */
export const CATEGORY_LABELS: readonly string[] = CATEGORIES.flatMap((c) => [c.label, ...(c.negated ? [c.negated.label] : [])]);

function matches(lower: string, pattern: string): boolean {
  if (pattern.includes(".*")) return pattern.split(".*").every((p) => lower.includes(p));
  return lower.includes(pattern);
}

/** Assign a semantic label to a finding based on its text content. Returns null when no category matches. */
export function categorize(text: string): string | null {
  const lower = text.toLowerCase().replace(/[’‘]/g, "'");
  for (const rule of CATEGORIES) {
    if (rule.excludes?.some((e) => lower.includes(e))) continue;
    if (!rule.patterns.some((p) => matches(lower, p))) continue;
    if (rule.negated && (NEGATED.test(lower) || rule.negated.also?.some((w) => lower.includes(w)))) return rule.negated.label;
    return rule.label;
  }
  return null;
}
