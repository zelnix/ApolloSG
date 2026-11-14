# Higgins source implementation report

Baseline: remote `slm` resolved to `5b95236bccb9610238cca694fee41ffe2316c93c`.
No reset was performed. This delivers source changes, not an APK or deployment.

## Changed components

- `backend/services/higgins/chat_context.py`, `backend/routers/ask.py`: authenticated
  structured retrieval; up to six product-guide/KB excerpts, provenance and scoped
  records. Ordinary retrieval neither generates conversation nor calls Gemini.
- `frontend/src/higgins/groundedChat.ts`, `chatClient.ts`, `localKnowledgeCache.ts`,
  `frontend/app/(tabs)/ask.tsx`: shared on-device conversation with a separate JSON
  contract, citation/quotation checks, visible uncertainty, versioned offline product
  guidance, bounded history and device/conversation/case isolation. Removed the
  ordinary-chat local canned responder bypass. Existing investigation submission and
  approved navigation remain deterministic. Legacy backend chat compatibility and
  the obsolete rewrite helper are not ordinary generation paths in the new client.
- `frontend/src/domain/slm/modelProfiles.ts`, `modelAdmission.ts`, native bootstrap,
  Settings and Support: typed pinned model profiles and profile-aware file admission.
  The proposed 1.7B model is inactive pending qualification.
- Native binding/runtime and `outputSchema.ts`: SDK-formatted native token counting,
  operation output reservations and constrained schemas; bounded serial execution,
  deadline/cancellation/background handling, native stop and stale-result rejection.
- `slm_timing.py`, coordinator, handoff and frontend transport/windowing: planned
  90–300-second stages bounded by original case/job/request expiry, per-generation
  limits and recorded window progress. Existing job heartbeat/fencing remains.
- `di_record.py`, investigation DI API and frontend DI: retained transaction usage
  summaries with unknown counters/cost left unknown, estimated cost labelled and
  reasoning tokens captured when reported. Usage is retained with the device's
  existing audit snapshot. Magnum provider selection, four-window limit, atomic
  claims and checkpoint reuse were not changed.

## Validation

- Configured frontend regression gate: **451 passed**.
- Affected backend regression set: **207 passed**, plus **12 subtests**.
- Focused retrieval/timing/usage/DI/continuation set: **37 passed**.
- Whole frontend TypeScript and backend Python syntax validation passed.
- Regression responses are substituted. They prove software validation/routing,
  not real model accuracy, memory use or supported-device performance.

Coverage includes actual chat-client SLM invocation for product and diagnostic
questions, failure without backend substitution, KB references and quotations,
conversation/device/case boundaries, unavailable/stale knowledge, injection-shaped
unsupported actions/links, authoritative finding rejection, expiry, serial native
cancellation, bounded queue/background cancellation, token admission, and existing
Magnum continuation checks.

## Model comparison and remaining qualification

See [model qualification](HIGGINS_MODEL_QUALIFICATION.md) for immutable package
metadata, source-level llama.rn compatibility evidence, identical fixture runner,
sampling profiles and the measurement protocol.

No physical device or actual GGUF inference was available. Cold-load time, latency,
completion rate on real models, semantic quality, peak memory/headroom and thermal
behaviour are **not measured**. Neither the Fold6 nor another device is newly
qualified by this work. The replacement is not adopted; no quality improvement is
claimed from substituted tests. The provisional window-latency estimate and RAM
floor require physical calibration. Native SDK initialisation is not cancellable;
an expired request cannot start generation after loading completes, and its slot
is not reused before outstanding native work settles.

Citations and schema conformity are not proof of semantic truth. Case explanation
fidelity is intentionally conservative and may reject a useful paraphrase. Real
response review is necessary before treating the new chat behaviour or model as
production-qualified. No evidence retention period was extended.

Completed-case conversation reads the owner-bound retained device snapshot instead
of reopening its investigation. Legacy snapshots without owner attribution, or
results not yet retained locally, are declined rather than borrowed across scopes.
