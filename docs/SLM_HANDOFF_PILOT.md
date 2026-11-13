# ApolloSG on-device handoff — current status

Updated 13 November 2026. The original optional pilot design is superseded by
the mandatory native investigation pipeline. It must not be used to configure
a web-preview bypass. The historical pilot text is retained in Git history.

## Current investigation contract

Every first-turn investigation requires on-device Wright semantic triage,
TC Hawkeye investigation, on-device Higgins escalation assessment, optional
Magnum DI when warranted, and a validated on-device Finding/presentation.
There is one shared admitted native runtime. Model hypotheses do not become
source facts, numeric ratings or independently verified evidence. Hawkeye's
deterministic evidence classification, reconciliation and retained floors remain
authoritative at the existing acceptance boundary.

The authenticated device identity, case/job ownership, revision, epoch, work
epoch, cancellation and lease fences continue to govern every request/result.
Requests/results use the existing encrypted investigation-device request store;
they are not observations accepted through the ordinary device-results endpoint.

## Configuration and preview behavior

SLM is a core capability, with no handoff or native-build on/off switch. The
retired `APOLLO_SLM_HANDOFF` and `APOLLO_SLM_NATIVE` environment settings are not
read. The native plugin is always part of native builds, and valid native stage
results are always required by the coordinator. Old environment entries cannot
disable it or enable a fallback.

Web previews and Expo Go cannot provide the required native model. They may be
used for UI and backend/API checks, but successful live investigations require
a supported native build with an admitted model. Do not introduce a switch to
make preview investigations appear successful, or a
deterministic-only, simulated or external-model fallback.

The selected Android release target is ARM64-only. Compatibility admission also
requires at least 3 GiB reported memory, admitted model files, runtime startup
and valid inference output. Artifact compilation is not physical-device model,
lifecycle, thermal or evidence-storage acceptance.

## Current verification and remaining qualification

The bounded regression gate exercises request correlation, device isolation,
evidence coverage, failures, deadlines, cancellation/recovery, retained verdicts
and score transparency. See `APOLLO_REVIEW_REPAIRS.md` and
`.github/workflows/ci.yml` for the current checks and their limits.

Native investigation timing, real model quality and end-to-end acceptance on
supported physical devices remain separate qualification work. A preview
without that native capability must continue to report `device_unavailable`.
