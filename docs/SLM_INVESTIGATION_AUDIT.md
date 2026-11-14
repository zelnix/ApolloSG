# Investigation history and on-device SLM records

History and DI consume the same case-scoped audit state. History includes recorded
triage, Hawkeye and Magnum stages as well as the case lifecycle and SLM handoffs.
DI shows each SLM role, its recorded lifecycle and expandable validated output.

An issued request is not proof of native execution. The device records the first
actual adapter invocation, the validated stage result or safe failure code, and the
validated coordinator receipt separately. Source-window processing produces the
existing validated aggregate result. Invalid native replies are not retained or
presented as valid output. Output and receipt acceptance are advisory, not evidence,
verification or approval of a final Finding. A generic headline cannot establish an
Evidence Lock without a response or recorded complete investigation result.

Server DI supplies only owner/case-scoped request and receipt metadata; it does not
decrypt expired requests or send model replies, prompts or submitted evidence for
audit display. The native device retains its validated output and a DI snapshot in
its existing private local storage. This allows history to remain available after
the server's temporary investigation expires. It does not extend server retention.
Local data is scoped by device identity and case. Case deletion tombstones audit
writes, and privacy wipes fence pending callbacks, including after storage removal.

A lost receipt retries the identical pending payload without another inference.
A locally recorded accepted receipt also prevents a replay from rerunning that
request. Case revision, request identity and existing server validation remain in
force. The audit never changes triage admission, verdict rules, scoring or evidence.

Older investigations may have server request/receipt timestamps but no local
execution timestamps or output. Those missing records are shown as unavailable;
they cannot be reconstructed or treated as proof that inference ran. An old APK
does not collect the new local audit records.

Regression coverage includes ownership, late writes after deletion/wipes, recorded
timestamps, output preservation, lost acknowledgements, invalid output, cross-case
requests, engine history without a patrol event and uncommitted Evidence Locks.
No APK build or deployment is needed to run these tests.
