# Wright Triage — Phase 3: On-device SLM qualification

Status: **BENCHMARK PROTOCOL READY; MODEL NOT YET QUALIFIED**.
Scope: existing ApolloSG shared llama.rn runtime and native Android/iOS builds.
This document does not authorize changing the shipping model, runtime, verdict rules, or cloud fallback policy.

## Current implementation (slm)
- Qwen2.5-0.5B-Instruct Q4_K_M GGUF in bootstrap.native.ts/modelAdmission.ts.
- llama.rn 0.12.9; n_ctx=4096, n_gpu_layers=0, n_predict=768, temperature=0.1.
- Prompted JSON, followed by validation. No constrained JSON grammar is configured.
- Conservative full-prompt character budget; oversized evidence is rejected, not truncated.
- Device admission checks >=3 GiB RAM and private GGUF header/size; **not** full-file cryptographic identity.
- checkRequiredSLMCompatibility() prepares the native model but does not execute an inference.
- Existing higgins_triage role is investigation-readiness advice, not a mandatory initial scam semantic verdict.

## Candidate evaluation
Baseline: **shipping Qwen2.5-0.5B-Instruct Q4_K_M**.
Challengers (subject to actual compatible, licensed GGUF variants and device feasibility):
- Gemma 3 4B instruction-tuned, quantized GGUF.
- Qwen3 4B instruction-tuned, quantized GGUF.

These are **candidates, not recommendations**. Record exact model revision, quantization, GGUF checksum, licence, tokenizer/template, runtime build and device/OS. Larger candidates must not silently bypass admission, device storage, battery or memory constraints. Do not change the installed model until evidence and explicit approval support migration.

## Corpus and labels
Use consented or synthetic cases only; remove personal data and cross-device case details. Store source type, language, source text, expected action/exposure, expected semantic class, deception evidence and uncertainty. Include **paired benign/scam** cases for:
1. Genuine invoice vs changed-bank-account invoice.
2. Real bank security alert vs credential-collection link.
3. Real OTP delivery vs request to read out an OTP.
4. Routine IT remote-support discussion vs unsolicited remote-control demand.
5. Routine software install/update notice vs social-engineered installation.
6. Legitimate recruitment/onboarding vs advance-fee or credential-harvesting job offer.
7. Ordinary switch to WhatsApp/Signal vs off-platform payment/identity pressure.
8. Ordinary family emergency message vs new-number impersonation requesting transfer.
9. Real delivery update vs fake delivery-fee link.
10. Legitimate payment deadline vs coercive impersonation.
11. Legitimate authentication forwarding/DMARC failure vs deceptive sender.
12. Quotes, warnings, negated instructions, forwarded content, hypothetical examples.
13. Australian English and relevant multilingual variants.
14. Long messages and evidence over context budget; missing, conflicting and adversarial evidence.
15. Prompt-injection instructions embedded in untrusted evidence.

Do not count a brand claim, payment word, urgency, SPF failure, job offer, unknown SMS sender or remote-access software name as standalone proof of fraud.

## Test method
- Run **the same frozen case corpus** with the same source IDs and the same requested output schema on every candidate.
- Use native release-like builds on **physical Android and iOS devices**, spanning the minimum supported RAM and representative mid/high tiers.
- Run offline (airplane mode) and online, with no case-data cloud fallback.
- At least three independent cold-start sessions and repeated warm runs per model/device; record run counts and seed/sampling settings.
- Record model-load time, peak resident memory, first-token and total inference latency (where supported), tokens/sec, battery delta, temperature/thermal throttling, crash/OOM, context rejection and app foreground/background behaviour.
- Validate JSON syntax, allowed keys, evidence-ID references, grounding, negation, requested vs confirmed action, exposure uncertainty, and prompt-injection resistance.
- Compare **per-class precision/recall**, especially false-positive rate on legitimate communications, false-negative rate on confirmed scams, and abstention/limited rate.
- Report results per source type and language, not only one aggregate score. Review false-positive and false-negative examples manually.
- Treat syntax-valid JSON as necessary but insufficient: a fabricated identifier or unsupported exposure claim is a failure.
- Any context overflow must produce an explicit incomplete/limited result, never silently truncate or report a clean examination.

## Acceptance gates (release criteria, not measured results)
**Hard gates:** no cross-device case data; no invented verified identity/URL/account/evidence ID accepted; no silent truncation; no cloud inference fallback; no unqualified safe result when required semantic assessment fails; no unsupported model on admitted hardware; native build and App Store/Play policy review.

**Calibration gates:** set numerical thresholds *before* unblinding the holdout corpus, using product risk review and baseline performance. Explicitly require lower legitimate-message false positives without materially increasing confirmed-scam misses. Report confidence intervals and coverage; no cherry-picking.

**Performance gates:** agree minimum-device latency, memory, crash, thermal and battery budgets before selection. Compare to current shipping model and reject any candidate that fails minimum-device feasibility even if semantic accuracy improves.

**Decision:** Keep current Qwen only if it passes every hard gate and agreed accuracy/performance thresholds. Adopt another model only if it is demonstrably better and feasible on both platforms, with explicit migration approval. If none passes, Phase 3 remains blocked; do not falsely certify mandatory SLM triage.

## Required evidence package
- Exact corpus version, label provenance and class distribution (no private source material in logs).
- Candidate model IDs, GGUF SHA-256, quantization and licences.
- Android/iOS hardware/OS/build matrix and repeatable test commands.
- Per-case blinded outcomes and aggregate confusion matrices.
- JSON/grounding/negation/exposure failures, error and context-overflow counts.
- Load/inference/memory/thermal/battery metrics with distributions.
- Regression report against deterministic Wright triage and device/server parity.
- Signed-off model selection and explicit approval before shipping model changes.

## Known Phase 3 blockers
No physical-device inference or performance evidence is available from this GitHub-only audit. The current role prompt is not a complete Wright semantic schema. The current admission routine does not verify a full GGUF checksum. Grammar-constrained JSON is not configured. The backend/frontend rule tests added in Phase 2 have not been executed. These facts must be resolved or accounted for before qualification sign-off.
