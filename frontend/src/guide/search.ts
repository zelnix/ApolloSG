// Searching the ApolloSG User Guide. Pure functions over the guide content, so they run anywhere
// (the screen passes in the bundled guide; tests read the same JSON file).
//
// Every word typed must appear somewhere in a topic — its title, keywords, common questions,
// headings or body text — and words match as you type ("shar" finds "share").

export interface GuideDetail { heading: string; text: string }
export interface GuideLink { route: string; label: string }
export interface GuideTopic {
  id: string;
  title: string;
  answer: string;
  steps?: string[];
  details?: GuideDetail[];
  notes?: string[];
  links?: GuideLink[];
  questions?: string[];
  keywords?: string[];
}
export interface GuideSection { id: string; title: string; summary: string; topics: GuideTopic[] }
export interface UserGuide { reviewed: string; sections: GuideSection[] }

export interface GuideHit { section: GuideSection; topic: GuideTopic; snippet: string }

const STOP = new Set(
  "a an the to my me i im ive is are am be can could do does did how what where which who why when in on of for it this that with from into at by you your and or so please want need".split(" "),
);

const clean = (text: string) => text.toLowerCase().replace(/['’]/g, "");
const wordsOf = (text: string) => clean(text).match(/[a-z0-9]+/g) ?? [];

/** The words to look for: what was typed, minus filler words (unless that's all there is). */
export function searchTerms(query: string): string[] {
  const all = [...new Set(wordsOf(query))];
  const meaningful = all.filter((w) => !STOP.has(w));
  return meaningful.length ? meaningful : all;
}

/** The term plus its stem, so "share" also finds "sharing" and "links" finds "link". */
function variants(term: string): string[] {
  const out = [term];
  if (term.length > 3 && term.endsWith("s") && !term.endsWith("ss")) out.push(term.slice(0, -1));
  if (term.length > 5 && term.endsWith("ing")) out.push(term.slice(0, -3));
  else if (term.length > 4 && term.endsWith("ed")) out.push(term.slice(0, -2));
  else if (term.length > 3 && term.endsWith("e")) out.push(term.slice(0, -1));
  return out;
}

/** True when a word in the text starts with the term (or its singular). */
function hasTerm(words: string[], term: string): boolean {
  return variants(term).some((v) => words.some((w) => w.startsWith(v)));
}

interface Field { words: string[]; weight: number; prose?: string }

function fieldsOf(section: GuideSection, topic: GuideTopic): Field[] {
  const f = (text: string, weight: number, prose = false): Field => ({ words: wordsOf(text), weight, prose: prose ? text : undefined });
  return [
    f(topic.title, 6),
    f((topic.keywords ?? []).join(" "), 4),
    f((topic.questions ?? []).join(" "), 3),
    ...(topic.details ?? []).map((d) => f(d.heading, 3)),
    f(topic.answer, 2, true),
    ...(topic.steps ?? []).map((step) => f(step, 1, true)),
    ...(topic.details ?? []).map((d) => f(d.text, 1, true)),
    ...(topic.notes ?? []).map((note) => f(note, 1, true)),
    f(section.title, 1),
  ];
}

/** A short piece of readable text around the first match — the direct answer when only a title or keyword matched. */
function snippetOf(fields: Field[], terms: string[], fallback: string): string {
  const prose = fields.filter((field) => field.prose);
  const hit = prose.find((field) => terms.some((t) => hasTerm(field.words, t)));
  const text = hit?.prose ?? fallback;
  const line = text.split("\n").find((l) => terms.some((t) => hasTerm(wordsOf(l), t))) ?? text.split("\n")[0];
  const plain = line.replace(/^•\s*/, "");
  return plain.length > 160 ? `${plain.slice(0, 157).trimEnd()}…` : plain;
}

/** Topics that contain every search word, best match first. */
export function searchGuide(guide: UserGuide, query: string): GuideHit[] {
  const terms = searchTerms(query);
  if (!terms.length) return [];
  const phrase = terms.length > 1 ? clean(query).trim() : "";
  const hits: { hit: GuideHit; score: number; order: number }[] = [];
  let order = 0;
  for (const section of guide.sections) {
    for (const topic of section.topics) {
      order += 1;
      const fields = fieldsOf(section, topic);
      let score = 0;
      let all = true;
      for (const term of terms) {
        const best = Math.max(0, ...fields.filter((field) => hasTerm(field.words, term)).map((field) => field.weight));
        if (!best) { all = false; break; }
        score += best;
      }
      if (!all) continue;
      if (phrase && clean(topic.title).includes(phrase)) score += 10;
      else if (phrase && (topic.questions ?? []).some((q) => clean(q).includes(phrase))) score += 5;
      hits.push({ hit: { section, topic, snippet: snippetOf(fields, terms, topic.answer) }, score, order });
    }
  }
  return hits.sort((a, b) => b.score - a.score || a.order - b.order).map((item) => item.hit);
}

/** Splits text into plain and matching parts, for highlighting search words. */
export function highlightParts(text: string, terms: string[]): { text: string; match: boolean }[] {
  if (!terms.length) return [{ text, match: false }];
  const pattern = new RegExp(`\\b(${terms.flatMap(variants).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})[a-z0-9']*`, "gi");
  const parts: { text: string; match: boolean }[] = [];
  let last = 0;
  for (const m of text.matchAll(pattern)) {
    if (m.index! > last) parts.push({ text: text.slice(last, m.index), match: false });
    parts.push({ text: m[0], match: true });
    last = m.index! + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), match: false });
  return parts;
}
