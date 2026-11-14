// The Deep Investigation (DI) tab: how the investigation reached its result. The decision path in the order it ran —
// Higgins Triage → TC Hawkeye → Magnum DI → Evidence Lock — then the outside research behind it, each source with the
// fact it supports or points against, how Apollo checked and the related history it had. Plain words only: token
// counts, cost, Magnum DI's prompts and full reply, and rule-book codes are in the Admin Portal. The provider and
// model are never shown. Shown on both the Threat Case screen and Ask Higgins. Evidence is never modified here.

import React, { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";
import ChevronDown from "lucide-react-native/icons/chevron-down";
import ChevronUp from "lucide-react-native/icons/chevron-up";

import { apiGet } from "@/src/api/client";
import { SettledByBadge } from "@/src/components/SettledByBadge";
import { SettledReasonLine } from "@/src/components/SettledReasonLine";
import { Card } from "@/src/components/ui";
import type { PatrolEvent } from "@/src/domain/types";
import type { FindingsRatingBreakdown, FindingsRatingDimension, HigginsResponse, HistoryNote, SettledReason, SourceReference } from "@/src/investigation/types";
import type { DiTrace, DiTransaction } from "@/src/domain/diTransaction";
import { buildDecisionTrace, type PresentedResult, type ResearchRow, type TraceStatus, type TraceStep } from "@/src/domain/diTrace";
import type { TriageInvestigationRecord } from "@/src/domain/triage/contract";
import { formatDateTime } from "@/src/domain/threatCase";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  content: { paddingHorizontal: spacing.md, gap: spacing.md, paddingBottom: spacing.xl },
  sectionTitle: { fontFamily: fonts.displayBold, fontSize: 16, color: c.onSurface, marginBottom: spacing.xs },
  sourceSub: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurfaceSecondary },
  value: { fontFamily: fonts.text, fontSize: 13, lineHeight: 18, color: c.onSurface },
  note: { fontFamily: fonts.text, fontSize: 11, lineHeight: 15, color: c.onSurfaceSecondary, marginTop: 2 },
  diNotice: { borderRadius: radius.md, borderWidth: 1, borderStyle: "dashed", borderColor: c.gold, backgroundColor: c.surfaceSecondary, padding: spacing.md },
  diNoticeText: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.onSurface },
  // Decision path
  stepRow: { flexDirection: "row", gap: spacing.md },
  stepRail: { width: 14, alignItems: "center" },
  stepDot: { width: 12, height: 12, borderRadius: 6, marginTop: 4 },
  stepLine: { width: 2, flex: 1, backgroundColor: c.divider, marginTop: 4 },
  stepBody: { flex: 1, paddingBottom: spacing.md, gap: 4 },
  stepHead: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: spacing.sm },
  stepName: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.onSurface },
  pill: { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.pill },
  pillText: { fontFamily: fonts.textSemibold, fontSize: 11 },
  stepDetail: { fontFamily: fonts.text, fontSize: 12, lineHeight: 17, color: c.onSurfaceSecondary },
  // Outside research
  source: { paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: c.divider, gap: 4 },
  sourceTitle: { fontFamily: fonts.textSemibold, fontSize: 14, lineHeight: 19, color: c.onSurface },
  factLabel: { fontFamily: fonts.textSemibold, fontSize: 12, marginTop: 2 },
  // Expandable sections
  expandToggle: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: spacing.sm },
  expandLabel: { fontFamily: fonts.textSemibold, fontSize: 12, color: c.brandPrimary },
  sectionToggle: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.xs },
  sectionToggleText: { fontFamily: fonts.textSemibold, fontSize: 16, color: c.onSurface, flex: 1 },
  detailSummary: { fontFamily: fonts.text, fontSize: 12, color: c.muted, marginTop: 2 },
  // Scoring breakdown
  scoreHeadline: { fontFamily: fonts.displayBold, fontSize: 20, color: c.onSurface },
  scoreDimRow: { borderTopWidth: 1, borderTopColor: c.divider, paddingVertical: spacing.sm },
  scoreDimHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  scoreDimLabel: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface, flex: 1 },
  scoreDimPoints: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface },
  scoreDimWhy: { fontFamily: fonts.text, fontSize: 12, lineHeight: 17, color: c.onSurfaceSecondary, marginTop: 2 },
  scoreSubLabel: { fontFamily: fonts.textSemibold, fontSize: 11, letterSpacing: 0.3, color: c.muted, textTransform: "uppercase", marginTop: spacing.sm },
  traceBlock: { marginTop: spacing.md, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: c.divider, gap: 4 },
}));

