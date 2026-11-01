/**
 * Threat Case detail screen — shared view for all threats recorded by Apollo/Patrol.
 * Matches the approved Threat Case mock-up. No separate Patrol UI.
 *
 * Tabs: Findings Brief | Evidence | History | DI — the same as an Ask Higgins investigation.
 *
 * Data: PatrolEvent is the primary source. CaseState (Magnum DI) is optional.
 * Only shows states/actions supported by real data.
 */
import { incompleteOnly, presentEvent } from "@/src/domain/luddish/present";
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import ChevronLeft from "lucide-react-native/icons/chevron-left";
import React, { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Share, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { EventActions } from "@/src/components/EventActions";
import * as Clipboard from "expo-clipboard";
import { Body, Button, Card } from "@/src/components/ui";
import { scrubMessage } from "@/src/domain/messageVoice";
import {
  threatCaseId,
  threatCaseStatus,
  caseGroupKey,
  STATUS_LABELS,
  STATUS_COLORS,
  formatDateTime,
  isSimulated,
  type ThreatCaseStatus,
} from "@/src/domain/threatCase";
import { caseAuditTrail, type AuditTone } from "@/src/domain/caseAuditTrail";
import type { PatrolEvent } from "@/src/domain/types";
import type { HigginsResponse } from "@/src/investigation/types";
import { threatResult } from "@/src/domain/caseBriefing";
import { hasRecordedFindings } from "@/src/domain/caseFacts";
import { buildCaseSources, type CaseSource } from "@/src/domain/caseSources";
import { buildEvidencePack } from "@/src/domain/evidencePack";
import { DiReport, useDiTransactions } from "@/src/components/DiReport";
import { recheckPlan } from "@/src/domain/recheckPlan";
import { CaseEvidenceTab } from "@/src/components/report/CaseEvidenceTab";
import { LIMITED_CAUTION, LIMITED_TODO, plainTriageText } from "@/src/domain/triage/contract";
import { looksLikeInternalCode } from "@/src/domain/messageVoice";
import { FindingsBrief, type BriefStep } from "@/src/components/report/FindingsBrief";
import { investigationVerdict, resultVerdict, riskPill, type BriefVerdict } from "@/src/domain/briefVerdict";
import { OutcomeExplainerLink } from "@/src/components/OutcomeExplainerLink";
import { SourceSummaryCard } from "@/src/components/report/SourceSummaryCard";
import { RelatedCases } from "@/src/components/report/RelatedCases";
import { ServerCopyNote } from "@/src/components/ServerCopyNote";
import { buildReport, plainReport, shownPlainEnglish, stepText, type Report } from "@/src/domain/reportSections";
import { luddishReport } from "@/src/domain/luddish";
import { involvedIn, type FamilySummary } from "@/src/domain/familySummary";
import { ShareWithFamily } from "@/src/components/ShareWithFamily";
import { FamilyNotes } from "@/src/components/FamilyNotes";
import { comparableChecks, compareDeviceChecks, type DeviceCheckProgress } from "@/src/domain/deviceCheckProgress";
import { getInvestigation, type DeviceInvestigation } from "@/src/investigation/deviceStore";
import { getCaseOriginal, getOriginalSource, type OriginalSource } from "@/src/store/originalSource";
import { markCaseSeen } from "@/src/store/seenCases";
import { goBackOrHome } from "@/src/utils/navigation";
import { useApollo } from "@/src/store/ApolloContext";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";

type TabKey = "overview" | "evidence" | "history" | "di";
const TAB_LABELS: { id: TabKey; label: string }[] = [
  { id: "overview", label: "Findings Brief" },
  { id: "evidence", label: "Evidence" },
  { id: "history", label: "History" },
  { id: "di", label: "DI" },
];

// ── Styles ───────────────────────────────────────────────────────────────────

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  // Header
  headerRow: { paddingHorizontal: spacing.md, flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingBottom: spacing.xs },
  backBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 16, color: c.onSurface, flex: 1 },
  // Tab bar — matches InvestigationView's working horizontal layout
  tabBar: { flexDirection: "row" as const, borderBottomWidth: 1, borderBottomColor: c.border, backgroundColor: c.surfaceSecondary },
  tab: { flexGrow: 1, flexBasis: "auto" as const, paddingVertical: 12, paddingHorizontal: spacing.sm, alignItems: "center" as const, borderBottomWidth: 2, borderBottomColor: "transparent" },
  tabActive: { borderBottomColor: c.brandPrimary },
  tabText: { fontFamily: fonts.textMedium, fontSize: 14, color: c.muted },
  tabTextActive: { color: c.onSurface, fontFamily: fonts.textSemibold },
  // Content
  content: { paddingHorizontal: spacing.md, gap: spacing.md, paddingBottom: spacing.xl },
  // Repeat checks
  reportLabel: { fontFamily: fonts.textSemibold, fontSize: 12, letterSpacing: 0.5, color: c.onSurfaceSecondary, textTransform: "uppercase", marginTop: spacing.xs },
  reportBody: { fontFamily: fonts.text, fontSize: 14, lineHeight: 20, color: c.onSurface },
  sectionTitle: { fontFamily: fonts.displayBold, fontSize: 15, color: c.onSurface, marginTop: spacing.sm },
  // Evidence
  evidenceSection: { borderWidth: 1, borderColor: c.border, borderRadius: radius.lg, overflow: "hidden" },
  evidenceHeader: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md, backgroundColor: c.surfaceSecondary },
  evidenceHeaderIcon: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  evidenceHeaderText: { flex: 1 },
  evidenceHeaderTitle: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.onSurface },
  evidenceHeaderSub: { fontFamily: fonts.text, fontSize: 12, color: c.muted },
  evidenceBody: { padding: spacing.md, gap: spacing.sm },
  evidenceFieldRow: { flexDirection: "row", gap: spacing.sm },
  evidenceFieldLabel: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.onSurfaceSecondary, width: 72 },
  evidenceFieldValue: { fontFamily: fonts.text, fontSize: 13, color: c.onSurface, flex: 1, lineHeight: 19 },
  evidenceOriginalContent: { backgroundColor: c.surfaceTertiary, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: c.border },
  evidenceOriginalText: { fontFamily: fonts.text, fontSize: 14, lineHeight: 22, color: c.onSurface },
  evidenceLink: { fontFamily: fonts.textMedium, fontSize: 14, color: c.brandPrimary },
  // Collapsible section
  collapseHeader: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md, borderTopWidth: 1, borderTopColor: c.divider },
  collapseIcon: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  collapseTitle: { fontFamily: fonts.textSemibold, fontSize: 15, color: c.onSurface, flex: 1 },
  collapseSub: { fontFamily: fonts.text, fontSize: 12, color: c.muted },
  collapseBody: { paddingHorizontal: spacing.md, paddingBottom: spacing.md, gap: spacing.sm },
  // Timeline
  timelineRow: { flexDirection: "row", gap: spacing.md, minHeight: 60 },
  timelineDotCol: { width: 20, alignItems: "center" },
  timelineDot: { width: 12, height: 12, borderRadius: 6, marginTop: 4 },
  timelineLine: { width: 2, flex: 1, backgroundColor: "rgba(107,114,128,0.2)", marginTop: 4 },
  timelineContent: { flex: 1, paddingBottom: spacing.md },
  timelineTime: { fontFamily: fonts.text, fontSize: 11, color: c.muted, marginBottom: 2 },
  timelineTitle: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface },
  timelineDesc: { fontFamily: fonts.text, fontSize: 13, color: c.onSurfaceSecondary, lineHeight: 19 },
  timelineInProgress: { fontFamily: fonts.textMedium, fontSize: 12, color: c.muted, fontStyle: "italic" },
  // Related items
  relatedSub: { fontFamily: fonts.text, fontSize: 13, color: c.muted },
  // Provenance note
  provenanceNote: { fontFamily: fonts.text, fontSize: 11, color: c.muted, fontStyle: "italic", marginTop: spacing.xs },
}));

