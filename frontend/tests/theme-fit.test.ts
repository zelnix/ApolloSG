/**
 * Unit tests for the theme.ts fit() scaling pipeline.
 * Run:  cd frontend && yarn test:fit   (node:test)
 *
 * Validates that:
 *  - String layout properties (flexDirection, alignItems, …) always pass through
 *  - TEXT_KEYS are scaled by the text factor
 *  - SPACE_KEYS are scaled by the space factor
 *  - NEVER_SCALE properties (flex, opacity, zIndex, …) are never modified
 *  - DIMENSION_KEYS (width, height, borderRadius, …) pass through unchanged
 *  - noFit()-marked style objects skip scaling entirely
 *  - null / undefined style entries are handled gracefully
 *  - Key sets do not overlap (each property belongs to exactly one category)
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { fit, round, noFit, NEVER_SCALE, DIMENSION_KEYS, TEXT_KEYS, SPACE_KEYS } from "../src/theme-scaling.ts";

const SCALE_SPACE = 0.85;
const SCALE_TEXT = 0.9;

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Verify internal round() matches expected RN-style half-point snapping. */
describe("round()", () => {
  it("snaps to nearest 0.5", () => {
    assert.equal(round(12.6, 0.5), 12.5);
    assert.equal(round(14.4, 0.5), 14.5);
    assert.equal(round(19.8, 0.5), 20);
    assert.equal(round(10.0, 0.5), 10);
  });
  it("snaps to nearest 0.01", () => {
    assert.equal(round(0.847, 0.01), 0.85);
    assert.equal(round(0.924, 0.01), 0.92);
  });
});

// ── Early exit ───────────────────────────────────────────────────────────────

describe("fit() early exit", () => {
  it("returns the SAME reference when space=1 and text=1", () => {
    const input = { row: { flexDirection: "row", gap: 8, fontSize: 14 } };
    assert.equal(fit(input, 1, 1), input); // same object reference
  });
});

// ── String / non-number passthrough ──────────────────────────────────────────

