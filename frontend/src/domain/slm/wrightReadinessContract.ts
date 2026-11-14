/** Wright checks source availability/readability only. No threat or Finding fields. */
import type { SLMReference } from "./index.ts";
export type WrightAvailability = "readable" | "unreadable" | "inventory_only";
export interface WrightReadinessResult {
  version: "wright.readiness.v1";
  evidence: { evidenceId: string; availability: WrightAvailability }[];
}
export const WRIGHT_WINDOW_QUESTION = "Check readability of this source window only.";

export function validateWrightReadiness(value: unknown, sources: readonly Pick<SLMReference, "evidenceId" | "representation">[]): WrightReadinessResult | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const v = value as Record<string, unknown>;
  if (Object.keys(v).length !== 2 || v.version !== "wright.readiness.v1" ||
      !Array.isArray(v.evidence) || !v.evidence.length || v.evidence.length > 64) return null;
  const expected = new Map(sources.map(s => [s.evidenceId, s.representation ?? "source_text"]));
  const seen = new Set<string>();
  for (const item of v.evidence) {
    if (!item || typeof item !== "object" || Array.isArray(item) || Object.keys(item).length !== 2 ||
        typeof item.evidenceId !== "string" || !expected.has(item.evidenceId) || seen.has(item.evidenceId) ||
        !["readable", "unreadable", "inventory_only"].includes(item.availability)) return null;
    seen.add(item.evidenceId);
    if ((expected.get(item.evidenceId) === "inventory_only") !== (item.availability === "inventory_only")) return null;
  }
  return seen.size === expected.size ? value as WrightReadinessResult : null;
}

export function hasReadableEvidence(readiness: WrightReadinessResult): boolean {
  return readiness.evidence.some(item => item.availability === "readable");
}