// ── Findings Brief Tab ───────────────────────────────────────────────────────

/** Higgins' report for a threat, built exactly as Ask Higgins builds it: each fact once. A threat Apollo recorded on
 *  its own (no investigation) uses what it recorded instead. The Findings Brief shows the result; DI shows "how". */
function threatReport(event: PatrolEvent, investigation: DeviceInvestigation | null): Report {
  const response = investigation?.response ?? null;
  if (response) {
    // Higgins' plain English when it passed its Fidelity Check; otherwise Apollo's own wording.
    const plain = shownPlainEnglish(response);
    if (plain) return plainReport(plain, investigation?.sources, response.sourceIds, investigation?.evidenceItems);
    return buildReport({
      overview: scrubMessage(response.overview), explanationMarkdown: scrubMessage(response.explanationMarkdown), attentionReason: response.attentionReason,
      findings: response.findings, uncertainties: response.uncertainties, scope: response.scope,
      sources: investigation?.sources, sourceIds: response.sourceIds, alreadySaid: [investigation?.settledReason?.sentence],
      evidence: investigation?.evidenceItems,
    });
  }
  const briefing = event.patrol_record?.higginsBriefing;
  // Checks that couldn't run aren't a caution: only a Limited result with a concerning sign is.
  const limited = event.triage_investigation?.outcome === "LIMITED_UNABLE_TO_DETERMINE" && !incompleteOnly(event);
  const headline = (event.headline || "").trim();
  const established = plainTriageText((briefing?.established ?? event.what_happened ?? "").trim());
  return buildReport({
    overview: established || (headline && !looksLikeInternalCode(headline) ? plainTriageText(headline) : ""),
    fallbackFound: [...(event.why ?? []), ...(briefing?.evidence_points ?? [])].map(plainTriageText).filter((line) => !!line && !looksLikeInternalCode(line)),
    // A Limited Triage result is never shown as safe or as nothing to worry about.
    fallbackMeans: limited ? LIMITED_CAUTION : briefing?.meaning ?? null,
  });
}

