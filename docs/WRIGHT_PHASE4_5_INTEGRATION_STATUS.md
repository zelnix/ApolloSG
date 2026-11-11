# Wright Phases 4–5 integration status

## Implemented on slm
- `wright_semantic` operation and `wright_triage` role accepted by the existing shared on-device SLM boundary.
- Dedicated `llama.rn` JSON prompt; strict `wright.semantic.v1` validation before returning a semantic result.
- `runWrightSemanticSources` processes a complete, source-linked window inventory; any failed window returns `limited`, never a clean assessment.
- Overlapping windows retain parent source IDs and exact character offsets. Original source remains unchanged.
- Native SLM adapter, model selection, existing authoritative verdict rules and investigation providers remain unchanged.
- Unit tests added for coverage, invalid/unsupported output, and fail-limited semantics.

## Explicitly not yet integrated / accepted
1. The existing initial triage entry point does **not** yet invoke `runWrightSemanticSources` on every case. Mandatory use is Phase 6.
2. The server-side Higgins coordinator still rejects >10,000 words before its existing investigation. It must be replaced with bounded, source-linked **server investigation** continuation, not by simply lifting the limit or silently summarising evidence.
3. Per-window interpretations are not a single cross-document conclusion. A later synthesis must reconcile contradictions and preserve citations and incomplete coverage.
4. Image/PDF/OCR/file extraction and original-source access remain under their existing evidence-ingress and privacy controls; this text-window utility does not claim to have examined non-text portions.
5. Physical Android/iOS inference, latency, memory, thermal, context-window, JSON compliance, full tests and backend/frontend parity are not verified.

## Acceptance before enabling mandatory triage
- Run TS tests and typecheck; run Python contract tests.
- Confirm each window fits the **complete** model prompt budget on native hardware. On overflow return Limited.
- Validate negative/quoted/hypothetical and benign/scam paired cases.
- Add bounded server investigation continuation with explicit coverage ledger, source refs and no Gemini transfer of unredacted private evidence.
- Ensure evidence from another device is never accessible and no SLM text is promoted into verified evidence.
- Preserve existing evidence-lock and Higgins Luddish authority boundaries.
