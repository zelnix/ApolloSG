# ApolloSG SLM — guarded backend/device pilot

Status: coded only on the `slm` branch, disabled by default. The native device must have a verified local model and an explicitly supplied runtime. No automatic case execution or verdict use is enabled.

## Reused infrastructure

- Routes are mounted on the existing authenticated investigations router under `/api/investigations/{case_id}/slm/`.
- The existing bearer device identity, `repo.get_case`, `repo.get_job`, case revision and epoch remain authoritative.
- Requests and results are stored encrypted in the existing `investigation_device_requests` collection, not in a new datastore.
- `POST .../requests` takes `jobId`, `caseRevision` and `role`; the server supplies the question and scoped user-submitted text/URL evidence, with strict size limits. The response has `request` and `expiresAt`.
- `POST .../results` takes the matching `SLMReasoningResult`. It verifies case/job/revision/expiry, whitelisted evidence references, and atomically accepts the first response.
- Ordinary `/device-results` explicitly rejects SLM requests. This is crucial: Luddish output is not an observed fact and must never be ingested into the case evidence table.
- The device's `submitAdvisoryForActiveCase` uses the existing `apiPost` authentication and egress policy; it is not called automatically.

## Activation

The server gate is `APOLLO_SLM_HANDOFF=on`. It is **off** by default; do not enable in production. This is a development pilot only. Client code requires a real admitted `SLMAdapter` and will not automatically call Gemini.

## Current coordinator checkpoint integration

The existing `services/higgins/coordinator.py` now reads pre-accepted, revalidated, case/job/revision-bound advisory results at four checkpoints: Higgins Triage, TC Hawkeye, Magnum DI and Luddish. The code in `services/higgins/slm_advisory.py` rejects cancelled/stale/expired cases, other devices, unrecognised evidence citations and wrong roles. Only per-role counts and an explicitly `advisoryOnly` status are recorded in the existing case routing metadata. **No model text is treated as authoritative facts, score inputs, evidence or Luddish-approved wording.** The stage checks are non-blocking and do not initiate an SLM request, wait for one, trigger Gemini or change a verdict. There is no guarantee a phone supplied an answer before a checkpoint.

## Still necessary before live integration

1. Select and validate the actual model on physical Android/iOS devices, including memory, prompt-output integrity and latency.
2. The coordinator checkpoints are now present, but actual backend-initiated request scheduling, device pickup and timing remain outstanding. Design these with the existing job lease/cancellation/recovery rules, without a new worker or investigation engine.
3. Add definitive case/job fencing and cleanup tests under concurrency, cancellation, expiry, device disconnect and app restart.
4. Consume **only validated advisory suggestions**, with independent verification by TC Hawkeye / Magnum DI and no verdict/score or Evidence Lock changes.
5. Preserve verified provenance, exact source identifiers and Luddish explanation fidelity; Gemini stays a warranted Magnum DI extension, not a failed-SLM fallback.

The two pilot endpoints and coordinator checkpoints demonstrate an opt-in HTTP handoff and read-only stage-aware intake. They do **not** yet put Luddish's output into substantive investigative planning, prove genuine model execution, or constitute an end-to-end device acceptance test.
