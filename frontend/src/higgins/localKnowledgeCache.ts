/** Versioned product guidance shipped with this source revision; never stores personal records. */
import { CHECK_ROLES } from "../domain/howApolloChecks.ts";
import type { ChatPassage } from "./groundedChat.ts";
export const LOCAL_KB_VERSION = "apollosg-product-2026-11-14-v1";
export function retrieveLocalProduct(question: string): ChatPassage[] {
  const terms = new Set(question.toLowerCase().match(/[a-z]{3,}/g) ?? []);
  return CHECK_ROLES.map(role => ({ id: `${LOCAL_KB_VERSION}:${role.id}`, title: `${role.name} — ${role.job}`, url: null,
    text: role.rules.join("\n"), publishedAt: null, checkedAt: null, freshness: "versioned_product_guide" }))
    .map(p => ({ p, score: [...terms].filter(t => `${p.title} ${p.text}`.toLowerCase().includes(t)).length }))
    .filter(row => row.score > 0).sort((a, b) => b.score - a.score).slice(0, 6).map(row => row.p);
}
