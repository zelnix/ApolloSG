// Follow-ups on a FINISHED Magnum DI investigation are answered here, on the device, from the investigation's own
// record — never by Gemini, and never by reopening the investigation. This holds even when the follow-up brings
// something new (a link, an email address or a phone number): the new item is named as not covered.
// Mirrors backend/services/higgins/presenter.py `investigation_follow_up` so both sides say the same thing.
import { investigatorName } from "../domain/messageVoice.ts";
import type { HigginsResponse, SourceReference } from "@/src/investigation/types";

export interface FollowUpAnswer {
  turnId: string;
  question: string;
  answer: string;
  intent: string;
  limitation: boolean;
  newItems: string[];
  answeredBy: "apollo";
}

// "{name}" is whichever investigator settled the result: TC Hawkeye or Magnum DI.
const ASSESSMENT_TEXT: Record<string, string> = {
  concern_found: "{name} found a concern.",
  no_concern_found_within_scope: "{name} found no concern within what it was able to check.",
  uncertain: "{name} couldn't reach a firm conclusion.",
};
const ATTENTION_TEXT: Record<string, string> = { none: "No action is needed.", review: "It's worth reviewing.", action_needed: "Action is needed.", urgent: "This is urgent." };
const BASIS_TEXT: Record<string, string> = { observation: "observed in the evidence", user_report: "from what you told ApolloSG", inference: "{name}'s inference from the evidence" };

