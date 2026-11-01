# Apollo Review Closure Record

Date: 2026-09-23

## Identity binding

- Reviewed base commit: `dac83b072bba9a541dde431b78b8668659625e27`.
- Closure working-source digest: `e7ca068ff6a902d4d347760fb7b8dab259f3ea1d081875930590b66961d87c3e` over 38 changed backend/frontend/desktop files above that commit.
- Backend origin: `https://case-source-preview--3ijise2t.preview.emergentagent.com`.
- Expo project: `47cd97c4-e5a6-41fa-9fde-257a5de031af`; version `1.1.0`; Android version code `2`; iOS build `2`.
- Android application ID and iOS bundle ID remain `app.apollo.hwg`.
- This is source/build-check evidence, not a signed candidate or physical-device acceptance record.

## Confirmed product defects closed

1. Gmail manual scans without a connection return typed HTTP 404 (`Gmail is not connected`) rather than a busy state; covered by `TestGmailScan::test_scan_without_connection_returns_404`.
2. Deterministic callback extraction now derives a two-letter parsing region from the registered device locale. `en-AU` extracts `02 8000 1234` without applying a universal country assumption.
3. Investigation processing metadata again includes `temporary_copy_policy`, including the success, failure, timeout and cancellation disposal boundary and the 15-minute maximum.

## Historical 24-failure reconciliation

The preserved JUnit artifact `test_reports/pytest/pytest_iter62_p0_targeted.xml` contains exactly 24 failures. This resolves the earlier 23/24 discrepancy. The exact historical nodes were:

1. `TestAccountAnalyse::test_off_domain_malicious_link_flagged`
2. `TestAccountAnalyse::test_password_values_are_scrubbed`
3. `TestAccountAnalyse::test_second_opinion_never_errors`
4. `TestMessageAnalyse::test_commbank_acceptance_with_second_opinion`
5. `TestMessageAnalyse::test_second_opinion_false_no_explanation`
6. `TestMessageAnalyse::test_known_bad_url_malicious`
7. `TestPageCrawlInvalid::test_bad_tld_degrades_gracefully`
8. `TestPageCrawlInvalid::test_non_http_scheme_rejected`
9. `TestPageCrawlInvalid::test_missing_device_id_rejected`
10. `TestEnforcementEvidenceGate::test_fully_valid_evidence_authorises_a_verified_block_and_persists_state_biting`
11. `TestPageCrawlInvalid::test_empty_url_rejected`
12. `TestPageCrawlSSRF::test_private_target_blocked_fast[http://127.0.0.1:8001/api/health]`
13. `TestEnforcementEvidenceGate::test_evidence_with_no_device_id_named_is_still_valid_everywhere_else`
14. `TestPageCrawlSSRF::test_private_target_blocked_fast[http://localhost:8001/api/health]`
15. `TestPageCrawlSSRF::test_private_target_blocked_fast[http://169.254.169.254/]`
16. `TestPageCrawlHappyPath::test_real_benign_url`
17. `TestEnforcementEvidenceGate::test_re_upserting_the_same_event_as_barking_without_evidence_downgrades_it_from_a_prior_verified_block`
18. `TestPageCrawlHappyPath::test_real_url_strava_docs`
19. `TestBreachCheck::test_breach_lookup_is_truthful_about_configuration`
20. `TestBreachCheck::test_breach_validation`
21. `TestMessageExtract::test_image_too_short_422`
22. `TestEnforcementEvidenceGate::test_patch_can_touch_other_fields_on_an_already_verified_biting_event`
23. `TestMessageExtract::test_valid_png_200_with_shape`
24. `TestPatrolEventsGate2::test_upsert_and_list_message_event` — the previously missing item; its exact historical mismatch was `claimed_brand == None` instead of `CommBank`.

Subsequent privacy, evidence-gate and contract remediation had already reduced the reproducible fork baseline to 16 failures. Those remaining Voice, Ask, account/app compatibility, mailbox, privacy-metadata and source-contract failures are now repaired or correctly classified as credentialed integration coverage.

## Provider-disabled and credentialed suites

- Default provider-disabled backend suite: **386 passed, 19 skipped, 0 failed** in 224.55 seconds.
- JUnit: `test_reports/backend-closure-final.xml`.
- All 19 skips carry the `credentialed_integration` marker and are enabled only with `APOLLO_RUN_CREDENTIALED_INTEGRATION=1`.
- Credentialed coverage includes owner-key Ask/Gemini, screenshot extraction, public-page interpretation, voice/TTS/transcription and transactional guardian email. None was used as closure evidence and no managed LLM key was used.

## Source and native verification

- TypeScript: `npx tsc --noEmit` passed.
- ESLint: `npx eslint app src modules plugins --ext .js,.jsx,.ts,.tsx` passed with zero warnings/errors.
- GuardDog production source checks: **9 passed**; JUnit `test_reports/guarddog-production-source.xml`.
- Frozen GuardDog manifest: **91/91 files passed** SHA-256 verification; log `test_reports/guarddog-frozen-manifest.log`.
- Android Kotlin: `:apollo-security:compileDebugKotlin` and `:apollo-family-assist:compileDebugKotlin` passed; GuardDog core/VPN modules also compiled; `BUILD SUCCESSFUL` in 41 seconds.
- Desktop/Tauri: `cargo check --jobs 2` passed with output isolated outside the constrained project volume.

## External acceptance still owned outside this source pass

- Production push notification validation.
- Owner-`GEMINI_API_KEY` acceptance validation.
- Government-feed operational validation.
- Signed mobile candidates and physical-device acceptance.