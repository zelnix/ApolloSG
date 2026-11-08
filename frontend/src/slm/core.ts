/**
 * On-device small language model (SLM) — the rules, as pure functions.
 *
 * The SLM is the phone's own model (Gemini Nano via ML Kit on Android, Apple Foundation Models on iOS — see
 * modules/apollo-slm). Nothing it is given or writes leaves the phone. It is ADVISORY ONLY:
 *
 *   1. It never decides. Apollo's state, verdict, Gate result and Higgins' action come from the fixed rules exactly
 *      as before (OPERATING_RULES.md, Gate checks rule 4). No SLM output is an input to any of them.
 *   2. Pre-screen: it may point at words in the message — a request to act, a claimed organisation, urgency. Each
 *      pointer must quote the message verbatim; a quote that isn't in the text, or that sits under a negation
 *      ("we will never ask…"), is dropped. What survives is shown as "also noticed on this phone" and can only
 *      suggest running a full check. It never lowers, raises or clears anything.
 *   3. Explain: it may re-word a result that is already settled. The re-wording is checked against the settled
 *      result; anything that adds a fact, a number, a link, reassurance ("safe"), or contradicts the advice is
 *      rejected, and the fixed wording is shown as it always was.
 *   4. One call, no retry, no other model. A failure is reported, never papered over.
 *
 * This file imports nothing from React Native so it runs under `node --test`.
 */
import { CREDENTIAL_PATTERNS } from "../domain/privacyPolicy.ts";
import { clauses, negated } from "../domain/requestSignals.ts";

export const SLM_MAX_INPUT_CHARS = 4000;
export const SLM_TIMEOUT_MS = 12_000;

// ── Input preparation ─────────────────────────────────────────────────────────

/** Credentials and codes are removed even on the phone, so the model can't repeat one back onto the screen. */
export function prepareSlmInput(text: string): string {
  let out = String(text ?? "");
  for (const { pattern } of CREDENTIAL_PATTERNS) {
    out = out.replace(new RegExp(pattern.source, pattern.flags.includes("g") ? pattern.flags : pattern.flags + "g"), "[credential removed]");
  }
  out = out.replace(/\s+/g, " ").trim();
  return out.length > SLM_MAX_INPUT_CHARS ? out.slice(0, SLM_MAX_INPUT_CHARS) : out;
}

