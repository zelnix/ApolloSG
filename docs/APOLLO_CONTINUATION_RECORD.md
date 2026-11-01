## 2026-09-22 Phase 2 authorised continuation

- Exact pre-change source HEAD: `d1ab4ff22f7476fefd3999e6c292c3ac92f2e30b` (`main`). This workspace exposes no configured remote/upstream, so no older review anchor was substituted.
- The Phase 2 execution cover in `Apollo_Consolidated_Architecture_and_Execution_Mandate-3.md` controls.
- M1–M4 remain accepted. Execute P2.1 through P2.6 in order without reopening the completed baseline.
- Active findings/checks are C19–C25 and V27–V36. See `APOLLO_PHASE2_EXECUTION_RECORD.md`.

## 2026-09-22 C15 production GuardDog track (“M4” continuation)

- Clarification: the source mandate's milestone table ends at M3. “M4” here means the remaining C15 production GuardDog implementation track.
- Added separate `guarddog_production` runtime/build selection without changing the default `app-bundle` legacy engine.
- Production trust uses pinned primary/recovery public roots, strict signed manifests, ordinary signer validity/revocation, permanent recovery disablement of primary authority, rollback/version conflict checks and Android-Keystore HMAC state.
- One Apollo-owned process runtime stages signed updates, observes stop/recovery, drains evidence, clears old runtime bindings/authorization and rebuilds verifier/registry/version state before resume. The frozen Expo bridge remains excluded.
- Background workers refresh signed authority every six hours and stop enforcement at exact authority/rule expiry. Invalid unchanged-trust rule updates preserve the previous valid policy; a changed trust generation with an invalid replacement remains fail-closed.
- Added offline signing tools and a production failure matrix. Private signing keys are forbidden in the app repository, binary and CI; only public roots and signed artifacts enter builds/update hosting.
- Verification within the owner boundary: TypeScript/ESLint pass; production source/configuration pytest checks pass; existing 58 lifecycle pytest tests pass; Cargo check passes. Native Gradle/device verification remains unperformed and therefore blocks cutover evidence only.

## 2026-09-22 consolidated mandate M3 implementation

- Implemented M3 findings `C13` and `C14`.
- Cancellation now has explicit actual outcomes. Duplicate cancel is idempotent; stale requests cannot clear newer work; accepted completion wins the race and the mobile client shows the winning answer instead of claiming cancellation.
- Case narration is fenced by both epoch and work epoch before/after provider calls. Cancellation, deletion, expiry and unexpected failures remove partial narration cache before retry.
- Saved reports now retain historical scope, sources, actions, response revision and a clear saved-until-deleted notice. Independent list/detail errors keep persistent Retry controls; report deletion removes linked speech scope/cache.
- Family voice notes now use one stable identity per recording, relationship-generation fencing and idempotent attachment. Uploads revalidate the relationship before and after note publication; unlink immediately fences/clears transcripts, and late caption workers cannot republish revoked content.
- Verification: TypeScript and ESLint pass, 58 provider-disabled lifecycle pytest tests pass, and Cargo check passes. No live Gemini or prohibited scenario/browser testing was used.

## 2026-09-22 consolidated mandate M2 implementation

- Implemented all six M2 findings: `C05`, `C06`, `C08–C11`.
- Text Guard now has a serialised encrypted Android queue, revision-aware message identity, bounded expiry/overflow/decryption reporting and a WorkManager handoff configured with encrypted device credentials. Foreground and background deliveries call the same idempotent case intake and only acknowledge after durable acceptance.
- Gmail manual and monitored work now share one cursor/receipt/lease pipeline. A cursor page commits only after each message reaches durable Higgins intake; retries are deduplicated and status exposes meaningful attempt/success/error/cursor state.
- PDF visual pages are retained even when they also contain text. DOCX embedded images are extracted under expanded-byte and secret admission; unresolved drawings are explicit coverage gaps. Complete image transcript output is retained without the old 60k/8k clipping.
- URL continuation reads immutable retained snapshots rather than refetching changed pages. Jobs pin their original model across recovery. A model-free idempotent projector makes completed background/foreground cases visible in Patrol and does not derive new conclusions.
- Android app/device observations no longer exclude or trust vendor prefixes and distinguish requested/granted/special-access/user-reported permission provenance.
- Saved Reports are an independent Patrol destination with stable keyset paging, historical detail/speech and owner-scoped deletion including speech cache/scope.
- Verification: TypeScript and ESLint pass; 53 provider-disabled M2 pytest tests pass; Cargo check passes. Android Gradle compilation was intentionally not run because the owner restricted verification to TypeScript, ESLint, pytest and Cargo.

## 2026-09-22 consolidated mandate M1 implementation

- Implemented every M1 register item (`C01–C04`, `C07`, `C12`, `C16–C18`; nine IDs in the source mandate).
- Mobile investigation operations now have pre-I/O fixed deadlines, generation fences, explicit business submission IDs, late-callback rejection and terminal disposal. Patrol-to-case continuity is persisted server-side with owner validation.
- Maintenance now has a lifespan-owned restart supervisor, per-component timeouts/telemetry and backlog health. Family-audio unknown upload outcomes retain durable cleanup ownership.
- App/Account compatibility routes are lookup-only and cannot run a second investigator. Settings plan/recheck egress is schema-complete and failed binding is visible.
- A shared protection health coordinator owns boot/foreground/periodic/manual/post-action checks. Android permission launch state and durable settings-return recovery safely restore intended Site protection without repeated dialogs.
- Home and Protection use component-scoped, direct actions. Build IDs, adapter/provider availability, SecureCore status and manual diagnostics now live under Support; recurring top-level visibility alarms and routine Verify controls are removed.
- Verification respected the owner boundary: `tsc --noEmit`, ESLint, provider-disabled focused pytest and `cargo check` only. No live Gemini, scenario/Playwright run, testing agent or managed AI key.
- Full legacy pytest was also attempted once: M1-relevant failures were corrected; remaining failures require absent email/object-storage/voice provider configuration or belong to older unrelated contract baselines. They are not represented as M1 passes.

