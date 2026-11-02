// The Deep Investigation (DI) tab: how the investigation reached its result. The decision path in the order it ran —
// Higgins Triage → TC FlyBy → Magnum DI → Evidence Lock — then the outside research behind it, each source with the
// fact it supports or points against, how Apollo checked and the related history it had. Plain words only: token
// counts, cost, Magnum DI's prompts and full reply, and rule-book codes are in the Admin Portal. The provider and
// model are never shown. Shown on both the Threat Case screen and Ask Higgins. Evidence is never modified here.

import React, { useEffect, useState } from "react";
import { Text, View } from "react-native";

import { apiGet } from "@/src/api/client";
import { SettledByBadge } from "@/src/components/SettledByBadge";
import { SettledReasonLine } from "@/src/components/SettledReasonLine";
import { Card } from "@/src/components/ui";
import type { PatrolEvent } from "@/src/domain/types";
import type { HigginsResponse, HistoryNote, SettledReason, SourceReference } from "@/src/investigation/types";
import type { DiTrace, DiTransaction } from "@/src/domain/diTransaction";
import { buildDecisionTrace, outsideResearch, TRACE_ORDER, type PresentedResult, type ResearchRow, type TraceStatus, type TraceStep } from "@/src/domain/diTrace";
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
}));

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
  return (
    <Card testID="tc-di-trace">
      <Text style={s.sectionTitle}>Decision path</Text>
      {settled}
      <Text style={[s.note, { marginBottom: spacing.md }]}>{TRACE_ORDER}</Text>
      {steps.map((step, i) => {
        const tone = tones[step.status];
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
              {step.details.map((d, j) => <Text key={j} style={s.stepDetail} selectable testID={`tc-di-step-${step.id}-detail-${j}`}>{`• ${d}`}</Text>)}
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

function Research({ rows }: { rows: ResearchRow[] }) {
  const s = useStyles();
  const { colors } = useTheme();
  return (
    <Card testID="tc-di-research">
      <Text style={s.sectionTitle}>Outside research</Text>
      {rows.length ? (
        <Text style={[s.sourceSub, { marginBottom: spacing.xs }]}>Each source ApolloSG consulted, and the fact it supports or points against.</Text>
      ) : (
        <Text style={s.sourceSub} testID="tc-di-research-none">No outside research is recorded for this case.</Text>
      )}
      {rows.map((r, i) => (
        <View key={r.id} style={s.source} testID={`tc-di-research-${i}`}>
          <Text style={s.sourceTitle} selectable>{r.title}</Text>
          <Text style={s.note} selectable>
            {[r.site && r.site !== r.title ? r.site : null, r.standing, r.how, r.at ? formatDateTime(r.at) : null, r.reused ? "From an earlier check" : null].filter(Boolean).join(" · ")}
          </Text>
          <FactList label="Supports" facts={r.supports} color={colors.onSurface} testID={`tc-di-research-${i}-supports`} />
          <FactList label="Points the other way" facts={r.against} color={colors.ears_upText} testID={`tc-di-research-${i}-against`} />
          <FactList label="Also informs" facts={r.other} color={colors.onSurfaceSecondary} testID={`tc-di-research-${i}-other`} />
          {!r.supports.length && !r.against.length && !r.other.length ? (
            <Text style={s.stepDetail} testID={`tc-di-research-${i}-uncited`}>Consulted, but no fact rests on it.</Text>
          ) : null}
        </View>
      ))}
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
  /** The related history TC FlyBy and Magnum DI had, with where each note came from (context, never evidence). */
  history?: HistoryNote[];
  triage?: TriageInvestigationRecord | null;
  /** The rule that settled the result, as this phone recorded it ("Settled by TC FlyBy — …"). */
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
            Apollo settled this case with his own checks. Magnum DI was not engaged, and no Higgins Triage, TC FlyBy or
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

      <Research rows={outsideResearch(sources ?? [], response ?? null)} />

      {how?.length ? (
        <Card testID="tc-di-how">
          <Text style={s.sectionTitle}>How ApolloSG checked</Text>
          {how.map((line, i) => <Text key={`${i}-${line}`} style={s.sourceSub} testID={`tc-di-how-${i}`}>{line}</Text>)}
        </Card>
      ) : null}

      {history?.length ? (
        <Card testID="tc-di-history">
          <Text style={s.sectionTitle}>Related history</Text>
          <Text style={s.sourceSub}>Context TC FlyBy and Magnum DI had, never evidence for this case. It can't change the verdict.</Text>
          {history.map((n, i) => (
            <Text key={`${i}-${n.text}`} style={s.sourceSub} testID={`tc-di-history-${i}`}>
              {`${n.source}: ${n.text}${n.findingIds.length ? ` Raised the confidence of ${n.findingIds.length === 1 ? "one finding" : `${n.findingIds.length} findings`}.` : ""}`}
            </Text>
          ))}
        </Card>
      ) : null}
    </View>
  );
}
