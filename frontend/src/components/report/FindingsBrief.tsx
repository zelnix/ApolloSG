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

/** Flowing prose from the report: the verdict heading lives in the shield row; everything
 *  else becomes continuous paragraphs with no section titles and no bullet points. */
function briefNarrative(report: Report, verdict: Pick<BriefVerdict, "label" | "caution" | "tone">): {
  heading: string | null;
  paragraphs: string[];
} {
  const r = luddishReport(report);
  const heading = verdict.label || null;
  const paragraphs: string[] = [];
  const labelWords = heading ? words(heading) : null;

  // Opening: answer sentences minus the verdict label (already in the shield heading).
  const opening: string[] = [];
  for (const para of r.answer) {
    const kept = labelWords
      ? sentences(para).filter((s) => words(s) !== labelWords)
      : sentences(para);
    opening.push(...kept);
  }
  // Enrich with "what it means" when it adds something new.
  for (const m of r.means) {
    if (!opening.some((s) => words(s) === words(m))) opening.push(m);
  }
  // Caution rides along if the opening doesn't already carry it.
  if (verdict.caution && !opening.some((s) => s.includes(verdict.caution!))) {
    opening.push(verdict.caution);
  }
  if (opening.length) paragraphs.push(scrubMessage(opening.join(" ")));

  // Evidence: deduplicated findings as flowing sentences.
  const allFindings = r.found.map((f) => ({ text: scrubMessage(f.text), findingId: f.findingId, category: f.category })).filter((f) => f.text);
  const deduped = dedupFindings(allFindings).slice(0, MAX_BRIEF_FINDINGS);
  if (deduped.length) paragraphs.push(deduped.map((f) => f.text).join(" "));

  // Additional investigation sections, flattened into prose.
  for (const section of r.more) {
    const text = section.paragraphs.map(scrubMessage).filter(Boolean).join(" ");
    if (text) paragraphs.push(text);
  }

  // Uncertainties as a closing caveat paragraph.
  const uncertainTexts = r.uncertain.map(scrubMessage).filter(Boolean);
  if (uncertainTexts.length) paragraphs.push(uncertainTexts.join(" "));

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

  // Plain text for the clipboard.
  const copyText = useMemo(() => {
    const parts: string[] = [];
    if (heading) parts.push(heading);
    parts.push(...paragraphs);
    if (orgActions.length) { parts.push(""); orgActions.forEach((a) => parts.push(`\u2022 ${a}`)); }
    if (showSteps) { parts.push(""); steps.forEach((st) => parts.push(`\u2022 ${st.text}`)); }
    return parts.join("\n\n");
  }, [heading, paragraphs, orgActions, steps, showSteps]);

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

      {/* ── Org-specific actions (inline prose) ── */}
      {orgActions.length ? (
        <Text style={s.actionText} testID={`${ids}-actions`}>
          {orgActions.join(" ")}
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