## Current package continuation result

- Supported earlier source corrections remain closed. The four outstanding findings are repaired: supervised recovery/retention, strict operation/case ownership, replayable PDF image delivery, and Windows `$apolloTargetHost` generation.
- Package 3 is implemented with replayable clue/PDF/text depth, explicit research continuation and complete structured Gate observations rather than silent primary-evidence clipping.
- Package 4 is implemented with a Keystore-encrypted, acknowledge-after-submit Android Text inbox and durable shared-Higgins Gmail monitoring.
- Package 5 is implemented with user-reported Settings confirmation, paged/deletable saved reports and durable orphan-family-audio cleanup.
- Package 6 preparation continued: Rust Windows unit and `cargo check` pass. Existing Android APK remains unchanged; the next correction candidate must include the frontend/native changes. iOS and signed desktop artifacts retain only their documented external signing/host blockers.
- Package 7 remains correctly separated: acceptance configuration is non-production-only; production protection implementation is backlog and production-default cutover is a later evidence decision.

Bounded verification only: provider-disabled pytest, TypeScript, ESLint and Rust checks. No live Gemini call, browser/scenario automation, testing agent or managed AI key was used.

# Apollo — Continuation Record

Baseline reconciled from GitHub commit `ceb8108f815a408e450d6890d28dc4b6bfb55b22` (this session's HEAD at start was
already exactly this commit — no divergent work to reconcile).

Mandate in force: "Apollo — Complete Functionality and Device Delivery Instructions" (Packages 1–7). Working rules:
no testing agents / Playwright / scenario suites / live Gemini probes; targeted pytest + tsc/eslint only; no EAS
build commands (blocked in this sandbox — confirmed again this session); credentials never in Git/reports/chat.

## Package 1 — Recovery and evidence correctness: COMPLETE, verified this session

Files touched: `backend/routers/investigations.py`, `backend/services/higgins/evidence.py`, `backend/services/higgins/contracts.py`.
Tests: `backend/tests/test_recovery_fencing.py` (14 cases, all passing against real MongoDB; no Gemini calls).

### Second review pass (4 findings) — all resolved this session
1. **Heartbeat did not stop work on renewal failure; job/case writes were unconditional.** `_with_lease_renewal` now
   races the wrapped coroutine against the heartbeat with `asyncio.wait(FIRST_COMPLETED)`; a failed renewal (`matched_count
   == 0`) cancels the work immediately and raises `LeaseLost`, caught at each call site (defers to whichever attempt
   now owns the claim). The job resume write is now a `find_one_and_update` conditioned on the job's own
   `status ∈ {waiting_device,queued,retry_wait}` AND no unexpired lease held — it can no longer clobber a job a live
   coordinator turn is actively holding. The case update now goes through the existing `repo.cas()` helper instead of
   a raw `update_one`. No MongoDB transactions available (standalone instance, confirmed via `hello`) — mutual
   exclusion is the renewed fence; the job/case writes are additionally self-conditioned as a second, independent guard.
2. **A normal partial read was becoming a permanent gap.** Root cause: `mark_examined` was using its OWN output field
   (`coverage.materialGap`, which it overwrites every call as "not yet fully read") as the signal for "is this a
   permanent, ingestion-time gap" — self-referential. Added a new, dedicated `Coverage.permanent_gap` (alias
   `permanentGap`) field, set ONLY at ingestion (truncated/incomplete screenshot transcription, parser failure,
   unsupported format, encrypted/expanded/oversized documents) and NEVER written by `mark_examined`. An ordinary
   partial-then-complete read now correctly reaches `"examined"`.
3. **Upload replay could substitute a different file under the same `clientItemId`.** The replay/cleanup shortcut now
   compares the OTHER upload's `finalisation.digest` against this attempt's own content digest: identical content
   from a different upload attempt still replays (bind to the same evidence); different content now returns 409
   instead of silently returning the wrong file's evidence.
4. **Device-observation recovery reused a metadata-only evidence row.** Before reusing an `existing` observation
   evidence row, `_finish_device_submission` now confirms an actual content chunk exists in
   `investigation_content_chunks`; if not (crash between `insert_evidence` and `store_bytes`), the orphaned row is
   discarded and re-ingested fresh from the submission payload the claim already durably retained.

Package 1 is now considered fully complete per both review passes. Bugs found+fixed in the FIRST pass (scanned-page
`expires` NameError, invalid `Transformation(lossy=True)` kwarg, missing `storing`/`resuming` handling in
`_finish_device_submission`, attempt-specific upload cleanup, page-level coverage aggregation across text+image
children) remain in place and re-verified.

## Verification this session
- `backend/tests/test_recovery_fencing.py`: 14/14 pass (5 new: ordinary-partial-read-completes, digest-mismatch
  rejected, digest-match binds, orphaned-observation-metadata reingested, lease-loss-detected-and-cancelled).
