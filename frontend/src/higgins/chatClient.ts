import { apiDelete, apiGet, apiPost } from "@/src/api/client";
import type { NavLink } from "./appMap";
import type { DeviceSnapshot } from "./deviceSnapshot";

export interface HigginsChatAction { kind: "app_destination"; destination: "ask_higgins" | "higgins_case"; label: string; purpose: string }
export interface HigginsContextUse { source: string; status: string; provenance: string[]; observedAt: string | null }
/** Every answer comes from Apollo's own records or its knowledge base: Ask Higgins makes no AI call. */
export interface HigginsChatReply { turnId: string; conversationId: string; answer: string; evidenceBasis: string[]; uncertainty: string[]; clarification: string | null; contextUsed: HigginsContextUse[]; suggestedActions: HigginsChatAction[]; navigation: NavLink[]; investigationAvailable: boolean; investigativeWorkStarted: false; retention: { serverContentExpiresAt: string; localContentMaxSeconds: 3600; receiptOnlyAfterExpiry: true } }
/** `links` are validated Apollo destinations Higgins offered for this answer. */
export interface HigginsChatMessage { id: string; turnId: string; role: "user" | "higgins"; content: string; createdAt: string; conversationId: string; links?: NavLink[];
  /** The answer is in a source's own words (a scam alert, a Learn article, ApolloSG's KB): Luddish never rewords it. */
  quoted?: boolean }

/** Where an answer is shown in the source's own words (rule book HIG-03, HIG-04, HIG-06). */
export const QUOTED_BASES = ["recognised_government_feed_cache", "scam_alert_card", "learn_with_higgins_catalogue", "apollo_knowledge_base"];
export const isQuoted = (reply: Pick<HigginsChatReply, "evidenceBasis">) => (reply.evidenceBasis ?? []).some((basis) => QUOTED_BASES.includes(basis));

export function askHiggins(message: string, conversationId: string, turnId: string, previousTurnIds: string[], deviceSnapshot?: DeviceSnapshot) {
  return apiPost<HigginsChatReply>("/higgins/chat", "higgins_chat", { turnId, message, conversationId, previousTurnIds, ...(deviceSnapshot ? { deviceSnapshot } : {}) });
}
export function higginsHistory(deviceId: string) {
  return apiGet<{ items: HigginsChatMessage[]; receipts: unknown[]; kind: "ordinary_chat" }>(`/higgins/chat/history?device_id=${encodeURIComponent(deviceId)}`);
}
export function clearHigginsHistory(deviceId: string) {
  return apiDelete<{ deleted: number; investigationsDeleted: 0 }>(`/ask/history?device_id=${encodeURIComponent(deviceId)}`);
}
export function rememberHigginsContext(value: { category: "recent_outcome" | "protection_state" | "preference" | "goal" | "permission"; summary: string; provenance: "device_observation" | "apollo_outcome" | "user_report" | "user_preference"; observedAt?: string }) {
  return apiPost<{ item: unknown }>("/higgins/context", "higgins_context", value);
}
