// Unified Investigation Report, the same as a Threat Case: Findings Brief | Evidence | History | DI, opening on the
// Findings Brief. Apollo detects; Higgins Triage, TC FlyBy and Magnum DI investigate; the Evidence Lock keeps what
// they established; Higgins Luddish explains it. Findings Brief = the result in plain words; Evidence = the original
// material and the sources used; History = what happened when; DI = how it was checked.
import * as FileSystemLegacy from "expo-file-system/legacy";
import * as Clipboard from "expo-clipboard";
import * as Sharing from "expo-sharing";
import * as WebBrowser from "expo-web-browser";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Image, Platform, Pressable, Text, View } from "react-native";
import ChevronDown from "lucide-react-native/icons/chevron-down";
import ChevronRight from "lucide-react-native/icons/chevron-right";
import ChevronUp from "lucide-react-native/icons/chevron-up";
import CircleAlert from "lucide-react-native/icons/circle-alert";
import CircleCheck from "lucide-react-native/icons/circle-check";
import Clock from "lucide-react-native/icons/clock";
import Copy from "lucide-react-native/icons/copy";
import FileText from "lucide-react-native/icons/file-text";
import Globe from "lucide-react-native/icons/globe";
import Info from "lucide-react-native/icons/info";
import Mail from "lucide-react-native/icons/mail";
import MessageSquare from "lucide-react-native/icons/message-square";
import Phone from "lucide-react-native/icons/phone";
import RefreshCw from "lucide-react-native/icons/refresh-cw";
import Search from "lucide-react-native/icons/search";
import { Body, Button, Card } from "@/src/components/ui";
import { API_BASE } from "@/src/api/client";
import { getDeviceToken } from "@/src/auth/deviceIdentity";
import { EvidencePopup } from "@/src/components/EvidencePopup";
import { EvidenceArtefactCard } from "@/src/components/evidence/EvidenceArtefactCard";
import { DiReport, Research, CollapsibleSection } from "@/src/components/DiReport";
import { outsideResearch } from "@/src/domain/diTrace";
import { FindingsBrief, type BriefStep } from "@/src/components/report/FindingsBrief";
import { RelatedCases } from "@/src/components/report/RelatedCases";
import { investigationVerdict } from "@/src/domain/briefVerdict";
import { SourceList } from "@/src/components/report/SourceList";
import { SourceSummaryCard } from "@/src/components/report/SourceSummaryCard";
import { ServerCopyNote } from "@/src/components/ServerCopyNote";
import { PhoneIdentityCard } from "@/src/components/PhoneIdentityCard";
import { callNumberOf } from "@/src/domain/numberDetails";
import { buildReport, plainReport, shownPlainEnglish, stepText } from "@/src/domain/reportSections";
import { luddishReport, luddishText } from "@/src/domain/luddish";
import { investigationHistory, investigatorName, scrubMessage } from "@/src/domain/messageVoice";
import { fonts, makeStyles, radius, spacing, useTheme } from "@/src/theme";
import { InvestigationTabBar, type InvestigationTabId } from "@/src/components/InvestigationTabBar";
import type { CaseState } from "@/src/investigation/caseStore";
import * as investigationApi from "@/src/investigation/client";
import { listLocalReports, saveLocalReport, deleteLocalReport } from "@/src/investigation/localReports";
import { useApollo } from "@/src/store/ApolloContext";
import { getCaseOriginal, subscribeOriginalSource, type OriginalSource } from "@/src/store/originalSource";
import { canResubmit, resubmitLabels, resubmitWaitSeconds } from "@/src/investigation/resubmit";
import type { ActionProposal, EvidenceItem } from "@/src/investigation/types";
import { isExecutable, runAction, type ActionOutcome } from "@/src/settings/actions";
import { onRecheck, retryFailedAttempt } from "@/src/settings/recheck";

// ── Types ────────────────────────────────────────────────────────────────────
// Tab type re-exported from the shared InvestigationTabBar component.

// ── Styles ───────────────────────────────────────────────────────────────────

