/**
 * Phone Number Identity — device-first processing.
 *
 * Pure utility: no network calls, no I/O. Handles:
 *   - Australian phone number normalization (local → E.164)
 *   - Mobile / landline / service-number classification
 *   - Geographic area interpretation (AU landlines)
 *   - Basic international detection
 *   - Duplicate detection after normalization
 *
 * This module provides the LOCAL processing layer for the phone identity feature.
 * It does NOT resolve WHO a number belongs to (that's the backend identity service).
 *
 * ── Australian number anatomy ──
 *   Mobile:   04XX XXX XXX → +614XXXXXXXX
 *   Landline: 0X XXXX XXXX → +61XXXXXXXXX  (X = 2|3|7|8)
 *   13:       13 XX XX     → 13XXXX        (local rate, 6 digits — NOT E.164)
 *   1300:     1300 XXX XXX → 1300XXXXXX    (local rate, 10 digits — NOT E.164)
 *   1800:     1800 XXX XXX → 1800XXXXXX    (free call)
 *   1900:     1900 XXX XXX → 1900XXXXXX    (premium)
 *   Intl:     0011 XX …    → +XX…
 *   Emergency: 000 / 112 / 106
 */

// ── Types ────────────────────────────────────────────────────────────────────

export type NumberType =
  | "mobile"
  | "landline"
  | "local_rate"     // 13XX / 1300
  | "free_call"      // 1800
  | "premium"        // 1900
  | "emergency"
  | "short_code"
  | "international"
  | "unknown";

/** The six tiers from the spec's source hierarchy, plus "local" for device-only classification. */
export type SourceTier =
  | "tier_1_official"        // Organisation's own published number
  | "tier_2_government"      // ACMA, Scamwatch, ABN Lookup, ASIC, etc.
  | "tier_3_regulatory"      // Sector-specific authoritative registers
  | "tier_4_web"             // Public web search results
  | "tier_5_community"       // Directories, caller-reporting, forums
  | "tier_6_apollo_kb"       // ApolloSG's own privacy-safe intelligence
  | "local";                 // Device-only classification (no network)

/** Deterministic association confidence levels. */
export type AssociationConfidence =
  | "verified"     // Strong first-party or equivalent authoritative evidence
  | "strong"       // Multiple reliable independent sources
  | "possible"     // Some credible evidence, insufficient for confidence
  | "unknown"      // No reliable evidence found
  | "conflicting"; // Material evidence pointing to different identities

/** A single piece of evidence supporting (or contradicting) a number association. */
export interface AssociationEvidence {
  source: string;              // URL or source name
  sourceType: SourceTier;
  publisher: string;           // Who published this evidence
  claim: string;               // What the source establishes
  retrievedAt: string;         // ISO date
  lastVerifiedAt?: string;     // ISO date
}

/** The identity record for a phone number — what Apollo knows or has discovered. */
export interface PhoneIdentityRecord {
  /** E.164 or canonical form (+61412345678 or 131114). */
  canonical: string;
  /** Exactly as captured / entered. */
  original: string;
  /** ISO country code or null. */
  country: string | null;
  /** Classification. */
  type: NumberType;
  /** Geographic description for AU landlines ("New South Wales, ACT"). */
  geographic: string | null;
  /** Whether the number passes format validation. */
  isValid: boolean;

  // ── Identity fields (populated by backend resolution) ──

  /** Organisation or entity the number is associated with, if known. */
  associatedEntity: string | null;
  /** Deterministic confidence in the association. */
  associationConfidence: AssociationConfidence;
  /** Evidence supporting the association. */
  evidence: AssociationEvidence[];
  /** Scam/spam intelligence. */
  scamIntel: string | null;
  /** Whether spoofing/impersonation has been reported for this number. */
  knownImpersonation: boolean;
  /** When this identity was last checked / resolved. */
  checkedAt: string | null;
  /** Freshness of the cached result. */
  freshness: "fresh" | "cached" | "stale" | null;
}

/** Result of device-only number processing (no identity resolution yet). */
export interface NormalizedNumber {
  original: string;
  canonical: string;
  country: string | null;
  type: NumberType;
  geographic: string | null;
  isValid: boolean;
  /** Digits-only form for deduplication. */
  digits: string;
  /** Display-formatted version (e.g. "04XX XXX XXX"). */
  display: string;
}

