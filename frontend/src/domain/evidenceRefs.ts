// Plain words for the evidence references "How ApolloSG checked" can carry: the label line Apollo sends with each item
// ("evidence 3f2a… · kind=text · Call details") or a bare evidence id. What people read names the item instead ("the
// call details"); Apollo's recorded wording keeps the references (Show the technical detail). Pure: no React, no native imports.

export interface EvidenceRef { id: string; label?: string | null; kind?: string | null }

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
/** "[evidence <id> · kind=text · Call details]", with or without the brackets and the label. */
const LABELLED = new RegExp(`\\[?\\bevidence\\s+(?:id\\s+)?(${UUID})\\s*·\\s*kind=([a-z_]+)(?:\\s*·\\s*([^·\\]\\n;()]+?))?(?:\\s*\\]|(?=\\s*(?:\\(|;|,\\s|\\.\\s|\\.?$)))`, "gi");
/** A bare id, with the words that introduce it ("evidence ID 3f2a…"). */
const BARE = new RegExp(`(?:\\bevidence\\s+(?:items?\\s+)?(?:ids?\\s+)?)?\\[?(${UUID})\\]?`, "gi");
const KIND_TAG = /\s*·?\s*\bkind=[a-z_]+/gi;

const KIND_NAME: Record<string, string> = {
  text: "the text you sent", url: "the link you sent", image: "the picture you sent", document: "the document you sent",
  audio: "the audio file you sent", attachment: "the attachment you sent", email: "the email you sent",
  observation: "Apollo's own notes", source_snapshot: "a saved copy of a source page",
};

const lowerFirst = (s: string) => (/^[A-Z][a-z]/.test(s) ? s[0].toLowerCase() + s.slice(1) : s);

function itemName(id: string, kind: string | null, label: string | null, known: Map<string, EvidenceRef>): string {
  const ref = known.get(id.toLowerCase());
  const named = (label ?? ref?.label ?? "").trim();
  const type = (kind ?? ref?.kind ?? "").toLowerCase();
  if (/^(TC Hawkeye|Apollo|Higgins)/i.test(named)) return "TC Hawkeye's notes";
  if (named) return /^(the|a|an|your|my|this|that)\b/i.test(named) ? lowerFirst(named) : `the ${lowerFirst(named)}`;
  return KIND_NAME[type] ?? "an item in this case";
}

/** A name starting a sentence starts with a capital. */
function fit(name: string, offset: number, whole: string): string {
  return offset === 0 || /[.!?:]\s*$/.test(whole.slice(0, offset)) ? name[0].toUpperCase() + name.slice(1) : name;
}

/** `text` with every evidence reference named in plain words. `evidence`: the case's items, to name a bare id. */
export function plainEvidenceRefs(text: string, evidence: readonly EvidenceRef[] = []): string {
  if (!/evidence|kind=|[0-9a-f]{8}-[0-9a-f]{4}-/i.test(text)) return text;
  const known = new Map(evidence.map((e) => [e.id.toLowerCase(), e]));
  return text
    .replace(LABELLED, (_m, id: string, kind: string, label: string | undefined, offset: number, whole: string) => fit(itemName(id, kind, label ?? null, known), offset, whole))
    .replace(BARE, (_m, id: string, offset: number, whole: string) => fit(itemName(id, null, null, known), offset, whole))
    .replace(KIND_TAG, "");
}