/** Pulls the first JSON object out of a model reply (models sometimes wrap it in ``` fences or add a sentence). */
export function extractJsonObject(raw: string): unknown {
  const s = String(raw ?? "").replace(/```(?:json)?/gi, "");
  const start = s.indexOf("{");
  if (start < 0) return null;
  let depth = 0, inStr = false, esc = false;
  for (let i = start; i < s.length; i++) {
    const c = s[i];
    if (inStr) { if (esc) esc = false; else if (c === "\\") esc = true; else if (c === '"') inStr = false; continue; }
    if (c === '"') inStr = true;
    else if (c === "{") depth++;
    else if (c === "}" && --depth === 0) {
      try { return JSON.parse(s.slice(start, i + 1)); } catch { return null; }
    }
  }
  return null;
}

const norm = (s: string) => s.toLowerCase().replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/\s+/g, " ").trim();

/** Where the quote sits in the text (normalised), or -1. Quotes shorter than 4 characters prove nothing. */
export function locateQuote(text: string, quote: string): number {
  const q = norm(quote ?? "");
  if (q.length < 4) return -1;
  return norm(text).indexOf(q);
}

// ── Pre-screen ───────────────────────────────────────────────────────────────

export type SlmRequestKind = "send_money" | "share_code" | "share_details" | "install_app" | "remote_access" | "call_or_reply";
export const SLM_REQUEST_KINDS: readonly SlmRequestKind[] = ["send_money", "share_code", "share_details", "install_app", "remote_access", "call_or_reply"];

export const SLM_REQUEST_LABEL: Record<SlmRequestKind, string> = {
  send_money: "Asks you to send or pay money",
  share_code: "Asks for a code",
  share_details: "Asks for personal or account details",
  install_app: "Asks you to install something",
  remote_access: "Asks for access to your device",
  call_or_reply: "Asks you to call or reply",
};

export type SlmHint =
  | { type: "request"; kind: SlmRequestKind; quote: string }
  | { type: "organisation"; name: string; quote: string }
  | { type: "urgency"; quote: string };

export interface SlmPreScreen {
  hints: SlmHint[];
  /** Pointers the model gave that weren't in the message's own words (or were negated) — dropped, only counted. */
  dropped: number;
}

export const PRE_SCREEN_INSTRUCTIONS = [
  "You read one text message and point at words in it. You do not judge whether it is a scam.",
  "Reply with JSON only, in exactly this shape:",
  '{"requests":[{"kind":"send_money|share_code|share_details|install_app|remote_access|call_or_reply","quote":"..."}],',
  ' "organisation":{"name":"...","quote":"..."} or null, "urgency":{"quote":"..."} or null}',
  "Every quote must be copied exactly, word for word, from the message. If nothing fits, use [] or null.",
  "Only list a request if the message asks the reader to do it. A sentence saying it will never ask is not a request.",
].join("\n");

export function preScreenPrompt(preparedText: string): string {
  return `Message:\n"""${preparedText}"""`;
}

/** The clause holding the quote, and whether a negation governs it ("No one will ever ask you to send …"). */
function quoteIsNegated(text: string, quote: string): boolean {
  const q = norm(quote);
  for (const clause of clauses(text)) {
    const at = norm(clause).indexOf(q);
    if (at >= 0) return negated(norm(clause), at);
  }
  return false;
}

export function parsePreScreen(raw: string, preparedText: string): SlmPreScreen {
  const obj = extractJsonObject(raw) as Record<string, unknown> | null;
  const hints: SlmHint[] = [];
  let dropped = 0;
  if (!obj || typeof obj !== "object") return { hints, dropped };
  const seen = new Set<string>();
  const keep = (h: SlmHint) => { const k = JSON.stringify(h).toLowerCase(); if (!seen.has(k)) { seen.add(k); hints.push(h); } };

  const reqs = Array.isArray(obj.requests) ? obj.requests.slice(0, 8) : [];
  for (const r of reqs as Array<Record<string, unknown>>) {
    const kind = String(r?.kind ?? "") as SlmRequestKind;
    const quote = String(r?.quote ?? "").trim();
    if (!SLM_REQUEST_KINDS.includes(kind) || locateQuote(preparedText, quote) < 0 || quoteIsNegated(preparedText, quote)) { dropped++; continue; }
    keep({ type: "request", kind, quote });
  }
  const org = obj.organisation as Record<string, unknown> | null | undefined;
  if (org && typeof org === "object") {
    const name = String(org.name ?? "").trim().slice(0, 60);
    const quote = String(org.quote ?? "").trim();
    // The name itself must be in the message too: the model may not supply an organisation the text doesn't name.
    if (name && locateQuote(preparedText, quote) >= 0 && norm(quote).includes(norm(name))) keep({ type: "organisation", name, quote });
    else dropped++;
  }
  const urg = obj.urgency as Record<string, unknown> | null | undefined;
  if (urg && typeof urg === "object") {
    const quote = String(urg.quote ?? "").trim();
    if (locateQuote(preparedText, quote) >= 0) keep({ type: "urgency", quote });
    else dropped++;
  }
  return { hints, dropped };
}

/** The fixed-rule signals each SLM request kind corresponds to. Used only to avoid repeating what Apollo already said. */
export interface FixedSignalsView {
  paymentRequest?: boolean; moneyRequest?: boolean; giftCards?: boolean; crypto?: boolean;
  codeRequest?: boolean; identityRequest?: boolean; loginRequest?: boolean;
  remoteAccess?: boolean; callbackRequest?: boolean; replyRequest?: string | null;
  claimedBrand?: string | null; urgency?: boolean; timePressure?: string | null; deadlineThreat?: boolean;
}

function alreadyCovered(h: SlmHint, s: FixedSignalsView): boolean {
  if (h.type === "organisation") return !!s.claimedBrand;
  if (h.type === "urgency") return !!(s.urgency || s.timePressure || s.deadlineThreat);
  switch (h.kind) {
    case "send_money": return !!(s.paymentRequest || s.moneyRequest || s.giftCards || s.crypto);
    case "share_code": return !!s.codeRequest;
    case "share_details": return !!(s.identityRequest || s.loginRequest);
    case "install_app": return !!s.remoteAccess;
    case "remote_access": return !!s.remoteAccess;
    case "call_or_reply": return !!(s.callbackRequest || s.replyRequest);
  }
}

export interface SlmAdvisory {
  /** Verified pointers the fixed rules hadn't already named. Shown as "also noticed on this phone". */
  extra: SlmHint[];
  /** True when a verified request to act was found that the fixed rules didn't name: suggest a full check. */
  suggestFullCheck: boolean;
  /** Always the same: what the SLM changed about Apollo's result. */
  changedResult: false;
}

/** Combine with the fixed-rule reading. Takes no state and returns none: the SLM cannot move a result. */
export function advisoryFor(pre: SlmPreScreen, signals: FixedSignalsView): SlmAdvisory {
  const extra = pre.hints.filter((h) => !alreadyCovered(h, signals));
  return { extra, suggestFullCheck: extra.some((h) => h.type === "request"), changedResult: false };
}

export function hintLine(h: SlmHint): string {
  if (h.type === "request") return `${SLM_REQUEST_LABEL[h.kind]}: “${h.quote}”`;
  if (h.type === "organisation") return `Says it's from ${h.name}: “${h.quote}”`;
  return `Puts you under time pressure: “${h.quote}”`;
}

// ── Explain (re-word a settled result) ───────────────────────────────────────

export interface SettledResult {
  /** The state's user-facing name, exactly as Apollo shows it (STATE_NAME). */
  stateName: string;
  verdict: string;
  why: string[];
  recommendation: string;
}

export const EXPLAIN_MAX_WORDS = 90;

export const EXPLAIN_INSTRUCTIONS = [
  "You are Higgins, ApolloSG's friendly guide. Re-word a result that Apollo has already settled, for an older reader.",
  `Use plain, warm, short sentences, at most ${EXPLAIN_MAX_WORDS} words. Plain text only, no lists or headings.`,
  "Keep the meaning exactly. Do not add facts, numbers, links, names or reasons that are not in the result.",
  "Never say anything is safe, genuine, legitimate or nothing to worry about. Keep the advice of what to do.",
].join("\n");

export function explainPrompt(r: SettledResult): string {
  const why = r.why.slice(0, 6).map((w) => `- ${w}`).join("\n");
  return `Result: ${r.stateName}\nWhat Apollo found: ${r.verdict}\nWhy:\n${why}\nWhat to do: ${r.recommendation}`;
}

const REASSURANCE = /\b(safe|safely|harmless|genuine|legit(?:imate)?|trustworthy|authentic|nothing to worry|no need to worry|no risk|risk[- ]free|guarantee[ds]?|100\s?%|definitely fine|all clear|you can trust)\b/i;
const DISMISSAL = /\b(ignore (?:this|the) (?:warning|advice|result)|no need to (?:check|verify|act)|go ahead and (?:pay|click|reply|call|send))\b/i;
const URLISH = /\b(?:https?:\/\/|www\.)\S+|\b[a-z0-9-]+\.(?:com|net|org|au|io|co|xyz|info|app)\b/i;

export type ExplainCheck = { ok: true; text: string } | { ok: false; reason: "empty" | "too_long" | "reassurance" | "dismissal" | "new_link" | "new_number" };

/** Accept the re-wording only if it can't change what the result means. Otherwise the fixed wording is shown. */
export function checkExplanation(raw: string, r: SettledResult): ExplainCheck {
  const text = String(raw ?? "").replace(/```[a-z]*|```/gi, "").replace(/^[\s>*#-]+/gm, "").replace(/\s+/g, " ").trim();
  if (!text) return { ok: false, reason: "empty" };
  if (text.split(" ").length > EXPLAIN_MAX_WORDS + 20) return { ok: false, reason: "too_long" };
  const source = [r.stateName, r.verdict, ...r.why, r.recommendation].join(" ");
  // A reassuring word is allowed only when negated just before it ("isn't safe", "not genuine", "never guaranteed").
  for (const m of text.matchAll(new RegExp(REASSURANCE.source, "gi"))) {
    const before = text.slice(Math.max(0, (m.index ?? 0) - 40), m.index).toLowerCase().replace(/[\u2018\u2019]/g, "'");
    if (!/\b(?:not|isn'?t|aren'?t|wasn'?t|never|no longer|can'?t be|cannot be|may not be|might not be)\s+(?:\w+\s+){0,2}$/.test(before)) return { ok: false, reason: "reassurance" };
  }
  if (DISMISSAL.test(text)) return { ok: false, reason: "dismissal" };
  const link = text.match(URLISH);
  if (link && !norm(source).includes(norm(link[0]))) return { ok: false, reason: "new_link" };
  for (const n of text.match(/\d[\d,.:$%]*/g) ?? []) {
    if (!source.includes(n.replace(/[.,:]$/, ""))) return { ok: false, reason: "new_number" };
  }
  return { ok: true, text };
}

// ── Model identity ───────────────────────────────────────────────────────────

/** Which model answered: the OS picks and updates it, so ApolloSG records it rather than pinning it. */
export interface SlmModelInfo {
  engine: "gemini_nano_mlkit" | "apple_foundation_models" | "none";
  /** Android: the Gemini Nano version AICore reports. iOS: null (Apple publishes none; osVersion identifies it). */
  modelName: string | null;
  osVersion: string | null;
}

export function slmModelLabel(m: SlmModelInfo): string {
  const os = m.osVersion ? ` · ${m.osVersion}` : "";
  if (m.engine === "gemini_nano_mlkit") return `Gemini Nano${m.modelName ? ` (${m.modelName})` : " (version not reported)"}${os}`;
  if (m.engine === "apple_foundation_models") return `Apple on-device model${os}`;
  return "No on-device model";
}

export type SlmPurpose = "explain" | "pre_screen";

/** One on-device call, as kept in the phone's local record. Never the message, the prompt or the answer. */
export interface SlmCallRecord extends SlmModelInfo {
  at: string;
  purpose: SlmPurpose;
  elapsedMs: number | null;
  /** "ok", or why nothing was shown: timeout, failed, rejected_reassurance, … */
  outcome: string;
}

export const SLM_CALL_LOG_LIMIT = 50;

/** Newest first, capped. Drops any field that isn't part of the record so text can't leak in. */
export function appendCallRecord(log: SlmCallRecord[], rec: SlmCallRecord): SlmCallRecord[] {
  const clean: SlmCallRecord = {
    at: rec.at, purpose: rec.purpose, engine: rec.engine, modelName: rec.modelName, osVersion: rec.osVersion,
    elapsedMs: rec.elapsedMs, outcome: String(rec.outcome).slice(0, 40),
  };
  return [clean, ...log].slice(0, SLM_CALL_LOG_LIMIT);
}

/** One line for Settings: how the recent on-device calls went, and which model(s) answered them. */
export function summariseCallLog(log: SlmCallRecord[]): string | null {
  if (!log.length) return null;
  const shown = log.filter((r) => r.outcome.startsWith("ok")).length;
  const rejected = log.filter((r) => r.outcome.startsWith("rejected_")).length;
  const other = log.length - shown - rejected;
  const models = [...new Set(log.filter((r) => r.engine !== "none").map((r) => slmModelLabel(r)))];
  const parts = [`${shown} shown`, rejected ? `${rejected} rejected` : "", other ? `${other} not run` : ""].filter(Boolean).join(", ");
  return `Last ${log.length} on-device ${log.length === 1 ? "call" : "calls"}: ${parts}.${models.length ? ` Model: ${models.join("; ")}.` : ""}`;
}
