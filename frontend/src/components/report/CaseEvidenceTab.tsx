// The Threat Case Evidence tab: the material facts the case established, strongest first, each saying who found it and
// who confirmed it — then the original, as it arrived (inert), the evidence trail and Copy / Share.
// Every line comes from domain/caseEvidence.ts (the case's own records); nothing here re-decides a verdict or a status.
import ChevronDown from "lucide-react-native/icons/chevron-down";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import CircleAlert from "lucide-react-native/icons/circle-alert";
import CircleCheck from "lucide-react-native/icons/circle-check";
import Network from "lucide-react-native/icons/network";
import Search from "lucide-react-native/icons/search";
import Shield from "lucide-react-native/icons/shield";
import React, { useMemo, useState } from "react";
import { Linking, Pressable, Text, View } from "react-native";

import { CaseEvidenceProfile } from "@/src/components/CaseEvidenceProfile";
import { useDiTransactions } from "@/src/components/DiReport";
import { EvidenceArtefactCard } from "@/src/components/evidence/EvidenceArtefactCard";
import { caseEvidence, provenanceLine, type FactPiece, type TrailStage } from "@/src/domain/caseEvidence";
import { RAISED_LABEL } from "@/src/domain/caseHistory";
import { heroWhen } from "@/src/domain/homeHeroBrief";
import { formatDateTime } from "@/src/domain/threatCase";
import type { PatrolEvent } from "@/src/domain/types";
import type { DeviceInvestigation } from "@/src/investigation/deviceStore";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

type Icon = React.ComponentType<{ size: number; color: string }>;

const useStyles = makeStyles((c) => ({
  content: { paddingHorizontal: spacing.md, gap: spacing.md, paddingBottom: spacing.xl },
  card: { padding: spacing.md, borderRadius: radius.lg, backgroundColor: c.surface, borderWidth: 1, borderColor: c.border, gap: spacing.md },
  head: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  circle: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  headText: { flex: 1, gap: 2 },
  title: { fontFamily: fonts.displayBold, fontSize: 17, color: c.onSurface },
  sub: { fontFamily: fonts.text, fontSize: 13, lineHeight: 18, color: c.onSurfaceSecondary },
  // Fact cards
  fact: { padding: spacing.md, borderRadius: radius.lg, backgroundColor: c.surface, borderWidth: 1, borderColor: c.border, gap: spacing.sm },
  factContrary: { borderColor: c.ears_upText },
  row: { flexDirection: "row", gap: spacing.md },
  rowIcon: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  rowBody: { flex: 1, gap: 6 },
  rowTop: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  factText: { flex: 1, fontFamily: fonts.textSemibold, fontSize: 15, lineHeight: 21, color: c.onSurface },
  pills: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  meta: { fontFamily: fonts.text, fontSize: 12, lineHeight: 17, color: c.onSurfaceSecondary },
  metaLabel: { fontFamily: fonts.textSemibold, color: c.onSurfaceSecondary },
  provenance: { fontFamily: fonts.textMedium, fontSize: 13, lineHeight: 18, color: c.onSurfaceSecondary },
  pill: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.pill, alignSelf: "flex-start" },
  pillText: { fontFamily: fonts.textSemibold, fontSize: 12 },
  detail: { gap: 4, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: c.divider },
  link: { fontFamily: fonts.textMedium, fontSize: 12, lineHeight: 17, color: c.brandPrimary },
  empty: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurfaceSecondary },
  // Trail
  trail: { flexDirection: "row", alignItems: "stretch", gap: 4 },
  stage: { flex: 1, minWidth: 0, flexDirection: "row", gap: 6, padding: spacing.sm, borderRadius: radius.md, borderWidth: 1, borderColor: c.border },
  stageText: { flex: 1, minWidth: 0, gap: 2 },
  stageName: { fontFamily: fonts.textSemibold, fontSize: 13, lineHeight: 17, color: c.onSurface },
  stageMeta: { fontFamily: fonts.text, fontSize: 11, lineHeight: 15, color: c.onSurfaceSecondary },
  arrow: { justifyContent: "center" },
}));

const CONFIDENCE_LABEL = { high: "High confidence", medium: "Medium confidence", low: "Low confidence" } as const;

