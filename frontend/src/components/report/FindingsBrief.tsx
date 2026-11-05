// The Findings Brief, shared by Ask Higgins and a Threat Case: the result Higgins Luddish gives from the Evidence
// Lock — Verdict → Key findings → What isn't certain → What you can do. A section shows only when it has something
// to say, and nothing is said twice. No investigation mechanics: how Apollo checked is on the DI tab, the sources it
// used on Evidence.
import ChevronRight from "lucide-react-native/icons/chevron-right";
import CircleQuestionMark from "lucide-react-native/icons/circle-question-mark";
import Flag from "lucide-react-native/icons/flag";
import Gavel from "lucide-react-native/icons/gavel";
import Search from "lucide-react-native/icons/search";
import ShieldCheck from "lucide-react-native/icons/shield-check";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Alert, Pressable, Text, View } from "react-native";

import type { BriefVerdict } from "@/src/domain/briefVerdict";
import { luddishReport, luddishText } from "@/src/domain/luddish";
import { sentences } from "@/src/domain/luddish/patterns";
import { scrubMessage } from "@/src/domain/messageVoice";
import type { Report } from "@/src/domain/reportSections";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { listFindingFeedback, submitFindingFeedback } from "@/src/investigation/client";

export interface BriefStep { id: string; text: string; onPress?: () => void }

const ARTICLES = new Set(["a", "an", "the"]);
const words = (t: string) => t.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim().split(" ").filter((w) => w && !ARTICLES.has(w)).join(" ");

export interface BriefFinding { text: string; findingId?: string }

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
  const allFindings = r.found.map((f) => ({ text: scrubMessage(f.text), findingId: f.findingId })).filter((f) => f.text);
  const deduped = dedupFindings(allFindings).slice(0, MAX_BRIEF_FINDINGS);
  return {
    summary: summary.map(scrubMessage),
    findings: deduped,
    uncertain: r.uncertain.map(scrubMessage).filter(Boolean),
  };
}

const useStyles = makeStyles((c) => ({
  section: { flexDirection: "row", gap: spacing.md, borderRadius: radius.lg, padding: spacing.md, borderWidth: 0.25, borderColor: c.border },
  circle: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  content: { flex: 1, gap: spacing.xs },
  pills: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.xs },
  risk: { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.pill },
  riskText: { fontFamily: fonts.textSemibold, fontSize: 12, color: "#FFFFFF" },
  title: { fontFamily: fonts.displayBold, fontSize: 17, color: c.onSurface },
  body: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurfaceSecondary },
  bullet: { flexDirection: "row", gap: spacing.sm },
  dot: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface },
  item: { flex: 1, fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface },
  reportedItem: { opacity: 0.55 },
  link: { color: c.brandPrimary, fontFamily: fonts.textMedium },
  flagBtn: { width: 28, height: 28, alignItems: "center", justifyContent: "center", borderRadius: 14 },
  feedbackBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: radius.pill, alignSelf: "flex-start" },
  badgeIncorrect: { backgroundColor: c.barkingTint },
  badgeLegitimate: { backgroundColor: c.restingTint },
  feedbackBadgeText: { fontFamily: fonts.textSemibold, fontSize: 10, color: c.onSurfaceSecondary },
}));

function Section({ bg, circle, icon, title, testID, children }: {
  bg: string; circle: string; icon: React.ReactNode; title?: string; testID: string; children: React.ReactNode;
}) {
  const s = useStyles();
  return (
    <View style={[s.section, { backgroundColor: bg }]} testID={testID}>
      <View style={[s.circle, { backgroundColor: circle }]}>{icon}</View>
      <View style={s.content}>
        {title ? <Text style={s.title}>{title}</Text> : null}
        {children}
      </View>
    </View>
  );
}

function Bullets({ items, testID }: { items: string[]; testID: string }) {
  const s = useStyles();
  return <>{items.map((text, i) => (
    <View key={`${i}-${text}`} style={s.bullet} testID={`${testID}-${i}`}>
      <Text style={s.dot}>{"\u2022"}</Text>
      <Text style={s.item}>{text}</Text>
    </View>
  ))}</>;
}

function FindingBullets({ items, caseId, testID }: { items: BriefFinding[]; caseId?: string; testID: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  const [reported, setReported] = useState<Record<string, "incorrect" | "legitimate">>({});
  const [sending, setSending] = useState<string | null>(null);

  // Load existing feedback for this case
  useEffect(() => {
    if (!caseId) return;
    listFindingFeedback(caseId).then((res) => {
      const map: Record<string, "incorrect" | "legitimate"> = {};
      for (const fb of res.items) map[fb.findingId] = fb.verdict as "incorrect" | "legitimate";
      setReported(map);
    }).catch(() => {});
  }, [caseId]);

  const onReport = useCallback((findingId: string, text: string) => {
    if (!caseId || !findingId || reported[findingId]) return;
    Alert.alert(
      "Report this finding",
      `Is this finding incorrect or about a legitimate sender?\n\n"${text.slice(0, 120)}${text.length > 120 ? "..." : ""}"`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Incorrect", style: "destructive", onPress: () => send(findingId, "incorrect") },
        { text: "Legitimate", onPress: () => send(findingId, "legitimate") },
      ],
    );
  }, [caseId, reported]);

  const send = useCallback(async (findingId: string, verdict: "incorrect" | "legitimate") => {
    if (!caseId) return;
    setSending(findingId);
    try {
      await submitFindingFeedback(caseId, findingId, verdict);
      setReported((prev) => ({ ...prev, [findingId]: verdict }));
    } catch {
      Alert.alert("Could not submit", "Please try again later.");
    } finally {
      setSending(null);
    }
  }, [caseId]);

  return <>{items.map((f, i) => {
    const hasId = !!f.findingId && !!caseId;
    const fb = f.findingId ? reported[f.findingId] : undefined;
    return (
      <View key={`${i}-${f.text}`} style={s.bullet} testID={`${testID}-${i}`}>
        <Text style={s.dot}>{"\u2022"}</Text>
        <Text style={[s.item, fb ? s.reportedItem : undefined]}>{f.text}</Text>
        {hasId ? (
          sending === f.findingId ? (
            <ActivityIndicator size="small" color={colors.muted} style={{ marginLeft: 4, width: 28 }} />
          ) : fb ? (
            <View style={[s.feedbackBadge, fb === "incorrect" ? s.badgeIncorrect : s.badgeLegitimate]}>
              <Text style={s.feedbackBadgeText}>{fb === "incorrect" ? "Reported" : "OK"}</Text>
            </View>
          ) : (
            <Pressable
              onPress={() => onReport(f.findingId!, f.text)}
              hitSlop={8}
              style={({ pressed }) => [s.flagBtn, { opacity: pressed ? 0.5 : 1 }]}
              accessibilityLabel="Report this finding"
              testID={`${testID}-${i}-flag`}
            >
              <Flag size={14} color={colors.muted} />
            </Pressable>
          )
        ) : null}
      </View>
    );
  })}</>;
}

