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

## Still necessary before live integration

1. Select and validate the actual model on physical Android/iOS devices, including memory, prompt-output integrity and latency.
2. Add stage-specific dispatch at the existing coordinator's safe yield points, rather than on arbitrary app screens. Ensure the backend initiates the request at an appropriate time and waits or proceeds honestly when unavailable.
3. Add definitive case/job fencing and cleanup tests under concurrency, cancellation, expiry, device disconnect and app restart.
4. Consume **only validated advisory suggestions**, with independent verification by TC Hawkeye / Magnum DI and no verdict/score or Evidence Lock changes.
5. Preserve verified provenance, exact source identifiers and Luddish explanation fidelity; Gemini stays a warranted Magnum DI extension, not a failed-SLM fallback.

The two pilot endpoints demonstrate a real HTTP transport path only when explicitly activated. They do not automatically feed Luddish's output to the production investigation pipeline, do not prove genuine model execution and do not constitute an end-to-end device acceptance test.
