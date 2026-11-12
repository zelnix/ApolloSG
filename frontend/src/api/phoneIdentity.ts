/**
 * Phone Number Identity resolution — who this number belongs to, from Apollo's own sources.
 * Calls POST /api/number/identify and returns a typed result.
 */

import { apiPost } from "@/src/api/client";

/* ── Response types (mirror backend PhoneIdentityResult) ───────────────────── */

export interface IdentityEvidence {
  source: string;
  source_type: string; // tier_1_official | tier_2_government | ... | tier_6_apollo_kb
  publisher: string;
  claim: string;
  retrieved_at: string;
  last_verified_at?: string | null;
}

/** One tier of the progressive phone-number intelligence model. */
export interface PrefixIntelligenceTier {
  tier: "geographic" | "number_block" | "caller";
  description: string;
  entity: string | null;
  /** Qualification: "regional association" | "possible association" | "strong association" | "verified identity" | "unknown" */
  qualifier: string;
  confidence: "high" | "medium" | "low";
  prefix: string;
  detail: string | null;
  /** Named sub-brands, divisions, or business units of the entity. */
  business_units?: string[];
  /** How to reach them back — phone, email, or instruction. */
  callback?: string | null;
  /** Extra context about calling back (e.g. outbound lines don't accept incoming). */
  callback_note?: string | null;
  /** Physical location of the entity. */
  location?: string | null;
}

export interface PhoneIdentityResult {
  canonical: string;
  original: string;
  country: string | null;
  number_type: string | null;
  geographic: string | null;
  valid: boolean;
  network: string | null;

  associated_entity: string | null;
  association_confidence: "verified" | "strong" | "possible" | "unknown" | "conflicting";
  evidence: IdentityEvidence[];
  scam_intel: string | null;
  known_impersonation: boolean;
  /** Curated business registry, not authentication of the incoming caller. */
  verified_business?: {
    business_name: string | null;
    logo_url: string | null;
    number_published_by_business: boolean;
    caller_authenticated: false;
    spoofing_possible: boolean;
    special_service_number: boolean;\n    identity_mismatch?: boolean;
  } | null;

  /** Progressive prefix intelligence: geographic → number_block → caller */
  prefix_intelligence: PrefixIntelligenceTier[];

  checked_at: string | null;
  freshness: "fresh" | "cached" | "stale" | null;

  /** Per-source execution status: "match" | "no_match" | "empty_response" | "unavailable" | "timeout" | "not_checked" */
  lookup_status?: Record<string, string>;
}

/* ── API call ──────────────────────────────────────────────────────────────── */

export async function identifyNumber(number: string, country?: string): Promise<PhoneIdentityResult> {
  return apiPost<PhoneIdentityResult>(
    "/number/identify",
    "number_identify",
    { number, ...(country ? { country } : {}) },
    { timeoutMs: 15000 },
  );
}