describe("fit() non-number passthrough", () => {
  it("preserves flexDirection, alignItems, justifyContent, overflow", () => {
    const result = fit(
      { row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", overflow: "hidden" } },
      SCALE_SPACE,
      SCALE_TEXT,
    );
    assert.equal(result.row.flexDirection, "row");
    assert.equal(result.row.alignItems, "center");
    assert.equal(result.row.justifyContent, "space-between");
    assert.equal(result.row.overflow, "hidden");
  });

  it("preserves boolean and object values", () => {
    const offset = { width: 0, height: 2 };
    const result = fit(
      { card: { shadowOffset: offset, includeFontPadding: false } as any },
      SCALE_SPACE,
      SCALE_TEXT,
    );
    assert.deepEqual(result.card.shadowOffset, offset);
    assert.equal(result.card.includeFontPadding, false);
  });

  it("preserves color strings alongside scaled numbers", () => {
    const result = fit(
      { pill: { backgroundColor: "#FF0000", padding: 16, fontSize: 14 } },
      SCALE_SPACE,
      SCALE_TEXT,
    );
    assert.equal(result.pill.backgroundColor, "#FF0000");
    // padding and fontSize should be scaled
    assert.equal(result.pill.padding, Math.round(16 * SCALE_SPACE));
    assert.equal(result.pill.fontSize, round(14 * SCALE_TEXT, 0.5));
  });
});

// ── TEXT_KEYS scaling ────────────────────────────────────────────────────────

describe("fit() TEXT_KEYS", () => {
  it("scales fontSize by text factor with 0.5 snap", () => {
    const result = fit({ t: { fontSize: 16 } }, SCALE_SPACE, SCALE_TEXT);
    assert.equal(result.t.fontSize, round(16 * SCALE_TEXT, 0.5));
  });

  it("scales lineHeight by text factor with 0.5 snap", () => {
    const result = fit({ t: { lineHeight: 22 } }, SCALE_SPACE, SCALE_TEXT);
    assert.equal(result.t.lineHeight, round(22 * SCALE_TEXT, 0.5));
  });

  it("scales letterSpacing by text factor WITHOUT 0.5 snap", () => {
    const result = fit({ t: { letterSpacing: 0.5 } }, SCALE_SPACE, SCALE_TEXT);
    assert.ok(Math.abs(result.t.letterSpacing - 0.5 * SCALE_TEXT) < 0.0001);
  });
});

// ── SPACE_KEYS scaling ───────────────────────────────────────────────────────

describe("fit() SPACE_KEYS", () => {
  it("scales padding, marginTop, gap by space factor (integer-rounded)", () => {
    const result = fit(
      { box: { padding: 16, marginTop: 8, gap: 12 } },
      SCALE_SPACE,
      SCALE_TEXT,
    );
    assert.equal(result.box.padding, Math.round(16 * SCALE_SPACE));
    assert.equal(result.box.marginTop, Math.round(8 * SCALE_SPACE));
    assert.equal(result.box.gap, Math.round(12 * SCALE_SPACE));
  });

  it("scales all SPACE_KEYS variants", () => {
    const spacingStyles: Record<string, number> = {};
    for (const key of SPACE_KEYS) spacingStyles[key] = 24;
    const result = fit({ s: spacingStyles }, SCALE_SPACE, SCALE_TEXT);
    for (const key of SPACE_KEYS) {
      assert.equal(result.s[key], Math.round(24 * SCALE_SPACE), `${key} should be scaled`);
    }
  });
});

// ── NEVER_SCALE protection ───────────────────────────────────────────────────

describe("fit() NEVER_SCALE", () => {
  it("preserves flex, opacity, zIndex, borderWidth, elevation exactly", () => {
    const result = fit(
      { card: { flex: 1, opacity: 0.5, zIndex: 10, borderWidth: 1, elevation: 4 } },
      SCALE_SPACE,
      SCALE_TEXT,
    );
    assert.equal(result.card.flex, 1);
    assert.equal(result.card.opacity, 0.5);
    assert.equal(result.card.zIndex, 10);
    assert.equal(result.card.borderWidth, 1);
    assert.equal(result.card.elevation, 4);
  });

  it("preserves all NEVER_SCALE properties", () => {
    const neverStyles: Record<string, number> = {};
    for (const key of NEVER_SCALE) neverStyles[key] = 42;
    const result = fit({ ns: neverStyles }, SCALE_SPACE, SCALE_TEXT);
    for (const key of NEVER_SCALE) {
      assert.equal(result.ns[key], 42, `${key} must not be scaled`);
    }
  });
});

// ── DIMENSION_KEYS passthrough ───────────────────────────────────────────────

describe("fit() DIMENSION_KEYS", () => {
  it("passes width, height, borderRadius through unchanged", () => {
    const result = fit(
      { icon: { width: 32, height: 32, borderRadius: 16 } },
      SCALE_SPACE,
      SCALE_TEXT,
    );
    assert.equal(result.icon.width, 32);
    assert.equal(result.icon.height, 32);
    assert.equal(result.icon.borderRadius, 16);
  });

  it("passes all DIMENSION_KEYS through unchanged", () => {
    const dimStyles: Record<string, number> = {};
    for (const key of DIMENSION_KEYS) dimStyles[key] = 100;
    const result = fit({ d: dimStyles }, SCALE_SPACE, SCALE_TEXT);
    for (const key of DIMENSION_KEYS) {
      assert.equal(result.d[key], 100, `${key} must not be scaled`);
    }
  });
});

// ── Null / undefined handling ────────────────────────────────────────────────

describe("fit() null/undefined handling", () => {
  it("handles null style entries gracefully (produces empty object)", () => {
    const result = fit(
      { good: { fontSize: 14 }, bad: null as any },
      SCALE_SPACE,
      SCALE_TEXT,
    );
    assert.equal(result.good.fontSize, round(14 * SCALE_TEXT, 0.5));
    assert.deepEqual(result.bad, {});
  });

  it("handles undefined style entries gracefully (produces empty object)", () => {
    const result = fit(
      { good: { fontSize: 14 }, undef: undefined as any },
      SCALE_SPACE,
      SCALE_TEXT,
    );
    assert.deepEqual(result.undef, {});
  });
});

// ── noFit() escape hatch ─────────────────────────────────────────────────────

describe("noFit()", () => {
  it("skips all scaling on a noFit()-marked style", () => {
    const style = noFit({ flexDirection: "row", gap: 8, fontSize: 14, padding: 16 } as any);
    const result = fit({ row: style }, SCALE_SPACE, SCALE_TEXT);
    assert.equal(result.row.flexDirection, "row");
    assert.equal(result.row.gap, 8);       // SPACE_KEY but not scaled
    assert.equal(result.row.fontSize, 14); // TEXT_KEY but not scaled
    assert.equal(result.row.padding, 16);  // SPACE_KEY but not scaled
  });

  it("only affects the marked style — siblings still scale", () => {
    const result = fit(
      {
        header: noFit({ flexDirection: "row", gap: 8 } as any),
        body: { fontSize: 14, padding: 16 },
      },
      SCALE_SPACE,
      SCALE_TEXT,
    );
    // header: noFit → no scaling
    assert.equal(result.header.gap, 8);
    // body: normal scaling
    assert.equal(result.body.fontSize, round(14 * SCALE_TEXT, 0.5));
    assert.equal(result.body.padding, Math.round(16 * SCALE_SPACE));
  });

  it("returns the same object reference (doesn't clone)", () => {
    const original = { flexDirection: "row" };
    const marked = noFit(original);
    assert.equal(marked, original);
  });
});

// ── Key set disjointness ─────────────────────────────────────────────────────

describe("Key set invariants", () => {
  const allSets = [
    { name: "TEXT_KEYS", set: TEXT_KEYS },
    { name: "SPACE_KEYS", set: SPACE_KEYS },
    { name: "NEVER_SCALE", set: NEVER_SCALE },
    { name: "DIMENSION_KEYS", set: DIMENSION_KEYS },
  ];

  it("no property appears in more than one key set", () => {
    for (let i = 0; i < allSets.length; i++) {
      for (let j = i + 1; j < allSets.length; j++) {
        for (const key of allSets[i].set) {
          assert.equal(
            allSets[j].set.has(key),
            false,
            `"${key}" appears in both ${allSets[i].name} and ${allSets[j].name}`,
          );
        }
      }
    }
  });

  it("all four sets are non-empty", () => {
    for (const { name, set } of allSets) {
      assert.ok(set.size > 0, `${name} must not be empty`);
    }
  });
});
