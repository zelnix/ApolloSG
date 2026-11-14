# ApolloSG Qwen3 internal test APK — build 3

- Package: `app.apollo.hwg`, version `1.1.0`, Android versionCode `3`.
- APK source: `2ef6517cebaa50b1754d4f7f561d56d1b8e60c20`.
- Architecture: `arm64-v8a` only; 46 native libraries. JavaScript is bundled.
- Size: 177,783,786 bytes.
- SHA-256: `6d3c3fd17c9d244c97aa14be1acefde83863c99b04381ecd4f7221ca2fa52ec0`.
- Signing certificate SHA-256: `fac61745dc0903786fb9ede62a962b399f7348f0bb6f899b8332667591033b9c`.
- The exact published APK was downloaded and independently checked with the APK
  signature verifier, manifest inspector, ABI guard and embedded-profile checks.

[Download APK](https://github.com/zelnix/ApolloSG/releases/download/slm-qwen3-build3-2ef6517/ApolloSG-1.1.0-build3-qwen3-arm64.apk)

[Checksum](https://github.com/zelnix/ApolloSG/releases/download/slm-qwen3-build3-2ef6517/ApolloSG-1.1.0-build3-qwen3-arm64.apk.sha256)

Higgins uses the pinned Qwen3-1.7B Q4_K_M package with an 8192-token context,
non-thinking generation and CPU execution. The approximately 1.11-GB GGUF downloads
separately; it is not embedded in the APK. Physical-device model quality, memory,
latency and thermal qualification remain pending. No backend deployment occurred.

After Qwen3 successfully loads, startup removes only the previous app-private
Qwen2.5 model file. Failure to load Qwen3 preserves that file. Imported originals,
case evidence, investigations and settings are not deleted by this migration.

The native compile succeeded; publication initially stopped because a newly
created test signing identity differed from the previous GitHub APK. The owner
explicitly approved the existing PUBLIC test identity for this APK only, after
being informed that its publicly available test private key permits forged test updates. The completed
APK was re-signed and verified for an in-place update, preserving package identity.
This is not a Play/store signing key or a signing policy for future builds.
The fixed-artifact one-time publisher has been removed; no future key pin was added.
Ordinary pushes continue to skip APK builds. Future builds require their own
signing decision; this one-APK approval must not be reused.