const useStyles = makeStyles((c) => ({
  // ── Findings Brief tab ──
  briefingText: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurfaceSecondary },

  // ── Action cards ──
  actionCard: { backgroundColor: c.surfaceSecondary, borderRadius: radius.md, borderWidth: 0.25, borderColor: c.border, padding: spacing.lg, flexDirection: "row" as const, alignItems: "center" as const, gap: spacing.md },
  actionIconWrap: { width: 40, height: 40, borderRadius: 20, alignItems: "center" as const, justifyContent: "center" as const },
  actionContent: { flex: 1, gap: 2 },
  actionTitle: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.brandPrimary },
  actionDescription: { fontFamily: fonts.text, fontSize: 12, color: c.muted },
  infoCard: { borderRadius: radius.md, padding: spacing.lg, flexDirection: "row" as const, gap: spacing.md, alignItems: "flex-start" as const },
  infoIconWrap: { width: 28, height: 28, borderRadius: 14, alignItems: "center" as const, justifyContent: "center" as const, marginTop: 2 },
  infoContent: { flex: 1, gap: 4 },
  infoTitle: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface, lineHeight: 20 },
  infoBody: { fontFamily: fonts.text, fontSize: 13, lineHeight: 19, color: c.onSurfaceSecondary },

  // ── Shared content ──
  text: { fontFamily: fonts.text, fontSize: 15, lineHeight: 22, color: c.onSurface },
  muted: { fontFamily: fonts.text, fontSize: 13, lineHeight: 18, color: c.muted },
  sectionTitle: { fontFamily: fonts.textSemibold, fontSize: 11, letterSpacing: 0.4, color: c.muted, textTransform: "uppercase" },
  row: { flexDirection: "row" as const, flexWrap: "wrap" as const, gap: spacing.sm, alignItems: "center" as const },
  source: { paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: c.border },
  link: { fontFamily: fonts.textMedium, fontSize: 14, color: c.brandPrimary },
  question: { backgroundColor: c.surfaceTertiary, borderRadius: radius.md, padding: spacing.md, gap: spacing.xs },
  turn: { gap: spacing.xs, paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: c.border },
  user: { alignSelf: "flex-end" as const, backgroundColor: c.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: c.border, maxWidth: "88%" as const },
  divider: { height: 1, backgroundColor: c.border, marginVertical: spacing.xs },

  // ── Evidence tab ──
  evidenceCard: { gap: spacing.xs, borderColor: c.border, borderWidth: 1, borderRadius: radius.md, padding: spacing.md },
  evidenceLabel: { fontFamily: fonts.textMedium, fontSize: 12, color: c.muted, textTransform: "uppercase", letterSpacing: 0.3 },

  // ── Evidence source header ──
  sourceHeader: { flexDirection: "row" as const, alignItems: "center" as const, gap: spacing.md, paddingBottom: spacing.sm, borderBottomWidth: 1, borderBottomColor: c.border, marginBottom: spacing.sm },
  sourceIconWrap: { width: 40, height: 40, borderRadius: 12, alignItems: "center" as const, justifyContent: "center" as const },
  sourceHeaderInfo: { flex: 1, gap: 2 },
  sourceHeaderTitle: { fontFamily: fonts.displayBold, fontSize: 15, color: c.onSurface },
  sourceHeaderMeta: { fontFamily: fonts.text, fontSize: 12, color: c.muted },
  sourceHeaderMetaBold: { fontFamily: fonts.textSemibold, fontSize: 12, color: c.onSurfaceSecondary },
  sourceContentBlock: { backgroundColor: c.surfaceTertiary, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: c.border },
  sourceContentText: { fontFamily: fonts.text, fontSize: 14, lineHeight: 22, color: c.onSurface },

  // ── History tab ──
  timelineItem: { flexDirection: "row" as const, gap: spacing.md },
  timelineTrack: { alignItems: "center" as const, width: 32 },
  timelineDot: { width: 32, height: 32, borderRadius: 16, alignItems: "center" as const, justifyContent: "center" as const, zIndex: 1 },
  timelineLine: { width: 2, flex: 1, marginTop: -2, marginBottom: -2 },
  timelineContent: { flex: 1, paddingBottom: spacing.lg },
  timelineContentLast: { flex: 1, paddingBottom: spacing.sm },
  timelineRow: { flexDirection: "row" as const, justifyContent: "space-between" as const, alignItems: "flex-start" as const, gap: spacing.sm },
  timelineTitle: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface, lineHeight: 20, flex: 1 },
  timelineTime: { fontFamily: fonts.text, fontSize: 11, color: c.muted },
  timelineBody: { fontFamily: fonts.text, fontSize: 13, lineHeight: 19, color: c.onSurfaceSecondary, marginTop: 4 },
  // ── Entry kind badges ──
  entryBadge: { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.pill, alignSelf: "flex-start" as const, marginTop: 4 },
  entryBadgeText: { fontFamily: fonts.textSemibold, fontSize: 10, letterSpacing: 0.3, textTransform: "uppercase" as const },

  // ── Technical Error Details ──
  diagSection: { gap: spacing.sm },
  diagToggle: { flexDirection: "row" as const, alignItems: "center" as const, justifyContent: "space-between" as const, paddingVertical: spacing.sm },
  diagToggleText: { fontFamily: fonts.textSemibold, fontSize: 14, color: c.onSurface },
  diagCard: { backgroundColor: c.surfaceTertiary, borderRadius: radius.md, padding: spacing.md, gap: spacing.xs, borderWidth: 1, borderColor: c.border },
  diagRow: { flexDirection: "row" as const, gap: spacing.sm },
  diagLabel: { fontFamily: fonts.textSemibold, fontSize: 12, color: c.muted, minWidth: 100 },
  diagValue: { fontFamily: fonts.text, fontSize: 12, color: c.onSurface, flex: 1, flexShrink: 1 },
  diagDivider: { height: 1, backgroundColor: c.border, marginVertical: spacing.xs },
  retryEntry: { flexDirection: "row" as const, gap: spacing.xs, paddingVertical: 2 },
  retryBadge: { fontFamily: fonts.textMedium, fontSize: 11, color: c.muted },
  retryText: { fontFamily: fonts.text, fontSize: 12, color: c.onSurface, flex: 1, flexShrink: 1 },
  copyBtn: { marginTop: spacing.xs },

  // ── Raw provider response ──
  rawBlock: { backgroundColor: c.surfaceTertiary, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: c.border },
  rawHeader: { flexDirection: "row" as const, justifyContent: "space-between" as const, alignItems: "center" as const, marginBottom: spacing.sm },
  rawTitle: { fontFamily: fonts.textSemibold, fontSize: 13, color: c.onSurface },
  rawCopyBtn: { flexDirection: "row" as const, alignItems: "center" as const, gap: 4 },
  rawCopyText: { fontFamily: fonts.textMedium, fontSize: 12, color: c.brandPrimary },
  rawCode: { fontFamily: Platform.select({ ios: "Menlo", default: "monospace" }), fontSize: 12, color: c.onSurface, lineHeight: 18 },

  // ── Preserved legacy ──
  card: { gap: spacing.sm, borderColor: c.navyBorder },
  higginsExplanation: { backgroundColor: c.surfaceTertiary, borderRadius: radius.md, padding: spacing.md, borderLeftWidth: 3, borderLeftColor: c.gold, gap: spacing.xs },
  higginsExplainText: { fontFamily: fonts.text, fontSize: 14, lineHeight: 22, color: c.onSurface },
  higginsExplainLabel: { fontFamily: fonts.textSemibold, fontSize: 11, letterSpacing: 0.3, color: c.gold, textTransform: "uppercase" },
}));

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Build a copyable diagnostics record from failure data. */
function buildDiagnosticsCopy(failure: Record<string, unknown> | null | undefined, caseId?: string): string {
  if (!failure) return "No diagnostic information available.";
  const lines: string[] = ["── Technical Error Details ──"];
  const diag = (failure.diagnostics ?? {}) as Record<string, unknown>;
  const addLine = (label: string, value: unknown) => { if (value !== null && value !== undefined && value !== "") lines.push(`${label}: ${String(value)}`); else lines.push(`${label}: Unavailable`); };
  addLine("Failing component", diag.component);
  addLine("Service/provider", diag.service);
  addLine("Operation", diag.operation);
  addLine("Original error code", diag.originalErrorCode ?? diag.original_error_code);
  addLine("HTTP status", diag.httpStatus ?? diag.http_status);
  addLine("Original error message", diag.originalMessage ?? diag.original_message);
  addLine("Provider reply (verbatim, redacted)", diag.providerResponse ?? diag.provider_response);
  addLine("Provider model", diag.providerModel ?? diag.provider_model);
  addLine("Provider finish reason", diag.providerFinishReason ?? diag.provider_finish_reason);
  addLine("Exception type", diag.exceptionType ?? diag.exception_type);
  addLine("Timestamp", diag.timestamp);
  const durMs = diag.durationMs ?? diag.duration_ms;
  addLine("Duration", durMs ? `${durMs}ms` : undefined);
  addLine("Case ID", caseId ?? diag.caseId ?? diag.case_id);
  addLine("Job ID", diag.jobId ?? diag.job_id);
  addLine("Request ID", diag.requestId ?? diag.request_id);
  addLine("Final status", diag.finalStatus ?? diag.final_status);
  addLine("Failure code", failure.code);
  addLine("Retryable", failure.retryable);
  const history = (failure.retryHistory ?? failure.retry_history ?? []) as Record<string, unknown>[];
  if (history.length) {
    lines.push("\n── Investigation Attempts ──");
    for (const rh of history) {
      const attempt = rh.attempt ?? "?";
      const kind = rh.kind ?? "unknown";
      const outcome = rh.outcome ?? "unknown";
      const code = rh.failureCode ?? rh.failure_code ?? "";
      const msg = rh.failureMessage ?? rh.failure_message ?? "";
      const ts = rh.timestamp ?? "";
      const dur = rh.durationMs ?? rh.duration_ms;
      lines.push(`  Attempt ${attempt} (${String(kind).replace(/_/g, " ")}) → ${outcome}${code ? ` [${code}]` : ""}${msg ? `: ${String(msg).slice(0, 200)}` : ""}${ts ? ` at ${ts}` : ""}${dur ? ` (${dur}ms)` : ""}`);
    }
  }
  return lines.join("\n");
}

/** Map failure to Higgins-style user-facing explanation.
 *  The server already classifies the real failure and writes the honest sentence, so that message is
 *  preferred whenever it is present. The local map only covers failures with no server message. */
function higginsExplanation(failure: Record<string, unknown> | null | undefined, isRetrying: boolean): string {
  if (!failure) return "";
  const code = String(failure.code ?? "");
  const serverMessage = typeof failure.message === "string" ? failure.message.trim() : "";
  if (serverMessage) return serverMessage;
  const history = (failure.retryHistory ?? failure.retry_history ?? []) as unknown[];
  if (isRetrying) {
    if (code === "rate_limited") return "Magnum DI has temporarily reached the analysis service's request limit. It's waiting briefly before trying again.";
    if (code === "provider_unavailable") return "Magnum DI's analysis service took longer than expected to respond. It's automatically trying again, so you don't need to do anything just yet.";
    if (code === "budget_exhausted") return "Magnum DI ran out of processing time before it could finish. It's attempting to continue the investigation using the information already collected.";
    return "Magnum DI encountered a temporary issue and is automatically retrying.";
  }
  if (code === "response_invalid") return "Magnum DI couldn't complete the investigation. The AI tool returned a response ApolloSG couldn't validate. No investigation conclusion has been substituted — the AI tool's actual reply is in the technical details.";
  if (code === "provider_configuration") return "Magnum DI couldn't access one of its analysis services because it isn't configured correctly. This needs a technical fix rather than another immediate attempt.";
  if (history.length > 1) return "Magnum DI couldn't complete the investigation because the analysis service remained unavailable after several attempts. I'll show you any findings already collected. You can try again later.";
  if (code === "evidence_expired") return "Original evidence has been cleaned up from the server. The investigation findings remain available on your device.";
  return "Magnum DI couldn't complete the investigation, but I can't confirm exactly what interrupted it. I'll show you the available findings and the technical details so we can identify what needs fixing.";
}

/** Build a JSON representation of raw provider response for display. */
function buildRawProviderResponse(failure: Record<string, unknown> | null | undefined): string | null {
  if (!failure) return null;
  const diag = (failure.diagnostics ?? {}) as Record<string, unknown>;
  const code = diag.originalErrorCode ?? diag.original_error_code;
  const message = diag.originalMessage ?? diag.original_message;
  const httpStatus = diag.httpStatus ?? diag.http_status;
  // The provider's actual reply, when Apollo kept it (e.g. a reply that failed validation).
  const providerResponse = diag.providerResponse ?? diag.provider_response;
  if (!code && !message && !httpStatus && !providerResponse) return null;
  const error: Record<string, unknown> = {};
  if (code !== null && code !== undefined) error.code = code;
  if (message) error.message = message;
  if (httpStatus) error.status = httpStatus;
  const payload: Record<string, unknown> = { error };
  if (providerResponse) {
    payload.providerReply = providerResponse;
    payload.providerModel = diag.providerModel ?? diag.provider_model ?? null;
    payload.providerFinishReason = diag.providerFinishReason ?? diag.provider_finish_reason ?? null;
  }
  return JSON.stringify(payload, null, 2);
}

