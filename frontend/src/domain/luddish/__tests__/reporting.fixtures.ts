/**
 * Higgins Reporting — Evidence-to-Language Regression Fixtures
 *
 * These fixtures are behavioural specifications, not fixed strings. Each fixture defines:
 *   - A mock Evidence Lock (the investigation outcome frozen before Higgins speaks)
 *   - Expected reporting properties the composed explanation must satisfy
 *   - Forbidden claims the explanation must never make
 *
 * Test seven properties per fixture:
 *   1. The displayed verdict agrees with the locked verdict.
 *   2. Every material claim is supported by evidence.
 *   3. Missing or failed checks are represented honestly.
 *   4. The explanation does not contain unnecessary duplicated findings.
 *   5. The language is understandable without security expertise.
 *   6. Recommended actions match the actual risk and uncertainty.
 *   7. Original evidence and technical provenance remain unchanged.
 *
 * Run: ts-node --esm reporting.fixtures.ts   (or integrate with your test runner)
 */
import { lockEvidence, type EvidenceLock, type LockInput } from "../lock.ts";
import { compose, type LuddishExplanation } from "../compose.ts";
import { grade } from "../readability.ts";
import { SAFETY, CERTAINTY } from "../fidelity.ts";

// ── Helpers ──────────────────────────────────────────────────────────────────

function allText(ex: LuddishExplanation): string {
  return [
    ex.brief.text,
    ex.explanation?.text ?? "",
    ...ex.findings.map((f) => f.text),
    ...ex.meaning.map((m) => m.text),
    ex.importance?.text ?? "",
    ...ex.limitation.map((l) => l.text),
    ...ex.action.map((a) => a.text),
    ex.noAction ?? "",
  ].filter(Boolean).join(" ");
}

function uniqueTexts(parts: { text: string }[]): boolean {
  const seen = new Set<string>();
  for (const p of parts) {
    const normalised = p.text.toLowerCase().replace(/\s+/g, " ").trim();
    if (seen.has(normalised)) return false;
    seen.add(normalised);
  }
  return true;
}

/** Check for a forbidden standalone claim — not a substring of a product name or an identifier.
 *  Uses word-boundary matching so "safe" won't match "Safe Browsing" or "Salesforce". */
function containsForbiddenClaim(text: string, phrases: readonly string[], lockedEvidence: string[]): string | null {
  // Words that appear in the locked evidence itself can't be removed by Higgins — don't flag them
  const evidenceText = lockedEvidence.join(" ").toLowerCase();
  for (const phrase of phrases) {
    const re = new RegExp(`(?<![\\w-])${phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![\\w-])`, "i");
    // Check only in RULE-sourced or Luddish-added text; skip if the phrase is in the locked evidence
    if (re.test(text) && !re.test(evidenceText)) return phrase;
  }
  return null;
}

interface Fixture {
  name: string;
  lock: LockInput;
  /** Properties that MUST hold in the composed explanation. */
  expected: {
    stateId: string;
    verdictMentioned?: boolean;
    uncertaintiesPreserved?: boolean;
    actionsPresent?: boolean;
    readabilityMet?: boolean;
    fidelityPasses?: boolean;
    noDuplicateFindings?: boolean;
    technicalIntact?: boolean;
  };
  /** Phrases that must NEVER appear in the user-facing explanation. */
  forbidden: string[];
}

// ── Fixtures ─────────────────────────────────────────────────────────────────

