# Apollo Round 1 — expected versus actual

Generated: 2026-09-21T03:48:32.124993+00:00
Browser target: `https://case-source-preview--3ijise2t.preview.emergentagent.com`
Execution mode: **live**

Expected outcomes are source-controlled in `frontend/scripts/round1-scenario-engine.ts` before execution. Local preflight, real downstream browser evidence and device-only work are deliberately separate. Local preflight is not investigation/Higgins acceptance.

## Outcome summary

- Local application-logic preflight: **35/35 matched expectations** — not counted as external investigation or Higgins acceptance
- Browser journeys: **0/3 complete**, **1 partial**, **2 failed**, **0 blocked**
- Device-only scenarios: **6 blocked from browser completion and not counted as complete**
- External-source handling: **configured real services in every mode; no verdict, finding or Higgins response is injected**

## Local preflight across all ten Gates — not downstream acceptance

| ID | Gate | Situation | Expected state / detection / action | Actual state / detection / action | Outcome |
|---|---|---|---|---|---|
| `site-threat-protection-gap` | site | threatening | barking; Needs attention; Restore protection; must not: apollo blocked, automatic protection is confirmed when unavailable | barking; Needs attention; Restore protection | COMPLETE |
| `site-legitimate-active` | site | legitimate | resting; Active; Open Link Gate; must not: apollo blocked, automatic protection is confirmed when unavailable | resting; Active; Open Link Gate | COMPLETE |
| `site-ambiguous-stale` | site | ambiguous | barking; Needs attention; Restore protection; must not: apollo blocked, automatic protection is confirmed when unavailable | barking; Needs attention; Restore protection | COMPLETE |
| `link-threat-bank` | link | threatening | barking; mentions; keep the link closed; must not: verified safe, sender is verified | barking; Websites ending in .xyz are frequently used for scams. The address men; Keep the link closed and use the claimed service's official app. | COMPLETE |
| `link-legitimate-public` | link | legitimate | resting; No local warning; open only if expected; must not: verified safe, sender is verified | resting; No local warning was found; Open only if expected; the sender remains unauthenticated. | COMPLETE |
| `link-ambiguous-short` | link | ambiguous | ears_up; shortened; expand or verify independently; must not: verified safe, sender is verified | ears_up; This is a shortened link, so the real destination is hidden.; Expand or verify independently before opening. | COMPLETE |
| `text-threat-code` | text | threatening | barking; Verification code request; don't share; must not: sender is verified, message is safe | barking; Verification code request; Don't share that code. Verification codes are meant for you, not for someone contacting yo | COMPLETE |
| `text-legitimate-appointment` | text | legitimate | resting; No concern identified; nothing to do; must not: sender is verified, message is safe | resting; No concern identified; Nothing to do. If it's from a number you don't know, reply cautiously and never share code | COMPLETE |
| `text-ambiguous-family` | text | ambiguous | ears_up; Hi Mum; contact your family; must not: sender is verified, message is safe | ears_up; Hi Mum / Hi Dad pattern; Before sending money, contact your family member using the number you already know. | COMPLETE |
| `call-threat-code` | call | threatening | barking; Verification code; Hang up; must not: caller is verified, apollo hung up | barking; Verification code request; Hang up. Open your bank's official app, or call the number on the back of your card. Banks | COMPLETE |
| `call-legitimate-appointment` | call | legitimate | resting; Ordinary; number listed; must not: caller is verified, apollo hung up | resting; Ordinary call; Look the business up yourself (their website or a directory) and call the number listed th | COMPLETE |
| `call-ambiguous-callback` | call | ambiguous | ears_up; Callback; details you find yourself; must not: caller is verified, apollo hung up | ears_up; Callback request; If they claim to be from an organisation, hang up and contact it using details you find yo | COMPLETE |
| `network-threat-dangerous` | network | threatening | barking; Dangerous traffic; Check This App; must not: i blocked, traffic was intercepted | barking; Dangerous traffic reported from an app; Open Check This App and remove it unless you can explain why it needs that traffic. | COMPLETE |
| `network-legitimate-home` | network | legitimate | resting; Home Wi; Nothing to do; must not: i blocked, traffic was intercepted | resting; Home Wi‑Fi; Nothing to do. | COMPLETE |
| `network-ambiguous-open` | network | ambiguous | ears_up; Open Wi; mobile data; must not: i blocked, traffic was intercepted | ears_up; Open Wi‑Fi (no encryption); Stick to https and your apps; use mobile data for anything sensitive. | COMPLETE |
| `account-threat-reset` | account | threatening | barking; Fake password reset; open account; must not: confirmed breach, sender is verified, fine to use | barking; Fake password reset; Don't tap the link. Open account.microsoft.com yourself (type it) or the Microsoft Authent | COMPLETE |
| `account-legitimate-requested` | account | legitimate | ears_up; matching your request; open myaccount; must not: confirmed breach, sender is verified, fine to use | ears_up; Password reset matching your request; Do not use the alert link. Open myaccount.google.com yourself or the Gmail app → your prof | COMPLETE |
| `account-ambiguous-breach` | account | ambiguous | ears_up; Claimed data breach; official app; must not: confirmed breach, sender is verified, fine to use | ears_up; Claimed data breach notice; Open the service's official app, or type its address yourself. Never use a link or number  | COMPLETE |
| `email-threat-bank` | email | threatening | barking; impersonating; official; must not: sender is verified, email is safe, original email was deleted | barking; Email impersonating CommBank; Delete it. Don't reply or use any link or number in the email. Open CommBank's official ap | COMPLETE |
| `email-legitimate-receipt` | email | legitimate | resting; Ordinary; Nothing; must not: sender is verified, email is safe, original email was deleted | resting; Ordinary email; Nothing to do. Come back if it asks you to log in, pay or install anything. | COMPLETE |
| `email-ambiguous-security` | email | ambiguous | ears_up; Security alert; official; must not: sender is verified, email is safe, original email was deleted | ears_up; Security alert to verify; Do not reply or use details from the email. Open the claimed service's official app or typ | COMPLETE |
| `app-threat-remote` | app | threatening | barking; Remote; remove; must not: app is safe, app is malicious, apollo uninstalled | barking; Remote access app during a suspicious call; End the session now: turn off Wi‑Fi and mobile data, hang up, then remove the app. Follow  | COMPLETE |
| `app-legitimate-notes` | app | legitimate | ears_up; official store; Re-check; must not: app is safe, app is malicious, apollo uninstalled | ears_up; App reported from the official store; No urgent action from this evidence alone. Re-check if its permissions change or it behave | COMPLETE |
| `app-ambiguous-cleaner` | app | ambiguous | ears_up; notifications; turn it off; must not: app is safe, app is malicious, apollo uninstalled | ears_up; Can read notifications; If Super Cleaner doesn't need notification access for what you use it for, turn it off in  | COMPLETE |
| `file-threat-disguised` | file | threatening | barking; Executable; Delete it; must not: verified safe, malware scan completed, cloud hosting makes it safe, original fil | barking; Disguised executable; Delete it unless you can independently verify the sender. Don't 'open with' anything. | COMPLETE |
| `file-legitimate-document` | file | legitimate | ears_up; Limited file; Do not treat; must not: verified safe, malware scan completed, cloud hosting makes it safe, original fil | ears_up; Limited file inspection; Do not treat this result as permission to open the file. Verify the sender; never enable m | COMPLETE |
| `file-ambiguous-archive` | file | ambiguous | ears_up; Password; Don't extract; must not: verified safe, malware scan completed, cloud hosting makes it safe, original fil | ears_up; Password-protected archive; Don't extract it unless you expected it. Never run anything inside it. | COMPLETE |
| `device-threat-remote` | device | threatening | barking; Remote; End the session; must not: threat was blocked, all apps were inspected | barking; Remote access was granted; End the session, remove the remote-access app, then review the accounts used while they we | COMPLETE |
| `device-legitimate-observed` | device | legitimate | resting; Apollo protection; operational; must not: threat was blocked, all apps were inspected | resting; Apollo protection is confirmed running; The device reported protection operational at 03:47 AM. | COMPLETE |
| `device-ambiguous-limited` | device | ambiguous | growling; Protection; Restore; must not: threat was blocked, all apps were inspected | growling; Apollo protection stopped; Restore the permission or protection service, then return to Device Gate and re-check. | COMPLETE |