- Regression: `test_investigation_persistence.py`, `test_investigation_engine.py`, `test_p0_evidence_receipt_indexes.py`,
  `test_enforcement_evidence_gate.py`: 25/25 pass. `ast.parse` clean on all changed files. Backend restarted cleanly.
- This was a read-only source review by the requester (tests not independently rerun on their side) — the above is
  this session's own fresh run, on the current HEAD, immediately after the fixes.

## Package 1 — Recovery and evidence correctness: RECONCILED against the detailed architecture mandate this session

Re-verified (not just re-read) against the specific architectural elements named in the owner's reconciliation
request — durable device-result inbox, one authoritative job owner, conditional checkpoint writes, attempt-isolated
evidence publication, extraction gaps vs. reading progress — by re-reading `repository.py`, `jobs.py`,
`investigations.py` end-to-end line by line, not by trusting last session's summary:
1. **Durable device-result inbox**: `investigation_device_requests` persists the canonical result at first contact
   (`device_results` claims via `find_one_and_update(..., "submission": None)`) BEFORE any ingestion is attempted, then
   advances through fenced, renewable-ownership stages (`claimed → storing → stored → resuming → resumed`) via
   `_claim_submission_stage` + `_finish_device_submission`; `recover()` resumes any request stuck in `claimed/storing/
   stored/resuming` past staleness. Confirmed durable and crash-safe, not just "acknowledged".
2. **One authoritative job owner**: `repo.acquire_lease` fences a job (`fence` + 30s `lease_until`) so only one
   worker holds it; `_with_lease_renewal` (added in the prior review pass) races a 40s-renewal heartbeat against the
   wrapped coroutine itself for the two long-lived ownership stages (upload finalisation, device-result resume) and
   cancels the work the moment renewal fails — not merely a background timestamp ping with unrelated work still
   running underneath it.
3. **Conditional checkpoint writes**: every case/job mutation in the hot path is a `find_one_and_update` conditioned
   on the mutator's own expected state (`epoch`, `work_epoch`, `active_job_id`, `lease_fence`, or the job's own
   `status ∈ {...}` + unexpired lease) — e.g. `_resume()`'s job write in `investigations.py` line ~614; a superseded
   attempt's write matches nothing and is silently a no-op rather than corrupting state it no longer owns.
4. **Attempt-isolated evidence publication**: `settle_write` (repository.py) captures the case epoch BEFORE an
   awaited content write and compensates (deletes the row) if the epoch moved during the write; `sweep_tombstones`
   is the backstop for a process that died before compensating. `discard_incomplete_ingestion` removes a
   metadata-only or crashed-mid-write evidence row before any resumed attempt can reuse it. Upload finalisation
   (`complete_upload`) additionally binds replay to a content digest, not just a client item ID.