/** The tone of what Apollo recorded on its own, when no investigation answered. */
function recordedTone(state: PatrolEvent["state"]): BriefVerdict["tone"] {
  if (state === "barking" || state === "biting") return "barking";
  if (state === "growling" || state === "ears_up") return "ears_up";
  return state === "resting" ? "resting" : "sniffing";
}

/** The verdict a threat shows: its case result (caseBriefing.threatResult — the investigation's, or the copy its event
 *  carries), read exactly as Ask Higgins reads it, with the case's status beside it. A threat no investigation answered
 *  shows its status and recorded state; Limited is never safe. Home, History, Evidence and DI read the same result. */
function threatVerdict(event: PatrolEvent, response: HigginsResponse | null, status: ThreatCaseStatus): BriefVerdict {
  const statusPill = { label: STATUS_LABELS[status], bg: STATUS_COLORS[status].bg, fg: STATUS_COLORS[status].text };
  const result = threatResult(event, response);
  if (result) return { ...(response ? investigationVerdict(response) : resultVerdict(result)), status: statusPill };
  const limited = event.triage_investigation?.outcome === "LIMITED_UNABLE_TO_DETERMINE" && !incompleteOnly(event);
  return { label: STATUS_LABELS[status], tone: limited ? "sniffing" : recordedTone(event.state), risk: limited ? null : riskPill(event.state), caution: limited ? LIMITED_CAUTION : null };
}

