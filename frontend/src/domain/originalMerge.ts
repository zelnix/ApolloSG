// A saved original is never replaced: a later supply (the original email's headers, or the copy ApolloSG's server kept
// for this phone) only fills in what the saved copy is missing — a header it doesn't have, its text or its link when it
// has none. What it already holds stays exactly as it was: its text, link, device record, headers, when it was captured
// and where it came from. Pure: no React, no storage, unit-tested in node.
import type { OriginalSource } from "../store/originalSource";

type Field = { label: string; value: string };
const has = (v: string | null | undefined) => !!v?.trim();
const key = (label: string) => label.trim().toLowerCase();

/** `existing` enriched by `incoming`. An email's headers arriving for a copy saved as plain text make it an email. */
export function enrichOriginal(existing: OriginalSource, incoming: OriginalSource): OriginalSource {
  const fields: Field[] = (existing.fields ?? []).map((f) => ({ ...f }));
  for (const f of incoming.fields ?? []) {
    if (!has(f.value)) continue;
    const same = fields.filter((x) => key(x.label) === key(f.label));
    if (same.some((x) => has(x.value) && (x.value === f.value || !/^attachment/i.test(f.label)))) continue;
    const empty = same.find((x) => !has(x.value));
    if (empty) empty.value = f.value; else fields.push({ label: f.label, value: f.value });
  }
  return {
    ...existing,
    kind: existing.kind === "text" && incoming.kind === "email" ? "email" : existing.kind,
    ...(fields.length ? { fields } : {}),
    text: has(existing.text) ? existing.text : incoming.text ?? existing.text ?? null,
    url: has(existing.url) ? existing.url : incoming.url ?? existing.url ?? null,
    ...(existing.data !== undefined || incoming.data !== undefined ? { data: existing.data ?? incoming.data } : {}),
  };
}

/** Whether two saved originals hold exactly the same thing (so an enrichment that adds nothing writes nothing). */
export function sameOriginal(a: OriginalSource, b: OriginalSource): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
