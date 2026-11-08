# ApolloSG SLM — controlled Android device acceptance

**Branch:** `slm`. **Production:** unchanged. **Current behaviour:** development builds attempt local admission at startup ONLY when the exact model exists in app-private documents. Release builds stay disabled. Installing the APK alone does NOT install weights or prove real inference.

## 1. Get an installable test build

The existing `SLM Android native compile` GitHub Actions workflow now uploads the debug APK as a short-lived artifact named `apollosg-slm-android-debug` after successful `assembleDebug`.

- Open GitHub > Actions > SLM Android native compile > most recent passing run.
- Download the `apollosg-slm-android-debug` artifact, unzip it and install the APK only on a dedicated test Android phone.
- This debug APK is not a store release and should not be distributed as a production app.

## 2. Model acquisition and verification

Use the model filename and **published** SHA-256 identified in `docs/SLM_MODEL_BENCHMARK.md`. Verify on a test machine:

```bash
node frontend/scripts/slm-verify-gguf.cjs /secure/local/qwen2.5-0.5b-instruct-q4_k_m.gguf 74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db
```

Never fetch model weights automatically, commit them to GitHub, or treat shared storage as approved. The development-only private-file installation function is `installPrivateLuddishForTest(localFileUri)`, and startup checks the fixed filename in `Paths.document`. A model must come from an explicitly selected local file, or be copied into the debug app's private files directory for controlled testing. No public model-picker UI is enabled. The first candidate's publisher digest has not yet been independently reconfirmed from a downloaded file.

## 3. Activate shared runtime, only after admission

In development builds only, `frontend/app/_layout.tsx` calls `startSharedLuddish()`. The native bootstrap checks `Paths.document/qwen2.5-0.5b-instruct-q4_k_m.gguf`, requires at least 3 GiB of reported total RAM, streams a SHA-256 over the entire private file using 128 KiB chunks (without loading the weights into JS memory), and compares the result to the pinned candidate digest. Only then does it construct the shared `LocalLlamaRuntime` and register it with `setSharedSLM()`. Both Ask Higgins and stage-specific investigations obtain this one instance via `getSharedSLM()`.

For a dedicated Android *debug* device, developers may copy the verified GGUF into the app's private documents using their normal development tools (for example, Android Debug Bridge `run-as` for a debuggable installation), then restart the app. The exact package name and private path must be determined from the installed build; never guess them or enable shared storage access in production.

**Implemented in code, not yet physically verified:** fail-closed startup, bounded-memory SHA-256 verification with standard test vectors, conservative RAM admission, single shared runtime registration, explicit dev-only local-file import function and runtime release function. **Still outstanding:** on-device installation of the actual weights, physical memory/latency testing, automatic shutdown lifecycle integration, model provenance audit, and any user-visible installation flow. A passing CI test must not be treated as proof of a real device inference. The candidate remains disabled in release builds.

The **same** runtime must be used by Ask Higgins and all four investigator roles. No secondary model instance, model download service, or Gemini fallback.

## 4. Physical QA

- Confirm a cold model load and first structured result on a real Android phone.
- Record RAM, model load time, response latency, CPU/thermal impact and battery load.
- Check a benign golf-meeting text, a fraudulent-return claim, ambiguous messages, prompt injections, missing evidence and a revoked/cancelled case.
- Verify all model citations name only provided evidence IDs; no model verdict or score is accepted.
- Confirm concurrent Ask Higgins requests and case-stage requests serialize through the same model context.
- Check interrupted app/background/restart and request expiry.
- Confirm deterministic Higgins answers and investigation results are unchanged whenever the SLM is unavailable.

## 5. What GitHub tests mean

Contract, type and Android build success establish **build compatibility** and **offline contract integrity**, not actual local inference. Coordinator advisories are currently non-blocking and not used as authoritative investigation inputs. iOS native build/device testing is also outstanding.