function BriefContent({ event, status, verdict, shownWhatToDo, original, investigation, report }: {
  event: PatrolEvent; status: ThreatCaseStatus; verdict: BriefVerdict; shownWhatToDo: string; original: OriginalSource | null; investigation: DeviceInvestigation | null; report: Report;
}) {
  const s = useStyles();
  const response = investigation?.response ?? null;
  const limited = !response && event.triage_investigation?.outcome === "LIMITED_UNABLE_TO_DETERMINE" && !incompleteOnly(event);

  // What to do — the investigation's own steps, or an explicit statement that nothing needs doing.
  const action = (shownWhatToDo || "").trim();
  const noAction = !action || /^no action required\.?$/i.test(action) || (limited && /^(nothing to (do|worry)|no action)/i.test(action));
  const note = event.resolved_at
    ? "Nothing to do — this case is closed."
    : status === "investigating"
      ? "Nothing to do right now. I'll tell you as soon as the investigation finishes."
      : null;
  const steps: BriefStep[] = !note && response?.actions.length
    ? response.actions.map((a, i) => ({ id: a.id, text: stepText(response, i) || a.label }))
    : [{ id: "todo", text: note ?? (noAction ? (limited ? LIMITED_TODO : "Nothing to do.") : plainTriageText(action)) }];
  // "Send to family": the result, what happened, what to do and the website or number — nothing else.
  const summary: FamilySummary = {
    eventId: event.event_id, state: event.state, result: verdict.label ?? STATUS_LABELS[status],
    headline: presentEvent(event).title || (report.answer[0] ?? "A threat Apollo found"),
    whatHappened: report.answer.join(" ").trim(),
    whatToDo: scrubMessage(note ?? (noAction ? "Nothing to do." : action)).trim(),
    involved: involvedIn(event), caseRef: threatCaseId(event), occurredAt: event.occurred_at,
  };

  return (
    <View style={s.content} testID="tc-overview-briefing">
      {/* The Findings Brief — the same component as Ask Higgins. */}
      <FindingsBrief report={report} verdict={verdict} steps={steps} ids="tc-overview" />
      {response?.outcome ? <OutcomeExplainerLink outcome={response.outcome} testID="tc-overview-outcome-explainer" /> : null}

      <FamilyNotes eventId={event.event_id} />

      <ShareWithFamily summary={summary} when={formatDateTime(event.occurred_at)} />

      {/* Actions */}
      {event.resolved_at ? <ReopenCase event={event} /> : <EventActions event={event} hideAsk />}
      {!event.resolved_at && event.reopened_at ? <RecheckCase event={event} /> : null}

      {/* Repeat checks of this device: one case, every check listed. */}
      {event.case_key ? <CaseCheckRuns event={event} original={original} /> : null}

      {/* Cases on this device Apollo connected to this one, and what was previously encountered. */}
      <RelatedCases event={event} response={response} ids="tc" />
    </View>
  );
}

const CHANGE_PREFIX: Record<string, string> = { fixed: "Fixed", new_problem: "New", still_open: "Still open", not_confirmed: "Not confirmed" };

/** Repeat checks on the same subject are ONE case. This restates how many checks have been filed
 *  against it, what changed since the previous check, and lets the person open any earlier check.
 *  Nothing is re-analysed here — every line comes from what each check recorded at the time. */
function CaseCheckRuns({ event, original }: { event: PatrolEvent; original: OriginalSource | null }) {
  const s = useStyles();
  const router = useRouter();
  const { events } = useApollo();
  const runs = events
    .filter((e) => caseGroupKey(e) === caseGroupKey(event))
    .sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at));
  const index = runs.findIndex((e) => e.event_id === event.event_id);
  const previousRun = index >= 0 ? runs[index + 1] ?? null : null;

  // What changed since the check immediately before this one — compared from what each check
  // actually recorded. Nothing is compared when the earlier check kept no comparable results.
  const [progress, setProgress] = useState<DeviceCheckProgress | null>(null);
  useEffect(() => {
    let live = true;
    const current = comparableChecks(original?.data);
    if (!previousRun || !current) { setProgress(null); return; }
    void getOriginalSource(previousRun.event_id)
      .then((prior) => {
        const before = comparableChecks(prior?.data);
        if (live) setProgress(before ? compareDeviceChecks(before, current) : null);
      })
      .catch(() => { if (live) setProgress(null); });
    return () => { live = false; };
  }, [previousRun, original]);

  if (runs.length < 2) return null;
  const earlier = runs.filter((e) => e.event_id !== event.event_id).slice(0, 5);

  return (
    <Card style={{ gap: spacing.xs }} testID="tc-overview-runs">
      <Text style={s.sectionTitle}>Checks on this case</Text>
      <Text style={s.reportBody} testID="tc-overview-runs-count">
        Checked {runs.length} times · last checked {formatDateTime(runs[0].occurred_at)}
      </Text>
      {progress ? (
        <View style={{ gap: spacing.xs, marginTop: spacing.xs }} testID="tc-overview-runs-progress">
          <Text style={s.reportLabel}>Since the check before this one</Text>
          <Text style={s.reportBody} testID="tc-overview-runs-progress-summary">{progress.summary}</Text>
          {progress.changes.map((change) => (
            <Text key={change.id} style={s.relatedSub} testID={`tc-overview-runs-change-${change.id}`}>
              {CHANGE_PREFIX[change.kind]} — {change.title}: {change.detail}
            </Text>
          ))}
        </View>
      ) : null}
      {earlier.map((run) => (
        <Pressable
          key={run.event_id}
          testID={`tc-overview-run-${run.event_id}`}
          accessibilityRole="button"
          accessibilityLabel={`Open the check from ${formatDateTime(run.occurred_at)}`}
          onPress={() => router.push(`/patrol/${encodeURIComponent(run.event_id)}`)}
          style={({ pressed }) => [{ paddingVertical: spacing.xs, opacity: pressed ? 0.7 : 1 }]}
        >
          <Text style={s.relatedSub}>{formatDateTime(run.occurred_at)} — {run.headline}</Text>
        </Pressable>
      ))}
    </Card>
  );
}

