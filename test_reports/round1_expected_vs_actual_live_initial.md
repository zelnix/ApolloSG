# Apollo Round 1 — expected versus actual

Generated: 2026-09-20T14:56:27.120876+00:00
Browser target: `https://case-source-preview--3ijise2t.preview.emergentagent.com`
Execution mode: **live**

Expected outcomes are source-controlled in `frontend/scripts/round1-scenario-engine.ts` before execution. Automated engine evidence, browser evidence and device-only work are deliberately separate.

## Outcome summary

- Deterministic situations: **35/35 passed**
- Browser journeys: **7/10 passed**
- Device-only scenarios: **6 pending and not counted as browser completions**
- External-source handling: **configured live services; individual unavailability is reported in actual UI outcomes**

## All ten Gates: threatening, legitimate and ambiguous situations

| ID | Gate | Situation | Expected state / detection / action | Actual state / detection / action | Outcome |
|---|---|---|---|---|---|
| `site-threat-protection-gap` | site | threatening | barking; Needs attention; Restore protection | barking; Needs attention; Restore protection | PASS |
| `site-legitimate-active` | site | legitimate | resting; Active; Open Link Gate | resting; Active; Open Link Gate | PASS |
| `site-ambiguous-stale` | site | ambiguous | barking; Needs attention; Restore protection | barking; Needs attention; Restore protection | PASS |
| `link-threat-bank` | link | threatening | barking; mentions; keep the link closed | barking; Websites ending in .xyz are frequently used for scams. The address men; Keep the link closed and use the claimed service's official app. | PASS |
| `link-legitimate-public` | link | legitimate | resting; No local warning; open only if expected | resting; No local warning was found; Open only if expected; the sender remains unauthenticated. | PASS |
| `link-ambiguous-short` | link | ambiguous | ears_up; shortened; expand or verify independently | ears_up; This is a shortened link, so the real destination is hidden.; Expand or verify independently before opening. | PASS |
| `text-threat-code` | text | threatening | barking; Verification code request; don't share | barking; Verification code request; Don't share that code. Verification codes are meant for you, not for someone contacting yo | PASS |
| `text-legitimate-appointment` | text | legitimate | resting; No concern identified; nothing to do | resting; No concern identified; Nothing to do. If it's from a number you don't know, reply cautiously and never share code | PASS |
| `text-ambiguous-family` | text | ambiguous | ears_up; Hi Mum; contact your family | ears_up; Hi Mum / Hi Dad pattern; Before sending money, contact your family member using the number you already know. | PASS |
| `call-threat-code` | call | threatening | barking; Verification code; Hang up | barking; Verification code request; Hang up. Open your bank's official app, or call the number on the back of your card. Banks | PASS |
| `call-legitimate-appointment` | call | legitimate | resting; Ordinary; number listed | resting; Ordinary call; Look the business up yourself (their website or a directory) and call the number listed th | PASS |
| `call-ambiguous-callback` | call | ambiguous | ears_up; Callback; details you find yourself | ears_up; Callback request; If they claim to be from an organisation, hang up and contact it using details you find yo | PASS |
| `network-threat-dangerous` | network | threatening | barking; Dangerous traffic; Check This App | barking; Dangerous traffic reported from an app; Open Check This App and remove it unless you can explain why it needs that traffic. | PASS |
| `network-legitimate-home` | network | legitimate | resting; Home Wi; Nothing to do | resting; Home Wi‑Fi; Nothing to do. | PASS |
| `network-ambiguous-open` | network | ambiguous | ears_up; Open Wi; mobile data | ears_up; Open Wi‑Fi (no encryption); Stick to https and your apps; use mobile data for anything sensitive. | PASS |
| `account-threat-reset` | account | threatening | barking; Fake password reset; open account | barking; Fake password reset; Don't tap the link. Open account.microsoft.com yourself (type it) or the Microsoft Authent | PASS |
| `account-legitimate-requested` | account | legitimate | ears_up; matching your request; open myaccount | ears_up; Password reset matching your request; Do not use the alert link. Open myaccount.google.com yourself or the Gmail app → your prof | PASS |
| `account-ambiguous-breach` | account | ambiguous | ears_up; Claimed data breach; official app | ears_up; Claimed data breach notice; Open the service's official app, or type its address yourself. Never use a link or number  | PASS |
| `email-threat-bank` | email | threatening | barking; impersonating; official | barking; Email impersonating CommBank; Delete it. Don't reply or use any link or number in the email. Open CommBank's official ap | PASS |
| `email-legitimate-receipt` | email | legitimate | resting; Ordinary; Nothing | resting; Ordinary email; Nothing to do. Come back if it asks you to log in, pay or install anything. | PASS |
| `email-ambiguous-security` | email | ambiguous | ears_up; Security alert; official | ears_up; Security alert to verify; Do not reply or use details from the email. Don't reply or use any link or number in the e | PASS |
| `app-threat-remote` | app | threatening | barking; Remote; remove | barking; Remote access app during a suspicious call; End the session now: turn off Wi‑Fi and mobile data, hang up, then remove the app. Follow  | PASS |
| `app-legitimate-notes` | app | legitimate | ears_up; official store; Re-check | ears_up; App reported from the official store; No urgent action from this evidence alone. Re-check if its permissions change or it behave | PASS |
| `app-ambiguous-cleaner` | app | ambiguous | ears_up; notifications; turn it off | ears_up; Can read notifications; If Super Cleaner doesn't need notification access for what you use it for, turn it off in  | PASS |
| `file-threat-disguised` | file | threatening | barking; Executable; Delete it | barking; Disguised executable; Delete it unless you can independently verify the sender. Don't 'open with' anything. | PASS |
| `file-legitimate-document` | file | legitimate | ears_up; Limited file; Do not treat | ears_up; Limited file inspection; Do not treat this result as permission to open the file. Verify the sender; never enable m | PASS |
| `file-ambiguous-archive` | file | ambiguous | ears_up; Password; Don't extract | ears_up; Password-protected archive; Don't extract it unless you expected it. Never run anything inside it. | PASS |
| `device-threat-remote` | device | threatening | barking; Remote; End the session | barking; Remote access was granted; End the session, remove the remote-access app, then review the accounts used while they we | PASS |
| `device-legitimate-observed` | device | legitimate | resting; Apollo protection; operational | resting; Apollo protection is confirmed running; The device reported protection operational at 02:50 PM. | PASS |
| `device-ambiguous-limited` | device | ambiguous | growling; Protection; Restore | growling; Apollo protection stopped; Restore the permission or protection service, then return to Device Gate and re-check. | PASS |

