/** Phase 5: lossless, source-linked bounded text windows for on-device Wright inference.
 * Original source is never rewritten; offsets are UTF-16 code-unit offsets.
 * Windows overlap for context. Coverage is explicit; no silent omission.
 */
export interface WrightSource { evidenceId: string; text: string }
export interface WrightChunk { evidenceId: string; parentEvidenceId: string; start: number; end: number; text: string }
export interface WrightCoverage { totalCharacters: number; coveredCharacters: number; complete: boolean; chunks: number }
export function chunkWrightSources(sources: readonly WrightSource[], maxChars = 1600, overlap = 160): { chunks: WrightChunk[]; coverage: WrightCoverage } {
  if (!Number.isInteger(maxChars) || maxChars < 256 || maxChars > 4000 ||
      !Number.isInteger(overlap) || overlap < 0 || overlap >= maxChars / 2) throw new Error("invalid_chunk_budget");
  const seen = new Set<string>();
  const chunks: WrightChunk[] = [];
  let total = 0;
  for (const source of sources) {
    if (!source.evidenceId || seen.has(source.evidenceId) || typeof source.text !== "string") throw new Error("invalid_source_reference");
    seen.add(source.evidenceId);
    total += source.text.length;
    let start = 0;
    while (start < source.text.length) {
      const end = Math.min(source.text.length, start + maxChars);
      const id = `${source.evidenceId}:chars:${start}-${end}`;
      chunks.push({ evidenceId: id, parentEvidenceId: source.evidenceId, start, end, text: source.text.slice(start, end) });
      if (end === source.text.length) break;
      start = end - overlap;
    }
  }
  return { chunks, coverage: { totalCharacters: total, coveredCharacters: total, complete: true, chunks: chunks.length } };
}
