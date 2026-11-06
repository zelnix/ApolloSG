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
/** A single bullet: an optional bold label plus the body text. */
interface NarrativeBullet { label: string | null; body: string }

/** One block in the narrative: prose paragraph, section header, or a list of bullets. */
type NarrativePart =
  | { kind: 'para'; text: string }
  | { kind: 'header'; text: string }
  | { kind: 'bullets'; items: NarrativeBullet[] }

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

// ── Guidance composer ─────────────────────────────────────────────────────────
/** Org-specific actions as a natural guidance paragraph.
 *  "If you already X: Y" → "If you have already X, Y".
 *  Threat tones get a "For your safety, " opener. */
function composeGuidance(actions: string[] | undefined, tone: string): string | null {
  if (!actions?.length) return null;
  const cleaned = actions.map((a) =>
    a.replace(/^(If you (?:already |have )?[^:]{4,80}):\s+(.+)$/i,
      (_m, cond: string, rest: string) =>
        `${cond.replace(/\balready\b/, "have already")}, ${rest.charAt(0).toLowerCase()}${rest.slice(1)}`),
  );
  if (tone === "barking" || tone === "ears_up") {
    cleaned[0] = "For your safety, " + cleaned[0].charAt(0).toLowerCase() + cleaned[0].slice(1);
  }
  return cleaned.join(" ");
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

  // Supplement from means if still thin
  if (openSentences.length < 2) {
    for (const m of r.means) {
      for (const s of sentences(m)) {
        if (isNoise(s)) continue;
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
    parts.push({ kind: "para", text: openSentences.join(" ") });
  }

  // ── BLOCK 2: Evidence section — header + bullets ──────────────────────────
  const rawFindings = r.found
    .map((f) => ({ text: scrubMessage(f.text), findingId: f.findingId, category: f.category }))
    .filter((f) => f.text);
  const deduped = dedupFindings(rawFindings).slice(0, MAX_BRIEF_FINDINGS);

  const bulletItems: NarrativeBullet[] = [];
  for (const f of deduped) {
    if (!isNoise(f.text) && !said.repeats(f.text)) {
      // Start body with lowercase so "Label: body text" reads naturally
      const body = f.text.charAt(0).toLowerCase() + f.text.slice(1);
      bulletItems.push({ label: f.category ?? null, body });
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
function bulletString(item: NarrativeBullet): string {
  return item.label ? `• ${item.label}: ${item.body}` : `• ${item.body}`;
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
  prose: {
    fontFamily: fonts.text,
    fontSize: 15,
    lineHeight: 24,
    color: c.onSurfaceSecondary,
  },
  // Section header: "Here is why this raises immediate red flags"
  narrativeHeader: {
    fontFamily: fonts.textSemibold,
    fontSize: 14,
    lineHeight: 20,
    color: c.onSurface,
    letterSpacing: 0.1,
  },
  // Bullet list container — tighter gap than the outer card gap
  bulletList: { gap: 10 },
  bulletRow: { flexDirection: "row", alignItems: "flex-start", gap: 8 },
  bulletMark: {
    fontFamily: fonts.text,
    fontSize: 15,
    lineHeight: 24,
    color: c.onSurfaceSecondary,
    minWidth: 12,
  },
  bulletText: {
    flex: 1,
    fontFamily: fonts.text,
    fontSize: 15,
    lineHeight: 24,
    color: c.onSurfaceSecondary,
  },
  // Bold label portion inside a bullet: "Fake URL: "
  bulletLabel: {
    fontFamily: fonts.textSemibold,
    fontSize: 15,
    lineHeight: 24,
    color: c.onSurface,
  },
  actionText: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface },
  actionLink: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 44 },
  actionLinkText: {
    flex: 1,
    fontFamily: fonts.textMedium,
    fontSize: 15,
    lineHeight: 22,
    color: c.brandPrimary,
  },
  divider: { height: 1, backgroundColor: c.divider },
  copyRow: { flexDirection: "row", alignItems: "center", justifyContent: "flex-end" },
  copyButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
    borderRadius: radius.pill,
    minHeight: 36,
  },
  copyText: { fontFamily: fonts.textSemibold, fontSize: 12, color: c.brandPrimary },
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

  // Org-specific actions or investigation steps
  const orgActions = report.orgActions ?? [];
  const showSteps = !orgActions.length && steps.length > 0;
  const guidanceText = useMemo(
    () => composeGuidance(orgActions, verdict.tone),
    [orgActions, verdict.tone],
  );

  // Action section header (only shown when there is content below it)
  const hasAction = !!guidanceText || showSteps;
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
      } else if (part.kind === "para") {
        if (prevKind !== null) lines.push(""); // blank separator
        lines.push(part.text);
      } else if (part.kind === "bullets") {
        for (const item of part.items) lines.push(bulletString(item));
      }
      prevKind = part.kind;
    }
    // Action section
    if (hasAction) {
      lines.push("");
      lines.push(`${actionHeaderText}:`);
      if (guidanceText) lines.push(guidanceText);
      if (showSteps) steps.forEach((st) => lines.push(`• ${st.text}`));
    }
    return lines.join("\n");
  }, [heading, parts, hasAction, actionHeaderText, guidanceText, steps, showSteps]);

  const handleCopy = useCallback(async () => {
    try { await Clipboard.setStringAsync(copyText); } catch { /* ignore */ }
  }, [copyText]);

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

      {/* ── Narrative parts: prose paragraphs, section headers, bullet lists ── */}
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

        if (part.kind === "header") {
          return (
            <Text key={`h${i}`} style={s.narrativeHeader} testID={`${ids}-section-${i}`}>
              {part.text}
            </Text>
          );
        }

        if (part.kind === "bullets") {
          return (
            <View key={`bl${i}`} style={s.bulletList} testID={`${ids}-bullets-${i}`}>
              {part.items.map((item, j) => (
                <View key={j} style={s.bulletRow}>
                  <Text style={s.bulletMark}>•</Text>
                  <Text style={s.bulletText} testID={`${ids}-bullet-${j}`}>
                    {item.label ? (
                      <>
                        <Text style={s.bulletLabel}>{item.label}: </Text>
                        {item.body}
                      </>
                    ) : item.body}
                  </Text>
                </View>
              ))}
            </View>
          );
        }

        return null;
      })}

      {/* ── Action section: header + guidance prose ── */}
      {hasAction ? (
        <Text style={s.narrativeHeader} testID={`${ids}-action-header`}>
          {actionHeaderText}
        </Text>
      ) : null}

      {guidanceText ? (
        <Text style={s.prose} testID={`${ids}-guidance`}>
          {guidanceText}
        </Text>
      ) : null}

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