/** The fact's one marker: what points the other way says so; a weak signal says so; otherwise how firmly it was recorded. */
function factMark(f: FactPiece): { label: string; tone: "contrary" | "weak" | "firm" } | null {
  if (f.stance === "contrary") return { label: "Points the other way", tone: "contrary" };
  if (f.weak) return { label: "Weak signal", tone: "weak" };
  return f.confidence ? { label: CONFIDENCE_LABEL[f.confidence], tone: "firm" } : null;
}

function Pill({ label, tone, testID }: { label: string; tone: "contrary" | "weak" | "firm"; testID: string }) {
  const s = useStyles();
  const { colors } = useTheme();
  const t = {
    contrary: { bg: colors.ears_upTint, fg: colors.ears_upText, Icon: CircleAlert },
    weak: { bg: colors.unknownTint, fg: colors.onSurfaceSecondary, Icon: CircleAlert },
    firm: { bg: colors.groupAccountsTint, fg: colors.groupAccounts, Icon: CircleCheck },
  }[tone];
  return (
    <View style={[s.pill, { backgroundColor: t.bg }]} testID={testID}>
      <t.Icon size={13} color={t.fg} />
      <Text style={[s.pillText, { color: t.fg }]}>{label}</Text>
    </View>
  );
}

function Meta({ label, value, testID }: { label: string; value: string; testID?: string }) {
  const s = useStyles();
  return <Text style={s.meta} selectable testID={testID}><Text style={s.metaLabel}>{`${label}: `}</Text>{value}</Text>;
}