5. **Extraction gaps vs. reading progress**: `Coverage.permanent_gap` (evidence.py) is set ONLY at ingestion
   (truncated transcription, parser failure, unsupported format, scanned-page budget cutoff) and is NEVER written by
   `mark_examined`; `mark_examined`'s own `materialGap` output ("not yet fully read") cannot resolve a
   `permanent_gap` by re-reading the same already-limited retained content. Confirmed still correctly separated
   (this was the prior session's fix; re-verified present and unchanged).

Files re-verified: `backend/routers/investigations.py`, `backend/services/higgins/repository.py`,
`backend/services/higgins/jobs.py`, `backend/services/higgins/evidence.py`. No further backend changes were needed —
the architecture already satisfies the five elements above. Commit unchanged from last session's Package 1 head;
this reconciliation added no new commits (verification-only), confirmed via `pytest backend/tests/test_recovery_fencing.py`
(14/14) and the four adjacent regression files (25/25) both green again this session.

## Package 2 — File/Device/shared entry flows: Device Gate, File Gate, Text/Email Gate duplicate removal DONE this session

1. **File Gate acknowledgement boundary (frontend)** — `uploadFileEvidence` (single-shot multipart, no resume, and
   NOT replay-safe on retry — a retried multipart POST with the same `clientItemId` hits `ingest_file`'s plain
   `insert_evidence`, which 409s outright rather than replaying) has been replaced as the Gate's upload path by a
   new `uploadFileEvidenceResumable` (`frontend/src/investigation/client.ts`) that drives the ALREADY-HARDENED
   Package-1 resumable endpoints (`POST /uploads`, `PUT /uploads/{id}/chunks/{index}`, `POST /uploads/{id}/complete`
   — digest-checked replay, fenced finalisation). `frontend/src/investigation/caseStore.ts`'s `start()` now reads the
   file once into memory and reports a `FileUploadHandle` (uploadId + bytes + next chunk index) back to the caller
   after every step; on failure the handle is retained in a `pendingUpload` ref and `retry()` resumes the SAME
   upload session from the SAME chunk — never re-reading or discarding the original file, never recreating the
   case. `state.caseData` is now set immediately on case creation (previously only after every file + the opening
   turn succeeded), so the existing `InvestigationView` retry button — which requires `caseData` to render at all —
   now actually appears when a file upload or the opening turn fails, instead of silently having no retry
   affordance. Also fixed: `frontend/src/domain/privacy.ts`'s `investigation` egress allow-list was missing
   `filename`/`mediaType`/`declaredBytes` — needed by the new `POST /uploads` body — which would have been silently
   stripped, breaking every upload; added.
2. **Device Gate stable case identity** — `app/device.tsx` passed the LIVE, `useMemo`-recomputed `result` (recomputed
   on every self-report toggle and every recheck) directly as `GateInvestigation`'s `submission`. Since
   `GateInvestigation` keys a NEW investigation off object identity, every toggle of a "Tell Higgins what you've
   noticed" switch was silently discarding the in-progress conversation and opening a brand-new, separately billed
   investigation. Added a `submission` snapshot state that updates ONLY when a real check cycle completes (mount,
   or "I changed it — check again" via the `checking` flag) — never on a self-report toggle, which now only updates
   the live `result` shown on screen. This was the only Gate using this reactive pattern; the other 7 Gates
   (account/app-check/call/check/email/message/network) already hold `result` in plain `useState`, set once per
   "finish"-style call, so they were not affected.
3. **Text/Email Gate duplicate investigation paths removed** — `app/message.tsx` and `app/email.tsx` both call the
   legacy `/message/analyse` endpoint first (a standalone Gemini "second opinion" producing its own
   `assessment`/`explanation`, rendered via `MessageAssessmentResult`), and ALSO rendered `GateInvestigation`, which
   auto-starts a SECOND, independent shared-engine investigation (its own Gemini turn) the instant the result
   renders — two full Gemini analyses of the identical content, back to back, every single check, without the
   person asking twice. Added an `autoStart` prop to `GateInvestigation` (default `true`, unchanged for the other 7
   Gates); Text and Email Gate now pass `autoStart={false}`, so the shared-engine case is created only the first
   time the person actually taps "Ask Higgins about this message/email" (existing `openHigginsHandoff` → Ask tab
   path, unchanged). The legacy assessment's findings are still handed to Higgins as reusable context
   ("already performed; do not repeat the same lookups") when that follow-up happens.
4. **Home/Share intake, Patrol continuation** — audited, already correct from prior work (not from this session):
   `frontend/app/share.tsx` routes shared content to the same Gate screens audited above (file/message/etc., which
   all run the shared case engine); `frontend/src/components/EventActions.tsx`'s "Ask Higgins to explain" on a
   Patrol event resolves `caseForEvent(event.event_id)` first and continues that exact case (`case_id` handoff)
   instead of opening a duplicate. No changes needed; verified by reading the code, not assumed from the commit log.

Verification this session (frontend, no live Gemini calls, no testing_agent, no Playwright): `npx tsc --noEmit`
clean project-wide; `eslint` clean on every file touched (`client.ts`, `caseStore.ts`, `privacy.ts`, `device.tsx`,
`GateInvestigation.tsx`, `message.tsx`, `email.tsx`); existing frontend `node:test` suites re-run
(`purposeLimitedInvestigation.test.ts`, `p0TruthPrivacyFile.test.ts`) — 14/15 pass, the 1 failure
(`+61400000000` phone redaction inside an `ask_apollo` context payload) reproduces identically on the pre-change
HEAD (confirmed via `git stash`), so it is pre-existing and out of this session's scope, not a regression.
Backend: full `pytest backend/tests` re-run for regression — 307/324 pass; the 17 failures are all in files this
session (and the immediately prior Package-1 session) never touched (`test_family*.py`, `test_family_voice.py`,
`test_gate7_app.py`, `test_gate4_callguard_risk.py`, `test_device_auth.py`, `test_purpose_limited_investigation.py`,
`test_iter71_purpose_limited_contracts.py`); `RESEND_API_KEY` is unset in this sandbox (`email_configured()` is
False), which alone explains every `test_family*` guardian/confirm-token failure — a Package 7 configuration
blocker, recorded individually per the mandate, not a regression to chase now.

## Next (remainder of Package 2, then Packages 3–5 continuously): resume here

Package 2 is now functionally complete per the mandate's own listed items (2.1–2.5). Continue directly into:
- Package 3 — investigation depth and limits (document continuation slicing, content/clue limit audit, structured
  observations to Gemini, org/app research completion).
- Package 4 — Gate-specific behaviour (Text/SMS protected storage, Email Gate shared engine integration — note:
  Email Gate's INITIAL analysis is still the legacy `/message/analyse` path by design per #3 above, deliberately
  deferred rather than replaced, to avoid a live-Gemini-dependent rewrite of the primary verdict card without the
  ability to test it live this session; App Gate platform visibility; remaining Site/Link/Call/Network/Account
  Gates).
- Package 5 — guided actions, reports, lifecycle (Settings assistance, saved vs temporary reports, orphaned family
  voice upload cleanup).
- Package 6 stays active in parallel per the owner's correction (Android candidate refresh, Windows/macOS native
  work, unblocked iOS configuration) — not yet picked up this session; EAS build commands remain unavailable in
  this sandbox per every prior session's confirmation.
- Package 7 unblocked adapters continue in parallel; `RESEND_API_KEY` absence is the one blocker recorded above.

## Untouched packages (3, most of 4, 5, 6, 7): NOT STARTED — see mandate text for exact scope per package.


## 2026-09-21 continuation — review `9cfb377`, Package 1/2 closure and fresh platform candidates

### Exact source and configuration identity
- Starting reviewed source: git `9cfb3774d7210992d1d852d7d490c7272ab420bc`.
- Saved-source baseline visible to EAS: git `58fb1a066eaabe06a96c143da8d4ce171e254d6c`.
- Exact uploaded Android source fingerprint: EAS fingerprint `31a0394db69ca674b79ef91a3d0cf3c2b0e2e083`
  (`01a0c541-21a7-7d83-a8b9-5e0d153493a3`). This fingerprint includes the working-source changes below even
  though EAS's informational git field still names the last platform-created commit.