/** Retry kind label. */
function kindLabel(kind: string) {
  if (kind === "provider_retry") return "Provider retry";
  if (kind === "job_resume") return "Auto-resume";
  if (kind === "stream_reconnect") return "Reconnection";
  if (kind === "manual_retry") return "Manual retry";
  return kind.replace(/_/g, " ");
}

/** Evidence source type header info based on evidence kind and metadata. */
function evidenceSourceInfo(ev: EvidenceItem): {
  title: string;
  Icon: React.ComponentType<{ size: number; color: string }>;
  iconBg: string;
  iconColor: string;
  metaLines: string[];
} {
  const meta: string[] = [];
  let originalUrl: string | null = null;
  const label = ev.label ?? "";
  const prov = ev.provenance;

  // Extract URL from label if it looks like one
  const urlMatch = label.match(/https?:\/\/[^\s"'<>]+/);
  if (urlMatch) originalUrl = urlMatch[0];

  switch (ev.kind) {
    case "url": {
      const domain = originalUrl ? (() => { try { return new URL(originalUrl).hostname; } catch { return ""; } })() : "";
      if (!originalUrl && label.startsWith("http")) originalUrl = label;
      return {
        title: domain || "Website / Link",
        Icon: Globe, iconBg: "#DBEAFE", iconColor: "#1E3A5F",
        metaLines: [originalUrl ?? label, ...(prov?.sourceDescription ? [prov.sourceDescription] : []), ev.collectedAt ? `Captured: ${new Date(ev.collectedAt).toLocaleString()}` : ""].filter(Boolean),
      };
    }
    case "text": {
      // Determine if this is a message, email, or generic text
      const isEmail = /email|mail|subject|from:/i.test(label);
      const isMessage = /message|sms|chat|whatsapp/i.test(label);
      const isCall = /call|phone|number/i.test(label);
      if (isEmail) {
        const subjectMatch = label.match(/subject:\s*(.+)/i);
        const senderMatch = label.match(/from:\s*(.+?)(?:\s*[|·]|$)/i);
        meta.push(senderMatch ? `From: ${senderMatch[1].trim()}` : "Email");
        if (subjectMatch) meta.push(`Subject: ${subjectMatch[1].trim()}`);
        return { title: "Email", Icon: Mail, iconBg: "#DBEAFE", iconColor: "#1E3A5F", metaLines: [...meta, ev.collectedAt ? `Received: ${new Date(ev.collectedAt).toLocaleString()}` : ""].filter(Boolean) };
      }
      if (isMessage || isCall) {
        const phoneMatch = label.match(/\+?\d[\d\s().-]{7,}\d/);
        if (phoneMatch) meta.push(`From: ${phoneMatch[0].trim()}`);
        return { title: isCall ? "Call" : "Message", Icon: isCall ? Phone : MessageSquare, iconBg: "rgba(212,120,10,0.15)", iconColor: "#D4780A", metaLines: [...meta, ev.collectedAt ? new Date(ev.collectedAt).toLocaleString() : ""].filter(Boolean) };
      }
      return { title: "Text content", Icon: FileText, iconBg: "#DBEAFE", iconColor: "#1E3A5F", metaLines: [prov?.sourceDescription ?? label, ev.collectedAt ? new Date(ev.collectedAt).toLocaleString() : ""].filter(Boolean) };
    }
    case "image":
      return { title: "Screenshot", Icon: Search, iconBg: "rgba(212,120,10,0.15)", iconColor: "#D4780A", metaLines: [label || "User screenshot", ev.collectedAt ? `Captured: ${new Date(ev.collectedAt).toLocaleString()}` : "", ev.mediaType ?? ""].filter(Boolean) };
    case "document": case "file": case "attachment":
      return { title: prov?.originalFilename ?? "File", Icon: FileText, iconBg: "#E4F0E8", iconColor: "#2E7D32", metaLines: [prov?.originalFilename ?? label, ev.mediaType ?? "", ev.byteLength ? formatEvBytes(ev.byteLength) : "", ev.collectedAt ? `Uploaded: ${new Date(ev.collectedAt).toLocaleString()}` : ""].filter(Boolean) };
    case "email": case "email_original": {
      const subjectMatch = label.match(/subject:\s*(.+)/i);
      const senderMatch = label.match(/from:\s*(.+?)(?:\s*[|·]|$)/i);
      const metaEmail: string[] = [];
      if (senderMatch) metaEmail.push(`From: ${senderMatch[1].trim()}`);
      if (subjectMatch) metaEmail.push(`Subject: ${subjectMatch[1].trim()}`);
      if (!metaEmail.length && label) metaEmail.push(label);
      return { title: "Email", Icon: Mail, iconBg: "#DBEAFE", iconColor: "#1E3A5F", metaLines: [...metaEmail, ev.collectedAt ? `Received: ${new Date(ev.collectedAt).toLocaleString()}` : ""].filter(Boolean) };
    }
    default:
      return { title: (ev.kind ?? "Evidence").charAt(0).toUpperCase() + (ev.kind ?? "Evidence").slice(1), Icon: FileText, iconBg: "#DBEAFE", iconColor: "#1E3A5F", metaLines: [label, ev.collectedAt ? new Date(ev.collectedAt).toLocaleString() : ""].filter(Boolean) };
  }
}

function formatEvBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Timeline entry for History tab. */
interface TimelineEntry {
  title: string;
  body: string;
  at: string;
  iconType: "create" | "working" | "retry" | "complete" | "failed" | "question";
  /** Classifies the entry so the UI can distinguish administrative closures from real investigation outcomes. */
  entryKind: "process" | "user_action" | "administrative_closure" | "investigation_outcome" | "error";
}

/** Collapse consecutive retry entries of the same kind into a single grouped entry. */
function dedupeRetries(entries: TimelineEntry[]): TimelineEntry[] {
  const result: TimelineEntry[] = [];
  let retryGroup: TimelineEntry[] = [];
  const flushRetries = () => {
    if (retryGroup.length === 0) return;
    if (retryGroup.length === 1) { result.push(retryGroup[0]); }
    else {
      const successes = retryGroup.filter((e) => e.body.startsWith("Succeeded"));
      const failures = retryGroup.filter((e) => !e.body.startsWith("Succeeded"));
      const parts: string[] = [];
      if (failures.length) parts.push(`${failures.length} failed`);
      if (successes.length) parts.push(`${successes.length} succeeded`);
      result.push({
        title: `${retryGroup.length} automatic retries`,
        body: `${parts.join(", ")}. Last attempt: ${retryGroup[retryGroup.length - 1].body}`,
        at: retryGroup[retryGroup.length - 1].at,
        iconType: successes.length ? "complete" : "retry",
        entryKind: "process",
      });
    }
    retryGroup = [];
  };
  for (const entry of entries) {
    if (entry.iconType === "retry") { retryGroup.push(entry); }
    else { flushRetries(); result.push(entry); }
  }
  flushRetries();
  return result;
}

function buildTimeline(state: CaseState): TimelineEntry[] {
  const entries: TimelineEntry[] = [];
  const { caseData, turns, failure, phase, response } = state;
  const name = investigatorName(caseData?.answeredBy);
  const isFlyby = caseData?.answeredBy ? /^tc_flyby/i.test(caseData.answeredBy) : false;
  if (caseData) entries.push({ title: "Investigation opened", body: "ApolloSG began the investigation.", at: caseData.createdAt, iconType: "create", entryKind: "process" });
  for (const turn of turns) entries.push({ title: "Follow-up submitted", body: `You asked: "${turn.question.slice(0, 100)}${turn.question.length > 100 ? "\u2026" : ""}"`, at: turn.committedAt, iconType: "question", entryKind: "user_action" });
  const history = ((failure as unknown as Record<string, unknown> | null)?.retryHistory ?? (failure as unknown as Record<string, unknown> | null)?.retry_history ?? []) as Record<string, unknown>[];
  for (const rh of history) {
    entries.push({ title: kindLabel(String(rh.kind ?? "Retry")), body: `${rh.outcome === "success" ? "Succeeded" : "Failed"}${rh.failureCode || rh.failure_code ? ` \u2014 ${rh.failureCode ?? rh.failure_code}` : ""}`, at: String(rh.timestamp ?? caseData?.createdAt ?? ""), iconType: rh.outcome === "success" ? "complete" : "retry", entryKind: "process" });
  }
  if (response && (phase === "answered" || phase === "waiting_user")) {
    if (isFlyby) {
      entries.push({
        title: "Case settled",
        body: caseData?.settledReason?.sentence
          ?? `${name}'s automated checks resolved this case. No deep investigation was required.`,
        at: caseData?.updatedAt ?? caseData?.createdAt ?? "",
        iconType: "complete",
        entryKind: "administrative_closure",
      });
    } else {
      entries.push({
        title: response.completion === "complete" ? "Investigation complete" : "Results available",
        body: response.completion === "complete" ? `${name} completed the investigation within scope.`
          : response.completion === "partial" ? `${name} provided partial results.`
          : "Magnum DI is waiting for your answer.",
        at: caseData?.updatedAt ?? caseData?.createdAt ?? "",
        iconType: "complete",
        entryKind: "investigation_outcome",
      });
    }
  } else if (phase === "failed") {
    entries.push({ title: "Investigation incomplete", body: failure?.message ?? state.error ?? "The investigation could not be completed.", at: caseData?.updatedAt ?? caseData?.createdAt ?? "", iconType: "failed", entryKind: "error" });
  } else if (phase === "expired") {
    entries.push({ title: "Server copy cleaned up", body: "Original evidence was cleaned up from the server. Saved findings remain on this device.", at: caseData?.updatedAt ?? "", iconType: "failed", entryKind: "process" });
  }
  const sorted = entries.sort((a, b) => a.at.localeCompare(b.at));
  return dedupeRetries(sorted);
}

function timelineDotColor(type: string): string {
  switch (type) { case "create": return "#2563EB"; case "working": return "#7C3AED"; case "retry": return "#D97706"; case "complete": return "#16A34A"; case "failed": return "#DC2626"; case "question": return "#D97706"; default: return "#6B7280"; }
}

// ── Sub-components ───────────────────────────────────────────────────────────

/** Single row in the diagnostic detail display. */
function DiagRow({ label, value, s }: { label: string; value: unknown; s: ReturnType<typeof useStyles> }) {
  const display = value !== null && value !== undefined && value !== "" ? String(value) : "Unavailable";
  return <View style={s.diagRow}><Text style={s.diagLabel}>{label}</Text><Text style={s.diagValue}>{display}</Text></View>;
}

/** Expandable Technical Error Details section. */
function TechnicalErrorDetails({ failure, caseId, s }: { failure: Record<string, unknown> | null | undefined; caseId?: string; s: ReturnType<typeof useStyles> }) {
  const [expanded, setExpanded] = useState(false);
  const [copyNote, setCopyNote] = useState("");
  const { colors } = useTheme();
  if (!failure) return null;
  const diag = (failure.diagnostics ?? {}) as Record<string, unknown>;
  const history = (failure.retryHistory ?? failure.retry_history ?? []) as Record<string, unknown>[];
  const hasDiag = Object.values(diag).some((v) => v !== null && v !== undefined && v !== "");

  return <View style={s.diagSection} testID="inv-diag-section">
    <Pressable style={s.diagToggle} onPress={() => setExpanded((v) => !v)} testID="inv-diag-toggle">
      <Text style={s.diagToggleText}>Technical error details</Text>
      {expanded ? <ChevronUp size={18} color={colors.muted} /> : <ChevronDown size={18} color={colors.muted} />}
    </Pressable>
    {expanded ? <View style={s.diagCard} testID="inv-diag-details">
      {hasDiag ? <>
        <DiagRow s={s} label="Component" value={diag.component} />
        <DiagRow s={s} label="Service" value={diag.service} />
        <DiagRow s={s} label="Operation" value={diag.operation} />
        <View style={s.diagDivider} />
        <DiagRow s={s} label="Failure" value={failure.code} />
        <DiagRow s={s} label="HTTP status" value={diag.httpStatus ?? diag.http_status} />
        <DiagRow s={s} label="Error code" value={diag.originalErrorCode ?? diag.original_error_code} />
        <DiagRow s={s} label="Error message" value={diag.originalMessage ?? diag.original_message} />
        <DiagRow s={s} label="Exception" value={diag.exceptionType ?? diag.exception_type} />
        <View style={s.diagDivider} />
        <DiagRow s={s} label="Request ID" value={diag.requestId ?? diag.request_id} />
        <DiagRow s={s} label="Timestamp" value={diag.timestamp} />
        <DiagRow s={s} label="Duration" value={(diag.durationMs ?? diag.duration_ms) ? `${diag.durationMs ?? diag.duration_ms}ms` : undefined} />
        <DiagRow s={s} label="Attempts" value={history.length ? `${history.length} (${history.length - 1} automatic retries)` : undefined} />
        <DiagRow s={s} label="Recovery" value={diag.finalStatus ?? diag.final_status} />
        <DiagRow s={s} label="Case ID" value={caseId ?? diag.caseId ?? diag.case_id} />
        <DiagRow s={s} label="Job ID" value={diag.jobId ?? diag.job_id} />
      </> : <Text style={s.diagValue}>No detailed diagnostics were recorded for this failure.</Text>}
      {history.length ? <>
        <View style={s.diagDivider} />
        <Text style={[s.diagLabel, { minWidth: 0 }]}>Investigation Attempts</Text>
        {history.map((rh, i) => <View key={i} style={s.retryEntry}>
          <Text style={s.retryBadge}>#{String(rh.attempt ?? i + 1)}</Text>
          <Text style={s.retryText}>{kindLabel(String(rh.kind ?? "unknown"))} \u2192 {String(rh.outcome ?? "unknown")}{rh.failureCode ?? rh.failure_code ? ` [${rh.failureCode ?? rh.failure_code}]` : ""}{rh.failureMessage ?? rh.failure_message ? `: ${String(rh.failureMessage ?? rh.failure_message).slice(0, 150)}` : ""}</Text>
        </View>)}
      </> : null}
      <View style={s.copyBtn}>
        <Button testID="inv-diag-copy" variant="ghost" label={copyNote || "Copy Diagnostics"} onPress={() => {
          const text = buildDiagnosticsCopy(failure, caseId);
          void Clipboard.setStringAsync(text).then(() => { setCopyNote("Copied to clipboard"); setTimeout(() => setCopyNote(""), 3000); }).catch(() => setCopyNote("Copy failed"));
        }} />
      </View>
    </View> : null}
  </View>;
}

/** Raw provider response code block with Copy. */
function RawProviderResponse({ failure, s }: { failure: Record<string, unknown> | null | undefined; s: ReturnType<typeof useStyles> }) {
  const { colors } = useTheme();
  const [copyNote, setCopyNote] = useState("");
  const rawJson = useMemo(() => buildRawProviderResponse(failure), [failure]);
  if (!rawJson) return null;
  return <View style={s.rawBlock} testID="inv-raw-response">
    <View style={s.rawHeader}>
      <Text style={s.rawTitle}>Raw provider response</Text>
      <Pressable style={s.rawCopyBtn} onPress={() => { void Clipboard.setStringAsync(rawJson).then(() => { setCopyNote("Copied"); setTimeout(() => setCopyNote(""), 3000); }).catch(() => setCopyNote("Failed")); }} testID="inv-raw-copy">
        <Copy size={14} color={colors.brandPrimary} />
        <Text style={s.rawCopyText}>{copyNote || "Copy"}</Text>
      </Pressable>
    </View>
    <Text style={s.rawCode} selectable>{rawJson}</Text>
  </View>;
}

// ── Evidence Source Card ─────────────────────────────────────────────────────

/** Renders a single evidence item with source-specific header, original content, and metadata. */
function EvidenceSourceCard({ ev, caseId, onViewFull, s }: {
  ev: EvidenceItem; caseId: string; onViewFull: (id: string) => void;
  s: ReturnType<typeof useStyles>;
}) {
  const { colors } = useTheme();
  const info = evidenceSourceInfo(ev);
  const IconEl = info.Icon;
  const [textContent, setTextContent] = useState<string | null>(null);
  const [imageUri, setImageUri] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Load content on mount for available items
  useEffect(() => {
    if (ev.availability !== "available") return;
    setLoading(true);
    getDeviceToken().then((token) => {
      if (!token) { setLoading(false); return; }
      if (ev.kind === "image") {
        fetch(`${API_BASE}/investigations/${caseId}/evidence/${ev.id}/content`, { headers: { Authorization: `Bearer ${token}` } })
          .then(async (r) => { if (!r.ok) throw new Error(""); const blob = await r.blob(); return new Promise<string>((resolve) => { const reader = new FileReader(); reader.onloadend = () => resolve(reader.result as string); reader.readAsDataURL(blob); }); })
          .then((uri) => { setImageUri(uri); setLoading(false); })
          .catch(() => setLoading(false));
      } else if (ev.kind === "text" || ev.kind === "url") {
        fetch(`${API_BASE}/investigations/${caseId}/evidence/${ev.id}/content`, { headers: { Authorization: `Bearer ${token}` } })
          .then((r) => { if (!r.ok) throw new Error(""); return r.text(); })
          .then((text) => { setTextContent(text); setLoading(false); })
          .catch(() => setLoading(false));
      } else { setLoading(false); }
    }).catch(() => setLoading(false));
  }, [ev, caseId]);

  return (
    <View style={s.evidenceCard} testID={`inv-ev-source-${ev.id}`}>
      {/* ── Source Header ── */}
      <View style={s.sourceHeader}>
        <View style={[s.sourceIconWrap, { backgroundColor: info.iconBg }]}>
          <IconEl size={20} color={info.iconColor} />
        </View>
        <View style={s.sourceHeaderInfo}>
          <Text style={s.sourceHeaderTitle}>{info.title}</Text>
          {info.metaLines.map((line, i) => (
            <Text key={i} style={i === 0 ? s.sourceHeaderMetaBold : s.sourceHeaderMeta} numberOfLines={2}>{line}</Text>
          ))}
        </View>
      </View>

      {/* ── Original Content ── */}
      {loading ? (
        <View style={{ alignItems: "center", paddingVertical: spacing.md }}>
          <ActivityIndicator color={colors.gold} size="small" />
        </View>
      ) : null}

      {/* Text/URL content — show original unaltered */}
      {textContent ? (
        <View style={s.sourceContentBlock}>
          <Text style={s.sourceContentText} selectable testID={`inv-ev-content-${ev.id}`}>{textContent}</Text>
        </View>
      ) : null}

      {/* Image content — show original screenshot */}
      {imageUri ? (
        <Pressable onPress={() => onViewFull(ev.id)} style={{ borderRadius: radius.md, overflow: "hidden" }}>
          <Image source={{ uri: imageUri }} style={{ width: "100%", aspectRatio: 16 / 9 }} resizeMode="contain" testID={`inv-ev-image-${ev.id}`} />
        </Pressable>
      ) : null}

      {/* Unavailable / expired notice */}
      {ev.availability === "content_expired" ? (
        <Text style={s.muted}>ApolloSG&apos;s server copy was deleted after 24 hours. Your copy on this device is kept until you delete it.</Text>
      ) : ev.availability !== "available" ? (
        <Text style={s.muted}>{ev.availability === "purged" ? "Server copy deleted. Your copy on this device is kept until you delete it." : ev.availability === "permission_required" ? "Additional permissions needed." : "Content not currently available."}</Text>
      ) : null}

      {/* Label — preserved original submission label */}
      {ev.label && !textContent && !imageUri ? <Text style={s.muted}>{ev.label}</Text> : null}

      {/* View full details link */}
      <Pressable onPress={() => onViewFull(ev.id)} hitSlop={8}>
        <Text style={[s.link, { fontSize: 13 }]}>View full details →</Text>
      </Pressable>
    </View>
  );
}

// ── Main Component ──────────────────────────────────────────────────────────

export function InvestigationView({ state, onAnswer, onRetry, onCancel, onAction, testID = "investigation", eventId, openingQuestion = true, tabsOnly = false, initialEvidence, overrideReport, overrideVerdict }: {
  state: CaseState; onAnswer?: (text: string) => void; onRetry: () => void; onCancel: () => void; onAction?: (action: ActionProposal, outcome: ActionOutcome) => void; testID?: string;
  /** The Threat Case this investigation belongs to, when there is one: the original may be kept under its id. */
  eventId?: string | null;
  /** Show the question that opened the case. False when a check opened it: the question is Apollo's own wording. */
  openingQuestion?: boolean;
  /** Render ONLY the tab bar + tab content (for embedding in Threats screen). Parent provides ScrollView and header. */
  tabsOnly?: boolean;
  /** Pre-populated evidence items (avoids a server round-trip for completed investigations). */
  initialEvidence?: EvidenceItem[];
  /** Use this report instead of computing from the response (for triage-only threats). */
  overrideReport?: Report;
  /** Use this verdict instead of computing from the response. */
  overrideVerdict?: BriefVerdict;
}) {
  const s = useStyles(); const { colors } = useTheme();
  // The check's own record on this device: who started it (when the case doesn't say) and Higgins Triage's record.
  const { events } = useApollo();
  const event = useMemo(() => (eventId ? events.find((e) => e.event_id === eventId) ?? null : null), [events, eventId]);
  const [activeTab, setActiveTab] = useState<InvestigationTabId>("overview");
  const [actionNote, setActionNote] = useState<string | null>(null);
  const [confirmablePlanId, setConfirmablePlanId] = useState<string | null>(null);
  const [reports, setReports] = useState<investigationApi.SavedReport[]>([]);
  const [reportsOpen, setReportsOpen] = useState(false);
  const [reportNext, setReportNext] = useState<string | null>(null);
  const [reportNote, setReportNote] = useState<string | null>(null);
  const [failedRecheck, setFailedRecheck] = useState(false);
  const [evidencePopupVisible, setEvidencePopupVisible] = useState(false);
  const [focusEvidenceId, setFocusEvidenceId] = useState<string | null>(null);
  const [evidenceItems, setEvidenceItems] = useState<EvidenceItem[]>(initialEvidence ?? []);
  const [hasLocalOriginal, setHasLocalOriginal] = useState(false);
  const [pdfExporting, setPdfExporting] = useState(false);
  const [pdfNote, setPdfNote] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);

  // ── Recheck observer ──
  useEffect(() => onRecheck((o) => {
    if (!state.caseData || o.attempt.caseId !== state.caseData.id) return;
    const fresh = o.observation ? `fresh observation: ${scrubMessage(o.observation.status)}${o.observation.unavailableReason ? ` (${scrubMessage(o.observation.unavailableReason)})` : ""}` : "no observation possible on this device";
    const verdict = o.plan ? ({ correct: "The setting now matches what ApolloSG asked for.", not_yet_correct: "The setting is not yet at the expected value.", cannot_observe: "Apollo cannot read this setting here \u2014 only you can confirm it.", failed: "The re-check failed." } as const)[o.plan.outcome] : "";
    setActionNote(`Back from Settings \u2014 ${fresh}. ${verdict} ${o.plan?.explanation ?? ""}`.trim());
    setFailedRecheck(o.attempt.status === "failed" && o.plan?.outcome === "failed");
    setConfirmablePlanId(o.plan?.outcome === "cannot_observe" ? o.attempt.planId : null);
  }), [state.caseData]);

  // ── PDF export ──
  const exportPdf = useCallback(async () => {
    const currentCase = state.caseData;
    if (!currentCase) return;
    setPdfExporting(true); setPdfNote(null);
    try {
      const token = await getDeviceToken();
      if (!token) { setPdfNote("Device not registered. Please restart ApolloSG."); return; }
      // Times in the report are this device's local time.
      const url = `${API_BASE}/investigations/${currentCase.id}/export/pdf?tzOffset=${-new Date().getTimezoneOffset()}`;
      const filename = `Apollo_Report_${currentCase.id.slice(0, 8)}.pdf`;
      const fileUri = (FileSystemLegacy.cacheDirectory ?? "") + filename;
      const result = await FileSystemLegacy.downloadAsync(url, fileUri, { headers: { Authorization: `Bearer ${token}` } });
      if (!result || result.status !== 200) { setPdfNote("Could not generate the PDF. Please try again."); return; }
      const sharingAvailable = await Sharing.isAvailableAsync();
      if (sharingAvailable) {
        await Sharing.shareAsync(result.uri, { mimeType: "application/pdf", dialogTitle: "Export Apollo Investigation Report", UTI: "com.adobe.pdf" });
        setPdfNote("PDF exported successfully.");
      } else if (Platform.OS === "web") { setPdfNote("PDF download is not available in the web preview. Use the Expo Go app on a device."); }
      else { setPdfNote("This device can't share files from ApolloSG."); }
    } catch (e: unknown) { setPdfNote(e instanceof Error ? e.message : "PDF export failed."); }
    finally { setPdfExporting(false); }
  }, [state.caseData]);

  // ── Load reports + evidence ──
  useEffect(() => {
    if (!state.caseData) { setReports([]); setReportNext(null); return; }
    void listLocalReports().then((items) => { setReports(items); setReportNext(null); }).catch(() => setReportNote("Saved reports could not be loaded."));
    void investigationApi.listEvidence(state.caseData.id).then((result) => setEvidenceItems(result.items)).catch(() => {});
  }, [state.caseData]);

  const { phase, response, sources, turns, caseData, progress, failure, error, question } = state;
  const working = phase === "creating" || phase === "working" || phase === "reconnecting" || phase === "waiting_device";

  // Reset retrying state when phase leaves "failed"
  useEffect(() => { if (phase !== "failed") setRetrying(false); }, [phase]);

  const handleRetry = useCallback(() => {
    setRetrying(true);
    onRetry();
    // Safety: reset after 6s in case retry returns silently (e.g., expired operation)
    setTimeout(() => setRetrying(false), 6000);
  }, [onRetry]);

  // Resubmit waits out the server's pause (about five minutes after Magnum DI's second try failed).
  const [waitSeconds, setWaitSeconds] = useState(() => resubmitWaitSeconds(failure));
  useEffect(() => {
    setWaitSeconds(resubmitWaitSeconds(failure));
    if (phase !== "failed" || !resubmitWaitSeconds(failure)) return;
    const timer = setInterval(() => {
      const left = resubmitWaitSeconds(failure);
      setWaitSeconds(left);
      if (!left) clearInterval(timer);
    }, 1000);
    return () => clearInterval(timer);
  }, [failure, phase]);
  const showResubmit = phase === "failed" && canResubmit(failure);
  const resubmit = resubmitLabels(waitSeconds, retrying);
  const resubmitDisabled = retrying || waitSeconds > 0;
  const showTabs = tabsOnly || !!(response || (failure && caseData && !working));
  // Higgins' report, built the same way as a threat's Findings Brief: each fact once.
  // Higgins' plain English when it passed its Fidelity Check; otherwise Apollo's own wording.
  const computedReport = useMemo(() => {
    if (!response) return null;
    const plain = shownPlainEnglish(response);
    if (plain) return plainReport(plain, sources, response.sourceIds, evidenceItems);
    return buildReport({
      overview: scrubMessage(response.overview), explanationMarkdown: scrubMessage(response.explanationMarkdown), attentionReason: response.attentionReason,
      findings: response.findings, uncertainties: response.uncertainties, scope: response.scope, sources, sourceIds: response.sourceIds,
      alreadySaid: [caseData?.settledReason?.sentence], evidence: evidenceItems,
    });
  }, [response, sources, caseData?.settledReason, evidenceItems]);
  const report = overrideReport ?? computedReport;

  // ── Categorised evidence items ──
  const originalEvidence = useMemo(() => evidenceItems.filter((e) => e.origin === "user_submission" || e.origin === "device_observation"), [evidenceItems]);
  const derivedEvidence = useMemo(() => evidenceItems.filter((e) => e.origin !== "user_submission" && e.origin !== "device_observation"), [evidenceItems]);

  const timeline = useMemo(() => buildTimeline(state), [state]);

  // The Findings Brief's verdict and how serious it is, from the Case Briefing — read the same way on a threat.
  const computedVerdict = useMemo(() => (response ? investigationVerdict(response) : null), [response]);
  const verdict = overrideVerdict ?? computedVerdict;
  // Whoever actually settled this result: TC FlyBy or Magnum DI.
  const investigator = investigatorName(caseData?.answeredBy);
  // What you can do: the investigation's own steps. One Apollo can carry out (open a setting, a verified source) is tappable.
  const pressAction = (action: ActionProposal) => {
    if (action.kind === "open_verified_source") { const src = sources.find((x) => action.sourceIds.includes(x.id)); if (src) void WebBrowser.openBrowserAsync(src.url); onAction?.(action, { kind: "opened_source" }); return; }
    if (!caseData) return;
    void runAction(action, caseData).then((outcome) => {
      setActionNote(outcome.kind === "observed" ? "Apollo took a fresh reading on this device."
        : outcome.kind === "opened" ? `${outcome.descriptor.label} \u2014 opened${outcome.iosPath ? `. In Settings go to: ${outcome.iosPath}` : ""}. When you come back, Apollo checks automatically.`
        : outcome.kind === "requested" ? "ApolloSG asked the system for that permission. A fresh check runs when you return."
        : outcome.kind === "opened_source" ? "Opened the source." : outcome.reason);
      onAction?.(action, outcome);
    });
  };
  const steps: BriefStep[] = response?.actions?.map((action, i) => ({
    id: action.id, text: stepText(response, i) || action.label, onPress: isExecutable(action) ? () => pressAction(action) : undefined,
  })) ?? [];

  // ── Phone number for identity resolution ──
  // When a case started from a call/number check, extract it so the identity card appears alongside the investigation.
  // Also detect when a phone number appears in the submitted text/message content.
  const [originalSource, setOriginalSource] = useState<OriginalSource | null>(null);
  useEffect(() => {
    const keys = [eventId, caseData?.id].filter((k): k is string => !!k);
    if (!keys.length) return;
    let live = true;
    void getCaseOriginal(keys).then((found) => { if (live) setOriginalSource(found); }).catch(() => {});
    const off = subscribeOriginalSource(() => void getCaseOriginal(keys).then((found) => { if (live) setOriginalSource(found); }).catch(() => {}));
    return () => { live = false; off(); };
  }, [eventId, caseData?.id]);

  const phoneNumber = useMemo(() => {
    // 1. Explicit call check — uses the kept original and the PatrolEvent
    const fromCall = callNumberOf(originalSource, event);
    if (fromCall) return fromCall;
    // 2. Text/message checks: look for a phone number in the submitted content
    //    Try the kept OriginalSource first (most reliable), then fall back to the PatrolEvent's recorded preview.
    const text = originalSource?.text?.trim()
      ?? originalSource?.fields?.find((f) => /^(content|text|message|number)$/i.test(f.label.trim()))?.value?.trim()
      ?? event?.source_metadata?.preview?.trim()
      ?? event?.local_indicator?.trim();
    if (text) {
      // Direct number entry: "0412345678" or "+61 412 345 678" or "13 22 21"
      const stripped = text.replace(/[\s\-().+]/g, "");
      if (stripped.length >= 6 && stripped.length <= 15 && /^\+?\d[\d\s\-().]{4,18}\d$/.test(text)) {
        return text;
      }
      // Call picker format: "0412345678 (saved as John)" — extract the number before the parenthetical
      const parenMatch = text.match(/^(\+?\d[\d\s\-().]{4,18}\d)\s*\(/);
      if (parenMatch) return parenMatch[1].trim();
      // Number followed by descriptive text: "0452638791 text message saying..."
      // Extract the leading phone-number-like sequence before alphabetic characters.
      const leadMatch = text.match(/^(\+?\d[\d\s\-().]{4,18}\d)(?:\s+[a-zA-Z]|\s*$)/);
      if (leadMatch) return leadMatch[1].trim();
      // Fallback: first phone-like sequence anywhere in text (at least 8 digits)
      const anyMatch = text.match(/(\+?\d[\d\s\-().]{6,18}\d)/);
      if (anyMatch) {
        const digits = anyMatch[1].replace(/\D/g, "");
        if (digits.length >= 8 && digits.length <= 15) return anyMatch[1].trim();
      }
    }
    return null;
  }, [originalSource, event]);

  return <View style={{ gap: spacing.md }} testID={testID}>

    {/* ── Conversation history (all turns). The opening question is left out when the case began from a check: the
        card at the top already shows what was submitted, and the question is Apollo's own wording. ── */}
    {!tabsOnly ? <>
    {turns.slice(0, -1).map((turn, i) => <View key={turn.turnId} style={s.turn} testID={`inv-turn-${turn.turnId}`}>
      {i > 0 || openingQuestion ? <View style={s.user}><Text style={s.text}>{turn.question}</Text></View> : null}
      <Text style={s.text}>{luddishText(scrubMessage(turn.response.overview))}</Text>
    </View>)}
    {turns.length && (turns.length > 1 || openingQuestion) ? <View style={s.user} testID="inv-current-question"><Text style={s.text}>{turns[turns.length - 1].question}</Text></View> : null}

    {/* ── Working / progress state — hidden once we have a response ── */}
    {working && !response ? <Card style={s.card} testID="inv-progress"><View style={s.row}><ActivityIndicator color={colors.gold} /><Body>{phase === "reconnecting" ? "Connection interrupted \u2014 reconnecting to the same investigation\u2026" : phase === "waiting_device" ? "Checking this device for a fresh observation\u2026" : "Apollo is investigating\u2026"}</Body></View>
      {progress.slice(-3).map((line, i) => <Text key={`${i}-${line}`} style={s.muted}>{line}</Text>)}
      {caseData?.activeJobId ? <Button testID="inv-cancel" variant="ghost" label="Cancel this investigation" onPress={onCancel} /> : null}</Card> : null}

    {/* ── Retrying state — show Higgins explanation during auto-retry ── */}
    {(phase as string) === "retry_wait" ? <Card style={s.card} testID="inv-retry-progress">
      <View style={s.row}><ActivityIndicator color={colors.gold} /><Body>Investigation continuing</Body></View>
      <View style={s.higginsExplanation}>
        <Text style={s.higginsExplainLabel}>Higgins</Text>
        <Text style={s.higginsExplainText}>{higginsExplanation(failure as unknown as Record<string, unknown> | null, true)}</Text>
      </View>
    </Card> : null}
    </> : null}

    {/* ── Status Card + Four-Tab Report ── */}
    {showTabs ? <>
      {/* ── What started it, and when (shared with a threat) — the result is in the Findings Brief ── */}
      {!tabsOnly ? <SourceSummaryCard origin={caseData?.origin ?? event?.origin} at={caseData?.createdAt} caseKeys={[eventId, caseData?.id]}
        event={event} evidence={evidenceItems} gates={caseData?.gates} simulated={caseData?.simulated} testID="inv-source-summary" /> : null}

      {/* ── Tab Navigation — shared component, identical to Threat Case ── */}
      <InvestigationTabBar active={activeTab} onChange={setActiveTab} testID="inv-tab-bar" />

      {/* ━━━━ TAB 1: FINDINGS BRIEF — what the investigation concluded, from the Evidence Lock ━━━━ */}
      {activeTab === "overview" ? (
        <View style={{ gap: spacing.md }} testID="inv-tab-overview-content">
          {report && verdict ? <View testID="inv-overview"><FindingsBrief report={report} verdict={verdict} steps={steps} ids="inv" caseId={caseData?.id} /></View> : null}
          {response?.history?.length ? <RelatedCases event={event} response={response} ids="inv" /> : null}
        <Card style={[s.card, { gap: spacing.md }]} testID="inv-overview-more">
          {!response && failure ? (
            <Text style={s.briefingText} testID="inv-overview">{higginsExplanation(failure as unknown as Record<string, unknown>, false)}</Text>
          ) : !response && error ? (
            <Text style={s.briefingText} testID="inv-overview">{error}</Text>
          ) : null}

          <View style={{ gap: spacing.sm }}>
            {/* Resubmit — only when the investigation stopped before Magnum DI's one call was made */}
            {(showResubmit && caseData) ? (
              <Pressable style={[s.actionCard, resubmitDisabled && { opacity: 0.6 }]} disabled={resubmitDisabled} onPress={handleRetry} testID="inv-retry"
                accessibilityRole="button" accessibilityState={{ disabled: resubmitDisabled }}>
                <View style={[s.actionIconWrap, { backgroundColor: "#DBEAFE" }]}>{retrying ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : waitSeconds > 0 ? <Clock size={20} color={colors.brandPrimary} /> : <RefreshCw size={20} color={colors.brandPrimary} />}</View>
                <View style={s.actionContent}>
                  <Text style={s.actionTitle} testID="inv-retry-title">{resubmit.title}</Text>
                  <Text style={s.actionDescription}>{resubmit.description}</Text>
                </View>
                {!resubmitDisabled ? <ChevronRight size={18} color={colors.muted} /> : null}
              </Pressable>
            ) : null}

            {/* Partial findings card — when partial findings available */}
            {failure && response ? (
              <View style={[s.infoCard, { backgroundColor: "#E6F2FF" }]} testID="inv-partial-findings">
                <View style={[s.infoIconWrap, { backgroundColor: colors.info }]}><Info size={16} color="#FFFFFF" /></View>
                <View style={s.infoContent}>
                  <Text style={s.infoTitle}>Partial findings available</Text>
                  <Text style={s.infoBody}>Some initial checks were completed. View Evidence tab for details.</Text>
                </View>
              </View>
            ) : null}
          </View>

          {actionNote ? <Text style={s.muted} testID="inv-action-note">{actionNote}</Text> : null}
          {confirmablePlanId && caseData ? <Button testID="inv-settings-user-confirm" variant="ghost" label="I checked this setting myself" onPress={() => {
            void investigationApi.confirmSettingsPlan(caseData.id, confirmablePlanId, true).then((result) => {
              setConfirmablePlanId(null); setActionNote(result.explanation);
            }).catch(() => setActionNote("ApolloSG could not record your confirmation. Try again."));
          }} /> : null}
          {failedRecheck ? <Button testID="inv-recheck-retry" variant="ghost" label="Retry the fresh check" onPress={() => { setFailedRecheck(false); void retryFailedAttempt(); }} /> : null}

          {/* ── Report controls (moved from Probe) ── */}
          {caseData && response ? <View style={{ gap: spacing.xs, marginTop: spacing.md }} testID="inv-report-controls">
            <View style={s.divider} />
            <Button testID="inv-export-pdf" variant="secondary" disabled={pdfExporting}
              label={pdfExporting ? "Generating PDF\u2026" : "Export Report as PDF"}
              icon={pdfExporting ? <ActivityIndicator size="small" color={colors.brand} /> : undefined}
              onPress={exportPdf} />
            {pdfNote ? <Text style={s.muted} testID="inv-pdf-note">{pdfNote}</Text> : null}
            <Button testID="inv-report-save" variant="ghost" label="Save a redacted report" onPress={() => {
              void saveLocalReport(caseData.id, response as unknown as Record<string, unknown>, response.revision).then((reportId) => listLocalReports().then((items) => {
                setReports(items); setReportNext(null); setReportNote(`Saved report ${reportId.slice(0, 8)}. Evidence stays on your device.`);
              })).catch(() => setReportNote("The report could not be saved."));
            }} />
            <Button testID="inv-reports-toggle" variant="ghost" label={`${reportsOpen ? "Hide" : "Manage"} saved reports (${reports.length}${reportNext !== null ? "+" : ""})`} onPress={() => setReportsOpen((v) => !v)} />
            {reportsOpen ? <View style={{ gap: spacing.sm }} testID="inv-reports-list">{reports.map((report) => <View key={report.reportId} style={s.source} testID={`inv-report-${report.reportId}`}>
              <Text style={s.text}>{luddishText(scrubMessage(report.overview))}</Text><Text style={s.muted}>Saved {new Date(report.savedAt).toLocaleDateString()} \u00B7 historical snapshot</Text>
              <Button testID={`inv-report-delete-${report.reportId}`} variant="ghost" label="Delete saved report" onPress={() => {
                void deleteLocalReport(report.reportId).then(() => { setReports((items) => items.filter((item) => item.reportId !== report.reportId)); setReportNote("Saved report deleted."); })
                  .catch(() => setReportNote("That report could not be deleted."));
              }} />
            </View>)}
            {reportNext !== null ? null : null}</View> : null}
            {reportNote ? <Text style={s.muted} testID="inv-report-note">{reportNote}</Text> : null}
          </View> : null}
        </Card>
        </View>
      ) : null}

      {/* ━━━━ TAB 2: EVIDENCE — Original Source Material ━━━━ */}
      {activeTab === "evidence" ? (
        <View style={{ gap: spacing.md }} testID="inv-tab-evidence-content">
          {caseData ? <EvidenceArtefactCard caseKeys={[eventId, caseData.id]} onAvailable={setHasLocalOriginal} packTitle={`Apollo investigation ${caseData.id.slice(0, 8)}`} packDate={caseData.createdAt} packSummary={caseData.response ? {
            overview: caseData.response.overview || null,
            findings: (caseData.response.findings ?? []).map((f) => f.text),
            steps: (caseData.response.actions ?? []).map((a) => a.instruction ? `${a.label}: ${a.instruction}` : a.label),
            uncertainties: caseData.response.uncertainties,
          } : null} /> : null}

          {/* Original evidence items — the server-side chain. Skipped when the exact original is
              already on this device, so the same material isn't shown twice. */}
          {originalEvidence.length && !hasLocalOriginal ? <>
            {originalEvidence.map((ev) => (
              <Card key={ev.id} style={[s.card, { gap: spacing.sm }]}>
                <EvidenceSourceCard
                  ev={ev} caseId={caseData?.id ?? ""}
                  onViewFull={(id) => { setFocusEvidenceId(id); setEvidencePopupVisible(true); }} s={s} />
              </Card>
            ))}
          </> : null}

          {!originalEvidence.length && !derivedEvidence.length && !hasLocalOriginal && !failure ? <Card style={s.card}><Text style={s.muted}>No evidence items are available for this investigation.</Text></Card> : null}

          {/* Investigation incomplete alert */}
          {failure ? (
            <Card style={[s.card, { gap: spacing.sm }]}>
              <View style={[s.infoCard, { backgroundColor: colors.barkingTint, padding: spacing.md }]}>
                <View style={[s.infoIconWrap, { backgroundColor: colors.barking }]}><CircleAlert size={16} color="#FFFFFF" /></View>
                <View style={s.infoContent}>
                  <Text style={[s.infoTitle, { color: colors.barkingText }]}>Investigation incomplete</Text>
                  <Text style={s.infoBody}>{failure.message ?? error ?? "Magnum DI couldn\u0027t complete all checks."}</Text>
                </View>
              </View>
              <TechnicalErrorDetails failure={failure as unknown as Record<string, unknown>} caseId={caseData?.id} s={s} />
              <RawProviderResponse failure={failure as unknown as Record<string, unknown>} s={s} />
            </Card>
          ) : null}

          {/* Outside research — sources consulted during investigation */}
          <Research rows={outsideResearch(sources ?? [], response ?? null)} />

          {/* Related history — context, never evidence */}
          {response?.history?.length ? (
            <CollapsibleSection title="Related history" testID="tc-di-history" subtitle="Context TC FlyBy and Magnum DI had, never evidence for this case. It can't change the verdict." defaultOpen={false}>
              {response.history.map((n, i) => (
                <Text key={`${i}-${n.text}`} style={s.muted} testID={`tc-di-history-${i}`}>
                  {`${n.source}: ${n.text}${n.findingIds.length ? ` Raised the confidence of ${n.findingIds.length === 1 ? "one finding" : `${n.findingIds.length} findings`}.` : ""}`}
                </Text>
              ))}
            </CollapsibleSection>
          ) : null}

        </View>
      ) : null}

      {/* ━━━━ TAB 3: HISTORY — Investigation Timeline ━━━━ */}
      {activeTab === "history" ? (
        <View style={{ gap: spacing.md }} testID="inv-tab-history-content">

          {/* Timeline */}
          <Card style={[s.card, { gap: spacing.md }]} testID="inv-history-timeline">
            {timeline.map((entry, i) => {
              const isLast = i === timeline.length - 1;
              const dotBg = entry.entryKind === "administrative_closure" ? "#6B7280"
                : entry.entryKind === "investigation_outcome" ? "#16A34A"
                : timelineDotColor(entry.iconType);
              const IconEl = entry.iconType === "create" ? Search : entry.iconType === "complete" ? CircleCheck : entry.iconType === "failed" ? CircleAlert : entry.iconType === "retry" ? RefreshCw : entry.iconType === "question" ? MessageSquare : Clock;
              // Badge config for entry kind
              const badge = entry.entryKind === "administrative_closure"
                ? { label: "RULE-BASED", bg: colors.surfaceTertiary, fg: colors.muted }
                : entry.entryKind === "investigation_outcome"
                ? { label: "INVESTIGATED", bg: colors.restingTint, fg: colors.restingText }
                : null;
              return (
                <View key={i} style={s.timelineItem} testID={`inv-history-${i}`}>
                  <View style={s.timelineTrack}>
                    <View style={[s.timelineDot, { backgroundColor: dotBg }]}><IconEl size={16} color="#FFFFFF" /></View>
                    {!isLast ? <View style={[s.timelineLine, { backgroundColor: colors.divider }]} /> : null}
                  </View>
                  <View style={isLast ? s.timelineContentLast : s.timelineContent}>
                    <View style={s.timelineRow}>
                      <Text style={s.timelineTitle}>{entry.title}</Text>
                      {entry.at ? <Text style={s.timelineTime}>{new Date(entry.at).toLocaleString([], { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" })}</Text> : null}
                    </View>
                    {badge ? (
                      <View style={[s.entryBadge, { backgroundColor: badge.bg }]}>
                        <Text style={[s.entryBadgeText, { color: badge.fg }]}>{badge.label}</Text>
                      </View>
                    ) : null}
                    <Text style={s.timelineBody}>{entry.body}</Text>
                  </View>
                </View>
              );
            })}
            {/* When the files sent for this result leave Apollo's server. */}
            {response && !response.question ? <ServerCopyNote caseId={caseData?.id} live={caseData} testID="inv-server-copy" /> : null}
          </Card>

          {/* Investigation history from domain (phase-based) */}
          {response ? <Card style={[s.card, { gap: spacing.xs }]}>
            <Text style={s.sectionTitle}>INVESTIGATION PROGRESS</Text>
            {investigationHistory({ turns: turns.map((t) => ({ question: t.question, overview: t.response.overview })), phase, completion: response.completion, answeredBy: caseData?.answeredBy }).map((h, i) => <Text key={i} style={s.muted} testID={`inv-progress-history-${i}`}>{"\u2022"} {h.text}</Text>)}
          </Card> : null}
        </View>
      ) : null}
    </> : null}

    {/* ── Follow-ups on the finished investigation — answered from its record, never re-investigated ── */}
    {!tabsOnly ? state.followUps.map((item) => <View key={item.turnId} style={s.turn} testID={`inv-followup-${item.turnId}`}>
      <View style={s.user}><Text style={s.text}>{item.question}</Text></View>
      <Card style={s.card}>
        <View style={s.higginsExplanation}>
          <Text style={s.higginsExplainLabel}>Higgins</Text>
          <Text style={s.higginsExplainText} testID="inv-followup-answer">{luddishText(scrubMessage(item.answer))}</Text>
        </View>
        <Text style={s.muted}>{`From ${investigator}'s finished investigation. Nothing new was analysed.`}</Text>
      </Card>
    </View>) : null}

    {/* ── Question from Higgins (outside tabs — transient) ── */}
    {!tabsOnly && question && phase === "waiting_user" ? <View style={s.question} testID="inv-question"><Text style={s.text}>{scrubMessage(question.text)}</Text><Text style={s.muted}>Why Magnum DI asks: {scrubMessage(question.reasonNeeded)}</Text>
      {question.answerType === "yes_no" ? <View style={s.row}><Button testID="inv-answer-yes" label="Yes" onPress={() => onAnswer?.("Yes")} /><Button testID="inv-answer-no" variant="ghost" label="No" onPress={() => onAnswer?.("No")} /></View> : null}
      {question.answerType === "choice" ? <View style={s.row}>{question.choices.map((c) => <Button key={c} testID={`inv-answer-${c}`} variant="ghost" label={c} onPress={() => onAnswer?.(c)} />)}</View> : null}</View> : null}

    {/* ── Who Called: mounted as soon as a phone number is known so the lookup runs during
        the investigation, not after findings are displayed. Hidden until the DI tab opens. ── */}
    {phoneNumber ? (
      <View style={activeTab === "di" && showTabs ? undefined : { display: "none" }}>
        <PhoneIdentityCard number={phoneNumber} testID="inv-di-phone-identity" />
      </View>
    ) : null}

    {/* ── DI tab: the Magnum DI processing record (evidence is untouched by this view) ── */}
    {activeTab === "di" && showTabs ? (
      <View style={{ gap: spacing.md }} testID="inv-tab-di-content">
        <DiReport caseId={caseData?.id ?? null} triage={event?.triage_investigation ?? null} settledReason={response ? caseData?.settledReason : null} how={report ? luddishReport(report).how : []}
          presented={verdict ? { verdict: verdict.label, risk: verdict.risk?.label ?? null } : null} history={response?.history}
          response={response ?? null} sources={sources} />
      </View>
    ) : null}

    {/* ── Lifecycle notice ── */}
    {!tabsOnly && state.notice ? <Card style={s.card} testID="inv-lifecycle-notice"><Body>{state.notice}</Body></Card> : null}

    {/* ── Error without tabs (edge case: failed before case created) ── */}
    {!tabsOnly && error && !showTabs && (phase === "failed" || phase === "expired") ? <Card style={s.card} testID="inv-error">
      <View style={s.higginsExplanation}>
        <Text style={s.higginsExplainLabel}>Higgins</Text>
        <Text style={s.higginsExplainText}>{failure ? higginsExplanation(failure as unknown as Record<string, unknown> | null, false) : error}</Text>
      </View>
      <TechnicalErrorDetails failure={failure as unknown as Record<string, unknown> | null} caseId={caseData?.id} s={s} />
      {showResubmit ? <Button testID="inv-retry" label={resubmit.title} disabled={resubmitDisabled} onPress={handleRetry} /> : null}
    </Card> : null}

    {/* ── Partial failure indicator (outside tabs) ── */}
    {!tabsOnly && failure && phase !== "failed" && !showTabs ? <Text style={s.muted} testID="inv-partial-reason">Incomplete: {failure.message}</Text> : null}

    {/* ── Evidence popup (shared across all tabs) ── */}
    {caseData ? <EvidencePopup visible={evidencePopupVisible} onClose={() => setEvidencePopupVisible(false)}
      caseId={caseData.id} focusEvidenceId={focusEvidenceId} items={evidenceItems} /> : null}
  </View>;
}
