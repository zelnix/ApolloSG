# ApolloSG slm branch — investigation workflow and redundancy audit

Reference: user-approved ApolloSG workflow, 11 November 2026. Scope: `slm` only.

1. Apollo detects suspicious material, or the user submits it.
2. Higgins Triage uses the required on-device SLM to prepare the case.
3. TC Hawkeye investigates and returns evidence-backed findings.
4. Higgins uses the on-device SLM to assess whether escalation is required.
5. If no escalation is required, Higgins uses the SLM Finding and Luddish to present the result.
6. If escalation is required, Magnum DI uses Gemini (the configured external provider) to investigate further and returns additional evidence to Higgins; Higgins then uses the mandatory on-device SLM Finding and Luddish to present the result.

## Verified in source at audit time

- `backend/services/higgins/coordinator.py` already uses one shared expiry-aware `_wait_for_slm` helper. Do not duplicate it.
- `run_turn` calls `_slm_stage` for Higgins Triage and TC Hawkeye, then passes both accepted outputs to `tc_flyby.investigate`; it requires an SLM escalation assessment and SLM Finding. `prioritise_existing_checks` uses their verification suggestions solely to reorder existing checks by keyword overlap; it does not add checks or establish evidence. The benefit of two serial SLM requests remains unmeasured.
- `_commit_flyby` was removed from the coordinator after inspecting its active entry point and selected callers. A source-level regression guard now prohibits restoring the legacy direct Hawkeye commit. Exhaustive repository-wide reference proof and runtime validation remain outstanding.
- `frontend/src/investigation/caseStore.ts` retries an issued SLM request at most once after a failed delivery and clears the attempted marker; full SSE reconnection behaviour is not yet proven.
- `frontend/src/domain/slm/llamaRnRuntime.ts` selects operation-specific prompt instructions through `instructionsFor(request)`.

## Deliberately not removed

- Required SLM admission, platform-specific bootstraps, evidence storage versus display summaries, distinct triage service and catalogue evaluation, and Higgins presentation/fidelity functions.
- The mandatory SLM escalation and Finding path; no direct Hawkeye commit fallback is permitted.

## Outstanding acceptance work

- Run backend mandatory-SLM contract tests and frontend native-runtime tests against the same commit.
- Verify triage and Hawkeye SLM advice actually influences the intended investigation stages without promoting unsupported hypotheses to evidence.
- Test expired/slow native inference, failed submissions and SSE reconnects, stale job/revision, cross-device isolation, unsupported evidence modalities, and Magnum DI unavailability.
- Test Android, iOS, Windows and macOS runtime admission/recovery on supported native builds. Do not infer desktop runtime readiness from mobile implementation.

This note records a source-level audit and documentation alignment, **not** successful runtime/device validation.

## 11 November follow-up: definitive workflow reconciliation

- Removed the second pre-investigation `tc_hawkeye` SLM stage call from `run_turn`. Higgins Triage still uses the on-device SLM and its accepted suggestions still pass to TC Hawkeye. TC Hawkeye continues to run its own investigative checks. A source-level regression guard enforces one pre-investigation SLM request.
- **Unresolved P0 semantic mismatch:** `_commit_slm_finding` currently accepts an SLM-authored `caseFinding.outcome`, maps it to the case assessment, and commits it. This may allow the presentation model to establish or change the finding rather than faithfully explain TC Hawkeye's or Magnum DI's established finding. Do not remove mandatory SLM availability or bypass case validation to fix this. Define and test an authoritative finding handoff with evidence-locked explanation before modifying the verdict path.
- **Unresolved platform mismatch:** `routers/slm_handoff.issue_stage_request` currently admits native Android/iOS only. Windows/macOS support is an approved product requirement but cannot be claimed as implemented without native runtime and security validation.
- Existing `tc_hawkeye` role definitions remain for compatibility and any separately authorised callers; only the redundant active coordinator invocation was removed.
- This is source-level verification; CI and native device tests have not been executed.

