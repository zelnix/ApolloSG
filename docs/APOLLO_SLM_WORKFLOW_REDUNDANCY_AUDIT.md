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
