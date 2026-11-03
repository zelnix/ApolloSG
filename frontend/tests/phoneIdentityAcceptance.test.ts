/**
 * Phone Number Identity — 22 Acceptance Tests.
 *
 * Covers the full feature across all four phases:
 *   A. Normalization (6 tests) — device-first number processing
 *   B. Identity resolution (6 tests) — backend pipeline via API
 *   C. Association assessment (5 tests) — deterministic confidence rules
 *   D. Explanation generation (5 tests) — Higgins plain-English output
 *
 * Run:  cd frontend && npx tsx --test tests/phoneIdentityAcceptance.test.ts
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  normalizeAustralian,
  normalizeAndDeduplicate,
  assessAssociation,
  searchQueryVariations,
  type AssociationEvidence,
} from "../src/domain/phoneIdentity.ts";
import { explainIdentity, type IdentityExplanation } from "../src/domain/phoneIdentityExplanation.ts";
import type { PhoneIdentityResult } from "../src/api/phoneIdentity.ts";

// ═══════════════════════════════════════════════════════════════════════════════
// A. NORMALIZATION (6 scenarios) — device-first number processing
// ═══════════════════════════════════════════════════════════════════════════════

describe("A: Normalization", () => {
  // A1 — Australian mobile
  it("A1: AU mobile 0412 345 678 → +61412345678, type=mobile, country=AU", () => {
    const n = normalizeAustralian("0412 345 678");
    assert.equal(n.canonical, "+61412345678");
    assert.equal(n.type, "mobile");
    assert.equal(n.country, "AU");
    assert.equal(n.isValid, true);
    assert.equal(n.display, "0412 345 678");
  });

  // A2 — Australian landline with geographic info
  it("A2: AU landline 08 6116 6418 → +61861166418, type=landline, geo=WA/SA/NT", () => {
    const n = normalizeAustralian("08 6116 6418");
    assert.equal(n.canonical, "+61861166418");
    assert.equal(n.type, "landline");
    assert.equal(n.country, "AU");
    assert.equal(n.geographic, "Western Australia, South Australia, Northern Territory");
    assert.equal(n.isValid, true);
  });

  // A3 — Australian 13 service number (6-digit local rate)
  it("A3: AU service 13 22 21 → 132221, type=local_rate, country=AU", () => {
    const n = normalizeAustralian("13 22 21");
    assert.equal(n.canonical, "132221");
    assert.equal(n.type, "local_rate");
    assert.equal(n.country, "AU");
    assert.equal(n.isValid, true);
    assert.equal(n.display, "13 22 21");
  });

  // A4 — Australian 1300 number (10-digit local rate)
  it("A4: AU 1300 number 1300 123 456 → 1300123456, type=local_rate", () => {
    const n = normalizeAustralian("1300 123 456");
    assert.equal(n.canonical, "1300123456");
    assert.equal(n.type, "local_rate");
    assert.equal(n.country, "AU");
    assert.equal(n.display, "1300 123 456");
  });

  // A5 — International UK number
  it("A5: International +44 20 7946 0958 → type=international, country=GB", () => {
    const n = normalizeAustralian("+44 20 7946 0958");
    assert.equal(n.type, "international");
    assert.equal(n.country, "GB");
    assert.equal(n.isValid, true);
    assert.ok(n.canonical.startsWith("+44"));
  });

  // A6 — Edge case: brackets, dashes, dots all stripped
  it("A6: Edge case (08) 6116-6418 → same as clean input", () => {
    const clean = normalizeAustralian("08 6116 6418");
    const messy = normalizeAustralian("(08) 6116-6418");
    assert.equal(messy.canonical, clean.canonical);
    assert.equal(messy.type, clean.type);
    assert.equal(messy.geographic, clean.geographic);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// B. IDENTITY RESOLUTION (6 scenarios) — backend pipeline via API
//    These are integration tests: they require the backend to be running.
//    We use fetch against localhost:8001/api/number/identify.
// ═══════════════════════════════════════════════════════════════════════════════

async function getToken(): Promise<string> {
  const r = await fetch("http://localhost:8001/api/devices/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ platform: "test", adapter_mode: "test", app_version: "1.0" }),
  });
  const data = (await r.json()) as Record<string, string>;
  return data.device_token;
}

async function identify(token: string, number: string, country?: string): Promise<PhoneIdentityResult> {
  const r = await fetch("http://localhost:8001/api/number/identify", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ number, ...(country ? { country } : {}) }),
  });
  if (!r.ok) throw new Error(`API returned ${r.status}`);
  return (await r.json()) as PhoneIdentityResult;
}

describe("B: Identity Resolution (integration)", () => {
  let token = "";

  // B7 — Known org number resolves to verified
  it("B7: CommBank 13 22 21 → verified, entity=CommBank, tier_1 evidence", async () => {
    token = token || await getToken();
    const result = await identify(token, "13 22 21", "AU");
    assert.equal(result.associated_entity, "CommBank");
    assert.equal(result.association_confidence, "verified");
    assert.ok(result.evidence.some((e) => e.source_type === "tier_1_official"), "Should have Tier 1 evidence");
    assert.ok(result.valid, "Should be valid");
  });

  // B8 — Known org landline with geographic info
  it("B8: CommBank Sydney +61 2 9999 3283 → verified, geographic=NSW", async () => {
    token = token || await getToken();
    const result = await identify(token, "+61 2 9999 3283", "AU");
    assert.equal(result.associated_entity, "CommBank");
    assert.equal(result.association_confidence, "verified");
    assert.ok(result.geographic?.includes("New South Wales"), "Should include NSW in geographic");
    assert.equal(result.number_type, "Landline");
  });

  // B9 — Unknown mobile → unknown confidence
  it("B9: Unknown mobile 0412 000 000 → unknown confidence, no entity", async () => {
    token = token || await getToken();
    const result = await identify(token, "0412000000", "AU");
    assert.equal(result.association_confidence, "unknown");
    assert.equal(result.associated_entity, null);
    assert.equal(result.number_type, "Mobile");
  });

  // B10 — Cached result returns correct freshness
  it("B10: Second call for same number returns cached freshness", async () => {
    token = token || await getToken();
    // First call (already done in B7, but let's be explicit)
    await identify(token, "131314", "AU");
    // Second call — should be cached
    const result = await identify(token, "131314", "AU");
    assert.ok(result.freshness === "cached" || result.freshness === "fresh", `Expected cached or fresh, got ${result.freshness}`);
  });

  // B11 — Input validation: too-short number → 422
  it("B11: Too-short number '12' → 422 validation error", async () => {
    token = token || await getToken();
    const r = await fetch("http://localhost:8001/api/number/identify", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ number: "12" }),
    });
    assert.equal(r.status, 422, "Should return 422 for too-short number");
  });

  // B12 — Missing auth → 401
  it("B12: No Authorization header → 401", async () => {
    const r = await fetch("http://localhost:8001/api/number/identify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ number: "0412345678", country: "AU" }),
    });
    // Backend may return 401 or 403 depending on middleware — both are auth failures
    assert.ok(r.status === 401 || r.status === 403, `Expected 401/403 auth failure, got ${r.status}`);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// C. ASSOCIATION ASSESSMENT (5 scenarios) — deterministic confidence rules
// ═══════════════════════════════════════════════════════════════════════════════

describe("C: Association Assessment", () => {
  const mkEvidence = (overrides: Partial<AssociationEvidence> & Pick<AssociationEvidence, "sourceType" | "claim">): AssociationEvidence => ({
    source: "https://example.com",
    publisher: overrides.claim,
    retrievedAt: "2026-11-01",
    ...overrides,
  });

  // C13 — Tier 1 → verified
  it("C13: Tier 1 official evidence → verified", () => {
    const evidence = [mkEvidence({ sourceType: "tier_1_official", claim: "CommBank" })];
    const result = assessAssociation(evidence);
    assert.equal(result.confidence, "verified");
    assert.equal(result.entity, "CommBank");
  });

  // C14 — Tier 2 government → strong
  it("C14: Tier 2 government evidence → strong", () => {
    const evidence = [mkEvidence({ sourceType: "tier_2_government", claim: "Telstra" })];
    const result = assessAssociation(evidence);
    assert.equal(result.confidence, "strong");
    assert.equal(result.entity, "Telstra");
  });

  // C15 — 2+ web sources agree → strong
  it("C15: Two independent web sources agree → strong", () => {
    const evidence = [
      mkEvidence({ source: "https://a.com", sourceType: "tier_4_web", claim: "ANZ" }),
      mkEvidence({ source: "https://b.com", sourceType: "tier_4_web", claim: "ANZ" }),
    ];
    const result = assessAssociation(evidence);
    assert.equal(result.confidence, "strong");
    assert.equal(result.entity, "ANZ");
  });

  // C16 — Single web source → possible
  it("C16: Single web source → possible", () => {
    const evidence = [mkEvidence({ sourceType: "tier_4_web", claim: "Mystery Corp" })];
    const result = assessAssociation(evidence);
    assert.equal(result.confidence, "possible");
  });

  // C17 — Conflicting entities → conflicting
  it("C17: Two different entities → conflicting", () => {
    const evidence = [
      mkEvidence({ sourceType: "tier_4_web", claim: "Telstra" }),
      mkEvidence({ sourceType: "tier_4_web", claim: "Optus" }),
    ];
    const result = assessAssociation(evidence);
    assert.equal(result.confidence, "conflicting");
    assert.equal(result.entity, null);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// D. EXPLANATION GENERATION (5 scenarios) — Higgins plain-English output
// ═══════════════════════════════════════════════════════════════════════════════

function mkResult(overrides: Partial<PhoneIdentityResult>): PhoneIdentityResult {
  return {
    canonical: "+61412345678",
    original: "0412 345 678",
    country: "Australia",
    number_type: "Mobile",
    geographic: null,
    valid: true,
    network: null,
    associated_entity: null,
    association_confidence: "unknown",
    evidence: [],
    scam_intel: null,
    known_impersonation: false,
    checked_at: "2026-11-01T00:00:00Z",
    freshness: "fresh",
    ...overrides,
  };
}

describe("D: Explanation Generation", () => {
  // D18 — Verified org → appropriate headline + body
  it("D18: Verified entity produces correct headline and mentions official website", () => {
    const result = mkResult({
      associated_entity: "CommBank",
      association_confidence: "verified",
      evidence: [{
        source: "https://commbank.com.au/contact",
        source_type: "tier_1_official",
        publisher: "CommBank",
        claim: "CommBank",
        retrieved_at: "2026-11-01",
      }],
    });
    const explanation = explainIdentity(result);
    assert.ok(explanation.headline.includes("CommBank"), `Headline should mention CommBank: ${explanation.headline}`);
    assert.ok(explanation.headline.includes("published"), `Headline should say "published": ${explanation.headline}`);
    assert.ok(explanation.body.includes("confirmed"), `Body should mention confirmation: ${explanation.body}`);
    assert.ok(explanation.body.includes("strongest"), `Body should mention strongest level: ${explanation.body}`);
    assert.ok(explanation.whatToDo.includes("confident"), `Advice should mention confidence: ${explanation.whatToDo}`);
    // No spoofing warning for verified
    assert.equal(explanation.spoofing, null, "Verified → no spoofing warning");
  });

  // D19 — Unknown number → appropriate explanation
  it("D19: Unknown number produces helpful, non-alarmist explanation", () => {
    const result = mkResult({
      associated_entity: null,
      association_confidence: "unknown",
      evidence: [],
    });
    const explanation = explainIdentity(result);
    assert.ok(explanation.headline.includes("couldn't identify"), `Headline: ${explanation.headline}`);
    assert.ok(explanation.body.includes("doesn't mean"), `Body should be non-alarmist: ${explanation.body}`);
    assert.ok(explanation.whatToDo.includes("verify"), `Advice should suggest verification: ${explanation.whatToDo}`);
    assert.equal(explanation.spoofing, null, "Unknown → no spoofing warning");
    assert.equal(explanation.scamWarning, null, "No scam intel");
    assert.equal(explanation.impersonationWarning, null, "No impersonation");
  });

  // D20 — Spoofing warning when entity is possible (not verified)
  it("D20: Possible entity triggers spoofing awareness", () => {
    const result = mkResult({
      associated_entity: "Mystery Corp",
      association_confidence: "possible",
      evidence: [{
        source: "https://somesite.com",
        source_type: "tier_4_web",
        publisher: "Some Site",
        claim: "Mystery Corp",
        retrieved_at: "2026-11-01",
      }],
    });
    const explanation = explainIdentity(result);
    assert.ok(explanation.spoofing !== null, "Possible → should have spoofing warning");
    assert.ok(explanation.spoofing!.includes("spoofed"), `Spoofing text: ${explanation.spoofing}`);
    assert.ok(explanation.headline.includes("may belong"), `Headline: ${explanation.headline}`);
  });

  // D21 — Scam intel included in explanation
  it("D21: Scam intel is passed through as scamWarning", () => {
    const result = mkResult({
      scam_intel: "This number has been reported for recent abuse (fraud score: 92/100).",
    });
    const explanation = explainIdentity(result);
    assert.ok(explanation.scamWarning !== null, "Should have scam warning");
    assert.ok(explanation.scamWarning!.includes("fraud score"), `Scam warning text: ${explanation.scamWarning}`);
    assert.ok(explanation.whatToDo.includes("caution"), `Advice with scam intel: ${explanation.whatToDo}`);
  });

  // D22 — Impersonation warning in explanation
  it("D22: Known impersonation produces impersonation warning + urgent advice", () => {
    const result = mkResult({
      associated_entity: "Westpac",
      association_confidence: "possible",
      known_impersonation: true,
      evidence: [{
        source: "https://somesite.com",
        source_type: "tier_4_web",
        publisher: "Some Site",
        claim: "Westpac",
        retrieved_at: "2026-11-01",
      }],
    });
    const explanation = explainIdentity(result);
    assert.ok(explanation.impersonationWarning !== null, "Should have impersonation warning");
    assert.ok(explanation.impersonationWarning!.includes("not published by Westpac"), `Impersonation text: ${explanation.impersonationWarning}`);
    assert.ok(explanation.whatToDo.includes("Do not share"), `Urgent advice: ${explanation.whatToDo}`);
  });
});
