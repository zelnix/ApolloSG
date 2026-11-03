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

  checked_at: string | null;
  freshness: "fresh" | "cached" | "stale" | null;
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