export function FindingsBrief({ report, verdict, steps, ids, caseId }: {
  report: Report; verdict: BriefVerdict; steps: BriefStep[];
  /** testID prefix: "inv" on Ask Higgins, "tc-overview" on a threat. */
  ids: string;
  /** Case ID for finding feedback. When provided, each finding gets a report button. */
  caseId?: string;
}) {
  const s = useStyles();
  const { colors } = useTheme();
  const { summary, findings, uncertain } = useMemo(() => briefSections(report, verdict), [report, verdict]);
  const tone = {
    barking: { bg: colors.barkingTint, solid: colors.barking, ink: colors.barkingText },
    ears_up: { bg: colors.ears_upTint, solid: colors.ears_up, ink: colors.ears_upText },
    resting: { bg: colors.restingTint, solid: colors.resting, ink: colors.restingText },
    sniffing: { bg: colors.sniffingTint, solid: colors.sniffing, ink: colors.sniffingText },
  }[verdict.tone];

  return (
    <View style={{ gap: spacing.md }} testID={`${ids}-brief`}>
      {verdict.label || summary.length ? (
        <Section bg={tone.bg} circle={tone.solid} icon={<Gavel size={22} color="#FFFFFF" />} testID={`${ids}-verdict`}>
          {/* Titled like every other card; the pills sit under the title so they never crowd it on a phone. */}
          <Text style={s.title}>
            {verdict.label ? <>{"Verdict: "}<Text style={{ color: tone.ink }} testID={`${ids}-verdict-label`}>{verdict.label}</Text></> : "Higgins' answer"}
          </Text>
          {verdict.risk || verdict.status ? (
            <View style={s.pills}>
              {verdict.risk ? (
                <View style={[s.risk, { backgroundColor: verdict.risk.color }]} testID={`${ids}-risk`}>
                  <Text style={s.riskText}>{verdict.risk.label}</Text>
                </View>
              ) : null}
              {verdict.status ? (
                <View style={[s.risk, { backgroundColor: verdict.status.bg }]} testID={`${ids}-status`}>
                  <Text style={[s.riskText, { color: verdict.status.fg }]}>{verdict.status.label}</Text>
                </View>
              ) : null}
            </View>
          ) : null}
          {summary.map((para, i) => <Text key={`a${i}`} style={s.body} testID={i === 0 ? `${ids}-answer` : `${ids}-answer-${i}`}>{para}</Text>)}
        </Section>
      ) : null}

      {findings.length ? (
        <Section bg={colors.goldTint} circle={colors.ears_upTint} icon={<Search size={22} color={colors.ears_upText} />} title="Key findings" testID={`${ids}-findings`}>
          <FindingBullets items={findings} caseId={caseId} testID={`${ids}-finding`} />
        </Section>
      ) : null}

      {uncertain.length ? (
        <Section bg={colors.groupAccountsTint} circle={colors.groupAccountsTint} icon={<CircleQuestionMark size={22} color={colors.groupAccounts} />} title="What isn't certain" testID={`${ids}-uncertainties`}>
          <Bullets items={uncertain} testID={`${ids}-uncertain`} />
        </Section>
      ) : null}

      {steps.length ? (
        <Section bg={colors.restingTint} circle={colors.restingTint} icon={<ShieldCheck size={22} color={colors.restingText} />} title="What you can do" testID={`${ids}-todo`}>
          {steps.map((step) => {
            const text = luddishText(scrubMessage(step.text), true);
            return step.onPress ? (
              <Pressable key={step.id} style={({ pressed }) => [s.bullet, { minHeight: 44, alignItems: "center", opacity: pressed ? 0.7 : 1 }]} onPress={step.onPress}
                accessibilityRole="button" testID={`${ids}-action-${step.id}`}>
                <Text style={s.dot}>{"\u2022"}</Text>
                <Text style={[s.item, s.link]}>{text}</Text>
                <ChevronRight size={18} color={colors.muted} />
              </Pressable>
            ) : (
              <View key={step.id} style={s.bullet} testID={`${ids}-action-${step.id}`}>
                <Text style={s.dot}>{"\u2022"}</Text>
                <Text style={s.item}>{text}</Text>
              </View>
            );
          })}
        </Section>
      ) : null}
    </View>
  );
}