const INTENTS: [string, RegExp][] = [
  ["recheck", /\bre-?check|\bfresh (?:observation|reading)|\bre-?assess|\bcheck (?:it |this |that )?again\b/i],
  ["not_established", /\b(?:wasn'?t|not|never|couldn'?t|didn'?t)\s+(?:established|found|checked|confirmed|able|cover(?:ed)?|look(?:ed)?)\b|\bunknown\b|\buncertain|\blimitations?\b|\bmissing\b|\bgaps?\b|\bscope\b|what (?:don'?t|didn'?t) (?:you|we|it) know/i],
  ["sources", /\bsources?\b|where did (?:this|that|the|you|it)\b.*\b(?:come from|get)|\breferences?\b|\bcitations?\b|\blinks?\b/i],
  ["evidence", /\bevidence\b|\bproof\b|\bsupport(?:s|ed|ing)?\b|\bbased on\b|how do (?:you|we) know|what shows/i],
  ["confidence", /\bconfiden|\bsure\b|\bcertain(?:ty)?\b|how likely|how accurate|\breliable\b/i],
  ["watch", /watch (?:out )?for|look out|warning signs|red flags|\bsigns\b|be careful of|what to look/i],
  ["why", /\bwhy\b|\bsuspicious\b|what makes|what'?s wrong/i],
  ["meaning", /mean(?:s)? for me|what does (?:this|it|that) mean|\bworr|am i (?:safe|at risk|ok)|is (?:this|it|that) (?:safe|a scam|dangerous|legit|real|ok)/i],
  ["actions", /what (?:should|can|do) i do|next steps?|what now|what next|how do i (?:fix|stop|protect)|\brecommend|\bshould i\b|\bactions?\b/i],
  ["findings", /what did (?:you|magnum(?: di)?|it|apollo(?:\s?sg)?) find|\bfindings?\b|what was found|\bsummar|\boverview\b|tell me (?:more|about)|\bexplain\b|what happened/i],
];
const WATCH_WORDS = /\b(watch|look out|be wary|be careful|beware|signs?|suspicious|unexpected)\b/i;

// Something new: emails first (so their domain isn't also counted as a link), then links, then phone numbers.
const NEW_ITEMS: [string, RegExp][] = [
  ["an email address", /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g],
  ["a link", /\bhttps?:\/\/\S+|\bwww\.\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|info|biz|io|app|xyz|top|online|site|shop|link|co|au|uk|nz)(?:\/\S*)?\b/gi],
  ["a phone number", /(?:^|[^\w.])(\+?\d[\d ()-]{6,}\d)(?![\w.])/g],
];
export const NEW_ITEM_NOTE = (items: string) => `You've mentioned something new (${items}) that wasn't part of this investigation. ApolloSG doesn't reopen a finished investigation, so its findings don't cover it and nothing new has been checked. To have it checked, start a new check.`;

const bullets = (lines: string[]) => lines.filter(Boolean).map((line) => `• ${line}`).join("\n");
const join = (labels: string[]) => labels.length === 1 ? labels[0] : `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;

export function followUpIntent(question: string): string | null {
  return INTENTS.find(([, pattern]) => pattern.test(question ?? ""))?.[0] ?? null;
}

export function newItems(question: string): string[] {
  let text = question ?? "";
  const found: string[] = [];
  for (const [label, pattern] of NEW_ITEMS) {
    const hits = [...text.matchAll(pattern)].map((m) => m[1] ?? m[0]);
    const real = label === "a phone number" ? hits.filter((hit) => (hit.match(/\d/g) ?? []).length >= 8) : hits;
    if (real.length) { found.push(label); text = text.replace(pattern, " "); }
  }
  return found;
}

/** A Magnum DI result that is complete or partial — not one still waiting for the person's answer. */
export function isFinished(response: HigginsResponse | null | undefined): response is HigginsResponse {
  return !!response && (response.completion === "complete" || response.completion === "partial") && !response.question;
}

export function investigationFollowUp(response: HigginsResponse, sources: SourceReference[], question: string, turnId = "", answeredBy: string | null = null): FollowUpAnswer {
  const name = investigatorName(answeredBy);
  const overview = (response.overview ?? "").trim();
  const assessment = (ASSESSMENT_TEXT[response.assessment] ?? "").replace("{name}", name);
  const attention = ATTENTION_TEXT[response.attention] ?? "";
  const reason = (response.attentionReason ?? "").trim();
  const findings = (response.findings ?? []).filter((f) => (f.text ?? "").trim());
  const actions = (response.actions ?? []).filter((a) => (a.instruction || a.label || "").trim())
    .sort((a, b) => Number(a.id !== response.recommendedActionId) - Number(b.id !== response.recommendedActionId));
  const uncertainties = (response.uncertainties ?? []).map((u) => String(u).trim()).filter(Boolean);
  const scope = (response.scope ?? "").trim();
  const bySource = new Map(sources.map((s) => [s.id, s]));
  const intent = followUpIntent(question);
  let limitation = false;
  let answer: string;

  const findingLine = (f: HigginsResponse["findings"][number], detail = false) => {
    let line = `${f.text} (${(BASIS_TEXT[f.basis] ?? "basis not recorded").replace("{name}", name)}; ${f.confidence ?? "unknown"} confidence`;
    if (detail) {
      const count = (f.evidenceIds ?? []).length;
      const titles = (f.sourceIds ?? []).map((id) => bySource.get(id)?.title).filter(Boolean);
      line += count ? `; ${count} evidence item${count !== 1 ? "s" : ""}` : "; no evidence item cited";
      line += titles.length ? `; source: ${titles.join(", ")}` : "";
    }
    return `${line})`;
  };
  const paragraphs = (parts: string[]) => parts.filter(Boolean).join("\n\n");

  if (intent === "recheck") {
    answer = `${name}'s investigation is finished, so it isn't re-assessed — any fresh reading Apollo took is shown with the action, and what the investigation established is unchanged.` + (overview ? `\n\n${overview}` : "");
  } else if (intent === "meaning") {
    answer = paragraphs([overview, [assessment, attention, reason].filter(Boolean).join(" ")]);
  } else if (intent === "why") {
    answer = paragraphs([reason || assessment, findings.length ? `What ${name} found:\n${bullets(findings.map((f) => findingLine(f)))}` : ""]);
    if (!findings.length && !reason) { answer = `${name}'s investigation doesn't record specific reasons beyond its overall result. ${overview}`; limitation = true; }
  } else if (intent === "evidence") {
    answer = findings.length ? `Each finding and what supports it:\n${bullets(findings.map((f) => findingLine(f, true)))}` : `${name} didn't record individual findings with supporting evidence for this investigation.`;
    limitation = !findings.length;
  } else if (intent === "confidence") {
    const counts = (["high", "medium", "low"] as const).map((level) => [level, findings.filter((f) => f.confidence === level).length] as const).filter(([, n]) => n);
    answer = paragraphs([assessment ? `Overall: ${assessment}` : "", findings.length ? `Confidence in the findings: ${counts.map(([level, n]) => `${n} ${level}`).join(", ")}` : "",
      uncertainties.length ? `What it couldn't establish:\n${bullets(uncertainties)}` : ""]) || `${name} didn't record a confidence level for this investigation.`;
  } else if (intent === "watch") {
    const watch = actions.filter((a) => WATCH_WORDS.test(`${a.label ?? ""} ${a.instruction ?? ""}`)).map((a) => a.instruction || a.label);
    if (watch.length) answer = `What ${name} says to look out for:\n${bullets(watch)}`;
    else {
      answer = `${name}'s investigation doesn't list specific warning signs to watch for.`; limitation = true;
      if (actions.length) answer += ` What it does recommend:\n${bullets(actions.map((a) => `${a.label}: ${a.instruction}`))}`;
    }
  } else if (intent === "actions") {
    answer = actions.length ? `What ${name} recommends:\n${bullets(actions.map((a) => a.label ? `${a.label}: ${a.instruction}` : a.instruction))}` : `${name} didn't recommend any action for this. ${attention}`.trim();
  } else if (intent === "not_established") {
    answer = paragraphs([uncertainties.length ? `What ${name} couldn't establish:\n${bullets(uncertainties)}` : `${name} didn't record anything it was unable to establish.`, scope ? `What it checked: ${scope}` : ""]);
  } else if (intent === "sources") {
    const listed = sources.filter((s) => s.url).map((s) => `${s.title || s.url} — ${s.url} (${s.authority ?? "unknown"} source)`);
    answer = listed.length ? `The sources ${name} used:\n${bullets(listed)}` : `${name} didn't use any outside sources for this; its findings come from the evidence you submitted.`;
  } else if (intent === "findings") {
    answer = paragraphs([overview, findings.length ? `Findings:\n${bullets(findings.map((f) => findingLine(f)))}` : ""]);
  } else {
    limitation = true;
    answer = `I can only answer from what ${name}'s investigation established, and it doesn't answer that directly.` + (overview ? ` Here's what it did establish: ${overview}` : "");
  }
  const mentioned = newItems(question);
  if (mentioned.length) answer = `${NEW_ITEM_NOTE(join(mentioned))}\n\n${answer.trim()}`;
  return { turnId, question, answer: answer.trim(), intent: intent ?? "unanswered", limitation, newItems: mentioned, answeredBy: "apollo" };
}