/** After a reopen, Apollo can look again. This re-runs the same pipeline — detection → Triage →
 *  Magnum DI if Triage escalates — and opens the fresh result, or sends the person to the Gate that
 *  performs the live read. It never pretends to re-check something it can no longer see. */
function RecheckCase({ event }: { event: PatrolEvent }) {
  const s = useStyles();
  const router = useRouter();
  const { checkLink, checkMessage, checkNumberRisk, showToast } = useApollo();
  const [busy, setBusy] = useState(false);
  const plan = recheckPlan(event);

  const openResult = (fresh: PatrolEvent | null, nothingFound: string) => {
    if (fresh) router.replace(`/patrol/${encodeURIComponent(fresh.event_id)}`);
    else showToast(nothingFound, "neutral");
  };

  const run = async () => {
    setBusy(true);
    try {
      if (plan.kind === "link") {
        // The same link is re-triaged in THIS case: its evidence level, history and earlier results stay with it.
        const outcome = await checkLink(plan.url, event.scent_id ?? undefined, { via: "recheck", upgradeEventId: event.event_id });
        if (outcome.notice) showToast(outcome.notice, "neutral");
        openResult(outcome.event, "ApolloSG re-checked the website and found nothing to flag this time.");
      } else if (plan.kind === "message") {
        const original = await getCaseOriginal([event.event_id, event.investigation_case_id]).catch(() => null);
        const text = (original?.text ?? "").trim();
        if (!text) {
          showToast("ApolloSG can't re-check this one here — the original message isn't stored with this case. Open the Text or Email check and submit it again.", "growling");
          return;
        }
        const from = original?.fields?.find((f) => /from|sender/i.test(f.label))?.value ?? event.source_metadata?.sender ?? "";
        const outcome = await checkMessage(from, text, { via: "recheck", upgradeEventId: event.event_id });
        openResult(outcome.event, "ApolloSG re-checked the message and found nothing to flag this time.");
      } else if (plan.kind === "number") {
        const risk = await checkNumberRisk(plan.number, undefined, { deliberate: true, via: "recheck" });
        showToast(`Re-check complete: ${risk.higgins.headline}`, "neutral");
      }
    } catch (error) {
      showToast(`ApolloSG couldn't finish the re-check (${error instanceof Error ? error.message : "reason not recorded"}).`, "growling");
    } finally {
      setBusy(false);
    }
  };

  if (plan.kind === "none") {
    return <Text style={s.provenanceNote} testID="tc-recheck-unavailable">{plan.reason}</Text>;
  }

  if (plan.kind === "gate") {
    return (
      <View style={{ gap: spacing.xs }}>
        <Button testID="tc-recheck" variant="secondary" label={plan.label} onPress={() => router.push(plan.route as never)} />
        <Text style={s.provenanceNote}>{plan.note}</Text>
      </View>
    );
  }

  return (
    <View style={{ gap: spacing.xs }}>
      <Button testID="tc-recheck" variant="secondary" label={busy ? "Re-checking…" : plan.label} disabled={busy} onPress={() => void run()} />
      <Text style={s.provenanceNote}>
        Apollo runs the whole check again — his own checks first, and a Magnum DI investigation only if those find a possible threat. The result opens as a fresh case.
      </Text>
    </View>
  );
}