// ── Scoring breakdown (DI Scoring Transparency, Apollo PRD v2.3) ────────────

const FINDING_RATING_LABELS: Record<string, string> = {
  scam: "This is a Scam", likely_scam: "This is Likely a Scam",
  unlikely_scam: "This is Unlikely a Scam", not_scam: "This is Not a Scam",
};

function ScoreDimensionRow({ dim }: { dim: FindingsRatingDimension }) {
  const s = useStyles();
  const checks = dim.checks ?? [];
  const evidence = dim.evidence ?? [];
  const missing = dim.missing ?? [];
  return (
    <View style={s.scoreDimRow} testID={`tc-di-score-dim-${dim.key}`}>
      <View style={s.scoreDimHead}>
        <Text style={s.scoreDimLabel}>{dim.label}</Text>
        <Text style={s.scoreDimPoints} testID={`tc-di-score-dim-${dim.key}-points`}>{dim.points}/{dim.max}</Text>
      </View>
      <Text style={s.scoreDimWhy} selectable>{dim.why}</Text>
      {checks.length || evidence.length || missing.length ? (
        <View style={{ gap: 4 }} testID={`tc-di-score-dim-${dim.key}-details`}>
          {checks.length ? (
            <View>
              <Text style={s.scoreSubLabel}>Checks performed</Text>
              {checks.map((c, i) => <Text key={i} style={s.stepDetail} selectable>{`• ${c.kind} check on ${c.subject}: ${c.status}`}</Text>)}
            </View>
          ) : null}
          {evidence.length ? (
            <View>
              <Text style={s.scoreSubLabel}>Evidence</Text>
              {evidence.map((e, i) => <Text key={i} style={s.stepDetail} selectable>{`• ${e}`}</Text>)}
            </View>
          ) : null}
          {missing.length ? (
            <View>
              <Text style={s.scoreSubLabel}>Missing evidence (not reported as clean)</Text>
              {missing.map((m, i) => <Text key={i} style={s.stepDetail} selectable>{`• ${m}`}</Text>)}
            </View>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

/** The Scoring Breakdown card: one collapsible card, closed until opened (owner, 2026-11-08). Inside it the rating,
 *  then every dimension with its checks and evidence shown in full — no section of its own collapses, and nothing is
 *  said twice: the narrative paragraph and the "how this was calculated" sum restated the rows, so they're gone. */
function ScoreBreakdown({ breakdown }: { breakdown: FindingsRatingBreakdown }) {
  const s = useStyles();
  const dimensions = breakdown.dimensions ?? [];
  const gaps = breakdown.contentGaps ?? [];
  return (
    <CollapsibleSection title="Scoring Breakdown" testID="tc-di-score-breakdown">
      <Text style={s.scoreHeadline} testID="tc-di-score-rating">
        {breakdown.rating} / 100 {"\u2014"} {FINDING_RATING_LABELS[breakdown.finding] ?? breakdown.finding}
      </Text>
      <View style={{ height: spacing.sm }} />

      {dimensions.map((d) => <ScoreDimensionRow key={d.key} dim={d} />)}

      {breakdown.adjustmentReason ? (
        <View style={s.traceBlock} testID="tc-di-score-adjustment">
          <Text style={s.scoreSubLabel}>Rating adjusted to match the evidence{breakdown.verdictRuleIds?.length ? ` (rule ${breakdown.verdictRuleIds.join(", ")})` : ""}</Text>
          <Text style={s.stepDetail} selectable>{`Calculated: ${breakdown.rawRating} / 100  \u2192  Shown: ${breakdown.rating} / 100`}</Text>
          <Text style={s.stepDetail} selectable>{breakdown.adjustmentReason}</Text>
        </View>
      ) : null}

      {gaps.length ? (
        <View style={s.traceBlock} testID="tc-di-score-gaps">
          <Text style={s.scoreSubLabel}>Content ApolloSG could not read</Text>
          {gaps.map((g, i) => <Text key={i} style={s.stepDetail} selectable>{`• ${g}`}</Text>)}
        </View>
      ) : null}
    </CollapsibleSection>
  );
}

type DiState = { loading: boolean; error: string | null; records: DiTransaction[]; trace: DiTrace | null };

/** The Magnum DI record(s) and decision path for one case, as the server gives them to the app. */
export function useDiTransactions(caseId: string | null): DiState {
  const [state, setState] = useState<DiState>({ loading: !!caseId, error: null, records: [], trace: null });

  useEffect(() => {
    if (!caseId) return;
    let alive = true;
    apiGet<{ transactions: DiTransaction[]; trace?: DiTrace | null }>(`/investigations/${encodeURIComponent(caseId)}/di`)
      .then((data) => { if (alive) setState({ loading: false, error: null, records: data.transactions ?? [], trace: data.trace ?? null }); })
      .catch((error: unknown) => {
        if (alive) setState({ loading: false, error: error instanceof Error ? error.message : "The DI record could not be read.", records: [], trace: null });
      });
    return () => { alive = false; };
  }, [caseId]);

  return state;
}

// ── Decision path ───────────────────────────────────────────────────────────

function useStatusColors(): Record<TraceStatus, { dot: string; bg: string; fg: string }> {
  const { colors } = useTheme();
  const muted = { dot: colors.muted, bg: colors.surfaceSecondary, fg: colors.onSurfaceSecondary };
  return {
    ran: { dot: colors.brandPrimary, bg: colors.sniffingTint, fg: colors.sniffingText },
    settled: { dot: colors.restingText, bg: colors.restingTint, fg: colors.restingText },
    escalated: { dot: colors.ears_upText, bg: colors.ears_upTint, fg: colors.ears_upText },
    simulated: { dot: colors.gold, bg: colors.ears_upTint, fg: colors.ears_upText },
    failed: { dot: colors.barkingText, bg: colors.barkingTint, fg: colors.barkingText },
    not_engaged: muted, pending: muted, not_recorded: muted,
  };
}

function DecisionTrace({ steps, settled }: { steps: TraceStep[]; settled: React.ReactNode }) {
  const s = useStyles();
  const tones = useStatusColors();
  const { colors } = useTheme();
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set());
  const toggleStep = (id: string) => setExpandedSteps((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  return (
    <Card testID="tc-di-trace">
      <Text style={s.sectionTitle}>Decision path</Text>
      {settled}
      <Text style={[s.note, { marginBottom: spacing.md }]}>{steps.map(step => step.name).join(" → ")}</Text>
      {steps.map((step, i) => {
        const tone = tones[step.status];
        const hasDetails = step.details.length > 0;
        const isExpanded = expandedSteps.has(step.id);
        return (
          <View key={step.id} style={s.stepRow} testID={`tc-di-step-${step.id}`}>
            <View style={s.stepRail}>
              <View style={[s.stepDot, { backgroundColor: tone.dot }]} />
              {i < steps.length - 1 ? <View style={s.stepLine} /> : null}
            </View>
            <View style={s.stepBody}>
              <View style={s.stepHead}>
                <Text style={s.stepName}>{step.name}</Text>
                <View style={[s.pill, { backgroundColor: tone.bg }]}>
                  <Text style={[s.pillText, { color: tone.fg }]} testID={`tc-di-step-${step.id}-status`}>{step.label}</Text>
                </View>
              </View>
              <Text style={s.value} selectable testID={`tc-di-step-${step.id}-summary`}>{step.summary}</Text>
              {hasDetails ? (
                <Pressable style={s.expandToggle} onPress={() => toggleStep(step.id)} hitSlop={8} testID={`tc-di-step-${step.id}-toggle`}>
                  <Text style={s.expandLabel}>{isExpanded ? "Hide details" : `Show ${step.details.length} detail${step.details.length > 1 ? "s" : ""}`}</Text>
                  {isExpanded ? <ChevronUp size={14} color={colors.brandPrimary} /> : <ChevronDown size={14} color={colors.brandPrimary} />}
                </Pressable>
              ) : null}
              {hasDetails && isExpanded ? step.details.map((d, j) => <Text key={j} style={s.stepDetail} selectable testID={`tc-di-step-${step.id}-detail-${j}`}>{`• ${d}`}</Text>) : null}
            </View>
          </View>
        );
      })}
    </Card>
  );
}

// ── Outside research ────────────────────────────────────────────────────────

function FactList({ label, facts, color, testID }: { label: string; facts: string[]; color: string; testID: string }) {
  const s = useStyles();
  if (!facts.length) return null;
  return (
    <View testID={testID}>
      <Text style={[s.factLabel, { color }]}>{label}</Text>
      {facts.map((f, i) => <Text key={i} style={s.stepDetail} selectable>{`• ${f}`}</Text>)}
    </View>
  );
}

function ResearchSource({ r, i }: { r: ResearchRow; i: number }) {
  const s = useStyles();
  const { colors } = useTheme();
  const hasFacts = r.supports.length > 0 || r.against.length > 0 || r.other.length > 0;
  const [expanded, setExpanded] = useState(false);
  const factCount = r.supports.length + r.against.length + r.other.length;
  return (
    <View style={s.source} testID={`tc-di-research-${i}`}>
      <Pressable onPress={() => setExpanded((v) => !v)} hitSlop={6}>
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
          <Text style={[s.sourceTitle, { flex: 1 }]} selectable>{r.title}</Text>
          {hasFacts ? (expanded ? <ChevronUp size={14} color={colors.muted} /> : <ChevronDown size={14} color={colors.muted} />) : null}
        </View>
        <Text style={s.note} selectable>
          {[r.site && r.site !== r.title ? r.site : null, r.standing, r.how, r.at ? formatDateTime(r.at) : null, r.reused ? "From an earlier check" : null].filter(Boolean).join(" · ")}
        </Text>
        {!expanded && hasFacts ? <Text style={[s.note, { fontStyle: "italic" }]}>{`${factCount} fact${factCount !== 1 ? "s" : ""} cited — tap to expand`}</Text> : null}
      </Pressable>
      {expanded || !hasFacts ? <>
        <FactList label="Supports" facts={r.supports} color={colors.onSurface} testID={`tc-di-research-${i}-supports`} />
        <FactList label="Points the other way" facts={r.against} color={colors.ears_upText} testID={`tc-di-research-${i}-against`} />
        <FactList label="Also informs" facts={r.other} color={colors.onSurfaceSecondary} testID={`tc-di-research-${i}-other`} />
        {!r.supports.length && !r.against.length && !r.other.length ? (
          <Text style={s.stepDetail} testID={`tc-di-research-${i}-uncited`}>Consulted, but no fact rests on it.</Text>
        ) : null}
      </> : null}
    </View>
  );
}

export function Research({ rows }: { rows: ResearchRow[] }) {
  const s = useStyles();
  const { colors } = useTheme();
  const [showAll, setShowAll] = useState(false);
  const INITIAL_SHOWN = 3;
  const visibleRows = showAll ? rows : rows.slice(0, INITIAL_SHOWN);
  const hasMore = rows.length > INITIAL_SHOWN;
  return (
    <Card testID="tc-di-research">
      <Text style={s.sectionTitle}>Outside research</Text>
      {rows.length ? (
        <Text style={[s.sourceSub, { marginBottom: spacing.xs }]}>Each source ApolloSG consulted, and the fact it supports or points against.</Text>
      ) : (
        <Text style={s.sourceSub} testID="tc-di-research-none">No outside research is recorded for this case.</Text>
      )}
      {visibleRows.map((r, i) => <ResearchSource key={r.id} r={r} i={i} />)}
      {hasMore && !showAll ? (
        <Pressable style={[s.expandToggle, { justifyContent: "center" }]} onPress={() => setShowAll(true)} hitSlop={8} testID="tc-di-research-show-all">
          <Text style={s.expandLabel}>{`Show all ${rows.length} sources`}</Text>
          <ChevronDown size={14} color={colors.brandPrimary} />
        </Pressable>
      ) : null}
    </Card>
  );
}

// ── Collapsible section wrapper ──────────────────────────────────────────────

export function CollapsibleSection({ title, subtitle, children, testID, defaultOpen = false }: {
  title: string; subtitle?: string; children: React.ReactNode; testID: string; defaultOpen?: boolean;
}) {
  const s = useStyles();
  const { colors } = useTheme();
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Card testID={testID}>
      <Pressable style={s.sectionToggle} onPress={() => setOpen((v) => !v)} hitSlop={8} testID={`${testID}-toggle`}>
        <Text style={s.sectionToggleText}>{title}</Text>
        {open ? <ChevronUp size={16} color={colors.muted} /> : <ChevronDown size={16} color={colors.muted} />}
      </Pressable>
      {!open && subtitle ? <Text style={s.detailSummary}>{subtitle}</Text> : null}
      {open ? <>
        {subtitle ? <Text style={[s.sourceSub, { marginBottom: spacing.xs }]}>{subtitle}</Text> : null}
        {children}
      </> : null}
    </Card>
  );
}

// ── The DI tab ──────────────────────────────────────────────────────────────

export function DiReport({ caseId, triage, settledReason, settledEvent, how, presented, history, response, sources }: {
  caseId: string | null;
  /** The verdict and severity Higgins presented — the case result the Findings Brief shows. */
  presented?: PresentedResult | null;
  /** "How ApolloSG checked", in Higgins' plain words: the method behind the Findings Brief, kept here and not there. */
  how?: string[];
  /** The related history TC Hawkeye and Magnum DI had, with where each note came from (context, never evidence). */
  history?: HistoryNote[];
  triage?: TriageInvestigationRecord | null;
  /** The rule that settled the result, as this phone recorded it ("Settled by TC Hawkeye — …"). */
  settledReason?: SettledReason | null;
  /** For results saved before the settling rule was recorded: who settled it, from the threat's record. */
  settledEvent?: Pick<PatrolEvent, "investigation_completed_at" | "investigation_answered_by"> | null;
  /** The finished result: what was locked, and the facts each outside source supports or points against. */
  response?: HigginsResponse | null;
  /** The outside sources the result cites. */
  sources?: SourceReference[];
}) {
  const s = useStyles();
  const state = useDiTransactions(caseId);

  if (!caseId && !triage) {
    return (
      <View style={s.content}>
        <Card testID="tc-di-none">
          <Text style={s.sectionTitle}>No decision record</Text>
          <Text style={s.sourceSub}>
            Apollo settled this case with his own checks. Magnum DI was not engaged, and no Higgins Triage, TC Hawkeye or
            Magnum DI record is stored for it.
          </Text>
        </Card>
      </View>
    );
  }

  if (caseId && state.loading) {
    return <View style={s.content}><Card testID="tc-di-loading"><Text style={s.sourceSub}>Reading the decision record…</Text></Card></View>;
  }

  if (caseId && state.error) {
    return <View style={s.content}><Card testID="tc-di-error"><Text style={s.sectionTitle}>DI record unavailable</Text><Text style={s.sourceSub}>{state.error}</Text></Card></View>;
  }

  const triageRecord = state.trace?.triage ?? triage ?? null;
  const steps = buildDecisionTrace({ trace: state.trace, records: state.records, triage: triageRecord, hasCase: !!caseId, presented, response });
  // Who settled the result and by which rule: the device's record, else the server's decision record.
  const reason = settledReason ?? state.trace?.settledReason ?? null;
  const settled = reason ? <SettledReasonLine reason={reason} testID="tc-di-settled-reason" />
    : settledEvent ? <SettledByBadge event={settledEvent} testID="tc-di-settled" /> : null;

  return (
    <View style={s.content} testID="tc-di-content">
      {/* A simulated record says so; every other line below is what ran. */}
      {state.records.map((record, index) => record.notice && !record.simulated ? (
        <View key={index} style={s.diNotice} testID={`tc-di-notice-${index}`}>
          <Text style={s.diNoticeText}>{record.notice}</Text>
        </View>
      ) : null)}

      <DecisionTrace steps={steps} settled={settled} />

      {response?.findingsRatingBreakdown ? <ScoreBreakdown breakdown={response.findingsRatingBreakdown} /> : null}
    </View>
  );
}
