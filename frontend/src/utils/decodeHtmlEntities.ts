/**
 * Shared HTML entity decoder — single source of truth.
 *
 * Decodes HTML entities in one pass: "&amp;quot;" becomes "&quot;", never '"'.
 * Unknown or invalid entities are left exactly as written.
 *
 * Consolidates the three duplicate implementations that existed in
 * emailCleaner.ts, notificationText.ts and inertEmail.ts.
 */

const NAMED: Record<string, string> = {
  // Core XML entities
  amp: "&", lt: "<", gt: ">", quot: "\"", apos: "'",
  // Whitespace & punctuation
  nbsp: "\u00a0", ensp: "\u2002", emsp: "\u2003", thinsp: "\u2009",
  ndash: "\u2013", mdash: "\u2014", hellip: "\u2026",
  // Quotation marks
  lsquo: "\u2018", rsquo: "\u2019", ldquo: "\u201c", rdquo: "\u201d",
  laquo: "\u00ab", raquo: "\u00bb",
  // Typographic marks
  bull: "\u2022", middot: "\u00b7", times: "\u00d7",
  copy: "\u00a9", reg: "\u00ae", trade: "\u2122",
  // Currency
  euro: "\u20ac", pound: "\u00a3", cent: "\u00a2",
  // Misc
  deg: "\u00b0", shy: "\u00ad",
  zwnj: "\u200c", zwj: "\u200d",
};

const ENTITY = /&(#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[a-zA-Z][a-zA-Z0-9]{1,15});/g;

function fromCodePoint(code: number): string | null {
  const valid = code > 0 && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff);
  return valid ? String.fromCodePoint(code) : null;
}

/** Decode HTML entities in one pass. Unknown or invalid entities are left as-is. */
export function decodeHtmlEntities(text: string): string {
  return text.replace(ENTITY, (whole, body: string) => {
    if (body.startsWith("#")) {
      const hex = body[1] === "x" || body[1] === "X";
      return fromCodePoint(parseInt(body.slice(hex ? 2 : 1), hex ? 16 : 10)) ?? whole;
    }
    return NAMED[body.toLowerCase()] ?? whole;
  });
}