function ReopenCase({ event }: { event: PatrolEvent }) {
  const s = useStyles();
  const { reopenEvent } = useApollo();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!confirm) return <Button testID="tc-reopen-button" variant="secondary" label="Reopen case" onPress={() => setConfirm(true)} />;
  return (
    <Card style={{ gap: spacing.sm }} testID="tc-reopen-confirm">
      <Text style={s.provenanceNote}>Reopen this case? It will show as active again so you can act on it.</Text>
      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        <View style={{ flex: 1 }}><Button testID="tc-reopen-cancel" variant="secondary" label="Cancel" onPress={() => setConfirm(false)} disabled={busy} /></View>
        <View style={{ flex: 1 }}><Button testID="tc-reopen-yes" label={busy ? "Reopening…" : "Reopen"} disabled={busy}
          onPress={async () => { setBusy(true); try { await reopenEvent(event); } finally { setBusy(false); setConfirm(false); } }} /></View>
      </View>
    </Card>
  );
}

// ── Sources used ─────────────────────────────────────────────────────────────

/** Loads the saved Magnum DI investigation for this case, when there is one. */
function useCaseInvestigation(event: PatrolEvent | undefined): DeviceInvestigation | null {
  const caseId = event?.investigation_case_id ?? event?.patrol_record?.investigationCaseId ?? null;
  const [inv, setInv] = useState<DeviceInvestigation | null>(null);
  useEffect(() => {
    if (!caseId) { setInv(null); return; }
    getInvestigation(caseId).then(setInv).catch(() => setInv(null));
  }, [caseId]);
  return inv;
}

/** One-tap copy or share of the recorded facts + sources, for a bank, the police or family. */
function EvidencePackButton({ event, facts, sources }: { event: PatrolEvent; facts: string[]; sources: CaseSource[] }) {
  const { showToast } = useApollo();
  const [copied, setCopied] = useState(false);
  const pack = () => buildEvidencePack({ event, facts, sources });
  const copy = async () => {
    try {
      await Clipboard.setStringAsync(pack());
      setCopied(true);
      showToast("Facts and sources copied. Paste them into an email, message or report.", "neutral");
    } catch {
      showToast("ApolloSG couldn't copy to the clipboard on this device.", "growling");
    }
  };
  const share = async () => {
    try {
      await Share.share({ message: pack(), title: `Apollo Threat Case ${threatCaseId(event)}` });
    } catch {
      showToast("ApolloSG couldn't open the share sheet on this device.", "growling");
    }
  };
  return (
    <View style={{ flexDirection: "row", gap: spacing.sm }}>
      <View style={{ flex: 1 }}>
        <Button
          testID="tc-evidence-pack"
          variant="secondary"
          label={copied ? "Copied — facts & sources" : "Copy facts & sources"}
          onPress={() => void copy()}
        />
      </View>
      <View style={{ flex: 1 }}>
        <Button
          testID="tc-evidence-share"
          variant="secondary"
          label="Share"
          onPress={() => void share()}
        />
      </View>
    </View>
  );
}

/** The Evidence tab: the case's material facts, strongest first, each with who found and confirmed it → the original,
 *  as it arrived (inert) → Evidence trail → Copy / Share (components/report/CaseEvidenceTab, built from
 *  domain/caseEvidence). Nothing is reconstructed from Magnum prose or Higgins' explanation. */
