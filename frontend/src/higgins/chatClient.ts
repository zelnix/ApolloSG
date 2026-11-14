import { getDeviceIdentity } from "@/src/auth/deviceIdentity";
import { ApiError, apiDelete, apiGet, apiPost } from "@/src/api/client";
import { getSharedSLM } from "@/src/domain/slm/sharedRuntime";
import { retrieveLocalProduct } from "./localKnowledgeCache";
import { classifyIntent } from "./intentRouter";
import { generateChat, scopedCaseRecords, type ChatContext } from "./groundedChat";
import type { NavLink } from "./appMap";
import type { DeviceSnapshot } from "./deviceSnapshot";

export interface HigginsChatAction { kind: "app_destination"; destination: "ask_higgins" | "higgins_case"; label: string; purpose: string }
export interface HigginsContextUse { source: string; status: string; provenance: string[]; observedAt: string | null }
/** Context is authenticated/retrieved by services; ordinary conversational generation is on-device. */
export interface HigginsChatReply { caseScopeId?: string | null; grounding?: { passages: import("./groundedChat").ChatPassage[]; citations: string[] }; turnId: string; conversationId: string; answer: string; evidenceBasis: string[]; uncertainty: string[]; clarification: string | null; contextUsed: HigginsContextUse[]; suggestedActions: HigginsChatAction[]; navigation: NavLink[]; investigationAvailable: boolean; investigativeWorkStarted: false; retention: { serverContentExpiresAt: string; localContentMaxSeconds: 3600; receiptOnlyAfterExpiry: true } }
/** `links` are validated Apollo destinations Higgins offered for this answer. */
export interface HigginsChatMessage { ownerId?: string; caseScopeId?: string | null; id: string; turnId: string; role: "user" | "higgins"; content: string; createdAt: string; conversationId: string; links?: NavLink[];
  /** The answer is in a source's own words (a scam alert, a Learn article, ApolloSG's KB): Luddish never rewords it. */
  quoted?: boolean; grounding?: { passages: import("./groundedChat").ChatPassage[]; citations: string[] } }

/** Where an answer is shown in the source's own words (rule book HIG-03, HIG-04, HIG-06). */
export const QUOTED_BASES = ["recognised_government_feed_cache", "scam_alert_card", "learn_with_higgins_catalogue", "apollo_knowledge_base"];
export const isQuoted = (reply: Pick<HigginsChatReply, "evidenceBasis">) => (reply.evidenceBasis ?? []).some((basis) => QUOTED_BASES.includes(basis));

const pendingChat = new Map<string, AbortController>();
export function cancelHigginsChat() { for (const controller of pendingChat.values()) controller.abort(); }