- Independent non-secret source-tree digest after implementation: SHA-256
  `7e0f0ff6f77706449d3452891cfcd9b0b98be814253c8319e058e61ca7818c23` (backend/frontend/desktop source;
  excludes environment files, generated dependencies, caches, desktop target and export output).
- Compatible backend: `https://case-source-preview--3ijise2t.preview.emergentagent.com`, `/api/health` = HTTP 200 `apollo-v1`.
- Provider boundary: static source/config audit confirms Higgins uses `GEMINI_API_KEY`; no Emergent-managed LLM key
  was introduced or used. No live Gemini probe, scenario campaign, Playwright run or testing-agent run occurred.

### Package 1 — COMPLETE for the review's remaining architecture boundaries
1. **Durable device-result inbox / acknowledgement ordering** — `investigation_device_requests` remains the inbox.
   A submission now becomes `fulfilled/resumed` only after one conditional job write records its request ID in
   `consumed_device_request_ids` together with the resumed checkpoint. An active lease, stale status or lost fence
   leaves the submission durably `stored` and explicitly returns `consumed:false`; the recovery sweep retries it.
2. **One authoritative owner / conditional writes** — device resume now fences on job status, lease and unconsumed
   request ID; the case projection CAS also checks `work_epoch`, `active_job_id` and the pending request identity.
3. **Durable tool identity / reconstruction** — `request_device_observation` uses a deterministic UUID derived from
   the persisted tool-call key and a unique `(owner_id, job_id, tool_call_key)` index. Coordinator recovery detects
   the unresolved durable request before another Gemini call even if the process died before checkpointing its ID.
4. **Attempt-isolated evidence publication** — evidence trees stage behind `publication_root_id` and
   `ingestion_attempt_id`. Readers/list/inventory cannot see metadata/content/children until one atomic root-document
   transition publishes the completed manifest. Abandoned attempts are deleted as a whole; pre-manifest historical
   rows remain readable for compatibility.
5. **Extraction gap vs reading progress** — retained behavior was verified, not collapsed: `permanentGap` remains the
   ingestion/extraction limitation, while ordinary unread ranges update `materialGap` and can reach `examined` after
   the retained content is read. Focused coverage tests pass.

Changed backend files:
- `backend/services/higgins/repository.py`
- `backend/services/higgins/evidence.py`
- `backend/services/higgins/tools.py`
- `backend/services/higgins/coordinator.py`
- `backend/routers/investigations.py`
- `backend/services/investigation.py` (deterministic caller-reputation finding; no model call)
- `backend/tests/test_recovery_fencing.py`

Bounded verification: 42 focused Higgins persistence/evidence/engine tests pass; 17/17 recovery-fencing tests pass
including new consume-before-ack, atomic publication and deterministic request-identity cases; Call Guard's two
deterministic contract tests pass. Python lint/compile clean. No live provider behavior was exercised.

### Package 2 — COMPLETE for File, Device, shared entry and Patrol continuity boundaries
1. **File Gate acknowledgement boundary** — File Gate remains local-only until the explicit Ask action
   (`autoStart=false`). Apollo cache copies no longer die on navigation into Ask. Resumable upload owns them until
   backend durable publication; only then does `caseStore` call the scope-checking disposer. Explicit reset and the
   15-minute sweep remain bounded cleanup. Original provider/shared files are never deleted.
2. **Device Gate continuity** — the first completed check creates a stable submission/case. Self-report toggles and
   later settings refreshes no longer replace the submission object and therefore cannot delete/recreate the case;
   accepted answers and action observations continue in that case.
3. **Text/Email single investigator path** — compatibility `/message/analyse` requests now set
   `second_opinion:false`; they supply deterministic local/reputation observations only. Text and Email then auto-start
   the one shared Higgins case, removing the prior duplicate legacy-Gemini-plus-shared-Gemini path.
4. **Share intake completeness** — native share payloads are retained as one opaque 15-minute in-memory envelope;
   raw text, URLs and file paths are absent from route strings; no `.slice(...)` truncation is used; every attachment
   is preserved and supplied to the shared evidence inventory. Android ACTION_SEND_MULTIPLE and iOS multi-file/image
   activation are enabled up to the configured 10-item extension limit.
5. **Home/Share/Patrol continuity** — event IDs are carried in Higgins context; Gate-created and manually-created
   cases are persisted in the Patrol event→case index. Patrol's Ask action resumes that case rather than opening a
   duplicate investigation.

Changed frontend files:
- `frontend/src/investigation/caseStore.ts` (the existing `caseIndex.ts` is now consumed by all creation paths)
- `frontend/src/components/GateInvestigation.tsx`
- `frontend/src/domain/higginsHandoff.ts` (the existing scoped disposer in `fileCopyLifecycle.ts` is reused)
- `frontend/src/share/shareIntake.ts` (new), `ShareIntakeListener.tsx`, `classifyShare.ts`
- `frontend/app/share.tsx`, `file.tsx`, `device.tsx`, `message.tsx`, `email.tsx`, `account.tsx`, `check.tsx`,
  `frontend/app/(tabs)/ask.tsx`
- `frontend/src/store/ApolloContext.tsx`, `frontend/app.json`, `frontend/tests/share.test.ts`
- Removed obsolete `openHigginsHandoff` imports from Gate screens now using `GateInvestigation`.