## Realistic multi-Gate situations

| ID | Situation | Expected Gate path / meaning | Actual | Outcome |
|---|---|---|---|---|
| `multi-unexpected-purchase-message` | I received an unexpected purchase message. | {"gates": ["text", "link", "account"], "finding": "unexpected purchase pressure and off-domain account link", "uncertainty": "message does not prove a purchase occurred", "action": "open Pay | {"gates": ["text", "link", "account"], "text_state": "barking", "text_finding": "Bank fraud message", "link_level": "malicious", "action": "Don't enter your password or verification code. Open your bank's app y | COMPLETE |
| `multi-google-drive-file` | Someone shared this file from Google Drive. | {"gates": ["file"], "finding": "disguised executable; cloud hosting is not proof of safety", "uncertainty": "sender and complete contents remain unknown", "action": "keep closed and verify s | {"gates": ["file"], "state": "barking", "finding": "Disguised executable", "evidence": "Its name suggests a PDF file. Its actual type is executable content. Documents never need to be executable. Being hosted o | COMPLETE |
| `multi-caller-install-app` | A caller asked me to install an app. | {"gates": ["call", "app"], "follow_up_gate": "device only if the person says access was granted or the app was installed", "finding": "remote-access social engineering plus high-impact app c | {"gates": ["call", "app"], "call_state": "barking", "call_finding": "Remote access request", "app_state": "barking", "app_finding": "Remote access app during a suspicious call", "action": "Don't open it or read | COMPLETE |
| `multi-unfamiliar-installed-app` | I found an unfamiliar app already on my phone. | {"gates": ["app", "device"], "finding": "unfamiliar app and observed high-impact access", "uncertainty": "permissions do not prove malicious behaviour", "action": "review access and remove i | {"gates": ["app", "device"], "app_state": "growling", "app_finding": "Powerful accessibility access", "device_state": "growling", "device_finding": "Accessibility access: Device Helper", "action": "Revoke acces | COMPLETE |
| `multi-genuine-delivery-notification` | This is a genuine delivery notification. | {"gates": ["text", "link"], "finding": "delivery notification with configured official destination and no payment/login pressure", "uncertainty": "sender identity is not authenticated from t | {"gates": ["text", "link"], "text_state": "ears_up", "text_finding": "Delivery notification to verify", "link_level": "clean", "link_signals": [], "action": "Prefer the courier's official app or type its known  | COMPLETE |

## Normal app journeys

| ID | Gate | Situation | Expected | Actual | Outcome |
|---|---|---|---|---|---|
| `ui-link-threat` | link | Threatening bank lookalike | Barking result; persistent trusted verification; truthful continue label | Threat state Apollo is barking; This link does not belong to CommBank.; persistent verification instructions opened. Ambiguous shortened-link override label is truthful. Higgins qu | PARTIAL |
| `ui-file-handoff` | file | Disguised executable and post-open follow-up | Evidence-first follow-up; recovery; automatic Higgins Retry and continuity | AssertionError: Higgins output was rejected before reaching the user: File Gate showed Barking: This file is not really a PDF. Don't open it.; recovery worked. The user then saw: H | FAILED |
| `ui-device-setting` | device | Observed protection health and setting follow-up | Visible limitation, working setting guidance and retained Higgins context | AssertionError: Higgins output was rejected before reaching the user: Device Gate showed Growling: 1 item worth reviewing. Nothing confirmed dangerous.; the initial Higgins answer  | FAILED |

## Journey details — what the user actually saw

### `ui-link-threat` — PARTIAL

- **Expected:** Barking result; persistent trusted verification; truthful continue label
- **User saw:** Threat state Apollo is barking; This link does not belong to CommBank.; persistent verification instructions opened. Ambiguous shortened-link override label is truthful. Higgins quality: accuracy=yes, uncertainty=yes, action=yes, clarity=yes, depth=no. Exact live Higgins response: Please avoid the link and log in only via the official CommBank app. Apollo has noted that the provided link uses an unofficial '.xyz' TLD, which is the last part of a web address. Official communications from CommBank use 'commbank.com.au'. A technical inspection encountered a DNS failure, which is a failure to find the computer address for a website name. This often occurs with temporary scam pages. While no malicious listing was found, the domain—the unique name of a website—is not legitimate. If I may, I would suggest you treat this as a deceptive lure. Apollo has it in hand and confirms this address is not authorised.. Investigation display: LIVE INVESTIGATION: GEMINI COMPLETED — RESPONSE SHOWN VERBATIM. Sources shown: Submitted content analysis: INCONCLUSIVE — It looks like CommBank, but commbank-secure-verify.xyz is not one of CommBank's official domains.; Websites ending in .xyz are frequently used for scams.; The address mentions "com | Apollo link intelligence: INCONCLUSIVE — commbank-secure-verify.xyz: clean; coverage full. No current listing was found; this does not authenticate the site or prove safety. | Isolated webpage inspection: UNAVAILABLE — Inspection unavailable: dns_failed. | CommBank official guidance: CONCERN FOUND — Official domain: commbank.com.au. No submitted link matches.
- **Cause/gap:** Higgins answer for link did not explain why the evidence mattered
- **Artifact:** `/app/test_reports/round1_artifacts/live/ui-link-threat.png`

### `ui-file-handoff` — FAILED

- **Expected:** Evidence-first follow-up; recovery; automatic Higgins Retry and continuity
- **User saw:** AssertionError: Higgins output was rejected before reaching the user: File Gate showed Barking: This file is not really a PDF. Don't open it.; recovery worked. The user then saw: Higgins' answer did not meet Apollo's evidence rules. Retry.
- **Cause/gap:** AssertionError: Higgins output was rejected before reaching the user: File Gate showed Barking: This file is not really a PDF. Don't open it.; recovery worked. The user then saw: Higgins' answer did not meet Apollo's evidence rules. Retry.
- **Artifact:** `/app/test_reports/round1_artifacts/live/ui-file-handoff.png`

### `ui-device-setting` — FAILED

- **Expected:** Visible limitation, working setting guidance and retained Higgins context
- **User saw:** AssertionError: Higgins output was rejected before reaching the user: Device Gate showed Growling: 1 item worth reviewing. Nothing confirmed dangerous.; the initial Higgins answer arrived. The user then saw on follow-up: Higgins' answer did not meet Apollo's e
- **Cause/gap:** AssertionError: Higgins output was rejected before reaching the user: Device Gate showed Growling: 1 item worth reviewing. Nothing confirmed dangerous.; the initial Higgins answer arrived. The user then saw on follow-up: Higgins' answer did not meet Apollo's evidence rules. Retry.
- **Artifact:** `/app/test_reports/round1_artifacts/live/ui-device-setting.png`

## Device-only scenarios — blocked from browser evidence

- `site-native-confirmed-block` (site) — **BLOCKED**: Requires a real supported filter and device-recorded enforcement evidence.
- `call-native-screening-rejection` (call) — **BLOCKED**: Requires a real incoming call and supported call-screening role.
- `file-native-share-provider` (file) — **BLOCKED**: Requires Android/iOS share sheet, provider metadata and content URI access.
- `device-native-settings-return` (device) — **BLOCKED**: Requires real Settings deep links and refresh after returning to Apollo.
- `app-native-inventory-permissions` (app) — **BLOCKED**: Requires platform-exposed app inventory and permission observations.
- `network-native-enforcement` (network) — **BLOCKED**: Requires real network events; Stage 1D packet-blocking acceptance remains cancelled.

## Weakest outcomes

- `ui-link-threat` — **PARTIAL**: Threat state Apollo is barking; This link does not belong to CommBank.; persistent verification instructions opened. Ambiguous shortened-link override label is truthful. Higgins quality: accuracy=yes, uncertainty=yes, action=yes, clarity=yes, depth=no. Exact live Higgins response: Please avoid the link and log in only via the official CommBank app. Apollo has noted that the provided link uses an unofficial '.xyz' TLD, which is the last part of a web address. Official communications from CommBank
- `ui-file-handoff` — **FAILED**: AssertionError: Higgins output was rejected before reaching the user: File Gate showed Barking: This file is not really a PDF. Don't open it.; recovery worked. The user then saw: Higgins' answer did not meet Apollo's evidence rules. Retry.
- `ui-device-setting` — **FAILED**: AssertionError: Higgins output was rejected before reaching the user: Device Gate showed Growling: 1 item worth reviewing. Nothing confirmed dangerous.; the initial Higgins answer arrived. The user then saw on follow-up: Higgins' answer did not meet Apollo's e

## Runtime mocks, templates and deterministic fallbacks

- Web preview native device/network/app observations remain simulated or unavailable and are never treated as physical-device evidence.
- The deterministic 35-scenario engine is expectation preflight only; it does not stand in for external investigation or a Higgins response.
- Investigation fallback assessments remain a runtime safety path when Gemini is unavailable or rejected. The UI labels them as deterministic fallback, and any journey using one is PARTIAL rather than complete.
- Structured Higgins handoffs retry real Gemini once after a transport or grounding rejection. They do not substitute a canned answer; after both attempts fail, the user sees a Retry error and the journey is FAILED or BLOCKED.

## Remaining capability gaps

- **Bounded evidence handoff:** Ask Higgins currently carries at most 8 findings, 6 uncertainty items and 4 supported actions. Each item is length-bounded; longer investigations can still lose lower-priority evidence.
- **Bounded investigation inputs:** Message/email text and isolated webpage excerpts are intentionally capped before Gemini processing. This protects privacy and latency but is not complete-document or complete-page analysis.
- **Restricted research:** Live investigation uses configured reputation sources, official-brand guidance and an SSRF-protected page fetch. It has no unrestricted general web-research tool; DNS/SSRF/provider failures remain unresolved evidence rather than inferred verdicts.
- **Provider/guard compatibility:** Real Gemini prose can still fail the unsupported-capability, uncertainty or action contract. Ask Higgins then shows a Retry error and does not silently replace the answer.
- **Native scope:** Physical Stage 1D work remains cancelled. Native macOS/Windows enforcement adapters remain backlog, while current device-specific Settings guidance is still reviewed in browser where possible.

## Interpretation rule

A scenario passes only when the selected Gate is understandable, the detection preserves uncertainty, the investigation does not overclaim, Higgins provides a plain explanation, and the person can complete one labelled next action. Test count alone is not acceptance.
