# Ask Higgins — shared on-device Luddish SLM (staged)

Ask Higgins is the same existing screen and chat API. No second chat UI, backend chat engine or SLM model is introduced.

## Implemented

- Shared runtime registry: `frontend/src/domain/slm/sharedRuntime.ts`.
- The existing `askHiggins()` client receives its verified backend response first, then optionally calls `explainHigginsWithSLM()` when a validated native SLM adapter has been registered.
- The same SLM interface now recognises the `ask_higgins` role and `chat_explanation` operation.
- The SLM may propose a clearer wording of an ordinary chat answer only. It cannot alter backend evidence basis, citations, navigation, actions, case verdicts, scores or status.
- Fidelity checks compare the original server answer with the SLM draft. Source quotations, device-specific/current-context responses, active investigations and ambiguous replies bypass rewrites altogether.
- If the model is absent, unavailable, rejects the request or returns a risky rewrite, the original verified Higgins answer is kept.

## Important current limitation

Although the chat client integration and shared runtime registry are implemented, no validated model is registered during app startup. This is intentionally inert until native model provisioning and physical-device admission are complete. Do not advertise Ask Higgins as powered by live SLM inference until then.

## Remaining work

1. Select, hash-verify and benchmark the GGUF on physical Android/iOS devices.
2. Supply the admitted one-per-app `LocalLlamaRuntime` to `setSharedSLM()` from the native app lifecycle, release it on shutdown, and ensure no parallel model installations.
3. Verify safe conversational quality against evidence-specific and misleading-question test cases, including links, numbers, quoted articles, scams and source provenance.
4. Measure latency and resource impact in the existing Ask Higgins screen and add runtime capability states without creating additional UI.
5. Continue full investigation coordinator integration separately; Ask Higgins must not become a second investigator.

Gemini remains an optional Magnum DI extension, never an SLM failure fallback.
