# On-device small language model (SLM)

**Status:** source added on branch `slm-claude`. Not yet built or run on a device.

## What it is

ApolloSG can now use the small language model that is built into the phone:

| Platform | Model | Runtime | Requirement |
|---|---|---|---|
| Android | Gemini Nano | ML Kit GenAI Prompt API (AICore) | An AICore-supported device (e.g. recent Pixel / Galaxy). The OS downloads the model. |
| iOS | Apple on-device foundation model | `FoundationModels` framework | iOS 26+, Apple Intelligence on, eligible iPhone. |

ApolloSG bundles no model weights. Nothing the model reads or writes leaves the phone. It is **off by default**.
The person turns it on in **Settings → App → On-device AI**, and that row shows whether the phone's model is ready.

## What it does (advisory only)

1. **Plain-language explanation** of a result that Apollo has already settled (Message check result, under
   "On this phone"). The re-wording is checked before it is shown. It is rejected if it reassures ("safe",
   "genuine"…) without a negation, adds a link or a number that isn't in the result, or dismisses the advice. When
   it is rejected, nothing extra is shown: Apollo's fixed wording is already complete.
2. **Pre-screen pointers**: requests to act (send money, share a code or details, install something, remote access,
   call or reply), a claimed organisation, and urgency. Each pointer must quote the message word for word. A quote
   that isn't in the text, or that a negation governs ("we will never ask you to…"), is dropped. Only pointers the
   fixed rules didn't already name are shown. When one of them is a request to act, the note offers to hand the
   message to Higgins.

## What it never does

- It never sets or changes a state, verdict, Gate result or Higgins action. `advisoryFor()` takes no state and
  returns none (`changedResult: false`). Gate checks stay fixed catalogue rules (OPERATING_RULES, Gate checks 4),
  Higgins Triage stays no-network/no-AI, and Biting still needs a verified packet.
- It is not an investigation model. Magnum DI and TC Hawkeye run on the server through the single AI gateway
  (`backend/services/higgins/provider.py`) and need JSON, vision and web search. A phone model can't be called from
  there, so it is not listed in ApolloSG Settings → AI Provider & Model.
- No retry and no other model. A failure, timeout (12 s) or unavailable model shows nothing extra.

## Where the code is

- `frontend/modules/apollo-slm/`: Expo module. `android/…/ApolloSlmModule.kt` (ML Kit GenAI) and
  `ios/ApolloSlmModule.swift` (FoundationModels, weak-linked, `#available(iOS 26)`). `index.ts` returns
  "unavailable" when the module isn't in the build (web, Expo Go).
- `frontend/src/slm/core.ts`: the rules (input redaction, prompts, verbatim-quote and negation checks, explanation
  checks). Pure; tested by `yarn test:slm` (`tests/onDeviceSlm.test.ts`).
- `frontend/src/slm/onDeviceSlm.ts`: the setting, status, one call with a timeout.
- `frontend/src/components/OnDeviceAiNote.tsx`: the "On this phone" card. It renders through the new `footer` slot
  of `CheckResultScreen` / `InvestigationCheckScreen`, below the result.

## Before release

- Confirm the ML Kit artifact version (`com.google.mlkit:genai-prompt`) against Google Maven, then run an EAS
  Android build. Google Maven couldn't be reached from the authoring environment.
- Build on iOS with an Xcode version whose SDK includes FoundationModels (iOS 26 SDK).
- On-device acceptance: one AICore phone, one non-AICore phone, one Apple Intelligence iPhone, one older iPhone.
  Check the Settings status line, the note's appearance, and that the result above it is identical with the
  setting on and off.
- Update the privacy disclosure to say on-device AI processes message text locally when it is turned on.
