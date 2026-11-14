# Brief background/foreground failure in build 3

Reported symptom: the app surface stays blank after a brief switch away and back.
A screenshot alone does not prove a device-specific root cause.

A concrete matching exception was found in the shared runtime's AppState path:
llama.rn 0.12.9 declares `stopCompletion()` as returning `Promise<void>`, but its
`cpp/jsi/RNLlamaJSI.cpp` implementation of `llamaStopCompletion` sets the interruption
flag and returns `jsi::Value::undefined()`. Its TypeScript wrapper returns that
value directly. The app's `.stopCompletion?.().catch(...)` therefore dereferenced
`undefined.catch` during backgrounding, even with an idle loaded model. React error
boundaries do not catch exceptions from lifecycle event handlers.

The void-returning native form reproduced failures in the new resume tests before
the correction. The fix:

- Normalises native stop at the binding boundary and accepts void or a Promise.
- Stops native work only during an actual generation, never an idle app switch.
- Contains synchronous stop exceptions and rejected stop promises in the lifecycle
  handler, without logging source content or native exception text.
- Keeps the serial execution slot until the original native operation settles.
- Rechecks suspension/cancellation generation after model loading or tokenisation,
  so returning to the app cannot revive an interrupted old request.

The model remains required. The fix does not replace or unload the registered
runtime on an ordinary app switch, recreate navigation, change protection decisions,
retry a case automatically, delete evidence or clear app data.

Regressions cover idle warm resume, active cancellation with a void native stop,
synchronous native stop failure, backgrounding during load/tokenisation, and stale
chat preflight. Test responses are substituted, not physical Fold6 evidence.

The installed build 3 does not contain this source correction. A new separately
authorised APK is required for phone verification; no new build or deployment is
started by this source fix. If blank rendering persists with the correction, native
and JavaScript lifecycle diagnostics are needed to investigate other causes.