## Realistic multi-Gate situations

| ID | Situation | Expected Gate path / meaning | Actual | Outcome |
|---|---|---|---|---|
| `multi-unexpected-purchase-message` | I received an unexpected purchase message. | {"gates": ["text", "link", "account"], "finding": "unexpected purchase pressure and off-domain account link", "uncertainty": "message does not prove a purchase occurred", "action": "open Pay | {"gates": ["text", "link", "account"], "text_state": "barking", "text_finding": "Bank fraud message", "link_level": "malicious", "action": "Don't enter your password or verification code. Open your bank's app y | PASS |
| `multi-google-drive-file` | Someone shared this file from Google Drive. | {"gates": ["file"], "finding": "disguised executable; cloud hosting is not proof of safety", "uncertainty": "sender and complete contents remain unknown", "action": "keep closed and verify s | {"gates": ["file"], "state": "barking", "finding": "Disguised executable", "evidence": "Its name suggests a PDF file. Its actual type is executable content. Documents never need to be executable. Being hosted o | PASS |
| `multi-caller-install-app` | A caller asked me to install an app. | {"gates": ["call", "app"], "follow_up_gate": "device only if the person says access was granted or the app was installed", "finding": "remote-access social engineering plus high-impact app c | {"gates": ["call", "app"], "call_state": "barking", "call_finding": "Remote access request", "app_state": "barking", "app_finding": "Remote access app during a suspicious call", "action": "Don't open it or read | PASS |
| `multi-unfamiliar-installed-app` | I found an unfamiliar app already on my phone. | {"gates": ["app", "device"], "finding": "unfamiliar app and observed high-impact access", "uncertainty": "permissions do not prove malicious behaviour", "action": "review access and remove i | {"gates": ["app", "device"], "app_state": "growling", "app_finding": "Powerful accessibility access", "device_state": "growling", "device_finding": "Accessibility access: Device Helper", "action": "Revoke acces | PASS |
| `multi-genuine-delivery-notification` | This is a genuine delivery notification. | {"gates": ["text", "link"], "finding": "delivery notification with configured official destination and no payment/login pressure", "uncertainty": "sender identity is not authenticated from t | {"gates": ["text", "link"], "text_state": "ears_up", "text_finding": "Delivery notification to verify", "link_level": "clean", "link_signals": [], "action": "Prefer the courier's official app or type its known  | PASS |

## Normal app journeys

| ID | Gate | Situation | Expected | Actual | Outcome |
|---|---|---|---|---|---|
| `ui-site-popup` | site | Ten-Gate overview and stopped-protection recommendation | All ten Gates visible; popup dismisses before the working Device Gate action | Ten Gates visible; Site card: Site Gate Unavailable on this device Automatic Automatic filtering for supported website traffic; this is separate from manual link checks. This devic | PASS |
| `ui-link-threat` | link | Threatening bank lookalike | Barking result; persistent trusted verification; truthful continue label | Threat state Apollo is barking; Apollo is growling at this link.; persistent verification instructions opened. Ambiguous shortened-link override label is truthful. | PASS |
| `ui-text-threat` | text | Verification-code request | Barking result and persistent sender-check instructions | TimeoutError: Locator.wait_for: Timeout 90000ms exceeded. Call log: - waiting for get_by_test_id("textguard-result") to be visible | FAIL |
| `ui-call-threat` | call | Caller requests a security code | Threatening call result and trusted callback guidance | State Barking; Do not share the code.; independently trusted callback guidance opened. | PASS |
| `ui-network-ambiguous` | network | Available preview network information | Unknown limitations remain visible; no unsupported block claim | State Resting; Connected via unknown. Nothing worrying.; limitation: WHAT APOLLO CAN SEE HERE This build sees only what the platform reports: connection type, Wi‑Fi name (with loca | PASS |
| `ui-account-unknown-report` | account | No alert evidence plus offline report | Unknown stays unknown; no false report success; Retry; Mark as handled | No-evidence path stayed unknown; offline report showed Retry; online retry succeeded; resolution label is Mark as handled. | PASS |
| `ui-email-threat` | email | Bank-impersonation email | Threat result and independently trusted verification instructions | TimeoutError: Locator.wait_for: Timeout 90000ms exceeded. Call log: - waiting for get_by_test_id("email-result") to be visible | FAIL |
| `ui-app-remote` | app | Remote-support app prompted by caller | Capability risk plus working persistent Settings guidance | TimeoutError: Locator.wait_for: Timeout 90000ms exceeded. Call log: - waiting for get_by_test_id("app-result") to be visible | FAIL |
| `ui-file-handoff` | file | Disguised executable and post-open follow-up | Evidence-first follow-up; recovery; automatic Higgins Retry and continuity | Risky file source follow-up occurred after inspection; 'I already opened it' recovery worked; Higgins Retry and simpler follow-up preserved one conversation. Exact final Higgins re | PASS |
| `ui-device-setting` | device | Observed protection health and setting follow-up | Visible limitation, working setting guidance and retained Higgins context | State Growling; 1 item worth reviewing. Nothing confirmed dangerous.; Settings guidance and follow-up stayed attached to Device Gate context. Exact final Higgins response: Higgins  | PASS |

## Device-only scenarios — not completed by browser evidence

- `site-native-confirmed-block` (site): Requires a real supported filter and device-recorded enforcement evidence.
- `call-native-screening-rejection` (call): Requires a real incoming call and supported call-screening role.
- `file-native-share-provider` (file): Requires Android/iOS share sheet, provider metadata and content URI access.
- `device-native-settings-return` (device): Requires real Settings deep links and refresh after returning to Apollo.
- `app-native-inventory-permissions` (app): Requires platform-exposed app inventory and permission observations.
- `network-native-enforcement` (network): Requires real network events; Stage 1D packet-blocking acceptance remains cancelled.

## Interpretation rule

A scenario passes only when the selected Gate is understandable, the detection preserves uncertainty, the investigation does not overclaim, Higgins provides a plain explanation, and the person can complete one labelled next action. Test count alone is not acceptance.
