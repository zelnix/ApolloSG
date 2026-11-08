# Luddish SLM — first on-device benchmark candidate

This is a **benchmark candidate**, not an approved production scam-investigation model.

| Field | Value |
|---|---|
| Model | Qwen2.5-0.5B-Instruct, official Qwen GGUF |
| Quantisation | Q4_K_M |
| File | `qwen2.5-0.5b-instruct-q4_k_m.gguf` |
| Authoritative source | https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/blob/main/qwen2.5-0.5b-instruct-q4_k_m.gguf |
| SHA-256 (published by model host) | `74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db` |
| Approximate download | 491 MB |
| Licence listed by publisher | Apache-2.0 |
| Primary initial test | Can Expo/llama.rn run a small GGUF locally at all? |

## Explicit manual device-test provisioning

1. Download this precise file from its official source **only onto a test machine**.
2. Verify the SHA-256 before copying or installing it:

```sh
cd frontend
node scripts/slm-verify-gguf.cjs /path/to/qwen2.5-0.5b-instruct-q4_k_m.gguf 74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db
```

3. Copy to the app's private device storage using an explicit test-device provisioner, not Git/GitHub, a web URL or shared storage.
4. Verify integrity again on the device using native file hashing before marking `deviceAdmitted: true`.
5. Test on a **real Android/iOS native development build**. Record cold start, response validity, evidence-citation fidelity, cross-case isolation, memory peak, responsiveness, thermals and device resource use.
6. Compare against ApolloSG's existing investigation acceptance corpus. The 0.5B candidate is **not assumed adequate** for complex evidence reasoning, multilingual scams or high-stakes verdict support. Test a larger candidate only if actual device benchmarks warrant it.

No model weights or model downloads belong in this repository. No model is loaded by default. External verification continues through TC Hawkeye / Magnum DI; Gemini remains Magnum DI's specifically warranted extension, not a fallback after SLM failure.

## Release gate

A production model must be separately approved after: evidence-grounding and benign-case regression tests; source/licence review; reproducible SHA-256; performance benchmarks; Android and iOS native build success; physical-device tests; and preservation of Evidence Lock and Higgins explanation fidelity. Do not claim any of these gates from a CI prebuild alone.