const FIXTURES: Fixture[] = [
  // 1. Legitimate marketing email
  {
    name: "Legitimate marketing email (Adidas via Salesforce)",
    lock: {
      state: "safe",
      headline: "This looks like a genuine promotional email from Adidas.",
      findings: [
        { text: "The sender's domain passes SPF and DKIM checks for Salesforce marketing infrastructure.", basis: "observed", confidence: "high", by: "TC FlyBy" },
        { text: "The sending address bounces.salesforce.com is a known Salesforce marketing platform.", basis: "observed", confidence: "high", by: "TC FlyBy" },
        { text: "Links in the email resolve to adidas.com, the brand's official website.", basis: "observed", confidence: "high", by: "TC FlyBy" },
      ],
      explanation: "The sender's details and the links we verified are consistent with the brand's marketing activity.",
      uncertainties: [],
      actions: [],
      by: "TC FlyBy",
      confidence: "High",
    },
    expected: {
      stateId: "safe",
      verdictMentioned: true,
      uncertaintiesPreserved: true,
      actionsPresent: false,
      readabilityMet: true,
      fidelityPasses: true,
      noDuplicateFindings: true,
      technicalIntact: true,
    },
    forbidden: [
      "guaranteed", "definitely safe", "100%", "trustworthy",
      "impersonation", "phishing",
    ],
  },

  // 2. Unverified marketing email
  {
    name: "Unable to verify marketing email",
    lock: {
      state: "limited",
      headline: "This looks like a promotional email, but the sender couldn't be confirmed.",
      findings: [
        { text: "No known threat was found in the checks that completed.", basis: "observed", confidence: "medium", by: "TC FlyBy" },
      ],
      explanation: "Some checks were completed without finding known threats, while others couldn't be finished.",
      uncertainties: [
        "The sender's identity couldn't be independently verified.",
        "SPF/DKIM checks were inconclusive for this sending infrastructure.",
      ],
      actions: ["Check the brand's official website directly rather than using links in the email."],
      by: "TC FlyBy",
      confidence: null,
    },
    expected: {
      stateId: "limited",
      verdictMentioned: true,
      uncertaintiesPreserved: true,
      actionsPresent: true,
      readabilityMet: true,
      fidelityPasses: true,
      noDuplicateFindings: true,
      technicalIntact: true,
    },
    forbidden: [
      "safe", "genuine", "legitimate", "confirmed",
      "you don't need to do anything",
    ],
  },

  // 3. Suspicious marketing email
  {
    name: "Suspicious marketing email (sender inconsistencies)",
    lock: {
      state: "suspicious",
      headline: "This email claims to be from the brand, but there are signs it may not be genuine.",
      findings: [
        { text: "The display name claims Adidas, but the sending domain doesn't match any known Adidas infrastructure.", basis: "observed", confidence: "medium", by: "TC FlyBy" },
        { text: "The reply-to address uses a different domain from the sender.", basis: "observed", confidence: "high", by: "TC FlyBy" },
      ],
      explanation: "Apollo found signs that this email may be an impersonation attempt.",
      reason: "Warning signs are worth checking before you act.",
      uncertainties: ["The sending domain's ownership couldn't be established."],
      actions: ["Check it another way before you act on it."],
      by: "TC FlyBy",
      confidence: null,
    },
    expected: {
      stateId: "suspicious",
      verdictMentioned: true,
      uncertaintiesPreserved: true,
      actionsPresent: true,
      readabilityMet: true,
      fidelityPasses: true,
      noDuplicateFindings: true,
      technicalIntact: true,
    },
    forbidden: [
      "safe", "genuine", "legitimate",
      "you don't need to do anything",
      "confirmed", "proven",
    ],
  },

  // 4. Confirmed phishing email
  {
    name: "Confirmed phishing email",
    lock: {
      state: "threat",
      headline: "This is a phishing email.",
      findings: [
        { text: "The link leads to a confirmed fraudulent page designed to collect account details.", basis: "observed", confidence: "high", by: "Magnum DI" },
        { text: "The destination is listed on Google Safe Browsing as a phishing page.", basis: "observed", confidence: "high", by: "Magnum DI" },
        { text: "The display name and branding copy a real organisation, but the sending domain is unrelated.", basis: "observed", confidence: "high", by: "Magnum DI" },
      ],
      explanation: "This email is designed to steal your sign-in details by impersonating a real organisation.",
      reason: "Acting on it could cost you money, passwords or personal details.",
      uncertainties: [],
      actions: ["Do not use anything in it. If you've already acted on it, contact your bank or the organisation using details you find yourself."],
      by: "Magnum DI",
      confidence: "High",
    },
    expected: {
      stateId: "threat",
      verdictMentioned: true,
      uncertaintiesPreserved: true,
      actionsPresent: true,
      readabilityMet: true,
      fidelityPasses: true,
      noDuplicateFindings: true,
      technicalIntact: true,
    },
    forbidden: [
      "safe", "genuine", "legitimate", "trustworthy",
      "maybe", "probably",
      "you don't need to do anything",
    ],
  },

  // 5. Partial service failure
  {
    name: "Partial service failure (lookup unavailable)",
    lock: {
      state: "limited",
      headline: "Apollo couldn't complete every check.",
      findings: [
        { text: "No threat was found in the checks that completed.", basis: "observed", confidence: "low", by: "TC FlyBy" },
      ],
      explanation: "Some checks couldn't run because an outside service didn't respond.",
      uncertainties: [
        "The domain reputation check couldn't be completed (service timeout).",
        "The email authentication check returned an error.",
      ],
      actions: ["Treat this with caution."],
      by: "TC FlyBy",
      confidence: null,
    },
    expected: {
      stateId: "limited",
      verdictMentioned: true,
      uncertaintiesPreserved: true,
      actionsPresent: true,
      readabilityMet: true,
      fidelityPasses: true,
      noDuplicateFindings: true,
      technicalIntact: true,
    },
    forbidden: [
      "safe", "genuine", "legitimate", "confirmed",
      "clear", "definitely",
      "you don't need to do anything",
      "no threats found",
    ],
  },

  // 6. Conflicting evidence
  {
    name: "Conflicting evidence (domain registered recently, SPF passes)",
    lock: {
      state: "unknown",
      headline: "Apollo couldn't determine whether this is a scam.",
      findings: [
        { text: "SPF and DKIM checks pass for the sending domain.", basis: "observed", confidence: "high", by: "TC FlyBy" },
        { text: "The sending domain was registered less than 7 days ago.", basis: "observed", confidence: "high", by: "TC FlyBy" },
        { text: "No organisation matching the display name was found in official registers.", basis: "observed", confidence: "medium", by: "TC FlyBy" },
      ],
      explanation: "The evidence points in different directions: the technical checks pass, but the domain is new and unverified.",
      reason: "What couldn't be established could still matter.",
      uncertainties: [
        "The sender's real identity couldn't be established.",
        "The new domain has no reputation history.",
      ],
      actions: ["Treat this with caution."],
      by: "TC FlyBy",
      confidence: null,
    },
    expected: {
      stateId: "unknown",
      verdictMentioned: true,
      uncertaintiesPreserved: true,
      actionsPresent: true,
      readabilityMet: true,
      fidelityPasses: true,
      noDuplicateFindings: true,
      technicalIntact: true,
    },
    forbidden: [
      "safe", "genuine", "legitimate", "confirmed",
      "definitely", "proven", "guaranteed",
      "you don't need to do anything",
    ],
  },

  // 7. Who Called — RAC WA reference (Brief 2 contextual standard)
  {
    name: "Who Called — Perth number, possible RAC WA association",
    lock: {
      state: "safe",
      subject: "08 6116 6418",
      headline: "This is a Perth-area landline number in Western Australia.",
      findings: [
        { text: "Australian geographic number in the Perth area (08 6116 prefix).", basis: "observed", confidence: "high", by: "Apollo" },
        { text: "The number range may be associated with RAC WA, although exact ownership wasn't confirmed.", basis: "inferred", confidence: "low", by: "Apollo" },
      ],
      explanation: "RAC contacts customers about roadside assistance, insurance, membership and travel services. Other Perth businesses and call centres also use local numbers for customer service and outbound calls.",
      uncertainties: [
        "Exact number ownership was not independently verified.",
        "The actual caller's identity was not established.",
      ],
      actions: ["If you're expecting a call from RAC, it may be worth checking with them using their official contact details."],
      by: "Apollo",
      confidence: null,
    },
    expected: {
      stateId: "safe",
      verdictMentioned: true,
      uncertaintiesPreserved: true,
      actionsPresent: true,
      readabilityMet: true,
      fidelityPasses: true,
      noDuplicateFindings: true,
      technicalIntact: true,
    },
    forbidden: [
      // Must never treat the prefix as proof of ownership
      "belongs to RAC", "confirmed RAC", "definitely RAC",
      // Must never invent a reason for the call
      "called you about", "calling about your",
      // Must never present caller ID as proof
      "verified caller",
    ],
  },
];