Bounded verification: TypeScript compile clean; ESLint clean; Share/incident suite 13/13. No device journey or scenario
campaign was run, per owner instruction.

### Package 6 platform delivery — ACTIVE
- **Android:** EAS internal APK build `18706c6e-cf91-418e-9536-94b1cf592f93`, application
  `app.apollo.hwg`, profile `device-test`, source fingerprint above. Status: `FINISHED` at
  `2026-09-21T18:52:03.479Z`.
  Build page: `https://expo.dev/accounts/emergent-em-user-fb71a8d3-adc2-4275-b1ec-2692228557b8/projects/threat-patrol-1/builds/18706c6e-cf91-418e-9536-94b1cf592f93`.
  APK: `https://expo.dev/artifacts/eas/e6U7nUAuNc-tULLCTfLftpltfy7wll9oithASkmvk7U.apk`;
  147,531,093 bytes; SHA-256 `50e51aff03ee69ed859386b734365a205fe9040fc240c5af896e7a3342503e91`.
  Downloaded verification copy: `/app/Apollo-Android-18706c6e.apk`.
- **Desktop:** restored the Tauri CLI/Rust prerequisites, installed Linux WebKit/GTK build dependencies, and compiled
  both `cargo check` and the Linux release host. Candidate binary:
  `desktop/src-tauri/target/release/apollo-desktop`, SHA-256
  `f3d79697729e558c3351b4c6b44b4c2a739966e2a7ba0b1074bd216e5e794a2a`. The shared Expo web export also succeeds.
- **iOS:** compatible share-extension multi-item configuration is implemented. A signed device build remains blocked
  only by unavailable Apple signing credentials/profile; missing credentials do not block Android/backend/desktop.
- **Windows/macOS packages:** shared Tauri/Rust source compiles on Linux; `.msi/.nsis/.dmg/.app` outputs remain genuine
  target-host build/signing work and were not falsely claimed from this Linux container.

### Genuinely outstanding authorised work — continue without routine approval
- **P0:** owner-led physical device acceptance of Android build `18706c6e...` (launch, share-multiple, File→Ask
  upload retention, Device case continuation, native protection). Compilation succeeded; device behavior is not
  inferred from that fact.
- **P1 / Package 3:** document continuation slices beyond parser/context budgets; audit every content/clue limit and
  return structured original observations without silent omission.
- **P1 / Package 4:** protected Text/SMS storage lifecycle, Email background shared-engine work, App Gate platform
  visibility, and remaining Gate-specific boundaries.
- **P1 / Package 5:** guided Settings confirmations, saved-report vs temporary-case lifecycle, and family voice orphan
  upload cleanup.
- **P1 / Package 6:** iOS signed device build when owner credentials exist; Windows/macOS target builds and native
  extension completion on their host toolchains.
- **P2 / Package 7:** GuardDog production adapter/configuration closure and credential-gated integrations. Each missing
  credential blocks only its named integration.

## 2026-09-22 deployment readiness health check — PASS
- Final deployment-agent result: **PASS / ready for deployment**, with no source/config blockers.
- Removed the unconditional startup drop of `imap_connections` from `backend/server.py`; legacy records now require an
  explicit audited migration rather than being destroyed during process startup.
- Removed all automatic legacy-content bulk deletion from `migrate_and_index()` in
  `backend/services/higgins/retention.py`. The fenced helper remains operator-only and is never called by app startup.
- Added a bounded regression in `backend/tests/test_recovery_fencing.py` proving startup/index initialization preserves
  pre-v1 rows while a uniquely identified explicit migration runs only once.
- Updated the managed preview supervisor command to `expo start --tunnel --port 3000`; installed compatible
  `@expo/ngrok` through Expo (`frontend/package.json`, `frontend/yarn.lock`). Supervisor is RUNNING and logs confirm
  `Tunnel connected` / `Tunnel ready`.
- Verification: backend Python lint clean; 18/18 recovery/migration tests pass; `/health` and `/api/health` HTTP 200;
  frontend TypeScript and ESLint clean. Environment variables, URLs, ports, CORS, MongoDB and secret handling passed
  the final deployment scan.

## 2026-09-22 correction pass from saved-source review `4c03315`

### Source/build identity — do not collapse these identifiers
- Human-reviewed saved commit: `4c03315e5a4706812e67c4ed122822748993211a`.
- Last saved commit before this correction working tree: `41dab4304ecf67a4332a1d781db130dbc8f8c9b6`.
- Exact non-secret corrected working-source digest: SHA-256
  `01e4723d48cd34c3129701adebd2947249cb174f94d2ae21a699d30567ea0110` (18,626 backend/frontend/desktop
  source files; excludes environment files, dependencies, caches, exports and all Tauri `target/` output).
- Existing Android build `18706c6e-cf91-418e-9536-94b1cf592f93` remains mapped only to EAS fingerprint
  `31a0394db69ca674b79ef91a3d0cf3c2b0e2e083` and informational git SHA `58fb1a0...`. It **does not contain this
  correction pass** and must not be relabelled as if it did. The next native build must record its new saved commit,
  EAS fingerprint and artifact hash together.

### Ranked Package 1/2 corrections
1. **Text Gate shared case — COMPLETE.** `app/text-guard.tsx` now starts the same `GateInvestigation` flow as Message
   and Email. Legacy `/message/analyse` remains `second_opinion:false`; local findings are supplied as evidence. Text
   and Email hide their preliminary assessment once an accepted Higgins response exists, leaving one current
   assessment rather than two competing result cards.
