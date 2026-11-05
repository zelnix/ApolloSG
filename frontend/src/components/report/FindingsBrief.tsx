// The Findings Brief: a prominent verdict heading with a shield icon, followed by Higgins'
// flowing prose. No section titles, no bullets, no pills — just one cohesive narrative.
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

export interface BriefStep { id: string; text: string; onPress?: () => void }

const ARTICLES = new Set(["a", "an", "the"]);
const words = (t: string) => t.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim().split(" ").filter((w) => w && !ARTICLES.has(w)).join(" ");

export interface BriefFinding { text: string; findingId?: string; category?: string | null }

/** Maximum key findings shown in the primary brief: technical detail stays on the DI tab. */
const MAX_BRIEF_FINDINGS = 5;

/** Semantic core: strip specific host/list/address names so "X on blocklist A" and "X on blocklist B" share a core. */
const semanticCore = (t: string): string =>
  t.toLowerCase()
    // strip URLs, domains, IPs, email addresses
    .replace(/https?:\/\/\S+/g, "")
    .replace(/\b[\w.-]+\.[a-z]{2,}\b/g, "")
    .replace(/\b\d{1,3}(?:\.\d{1,3}){3}\b/g, "")
    .replace(/\S+@\S+/g, "")
    // strip quoted strings
    .replace(/"[^"]*"/g, "")
    .replace(/[^a-z ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();

/** Collapse semantically similar findings. When several findings share the same semantic core,
 *  keep the first (most specific) and drop the rest. The findingId of the first representative is kept. */
function dedupFindings(raw: BriefFinding[]): BriefFinding[] {
  const seen = new Map<string, number>(); // core → index in `out`
  const out: BriefFinding[] = [];
  for (const f of raw) {
    const core = semanticCore(f.text);
    if (!core) continue;
    const existing = seen.get(core);
    if (existing !== undefined) {
      // Already have a finding with this semantic core — skip this duplicate.
      continue;
    }
    seen.set(core, out.length);
    out.push(f);
  }
  return out;
}

/** What the brief says, section by section, in Higgins' plain words: the verdict's short reason (never the verdict
 *  again), the key findings and what isn't certain. An answer to a general question is the answer itself.
 *  When the verdict label consumes the entire answer, the most useful context from "What it means" is used instead,
 *  so the brief never shows an empty summary beside the verdict. */
export function briefSections(report: Report, verdict: Pick<BriefVerdict, "label" | "caution">): { summary: string[]; findings: BriefFinding[]; uncertain: string[] } {
  const r = luddishReport(report);
  const first = r.answer[0] ?? "";
  const label = verdict.label ? words(verdict.label) : null;
  const reason = label ? sentences(first).filter((x) => words(x) !== label).slice(0, 2).join(" ") : "";
  // When the verdict label consumed the first answer sentence, use means or the next answer paragraph as context
  const contextReason = reason || (r.means.length ? r.means[0] : r.answer[1] ?? "");
  const summary = label
    ? [[contextReason, verdict.caution && !first.includes(verdict.caution) && !contextReason.includes(verdict.caution) ? verdict.caution : ""].filter(Boolean).join(" ")].filter(Boolean)
    : r.answer;
  // Semantic dedup: collapse findings with identical cores (e.g. multiple blocklist hits), then cap.
  const allFindings = r.found.map((f) => ({ text: scrubMessage(f.text), findingId: f.findingId, category: f.category })).filter((f) => f.text);
  const deduped = dedupFindings(allFindings).slice(0, MAX_BRIEF_FINDINGS);
  return {
    summary: summary.map(scrubMessage),
    findings: deduped,
    uncertain: r.uncertain.map(scrubMessage).filter(Boolean),
  };
}

// ── Shield icon by verdict tone ──
const SHIELD_ICON = {
  barking: ShieldAlert,
  ears_up: ShieldAlert,
  resting: ShieldCheck,
  sniffing: Shield,
} as const;

// ── Narrative Composition ──────────────────────────────────────────────────
//
// The narrative composer takes a Report (already in Luddish plain English) and a verdict,
// then builds a single cohesive explanation in four logical paragraphs:
//
//   P1  Context     — what was submitted and what it claims to do
//   P2  Evidence    — key findings, with a lead-in and natural transitions
//   P3  Assessment  — what the evidence means, with uncertainty woven in
//   P4  Guidance    — practical advice, prefixed naturally
//
// It does three things the old join-arrays approach didn't:
//   1. Filters state-assessment noise and field labels
//   2. Deduplicates across sections using significant-word overlap
//   3. Structures the argument with transitions and weaving

// Known state-rule phrases and field labels to filter.  These are generic assessment
// narration produced by the backend state machine or the Luddish state rules — they
// describe *how sure Higgins is* rather than *what was found*.  Real investigation
// content never matches these patterns.
const NOISE_STARTS: RegExp[] = [
  /^concerning\.?\s*$/i,
  /^suspicious\.?\s*$/i,
  /^safe\.?\s*$/i,
  /^what (?:it is|you sent|was found)\s*:/i,          // field-label openers
  /^(?:apollo'?s? (?:checks? )?)(?:found|noticed|confirmed) (?:a |something |this )/i,
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

function isNoise(s: string): boolean {
  const t = s.trim();
  if (!t || t.length < 5) return true;
  if (NOISE_STARTS.some((re) => re.test(t))) return true;
  // A sentence that is ENTIRELY a noise phrase (not just containing it as a clause in a
  // longer, useful sentence).  Sentences under 12 words are checked fully; longer ones only
  // if the noise phrase accounts for most of the text.
  const wordCount = t.split(/\s+/).length;
  for (const re of NOISE_CONTAINS) {
    if (!re.test(t)) continue;
    if (wordCount <= 12) return true;
    const m = t.match(re);
    if (m && m[0].split(/\s+/).length >= wordCount * 0.6) return true;
  }
  return false;
}

/** "What it is: the website X" → "The website X" — strip the field label, keep the content. */
function stripLabel(s: string): string {
  const m = s.match(/^what (?:it is|you sent|was found)\s*:\s*(.+)$/i);
  return m ? m[1].charAt(0).toUpperCase() + m[1].slice(1) : s;
}

// ── Semantic deduplication ──
const STOP = new Set("a an the this that these those it its is are was were be been being so to of on in at or and but not with for by as from your you there here what which who how would will can could has have had do does did if then than also just into about".split(" "));
function sigWords(text: string): Set<string> {
  return new Set(text.toLowerCase().replace(/[^a-z0-9'\s-]/g, " ").split(/\s+/).filter((w) => w.length > 2 && !STOP.has(w)));
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
  add(text: string): void { const sig = sigWords(text); if (sig.size > 1) this.entries.push({ sig }); }
  repeats(text: string): boolean {
    const sig = sigWords(text);
    if (sig.size < 2) return false;
    return this.entries.some((e) => wordOverlap(e.sig, sig) >= 0.65);
  }
}

// ── Paragraph composers ──

/** Tone-sensitive lead-in for the evidence paragraph. */
function evidenceLeadIn(tone: string, count: number): string {
  if (count < 2) return "";
  switch (tone) {
    case "barking": return "";                                              // confirmed: evidence speaks for itself
    case "ears_up": return "Several details raise concerns about its authenticity.";
    case "resting": return "Several details support this.";
    default: return "";
  }
}

/** Tone-sensitive synthesis line when there are multiple findings. */
function evidenceSynthesis(tone: string, count: number): string {
  if (count < 2) return "";
  switch (tone) {
    case "ears_up": return "Taken together, these discrepancies suggest deception.";
    case "barking": return "";
    default: return "";
  }
}

/** Weave means and uncertainty into one assessment paragraph.
 *  "Although [caveat], [significance]." when both are present. */
function weaveAssessment(means: string[], uncertain: string[]): string | null {
  if (!means.length && !uncertain.length) return null;
  if (uncertain.length && means.length) {
    const caveat = uncertain[0].replace(/\.\s*$/, "");
    const lc = caveat.charAt(0).toLowerCase() + caveat.slice(1);
    const body = means.join(" ").replace(/\.\s*$/, "");
    const lb = body.charAt(0).toLowerCase() + body.slice(1);
    const extra = uncertain.slice(1);
    const core = `Although ${lc}, ${lb}.`;
    return extra.length ? `${core} ${extra.join(" ")}` : core;
  }
  return (means.length ? means : uncertain).join(" ");
}

/** Org actions as a natural guidance paragraph.
 *  "For your safety, [action]. [cleaned conditionals]." */
function composeGuidance(actions: string[] | undefined, tone: string): string | null {
  if (!actions?.length) return null;
  const cleaned = actions.map((a) =>
    // "If you already X: Y" → "If you have already X, Y"
    a.replace(/^(If you (?:already |have )?[^:]{4,80}):\s+(.+)$/i, (_m, cond: string, rest: string) =>
      `${cond.replace(/\balready\b/, "have already")}, ${rest.charAt(0).toLowerCase()}${rest.slice(1)}`),
  );
  const isThreat = tone === "barking" || tone === "ears_up";
  if (isThreat) {
    cleaned[0] = "For your safety, " + cleaned[0].charAt(0).toLowerCase() + cleaned[0].slice(1);
  }
  return cleaned.join(" ");
}

/** Build flowing prose from the report — context, evidence, assessment, guidance.
 *  The heading (verdict label) is rendered separately in the shield row. */
function briefNarrative(report: Report, verdict: Pick<BriefVerdict, "label" | "caution" | "tone">): {
  heading: string | null;
  paragraphs: string[];
} {
  const r = luddishReport(report);
  const heading = verdict.label || null;
  const labelNorm = heading ? words(heading) : null;
  const said = new NarrativeSaid();
  const paragraphs: string[] = [];

  // ── P1: CONTEXT — what was submitted, cleaned of verdict repetition and noise ──
  const ctx: string[] = [];
  for (const para of r.answer) {
    for (const s of sentences(para)) {
      if (labelNorm && words(s) === labelNorm) continue;        // verdict → heading
      if (isNoise(s)) continue;
      const cleaned = scrubMessage(stripLabel(s));
      if (cleaned && !said.repeats(cleaned)) { ctx.push(cleaned); said.add(cleaned); }
    }
  }
  // Fold in additional named sections (titles stripped — prose only).
  for (const section of r.more) {
    for (const p of section.paragraphs) {
      const cleaned = scrubMessage(p);
      if (cleaned && !isNoise(cleaned) && !said.repeats(cleaned)) { ctx.push(cleaned); said.add(cleaned); }
    }
  }
  if (ctx.length) paragraphs.push(ctx.join(" "));

  // ── P2: EVIDENCE — findings with lead-in and deduplication against context ──
  const rawFindings = r.found
    .map((f) => ({ text: scrubMessage(f.text), findingId: f.findingId, category: f.category }))
    .filter((f) => f.text);
  const deduped = dedupFindings(rawFindings).slice(0, MAX_BRIEF_FINDINGS);
  const ev: string[] = [];
  for (const f of deduped) {
    if (!isNoise(f.text) && !said.repeats(f.text)) { ev.push(f.text); said.add(f.text); }
  }
  if (ev.length) {
    const lead = evidenceLeadIn(verdict.tone, ev.length);
    const body = ev.join(" ");
    const synth = evidenceSynthesis(verdict.tone, ev.length);
    paragraphs.push([lead, body, synth].filter(Boolean).join(" "));
  }

  // ── P3: ASSESSMENT — means + uncertainty woven naturally ──
  const ms: string[] = [];
  for (const m of r.means) {
    const cleaned = scrubMessage(m);
    if (cleaned && !isNoise(cleaned) && !said.repeats(cleaned)) { ms.push(cleaned); said.add(cleaned); }
  }
  const uc: string[] = [];
  for (const u of r.uncertain) {
    const cleaned = scrubMessage(u);
    if (cleaned && !isNoise(cleaned) && !said.repeats(cleaned)) { uc.push(cleaned); said.add(cleaned); }
  }
  if (verdict.caution) {
    const cc = scrubMessage(verdict.caution);
    if (cc && !isNoise(cc) && !said.repeats(cc)) ms.push(cc);
  }
  const assessment = weaveAssessment(ms, uc);
  if (assessment) paragraphs.push(assessment);

  // ── P4: GUIDANCE — composed separately (rendered in the component, not as prose here) ──
  // Guidance is composed by the component using composeGuidance() so it can also handle
  // tappable investigation steps.  We include it in the paragraph list only for copy-text.

  return { heading, paragraphs };
}

// ── Styles ──
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
  heading: { flex: 1, fontFamily: fonts.displayBold, fontSize: 22, lineHeight: 28, letterSpacing: -0.3 },
  prose: { fontFamily: fonts.text, fontSize: 15, lineHeight: 24, color: c.onSurfaceSecondary },
  actionText: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface },
  actionLink: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 44 },
  actionLinkText: { flex: 1, fontFamily: fonts.textMedium, fontSize: 15, lineHeight: 22, color: c.brandPrimary },
  divider: { height: 1, backgroundColor: c.divider },
  copyRow: { flexDirection: "row", alignItems: "center", justifyContent: "flex-end" },
  copyButton: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: spacing.sm, paddingVertical: 6, borderRadius: radius.pill, minHeight: 36 },
  copyText: { fontFamily: fonts.textSemibold, fontSize: 12, color: c.brandPrimary },
}));

export function FindingsBrief({ report, verdict, steps, ids, caseId }: {
  report: Report; verdict: BriefVerdict; steps: BriefStep[];
  /** testID prefix: "inv" on Ask Higgins, "tc-overview" on a threat. */
  ids: string;
  /** Case ID — kept in the interface for callers that provide it. */
  caseId?: string;
}) {
  const s = useStyles();
  const { colors } = useTheme();
  const { heading, paragraphs } = useMemo(() => briefNarrative(report, verdict), [report, verdict]);

  const tone = {
    barking: { ink: colors.barkingText },
    ears_up: { ink: colors.ears_upText },
    resting: { ink: colors.restingText },
    sniffing: { ink: colors.sniffingText },
  }[verdict.tone];

  const ShieldIcon = SHIELD_ICON[verdict.tone];

  // Org-specific actions, or investigation steps as a fallback.
  const orgActions = report.orgActions ?? [];
  const showSteps = !orgActions.length && steps.length > 0;
  const guidanceText = useMemo(() => composeGuidance(orgActions, verdict.tone), [orgActions, verdict.tone]);

  // Plain text for the clipboard.
  const copyText = useMemo(() => {
    const parts: string[] = [];
    if (heading) parts.push(heading);
    parts.push(...paragraphs);
    if (guidanceText) parts.push(guidanceText);
    if (showSteps) { parts.push(""); steps.forEach((st) => parts.push(`\u2022 ${st.text}`)); }
    return parts.join("\n\n");
  }, [heading, paragraphs, guidanceText, steps, showSteps]);

  const handleCopy = useCallback(async () => {
    try { await Clipboard.setStringAsync(copyText); } catch { /* ignore */ }
  }, [copyText]);

  return (
    <View style={s.card} testID={`${ids}-brief`}>
      {/* ── Verdict heading with shield ── */}
      {heading ? (
        <View style={s.headingRow} testID={`${ids}-verdict`}>
          <ShieldIcon size={28} color={tone.ink} />
          <Text style={[s.heading, { color: tone.ink }]} testID={`${ids}-verdict-label`}>
            {heading}
          </Text>
        </View>
      ) : null}

      {/* ── Flowing prose ── */}
      {paragraphs.map((para, i) => (
        <Text key={`p${i}`} style={s.prose} testID={i === 0 ? `${ids}-answer` : `${ids}-prose-${i}`}>
          {para}
        </Text>
      ))}

      {/* ── Guidance (org-specific, composed as natural prose) ── */}
      {guidanceText ? (
        <Text style={s.prose} testID={`${ids}-guidance`}>
          {guidanceText}
        </Text>
      ) : null}

      {/* ── Investigation steps (tappable) ── */}
      {showSteps ? steps.map((step) => {
        const text = luddishText(scrubMessage(step.text), true);
        return step.onPress ? (
          <Pressable key={step.id} style={({ pressed }) => [s.actionLink, { opacity: pressed ? 0.7 : 1 }]} onPress={step.onPress}
            accessibilityRole="button" testID={`${ids}-action-${step.id}`}>
            <Text style={s.actionLinkText}>{text}</Text>
            <ChevronRight size={18} color={colors.muted} />
          </Pressable>
        ) : (
          <Text key={step.id} style={s.actionText} testID={`${ids}-action-${step.id}`}>{text}</Text>
        );
      }) : null}

      {/* ── Copy ── */}
      <View style={s.divider} />
      <View style={s.copyRow}>
        <Pressable style={({ pressed }) => [s.copyButton, { opacity: pressed ? 0.6 : 1 }]} onPress={handleCopy}
          accessibilityRole="button" accessibilityLabel="Copy report" testID={`${ids}-copy`}>
          <Copy size={14} color={colors.brandPrimary} />
          <Text style={s.copyText}>Copy report</Text>
        </Pressable>
      </View>
    </View>
  );
}
