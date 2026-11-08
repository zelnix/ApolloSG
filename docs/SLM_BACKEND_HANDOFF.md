# ApolloSG SLM backend handoff — staged contract

Existing architecture: backend/routers/investigations.py already implements authenticated case/device requests, owner scoping, job/revision fencing, cancellation and event streaming. Keep that workflow; do not create a duplicate investigation service.

Implemented in the slm branch:
- frontend/src/domain/slm/caseContract.ts: on-device case-correlated advisory envelope.
- backend/services/higgins/slm_contract.py: strict backend response and citation validation.
- Matching standalone tests on each side.

Important: This is not a working transport or live backend integration yet.

Activation requirements:
1. Backend issues a short-lived request for an authenticated device, current case, current revision and active job, authorising evidence IDs from server-owned case evidence. Never rely on device-chosen evidence as authorisation.
2. Reuse the existing device request lifecycle and its cancellation/expiry/recovery controls. SLM output must NOT pass through the existing path for storing device observations as evidence. It is advisory reasoning, not an observation.
3. Device calls reasonForCase with the one local runtime after device and model admission checks.
4. Backend checks the owner, live job, revision, expiry and device request, then calls accept_advisory_reasoning against the original request. A model's on_device claim does not verify origin.
5. TC Hawkeye checks any suggested external facts independently. Scores, Evidence Lock and verdict authority remain unchanged. Luddish draft explanations require existing fidelity review.
6. No automatic Gemini fallback. Gemini is an optional Magnum DI extension only when warranted.
7. Model unavailable, disconnected or unverified => preserve deterministic checks and disclose material gaps.

Why not immediately reuse /device-results unchanged: the current endpoint registers device observations as evidence. Treating an SLM hypothesis as device evidence would violate Evidence Lock provenance. The future capability discriminator needs special advisory-only handling and full lease/recovery tests.

Tests prove data-contract shape and reference validation only; native execution, end-to-end transport, auth and investigation integration remain pending.
