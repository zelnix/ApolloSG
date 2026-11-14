/**
 * Threat Case detail screen — shared view for all threats recorded by Apollo/Patrol.
 * Matches the approved Threat Case mock-up. No separate Patrol UI.
 *
 * Tabs: Findings Brief | Evidence | History | DI — the same as an Ask Higgins investigation.
 *
 * Data: PatrolEvent is the primary source. CaseState (Magnum DI) is optional.
 * Only shows states/actions supported by real data.
 */
import { gateCheckResult } from "@/src/domain/gateCheckResult";
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
import { InvestigationView } from "@/src/components/InvestigationView";
import type { CaseState } from "@/src/investigation/caseStore";
import type { InvestigationCase } from "@/src/investigation/types";
import { LIMITED_CAUTION, LIMITED_TODO, plainTriageText } from "@/src/domain/triage/contract";
import { looksLikeInternalCode } from "@/src/domain/messageVoice";
import { FindingsBrief, type BriefStep } from "@/src/components/report/FindingsBrief";
import { investigationVerdict, resultVerdict, riskPill, type BriefVerdict } from "@/src/domain/briefVerdict";
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
import { InvestigationTabBar, type InvestigationTabId } from "@/src/components/InvestigationTabBar";

// ── Styles ───────────────────────────────────────────────────────────────────

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  // Header
  headerRow: { paddingHorizontal: spacing.md, flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingBottom: spacing.xs },
  backBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: fonts.displayBold, fontSize: 16, color: c.onSurface, flex: 1 },
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
  const gate = gateCheckResult(event);
  if (gate) return gate.report;
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
  const gate = gateCheckResult(event);
  if (gate) return { label: gate.label, tone: "sniffing", risk: null, status: statusPill };
  const limited = event.triage_investigation?.outcome === "LIMITED_UNABLE_TO_DETERMINE" && !incompleteOnly(event);
  return { label: STATUS_LABELS[status], tone: limited ? "sniffing" : recordedTone(event.state), risk: limited ? null : riskPill(event.state), caution: limited ? LIMITED_CAUTION : null };
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

// ── CaseState builder for tabsOnly InvestigationView ────────────────────────

function threatCaseState(event: PatrolEvent, investigation: DeviceInvestigation | null): CaseState {
  const caseId = event.investigation_case_id ?? event.patrol_record?.investigationCaseId ?? null;
  // Device-local display projection only. Empty retention fields are not server retention claims.
  const validGates: InvestigationCase["gates"] = investigation?.gates.filter(
    (g): g is InvestigationCase["gates"][number] =>
      ["site", "link", "text", "call", "network", "account", "email", "app", "file", "device"].includes(g)
  ) ?? [];
  const caseData: InvestigationCase | null = caseId || investigation ? {
    schemaVersion: 1,
    id: investigation?.caseId ?? caseId!,
    revision: 0,
    status: investigation?.response ? "complete" : "partial",
    createdAt: investigation?.createdAt ?? event.occurred_at,
    updatedAt: investigation?.completedAt ?? event.resolved_at ?? event.occurred_at,
    expiresAt: "",
    evidenceExpiresAt: null,
    reportExpiresAt: null,
    retentionClass: "device_projection",
    reportByteSize: 0,
    response: investigation?.response ?? null,
    gates: validGates,
    activeJobId: null,
    pendingDeviceRequestIds: [],
    inventory: { total: 0, examined: 0, partial: 0, unavailable: 0, purged: 0, contentExpired: 0 },
    cleanupStatus: "not_due",
    answeredBy: investigation?.answeredBy ?? null,
    settledReason: investigation?.settledReason ?? null,
    simulated: investigation?.simulated,
    origin: investigation?.origin ?? event.origin ?? null,
  } : null;
  return {
    phase: investigation?.response ? "answered" : "answered",
    operationId: null,
    caseData,
    job: null,
    progress: [],
    response: investigation?.response ?? null,
    sources: investigation?.sources ?? [],
    turns: investigation?.turns ?? [],
    failure: null,
    question: null,
    error: null,
    notice: null,
    followUps: [],
  };
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
  // The item itself, as held on this device. Nothing here comes from the server's minimised copy.
  const investigationId = event?.investigation_case_id ?? null;
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
  const verdict = threatVerdict(event, investigation?.response ?? null, status);

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

      {/* Content scrolls naturally — no stickyHeaderIndices which breaks flexDirection: "row" on Android. */}
      <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xl }} testID="tc-scroll">
        {/* What started this case, and when (shared with Ask Higgins) — the result is in Overview. Tagged whenever
            its input or an outside source behind it was simulated. */}
        <View style={{ marginHorizontal: spacing.md, marginBottom: spacing.xs }}>
          <SourceSummaryCard origin={event.origin ?? investigation?.origin} at={event.occurred_at}
            caseKeys={[event.event_id, event.investigation_case_id, event.patrol_record?.investigationCaseId]}
            event={event} evidence={investigation?.evidenceItems} gates={investigation?.gates} simulated={isSimulated(event)} testID="tc-source-summary" />
        </View>

        {/* Tab content — uses the same InvestigationView as Ask Higgins, including its own tab bar */}
        <View style={{ paddingTop: spacing.sm }}>
          <InvestigationView
            state={threatCaseState(event, investigation)}
            tabsOnly
            eventId={event.event_id}
            openingQuestion={false}
            onRetry={() => {}}
            onCancel={() => {}}
            initialEvidence={investigation?.evidenceItems}
            overrideReport={report ?? undefined}
            overrideVerdict={verdict}
            testID="tc-tabs"
          />
        </View>
      </ScrollView>
    </View>
  );
}