// ── Constants ────────────────────────────────────────────────────────────────

/** Australian geographic area codes → regions. */
const AU_AREA_CODES: Record<string, string> = {
  "2": "New South Wales, ACT",
  "3": "Victoria, Tasmania",
  "7": "Queensland",
  "8": "Western Australia, South Australia, Northern Territory",
};

const EMERGENCY_NUMBERS = new Set(["000", "112", "106"]);

// ── Normalization ────────────────────────────────────────────────────────────

/** Strip all formatting characters, preserving a leading +. */
function stripFormatting(raw: string): string {
  const trimmed = raw.trim();
  if (trimmed.startsWith("+")) {
    return "+" + trimmed.slice(1).replace(/\D/g, "");
  }
  return trimmed.replace(/\D/g, "");
}

/** Normalize an Australian phone number to E.164 (or canonical form for service numbers).
 *
 *  Service numbers (13XX, 1300, 1800, 1900) are kept in their domestic form because
 *  they are not real E.164 telephone numbers — they're routing codes.
 *
 *  International numbers are kept as +CC... */
export function normalizeAustralian(raw: string): NormalizedNumber {
  const original = raw.trim();
  const stripped = stripFormatting(original);

  // ── Emergency ──
  if (EMERGENCY_NUMBERS.has(stripped)) {
    return {
      original, canonical: stripped, country: "AU", type: "emergency",
      geographic: null, isValid: true, digits: stripped, display: stripped,
    };
  }

  // ── Already E.164 with + ──
  if (stripped.startsWith("+")) {
    return normalizeE164(original, stripped);
  }

  // ── Australian international access code (0011...) ──
  if (stripped.startsWith("0011") && stripped.length > 6) {
    const intl = "+" + stripped.slice(4);
    return normalizeE164(original, intl);
  }

  // ── Australian service numbers (13XX, 1300, 1800, 1900) ──
  if (/^13\d{4}$/.test(stripped)) {
    return {
      original, canonical: stripped, country: "AU", type: "local_rate",
      geographic: null, isValid: true, digits: stripped,
      display: `${stripped.slice(0, 2)} ${stripped.slice(2, 4)} ${stripped.slice(4)}`,
    };
  }
  if (/^1300\d{6}$/.test(stripped)) {
    return {
      original, canonical: stripped, country: "AU", type: "local_rate",
      geographic: null, isValid: true, digits: stripped,
      display: `1300 ${stripped.slice(4, 7)} ${stripped.slice(7)}`,
    };
  }
  if (/^1800\d{6}$/.test(stripped)) {
    return {
      original, canonical: stripped, country: "AU", type: "free_call",
      geographic: null, isValid: true, digits: stripped,
      display: `1800 ${stripped.slice(4, 7)} ${stripped.slice(7)}`,
    };
  }
  if (/^1900\d{6}$/.test(stripped)) {
    return {
      original, canonical: stripped, country: "AU", type: "premium",
      geographic: null, isValid: true, digits: stripped,
      display: `1900 ${stripped.slice(4, 7)} ${stripped.slice(7)}`,
    };
  }

  // ── Australian domestic (leading 0) ──
  if (stripped.startsWith("0") && stripped.length === 10) {
    const e164 = "+61" + stripped.slice(1);
    const areaDigit = stripped[1];

    // Mobile (04XX)
    if (areaDigit === "4") {
      return {
        original, canonical: e164, country: "AU", type: "mobile",
        geographic: null, isValid: true, digits: stripped,
        display: `${stripped.slice(0, 4)} ${stripped.slice(4, 7)} ${stripped.slice(7)}`,
      };
    }

    // Landline (02, 03, 07, 08)
    const geo = AU_AREA_CODES[areaDigit];
    if (geo) {
      return {
        original, canonical: e164, country: "AU", type: "landline",
        geographic: geo, isValid: true, digits: stripped,
        display: `${stripped.slice(0, 2)} ${stripped.slice(2, 6)} ${stripped.slice(6)}`,
      };
    }
  }

  // ── Fallback: could be an international number without + ──
  if (stripped.length >= 7 && stripped.length <= 15) {
    return {
      original, canonical: stripped, country: null, type: "unknown",
      geographic: null, isValid: false, digits: stripped, display: original,
    };
  }

  // ── Too short or too long ──
  return {
    original, canonical: stripped, country: null, type: "unknown",
    geographic: null, isValid: false, digits: stripped, display: original,
  };
}