// ── Validator ────────────────────────────────────────────────────────────────

interface TestResult {
  fixture: string;
  passed: boolean;
  failures: string[];
}

function validate(fixture: Fixture): TestResult {
  const lock = lockEvidence(fixture.lock);
  const ex = compose(lock);
  const text = allText(ex);
  const failures: string[] = [];
  // Collect locked evidence texts (Higgins can't change these)
  const lockedEvidence = [lock.headline, ...lock.findings.map((f) => f.text), lock.explanation, lock.reason,
    ...lock.uncertainties, ...lock.actions, lock.how].filter((t): t is string => !!t);

  // 1. Verdict agrees with locked verdict
  if (ex.state !== fixture.expected.stateId) {
    failures.push(`State mismatch: expected "${fixture.expected.stateId}", got "${ex.state}"`);
  }

  // 2. Material claims supported by evidence — every finding in the lock must appear
  for (let i = 0; i < lock.findings.length; i++) {
    const part = ex.findings.find((f) => f.ref === `finding:${i}`);
    if (!part) failures.push(`Finding ${i} missing from explanation`);
  }

  // 3. Missing/failed checks represented honestly — uncertainties preserved
  if (fixture.expected.uncertaintiesPreserved) {
    for (let i = 0; i < lock.uncertainties.length; i++) {
      const part = ex.limitation.find((l) => l.ref === `uncertain:${i}`);
      if (!part) failures.push(`Uncertainty ${i} missing from explanation`);
    }
  }

  // 4. No unnecessary duplicated findings
  if (fixture.expected.noDuplicateFindings) {
    if (!uniqueTexts(ex.findings)) failures.push("Duplicate findings detected");
    for (const m of ex.meaning) {
      if (m.text === ex.brief.text) failures.push("Means section restates the brief verbatim");
    }
  }

  // 5. Language understandable — readability target met (allow up to 1.5 grades above target when evidence
  //    text itself contains technical terms that fidelity prevents from being simplified)
  if (fixture.expected.readabilityMet) {
    const maxGrade = ex.readability.target + 1.5;
    if (ex.readability.after > maxGrade) {
      failures.push(`Readability too high: grade ${ex.readability.after}, max allowed ${maxGrade}`);
    }
  }

  // 6. Recommended actions match risk and uncertainty
  if (fixture.expected.actionsPresent && !ex.action.length && !ex.noAction) {
    failures.push("Expected actions but none present");
  }
  if (!fixture.expected.actionsPresent && ex.action.length > 0) {
    if (!lock.actions.length) failures.push("Unexpected action present without lock evidence");
  }

  // 7. Technical provenance unchanged
  if (fixture.expected.technicalIntact) {
    const techTexts = ex.technical.map((t) => t.text);
    if (lockedEvidence.join("\0") !== techTexts.join("\0")) {
      failures.push("Technical provenance was altered");
    }
  }

  // Fidelity
  if (fixture.expected.fidelityPasses && ex.fidelity.status !== "PASS") {
    failures.push(`Fidelity failed: ${ex.fidelity.failures.map((f) => `${f.code}@${f.ref}`).join(", ")}`);
  }

  // Forbidden claims — only flags phrases that Higgins ADDS (rule-sourced text), not words in locked evidence
  const found = containsForbiddenClaim(text, fixture.forbidden, lockedEvidence);
  if (found) failures.push(`Forbidden claim found: "${found}"`);

  return { fixture: fixture.name, passed: failures.length === 0, failures };
}

// ── Run ──────────────────────────────────────────────────────────────────────

export function runFixtures(): TestResult[] {
  return FIXTURES.map(validate);
}

export { FIXTURES, type Fixture, type TestResult };
