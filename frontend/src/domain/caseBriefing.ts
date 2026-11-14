// The Higgins Case Briefing, projected for each surface: Home, Threats, the Overview and notifications all read the
// SAME briefing (backend services/higgins/explain/briefing.py), so they can't say different things about one case.
// DI stays the technical trace and Evidence the original material. Pure: no React Native, unit-tested in node.
import type { CaseBriefing, HigginsResponse } from "../investigation/types";
import { gateCheckResult } from "./gateCheckResult.ts";
import { evidenceModel } from "./evidenceModel.ts";
import { sentences } from "./luddish/patterns.ts";
import { outcomeLabel, outcomeTone } from "./messageVoice.ts";
import type { ApolloState, PatrolEvent } from "./types";

/** What a Patrol event carries of its case's briefing (device-local, never synced). */
export interface EventBriefing {
  /** "Stoko email checked". */
  headline: string;
  /** '"hello@stoko.com" is a published Stoko contact. No scam warning was found for "stoko.com".' */
  summary: string;
  subject: string | null;
  /** Every finding, its subject always named, in Apollo's order. */
  findings: string[];
  unresolved: string[];
  status: string;
  statusReason: string;
  /** "Needs you" only when this is true AND actionReason is a concrete reason. */
  userActionRequired: boolean;
  actionReason: string | null;
  recommendedAction: { label: string; instruction: string } | null;
  /** "briefing": the server's checked Case Briefing. "response": an older result that has none — only the
   *  authoritative fields are projected (attention, its reason, what isn't certain), nothing is reworded. */
  from: "briefing" | "response";
  /** The case result (caseResult), carried so Home and Threats show exactly what the Findings Brief shows. */
  verdict?: string | null;
  verdictCode?: string | null;
  severity?: ApolloState | null;
  /** caseResult.notFullyChecked, carried for the same reason. */
  notFullyChecked?: boolean;
}

const clean = (text: string | null | undefined) => (text ?? "").replace(/\s+/g, " ").trim();

// ── The case result: one authoritative verdict, severity and finding list ────────────────────────────────────────

/** The result every surface shows for an investigated case — Home, Threats, the Findings Brief, Evidence, History and
 *  DI — read once, here, from the Evidence Lock → Higgins Luddish result: its Case Briefing when it passed its Fidelity
 *  Check, else what the committed result recorded. No surface works any of these out for itself. */
export interface CaseResult {
  /** "Likely scam": the briefing's status, else the recorded outcome's label. Null for an answer to a general question. */
  verdict: string | null;
  verdictCode: string | null;
  tone: ReturnType<typeof outcomeTone>;
  /** How serious: the attention the result recorded (urgent/action needed → barking, review → growling, none → resting).
   *  A result that is notFullyChecked is resting: no warning and no alert. */
  severity: ApolloState;
  /** The result found nothing of concern, so the case closes on its own. */
  noConcern: boolean;
  /** The result couldn't decide either way and left nothing concrete to act on: no urgent or action-needed attention,
   *  and no decision owed with a recorded reason. The case is filed as not fully checked: it closes with no warning
   *  and no alert, stays in history, and is never called safe. Mirror: backend investigation_projector.inconclusive. */
  notFullyChecked: boolean;
  from: "briefing" | "response";
}

const passed = (response: HigginsResponse): CaseBriefing | null => (response.briefing?.fidelity?.status === "PASS" ? response.briefing : null);

const UNDECIDED = "unable_to_determine";

export function caseResult(response: HigginsResponse): CaseResult {
  const b = passed(response);
  const code = b ? b.statusCode : response.outcome ?? null;
  const attention = b?.attention ?? response.attention;
  const actionLevel = attention === "urgent" || attention === "action_needed";
  const owed = b ? b.userActionRequired && !!clean(b.actionReason)
    : response.completion === "waiting_user" && !!clean(response.question?.reasonNeeded);
  const notFullyChecked = code === UNDECIDED && !actionLevel && !owed;
  return {
    verdict: outcomeLabel(code) ?? (b?.status || null),
    verdictCode: code,
    tone: outcomeTone(code),
    severity: notFullyChecked ? "resting" : actionLevel ? "barking" : attention === "review" ? "growling" : "resting",
    noConcern: code ? (code === "not_scam" || code === "no_scam_indicators") : response.assessment === "no_concern_found_within_scope",
    notFullyChecked,
    from: b ? "briefing" : "response",
  };
}

/** A threat's result: its committed investigation's when this phone holds it, else the copy its event carries.
 *  Null when no investigation has answered. */
export function threatResult(event: Pick<PatrolEvent, "case_briefing">, response: HigginsResponse | null | undefined): CaseResult | null {
  if (response) return caseResult(response);
  const b = event.case_briefing;
  if (!b || !b.severity) return null;
  const code = b.verdictCode ?? null;
  return { verdict: b.verdict ?? null, verdictCode: code, tone: outcomeTone(code), severity: b.severity, noConcern: code === "not_scam" || code === "no_scam_indicators",
    notFullyChecked: !!b.notFullyChecked, from: b.from };
}

/** One finding exactly as the result recorded it — the briefing's (with its stance) when it passed, else the
 *  committed result's. Evidence lists these, History counts them, the Findings Brief shows their plain words. */