## Corrected findings and unresolved-gap contract (user-approved)

1. Apollo detects or the user submits; Higgins Triage uses the on-device SLM to understand and organise the case.
2. TC Hawkeye investigates and returns **evidence, findings, and unresolved gaps**, with the actual cause of each gap where known. Distinguish a genuine negative result from service unavailability, provider errors/error codes, timeout, quota, and token/context exhaustion. Never silently convert technical non-completion into a negative check.
3. Higgins SLM processes TC Hawkeye's evidence, including corroboration, contradictions, coverage and unresolved gaps, to decide whether Magnum DI investigation would materially help. No duplicate investigator or extra independent authority is required.
4. Without escalation, Higgins SLM Luddish explains TC Hawkeye's findings. With escalation, Magnum DI uses Gemini to investigate and returns its evidence; Higgins SLM Luddish explains the resulting findings, contradictions, and remaining gaps.
5. The user sees one clear finding, why it matters, what is uncertain, and what to do next. Luddish must not invent checks or evidence, misrepresent failed checks, or conceal unresolved gaps.

**Implementation audit:** TC Hawkeye currently records `checks`, `gaps`, `issues`, and `search.status` in its retained record. The SLM case-finding prompt has been aligned to distinguish service failures and resource exhaustion from genuine negative results. This prompt change alone does not prove that every technical failure reason is present in the SLM request or final UI. Audit the end-to-end propagation and acceptance tests before claiming full compliance. The `case_finding` stage still generates a structured outcome from evidence; no additional findings authority or verification engine is requested. CI and native tests have not been executed.

## TC Hawkeye naming (compatibility-preserving pass)

The active coordinator now refers to the investigator as `tc_hawkeye`, and investigator descriptions no longer call it a fly-by. The underlying Python package `services.higgins.tc_flyby`, stored keys (`tc_flyby_ciphertext`, `routing.tc_flyby`), persisted evidence IDs, telemetry names, and legacy test filenames remain unchanged for compatibility. This is **not yet a full package/schema rename**; a complete reference inventory, migration/alias strategy, and regression execution are required before removing those legacy identifiers. The investigation sequence and evidence handling were not changed in this pass.

## Hawkeye technical-gap propagation: web search

For an unavailable TC Hawkeye web lookup, the existing check now retains the provider reason code and human-readable explanation together in `check.open_issue`, and records the same explanation as a missing-evidence fact. This propagates through the existing serialized checks item to the Higgins SLM evidence request, without another search or investigator. It does not establish coverage for every provider, token/context exhaustion, or final display; those still require tracing and behavioural acceptance tests. Existing `tc_flyby` persistence identifiers remain for stored-case compatibility.

## TC Hawkeye service entry point and raw source fields

The active coordinator now imports `services.higgins.tc_hawkeye`, a named entry point delegating to the existing implementation without a second engine. The result type is `HawkeyeOutcome`, with the previous `FlyByOutcome` alias retained for callers. Historical `tc_flyby` package and persistence keys remain for compatibility; full package migration requires a complete reference scan and tests.

Removed the synthesized `Web search unavailable (reason): note` explanation from TC Hawkeye. The existing evidence fact instead retains only the lookup result's supplied `status`, `reason`, and `note` fields in JSON form. Higgins SLM interprets these fields. The lookup wrapper does not currently expose every underlying HTTP response or numeric error code, so this change must not be represented as raw provider payload preservation. Tests were not run.

## Source fidelity correction

The TC Hawkeye unavailable-web-lookup fact now retains the complete returned lookup object rather than selecting only `status`, `reason` and `note`. This avoids losing provider fields at that handoff. Higgins SLM receives the stored source fields and performs the explanation. The Higgins case-finding instruction uses the approved user-facing phrase **“Evidence could not be discovered”** when a check cannot obtain evidence, adding only a cause supported by recorded source data. No additional investigation or verification stage was introduced. This change does not yet establish full raw HTTP response preservation for all external providers; some upstream provider adapters still normalize responses. Tests were not executed.