2. **File retry from operation start — COMPLETE.** A stable `FileUploadHandle` and app-level transfer record are
   created before file reads or session creation. The manager owns bytes, immutable item/session keys, next chunk,
   server/case deadline, cleanup and retry state across navigation. Case expiry is armed immediately after case
   creation. Server session creation replays by immutable `clientItemId`, returns the same deterministic upload/root
   identities and rejects identity/content changes.
3. **Device continuity — COMPLETE.** Each real recheck appends a timestamped observation to the existing case via
   `continueWith`; explicit user-report submission has its own button and provenance. Accepted history is retained.
   A Patrol event created after case creation is bound by the event-ID effect, so Patrol resumes the same case.
4. **Evidence publication ownership — COMPLETE.** One immutable client item reserves one deterministic root. Root
   publication checks the current upload fence. Cleanup first CAS-marks one exact staging attempt `abandoned` and
   deletes only that attempt; a committed root cannot be discarded. A root published before the upload projection
   update is replayed by content digest and repairs that projection.
5. **Device-observation recovery — COMPLETE.** Coordinator start repairs inbox rows from authoritative consumed IDs
   before any wait decision. Pending-batch ledger replay restores `ctx.pending_request`. Wakeup now occurs only after
   the inbox is marked fulfilled; queued-job recovery remains the crash fallback.
6. **Cancellation race — COMPLETE.** Cancellation matches expected revision, active job and work epoch at the case
   control record. A stale target cannot clear a newer turn. Terminal jobs return their actual status with
   `cancelled:false` instead of claiming cancellation.

Changed core files:
- Backend: `backend/routers/investigations.py`, `backend/services/higgins/{repository,evidence,tools,coordinator}.py`,
  `backend/tests/test_recovery_fencing.py`.
- Mobile: `frontend/app/{text-guard,email,device}.tsx`, `frontend/src/components/GateInvestigation.tsx`,
  `frontend/src/investigation/{client,caseStore,transferManager}.ts`.

### Package 3 continuation progress
- Added bounded `continue_document` PDF extraction. Pages beyond the first 64 are now recoverable slices, not a
  permanent extraction gap. Each slice is new addressable evidence; parser extraction still does not count as
  semantic examination. Remaining omitted pages stay explicit. A generated-PDF regression verifies publication.
- Still outstanding: audit every other inline/content/clue cap and expose structured continuation for each cap that
  can omit material; complete the structured original-observation inventory audit.

### Package 6 desktop progress
- `desktop/src-tauri/src/lib.rs` now reports Windows manufacturer/model/chassis form factor via WMI and macOS model via
  `sysctl`; unknown values remain null rather than inferred.
- Notification permission uses the real Tauri notification plugin. Network-filter permission now performs a real
  administrator-approved OS hosts/DNS filter activation rather than recording request history only.
- Exact-domain block/unblock and filter-status commands are implemented with strict domain validation, unrelated hosts
  preservation, DNS cache flush and explicit scope: this is **hosts/DNS enforcement only**, not falsely claimed WFP,
  Network Extension packet inspection or app attribution.
- Native desktop selection now wins before fixture eligibility; fixtures remain browser-only. Windows/macOS adapter
  implementation flags are enabled for this bounded native host.
- Tracked build output removed without history rewrite: `git ls-files 'desktop/src-tauri/target/**'` = `0`;
  `/desktop/src-tauri/target/` is ignored. Local generated artifacts remain outside source tracking.
- Changed: `.gitignore`, `desktop/src-tauri/src/lib.rs`, `frontend/src/security/{DesktopSecurityAdapter,hostAdapter.web,desktopHost,PlatformCapabilityProfile}.ts`,
  `frontend/tests/desktopHost.test.ts`, `frontend/package.json`, `frontend/yarn.lock`.

### Bounded verification
- Backend: 51/51 focused Higgins persistence/evidence/recovery/cancellation tests passed, followed by 25/25 recovery
  tests after PDF continuation; Python lint clean.
- Frontend: TypeScript and ESLint clean; Text Gate deterministic suite 23/23; Email Gate 13/13; desktop-host priority
  1/1.
- Desktop: Rust hosts-filter unit tests 2/2 and native library compilation passed. Windows/macOS privileged flows need
  target-host acceptance; Linux cannot prove those OS prompts.
- No scenario campaign, Playwright or testing agent was used. **One unintended Gemini request occurred during the first
  ledger-replay regression because the checkpoint fixture used `ledger` instead of `toolLedger`; it returned HTTP 400
  and produced no accepted scenario result.** The fixture was corrected; all subsequent runs completed without live
  provider calls. This exception is recorded rather than concealed.

### Genuinely outstanding — continue without routine approval
- Save this corrected working tree to a new commit, then make the next Android build record map saved commit ↔ EAS
  fingerprint ↔ artifact SHA-256 exactly. Existing APK use may continue as the prior candidate only.
- Packages 3–5 remain active beyond the completed boundaries above: finish all cap continuations; protected/background
  Text/SMS and App Gate visibility; Settings confirmation, saved-report/temporary-case lifecycle and family voice
  orphan audit.
- Package 6: target-host Windows/macOS permission/filter acceptance; signed iOS work remains credential-blocked only.
  WFP/Network Extension packet-level services remain outstanding and are not implied by hosts/DNS filtering.

