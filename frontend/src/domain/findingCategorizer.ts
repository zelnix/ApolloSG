// Finding categorizer: assigns a semantic label to each finding based on its text content.
// Labels are displayed as bold prefixes in the Findings tab (e.g., "Fake URL: The domain...").
// Pure: no React, no native imports.

export interface CategorizedFinding {
  label: string | null;
  text: string;
}

interface CategoryRule {
  label: string;
  /** Patterns that trigger this category (checked against lowercase text). */
  patterns: string[];
  /** Only trigger if none of these words appear (to avoid false positives). */
  excludes?: string[];
}

const CATEGORIES: CategoryRule[] = [
  {
    label: "Fake URL",
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
    label: "Urgency & Threats",
    patterns: ["within 24 hours", "immediately", "will be suspended", "will be permanently",
      "urgent", "act now", "right away", "account will be", "must confirm", "must verify"],
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
    label: "Known Threat",
    patterns: ["blocklist", "threat list", "safe browsing", "phishtank", "reported as",
      "previously reported", "known scam", "known phishing"],
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
    patterns: ["official domain", "official phone", "official address", "verified email",
      "spf pass", "dkim pass", "dmarc pass", "authentication pass"],
  },
  {
    label: "No Suspicious Demands",
    patterns: ["does not ask for", "doesn't ask for", "no suspicious demand",
      "no request for password", "no sensitive info", "simply asks"],
  },
];

/** Assign a semantic label to a finding based on its text content. Returns null when no category matches. */
export function categorize(text: string): string | null {
  const lower = text.toLowerCase();
  for (const rule of CATEGORIES) {
    const excluded = rule.excludes?.some((e) => lower.includes(e));
    if (excluded) continue;
    for (const pattern of rule.patterns) {
      if (pattern.includes(".*")) {
        // Simple wildcard match
        const parts = pattern.split(".*");
        if (parts.every((p) => lower.includes(p))) return rule.label;
      } else if (lower.includes(pattern)) {
        return rule.label;
      }
    }
  }
  return null;
}

/** Categorize a finding: if a label is found, prefix it to the text. */
export function labelFinding(text: string): CategorizedFinding {
  const label = categorize(text);
  return { label, text };
}