function EvidenceContent({ event, investigation }: { event: PatrolEvent; investigation: DeviceInvestigation | null }) {
  // The recorded facts of the finding — what Apollo found, never why it matters: the finding statement itself,
  // Apollo's recorded signals, and evidence the deterministic Triage investigation actually captured. Checks that
  // didn't finish aren't findings: they're listed on the item, each with its recorded reason.
  const observedFacts = useMemo(() => Array.from(new Set([
    (event.headline || "").trim(),
    ...(event.why ?? []).map((w) => w.trim()),
    ...(event.triage_investigation?.rules ?? [])
      .filter((r) => r.result === "met")
      .flatMap((r) => r.evidence)
      .map((e) => plainTriageText(e.trim())),
  ].filter((line) => !!line && !looksLikeInternalCode(line) && !/^(Couldn't check|Not completed):/.test(line)))), [event]);
  const sources = buildCaseSources({ event, investigation });
  return (
    <CaseEvidenceTab event={event} investigation={investigation} facts={observedFacts}
      footer={<EvidencePackButton event={event} facts={observedFacts} sources={sources} />} />
  );
}

// ── History Tab ──────────────────────────────────────────────────────────────

function HistoryContent({ event, investigation: inv, verdict }: { event: PatrolEvent; investigation: DeviceInvestigation | null; verdict: string | null }) {
  const s = useStyles();
  const { colors } = useTheme();
  const di = useDiTransactions(event.investigation_case_id ?? event.patrol_record?.investigationCaseId ?? null);
  // Only what this case recorded, oldest first (domain/caseAuditTrail). Sources are on Evidence; related cases on the Findings Brief.
  const trail = useMemo(() => caseAuditTrail({ event, investigation: inv, trace: di.trace, records: di.records, verdict }),
    [event, inv, di.trace, di.records, verdict]);
  const dot: Record<AuditTone, string> = {
    start: colors.brandPrimary, check: colors.sniffingText, escalated: colors.ears_upText, done: colors.restingText,
    warning: colors.barkingText, closed: colors.muted,
  };

  return (
    <View style={s.content}>
      <Card style={{ gap: 0 }} testID="tc-history-timeline">
        {trail.map((entry, i) => (
          <View key={entry.id} style={s.timelineRow} testID={`tc-history-${entry.id}`}>
            <View style={s.timelineDotCol}>
              <View style={[s.timelineDot, { backgroundColor: dot[entry.tone] }]} />
              {i < trail.length - 1 ? <View style={s.timelineLine} /> : null}
            </View>
            <View style={s.timelineContent}>
              {entry.at ? (
                <Text style={s.timelineTime}>{formatDateTime(entry.at)}</Text>
              ) : (
                <Text style={s.timelineInProgress}>{entry.pending ? "In progress" : "Time not recorded"}</Text>
              )}
              <Text style={s.timelineTitle}>{entry.title}</Text>
              <Text style={s.timelineDesc}>{entry.description}</Text>
            </View>
          </View>
        ))}
        {/* When the files sent for this result leave Apollo's server. */}
        {inv?.response ? <ServerCopyNote caseId={inv.caseId} testID="tc-history-server-copy" /> : null}
      </Card>
    </View>
  );
}

// ── Main Screen ──────────────────────────────────────────────────────────────

export default function ThreatCaseScreen() {
  const s = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { id, focus } = useLocalSearchParams<{ id: string; focus?: string }>();
  const { events, ready, setupDone, casesSyncing } = useApollo();
  const event = events.find((e) => e.event_id === id);
  const investigation = useCaseInvestigation(event);
  const report = useMemo(() => (event ? threatReport(event, investigation) : null), [event, investigation]);
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  // The item itself, as held on this device. Nothing here comes from the server's minimised copy.
  const [original, setOriginal] = useState<OriginalSource | null>(null);
  const investigationId = event?.investigation_case_id ?? null;
  useEffect(() => {
    let active = true;
    if (!id) return;
    void getCaseOriginal([id, investigationId]).then((o) => { if (active) setOriginal(o); }).catch(() => undefined);
    return () => { active = false; };
  }, [id, investigationId]);
  // Opening a case clears its "New" mark.
  const openedId = event?.event_id;
  useEffect(() => { if (openedId) void markCaseSeen(openedId); }, [openedId]);

  if (ready && !setupDone) return <Redirect href="/onboarding" />;

  if (!event) {
    return (
      <View style={s.root}>
        <View style={[s.headerRow, { paddingTop: insets.top + spacing.sm }]}>
          <Pressable onPress={() => goBackOrHome(router)} style={s.backBtn}><ChevronLeft size={24} color={colors.onSurface} /></Pressable>
          <Text style={s.headerTitle}>Threat Case</Text>
        </View>
        {casesSyncing || !ready ? (
          <View style={[s.content, { alignItems: "center", gap: spacing.sm }]} testID="tc-loading">
            <ActivityIndicator color={colors.brand} />
            <Body>Getting this case…</Body>
          </View>
        ) : <View style={s.content}><Body>This threat case is no longer available.</Body></View>}
      </View>
    );
  }

  const caseId = threatCaseId(event);
  const status = threatCaseStatus(event);
  // One result for every tab: the Findings Brief, Evidence, History and DI all read this.
  const result = threatResult(event, investigation?.response ?? null);
  const verdict = threatVerdict(event, investigation?.response ?? null, status);

  const hasInvestigation = !!(event.investigation_case_id ?? event.patrol_record?.investigationCaseId);
  const hasSubstantiveData = !!(event.what_happened && event.what_happened.length > 30);
  const hasBriefing = !!event.patrol_record?.higginsBriefing;
  const isIncomplete = !hasRecordedFindings(event) && !hasInvestigation && !hasSubstantiveData && !hasBriefing;
  // Apollo's step, through the shared Luddish contract (an incomplete check says so, never "treat with caution").
  const shownWhatToDo = !isIncomplete && presentEvent(event).whatToDo
    ? presentEvent(event).whatToDo
    : event.patrol_record?.higginsBriefing?.action ?? "Review the investigation details for recommended next steps.";

  return (
    <View style={s.root}>
      {/* Header: back + Threat Case ID + status pill */}
      <View style={[s.headerRow, { paddingTop: insets.top + spacing.sm }]}>
        <Pressable testID="tc-back" onPress={() => goBackOrHome(router)} style={s.backBtn}>
          <ChevronLeft size={24} color={colors.onSurface} />
        </Pressable>
        <Text style={s.headerTitle} testID="tc-case-id">
          Threat Case #{caseId}
        </Text>
      </View>

      {/* The top card scrolls away with the content and comes back only at the top; the tab bar stays pinned. */}
      <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xl }} stickyHeaderIndices={[1]} testID="tc-scroll">
        {/* What started this case, and when (shared with Ask Higgins) — the result is in Overview. Tagged whenever
            its input or an outside source behind it was simulated. */}
        <View style={{ marginHorizontal: spacing.md, marginBottom: spacing.xs }}>
          <SourceSummaryCard origin={event.origin ?? investigation?.origin} at={event.occurred_at}
            caseKeys={[event.event_id, event.investigation_case_id, event.patrol_record?.investigationCaseId]}
            event={event} evidence={investigation?.evidenceItems} gates={investigation?.gates} simulated={isSimulated(event)} testID="tc-source-summary" />
        </View>

        {/* Tab bar */}
        <View style={s.tabBar} testID="tc-tab-bar">
          {TAB_LABELS.map(({ id: tabId, label }) => (
            <Pressable key={tabId} style={[s.tab, activeTab === tabId && s.tabActive]} onPress={() => setActiveTab(tabId)} accessibilityRole="tab" accessibilityState={{ selected: activeTab === tabId }} testID={`tc-tab-${tabId}`}>
              <Text style={[s.tabText, activeTab === tabId && s.tabTextActive]} numberOfLines={1}>{label}</Text>
            </Pressable>
          ))}
        </View>

        {/* Tab content */}
        <View style={{ paddingTop: spacing.sm }}>
        {activeTab === "overview" && report ? (
          <BriefContent event={event} status={status} verdict={verdict} shownWhatToDo={shownWhatToDo} original={original} investigation={investigation} report={report} />
        ) : activeTab === "evidence" ? (
          <EvidenceContent event={event} investigation={investigation} />
        ) : activeTab === "history" ? (
          <HistoryContent event={event} investigation={investigation} verdict={result ? verdict.label : null} />
        ) : activeTab === "di" ? (
          <DiReport caseId={event.investigation_case_id ?? event.patrol_record?.investigationCaseId ?? null} triage={event.triage_investigation ?? null}
            settledReason={investigation?.response ? investigation.settledReason : null} settledEvent={investigation?.settledReason ? null : event}
            how={report ? luddishReport(report).how : []} presented={result ? { verdict: verdict.label, risk: verdict.risk?.label ?? null } : null}
            history={investigation?.response?.history} response={investigation?.response ?? null} sources={investigation?.sources ?? []} />
        ) : null}
        </View>
      </ScrollView>
    </View>
  );
}