/** One fact. Only the summary is the button, so the detail opened under it keeps its own links. */
function FactCard({ fact, index }: { fact: FactPiece; index: number }) {
  const s = useStyles();
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  const testID = `tc-evidence-fact-${index}`;
  const mark = factMark(fact);
  const line = provenanceLine(fact);
  const IconEl: Icon = fact.device ? Shield : Search;
  return (
    <View style={[s.fact, fact.stance === "contrary" && s.factContrary]} testID={testID}>
      <Pressable style={({ pressed }) => [s.row, { opacity: pressed ? 0.85 : 1 }]} onPress={() => setOpen((v) => !v)}
        accessibilityRole="button" accessibilityState={{ expanded: open }}
        accessibilityLabel={[fact.text, mark?.label, line].filter(Boolean).join(". ")}
        accessibilityHint={open ? "Hides how this was found" : "Shows how this was found"} testID={`${testID}-toggle`}>
        <View style={[s.rowIcon, { backgroundColor: fact.device ? colors.restingTint : colors.groupDataTint }]}>
          <IconEl size={18} color={fact.device ? colors.restingText : colors.groupData} />
        </View>
        <View style={s.rowBody}>
          <View style={s.rowTop}>
            <Text style={s.factText} selectable testID={`${testID}-text`}>{fact.text}</Text>
            {open ? <ChevronDown size={18} color={colors.muted} /> : <ChevronRight size={18} color={colors.muted} />}
          </View>
          {mark ? <Pill label={mark.label} tone={mark.tone} testID={`${testID}-mark`} /> : null}
          {/* Left out, never guessed, when the record doesn't say who found it. */}
          {line ? <Text style={s.provenance} testID={`${testID}-found-by`}>{line}</Text> : null}
        </View>
      </Pressable>
      {open ? (
        <View style={s.detail} testID={`${testID}-detail`}>
          {fact.basis ? <Meta label="How it was found" value={fact.basis} /> : null}
          {fact.confidence ? <Meta label="Confidence" value={`${fact.confidence[0].toUpperCase()}${fact.confidence.slice(1)}`} /> : null}
          {fact.basedOn.length ? <Meta label="Based on" value={fact.basedOn.join(", ")} /> : null}
          {fact.details.map((d, i) => <Meta key={`${d.label}-${i}`} label={d.label} value={d.value} />)}
          {fact.raisedBy.map((r, i) => <Meta key={`${i}-${r.text}`} label={RAISED_LABEL[r.from]} value={r.text} />)}
          {fact.at ? <Meta label="Recorded" value={formatDateTime(fact.at)} /> : null}
          {fact.simulated ? <Text style={s.meta}>A preview result: simulated, not a real check.</Text> : null}
          {fact.sources.map((src, i) => (
            <Pressable key={`${src.url}-${i}`} onPress={() => void Linking.openURL(src.url)} accessibilityRole="link" testID={`${testID}-source-${i}`}>
              <Text style={s.link}>{`Source: ${src.title}`}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
    </View>
  );
}

function Trail({ stages }: { stages: TrailStage[] }) {
  const s = useStyles();
  const { colors } = useTheme();
  const tone = {
    done: { bg: colors.surfaceSecondary, fg: colors.groupAccounts },
    escalated: { bg: colors.ears_upTint, fg: colors.ears_upText },
    failed: { bg: colors.barkingTint, fg: colors.barkingText },
    pending: { bg: colors.surfaceSecondary, fg: colors.muted },
  };
  return (
    <View style={s.trail} testID="tc-evidence-trail-stages">
      {stages.map((stage, i) => {
        const triage = stage.id === "triage" && stage.tone === "done";
        const t = triage ? { bg: colors.restingTint, fg: colors.restingText } : tone[stage.tone];
        const IconEl = triage ? CircleCheck : stage.tone === "failed" ? CircleAlert : Search;
        return (
          <React.Fragment key={stage.id}>
            {i ? <View style={s.arrow}><ChevronRight size={14} color={colors.muted} /></View> : null}
            <View style={[s.stage, { backgroundColor: t.bg }]} testID={`tc-evidence-trail-${stage.id}`}>
              <IconEl size={16} color={t.fg} />
              <View style={s.stageText}>
                <Text style={s.stageName}>{stage.name}</Text>
                <Text style={s.stageMeta}>{stage.at ? heroWhen(stage.at) : "Time not recorded"}</Text>
                <Text style={s.stageMeta} testID={`tc-evidence-trail-${stage.id}-status`}>{stage.status}</Text>
              </View>
            </View>
          </React.Fragment>
        );
      })}
    </View>
  );
}

export function CaseEvidenceTab({ event, investigation, facts, footer }: {
  event: PatrolEvent; investigation: DeviceInvestigation | null;
  /** What Higgins Triage / Apollo recorded about the item. */
  facts: string[];
  /** Copy facts & sources · Share. */
  footer: React.ReactNode;
}) {
  const s = useStyles();
  const { colors } = useTheme();
  const caseId = event.investigation_case_id ?? event.patrol_record?.investigationCaseId ?? null;
  const di = useDiTransactions(caseId);
  const ev = useMemo(() => caseEvidence({ event, investigation, trace: di.trace, records: di.records, facts }),
    [event, investigation, di.trace, di.records, facts]);
  const running = !!caseId && !event.investigation_completed_at;

  return (
    <View style={s.content} testID="tc-evidence-tab">
      {/* 1. The facts, strongest first. */}
      {ev.facts.length ? ev.facts.map((f, i) => <FactCard key={f.id} fact={f} index={i} />) : (
        <View style={s.card} testID="tc-evidence-empty">
          <Text style={s.empty} testID={!running && ev.messageNotSaved ? "tc-evidence-not-saved" : undefined}>
            {running ? "Higgins is still investigating. The evidence appears here as it is established."
              : ev.messageNotSaved ? "The message wasn't saved with this investigation, so there was nothing to examine. To investigate it, check the message again."
                : "No material evidence was recorded for this case."}
          </Text>
        </View>
      )}

      {/* 2. The original, as it arrived — the item itself, made inert, not a fact about it. */}
      <EvidenceArtefactCard caseKeys={[event.event_id, event.investigation_case_id, event.patrol_record?.investigationCaseId]}
        packTitle={event.headline} packDate={event.occurred_at} phones={event.evidence_phones}
        packSummary={{ overview: event.what_happened || null, findings: event.why ?? [], steps: event.what_to_do ? [event.what_to_do] : [], uncertainties: [] }}
        showMissing testID="tc-evidence-artefact" />
      <CaseEvidenceProfile event={event} />

      {/* 3. Evidence trail — only the stages that happened. */}
      {ev.trail.length ? (
        <View style={s.card} testID="tc-evidence-trail">
          <View style={s.head}>
            <View style={[s.circle, { backgroundColor: colors.groupDataTint }]}><Network size={22} color={colors.groupData} /></View>
            <View style={s.headText}>
              <Text style={s.title}>Evidence trail</Text>
              <Text style={s.sub}>How evidence was used in this investigation</Text>
            </View>
          </View>
          <Trail stages={ev.trail} />
        </View>
      ) : null}

      {footer}
    </View>
  );
}
