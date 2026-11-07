// "Ask Higgins to explain" on a Patrol finding, an incident or a Device Check result: Higgins explains what Apollo
// already recorded, in fixed wording, on the device. No Gemini call and no new investigation — Magnum DI only
// investigates if the person then asks it to, with a separate tap.
import type { HigginsIssueContext } from "@/src/domain/higginsHandoff";

const STATE_TEXT: Record<string, string> = {
  resting: "no concern found within the checks that completed", sniffing: "Apollo is looking closer", ears_up: "worth a look", growling: "possible concern",
  barking: "significant concern", biting: "Apollo blocked it", unknown: "state not known",
};
const PROVENANCE_TEXT: Record<string, string> = { observed: "observed by Apollo", inferred: "Apollo's inference", user_reported: "from what you told ApolloSG" };
const STATUS_TEXT: Record<string, string> = { confirmed: "confirmed", warning: "a warning", uncertain: "not certain" };

const bullets = (lines: string[]) => lines.filter(Boolean).map((line) => `• ${line}`).join("\n");

export function explainIssue(context: HigginsIssueContext): string {
  const parts = [
    `${context.issue_summary} — ${STATE_TEXT[context.assessment_state] ?? STATE_TEXT.unknown}.`,
    context.findings.length ? `What Apollo found:\n${bullets(context.findings.map((f) => `${f.summary} (${PROVENANCE_TEXT[f.provenance] ?? f.provenance}; ${STATUS_TEXT[f.status] ?? f.status})`))}` : "Apollo didn't record individual findings for this.",
    context.uncertainty.length ? `What ApolloSG couldn't establish:\n${bullets(context.uncertainty)}` : "",
    context.confirmed_protective_actions.length ? `Protection Apollo confirmed:\n${bullets(context.confirmed_protective_actions)}` : "",
    context.user_reported_actions.length ? `What you reported:\n${bullets(context.user_reported_actions)}` : "",
    (context.available_actions ?? []).length ? `What you can do:\n${bullets((context.available_actions ?? []).map((a) => `${a.label}: ${a.instruction}`))}` : "",
  ];
  return `Here's what Apollo recorded about this — explained from Apollo's own findings, with no new analysis:\n\n${parts.filter(Boolean).join("\n\n")}`;
}

export const INVESTIGATE_OFFER = "If you'd like more than Apollo's own findings, Apollo can investigate this as a separate check — TC Hawkeye first, and Magnum DI only if a deeper look could change the answer. Nothing has started yet.";