export interface CaseFinding {
  id: string;
  text: string;
  basis: string;
  confidence: string | null;
  evidenceIds: string[];
  sourceIds: string[];
  /** Which way it points against the verdict; null when the result recorded no stance. */
  stance: "supporting" | "contrary" | "context" | null;
}

export function caseFindings(response: HigginsResponse): CaseFinding[] {
  const b = passed(response);
  if (b) {
    const byId = new Map((response.findings ?? []).map((f) => [f.id, f]));
    return b.findings.filter((f) => clean(f.finding)).map((f) => ({
      id: f.id, text: clean(f.finding), basis: byId.get(f.id)?.basis ?? f.basis, confidence: f.confidence || null,
      evidenceIds: f.evidenceIds ?? [], sourceIds: f.sourceIds ?? [], stance: f.stance,
    }));
  }
  return (response.findings ?? []).filter((f) => clean(f.text)).map((f) => ({
    id: f.id, text: clean(f.text), basis: f.basis, confidence: f.confidence ?? null, evidenceIds: f.evidenceIds ?? [], sourceIds: f.sourceIds ?? [], stance: null,
  }));
}

/** The briefing projection for a committed result. An older result without a briefing projects its authoritative
 *  fields only: a decision is owed only at an action-level attention with its recorded reason, or Magnum DI's
 *  pending question with its reason. */
export function eventBriefing(response: HigginsResponse): EventBriefing | null {
  const b: CaseBriefing | null | undefined = response.briefing;
  const result = caseResult(response);
  const carried = { verdict: result.verdict, verdictCode: result.verdictCode, severity: result.severity, notFullyChecked: result.notFullyChecked };
  if (b && b.fidelity?.status === "PASS") {
    const reason = clean(b.actionReason);
    return {
      headline: clean(b.headline), summary: clean(b.summary), subject: b.subject?.value ?? null,
      findings: b.findings.map((f) => clean(f.finding)).filter(Boolean), unresolved: b.unresolved.map(clean).filter(Boolean),
      status: b.status, statusReason: clean(b.statusReason),
      userActionRequired: b.userActionRequired && !!reason, actionReason: reason || null,
      recommendedAction: b.recommendedAction, from: "briefing", ...carried,
    };
  }
  const actionLevel = response.attention === "action_needed" || response.attention === "urgent";
  const reason = actionLevel ? clean(response.attentionReason)
    : response.completion === "waiting_user" ? clean(response.question?.reasonNeeded) : "";
  const recommended = response.actions.find((a) => a.id === response.recommendedActionId) ?? response.actions[0] ?? null;
  return {
    headline: "", summary: "", subject: null, findings: [], unresolved: response.uncertainties.map(clean).filter(Boolean),
    status: "", statusReason: clean(response.attentionReason),
    userActionRequired: !!reason, actionReason: reason || null,
    recommendedAction: recommended ? { label: recommended.label, instruction: recommended.instruction } : null, from: "response", ...carried,
  };
}

const BARKING = (e: PatrolEvent) => e.state === "barking" || (e.state === "biting" && !e.verified_block);

/** "Needs you", strictly. With a case: only when its briefing says a decision is owed AND names the concrete
 *  reason. Without one (Apollo's own on-device decision, no investigation): only a Barking record this device made
 *  itself with its reason and next step recorded. A server placeholder, a review, or "keeping watch" never is. */
export function needsYou(event: PatrolEvent): boolean {
  if (event.resolved_at || event.status === "resolved" || event.status === "trusted") return false;
  if (event.verified_block && event.enforcement_evidence) return false; // Blocked: Apollo already acted
  const b = event.case_briefing;
  if (b) return b.userActionRequired && !!clean(b.actionReason);
  const investigation = event.investigation_case_id ?? event.patrol_record?.investigationCaseId;
  if (investigation) return false; // still investigating, or answered without a recorded decision
  const gate = gateCheckResult(event);
  if (gate && gate.admission !== "investigate") return false;
  const model = evidenceModel(event);
  const serverHeld = model.representation === "privacy_summary" || model.representation === "privacy_protected_copy";
  return BARKING(event) && !serverHeld && model.completeness !== "partial"
    && !!clean(event.why?.[0]) && !!clean(event.what_to_do);
}

/** The event's checked Case Briefing, when it has one to show (a headline and a summary); null otherwise. Every
 *  case-result surface reads the briefing through this. */
export function briefed(event: PatrolEvent | undefined): EventBriefing | null {
  const b = event?.case_briefing;
  return b && b.from === "briefing" && b.headline && b.summary ? b : null;
}

/** The briefing's first finding (its subject always named): the short form Home and notifications show. */
export function firstFinding(b: EventBriefing): string {
  return (sentences(b.summary)[0] ?? b.summary).trim();
}

/** Title and summary for a case card (Home and Threats): the briefing's when there is one, else what Apollo recorded. */
export function caseCardText(event: PatrolEvent, fallbackTitle: string): { title: string; summary: string | null } {
  const b = briefed(event);
  if (b) return { title: b.headline, summary: b.summary };
  const gate = gateCheckResult(event);
  return gate ? { title: gate.label, summary: gate.report.answer[0] } : { title: fallbackTitle, summary: null };
}
