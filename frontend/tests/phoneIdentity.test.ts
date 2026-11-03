/**
 * Phone number identity — device-first processing tests.
 * Run:  cd frontend && yarn test:phone-identity
 *
 * Covers:
 *  - Australian number normalization (mobile, landline, service, emergency)
 *  - E.164 international numbers
 *  - Geographic area interpretation
 *  - Number classification
 *  - Deduplication
 *  - Search query variations
 *  - Deterministic association assessment
 *  - Display helpers
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  normalizeAustralian,
  normalizeAndDeduplicate,
  numberTypeLabel,
  confidenceLabel,
  numberDescription,
  searchQueryVariations,
  assessAssociation,
  type NormalizedNumber,
  type AssociationEvidence,
} from "../src/domain/phoneIdentity.ts";

// ── Australian mobile ────────────────────────────────────────────────────────

describe("Australian mobile numbers", () => {
  it("normalizes 04XX XXX XXX → +614XXXXXXXX", () => {
    const n = normalizeAustralian("0412 345 678");
    assert.equal(n.canonical, "+61412345678");
    assert.equal(n.country, "AU");
    assert.equal(n.type, "mobile");
    assert.equal(n.isValid, true);
  });

  it("normalizes 0412345678 (no spaces) → +61412345678", () => {
    const n = normalizeAustralian("0412345678");
    assert.equal(n.canonical, "+61412345678");
    assert.equal(n.type, "mobile");
  });

  it("normalizes +61 412 345 678 → +61412345678", () => {
    const n = normalizeAustralian("+61 412 345 678");
    assert.equal(n.canonical, "+61412345678");
    assert.equal(n.type, "mobile");
    assert.equal(n.country, "AU");
  });

  it("normalizes +614XXXXXXXX already in E.164", () => {
    const n = normalizeAustralian("+61412345678");
    assert.equal(n.canonical, "+61412345678");
    assert.equal(n.type, "mobile");
  });

  it("formats mobile for display as 0412 345 678", () => {
    const n = normalizeAustralian("0412345678");
    assert.equal(n.display, "0412 345 678");
  });

  it("describes as 'Australian mobile number'", () => {
    const n = normalizeAustralian("0412345678");
    assert.equal(numberDescription(n), "Australian mobile number");
  });
});

// ── Australian landline ──────────────────────────────────────────────────────

describe("Australian landline numbers", () => {
  it("normalizes 08 6116 6418 → +61861166418 (WA/SA/NT)", () => {
    const n = normalizeAustralian("08 6116 6418");
    assert.equal(n.canonical, "+61861166418");
    assert.equal(n.type, "landline");
    assert.equal(n.country, "AU");
    assert.equal(n.geographic, "Western Australia, South Australia, Northern Territory");
  });

  it("normalizes 02 XXXX XXXX (NSW/ACT)", () => {
    const n = normalizeAustralian("02 9374 5000");
    assert.equal(n.canonical, "+61293745000");
    assert.equal(n.geographic, "New South Wales, ACT");
  });

  it("normalizes 03 XXXX XXXX (VIC/TAS)", () => {
    const n = normalizeAustralian("03 9000 1234");
    assert.equal(n.canonical, "+61390001234");
    assert.equal(n.geographic, "Victoria, Tasmania");
  });

  it("normalizes 07 XXXX XXXX (QLD)", () => {
    const n = normalizeAustralian("07 3000 5678");
    assert.equal(n.canonical, "+61730005678");
    assert.equal(n.geographic, "Queensland");
  });

  it("normalizes +61 8 6116 6418 → +61861166418", () => {
    const n = normalizeAustralian("+61 8 6116 6418");
    assert.equal(n.canonical, "+61861166418");
    assert.equal(n.type, "landline");
    assert.equal(n.geographic, "Western Australia, South Australia, Northern Territory");
  });

  it("formats landline for display as 08 6116 6418", () => {
    const n = normalizeAustralian("0861166418");
    assert.equal(n.display, "08 6116 6418");
  });

  it("describes with geographic info", () => {
    const n = normalizeAustralian("08 6116 6418");
    assert.equal(numberDescription(n), "Landline — Western Australia, South Australia, Northern Territory");
  });
});

// ── Australian service numbers ───────────────────────────────────────────────

describe("Australian service numbers", () => {
  it("normalizes 13 XX XX (6-digit local rate)", () => {
    const n = normalizeAustralian("13 11 14");
    assert.equal(n.canonical, "131114");
    assert.equal(n.type, "local_rate");
    assert.equal(n.country, "AU");
    assert.equal(n.isValid, true);
    assert.equal(n.display, "13 11 14");
  });

  it("normalizes 1300 XXX XXX", () => {
    const n = normalizeAustralian("1300 123 456");
    assert.equal(n.canonical, "1300123456");
    assert.equal(n.type, "local_rate");
    assert.equal(n.display, "1300 123 456");
  });

  it("normalizes 1800 XXX XXX (free call)", () => {
    const n = normalizeAustralian("1800 123 456");
    assert.equal(n.canonical, "1800123456");
    assert.equal(n.type, "free_call");
    assert.equal(n.display, "1800 123 456");
  });

  it("normalizes 1900 XXX XXX (premium)", () => {
    const n = normalizeAustralian("1900 123 456");
    assert.equal(n.canonical, "1900123456");
    assert.equal(n.type, "premium");
    assert.equal(n.display, "1900 123 456");
  });

  it("describes service numbers correctly", () => {
    assert.equal(numberDescription(normalizeAustralian("131114")), "Australian local-rate service number");
    assert.equal(numberDescription(normalizeAustralian("1800123456")), "Australian free-call number");
    assert.equal(numberDescription(normalizeAustralian("1900123456")), "Australian premium-rate number");
  });
});

// ── Emergency ────────────────────────────────────────────────────────────────

describe("Emergency numbers", () => {
  it("recognizes 000", () => {
    const n = normalizeAustralian("000");
    assert.equal(n.type, "emergency");
    assert.equal(n.country, "AU");
    assert.equal(n.isValid, true);
  });

  it("recognizes 112", () => {
    assert.equal(normalizeAustralian("112").type, "emergency");
  });

  it("recognizes 106", () => {
    assert.equal(normalizeAustralian("106").type, "emergency");
  });
});

// ── International ────────────────────────────────────────────────────────────

describe("International numbers", () => {
  it("detects UK number", () => {
    const n = normalizeAustralian("+44 20 7946 0958");
    assert.equal(n.type, "international");
    assert.equal(n.country, "GB");
    assert.equal(n.isValid, true);
  });

  it("detects US number", () => {
    const n = normalizeAustralian("+1 212 555 1234");
    assert.equal(n.type, "international");
    assert.equal(n.country, "US");
  });

  it("detects NZ number", () => {
    const n = normalizeAustralian("+64 9 123 4567");
    assert.equal(n.type, "international");
    assert.equal(n.country, "NZ");
  });

  it("handles 0011 prefix (AU international access)", () => {
    const n = normalizeAustralian("0011 44 20 7946 0958");
    assert.equal(n.canonical, "+442079460958");
    assert.equal(n.type, "international");
    assert.equal(n.country, "GB");
  });

  it("describes international numbers with country name", () => {
    const n = normalizeAustralian("+64 9 123 4567");
    assert.equal(numberDescription(n), "International number (New Zealand)");
  });
});

// ── Edge cases ───────────────────────────────────────────────────────────────

describe("Edge cases", () => {
  it("handles numbers with brackets and dashes", () => {
    const n = normalizeAustralian("(08) 6116-6418");
    assert.equal(n.canonical, "+61861166418");
    assert.equal(n.type, "landline");
  });

  it("handles numbers with dots", () => {
    const n = normalizeAustralian("0412.345.678");
    assert.equal(n.canonical, "+61412345678");
    assert.equal(n.type, "mobile");
  });

  it("preserves original format", () => {
    const n = normalizeAustralian("  (08) 6116-6418  ");
    assert.equal(n.original, "(08) 6116-6418");
  });

  it("handles very short numbers as unknown/invalid", () => {
    const n = normalizeAustralian("123");
    assert.equal(n.type, "unknown");
    assert.equal(n.isValid, false);
  });

  it("handles empty string", () => {
    const n = normalizeAustralian("");
    assert.equal(n.type, "unknown");
    assert.equal(n.isValid, false);
  });
});

// ── Deduplication ────────────────────────────────────────────────────────────

describe("normalizeAndDeduplicate", () => {
  it("deduplicates same number in different formats", () => {
    const results = normalizeAndDeduplicate([
      "08 6116 6418",
      "0861166418",
      "+61 8 6116 6418",
    ]);
    assert.equal(results.length, 1);
    assert.equal(results[0].canonical, "+61861166418");
  });

  it("keeps different numbers", () => {
    const results = normalizeAndDeduplicate(["0412345678", "0861166418"]);
    assert.equal(results.length, 2);
  });

  it("preserves first occurrence's original format", () => {
    const results = normalizeAndDeduplicate(["08 6116 6418", "0861166418"]);
    assert.equal(results[0].original, "08 6116 6418");
  });
});

// ── Search query variations ──────────────────────────────────────────────────

describe("searchQueryVariations", () => {
  it("generates variations for AU landline", () => {
    const n = normalizeAustralian("08 6116 6418");
    const queries = searchQueryVariations(n);
    assert.ok(queries.some((q) => q.includes("+61861166418")));
    assert.ok(queries.some((q) => q.includes("0861166418")));
    assert.ok(queries.some((q) => q.includes("08 6116 6418")));
  });

  it("generates variations for AU mobile", () => {
    const n = normalizeAustralian("0412 345 678");
    const queries = searchQueryVariations(n);
    assert.ok(queries.some((q) => q.includes("+61412345678")));
    assert.ok(queries.some((q) => q.includes("0412345678")));
  });

  it("generates variations for service number", () => {
    const n = normalizeAustralian("1300 123 456");
    const queries = searchQueryVariations(n);
    assert.ok(queries.some((q) => q.includes("1300123456")));
    assert.ok(queries.some((q) => q.includes("1300 123 456")));
  });

  it("deduplicates variations", () => {
    const n = normalizeAustralian("131114");
    const queries = searchQueryVariations(n);
    const unique = new Set(queries);
    assert.equal(queries.length, unique.size);
  });
});

// ── Deterministic association assessment ─────────────────────────────────────

describe("assessAssociation", () => {
  it("returns 'unknown' when no evidence", () => {
    const result = assessAssociation([]);
    assert.equal(result.confidence, "unknown");
    assert.equal(result.entity, null);
  });

  it("returns 'verified' when Tier 1 official source", () => {
    const evidence: AssociationEvidence[] = [{
      source: "https://rac.com.au/contact",
      sourceType: "tier_1_official",
      publisher: "RAC WA",
      claim: "RAC WA",
      retrievedAt: "2026-11-01",
    }];
    const result = assessAssociation(evidence);
    assert.equal(result.confidence, "verified");
    assert.equal(result.entity, "RAC WA");
  });

  it("returns 'strong' when Tier 2 government source", () => {
    const evidence: AssociationEvidence[] = [{
      source: "https://www.acma.gov.au/...",
      sourceType: "tier_2_government",
      publisher: "ACMA",
      claim: "Telstra",
      retrievedAt: "2026-11-01",
    }];
    const result = assessAssociation(evidence);
    assert.equal(result.confidence, "strong");
    assert.equal(result.entity, "Telstra");
  });

  it("returns 'strong' when 2+ independent web sources agree", () => {
    const evidence: AssociationEvidence[] = [
      { source: "https://site-a.com", sourceType: "tier_4_web", publisher: "Site A", claim: "ANZ Bank", retrievedAt: "2026-11-01" },
      { source: "https://site-b.com", sourceType: "tier_4_web", publisher: "Site B", claim: "ANZ Bank", retrievedAt: "2026-11-01" },
    ];
    const result = assessAssociation(evidence);
    assert.equal(result.confidence, "strong");
    assert.equal(result.entity, "ANZ Bank");
  });

  it("returns 'possible' when only 1 web source", () => {
    const evidence: AssociationEvidence[] = [{
      source: "https://some-site.com",
      sourceType: "tier_4_web",
      publisher: "Some Site",
      claim: "ABC Corp",
      retrievedAt: "2026-11-01",
    }];
    const result = assessAssociation(evidence);
    assert.equal(result.confidence, "possible");
  });

  it("returns 'conflicting' when sources disagree on entity", () => {
    const evidence: AssociationEvidence[] = [
      { source: "https://site-a.com", sourceType: "tier_4_web", publisher: "A", claim: "Telstra", retrievedAt: "2026-11-01" },
      { source: "https://site-b.com", sourceType: "tier_4_web", publisher: "B", claim: "Optus", retrievedAt: "2026-11-01" },
    ];
    const result = assessAssociation(evidence);
    assert.equal(result.confidence, "conflicting");
    assert.equal(result.entity, null);
  });

  it("does NOT treat name variations as conflicts ('RAC' vs 'RAC WA')", () => {
    const evidence: AssociationEvidence[] = [
      { source: "https://rac.com.au", sourceType: "tier_1_official", publisher: "RAC", claim: "RAC WA", retrievedAt: "2026-11-01" },
      { source: "https://some-dir.com", sourceType: "tier_5_community", publisher: "Dir", claim: "RAC", retrievedAt: "2026-11-01" },
    ];
    const result = assessAssociation(evidence);
    assert.equal(result.confidence, "verified");
    // Should pick the most descriptive name
    assert.ok(result.entity?.includes("RAC"));
  });

  it("returns 'possible' when 2+ community sources agree", () => {
    const evidence: AssociationEvidence[] = [
      { source: "https://whocalled-a.com", sourceType: "tier_5_community", publisher: "Who Called A", claim: "Pizza Hut", retrievedAt: "2026-11-01" },
      { source: "https://whocalled-b.com", sourceType: "tier_5_community", publisher: "Who Called B", claim: "Pizza Hut", retrievedAt: "2026-11-01" },
    ];
    const result = assessAssociation(evidence);
    assert.equal(result.confidence, "possible");
    assert.equal(result.entity, "Pizza Hut");
  });
});

// ── Display helpers ──────────────────────────────────────────────────────────

describe("Display helpers", () => {
  it("numberTypeLabel covers all types", () => {
    const types: NormalizedNumber["type"][] = ["mobile", "landline", "local_rate", "free_call", "premium", "emergency", "short_code", "international", "unknown"];
    for (const t of types) {
      assert.ok(numberTypeLabel(t).length > 0, `${t} should have a label`);
    }
  });

  it("confidenceLabel covers all levels", () => {
    const levels = ["verified", "strong", "possible", "unknown", "conflicting"] as const;
    for (const l of levels) {
      assert.ok(confidenceLabel(l).length > 0, `${l} should have a label`);
    }
  });
});
