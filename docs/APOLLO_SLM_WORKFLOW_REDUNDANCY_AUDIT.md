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