/** Normalize an E.164 number (already starts with +). */
function normalizeE164(original: string, stripped: string): NormalizedNumber {
  // Australian +61
  if (stripped.startsWith("+61")) {
    const national = stripped.slice(3); // digits after +61

    // Mobile +614XX...
    if (national.startsWith("4") && national.length === 9) {
      return {
        original, canonical: stripped, country: "AU", type: "mobile",
        geographic: null, isValid: true, digits: stripped.replace(/\D/g, ""),
        display: `0${national.slice(0, 3)} ${national.slice(3, 6)} ${national.slice(6)}`,
      };
    }

    // Landline +612/3/7/8
    const areaDigit = national[0];
    const geo = AU_AREA_CODES[areaDigit];
    if (geo && national.length === 9) {
      return {
        original, canonical: stripped, country: "AU", type: "landline",
        geographic: geo, isValid: true, digits: stripped.replace(/\D/g, ""),
        display: `0${national[0]} ${national.slice(1, 5)} ${national.slice(5)}`,
      };
    }

    // Other +61 numbers (could be valid AU numbers we don't specifically classify)
    return {
      original, canonical: stripped, country: "AU", type: "unknown",
      geographic: null, isValid: national.length >= 5 && national.length <= 12,
      digits: stripped.replace(/\D/g, ""), display: original,
    };
  }

  // Non-Australian international
  const country = detectCountryFromE164(stripped);
  return {
    original, canonical: stripped, country, type: "international",
    geographic: null, isValid: stripped.length >= 8 && stripped.length <= 16,
    digits: stripped.replace(/\D/g, ""), display: original,
  };
}

// ── Country detection for international numbers ──────────────────────────────

/** Common country calling codes for basic detection. */
const COUNTRY_CODES: [string, string][] = [
  ["+1", "US"],    // US/Canada/Caribbean
  ["+44", "GB"],   // UK
  ["+64", "NZ"],   // New Zealand
  ["+91", "IN"],   // India
  ["+86", "CN"],   // China
  ["+81", "JP"],   // Japan
  ["+82", "KR"],   // South Korea
  ["+65", "SG"],   // Singapore
  ["+60", "MY"],   // Malaysia
  ["+62", "ID"],   // Indonesia
  ["+63", "PH"],   // Philippines
  ["+66", "TH"],   // Thailand
  ["+49", "DE"],   // Germany
  ["+33", "FR"],   // France
  ["+39", "IT"],   // Italy
  ["+34", "ES"],   // Spain
  ["+31", "NL"],   // Netherlands
  ["+46", "SE"],   // Sweden
  ["+47", "NO"],   // Norway
  ["+45", "DK"],   // Denmark
  ["+358", "FI"],  // Finland
  ["+353", "IE"],  // Ireland
  ["+41", "CH"],   // Switzerland
  ["+43", "AT"],   // Austria
  ["+48", "PL"],   // Poland
  ["+55", "BR"],   // Brazil
  ["+52", "MX"],   // Mexico
  ["+27", "ZA"],   // South Africa
  ["+234", "NG"],  // Nigeria
  ["+254", "KE"],  // Kenya
  ["+971", "AE"],  // UAE
  ["+966", "SA"],  // Saudi Arabia
  ["+972", "IL"],  // Israel
  ["+7", "RU"],    // Russia/Kazakhstan
];

function detectCountryFromE164(e164: string): string | null {
  // Try longer prefixes first for specificity
  const sorted = [...COUNTRY_CODES].sort((a, b) => b[0].length - a[0].length);
  for (const [prefix, code] of sorted) {
    if (e164.startsWith(prefix)) return code;
  }
  return null;
}

// ── Batch processing ─────────────────────────────────────────────────────────

/** Normalize a batch of raw number strings and deduplicate by canonical form.
 *  Preserves the first occurrence of each canonical number. */
export function normalizeAndDeduplicate(raws: string[]): NormalizedNumber[] {
  const seen = new Set<string>();
  const out: NormalizedNumber[] = [];
  for (const raw of raws) {
    const n = normalizeAustralian(raw);
    if (seen.has(n.canonical)) continue;
    seen.add(n.canonical);
    out.push(n);
  }
  return out;
}

