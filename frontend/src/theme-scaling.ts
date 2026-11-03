/**
 * Pure scaling utilities for the Apollo theme pipeline.
 *
 * Separated from theme.ts so they can be:
 *  1. Tested without React Native imports (node --test)
 *  2. Used by non-React utilities if needed
 *
 * theme.ts imports and wires these into makeStyles() / makeStaticStyles().
 *
 * ── Property categories ──
 *  TEXT_KEYS      — fontSize, lineHeight, letterSpacing (scaled by text factor)
 *  SPACE_KEYS     — padding*, margin*, gap* (scaled by space factor)
 *  NEVER_SCALE    — flex, opacity, zIndex, borderWidth, … (unitless / crisp, never touched)
 *  DIMENSION_KEYS — width, height, borderRadius, … (not scaled by default; opt-in TBD)
 */

// ── Scalable key sets ────────────────────────────────────────────────────────

export const TEXT_KEYS = new Set(["fontSize", "lineHeight", "letterSpacing"]);

export const SPACE_KEYS = new Set([
  "padding", "paddingHorizontal", "paddingVertical", "paddingTop", "paddingBottom", "paddingLeft", "paddingRight", "paddingStart", "paddingEnd",
  "margin", "marginHorizontal", "marginVertical", "marginTop", "marginBottom", "marginLeft", "marginRight", "marginStart", "marginEnd",
  "gap", "rowGap", "columnGap",
]);

// ── Non-scalable key sets ────────────────────────────────────────────────────

/** Properties that must NEVER be scaled — unitless ratios, multipliers, ordering
 *  values, intentionally-crisp widths, or values whose visual meaning would break
 *  if rounded (e.g. opacity 0.5 becoming 1 on a narrow phone). */
export const NEVER_SCALE = new Set([
  // Flex layout (unitless ratios / weights)
  "flex", "flexGrow", "flexShrink",
  // Visual multipliers
  "opacity", "shadowOpacity",
  // Z-ordering (integer, not a dimension)
  "zIndex", "elevation",
  // Aspect ratio (unitless)
  "aspectRatio",
  // Border widths — intentionally thin/crisp; scaling blurs hairline borders
  "borderWidth", "borderTopWidth", "borderBottomWidth",
  "borderLeftWidth", "borderRightWidth", "borderStartWidth", "borderEndWidth",
  // Shadow geometry — platform-specific, not screen-relative
  "shadowRadius",
  // Font weight when numeric (e.g. 700 — it's a weight class, not a size)
  "fontWeight",
  // Text shadow
  "textShadowRadius",
]);

/** Dimension properties we recognise but deliberately do NOT scale by default.
 *  They are design-point values whose scaling needs per-component judgement.
 *  Listed here so they don't trigger the __DEV__ unknown-property warning. */
export const DIMENSION_KEYS = new Set([
  "width", "height", "minWidth", "minHeight", "maxWidth", "maxHeight",
  "top", "bottom", "left", "right", "start", "end",
  "flexBasis",
  "borderRadius", "borderTopLeftRadius", "borderTopRightRadius",
  "borderBottomLeftRadius", "borderBottomRightRadius",
  "borderTopStartRadius", "borderTopEndRadius",
  "borderBottomStartRadius", "borderBottomEndRadius",
]);

// ── noFit escape hatch ──────────────────────────────────────────────────────
// Mark individual style objects inside a makeStyles factory to skip fit() scaling.
// Usage:  makeStyles((c) => ({ row: noFit({ flexDirection: "row", gap: 8 }), text: { fontSize: 14 } }))
// The row's gap stays 8 on every screen; the text's fontSize still scales.
const _noFitSet = new WeakSet<object>();

/** Mark a style object to skip responsive scaling inside makeStyles' fit() pipeline.
 *  The object is returned unchanged; the marker is stored externally via WeakSet
 *  and garbage-collected when the style object is. */
export function noFit<T extends Record<string, any>>(style: T): T {
  _noFitSet.add(style);
  return style;
}

// Dev-mode warning deduplication — only log each unknown numeric key once per session.
const _warnedKeys: Set<string> | undefined =
  typeof __DEV__ !== "undefined" && __DEV__ ? new Set() : undefined;

// ── Core utilities ───────────────────────────────────────────────────────────

export const round = (value: number, step: number) => Math.round(value / step) * step;

/** Scale spacing and text properties for the current screen width.
 *
 *  **What gets scaled:**
 *  - `TEXT_KEYS` (fontSize, lineHeight, letterSpacing) — by `text` factor.
 *  - `SPACE_KEYS` (padding*, margin*, gap*) — by `space` factor.
 *
 *  **What is explicitly preserved:**
 *  - `NEVER_SCALE` (flex, opacity, zIndex, borderWidth, elevation, …) — unitless/crisp values.
 *  - `DIMENSION_KEYS` (width, height, borderRadius, …) — design-point dimensions (opt-in scaling TBD).
 *  - All non-number values (strings like flexDirection, objects like shadowOffset) — always pass through.
 *  - `noFit()`-marked style objects — skip scaling entirely.
 *
 *  In `__DEV__`, unrecognised numeric properties trigger a one-time console warning so they can be
 *  categorised in the appropriate set. */
export function fit<T extends Record<string, any>>(styles: T, space: number, text: number): T {
  if (space === 1 && text === 1) return styles;
  const out: Record<string, any> = {};
  for (const [name, style] of Object.entries(styles)) {
    // Guard: null / undefined / non-object → empty object (preserves StyleSheet.create contract)
    if (!style || typeof style !== "object") {
      out[name] = {};
      continue;
    }
    // noFit() escape hatch — skip scaling entirely for this style object
    if (_noFitSet.has(style)) {
      out[name] = style;
      continue;
    }
    const next: Record<string, any> = {};
    for (const [key, value] of Object.entries(style)) {
      if (typeof value !== "number") {
        // Non-number values ALWAYS pass through (flexDirection, alignItems, colors, objects, etc.)
        next[key] = value;
        continue;
      }
      if (TEXT_KEYS.has(key)) {
        next[key] = key === "letterSpacing" ? value * text : round(value * text, 0.5);
      } else if (SPACE_KEYS.has(key)) {
        next[key] = Math.round(value * space);
      } else {
        // All other numeric values pass through unchanged (NEVER_SCALE, DIMENSION_KEYS, unknown)
        next[key] = value;
        // Dev-mode: warn once about unrecognised numeric properties
        if (_warnedKeys && !NEVER_SCALE.has(key) && !DIMENSION_KEYS.has(key) && !_warnedKeys.has(key)) {
          _warnedKeys.add(key);
          console.warn(
            `[theme.fit] Numeric property "${key}" in style "${name}" is not in any known category. ` +
            `Add it to TEXT_KEYS, SPACE_KEYS, DIMENSION_KEYS, or NEVER_SCALE in theme.ts to suppress this warning.`,
          );
        }
      }
    }
    out[name] = next;
  }
  return out as T;
}