## 2026-09-22 final deployment health check — PASS
- Deployment Agent final result: **PASS; no blockers detected**.
- Last saved source before readiness remediation: `63d60d861104902cfaed0970f9010899ded1f2b3`; exact post-remediation
  working-source SHA-256: `b70cdffb4ca7441313c928ec9acc4a946ab7c1b310de55707c6353bc9bdabb10` (18,639 files,
  using the same non-secret exclusions documented above).
- Removed repository-wide `.env` ignore patterns required by deployment automation. Injected runtime values remain
  protected in this workspace through local `.git/info/exclude`; no values were committed or printed.
- FastAPI startup is initialization-only. It no longer launches retention, investigation, or family-audio deletion
  loops. This prevents deployment/process restart from being the trigger for destructive maintenance.
- Retention cleanup remains available as an explicit operator command:
  `cd /app/backend && python -m scripts.run_retention_sweep`. The command is not invoked by API startup.
- Changed: `.gitignore`, local `.git/info/exclude`, `backend/server.py`,
  `backend/scripts/{__init__,run_retention_sweep}.py`.
- Verification: Python lint clean, `py_compile` clean, 25/25 focused recovery/retention regressions pass, static startup
  cleanup check passes, and `/health` plus `/api/health` return HTTP 200.
- Final scan also passed Expo environment/supervisor configuration, MongoDB indexes and query limits, CORS, dynamic
  OAuth redirects, source secret scanning, URL/port configuration, Tauri configuration, and ignored/untracked desktop
  build output.

## 2026-09-22 seven-defect correction package (reviewed baseline `63d60d8`)
- **Desktop bounded filter completed:** privileged Windows/macOS updater now owns read→modify→safe-replace→flush→readback;
  changes serialize through one native lock; read/write/verification failures propagate; aliases remain explicit exact
  hostnames. No WFP/Network Extension or app-attribution claim was added.
- **Evidence attempts isolated:** upload control document is the publication authority. One CAS matching the current
  finalisation fence records the winning attempt and immutable manifest. Readers accept only manifest members from
  that attempt; ingestion-time updates are attempt-matched; cleanup cannot delete an authoritative published attempt.
- **Concurrent device results serialized:** every encrypted checkpoint has `checkpoint_revision`; result consumption
  merges and retries against the exact revision while atomically adding the consumed request ID.
- **Application-owned operations:** file transfers retain case/operation/item/session/deadline/chunk/turn state,
  abort controllers and bytes outside screens; recreated screens attach to active operations. Expiry/deletion aborts,
  releases bytes/copies and rejects late callbacks. Same-case device appends retain stable evidence/turn identities and
  Retry resumes the failed append.
- **PDF continuation completed for bounded components:** initial and continuation extraction share text/link parsing;
  continuation publishes text, exact hyperlink destinations and scanned-page visuals as one slice manifest. Only
  successfully available components clear coverage gaps; staged slices are abandoned/rebuilt and committed slices
  replay/repair parent references.
- **Client cancellation corrected:** UI waits for authoritative `cancelled/status`, refreshes after conflicts, reconnects
  continuing work and displays `Cancellation not confirmed` with Retry on conflict/transport failure.
- **Single current assessment completed:** Message/screenshot now follows Text/Email—local signals remain supporting
  evidence while the last accepted Higgins answer stays current during pending/failed follow-up.
- **Provider-call prohibition:** bounded pytest sets `APOLLO_FORBID_PROVIDER_CALLS=1`; Higgins provider functions fail
  locally before SDK/network access. A dedicated regression verifies the prohibition.
- Corrected non-secret source digest before save/build:
  `fe41defb4f0fd0bc6fa85cd0dfb9d9db5412a75445c6be88c4f7d65d694770da` (18,639 files; documented exclusions).
- Verification: backend focused suite 56/56, including 29/29 recovery/control tests; Python lint clean; frontend
  TypeScript/ESLint clean; desktop Rust 3/3. No scenario, Playwright, testing-agent or live provider run.
- Build next: save this exact correction package, then create a `device-test` Android APK and map saved SHA ↔ EAS
  fingerprint ↔ artifact URL/hash. Do not reuse build `18706c6e...` identifiers.

### Fresh Android candidate delivered
- Correction commit: `4bb068292ad92118969dcc7802c2fb529502847f`.
- Native-profile boundary commit: `7fd6f9a61d292bdab17700152f7e47e457afc411`.
- First attempt `c46c1d78-d662-4cd6-a45d-292ffe175247` failed Pre-install because development `.env` enabled
  the browser-only preview harness. It produced no APK and is retained only as a failure record.
- Final EAS build: `047bc183-37e9-447b-b0f8-48012f591550`, **FINISHED**.
- EAS fingerprint: `565f42d9b04dd39c836360eeccd12c4e442b800f`; fingerprint ID
  `01a0c708-0e1b-7824-8b82-319c7b2396c8`.
- APK: `https://expo.dev/artifacts/eas/HNq2PiQUZ46vTsP-q2f8OTQ4O0CU4L_uNJY2RyCTRB8.apk`.
- APK SHA-256: `c15804e04597e09628575cc58734bd97fc10c2cbe1f89dd4c1ddae239e102e97`;
  size 147,567,093 bytes; local verification copy `/app/Apollo-Android-047bc183.apk`.
- The EAS log loaded `EXPO_PUBLIC_BACKEND_URL` from the uploaded environment and compiled against the compatible
  `device-file-gate` backend. Preview fixtures were explicitly disabled before native security preflight.
- Physical-device behavior remains owner acceptance work; successful compilation is not represented as device proof.