// ── Display helpers ──────────────────────────────────────────────────────────

/** Human-readable label for a number type. */
export function numberTypeLabel(type: NumberType): string {
  switch (type) {
    case "mobile": return "Mobile";
    case "landline": return "Landline";
    case "local_rate": return "Local rate";
    case "free_call": return "Free call";
    case "premium": return "Premium rate";
    case "emergency": return "Emergency";
    case "short_code": return "Short code";
    case "international": return "International";
    case "unknown": return "Unknown";
  }
}

/** Human-readable label for association confidence. */
export function confidenceLabel(confidence: AssociationConfidence): string {
  switch (confidence) {
    case "verified": return "Verified association";
    case "strong": return "Strong association";
    case "possible": return "Possible association";
    case "unknown": return "Unknown";
    case "conflicting": return "Conflicting evidence";
  }
}

/** One-line description of what Apollo knows about the number's type and location.
 *  Example: "Australian mobile number" or "Landline — Western Australia, South Australia, Northern Territory" */
export function numberDescription(n: NormalizedNumber): string {
  const au = n.country === "AU";
  switch (n.type) {
    case "mobile": return au ? "Australian mobile number" : "Mobile number";
    case "landline": return n.geographic ? `Landline — ${n.geographic}` : (au ? "Australian landline" : "Landline");
    case "local_rate": return "Australian local-rate service number";
    case "free_call": return "Australian free-call number";
    case "premium": return "Australian premium-rate number";
    case "emergency": return "Emergency number";
    case "short_code": return "Short code";
    case "international": {
      const cc = n.country;
      if (!cc) return "International number";
      const name = COUNTRY_NAMES[cc];
      return name ? `International number (${name})` : `International number (${cc})`;
    }
    case "unknown": return au ? "Australian number (type unknown)" : "Phone number";
  }
}

const COUNTRY_NAMES: Record<string, string> = {
  US: "United States", GB: "United Kingdom", NZ: "New Zealand", IN: "India",
  CN: "China", JP: "Japan", KR: "South Korea", SG: "Singapore", MY: "Malaysia",
  ID: "Indonesia", PH: "Philippines", TH: "Thailand", DE: "Germany", FR: "France",
  IT: "Italy", ES: "Spain", NL: "Netherlands", SE: "Sweden", NO: "Norway",
  DK: "Denmark", FI: "Finland", IE: "Ireland", CH: "Switzerland", AT: "Austria",
  PL: "Poland", BR: "Brazil", MX: "Mexico", ZA: "South Africa", NG: "Nigeria",
  KE: "Kenya", AE: "United Arab Emirates", SA: "Saudi Arabia", IL: "Israel",
  RU: "Russia", AU: "Australia",
};

// ── Search query formatting ──────────────────────────────────────────────────

/** Generate search query variations for web lookup of a phone number.
 *  Returns the canonical form plus Australian local-format variations.
 *  These are useful for Tier 4 web discovery. */
export function searchQueryVariations(n: NormalizedNumber): string[] {
  const queries: string[] = [];

  // Always include the canonical form
  if (n.canonical.startsWith("+")) {
    queries.push(`"${n.canonical}"`);
  }

  // Australian variations
  if (n.country === "AU") {
    if (n.type === "mobile" && n.canonical.startsWith("+61")) {
      const local = "0" + n.canonical.slice(3);
      queries.push(`"${local}"`);
      // Spaced: 0412 345 678
      queries.push(`"${local.slice(0, 4)} ${local.slice(4, 7)} ${local.slice(7)}"`);
    } else if (n.type === "landline" && n.canonical.startsWith("+61")) {
      const local = "0" + n.canonical.slice(3);
      queries.push(`"${local}"`);
      // Spaced: 08 6116 6418
      queries.push(`"${local.slice(0, 2)} ${local.slice(2, 6)} ${local.slice(6)}"`);
    } else if (n.type === "local_rate" || n.type === "free_call" || n.type === "premium") {
      queries.push(`"${n.canonical}"`);
      if (n.canonical.length === 10) {
        // Spaced: 1300 123 456
        queries.push(`"${n.canonical.slice(0, 4)} ${n.canonical.slice(4, 7)} ${n.canonical.slice(7)}"`);
      } else if (n.canonical.length === 6) {
        // Spaced: 13 11 14
        queries.push(`"${n.canonical.slice(0, 2)} ${n.canonical.slice(2, 4)} ${n.canonical.slice(4)}"`);
      }
    }
  }

  // International spaced form
  if (n.canonical.startsWith("+") && n.country !== "AU") {
    const digits = n.canonical.replace(/\D/g, "");
    if (digits.length > 6) {
      queries.push(`"${n.original.replace(/[^\d\s+()-]/g, "").trim()}"`);
    }
  }

  // Deduplicate
  const seen = new Set<string>();
  return queries.filter((q) => {
    if (seen.has(q)) return false;
    seen.add(q);
    return true;
  });
}

