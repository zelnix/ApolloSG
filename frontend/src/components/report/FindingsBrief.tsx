// The Findings Brief: a prominent verdict heading with a shield icon, followed by Higgins'
// structured three-block report:
//
//   1. Opening paragraph — decisive conclusion (what it is and why)
//   2. Evidence section  — section header + bullet points (one key fact each)
//   3. Action section    — section header + guidance prose or tappable steps
//
// No fragmented sentences, no system-noise phrases, no bullets-as-prose.
// Visual format follows the product exemplar exactly.
import ChevronRight from "lucide-react-native/icons/chevron-right";
import Copy from "lucide-react-native/icons/copy";
import Shield from "lucide-react-native/icons/shield";
import ShieldAlert from "lucide-react-native/icons/shield-alert";
import ShieldCheck from "lucide-react-native/icons/shield-check";
import React, { useCallback, useMemo } from "react";
import { Pressable, Text, View } from "react-native";
import * as Clipboard from "expo-clipboard";

import type { BriefVerdict } from "@/src/domain/briefVerdict";
import { luddishReport, luddishText } from "@/src/domain/luddish";
import { sentences } from "@/src/domain/luddish/patterns";
import { scrubMessage } from "@/src/domain/messageVoice";
import type { Report } from "@/src/domain/reportSections";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

// ── Public interface ──────────────────────────────────────────────────────────
export interface BriefStep { id: string; text: string; onPress?: () => void }

export interface BriefFinding { text: string; findingId?: string; category?: string | null }

/** Maximum key findings shown in the primary brief: technical detail stays on the DI tab. */
const MAX_BRIEF_FINDINGS = 5;

// ── Narrative part types ──────────────────────────────────────────────────────
/** A single bullet: an optional bold label, the body text, and (for an action) its sub-points. */
interface NarrativeBullet { label: string | null; body: string; sub?: string[] }

/** One block in the narrative: prose paragraph, a stand-alone instruction, section header, or a list of bullets. */
type NarrativePart =
  | { kind: 'para'; text: string }
  | { kind: 'callout'; text: string }
  | { kind: 'header'; text: string }
  | { kind: 'bullets'; items: NarrativeBullet[] }

/** "Don't click or open that link." — an instruction, shown on its own line after the conclusion (owner's
 *  example, 2026-11-08), never buried mid-paragraph. */
