# ApolloSG SLM — controlled Android device acceptance

**Branch:** `slm`. **Production:** unchanged. **Current behaviour:** the SLM remains unregistered and disabled. Installing the APK alone does NOT enable model inference or prove shared SLM functionality.

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

Never fetch model weights at runtime from an unverified URL, commit them to GitHub, or assume an external-storage copy is safe. A private-app-storage provisioning path and on-device SHA-256 verification must be implemented before actual model admission; these do not yet exist.

## 3. Activate shared runtime, only after admission

Once a verified private file URI, trusted identity and device admission decision exist, the native application bootstrap can create a single `LocalLlamaRuntime` from `llamaRnBinding.native.ts` and register it through `setSharedSLM()`.

**Not done yet:** App bootstrap, streamed SHA-256 verification on the phone, native model lifecycle cleanup, device RAM admission, and a test-device local GGUF provisioner. The current bridge rejects setup without explicit admission. Do not mark these complete merely because Android compilation passes.

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
