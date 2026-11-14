import { recordSuccessfulSLMInference, recordFailedSLMInference } from "../domain/slm/sharedRuntime.ts";
import type { SLMAdapter } from "../domain/slm/index.ts";
export interface ChatPassage { id: string; title: string; url: string | null; text: string; publishedAt: string | null; checkedAt: string | null; freshness: string }
export interface ChatContext { caseScopeId?: string | null; kind: string; conversationId: string; turnId: string; scope: string; userStatement: string; passages: ChatPassage[]; deviceObservation: unknown; caseFindings: unknown[]; expiresAt: string; navigation: { route: string; label: string }[] }
export interface ChatAnswer { answer: string; citations: string[]; quotations: { passageId: string; text: string }[]; clarification: string | null; uncertainty: string[] }
export function validateChat(value: unknown, packet: ChatContext): ChatAnswer {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw Error("Higgins returned invalid output");
  const a = value as ChatAnswer;
  if (Object.keys(a).some(k => !["answer", "citations", "quotations", "clarification", "uncertainty"].includes(k)) || typeof a.answer !== "string" || !a.answer.trim() || a.answer.length > 6000 ||
      !Array.isArray(a.citations) || a.citations.length > 6 || a.citations.some(id => !packet.passages.some(p => p.id === id)) ||
      !Array.isArray(a.quotations) || a.quotations.length > 6 || a.quotations.some(q => !q || typeof q.text !== "string" || !q.text || Object.keys(q).some(k => !["passageId", "text"].includes(k)) || !packet.passages.some(p => p.id === q.passageId && p.text.includes(q.text))) ||
      !(a.clarification === null || typeof a.clarification === "string") || !Array.isArray(a.uncertainty) || a.uncertainty.length > 8 || a.uncertainty.some(x => typeof x !== "string")) throw Error("Higgins response failed grounding validation");
  if (packet.passages.length && !packet.caseFindings.length && !a.citations.length && !a.clarification && !a.uncertainty.length) throw Error("Higgins did not cite the supplied knowledge");
  if (!packet.passages.length && !packet.deviceObservation && !packet.caseFindings.length && !a.clarification && !a.uncertainty.length) throw Error("Higgins did not acknowledge missing context");
  if (a.citations.some(id => packet.passages.some(p => p.id === id && ["historical", "stale", "unknown"].includes(p.freshness))) && !a.uncertainty.length) throw Error("Higgins did not disclose stale or unverified knowledge");
  const allowedLinks = [...packet.passages.map(p => p.url ?? ""), ...packet.navigation.map(n => n.route)];
  for (const url of a.answer.match(/https?:\/\/[^\s)\]"<>]+/g) ?? []) if (!allowedLinks.includes(url.replace(/[.,;]+$/, ""))) throw Error("Higgins invented a link");
  if (/\bI (?:have )?(?:blocked|unblocked|reported|deleted|changed|verified|installed|scanned)\b/i.test(a.answer)) throw Error("Higgins claimed an action that ordinary chat cannot perform");
  const observation = packet.deviceObservation as { protectionOn?: boolean; protection_on?: boolean } | null;
  const enabled = observation?.protectionOn ?? observation?.protection_on;
  if (enabled === false && /\b(?:protection is (?:on|active|enabled)|you are protected)\b/i.test(a.answer)) throw Error("Higgins contradicted the live device reading");
  if (enabled === true && /\bprotection is (?:off|disabled)\b/i.test(a.answer)) throw Error("Higgins contradicted the live device reading");
  if (/\b(?:completely safe|guaranteed safe|fully protected|no risk|100% safe)\b/i.test(a.answer)) throw Error("Higgins added a safety guarantee");
  // Numeric values and negations in authoritative records may not be changed.
  for (const record of packet.caseFindings) {
    if (!record || typeof record !== "object") throw Error("Higgins received invalid recorded findings");
    const row = record as { findings?: { text?: string }[]; uncertainties?: string[]; outcome?: string; headline?: string };
    const locked = [...(row.findings ?? []).map(f => f.text).filter((t): t is string => !!t), ...(row.uncertainties ?? []), ...(row.headline ? [row.headline] : [])];
    if ((!locked.length && !a.clarification && !a.uncertainty.length) || locked.some(text => !a.answer.includes(text))) throw Error("Higgins did not preserve the recorded finding text and uncertainty");
    if (row.outcome === "not_scam" && /(?:this|it) is (?:likely )?a scam/i.test(a.answer)) throw Error("Higgins contradicted the recorded verdict");
    if (row.outcome === "scam" && /(?:this|it) is (?:not|unlikely to be) a scam/i.test(a.answer)) throw Error("Higgins contradicted the recorded verdict");
  }
  return a;
}
export async function generateChat(packet: ChatContext, adapter: SLMAdapter | null, history: { role: string; content: string; createdAt: string; conversationId: string; caseScopeId?: string | null }[] = [], deadlineAt = Date.now() + 45000, signal?: AbortSignal): Promise<ChatAnswer> {
  if (!adapter) throw Error("Higgins’ on-device model is unavailable. Retry after checking Higgins in Settings.");
  deadlineAt = Math.min(deadlineAt, Date.parse(packet.expiresAt));
  if (!Number.isFinite(deadlineAt) || deadlineAt <= Date.now()) throw Error("Higgins request expired. Please retry.");
  const boundedHistory = history.filter(t => t.conversationId === packet.conversationId && (t.caseScopeId ?? null) === (packet.caseScopeId ?? null) && Date.now() - Date.parse(t.createdAt) >= 0 && Date.now() - Date.parse(t.createdAt) < 3600000).slice(-8);
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) throw Error("Higgins request was cancelled");
  signal?.addEventListener("abort", abort, { once: true });
  let usedPacket = { ...packet, passages: packet.passages.slice(0, 6) };
  const turns = [...boundedHistory];
  const makeRequest = () => ({ signal: controller.signal, role: "ask_higgins" as const, operation: "grounded_chat" as const, question: packet.userStatement,
    evidence: usedPacket.passages.map(p => ({ evidenceId: p.id, text: JSON.stringify(p) })), chatContext: { ...usedPacket, history: turns }, deadlineAt });
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => { timer = setTimeout(() => { controller.abort(); reject(Error("Higgins took too long. Please retry.")); }, Math.max(0, deadlineAt - Date.now())); });
  const work = async () => {
    while (adapter.canFitAsync && !await adapter.canFitAsync(makeRequest())) {
      if (controller.signal.aborted) throw Error("Higgins request expired");
      if (turns.length) turns.shift();
      else if (usedPacket.passages.length) usedPacket = { ...usedPacket, passages: usedPacket.passages.slice(0, -1) };
      else throw Error("Higgins cannot fit the complete authoritative context. Please narrow your question.");
    }
    return adapter.infer(makeRequest());
  };
  let value: unknown;
  try { value = await Promise.race([work(), timeout]); }
  finally { if (timer) clearTimeout(timer); signal?.removeEventListener("abort", abort); }
  if (controller.signal.aborted || Date.now() >= deadlineAt) throw Error("Higgins request expired. Please retry.");
  try { const answer = validateChat(value, usedPacket); recordSuccessfulSLMInference(adapter); return answer; }
  catch (error) { recordFailedSLMInference(adapter, "invalid_output"); throw error; }
}

export function scopedCaseRecords(saved: { ownerId?: string; caseId: string; response: { outcome?: unknown; findings: unknown[]; uncertainties: string[]; revision: number } } | null, ownerId: string, caseId: string): unknown[] {
  if (!saved || saved.ownerId !== ownerId || saved.caseId !== caseId) throw Error("The retained findings are not available for this device");
  return [{ outcome: saved.response.outcome, findings: saved.response.findings, uncertainties: saved.response.uncertainties, revision: saved.response.revision }];
}