const IMPERATIVE = /^(?:don't|do not|never)\b/i;

/** "Status: Origin: Australia (domestic landline)" — a labelled field from a structured section, not a sentence.
 *  It belongs to the DI tab's full report, never to the opening paragraph. */
const FIELD_LINE = /^(?:[A-Z][\w'/-]*\s?){1,4}:\s/;

/** Ordinary first words that read on from a label in lowercase ("Fake Domain: the address…"). */
const ORDINARY_STARTS = new Set(["the", "this", "that", "these", "those", "a", "an", "it", "its", "there", "no", "none", "nothing",
  "your", "you", "one", "some", "several", "both", "each", "all", "every", "what", "when", "where", "who", "how", "someone", "something"]);
function afterLabel(text: string): string {
  const first = text.match(/^[A-Za-z']+/)?.[0] ?? "";
  return ORDINARY_STARTS.has(first.toLowerCase()) ? first.toLowerCase() + text.slice(first.length) : text;
}

// ── Tone-driven section header text ──────────────────────────────────────────
/** "Here is why…" section header based on the verdict's tone. */
const EVIDENCE_HEADER: Record<string, string> = {
  barking:  'Here is why this is a scam',
  ears_up:  'Here is why this raises immediate red flags',
  resting:  'Here is why this appears genuine',
  sniffing: 'What was found',
};

/** "What to do…" section header based on the verdict's tone. */
const ACTION_HEADER: Record<string, string> = {
  barking:  'What to do next',
  ears_up:  'What to do next',
  resting:  'What this means for you',
  sniffing: 'What to do in the meantime',
};

// ── Utility: articles to strip when comparing headings ───────────────────────
const ARTICLES = new Set(["a", "an", "the"]);
const words = (t: string) =>
  t.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim().split(" ")
   .filter((w) => w && !ARTICLES.has(w)).join(" ");

// ── Semantic dedup for findings ───────────────────────────────────────────────
/** Strip URLs / IPs / emails / quoted strings → stable semantic core for dedup. */
const semanticCore = (t: string): string =>
  t.toLowerCase()
    .replace(/https?:\/\/\S+/g, "")
    .replace(/\b[\w.-]+\.[a-z]{2,}\b/g, "")
    .replace(/\b\d{1,3}(?:\.\d{1,3}){3}\b/g, "")
    .replace(/\S+@\S+/g, "")
    .replace(/"[^"]*"/g, "")
    .replace(/[^a-z ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();

/** Collapse semantically near-identical findings: keep the first, drop the rest. */
function dedupFindings(raw: BriefFinding[]): BriefFinding[] {
  const seen = new Map<string, number>();
  const out: BriefFinding[] = [];
  for (const f of raw) {
    const core = semanticCore(f.text);
    if (!core || seen.has(core)) continue;
    seen.set(core, out.length);
    out.push(f);
  }
  return out;
}

// ── Noise filters ─────────────────────────────────────────────────────────────
// State-rule phrases and field labels produced by the backend state machine.
// These describe how confident Higgins is, not what was actually found.
const NOISE_STARTS: RegExp[] = [
  /^concerning\.?\s*$/i,
  /^suspicious\.?\s*$/i,
  /^safe\.?\s*$/i,
  /^what (?:it is|you sent|was found)\s*:/i,
  /^(?:apollo'?s?['\s]?)(?:check|checks|scan|scans)?\s*(?:found|noticed|confirmed|established|identified|detected) (?:a |something |this |the |that |no )/i,
  /^the evidence points to a scam\.?\s*$/i,
  /^no threat was found/i,
  /^the checks that completed found no threat/i,
  /^apollo (?:couldn'?t|could not|can'?t|cannot) (?:determine|complete|say|give|run|be certain)/i,
  /^apollo (?:is (?:looking|still)|hasn'?t finished)/i,
  /^this (?:check |wasn'?t )/i,
  /^you'?ve marked this/i,
  /^it was (?:stopped|blocked)/i,
  /^that(?:'s| is) reason to be careful/i,
  /^something here could be/i,
  /^a concern (?:isn'?t|is not) proof/i,
  /^scams like this aim/i,
];
const NOISE_CONTAINS: RegExp[] = [
  /raises?\s+a\s+concern/i,
  /not enough to call it/i,
  /warning sign[s,]?\s*(?:not|isn'?t)\s+proof/i,
  /concern isn'?t proof/i,
  /strong warning,?\s*not proof/i,
  /isn'?t a guarantee/i,
  /very likely a scam,?\s*(?:though|but)/i,
  /treat (?:it|this) as a scam/i,
  /nothing (?:in the checks|apollo completed) points/i,
  // These conflict with a scam/likely-scam verdict banner — "nothing proves it's a scam" under
  // a "This is likely a scam" heading creates direct contradiction (Higgins guideline 3).
  // NOTE: short matches like /nothing here proves/ belong in NOISE_HARD (not here) so the
  // percentage-of-sentence threshold does not block them from filtering long sentences.
  /doesn'?t prove it(?:'s| is) a scam/i,
  /that(?:'s| is) not proof/i,
  /not proof that/i,
  /isn'?t proven to be/i,
  /(?:some|all) checks couldn'?t run/i,
  /there isn'?t enough evidence to say/i,
  /couldn'?t? (?:give|provide) a full answer/i,
  /you don'?t need to do anything/i,
  /(?:needs?|before) your? attention (?:before|—)/i,
  /acting on it (?:before|could)/i,
  /what (?:wasn'?t|couldn'?t be) (?:checked|established) could still matter/i,
  /could be a warning sign/i,
  /something (?:here |apollo )(?:could|checked|found)/i,
  /worth knowing about/i,
  /worth checking before/i,
  /none of the checks/i,
  /check it another way/i,
  /apollo didn'?t run this check/i,
  /tells you nothing either way/i,
];

/**
 * Hard-stop phrases: a sentence containing any of these is ALWAYS noise,
 * regardless of sentence length.  Used for phrases that conflict with the
 * verdict banner (Higgins guideline 3) or reference internal system state.
 */
const NOISE_HARD: RegExp[] = [
  /nothing here proves/i,                        // "Nothing here proves it's a scam…"
  /doesn'?t prove it(?:'s| is) a scam/i,
  /that(?:'s| is) (?:no|not) proof/i,
  /not proof that/i,
  /isn'?t proven to be a scam/i,
  /(?:apollo'?s?|the) check(?:s)? established the/i,  // "Apollo's checks established the warning…"
];

function isNoise(s: string): boolean {
  const t = s.trim();
  if (!t || t.length < 5) return true;
  if (NOISE_STARTS.some((re) => re.test(t))) return true;
  // Hard-stop phrases: always noise regardless of sentence length.
  // These either contradict the verdict (conflicting logic rule) or describe
  // internal system state rather than what was found.
  if (NOISE_HARD.some((re) => re.test(t))) return true;
  const wordCount = t.split(/\s+/).length;
  for (const re of NOISE_CONTAINS) {
    if (!re.test(t)) continue;
    if (wordCount <= 12) return true;
    const m = t.match(re);
    if (m && m[0].split(/\s+/).length >= wordCount * 0.6) return true;
  }
  return false;
}

/** "What it is: the website X" → "The website X" */
function stripLabel(s: string): string {
  const m = s.match(/^what (?:it is|you sent|was found)\s*:\s*(.+)$/i);
  return m ? m[1].charAt(0).toUpperCase() + m[1].slice(1) : s;
}

// ── Cross-paragraph dedup tracker ─────────────────────────────────────────────
const STOP = new Set(
  "a an the this that these those it its is are was were be been being so to of on in at or and but not with for by as from your you there here what which who how would will can could has have had do does did if then than also just into about"
  .split(" ")
);

function sigWords(text: string): Set<string> {
  return new Set(
    text.toLowerCase().replace(/[^a-z0-9'\s-]/g, " ").split(/\s+/)
        .filter((w) => w.length > 2 && !STOP.has(w))
  );
}

function wordOverlap(a: Set<string>, b: Set<string>): number {
  if (!a.size || !b.size) return 0;
  let hits = 0;
  for (const w of a) if (b.has(w)) hits++;
  return hits / Math.min(a.size, b.size);
}

/** Tracks what the narrative has already said so the same point isn't stated twice. */
class NarrativeSaid {
  private entries: { sig: Set<string> }[] = [];
  add(text: string): void {
    const sig = sigWords(text);
    if (sig.size > 1) this.entries.push({ sig });
  }
  repeats(text: string): boolean {
    const sig = sigWords(text);
    if (sig.size < 2) return false;
    return this.entries.some((e) => wordOverlap(e.sig, sig) >= 0.65);
  }
}

// ── What to do next ───────────────────────────────────────────────────────────
/** What the case is about, from the words of the report itself — the action labels follow it. */
function caseKind(report: Report): "link" | "call" | "message" {
  const text = [...report.answer, ...report.found.map((f) => f.text)].join(" ").toLowerCase();
  if (/\b(?:caller|phone call|called you|call back|this call|the call)\b/.test(text)) return "call";
  if (/\b(?:link|web address|website|url|domain)\b/.test(text)) return "link";
  return "message";
}

const NOT_ACTED: Record<ReturnType<typeof caseKind>, { label: string; body: string }> = {
  link: { label: "If you haven't clicked it", body: "Delete the message or email immediately, and don't open the link." },
  message: { label: "If you haven't replied", body: "Delete the message immediately — don't reply or open anything in it." },
  call: { label: "If you haven't acted on it", body: "Hang up. Don't call back on the number that called you." },
};
const ACTED_LABEL: Record<ReturnType<typeof caseKind>, string> = {
  link: "If you clicked it or entered details",
  message: "If you replied or entered details",
  call: "If you gave any details or codes",
};

/** Organisation-specific steps as labelled bullets (owner's example, 2026-11-08): what to do if you haven't acted,
 *  what to do if you have (the organisation's own contact, one sub-point per sentence when there are several),
 *  and where to report it. Only on a scam or likely-scam verdict: a genuine message needs none of this. */
function actionBullets(report: Report, tone: string): NarrativeBullet[] {
  const org = report.detectedOrg;
  if (!org || (tone !== "barking" && tone !== "ears_up")) return [];
  const kind = caseKind(report);
  const compromised = sentences(org.ifCompromised).map((s) => s.trim()).filter(Boolean);
  return [
    { label: NOT_ACTED[kind].label, body: NOT_ACTED[kind].body },
    compromised.length > 1
      ? { label: ACTED_LABEL[kind], body: "", sub: compromised }
      : { label: ACTED_LABEL[kind], body: org.ifCompromised },
    { label: "Report it", body: org.reportScam },
  ];
}

// ── Shield icon by verdict tone ───────────────────────────────────────────────
const SHIELD_ICON = {
  barking:  ShieldAlert,
  ears_up:  ShieldAlert,
  resting:  ShieldCheck,
  sniffing: Shield,
} as const;

// ── briefSections (kept for compatibility) ────────────────────────────────────
export function briefSections(
  report: Report,
  verdict: Pick<BriefVerdict, "label" | "caution">,
): { summary: string[]; findings: BriefFinding[]; uncertain: string[] } {
  const r = luddishReport(report);
  const first = r.answer[0] ?? "";
  const label = verdict.label ? words(verdict.label) : null;
  const reason = label
    ? sentences(first).filter((x) => words(x) !== label).slice(0, 2).join(" ")
    : "";
  const contextReason =
    reason || (r.means.length ? r.means[0] : r.answer[1] ?? "");
  const summary = label
    ? [[contextReason,
        verdict.caution &&
        !first.includes(verdict.caution) &&
        !contextReason.includes(verdict.caution)
          ? verdict.caution : "",
       ].filter(Boolean).join(" ")].filter(Boolean)
    : r.answer;
  const allFindings = r.found
    .map((f) => ({ text: scrubMessage(f.text), findingId: f.findingId, category: f.category }))
    .filter((f) => f.text);
  return {
    summary: summary.map(scrubMessage),
    findings: dedupFindings(allFindings).slice(0, MAX_BRIEF_FINDINGS),
    uncertain: r.uncertain.map(scrubMessage).filter(Boolean),
  };
}

// ── Main narrative builder ────────────────────────────────────────────────────
/**
 * Build the three-block Higgins narrative from investigation data.
 *
 *   Block 1  Opening paragraph   — decisive conclusion (1–2 clean sentences)
 *   Block 2  Evidence section    — header + bullet per finding (with category label)
 *
 * The action section (Block 3) is rendered by the component from `orgActions` /
 * investigation steps so it can include tappable rows.
 */
function briefNarrative(
  report: Report,
  verdict: Pick<BriefVerdict, "label" | "caution" | "tone">,
): { heading: string | null; parts: NarrativePart[] } {
  const r = luddishReport(report);
  const heading = verdict.label || null;
  const labelNorm = heading ? words(heading) : null;
  const said = new NarrativeSaid();
  const parts: NarrativePart[] = [];

  // ── BLOCK 1: Opening paragraph ────────────────────────────────────────────
  // Up to 2 non-noise sentences from r.answer (skipping the bare verdict label).
  // If fewer than 2, supplement with one clean sentence from r.means.
  const openSentences: string[] = [];

  for (const para of r.answer) {
    for (const s of sentences(para)) {
      if (labelNorm && words(s) === labelNorm) continue; // pure verdict → heading
      if (isNoise(s)) continue;
      const cleaned = scrubMessage(stripLabel(s));
      // Reject trivially short sentences (fewer than 5 words add nothing)
      if (cleaned && !said.repeats(cleaned) && cleaned.split(/\s+/).length >= 5) {
        openSentences.push(cleaned);
        said.add(cleaned);
        if (openSentences.length >= 2) break;
      }
    }
    if (openSentences.length >= 2) break;
  }

  // Supplement from means if still thin (prose only — a labelled field or instruction line isn't a sentence, and a
  // sentence that restates a finding is left to the findings list, where it belongs)
  if (openSentences.length < 2) {
    const findingsSaid = new NarrativeSaid();
    for (const f of r.found) findingsSaid.add(f.text);
    for (const m of r.means) {
      if (FIELD_LINE.test(m.trim())) continue;
      for (const s of sentences(m)) {
        if (isNoise(s) || FIELD_LINE.test(s) || findingsSaid.repeats(s)) continue;
        const cleaned = scrubMessage(s);
        if (cleaned && !said.repeats(cleaned) && cleaned.split(/\s+/).length >= 5) {
          openSentences.push(cleaned);
          said.add(cleaned);
          break;
        }
      }
      if (openSentences.length >= 2) break;
    }
  }

  // For unable-to-determine (sniffing), one uncertainty note improves context
  if (verdict.tone === "sniffing" && openSentences.length < 2) {
    for (const u of r.uncertain) {
      const cleaned = scrubMessage(u);
      if (cleaned && !isNoise(cleaned) && !said.repeats(cleaned)) {
        openSentences.push(cleaned);
        said.add(cleaned);
        break;
      }
    }
  }

  if (openSentences.length) {
    // The conclusion first, then the instruction ("Don't click or open that link.") on its own line.
    const statements = openSentences.filter((s) => !IMPERATIVE.test(s));
    const instructions = openSentences.filter((s) => IMPERATIVE.test(s));
    if (statements.length) parts.push({ kind: "para", text: statements.join(" ") });
    if (instructions.length) parts.push({ kind: "callout", text: instructions.join(" ") });
  }

  // ── BLOCK 2: Evidence section — header + bullets ──────────────────────────
  const rawFindings = r.found
    .map((f) => ({ text: scrubMessage(f.text), findingId: f.findingId, category: f.category }))
    .filter((f) => f.text);
  const deduped = dedupFindings(rawFindings).slice(0, MAX_BRIEF_FINDINGS);

  const bulletItems: NarrativeBullet[] = [];
  for (const f of deduped) {
    if (!isNoise(f.text) && !said.repeats(f.text)) {
      // After a label the body starts lowercase so "Label: the address…" reads naturally — only when the first word
      // is an ordinary one; a name ("Google Safe Browsing lists…") keeps its capital, as does a bare bullet.
      bulletItems.push({ label: f.category ?? null, body: f.category ? afterLabel(f.text) : f.text });
      said.add(f.text);
    }
  }

  if (bulletItems.length) {
    parts.push({ kind: "header", text: EVIDENCE_HEADER[verdict.tone] ?? "What was found" });
    parts.push({ kind: "bullets", items: bulletItems });
  }

  return { heading, parts };
}

// ── Helpers for copy text serialisation ──────────────────────────────────────
function bulletString(item: NarrativeBullet): string[] {
  const head = item.label ? (item.body ? `• ${item.label}: ${item.body}` : `• ${item.label}:`) : `• ${item.body}`;
  return [head, ...(item.sub ?? []).map((s) => `    ◦ ${s}`)];
}

// ── Styles ────────────────────────────────────────────────────────────────────
const useStyles = makeStyles((c) => ({
  card: {
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 0.25,
    borderColor: c.border,
    backgroundColor: c.surfaceSecondary,
    gap: spacing.lg,
  },
  headingRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  heading: {
    flex: 1,
    fontFamily: fonts.displayBold,
    fontSize: 22,
    lineHeight: 28,
    letterSpacing: -0.3,
  },
  // Body paragraphs — 16 pt minimum per design guidelines ("plain-language accessibility")
  prose: {
    fontFamily: fonts.text,
    fontSize: 16,
    lineHeight: 26,
    color: c.onSurfaceSecondary,
  },
  // Section header "Here is why…" — semibold at body size creates clear weight hierarchy
  // over prose without competing with the verdict heading.
  narrativeHeader: {
    fontFamily: fonts.textSemibold,
    fontSize: 16,
    lineHeight: 24,
    color: c.onSurface,
    letterSpacing: 0.1,
  },
  // Bullet list container — 8 pt grid spacing between items
  bulletList: { gap: spacing.md },
  bulletRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  bulletMark: {
    fontFamily: fonts.text,
    fontSize: 16,
    lineHeight: 26,
    color: c.onSurfaceSecondary,
    minWidth: 12,
  },
  bulletText: {
    flex: 1,
    fontFamily: fonts.text,
    fontSize: 16,
    lineHeight: 26,
    color: c.onSurfaceSecondary,
  },
  // Bold label portion inside a bullet: "Fake Domain: "
  bulletLabel: {
    fontFamily: fonts.textSemibold,
    fontSize: 16,
    lineHeight: 26,
    color: c.onSurface,
  },
  // A stand-alone instruction under the conclusion: "Don't click or open that link."
  callout: {
    fontFamily: fonts.textSemibold,
    fontSize: 16,
    lineHeight: 26,
    color: c.onSurface,
  },
  // Sub-points of an action bullet, indented under their label
  subList: { gap: spacing.xs, marginTop: spacing.xs },
  subRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm, paddingLeft: spacing.md },
  actionText: { fontFamily: fonts.text, fontSize: 16, lineHeight: 26, color: c.onSurface },
  actionLink: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 44 },
  actionLinkText: {
    flex: 1,
    fontFamily: fonts.textMedium,
    fontSize: 16,
    lineHeight: 26,
    color: c.brandPrimary,
  },
  divider: { height: 1, backgroundColor: c.divider },
  copyRow: { flexDirection: "row", alignItems: "center", justifyContent: "flex-end" },
  copyButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: radius.pill,
    minHeight: 36,
  },
  copyText: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.brandPrimary },
}));

// ── Component ─────────────────────────────────────────────────────────────────
export function FindingsBrief({
  report,
  verdict,
  steps,
  ids,
  caseId,
}: {
  report: Report;
  verdict: BriefVerdict;
  steps: BriefStep[];
  /** testID prefix: "inv" on Ask Higgins, "tc-overview" on a threat. */
  ids: string;
  /** Case ID — kept in the interface for callers that provide it. */
  caseId?: string;
}) {
  const s = useStyles();
  const { colors } = useTheme();
  const { heading, parts } = useMemo(() => briefNarrative(report, verdict), [report, verdict]);

  const tone = {
    barking:  { ink: colors.barkingText },
    ears_up:  { ink: colors.ears_upText },
    resting:  { ink: colors.restingText },
    sniffing: { ink: colors.sniffingText },
  }[verdict.tone];

  const ShieldIcon = SHIELD_ICON[verdict.tone];

  // Organisation-specific action bullets on a scam / likely-scam verdict; else the investigation's own steps.
  const actions = useMemo(() => actionBullets(report, verdict.tone), [report, verdict.tone]);
  const showSteps = !actions.length && steps.length > 0;

  // Action section header (only shown when there is content below it)
  const hasAction = actions.length > 0 || showSteps;
  const actionHeaderText = ACTION_HEADER[verdict.tone] ?? "What to do next";

  // Plain text for the clipboard
  const copyText = useMemo(() => {
    const lines: string[] = [];
    if (heading) lines.push(heading);
    // Serialise narrative parts
    let prevKind: string | null = null;
    for (const part of parts) {
      // Extra blank line before headers and before the first bullet (but not between bullets)
      if (part.kind === "header") {
        lines.push(`${part.text}:`);
      } else if (part.kind === "para" || part.kind === "callout") {
        if (prevKind !== null) lines.push(""); // blank separator
        lines.push(part.text);
      } else if (part.kind === "bullets") {
        for (const item of part.items) lines.push(...bulletString(item));
      }
      prevKind = part.kind;
    }
    // Action section
    if (hasAction) {
      lines.push("");
      lines.push(`${actionHeaderText}:`);
      for (const item of actions) lines.push(...bulletString(item));
      if (showSteps) steps.forEach((st) => lines.push(`• ${st.text}`));
    }
    return lines.join("\n");
  }, [heading, parts, hasAction, actionHeaderText, actions, steps, showSteps]);

  const handleCopy = useCallback(async () => {
    try { await Clipboard.setStringAsync(copyText); } catch { /* ignore */ }
  }, [copyText]);

  const bulletList = (items: NarrativeBullet[], testID: string, itemId: (j: number) => string) => (
    <View style={s.bulletList} testID={testID}>
      {items.map((item, j) => (
        <View key={j}>
          <View style={s.bulletRow}>
            <Text style={s.bulletMark}>•</Text>
            <Text style={s.bulletText} testID={itemId(j)}>
              {item.label ? (
                <>
                  <Text style={s.bulletLabel}>{item.label}{item.body ? ": " : ":"}</Text>
                  {item.body}
                </>
              ) : item.body}
            </Text>
          </View>
          {item.sub?.length ? (
            <View style={s.subList}>
              {item.sub.map((line, k) => (
                <View key={k} style={s.subRow}>
                  <Text style={s.bulletMark}>◦</Text>
                  <Text style={s.bulletText} testID={`${itemId(j)}-sub-${k}`}>{line}</Text>
                </View>
              ))}
            </View>
          ) : null}
        </View>
      ))}
    </View>
  );

  return (
    <View style={s.card} testID={`${ids}-brief`}>

      {/* ── Verdict heading with shield ── */}
      {heading ? (
        <View style={s.headingRow} testID={`${ids}-verdict`}>
          <ShieldIcon size={28} color={tone.ink} />
          <Text
            style={[s.heading, { color: tone.ink }]}
            testID={`${ids}-verdict-label`}
          >
            {heading}
          </Text>
        </View>
      ) : null}

      {/* ── Narrative parts: prose paragraphs, the instruction, section headers, bullet lists ── */}
      {parts.map((part, i) => {
        if (part.kind === "para") {
          return (
            <Text
              key={`p${i}`}
              style={s.prose}
              testID={i === 0 ? `${ids}-answer` : `${ids}-prose-${i}`}
            >
              {part.text}
            </Text>
          );
        }

        if (part.kind === "callout") {
          return (
            <Text key={`c${i}`} style={s.callout} testID={i === 0 ? `${ids}-answer` : `${ids}-instruction`}>
              {part.text}
            </Text>
          );
        }

        if (part.kind === "header") {
          return (
            <Text key={`h${i}`} style={s.narrativeHeader} testID={`${ids}-section-${i}`}>
              {part.text}
            </Text>
          );
        }

        if (part.kind === "bullets") {
          return <React.Fragment key={`bl${i}`}>{bulletList(part.items, `${ids}-bullets-${i}`, (j) => `${ids}-bullet-${j}`)}</React.Fragment>;
        }

        return null;
      })}

      {/* ── Action section: header + organisation-specific bullets, or the investigation's steps ── */}
      {hasAction ? (
        <Text style={s.narrativeHeader} testID={`${ids}-action-header`}>
          {actionHeaderText}
        </Text>
      ) : null}

      {actions.length ? bulletList(actions, `${ids}-guidance`, (j) => `${ids}-guidance-${j}`) : null}

      {/* ── Investigation steps (tappable) ── */}
      {showSteps ? steps.map((step) => {
        const text = luddishText(scrubMessage(step.text), true);
        return step.onPress ? (
          <Pressable
            key={step.id}
            style={({ pressed }) => [s.actionLink, { opacity: pressed ? 0.7 : 1 }]}
            onPress={step.onPress}
            accessibilityRole="button"
            testID={`${ids}-action-${step.id}`}
          >
            <Text style={s.actionLinkText}>{text}</Text>
            <ChevronRight size={18} color={colors.muted} />
          </Pressable>
        ) : (
          <Text
            key={step.id}
            style={s.actionText}
            testID={`${ids}-action-${step.id}`}
          >
            {text}
          </Text>
        );
      }) : null}

      {/* ── Copy ── */}
      <View style={s.divider} />
      <View style={s.copyRow}>
        <Pressable
          style={({ pressed }) => [s.copyButton, { opacity: pressed ? 0.6 : 1 }]}
          onPress={handleCopy}
          accessibilityRole="button"
          accessibilityLabel="Copy report"
          testID={`${ids}-copy`}
        >
          <Copy size={14} color={colors.brandPrimary} />
          <Text style={s.copyText}>Copy report</Text>
        </Pressable>
      </View>

    </View>
  );
}
