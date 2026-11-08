/**
 * Ask Higgins is the conversational surface of the same on-device Luddish
 * runtime used by investigators. This is an optional language refinement,
 * never a new source of factual claims, device state or scam verdicts.
 */
import { differences } from "../luddish/fidelity.ts";
import { runSLM, type SLMAdapter } from "../slm/index.ts";
import type { HigginsChatReply } from "./chatClient.ts";

const QUOTED = new Set([
  "recognised_government_feed_cache",
  "scam_alert_card",
  "learn_with_higgins_catalogue",
  "apollo_knowledge_base",
]);

export async function explainHigginsWithSLM(
  userQuestion: string,
  reply: HigginsChatReply,
  adapter: SLMAdapter | null,
): Promise<HigginsChatReply> {
  if (!adapter || !reply.answer.trim() || reply.investigativeWorkStarted ||
      reply.investigationAvailable || reply.clarification ||
      reply.evidenceBasis.some((basis) => QUOTED.has(basis)) ||
      reply.contextUsed.length > 0 || reply.answer.length > 2800) {
    return reply;
  }

  const result = await runSLM({
    role: "ask_higgins",
    operation: "chat_explanation",
    question: "Make Higgins' existing answer clearer and more conversational, using Australian English. " +
      "Preserve all facts, qualifications, negations, figures, actions and uncertainty. " +
      "Do not add advice, findings, links or claims. User question: " + userQuestion.slice(0, 700),
    evidence: [{ evidenceId: "higgins-approved-reply", text: reply.answer }],
  }, adapter);
  if (result.status !== "completed") return reply;
  const candidate = result.answer.draftExplanation?.trim();
  if (!candidate || candidate === reply.answer || candidate.length < reply.answer.length * 0.8 ||
      candidate.length > reply.answer.length * 1.2 ||
      differences(reply.answer, candidate).length > 0) {
    return reply;
  }
  // The backend owns the metadata, available actions, evidence basis and
  // navigation. The model may only replace wording after deterministic fidelity
  // validation and may never alter other fields.
  return { ...reply, answer: candidate };
}