// ── Association assessment (deterministic) ───────────────────────────────────

/** Deterministic association confidence from structured evidence.
 *  This does NOT require an LLM — it applies fixed rules to the evidence array.
 *
 *  Rules:
 *  1. If any Tier 1 (official) source directly associates the number → VERIFIED
 *  2. If a Tier 2 (government/regulatory) source directly associates → STRONG
 *  3. If 2+ independent Tier 3/4 sources agree → STRONG
 *  4. If 1 Tier 3/4 source associates → POSSIBLE
 *  5. If Tier 5 (community) sources agree → POSSIBLE
 *  6. If sources disagree on entity → CONFLICTING
 *  7. Otherwise → UNKNOWN */
export function assessAssociation(evidence: AssociationEvidence[]): {
  confidence: AssociationConfidence;
  entity: string | null;
} {
  if (!evidence.length) return { confidence: "unknown", entity: null };

  // Group by claimed entity (normalised lower-case)
  const byEntity = new Map<string, { tier: SourceTier; count: number }[]>();
  for (const e of evidence) {
    const key = e.claim.toLowerCase().trim();
    if (!key) continue;
    const list = byEntity.get(key) ?? [];
    list.push({ tier: e.sourceType, count: 1 });
    byEntity.set(key, list);
  }

  // No entity claims at all
  if (byEntity.size === 0) return { confidence: "unknown", entity: null };

  // Conflicting: multiple distinct entity claims
  if (byEntity.size > 1) {
    // Check if the conflict is substantive (not just casing/naming variations)
    const entities = [...byEntity.keys()];
    const substantiveConflict = entities.some((a, i) =>
      entities.slice(i + 1).some((b) => !namesMatch(a, b)),
    );
    if (substantiveConflict) {
      return { confidence: "conflicting", entity: null };
    }
  }

  // Single entity (or name variations of the same entity)
  const [entityKey, sources] = [...byEntity.entries()].sort((a, b) => b[1].length - a[1].length)[0];
  const entity = evidence.find((e) => e.claim.toLowerCase().trim() === entityKey)?.claim ?? entityKey;

  // Check highest tier
  const hasTier1 = sources.some((s) => s.tier === "tier_1_official");
  if (hasTier1) return { confidence: "verified", entity };

  const hasTier2 = sources.some((s) => s.tier === "tier_2_government" || s.tier === "tier_3_regulatory");
  if (hasTier2) return { confidence: "strong", entity };

  const tier34Count = sources.filter((s) => s.tier === "tier_4_web" || s.tier === "tier_3_regulatory").length;
  if (tier34Count >= 2) return { confidence: "strong", entity };

  const hasTier4 = sources.some((s) => s.tier === "tier_4_web");
  if (hasTier4) return { confidence: "possible", entity };

  const tier5Count = sources.filter((s) => s.tier === "tier_5_community").length;
  if (tier5Count >= 2) return { confidence: "possible", entity };

  return { confidence: "possible", entity };
}

/** Fuzzy name matching: "RAC WA" vs "RAC Western Australia" → true.
 *  "RAC WA" vs "Telstra" → false. */
function namesMatch(a: string, b: string): boolean {
  if (a === b) return true;
  // One contains the other
  if (a.includes(b) || b.includes(a)) return true;
  // Tokenise and check overlap
  const tokA = new Set(a.split(/\s+/).filter((t) => t.length > 1));
  const tokB = new Set(b.split(/\s+/).filter((t) => t.length > 1));
  if (tokA.size === 0 || tokB.size === 0) return false;
  const overlap = [...tokA].filter((t) => tokB.has(t)).length;
  return overlap / Math.min(tokA.size, tokB.size) >= 0.5;
}
