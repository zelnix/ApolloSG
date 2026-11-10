# Apollo investigation architecture (as built, 2026-09-21)

> **Historical implementation snapshot (2026-09-21).** This document records the architecture at that date; it is not the current approved ApolloSG architecture. The later approved design uses a shared On-device AI SLM across Higgins Triage, TC Hawkeye, Magnum DI and Higgins Luddish, with Gemini as an optional Magnum DI extension only. Evidence Lock remains authoritative. Approval does not itself establish that every runtime path has been migrated; verify the implementation separately.

## Boundaries

| Layer | File | Responsibility |
|---|---|---|
| Gemini boundary | `backend/services/higgins/provider.py` | Sole AI transport (`google-genai`, owner `GEMINI_API_KEY`). Capability registry per model; complete-input token admission; SDK retries disabled; finish reason, usage and grounding preserved. Non-STOP = incomplete. |
| Contracts | `backend/services/higgins/contracts.py` → `frontend/src/investigation/types.ts` | Strict Pydantic (`extra="forbid"`, camelCase wire). `InvestigationCase`, `EvidenceItem`, `Coverage`, `SourceReference`, `Finding`, `HigginsResponse`, `Job`, `Failure`, `TurnCommit`, `DeviceRequest/Result`, `SettingsPlan`, `RecheckResult`, request models. `ModelResponse` is the model-facing subset (IDs assigned server-side). |
| Repository | `repository.py` | Owner-scoped Mongo access; Fernet-encrypted content fields; CAS on the case control record; idempotency store; evidence chunks; jobs/events; staged→accepted turn commit; revoke/cleanup/expiry sweep. |
| Evidence | `evidence.py` | Ingest text/url/observation/file; signature sniffing vs declared type; PDF (pypdf) / DOCX (python-docx) / TXT extraction into a derived child item with page offsets; image budget; coverage ledger (`mark_examined`, range union); model parts (inline ≤24k chars, images inline, longer via `read_evidence`). |
| Tools | `tools.py` | Function declarations + executor: `read_evidence`, `research_public_sources` (separate Gemini Search-grounded call with minimal public identifiers), `inspect_url` (redirects + SSRF-safe fetch), `lookup_reputation` (Safe Browsing/blocklist/IPQS via existing services), `lookup_breach` (HIBP), `research_application`, `request_device_observation`, `research_settings`, `ask_user`. Tool output is data; ownership comes from `ToolContext`. |
| Validation | `validation.py` | Interface checks only: schema, registered evidence/source IDs, capability-bound actions, completion/question consistency, provider completion. Machine-readable errors → one repair call. No style/keyword filters. |
| Coordinator | `coordinator.py` | Brief (inventory + history + open question + device profile) → function-calling loop (≤10 rounds) → JSON response → validate/repair → stage → single CAS accept. Pauses on `device_request` with an encrypted checkpoint of the conversation; resumes with the device result appended. |
| Jobs | `jobs.py` | Lease acquire (fenced), 10 s heartbeat, transient retry (429/5xx/timeout; ≤2, jittered backoff within deadline), typed failures, `partial` + `failed` events, `recover()` for expired leases at startup and every sweep. |
| HTTP | `routers/investigations.py` | Spec §8 routes: capabilities, create (Idempotency-Key), get, evidence (JSON + multipart), resumable uploads, evidence/sources/turns pages, turns (202), job, SSE events (`after=`), resume, cancel, delete, device-results, settings-plan, recheck, speech (job + authenticated audio), reports. Error body `{"error": Failure}` (server-level handler). |
| Compatibility | `routers/ask.py` | `/ask/stream` creates/continues a case per `conversation_id` and streams the committed response; `/ask/history` and `DELETE` derive from cases. No second engine. |
| Frontend | `src/investigation/{types,client,caseStore,deviceBroker}.ts`, `src/components/InvestigationView.tsx`, `app/(tabs)/ask.tsx` | Idempotent create/turn; SSE via XHR with sequence reconnect; EOF without terminal event → poll job → resume stream; per-case expiry; faithful overview + expandable explanation, findings by basis, sources with authority label, coverage, question answering, actions, Retry/Cancel. |

## Authoritative commit (spec §5)

1. `stage_turn` writes the encrypted `TurnCommit` with `staged=True`.
2. `accept_turn` performs one `find_one_and_update` on the case matching `owner_id, case_id, epoch, active_job_id, lease_fence, deleted=False, expires_at>now`; it sets `response_ciphertext`, `response_revision`, `status`, clears the active job and appends `turn_id` to `accepted_turn_ids`, incrementing `revision`.
3. Only then is the bundle flipped to `staged=False`. Readers (`accepted_turns`) require both `staged=False` and membership in `accepted_turn_ids`. A failed CAS deletes the staged bundle; the sweeper reclaims stale staged bundles.
4. Cancel/delete/expire rotate `epoch`; an old worker's CAS cannot match. `completed` is emitted only after the accept succeeds.

## State transitions

`queued → investigating → (retry_wait ↔ investigating) → complete | partial | waiting_user`; `investigating → waiting_device → queued (device result) → investigating`; any active → `cancelled` (turn) ; case → `expired` (sweeper/read-time) or `deleted`. `attention` (`none/review/action_needed/urgent`) is a separate projection; Biting is never derivable from it.

## Known gaps

Frontend `deviceBroker` returns honest `unavailable` for every request until Apollo-owned native adapters are bound (Stage C). Site/Link/Network/App/Device Gate screens still hand off summaries only. Delivery adapters (email/push/storage) remain 503 stubs pending owner credentials. Speech in the UI uses the existing protected `/voice/speak` path rather than `/investigations/{id}/speech`.