export async function askHiggins(message: string, conversationId: string, turnId: string, previousTurnIds: string[], deviceSnapshot?: DeviceSnapshot, history: HigginsChatMessage[] = [], localCase?: { ownerId: string; caseId: string; records?: unknown[] }) {
  const ownerId = (await getDeviceIdentity())?.deviceId;
  if (!ownerId) throw Error("Higgins cannot establish this device’s chat scope");
  history = history.filter(m => m.ownerId === ownerId);
  const controller = new AbortController();
  const pendingKey = `${conversationId}:${turnId}`; pendingChat.set(pendingKey, controller);
  try {
  const deadline = Date.now() + 45000;
  let packet: ChatContext;
  let offline = false;
  try { packet = await apiPost<ChatContext>("/higgins/chat/context", "higgins_context", { turnId, message, conversationId, previousTurnIds, ...(deviceSnapshot ? { deviceSnapshot } : {}) }); }
  catch (cause) {
    const intent = classifyIntent(message, [], false);
    if (!(cause instanceof ApiError) || cause.status !== 0 || !["local_knowledge", "local_diagnostic"].includes(intent.route)) throw cause;
    offline = true;
    packet = { kind: "grounded_chat", conversationId, turnId, scope: "in_scope", userStatement: message, passages: retrieveLocalProduct(message), deviceObservation: deviceSnapshot ?? null, caseFindings: [], expiresAt: new Date(deadline).toISOString(), navigation: [] };
  }
  if (controller.signal.aborted) throw Error("Higgins request cancelled");
  if (packet.kind === "investigation_required") {
    // Existing authenticated submission, never an ordinary conversational model call.
    return apiPost<HigginsChatReply>("/higgins/chat", "higgins_chat", { turnId, message, conversationId, previousTurnIds, ...(deviceSnapshot ? { deviceSnapshot } : {}) });
  }
  if (localCase) {
    if (localCase.ownerId !== ownerId) throw Error("Higgins case owner mismatch");
    const { getInvestigation } = await import("../investigation/deviceStore");
    const saved = await getInvestigation(localCase.caseId);
    packet = { ...packet, caseScopeId: localCase.caseId, caseFindings: scopedCaseRecords(saved, ownerId, localCase.caseId) };
  }
  if (packet.conversationId !== conversationId || packet.turnId !== turnId) throw Error("Higgins context mismatch");
  const previousPassages = history.filter(m => m.conversationId === conversationId && (m.caseScopeId ?? null) === (packet.caseScopeId ?? null) && Date.now() - Date.parse(m.createdAt) >= 0 && Date.now() - Date.parse(m.createdAt) < 3600000).slice(-2).flatMap(m => m.grounding?.passages ?? []);
  packet.passages = [...new Map([...packet.passages, ...previousPassages.filter(p => !packet.passages.some(current => current.id === p.id))].map(p => [p.id, p])).values()].slice(0, 6);
  if (packet.passages.length < 6) packet.passages = [...packet.passages, ...retrieveLocalProduct(message)].slice(0, 6);
  const answer = await generateChat(packet, getSharedSLM(), history, deadline, controller.signal);
  if ((await getDeviceIdentity())?.deviceId !== ownerId) throw Error("Higgins device scope changed");
  return { caseScopeId: packet.caseScopeId, turnId, conversationId, answer: (offline ? "Offline: using this installed version’s product guide and this device’s available readings. Current online information is unavailable.\n\n" : "") + answer.answer + answer.quotations.map(q => `\n\n“${q.text}”`).join("") + answer.uncertainty.map(note => `\n\n${note}`).join(""), clarification: answer.clarification,
    grounding: { passages: packet.passages.filter(p => answer.citations.includes(p.id)), citations: answer.citations },
    evidenceBasis: ["on_device_grounded_chat"], uncertainty: answer.uncertainty, contextUsed: [], suggestedActions: [],
    navigation: packet.navigation, investigationAvailable: false, investigativeWorkStarted: false,
    retention: { serverContentExpiresAt: packet.expiresAt, localContentMaxSeconds: 3600, receiptOnlyAfterExpiry: true } } as HigginsChatReply;
  } finally { if (pendingChat.get(pendingKey) === controller) pendingChat.delete(pendingKey); }
}
export function higginsHistory(deviceId: string) {
  return apiGet<{ items: HigginsChatMessage[]; receipts: unknown[]; kind: "ordinary_chat" }>(`/higgins/chat/history?device_id=${encodeURIComponent(deviceId)}`);
}
export function clearHigginsHistory(deviceId: string) {
  cancelHigginsChat();
  return apiDelete<{ deleted: number; investigationsDeleted: 0 }>(`/ask/history?device_id=${encodeURIComponent(deviceId)}`);
}
export function rememberHigginsContext(value: { category: "recent_outcome" | "protection_state" | "preference" | "goal" | "permission"; summary: string; provenance: "device_observation" | "apollo_outcome" | "user_report" | "user_preference"; observedAt?: string }) {
  return apiPost<{ item: unknown }>("/higgins/context", "higgins_context", value);
}
