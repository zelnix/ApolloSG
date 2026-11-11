# Wright / TC Hawkeye / Magnum DI — Phase 8 acceptance gate

Status: **NOT CERTIFIED**. Code commits and added tests are not test execution.
Target branch: `slm`. Never interpret an unavailable check as a clean result.

## Automated gates (required)

From `frontend/` with dependencies installed:

```sh
yarn test:wright-phase8
yarn tsc --noEmit
```

From `backend/` with the existing backend test environment configured:

```sh
python -m pytest -q tests/test_wright_evidence_windows.py tests/test_wright_window_synthesis.py tests/test_wright_phase6_contract.py tests/test_magnum_continuation.py tests/test_phase7_investigation_safeguards.py
```

All tests must pass on the exact candidate commit. Record the commit SHA, run URLs,
environment, device model, OS version and native model checksum.

## Native device and real investigation gates

1. **Android and iOS native admission**: verify actual llama.rn loading, memory bounds,
   model identity and offline inference. Simulated adapters do not qualify.
2. **Event round trip**: authenticated device receives `slm_advisory_request` for
   `wright_triage/wright_semantic`, examines *all* original text windows and
   POSTs the same case, revision and request ID to the existing results endpoint.
   TC Hawkeye must not start before accepted native semantic results.
3. **Semantic accuracy**: legitimate invoice, actual credential phishing, negated
   scam warning, hypothetical example, mixed/contradictory documents, long text,
   quoted instructions, Unicode and multiple evidence sources. Compare source
   references, uncertainty and coverage; do not assume the model is accurate.
4. **Fail-closed**: no model, malformed JSON, missing citations, foreign evidence ID,
   model crash, one failed window, expiration, duplicate response, case cancellation,
   stale revision, offline delivery and 90-second timeout. None may yield an
   unqualified safe or scam Finding.
5. **Hawkeye and escalation**: confirm unresolved Hawkeye concerns cannot be
   downgraded to `proceed_local`; evidence-gapped cases remain Limited; only
   approved escalation invokes Magnum DI.
6. **Magnum continuation**: 1–4 windows, exhausted cap, binary evidence, provider
   timeout after claim, duplicate concurrent jobs, restart checkpoint recovery,
   evidence change between windows, retained citations and contradictory results.
   Verify actual provider cost accounting and maximum per-case calls.
7. **Evidence Lock and Higgins**: original source remains unaltered and all source
   links inert; source/device isolation is preserved; Higgins wording is checked
   against the locked Finding and cannot add unsupported facts.
8. **Privacy**: no raw source text or credentials in logs, telemetry, error messages,
   cross-device caches or unapproved network traffic. Verify on-device image
   redaction separately before any external vision request.

## Release decision

- **PASS** only if all automated and device tests pass on the same candidate commit,
  with zero open critical defects and evidence/provenance and cost limits verified.
- **FAIL** for a confirmed contract, security, coverage or safety violation.
- **BLOCKED** if devices, credentials, external providers, CI or test environments
  are unavailable. Do not substitute a code-review claim for execution.

Owner must attach the test output and acceptance record before changing status.
