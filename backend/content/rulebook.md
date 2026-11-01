# ApolloSG rule book

How a check moves through ApolloSG, the rules each part follows, when a check is settled, what sends it to the next step, and what information can be requested. Written from the code, word for word the same in the app (Settings → Rule book) and the admin portal.

_Last reviewed against the code: 2026-11-01._

_Revision 2, 27 October 2026: rules corrected after the Rule Book review (rule classes, Possible Threat, TC FlyBy weak signals and verified checks, Magnum DI triggers and provider calls, ABN, ACN and licence numbers), with the second-round corrections the same day (LINK-11, CORR-08, text copied elsewhere, Magnum DI correcting a provisional concern). Status: approved by the owner, then the code was audited against it and brought into line the same day: both engines decide from each rule's class, so ROUTE and COVERAGE rules no longer make a Possible Threat; CORR-08 needs a harmful payload; a failed lookup never supplies a rule's evidence; TC FlyBy treats weak signals as weak; Magnum DI can't go below TC FlyBy's concern without resolving evidence; and ABN, ACN and licence numbers reach only their register question. The EXPLAIN class was added for Higgins' explanation rules, and each one was checked against the code._

This is the only copy. Whenever a rule or process changes, this book is updated in the same change. An automatic check stops the change until it is.

**The path of every check**

Apollo detection (the gate) → *only if Possible Threat* → one investigation case → **Higgins Triage** → **TC FlyBy** (official sources → ApolloSG KB → one targeted Brave search, no AI) → settled, *or*, when unresolved evidence could materially change the outcome or the protective action → **Magnum DI** (at most 1 Magnum DI call per correlated case, no retry) → **Higgins** explains the result.

Each check creates exactly one entry in the Threats list. The phone's first detection and the later investigation update the same card.

The book has five parts: **Protection Gates** (each gate with all of its rules), **Investigation process**, **Privacy and data**, **Device protections** and **General**.

---

## Protection Gates {#protection-gates}

Every check starts at a gate. Each gate below lists every one of its rules, word for word from the gate catalogue.

### How the gates decide (Apollo detection) {#gate-decisions}

**Job:** detect and protect. Uses no AI.

**Process**
1. **First look on the phone.** Fixed rules give the check one of six states: Checking, Patrolling, Sniffing, Growling, Barking or Biting.
2. **Specialist lookups, gathered once.** These are Google Safe Browsing, Apollo's blocklist and the free threat lists (see ApolloSG's knowledge base), the domain registration record (RDAP), redirect expansion, IPQualityScore (links and phone numbers), direct-download detection, official scam advisories and breach data. TC FlyBy and Magnum DI reuse these results; they never repeat them.
3. **Gate rules.** A fixed catalogue of 155 rules covers links/QR, messages, calls, email/accounts, files, apps, device, network and correlated sequences. Each source type is checked only against its own rule groups. Every rule has one class (see Rule classes) and is listed under its gate below, grouped by class.
4. **Retries.** A temporary failure gets up to 3 attempts. This covers a provider not answering, a network failure, content that couldn't be opened, or a check error. Permanent limits are never retried. On the phone, link and number reputation lookups follow the same policy within a time budget, and identical lookups already running are shared, never sent twice. An authorisation failure or rejected input is not retried. If every attempt fails, the lookup is recorded as unavailable, with how it failed. It is never counted as a pass, and the attempts appear in the DI.
5. **Rules that can't run here.** A rule that needs something this context can never provide is **not applicable**, not a coverage gap. The DI still lists it, with the reason. Example: BITM-01 to BITM-04 need the page's live content and WebSocket traffic as a browser sees them, which ApolloSG can't observe from an app. A coverage gap means a check that should have run, but didn't.
6. **Limited by cause.** Every Triage outcome reports its cause codes (no content): reputation timeout, authorisation failure, lookup allowance used up, provider unavailable, genuine insufficient evidence, a moderate number-risk result, a rule execution error, and so on. Every number check reports its outcome, whether the number was allowed, risky or unknown. The admin Triage page counts them for real phones separately from previews and test devices, with the checks that didn't complete listed for every outcome.
7. **Checks that didn't complete.** A check Apollo needed but couldn't finish is recorded with how it failed: it timed out, there was no connection, the service couldn't be reached or had an error, the lookup allowance is used up, the lookup wasn't authorised, the service had no information, the website's address doesn't exist, and so on. This covers a reputation source that didn't answer, a link whose final destination couldn't be verified, and a phone number scored only from Apollo's last check. The wording follows the kind of check and how it failed, never the provider. It is never shown as a completed check.

**Rule classes**

Every rule has exactly one class. Only DETECT and CORRELATE rules are threat-producing, and "a rule is met" in the outcomes below always means a threat-producing rule. Every gate rule's class is recorded in the gate catalogue, and both engines (on the phone and on ApolloSG's server) decide the outcome from it.

| Class | What it does | Can it make a Possible Threat? |
|---|---|---|
| **DETECT** | Finds a threat in the item itself, from evidence this check holds: a request for a code or password, a disguised program, a lookalike domain with a login form, an authoritative malicious listing. | Yes, but only when every piece of evidence the rule requires is present (observed, or recorded by an authoritative source) and every corroboration it names is established. |
| **CORRELATE** | Connects the item with other recorded events into a known scam sequence, such as a suspicious call, then a remote-access app, then a permission change. | Yes, but only when every event it links is recorded and the relationship the rule names (the same sender, link, app or case, in the stated order) is established. Two events close together in time are never enough. |
| **ROUTE** | Hands part of the item to the gate whose rules judge it: the address in a QR code, a link in a message, email, file, calendar invitation or notification, an attachment, a captive-portal page. | Never by itself. A ROUTE rule is recorded as **Routed**, never as Met. The routed part is judged by its own gate's rules. When one of those threat-producing rules is met, that rule is the one recorded as met, and the original item's case cites it. |
| **COVERAGE** | Records what could and couldn't be examined: coverage gaps, rules that can't run here, checks that didn't complete, evidence levels, contents that couldn't be inspected. | Never. It can stop "No threat identified" and make a result Limited. It never creates or strengthens a threat, and never weakens real threat evidence. |
| **ENFORCE** | Acts on what is already established: Site Gate's blocking, the Call Gate's reject requests and "Suspected scam" labels, the person's own block and trust choices, and Biting. | Never. It decides no threat itself, and Biting still needs a real, fresh block on this device (see Rules below). |
| **EXPLAIN** | Presents or explains a result without changing it: the order Higgins answers in, the Plain-English Renderer, the Fidelity Check and the settling sentence. These are Higgins' rules, not gate rules, and each is listed under its own section in Investigation process. | Never. It changes how a result is presented, never what it means, and it never opens, raises or lowers a case. |

- Steps 4 to 7 above, the evidence levels and the coverage-gap codes are COVERAGE. Site Gate, the Call Gate's screening and labels, and the Biting rule are ENFORCE. Higgins' explanation rules (HIG, PER and FID), the Fidelity Check's failure codes and the settling rules are EXPLAIN.
- A weak or unknown qualifier in a rule's title ("unrated", "newly registered") never satisfies the rule on its own. The rule is met only when the strong evidence it also requires (a credential or payment lure, brand impersonation, a login or payment form) is present.
- A lookup that failed or didn't answer never supplies a rule's evidence. It is a coverage gap.

**Gate outcomes**
| Outcome | When |
|---|---|
| **Possible threat** | At least one threat-producing rule (DETECT or CORRELATE) is met, with every piece of evidence it requires present and every corroboration it names established. A ROUTE, COVERAGE or ENFORCE rule never makes a Possible Threat on its own. This opens **one** investigation case. |
| **Limited / unable to determine** | No threat-producing rule was met, but evidence was missing (a coverage gap), or concerning signs didn't meet a rule. No case is opened, and the person is told what Apollo couldn't see, in plain English, and to treat the item with caution. A Limited result is never shown as safe or as nothing to worry about. |
| **No threat found by available checks** | No threat-producing rule was met and no coverage gap stands, but a check Apollo needed didn't complete. The result names each check that didn't complete and how it failed. It is never shown as the unqualified "No threat identified". |
| **No threat identified** | No threat-producing rule was met and every applicable check completed. |

**Rules**
- Missing evidence is a coverage gap. It can block "no threat", but it never creates a threat and never weakens real threat evidence.
- A check that didn't complete is a coverage gap only when its answer could change the result. When no reputation source answered at all, the result is Limited. When one source didn't answer but another did, or a link's final destination couldn't be verified, or a number's reputation lookup failed while nothing in the material depends on it, the result is "No threat found by available checks".
- **Never a threat on their own:** unknown sender or caller, urgency, a brand mention, PayID/Osko use, link shorteners, a new domain, risky TLDs, public Wi-Fi, developer options, official-store apps, encryption alone, and similar weak signals.
- **Cache:** a possible threat is kept 30 days and no threat 7 days. Limited results, and results with a check that didn't complete, are never cached.
- **Biting only for a real block.** The DNS, VPN or packet filter must have actually blocked the connection. The block must be fresh (within 60 seconds), on this device, for this event, and on a real platform (not mock). Calls can never reach Biting. Link, email and text checks go no higher than Barking.
- **Unknown is not unsafe.** A setting Apollo couldn't read is never counted as a change. "No concern" covers only the checks that completed. Nothing is ever called safe.
- **Privacy first.** Passwords and codes are removed on the phone, and an image showing one is not sent. Only allow-listed fields leave the device. Secrets are stripped again before every AI request. The full rules are under Privacy and redaction.
- **Protection changes** say only what changed, never who changed it or why. The "what to do" lines are fixed text.

**What sends a check onward:** a Possible Threat result. A check the person starts (Check It, or Ask Higgins with something to check) enters the same investigation pipeline.

### Site Gate {#site-gate}

**Job:** stop known dangerous websites before they load.

**Site Gate (Android)**
- An on-device filter, run through Android's private VPN, blocks known dangerous websites before they load. Browsing is checked on the phone and never sent anywhere.
- A blocked website reaches Biting only when the filter actually blocked the connection.

**Site Gate (iPhone)**
- ApolloSG's Safari content blocker blocks verified threat websites once the person turns it on under Settings › Safari › Extensions.
- It covers websites opened in Safari, and Safari views inside other apps. Not covered: Chrome, Firefox and other browsers, in-app browsers that don't use Safari, and non-browser apps.

The Site Gate has no catalogue rules of its own. Its blocking is ENFORCE: it blocks only websites already verified as dangerous and decides no threat itself; a link the person checks is judged by the Link Gate rules.

**Evidence received:** a website Site Gate stopped is classified "Connection seen by Site Gate": the connection attempt is ApolloSG's own observation (Verified by ApolloSG), and the block is Verified when the operating system confirmed the drop, or Recorded when it reported a stopped flow. "It saw where the connection was going, not the page itself" — the full link, redirects, certificate and hosting are Couldn't be verified. A re-check from the case can raise it to "Destination followed".

### Link Gate {#link-gate}

**Job:** check a link before it is opened.

**How a link is checked**
- The link is checked exactly as given: Apollo's blocklist, Google Safe Browsing and the free threat lists (PhishTank, OpenPhish, Spamhaus DROP, ASIC's investor alert list and ACMA's blocked gambling websites), then up to 5 redirects followed to the final address. When the final destination can't be verified (more than 5 redirects, an address that doesn't exist, a website that can't be reached, a timeout), the link is judged as given and the final-destination check is recorded as not completed, with how it failed.
- The domain's registration record (RDAP) is fetched alongside it. It adds detail but never decides the result.
- Every link Apollo checks, in a message, an email or on its own, gets the same check.
- **QR codes:** the address inside is checked as a link. QR-01 is a ROUTE rule: it hands the address to the Link Gate rules and never makes a Possible Threat by itself. A QR check is a Possible Threat only when a threat-producing rule is met for the address (QR-02, QR-03 or any other Link Gate rule). The QR code itself is never a threat.
- A link the person checks themselves opens an investigation, which TC FlyBy and Magnum DI pick up as usual.
- **Trusted links:** trust covers only the exact link the person chose. Removing it ends the trust.
- **Never a threat on their own:** an http link, a bare IP address, punycode, an unusual port, a risky TLD, a link shortener, a long link, deep subdomains, encoded characters, a newly registered domain, a QR code itself, and data or blob links.
- **Several weak URL-risk indicators** that intelligence can't resolve are recorded by LINK-11, a COVERAGE rule. They can make the result Limited, never a Possible Threat. When the link also carries independent strong threat evidence (a brand lookalike with a login or payment form, a credential lure with a deceptive destination, a displayed link that differs from where it really goes, an authoritative malicious listing), that evidence meets its own DETECT rule, and that rule is the one recorded as met.

**Link evidence levels** (Higgins Triage classifies every link check, on the phone)
- **Link as given:** none of ApolloSG's lookups answered. "ApolloSG only had the link itself — none of its lookups answered, so nothing about the site could be verified." Every lookup row is Couldn't be verified, with how it failed.
- **Link checked:** the lookups answered but the link couldn't be followed to where it finally leads (the final-destination check didn't complete).
- **Destination followed:** followed by ApolloSG's server (never opened on the phone) to its final destination and checked there.
- **What could be examined:** Original URL (observed) · Redirect chain and Final destination (observed when followed) · Domain registration (recorded by the domain's registry, not verified by ApolloSG) · Reputation (recorded by the lists that answered: "Listed as … by N of M lists" or "No known threat listing found on the N lists that answered"; no known threat listing is never proof a site is safe) · TLS certificate and Hosting and DNS (ApolloSG doesn't inspect these).
- **Investigation signals — not proof of fraud:** the address's own structure as the on-device analyser reads it (bare IP, hidden username, punycode, http, unusual port, risky TLD, shortener — dropped once followed —, deep subdomains, many hyphens, encoded characters, brand lookalike, brand in the path, credential lure), a redirect to a different site, a newly registered domain, and a destination that couldn't be followed.
- **Where it came from** is recorded: Link you entered · Shared from another app · QR code · Link from a message or email · Re-check from the case.
- **Re-check from the case:** the same link is re-triaged in that case. The case keeps its first detection time and every earlier level and Triage result; a move to a stronger level shows "Evidence upgraded from … to …". A re-check that got less far than the earlier check never replaces it: "The re-check couldn't get as far as the earlier check (…), so this case keeps its earlier result." A case that already has an investigation keeps it; one without starts Magnum DI only if the re-check is a Possible Threat.

**Link Gate rules (21)**

**DETECT** (18)
- **LINK-01** · Authoritative reputation reports the destination as malicious
- **LINK-02** · An observed redirect destination is confirmed malicious
- **LINK-03** · Local URL engine reaches malicious through deception-gated rules
- **LINK-04** · Known deterministic threat indicator match
- **LINK-05** · Brand-lookalike domain with credential, login, payment or account interaction
- **LINK-06** · Credentials embedded in the URL
- **LINK-07** · Credential lure with an unrelated or deceptive destination
- **LINK-08** · Displayed link materially differs from the actual destination
- **LINK-09** · Brand presented in the link or path while the destination is unrelated, with a sensitive action
- **LINK-10** · Newly registered domain with a credential, payment, security-code or identity form
- **QR-02** · QR destination with brand or domain deception
- **QR-03** · QR destination with a credential or payment lure and a suspicious, unrated or newly registered destination
- **DATA-01** · data: or blob: content collecting credentials in a deceptive brand context
- **BITM-01** · Sensitive credential interaction with observable real-time relay and an inconsistent destination
- **BITM-02** · Brand authentication presented through an unauthorised origin with relay or strong deception
- **BITM-03** · Message, email, QR or call leads to a site presenting another brand's authentication with relay behaviour
- **BITM-04** · MFA or security-code interaction on an unrelated authentication origin with observable relay evidence
- **BITM-05** · Destination matches authoritative intelligence for active BitM/AiTM phishing infrastructure

**CORRELATE** (1)
- **LINK-12** · Suspicious URL evidence correlates with another suspicious event

**ROUTE** (1)
- **QR-01** · QR code contains a URL — the destination is triaged as a link

**COVERAGE** (1)
- **LINK-11** · Multiple URL-risk indicators reach the suspicious threshold and intelligence cannot resolve them

### Text Gate {#text-gate}

**Job:** check messages for scams.
- **Android:** optional, through notification access. Apollo reads each new text-message notification from the phone's default messaging app as it arrives, never the message inbox or history. Notifications from other apps, such as WhatsApp, Telegram and Messenger, are not read.
- Store builds of ApolloSG never ask to read text messages or the call log.
- **iPhone:** Apple gives apps no way to read Messages. The person can paste a message, use a screenshot, or share it to ApolloSG where the app offers Share.
- Every message goes through the same checks as a pasted one: the Text Gate rules below, plus the Link Gate check for each link (MSG-12 is the ROUTE rule that hands each link over).
- **Numbers in a message** get a reputation lookup. A lookup that fails is recorded as a check that didn't complete. On its own it never makes an ordinary message Limited: only a callback lure (a supplied number with a claimed charge or a claimed organisation) depends on that number's reputation.
- **Callback scams:** a supplied number (including 1800, 1300 and 13 numbers written without a leading 0) with call or contact wording, together with an unexpected charge or payment, meets CB-01. An unexpected charge is an explicit "unauthorised charge", "unrecognised transaction" or "suspicious transaction", or a claim that the person was charged, debited or billed (or a payment of a dollar amount) with dispute wording ("if this wasn't you") or urgency.
- **Look-alike characters:** characters that look like ordinary letters but aren't — typographic ligatures such as "ﬁ", full-width or mathematical letters, Greek or Cyrillic letters inside an English word, and invisible joiners inside a word. When the name of the organisation the message introduces itself as ("It's UNIﬁed Energy here", "This is Sam from …", "calling from …"; only a name with an organisation word, never a person's name) or a known brand's name is written with one, MSG-23 is met on its own. Brand names are matched with look-alike characters read as the letters they imitate; the name is always kept exactly as the message wrote it.
- **Rebate pressure:** a claimed government rebate or subsidy (for example "Government STCs", "battery rebates", or STCs offered as savings), with a deadline on the offer ("before rebates drop next week", "rebates are dropping", "before year-end") and a request to reply ("Reply YES"; a "reply STOP" opt-out is never one) or call a supplied number, meets MSG-24. A deadline on an offer also counts as urgency.
- **Never a threat on their own:** an unknown sender, urgency, an ordinary payment discussion, PayID/Osko use, a brand mention, a job, investment or romance discussion without scam mechanics, a sign-in or verification request without supporting context, a code delivered for the reader to use, and advice never to share a password or code.
- **Message evidence levels** (Higgins Triage, on the phone): Pasted text and Screenshot (who sent it and when couldn't be verified) · Shared from an app · Read from your messages (the number or name it arrived from and when, as the phone stored them) · Captured from the notification. Who really sent a message is never verified — messaging apps don't share it — unless a provider shared its own rating, which is recorded as that provider's rating. Links and numbers are recorded as checked, partly checked ("1 of 2 links couldn't be checked") or not checked; pictures or files sent with a message never reach ApolloSG. Signals (not proof): moving to another app or number, a "new number", a callback number, links or numbers that couldn't be checked. A re-check from the case keeps the case's level and history.

**Text Gate rules (32)**

**DETECT** (31)
- **MSG-01** · OTP, MFA or security code requested
- **MSG-02** · Password, PIN or login credential requested
- **MSG-03** · Banking or card credentials requested
- **MSG-04** · Transfer to a safe or protected account requested
- **MSG-05** · Gift-card payment requested
- **MSG-06** · Remote access or screen sharing requested in a suspicious context
- **MSG-07** · App or software installation requested in a suspicious context
- **MSG-08** · Government or authority impersonation with payment, credential, code or threat
- **MSG-09** · Extortion
- **MSG-10** · Advance-fee mechanics
- **MSG-11** · Fake-payment mechanics
- **MSG-13** · Family or new-number impersonation with a money, credential or code request
- **MSG-14** · Brand impersonation with a consequential action and inconsistent contact or destination
- **MSG-15** · Guaranteed-return or investment approach with payment or crypto transfer
- **MSG-16** · Job offer with advance payment, crypto, gift cards or credential harvesting
- **MSG-17** · Romance interaction with a suspicious financial request
- **MSG-18** · Sensitive identity request with impersonation or anomaly
- **MSG-19** · Platform switching combined with another scam mechanic
- **MSG-20** · Urgency or threat with a consequential action and a supporting anomaly
- **MSG-21** · Claimed or uncertain identity with a consequential action and another deterministic anomaly
- **MSG-22** · Multiple moderate scam indicators form a coherent scam pattern
- **PAY-01** · Instant-payment request with authority, family or business impersonation
- **PAY-02** · Instant-payment request with urgency or threat and a sender anomaly
- **PAY-03** · Unexpected change of payment destination with an immediate-payment request
- **FWD-01** · Instruction to enter a forwarding service code in a suspicious account or authority context
- **FWD-02** · Instruction designed to redirect calls, messages or security codes to another number
- **CB-01** · Claimed charge or account problem with a supplied callback number inconsistent with the claimed organisation
- **CB-02** · Urgent cancellation, refund or security lure with a suspicious callback number
- **CB-03** · Callback number has no known threat listing but strong impersonation evidence remains
- **MSG-23** · Name of the organisation the message claims to be is written with look-alike characters
- **MSG-24** · Government rebate or subsidy claim with deadline pressure and a request to reply or call

**ROUTE** (1)
- **MSG-12** · Malicious or deceptive link in the message

### Call Gate {#call-gate}

**Job:** screen incoming calls from risky numbers.

**Call evidence levels** (Higgins Triage, on the phone): Described by you (only what the person said; the number isn't looked up) · Number only (the reputation lookup didn't answer) · Number checked (recorded by the number-reputation service, not verified by ApolloSG) · Call screened by ApolloSG (its call screening saw the call arrive — time and screening Verified by ApolloSG). Caller ID is never shown as verified: the number shown can be faked and ApolloSG can't yet read the network's caller verification. Signals (not proof): an internet (VOIP) number, recent abuse reports, an invalid number, a carrier warning the person reported, a caller asking for remote access, an app, a code, password or card details, and a claimed organisation. A number's case keeps every level it has had: a screened call stays the case's level when a later re-check only gets the number checked.

**Call Gate (Android)**
- Works only when the person makes ApolloSG the phone's caller ID & spam app. Android then hands ApolloSG each incoming call before it rings, usually only from numbers that aren't in the person's contacts.
- Apollo never listens to a call and never reads the call log. It sees only the one incoming number.
- It compares that number with three lists kept on the phone: numbers the person blocked, numbers they allowed, and numbers this phone looked up earlier and found high-risk.
- An allowed number always rings. For a blocked or high-risk number, ApolloSG asks Android to reject the call. Android gives no receipt, so this is recorded as a request, never as a confirmed block. Calls never reach Biting. This screening is ENFORCE: it acts only on the person's own lists and on high-risk lookups this phone already recorded, and decides no threat itself.
- Every other call rings normally. ApolloSG never delays or silences a call on a guess, and if screening fails the call rings.
- A number with no local signal is queued (up to 20) and looked up the next time ApolloSG is open. Android allows only a few seconds to answer, which is too short for the lookup.
- A number's risk score is a likelihood, never proof. On its own it can only raise a warning.
- **Number reputation lookups:** a current saved score (24 hours) is used before a new lookup is paid for, for automatic and requested checks alike. If the live lookup fails, Apollo uses the number's last known score, says it is the result of its last check, and records the live lookup as not completed with how it failed. With no earlier score the number is unknown, never allowed.
- **Calls Apollo screened:** the last 50 calls, for up to 30 days, kept on the phone only.
- **Repeat Caller Alert:** a call from a number on the person's block list, or from a number this phone found high-risk or worth checking in the last 30 days, raises an alert. It is raised only after Android already has its screening answer, so it never delays or changes that answer. On a locked screen it says only that a repeat caller rang, without the number. When ApolloSG's notifications are off, the call's history says the alert wasn't shown. A later clean result clears a worth-checking finding, never a high-risk one.

**Call Gate (iPhone)**
- Apple lets no app screen calls as they arrive. When the person turns ApolloSG on under Settings › Phone › Call Blocking & Identification, iPhone blocks numbers on their block list, and numbers this phone looked up earlier and found high-risk still ring, with the label “Suspected scam”. Allowed numbers are never blocked or labelled. iPhone gives no per-call receipt, so nothing here is recorded as a confirmed block.

**Never a threat on their own:** an unknown caller, a number that isn't in contacts, and a number's reputation without matching behaviour.

**Call Gate rules (16)**

**DETECT** (15)
- **CALL-01** · OTP or security code requested
- **CALL-02** · Password or PIN requested
- **CALL-03** · Banking or card credentials requested
- **CALL-04** · Safe-account transfer requested
- **CALL-05** · Gift-card payment requested
- **CALL-06** · Suspicious cryptocurrency transfer requested
- **CALL-07** · Remote access or screen sharing requested
- **CALL-08** · Software or app installation requested
- **CALL-09** · Call or SMS forwarding instruction
- **CALL-10** · Government or authority payment threat
- **CALL-11** · Unsolicited technical support seeking device access
- **CALL-12** · Suspicious investment solicitation with a consequential financial action
- **CALL-13** · Claimed authority with a sensitive action and suspicious behaviour
- **CALL-14** · Unexpected refund or payment manipulation
- **CALL-15** · Reputation evidence with matching scam behaviour

**CORRELATE** (1)
- **CALL-16** · Call followed by a remote-access app, permission or device change forms a coherent sequence

### Email Gate {#email-gate}

**Job:** check emails for scams and phishing.

**Gmail**
- Read-only access only. ApolloSG never sends, deletes, labels or changes anything in the mailbox, and never sees or stores the mailbox password.
- The person connects through Google's own sign-in, and the sign-in link expires after 10 minutes. More than one account can be connected.
- The connection, an encrypted token, is kept until the person disconnects. Disconnecting also cancels it with Google.
- **Monitoring:** every 15 minutes, Apollo reads the next 15 messages of each connected account and gives each one the same checks as a pasted email.
- Message content is used for that check only and never written to ApolloSG's database. A receipt for each message, with no content, stops it from being checked twice.
- An attachment is checked by its fingerprint when the file-reputation service is connected; the attachment itself isn't uploaded.
- **Never a threat on their own:** a calendar invitation, a form-builder domain, valid sender checks (SPF, DKIM and DMARC) from a form provider, an address appearing in a breach, different sender and link domains, a brand mentioned in the email, a sign-in, verification or payment-update request without supporting context, a code delivered for the reader to use, a security notification, and advice never to share a password or code.
- **Triage reads the whole email:** its subject, sender, Reply-To, text, the authentication results the receiving mail server recorded (credited to that server), and each link as shown and where it really goes. Apollo's own wording about an email is never evidence of it: every rule reads the email itself.
- **Who the email speaks as** is its From name, or how its text introduces or signs itself. A brand it only mentions is not its claimed sender, so it can't be impersonation of that brand.
- **Missing headers are a check that couldn't run,** never a threat and never a gap that holds the result: without the Reply-To or the recorded SPF, DKIM and DMARC, EMAIL-08 and EMAIL-11 are not applicable and sender authentication is recorded as not completed.

**Email evidence levels** (Higgins Triage classifies every email check, on the phone)
- **L1 — Visual/Text:** a screenshot or pasted text. "ApolloSG only received a screenshot or pasted text, so technical sender authentication could not be independently verified."
- **L2 — Shared Email:** shared from another app without its full headers (also an "original" with no delivery headers). A connected-mailbox email that came back without them is the same level, shown as **L2 — Mailbox Email**: retrieved from the connected mailbox, without its full headers.
- **L3 — Original Message:** the original email with its full headers — an .eml file (chosen on the Check email screen, added later, or shared into ApolloSG) or the original source pasted ("Show original"). "ApolloSG examined the original email and full headers."
- **L4 — Provider-Verified Source:** the original retrieved by ApolloSG itself through the connected email account.
- **Read on the phone:** the original is parsed on the phone — headers, encoded subject, MIME parts, attachments (fingerprinted with SHA-256) and links. It is kept unaltered with its case on the phone and is never uploaded, not even to read its headers.
- **Sender authentication is reported as recorded, never re-checked:** SPF, DKIM, DMARC and ARC come from the topmost Authentication-Results header and are credited to the server that wrote it ("Recorded by mx.google.com, the mail server that received this email"). A server ApolloSG can't match to the delivering servers is said so. Status words: Verified by ApolloSG · Recorded by the source, not verified by ApolloSG · Observed, not verified · Couldn't be verified.
- **Below L3, authentication is never presented as checked:** the check says it needs the original email with its full headers, and the authentication rules (EMAIL-11, EMAIL-12) are not applicable: "Not applicable here: SPF, DKIM and DMARC results are only in the original email's full headers, which ApolloSG didn't receive."
- **Investigation signals — not proof of fraud:** Reply-To or Return-Path on another domain, SPF/DKIM/DMARC recorded as failed, a passing DKIM signature from another domain, no results recorded, results from an unmatched server, an address shown in the display name, a Message-ID from another domain. "Passing SPF, DKIM or DMARC confirms only which domain sent the email. It never makes an email safe."
- **Upgrading the evidence:** on the result or the Threat case, "Add the original email (.eml)" is offered below L3. The same email is re-checked by Higgins Triage in its existing case: the stronger level becomes current, every earlier level and Triage result is kept, and the timeline shows "Evidence upgraded to …". An original that isn't the same email (subject, sender address or opening text) never changes that case: "That original doesn't match the email you checked, so ApolloSG checked it as a separate email."
- **What travels with an investigation:** only Higgins Triage's findings — level, each capability's status, the recorded results and who recorded them, domains, counts, attachment types/sizes/fingerprints, signal names and the original's fingerprint. A case still under investigation receives better evidence the same way; a finished investigation keeps it on the phone only.

**Email-sending services.** A link through a recognised email-sending service's click tracking (Mailchimp, SendGrid, HubSpot and the like) says only who delivered the email. On its own it is never a sender/link mismatch, never makes an email a Possible Threat and never sends it to Magnum DI; where Apollo followed the redirect, the destination is judged instead. It is never proof the email is genuine either: every other rule still applies.

**Email Gate rules (19)**

**DETECT** (16)
- **EMAIL-01** · Claimed brand with sender-domain mismatch and a consequential action
- **EMAIL-02** · Freemail or unrelated domain impersonates a brand with a sensitive request
- **EMAIL-03** · Account or security alert with an off-domain, lookalike or deceptive link
- **EMAIL-04** · Credential request
- **EMAIL-05** · OTP or security-code request
- **EMAIL-06** · Invoice or payment request with changed bank details
- **EMAIL-07** · Executive or BEC impersonation with an unusual financial request and sender anomaly
- **EMAIL-08** · Material From/Reply-To mismatch with a consequential action
- **EMAIL-11** · Authentication failure with a consequential request or anomaly
- **EMAIL-12** · Authenticated legitimate sender with changed payment details, malicious link, unusual credential request or dangerous attachment
- **EMAIL-13** · Multiple moderate email anomalies form a coherent scam pattern
- **CAL-02** · Calendar invitation with a suspicious financial or account lure and a callback number
- **CAL-03** · Calendar invitation with a credential or payment collection destination
- **FORM-01** · Legitimate form service requesting a password, MFA or security code
- **FORM-02** · Legitimate form host collecting banking or card credentials in a suspicious originating context
- **FORM-03** · Legitimate form host collecting sensitive identity with impersonation or account-security lure

**ROUTE** (3)
- **EMAIL-09** · An embedded link produces a link-triage Possible Threat
- **EMAIL-10** · An attachment produces a file-triage Possible Threat
- **CAL-01** · External or unverified calendar invitation with a malicious or deceptive link

### Account Gate {#account-gate}

**Job:** watch the person's email addresses for breaches, and check pasted account alerts.

**Account checks**
- The email addresses the person watches stay on the phone.
- Each scan sends an address once to the breach service, Have I Been Pwned when it is connected and XposedOrNot otherwise, and the address isn't stored or logged.
- ApolloSG never asks for a password. Anything in a pasted account alert that looks like one is removed before it is checked.
- Links in a pasted account alert are compared with the organisation's official websites.
- "No breach found" is never called proof that the account is safe.

**Account Gate rules (1)**

**DETECT** (1)
- **BREACH-01** · Confirmed exposed credential evidence alongside current credential-harvesting or takeover activity

### File Gate {#file-gate}

**Job:** check a file before it is opened.

- **Trust the file, not its name.** The phone compares the file's real type with its name, and looks for double extensions, right-to-left name tricks, archives, app packages, profiles, certificates and links inside.
- Files can be up to 10 MB. The phone reads the start of the file and a text sample, and the whole file to fingerprint it (SHA-256); nothing is uploaded for this first look.
- **File evidence levels:** File name only (a name is only a claim) · Contents read (true type from its first bytes) · Contents read and fingerprinted (SHA-256 of the whole file, on the phone). The declared type is recorded as a claim; metadata, signatures and certificates, malware-list matches and macros inside documents are not inspected (a macro-enabled format is observed from its type). Signals (not proof): a name that says one type while the file is a program, script, installer, profile or certificate; a hidden second extension; hidden right-to-left characters; programs, installers, macro formats, an archive password sent with it, links inside.
- Links inside a file are checked as links. FILE-10 and FQR-01 are ROUTE rules: a link or QR code found in a file or image is judged by the Link Gate rules, and never makes a Possible Threat by itself.
- **Contents that can't be inspected** (an encrypted archive without its password) are recorded as a coverage gap (ARCH-03, COVERAGE), never as a threat. A suspicious sender or lure that came with the archive is judged by the Text Gate or Email Gate rules, and a dangerous payload found once the archive can be opened by ARCH-01 or ARCH-02.
- If the file is sent for an investigation, the server decides its type from its own bytes, not its name, and records any mismatch.
- ApolloSG only ever cleans up the copy its own picker made. A shared original is never touched.
- **Never a threat on their own:** encryption or password protection, ordinary file characteristics, and a QR code itself.
- ApolloSG never calls a file 100% safe, and unknown never means malicious.

**File Gate rules (19)**

**DETECT** (15)
- **FILE-01** · Executable or script disguised as a document or image
- **FILE-02** · Dangerous double extension
- **FILE-03** · Right-to-left filename deception
- **FILE-04** · Unexpected executable or script
- **FILE-05** · Suspicious APK
- **FILE-06** · APK impersonates a brand or update
- **FILE-07** · Unexpected configuration profile
- **FILE-08** · Unexpected trust certificate
- **FILE-09** · Macro-enabled document with suspicious provenance
- **FILE-11** · Dangerous PDF JavaScript, launch or embedded content
- **FILE-12** · Dangerous Office macro, external template or embedded object
- **FILE-13** · Archive contains an executable, script or dangerous nested content
- **FILE-14** · Archive contains path traversal or deceptive filenames
- **FILE-15** · Actual type materially contradicts the claimed type
- **ARCH-01** · Password-protected archive with the password supplied in the originating message and a dangerous payload

**CORRELATE** (1)
- **ARCH-02** · Password supplied separately but correlated to the same case with a dangerous payload

**ROUTE** (2)
- **FILE-10** · Embedded malicious or deceptive URL
- **FQR-01** · QR code detected in a file or image — destination is triaged as a link

**COVERAGE** (1)
- **ARCH-03** · Password-protected archive with a suspicious sender or lure and contents that cannot be inspected

### App Gate {#app-gate}

**Job:** check what an app can do and where it came from.

- Apollo doesn't judge an app by its name. It looks at what the app is allowed to do, where it came from and what happened around the install.
- It works from what the person tells ApolloSG plus what the phone's security checks can see, and never pretends to read other apps.
- Up to 10 web addresses the app uses are checked against the same reputation sources as a link.
- A remote-access app matters when it follows a suspicious call, message or website.
- **Never a threat on their own:** an app from an official store, permissions the app is expected to need, and installing a web app.
- **App evidence levels:** Described by you (name, developer, source and permissions as entered) · Read from this device (package, installer and requested/granted permissions as the phone's system records them). Signing information, the app's version and the store's or phone's own security checks aren't available to ApolloSG and are never claimed. Signals (not proof): installed outside an official store, screen access or control, accessibility, drawing over other apps, reading notifications, a brand in its name, destinations with a malicious reputation.
- **Images** (Show ApolloSG a picture): one level, "Image" — a picture shows what was on screen, not where it came from. Its text is read on the phone; its metadata is removed on the phone before anything is sent and never used as evidence; links, numbers and codes found in it are checked. Signals: sensitive details blacked out before sending, flagged identifiers.

**App Gate rules (14)**

**DETECT** (10)
- **APP-03** · Sideloaded app impersonates a known brand
- **APP-04** · Sideloaded app impersonates update, security or system software
- **APP-05** · App communicates with a confirmed malicious destination
- **APP-06** · Unexpected accessibility access with suspicious provenance or Threat Scent
- **APP-07** · Unexpected device-admin with suspicious provenance or Threat Scent
- **APP-08** · Unexpected screen sharing with suspicious provenance or Threat Scent
- **APP-09** · Unexpected install-app capability with suspicious provenance or Threat Scent
- **APP-10** · Multiple high-impact permissions with suspicious installation provenance
- **PWA-01** · PWA installation originates from a deceptive or known-malicious site
- **PWA-02** · Newly registered or unrated PWA origin with brand impersonation and login, payment or account interaction

**CORRELATE** (4)
- **APP-01** · Remote-access app or activity follows a suspicious call, message or site
- **APP-02** · Sideload follows a suspicious link or message
- **APP-11** · Install, then sensitive permission change, then suspicious network activity forms a coherent sequence
- **PWA-03** · PWA installation immediately follows a correlated scam message, email or link

### Device Gate {#device-gate}

**Job:** show what this phone's settings and protections reveal.

**Device check**
- ApolloSG shows only what this phone and this version of ApolloSG can truly see, plus what the person reports. It is never a full scan. Anything it can't see is shown as not visible, never as safe.

| Result | Meaning |
|---|---|
| Protected | No meaningful issues detected within what Apollo can see here. |
| Review recommended | Some permissions or settings deserve attention. |
| Action required | A high-risk configuration or app was detected. |
| Recovery | Risky access was already granted. Follow the steps — ApolloSG stays with you. |

- **Security & Privacy Review:** the same 9 areas on every kind of device. Each setting gets one of: Checked, Review recommended, Action required, Manual review required, Unavailable or Not applicable. The review is never one blanket "Protected".
- **Protection changes** say only what changed, never who changed it or why. A setting Apollo couldn't read is never counted as a change, and Apollo's own protection VPN is recognised as Apollo's.
- **Never a threat on their own:** expected management or device administration, expected accessibility access, ApolloSG or a trusted VPN, developer options, a custom DNS or DoH provider, notification permission, and signals the platform can't provide.

**Device Gate rules (15)**

**DETECT** (4)
- **DEV-01** · Trusted OS security facility reports malware or a threat
- **DNS-02** · DNS server matches authoritative malicious infrastructure
- **PUSH-01** · Browser notification from a deceptive origin with a fake security or financial warning and an action lure
- **PUSH-02** · Notification impersonates ApolloSG, the OS, a bank or a known service with an inconsistent destination

**CORRELATE** (10)
- **DEV-02** · Remote-access activation correlates with suspicious activity
- **DEV-03** · Unexpected management or profile change with suspicious activity
- **DEV-04** · Unexpected trusted certificate with suspicious activity
- **DEV-05** · New app with unexpected accessibility and relevant Threat Scent
- **DEV-06** · New app with unexpected device-admin and relevant Threat Scent
- **DEV-07** · Suspicious VPN installation or change with suspicious app or scam activity
- **DEV-08** · Multiple device-security changes form a coherent high-risk sequence
- **DEV-09** · System-integrity indicators with supporting compromise evidence
- **DNS-01** · DNS, Private DNS or DoH configuration unexpectedly changed with correlated suspicious activity
- **DNS-03** · DNS change with a preceding suspicious app installation or permission event

**ROUTE** (1)
- **PUSH-03** · Web-push notification leads to a malicious or deceptive URL

### Internet Gate {#internet-gate}

**Job:** check the connection the phone is using.

**Check this network**
- ApolloSG uses only what the phone reports: connection type, Wi-Fi security, a sign-in page (captive portal) and VPN status. The person adds where they are (home, work or school, a public place, or not sure), the network name they expect, and whether they turned the VPN on.
- Public isn't malicious, open isn't intercepted, and a VPN the person chose is fine.
- **Never a threat on their own:** public Wi-Fi, open or WEP Wi-Fi, an unknown Wi-Fi network, a lookalike network name, a captive portal, a trusted home or work connection, and a mobile data connection.

**Internet Gate rules (9)**

**DETECT** (4)
- **NET-01** · Confirmed malicious destination observed
- **TLS-01** · HTTPS certificate validation fails unexpectedly during a sensitive interaction in a suspicious network context
- **TLS-02** · Unexpected self-signed or untrusted certificate presented for a legitimate sensitive service
- **TLS-03** · Certificate identity does not match the requested legitimate domain

**CORRELATE** (4)
- **NET-03** · Unexpected VPN change with suspicious app or device activity
- **NET-04** · Network behaviour correlates with an existing suspicious incident
- **NET-05** · App, site or device sequence communicates with malicious infrastructure
- **TLS-04** · Newly introduced trusted root certificate with correlated suspicious network behaviour

**ROUTE** (1)
- **NET-02** · Captive-portal destination triggers a link Possible Threat

### Linked events across gates {#linked-events}

**Job:** connect events from different gates that together form a known scam sequence, such as a suspicious call, then a remote-access app, then a permission change.
- **Never a threat on its own:** two events happening close together in time.
- **CORR-08 needs payload evidence.** It is met only when the archive's contents show a harmful or suspicious payload: a program, script, installer, app package, profile or certificate, a macro-enabled document, a disguised file, or other dangerous nested content (as FILE-13, FILE-14, ARCH-01 and ARCH-02 describe). A password-protected archive arriving with its password, whose contents couldn't be inspected or showed nothing harmful, is recorded as COVERAGE (as ARCH-03 is), never a Possible Threat.

**Linked-event rules (9)**

**CORRELATE** (9)
- **CORR-01** · Suspicious call requesting remote access, then remote-access install, then accessibility or screen-sharing permission
- **CORR-02** · Message, then deceptive link, then APK or PWA installation
- **CORR-03** · Email, then changed bank details, then instant-payment request
- **CORR-04** · Email or QR, then deceptive authentication site, then BitM/AiTM indicators
- **CORR-05** · Callback lure followed by a suspicious call with matching claimed identity
- **CORR-06** · Suspicious app installation followed by a DNS, VPN or accessibility change
- **CORR-07** · Website or download, then executable, then malicious destination
- **CORR-08** · Password-protected archive with the password supplied in the originating message or email
- **CORR-09** · Scam site, then notification permission, then a later deceptive web-push lure

---

## Investigation process {#investigation-process}

### Higgins Triage (inside the case) {#higgins-triage}

**Job:** gets everything ready. It does not investigate and never decides whether something is a scam. It works offline, uses no AI and costs nothing.

**Process**
1. **Reads every input:** the submitted text and links, the text the phone read from screenshots and images, and the text layer of documents.
2. **Records what it couldn't read, and never guesses it:**
   - An image with no readable text, a scanned page with no text layer, or pictures on a page are marked **"Magnum DI can read this"**.
   - An unavailable item, a document whose text couldn't be extracted, audio or other attachments are recorded as a gap Magnum DI can't fill.
3. **Extracts:**
   - links and domains (max 5)
   - phone numbers (8–15 digits, never dates, BSBs or account numbers; max 3)
   - email addresses (max 3)
   - organisations named (whole-word match against the brand register)
   - companies (max 2) and people
   - ABN, ACN, and AFSL/ACL licence numbers
   - financial claims and quoted phrases
   - payment details (BSB, account, PayID, crypto wallet), amounts and urgency
   - how items relate: organisation ↔ link, email or number; company ↔ ABN or licence; person ↔ company
4. **Requests to act.** A request counts only when an action is tied to what it asks for. Negated requests ("we will never ask for your password") don't count. A negation that belongs to something else never cancels a request: in "Do not delay, send the payment today" or "Don't ignore this. Reply with your PIN" the request still counts. Request phrases are quoted whole. The 9 types are:
   - payment
   - credentials
   - personal details
   - remote access
   - gift cards or crypto
   - changed payment details
   - call back
   - reply
   - open a link

   **Consequential requests** are the first six, plus a call-back when an organisation is named.

   **Read from what each sentence does, never from the words it contains.** A sentence asks for credentials only when it asks the reader to give, send, enter or read out a password, PIN, code or card details. None of these is a request: a code delivered for the reader to use ("Your Microsoft verification code is 482913"), a security notice ("Your password was changed"), advice never to share ("We will never ask for your password"), or a mention of the word in a discussion or newsletter. An ordinary sign-in, verification or payment-update request is credentials only with supporting context: a threat or deadline, a disguised name, a sender that isn't the organisation it claims, or a link that goes somewhere else.
   **Who the material speaks as:** its From name, or how its text introduces or signs itself ("This is Sam from Apple Support", "The PayPal Team"). An organisation it only mentions (a retailer selling Apple products) is not who it claims to be.
5. **Message type:** investment, family impersonation, tech support, delivery/toll, government, bank, job, romance, prize, invoice or unknown. A submission can also be classed as link only or as a general question.
6. **General question.** This applies only when nothing was submitted except the question, it holds no identifier or amount, it is 40 words or fewer, it is phrased as a question, and it doesn't describe something that happened to the person.
7. **A first reading can be disproved before the Evidence Lock.** A Higgins Triage warning sign that rests on who the material says it is and where it sends the person (MSG-08, MSG-14, MSG-18, MSG-20, MSG-21, MSG-22) stops counting when TC FlyBy's official sources verify every link, number and address in it as the organisation's own. The first reading is kept, marked disproved, beside the verification.
8. **A check that couldn't run is not a threat.** A Limited result resting only on checks that couldn't run (a lookup that didn't answer, headers that weren't available) is recorded as "Not every check could run": no warning, and never a claim that it's safe.
9. **Plans the checks.** Each check asks one narrow factual question about one exact value:

| Check | Question asked |
|---|---|
| Link (each domain) | Is this exact domain named in any scam, phishing, fraud or security warning? |
| Impersonation (each organisation named, max 2) | No search. Do the links and addresses match the organisation's official domain? |
| Phone / email | Is it named in scam warnings, or is it a published official contact? |
| Company | Is it a registered business? Is it on ASIC's Investor Alert List or in any warning? |
| ABN / ACN | Who is it registered to, and is it active? |
| Licence | Who holds it on ASIC's register, and is it current? |
| Person + company | Is the person publicly associated with the company? |
| Quoted phrase | Does this exact text appear elsewhere online or in scam warnings? |
| Claims, scam alerts | ApolloSG KB only |
| Message analysis | Planned, but it reaches Magnum DI only if the deciding test says so |

### TC FlyBy {#tc-flyby}

**Job:** a fast, low-cost investigation that takes the cheapest reliable route. TC FlyBy makes no AI call. It runs once per case; a recovered job reuses its record and repeats no lookups.

**What Higgins Triage flagged is never dismissed.** Before its own stages, TC FlyBy runs Higgins Triage's message rules (the same catalogue the phone runs) over the material, except for a call. Each threat-producing rule met is a **warning sign** about this case, recorded in the message's own words (for example, an organisation name written with a look-alike character: MSG-23). TC FlyBy's own checks can add to it, never dismiss it on their own: the only exception is a sign that rests on who the material says it is and where it sends the person, which stops counting once official sources verify every link, number and address in it as the organisation's own (Higgins Triage step 7). A case Triage flagged can't end as "No scam indicators found" while any warning sign still counts. When TC FlyBy finds nothing more, it settles the case as **Concerning** ("be careful and check it first"); Magnum DI isn't called, because it couldn't change what to do.

**Weak signals, warning signs and verified checks**
- **Weak signals:** a redirect to another site, a newly registered domain, a direct download, a third-party reputation warning (an IPQualityScore flag on a link or a number, or a warning the search finds from a source that isn't official), the material's text found copied elsewhere online. Alone or together they never make a case Concerning. They are recorded as signals, and they count only as the independent corroboration that an impersonation or another warning sign needs. Related history (this device's own earlier cases, ApolloSG's previous reports) is never a signal of any kind (see Related history).
- **Warning signs:** a real lookalike sign, the organisation's name in front of a shared link service, a register entry that doesn't match the name in the material, an ABN or ACN that fails its check-digit test, a risky claim cited to Scamwatch, and a number presented as a listed organisation's that isn't one of its published numbers (needs corroboration). Those marked as needing corroboration count only once something corroborates them.
- **Verified checks:** a positive verification (an official domain, the organisation's own domains, an official contact, a register entry that matches) settles the one check it answers, never the whole case. The rest of the material is still checked: what it asks for, where a payment, reply or call goes, and anything else it links to. A verified link never cancels a concern found elsewhere in the material.
- **Negative reputation results** are worded "no known threat listing found". That is never "clear" and never proof that something is safe.

#### Stage 1: official and direct sources (no AI, 8 s per lookup)
- **Link**
  - On ApolloSG's official-domain register (government and regulator domains, plus organisations' own domains) → **verified as official**. This settles the link's domain check only, not the case.
  - Redirects to another site → weak signal. Moving within the same site, or between one organisation's own domains, isn't. The final destination is checked too.
  - Listed by Safe Browsing, Apollo's blocklist or one of the free threat lists → **decisive concern**. Not listed → **no known threat listing found**, never proof the link is safe. A free list that hasn't been refreshed within its window is "couldn't be checked", never "not listed".
  - Registered less than 90 days ago, or flagged as new → weak signal.
  - Flagged by IPQualityScore (phishing, malware or suspicious) → weak signal (a third-party reputation warning).
  - Downloads a file directly → weak signal.
  - Named in an official scam advisory → **decisive concern**.
  - A lookup that fails is recorded as "couldn't be checked", never as safe.
- **Impersonation**
  - Not being the organisation's main domain is never, on its own, a sign of impersonation.
  - Every link and address uses the organisation's own domains → **verified as the organisation's own**, which settles the impersonation check only. These are its published domains and sub-sites (pages.ebay.com.au), and, for a global organisation, its exact name on a country ending (ebay.com.au), as its country sites are.
  - A real lookalike sign → a warning sign on its own: the name with words added (commbank-notice.net, signin-ebay.com.au), a look-alike spelling (paypa1.com), the name in front of someone else's address (ebay.com.secure-login.example), or the name on another ending (commbank.co).
  - The name in front of a link-sharing or website service anyone can use (ebay.onelink.me) → a warning sign on its own.
  - The name is only *mentioned* beside an address that doesn't carry it → can't be confirmed either way; needs corroboration.
- **Phone:** named on ASIC's investor alert list → **decisive concern** (an official source naming this exact number). A listed organisation's published number on the Official Organisation Directory → **verified as an official contact**, which settles that check only. The material names a listed organisation but the number isn't one of its published numbers → warning sign that needs corroboration, with the organisation's published numbers named. An IPQualityScore fraud score of 85 or more, or recent abuse → weak signal (a third-party reputation warning).
- **Email:** named on ASIC's investor alert list → **decisive concern** (an official source naming this exact address). A listed organisation's published address on the Official Organisation Directory → **verified as an official contact**, which settles that check only. An official domain → **verified as official**, which settles the email address check only. A free personal account (Gmail and similar) while an organisation is named → warning sign, but it needs corroboration.
- **ABN/ACN:** checked with the official check-digit test. A fail is a warning sign and settles the check. A pass shows only that the number is well formed, never who holds it.

**TC FlyBy's stages end here only for a decisive concern → Confirmed scam or threat.** The deciding test still applies.

#### Stage 2: ApolloSG Knowledge Base (no AI)
- **Scam patterns.** There are 12 patterns from Scamwatch: family "new number" ("Hi Mum"), organisation phishing, delivery/toll, government threat, unexpected money or prize, job/paid task, investment returns, and remote access/tech support; and four for phone calls only: a bank or card provider asking for a code, PIN, password or card details; government or police impersonation asking you to pay, move money or hand over details; tech support or an internet provider asking you to install an app, share your screen or give remote access; and a delivery or parcel company asking for a fee or card details.
  - **Full match:** every defining indicator plus the ask. Organisation phishing also needs an organisation named and a link that isn't its own. Delivery/toll needs a link that isn't official.
  - **Phone calls:** a case opened from a call check is a call to assess, never a general question. The call is compared as the person described it (who the caller said they were, what they asked for, and anything typed), against all the patterns that need no link, and the four phone-call patterns are compared with calls only. They are matching rules, never a library answer to a general question. A call described only in the question goes to Magnum DI (Reasoning).
  - **Opening:** every indicator but no ask yet. This applies to the family pattern only.
  - **Partial:** some indicators. This establishes nothing on its own.
  - Indicators are phrases, never single keywords. Negated phrases don't count.
- **Claims.** Guaranteed returns, % per day/week/month, "risk-free", "double your money" or "can't lose" → a warning sign, cited to Scamwatch. Other claims are neutral.
- **General question.** An answer found in the KB settles it.
- **Limits.** Only sourced, current KB entries are used. Saved AI answers and historical pages are never used. KB content is general knowledge, never evidence about the sender.

**The stages still end early only for a confirmed threat, or an answered general question.** The deciding test still applies.

#### Stage 3: one targeted web search
- Only open checks no direct source or the KB already answered get here. **No AI is called.**
- ApolloSG's earlier lookups are checked first (see Reusable intelligence). A current earlier result about the same link, number, email address, company, ABN, ACN or licence is reused and not asked again. Something found counts as current for 7 days, "nothing found" for 1 day. Lookups about the material itself (a quoted phrase, a person, a claim) are never saved or reused.
- **One Brave Search request per case**, claimed for the case before it is sent, so no retry, job or recovery can make a second. It goes to the open check most likely to change the outcome or what Higgins tells the person: a link, number or address a consequential request goes through first, then the kinds an official source can settle. Every other open check is recorded as not searched: missing evidence, never a pass.
- The same lookup already running for another case is waited for and its result reused, never sent twice.
- The results are read by fixed rules, never by a model: a result counts only when its own words name the exact value; the publisher's authority comes from ApolloSG's trusted-source list; the fact quotes the page's own words with its publisher. A page on the subject's own domain is never a warning about it. "No record found" is recorded as missing, never as verified and never as proof of safety.
- Not set up, the spending limit reached, or the preview server: the search is recorded as unavailable and nothing is sent.
- How answers are treated:
  - A warning from an **official** source that names the exact link, number, email or company → **decisive → Confirmed**.
  - Any other warning → a third-party warning: a weak signal, never decisive and never Concerning on its own.
  - "Official contact" → **verified as an official contact**, which settles that check only.
  - "Copied elsewhere" → supporting evidence only (a weak signal). It never establishes a concern on its own.
- **Register entry for an ABN, ACN or licence:**
  - Matches the name in the material → **verified**, which settles the register check only.
  - A related but different name → conflict, sent to Magnum DI.
  - No match → warning sign.
- A failed search is recorded as unavailable and passed on.
- **ABN, ACN and licence numbers:** the exact number goes only into the register search that verifies it (who holds it, and is it current). Any other search carries it as a label, never the number (see Privacy and redaction).

#### The deciding test
*"Could unresolved evidence materially change Apollo's outcome or the protective action Higgins recommends?"* If not, TC FlyBy settles the case. If it could, the case goes to Magnum DI, even when TC FlyBy has already reached a concern outcome. "Unable to determine" is a valid finished result.

**How TC FlyBy's outcome is chosen (first that applies):**
1. **Confirmed scam or threat:** a decisive concern was found.
2. **Likely scam:** a full pattern match that nothing contradicts. A contradiction is an impersonation pattern where every link and address is the organisation's own.
3. **Concerning:** corroborated impersonation. An organisation is named, a link isn't one of its own domains, and an independent fact about that same link backs it up (a weak signal: a new domain, a third-party flag, a redirect to another site, or a download).
4. **Concerning:** the opening of the family pattern, with no ask yet.
5. **Concerning:** an established warning sign, including any rule Higgins Triage met. Weak signals never count here, alone or together. A name mentioned beside another organisation's address counts only once something corroborates it.
6. **No scam indicators found:** only when everything was checked. There are no gaps and no failed lookups, and every link is either verified as official, or has no known threat listing *and* an established registration.
7. Otherwise: **Unable to determine**, with any weak signals listed.

**Then the Magnum DI triggers below are checked, whatever the outcome.** A trigger sends the case to Magnum DI only when what it leaves unresolved could materially change the outcome or the protective action. Otherwise TC FlyBy settles the case with its outcome.
- **The outcome changes materially** when the unresolved evidence could decide whether there is a concern at all: a case with no concern outcome could reach one, an Unable to determine could be resolved, or a provisional concern could prove to be a false positive. Established threat evidence is never overridden (see Magnum DI).
- **The protective action changes materially** when the unresolved evidence could call for a different or additional step, for example contacting the bank because a payment may be involved, removing an app because remote access may be involved, or changing a password because credentials may be involved.
- Concerning, Likely scam and Confirmed lead to the same protective action, so Magnum DI is never called only to move a case between them.
- **Once a concern outcome is reached,** the request is already known, so reasoning about it can't change what to do. What can still count is content TC FlyBy couldn't read (Reading), and, for a provisional concern, a contradiction about the very facts the concern rests on (Relating). A concern resting on established threat evidence goes to Magnum DI only for Reading.

#### Triggers for Magnum DI (whether or not a concern outcome was reached)
| Capability | Trigger |
|---|---|
| **Reading** | Content Triage couldn't extract but Magnum DI can read: an image with no readable text, a scanned page, or the pictures on a page. |
| **Reasoning** | The material makes a consequential request (money, credentials, personal details, remote access, gift cards/crypto, changed payment details, or a call-back for a named organisation) through a route no official source verified. A route is verified only by an official domain, an official email domain, or a number the search confirmed as official. Payment details can never be verified. |
| **Relating** | Findings that contradict each other: a register entry under a related but different name; an organisation named beside an address that isn't its own, with nothing to corroborate it; or scam-pattern wording beside the organisation's real links while the request still goes somewhere unverified. |
| General question | Neither the KB nor the search could answer it. |
| Safety net | TC FlyBy's own result fails Apollo's validation, so Magnum DI takes the whole case with search on. |

A trigger counts only under the deciding test above. The type of input, its category or uncertainty alone never sends a case to Magnum DI. Example: a text already Concerning because of a lookalike link, with a picture TC FlyBy couldn't read that may hold a bank-transfer request, goes to Magnum DI (Reading). The same text without the picture is settled by TC FlyBy as Concerning, because nothing unresolved could change what the person should do.

**What Magnum DI receives:**
- the person's question, once
- TC FlyBy's brief ("For Magnum DI to settle — only these"), with the facts that bear on each issue and any partial pattern match
- TC FlyBy's outcome, when it reached one, marked as resting on established threat evidence or as provisional, with each finding it rests on labelled (E1, E2… for established threat evidence, P1, P2… for a provisional concern)
- the evidence each issue needs, with any exact ABN, ACN or licence number as a label beside the register check's result (see Privacy and redaction)
- anything TC FlyBy didn't examine
- any pre-gathered results TC FlyBy had no reader for

What TC FlyBy already settled, and the raw lookups behind it, are not sent again.

**Magnum DI's web search is on only when** something is being read for the first time, a lookup failed, or a general question is still open.

### Magnum DI {#magnum-di}

**Job:** a deep investigation, only when unresolved evidence could materially change the outcome or the protective action (see the deciding test).

**Process**
1. It runs only when TC FlyBy hands it issues under the deciding test, whether or not TC FlyBy reached a concern outcome. It never runs for a follow-up: follow-up questions, answers to its own question, retries, Resubmit taps, new jobs and restarts are answered from the case's locked findings (HIG-01).
2. **Size limit.** If the written evidence is over 10,000 words, nothing is sent, and the person is told the word count.
3. **At most 1 Magnum DI call per correlated case, and no retry.** The call goes to the AI provider and model selected in ApolloSG Settings → AI Provider & Model (ApolloSG's default until an admin changes it). The model is fixed when the investigation starts, so a change applies from the next investigation. If that model can't be used, or its call fails, the investigation says so: ApolloSG never switches to another model or provider.
   - The call is claimed for the case before anything is sent, apart from the case and job records, so a follow-up, retry, Resubmit tap, new job, recovered job or app restart never resets it. A case TC FlyBy settles uses none: the limit is at most one, never a requirement to make one.
   - If the call fails or its answer doesn't pass Apollo's checks, the investigation stops and says why, with what TC FlyBy established kept and shown. It is never tried again for that case. A configuration error says a technical fix is needed.
   - Only a stop before the call was made (TC FlyBy interrupted, or the daily spending limit refused the call before anything was sent) can be resubmitted.
   - A new case needs a genuinely separate incident or materially new evidence. Rewording a question, or submitting identical evidence again on the same device, opens the existing case instead.
4. There is no system prompt; the response shape and the outcome definitions travel in the schema. There are no tool rounds, no escalation to a bigger model and no further provider call to present the answer.
5. **The answer contains:**
   - overview and explanation
   - assessment and outcome
   - attention level (none, review, action needed or urgent) and the reason
   - findings, each citing evidence and marked as observed, reported by the person, or inferred
   - uncertainties and scope
   - actions and the recommended action
   - an optional question
   - completion: complete, partial or waiting for the person
6. Pages the web search used are saved as case sources. They are leads, not verification.

**Validation (an invalid answer is rejected, never replaced with an invented one)**
- Findings may cite only registered evidence and sources. "Observed" needs evidence.
- "Concern found" needs at least one finding.
- "No concern" can't come with "action needed" or "urgent".
- The outcome must match the assessment.
- Phone actions need a capability the device advertises. "Open verified source" needs a registered source.
- Every action needs a label and an instruction. "Action needed" or "urgent" needs at least one action and a reason. If there are actions, a recommended one must be set.
- "Waiting for the person" needs a question, and a question needs that status.
- "Complete" only when all material evidence was examined; otherwise "partial".
- A result can never contradict established threat evidence. A material that asks for a password, PIN, one-time code or card details can't end below Concerning. A result below TC FlyBy's provisional concern must name the provisional finding it corrects (its label, such as P1, among the finding's superseded findings) and cite the evidence that resolves it.
- The AI tool must have finished normally.

If the answer fails, the check fails honestly. The raw reply is kept only in the technical details.

**Information Magnum DI can ask for (no other part of ApolloSG can)**
- **A question to the person**, as free text, yes/no or multiple choice, always with the reason it's needed. The case waits, and the answer continues the investigation as a new turn.
- **A fresh device reading, a setting to open or a permission to grant**, only when the phone advertises that capability.

**Established threat evidence and provisional concern**
- **Established threat evidence** is never overridden. It is authoritative evidence (a Safe Browsing, blocklist or free threat list listing, an official scam advisory, or an official source naming this exact item: a decisive concern) and deterministic evidence Apollo observed directly that is threat evidence in itself (the material asks for a password, PIN, one-time code or card details; a program disguised as a document; credentials written into a link; a displayed link that differs from where it really goes). Magnum DI can't contradict it, and a case whose concern rests on it is never lowered.
- **A provisional concern** is one TC FlyBy inferred: a scam-pattern match, a corroborated impersonation, an established warning sign, or a concern resting on what Apollo's register or a third party doesn't list. Magnum DI may confirm it, raise it, or correct it downward when deeper investigation shows it was a false positive, for example when the link proves to be the organisation's own or the contact proves official.
- Magnum DI lowers a provisional concern only with evidence that resolves it, and its result names the provisional finding it corrected and cites that evidence. Finding nothing more never lowers a concern.
- It is never called only to move a case between concern outcomes.

### Higgins (explanation) {#higgins-explanation}

**Job:** explains and guides. Higgins never investigates. It may change how a result is presented, never what it means.

**Order.** HIG-01 to HIG-08 are tried in this order, and the first that applies answers. Ask Higgins makes no AI call: every answer comes from Apollo's records, the phone's live state, ApolloSG's product knowledge or ApolloSG's KB.

**Higgins explanation rules (11)**

**EXPLAIN** (11)
- **HIG-01** · Every follow-up on an investigated case is answered from its locked findings, with no AI, and the case is never reopened
  - This includes an answer to Magnum DI's own question, and a case whose Magnum DI call failed: its reason and what TC FlyBy established.
  - It covers: checking again, what wasn't established, sources, evidence, confidence, what to watch for, why it's suspicious, what it means, what to do, and what was found.
  - Anything new (a link, email or phone number) is named as not covered: "start a new check".
  - A general question about that kind of scam is answered from the KB, labelled as general knowledge and kept apart from the case.
  - The answer credits whoever settled the check: TC FlyBy or Magnum DI.
- **HIG-02** · Something to check goes to the investigation pipeline
  - What counts as something to check is set out under Ask Higgins below.
- **HIG-03** · A scam alert the person opened is shown in the source's own words
- **HIG-04** · A Learn article is shown in its own words
- **HIG-05** · Patrol records, the phone's live state, recent investigations and ApolloSG product knowledge are shown as they are
  - A "how do I…" or "where is…" question about using ApolloSG is answered first from the ApolloSG User Guide — the same guide the app shows under ☰ → User Guide: the one topic that answers it, its direct answer first, then its steps and any limitation, with taps to the screens. Never a whole section, and never a scam article in its place.
  - Scam-education questions ("how do I spot…", "how do I report…") are not product questions and still go to the KB.
- **HIG-06** · ApolloSG's KB is quoted with publisher and link, labelled as general knowledge
- **HIG-07** · An off-topic question gets a fixed reply, word for word
  - "I specialise in helping you stay safe from scams and cyber threats through ApolloSG. For that question, a general assistant would be a better fit. Is there anything security-related I can help with?"
- **HIG-08** · A question nothing above answers is told plainly that ApolloSG's trusted knowledge doesn't cover it; no general AI model is asked
  - "ApolloSG's trusted knowledge doesn't cover that question yet, so I won't guess at an answer. If it's about something you've received — a message, link, email, call, app or file — tap + and add it, and Apollo's investigators will check it. Learn with Higgins has guides on the common scams.", with a tap to Learn with Higgins. Something specific to check still goes to TC FlyBy and Magnum DI (HIG-02).
- **HIG-09** · The phone's live reading is the truth: Higgins never contradicts it, guesses past it or invents a concern
- **HIG-10** · A case gets at most one Magnum DI call: answering its pending question doesn't reopen the investigation
- **HIG-11** · Plain Australian English, no internal codes, 2–4 short paragraphs

#### Plain English and the Fidelity Check
Every finished TC FlyBy or Magnum DI result is explained in plain English by the **Higgins Plain-English Renderer** and checked by the **Fidelity Check** before it is shown. Both have their own sections below.

#### Higgins Luddish L1 (on the phone)
Luddish L1 is the one language layer everywhere Higgins speaks on the phone: check results, reports (Ask Higgins and a threat's Overview) and Ask Higgins answers. It is fixed rules only: no AI and no network. **It changes the language, never the evidence.**
- **Order:** Evidence Lock → Luddish Dictionary and Knowledge → Luddish Rules → Composer → Grammar and Punctuation → Readability Check → Evidence Fidelity Check → Higgins.
- **Evidence Lock:** the state, every finding (with who established it and how firmly), what isn't certain, what to do and who blocked it are frozen first. A lock that changed is never explained in plain words.
- **Dictionary:** one approved name and meaning for each term. A term is swapped for plain words only where they mean exactly the same ("URL" → "web address", "malicious" → "harmful"); every other term is kept and explained.
- **Knowledge:** general background, each entry with its source. Knowledge can explain evidence; it never becomes case evidence, and is never shown as a finding.
- **Rules:** one approved set of words for each state, never stronger or weaker than the state Apollo recorded. A state is never guessed: anything unrecognised is "unable to determine".
- **Composer:** Finding → Meaning → Importance → Limitation → Action. Apollo's own steps are used when it recorded any; "you don't need to do anything" only when nothing needs doing.
- **Grammar and Punctuation:** the Plain-English Renderer's swaps, plus a few that mean exactly the same; contractions; a long sentence split only where a full stop changes nothing. Links, addresses, numbers, dates, amounts and quoted words are held aside and put back word for word.
- **Warnings keep their strong wording:** an instruction ("Do not share the code", "…and do not tap the link") and a capitalised NOT are never shortened, and a headline, Apollo's answer or a step of what to do never shortens a "not" at all. Only ordinary sentences use contractions.
- **Readability:** the target is Year 7–8 (Flesch–Kincaid grade 8 or under, no sentence over 25 words). A sentence that is still hard keeps its exact words, with a plain note beside it: the dictionary's meaning of its hard terms, or the state's "In short" line. Evidence fidelity outranks readability.
- **Evidence Fidelity Check:** a line is shown in plain words only when nothing changed: the same meaning, the same "not", the same numbers, every "because" and "so", every identifier and quote, and no more certain, safer, milder or more alarming. Otherwise that line is shown in Apollo's own words.
- **Never reworded:** a scam alert, a Learn article and ApolloSG's KB stay in the source's own words, and the full technical details stay exactly as recorded.
- At most 2 plain notes are shown beside one result.
- **Question buttons on each result:** check results, investigation reports in Ask Higgins and a threat's Overview offer up to five questions — What does this mean? · Why does it matter? · How sure is Higgins? · What should I do? · Show the technical detail. A question is offered only when its answer adds something the screen doesn't already say, and its answer opens right under the result, one at a time. A general question answered from ApolloSG's library has nothing to explain, so it has no question buttons. Answers come only from the checked explanation, the recorded state's approved wording, the dictionary's meanings and the Knowledge Library (always labelled as general knowledge, with its source, never as a finding).
- **Show the technical detail** is Apollo's own wording exactly as recorded, with who established each piece and how firmly. Luddish never rewords it; where it reworded a piece elsewhere, its plain words are shown beside the original, never in place of it.
- **Typed questions about a word** ("What is phishing?", "What does DMARC mean?") are answered on the phone from the dictionary and the Knowledge Library, labelled as general knowledge. They never open a case. ApolloSG's own names keep Higgins' own replies.

### Higgins Plain-English Renderer {#plain-english-renderer}

**Job:** explains a finished TC FlyBy or Magnum DI result in everyday words, in Apollo's wording only. No AI is used and it costs nothing. A general question with nothing checked has nothing to explain, so it is shown as answered.

**The evidence lock.** The plain English can't add, drop or change a fact, a link, address, number, date or amount, how sure ApolloSG is, how serious it is, what to do, or who established it. The result itself is never changed: the explanation sits beside it, and where the two could ever differ the result wins.

**Step 1: the facts.** Built only from the validated result and the case's own records: what Higgins Triage and TC FlyBy did, what Magnum DI was sent, and the registered sources the result relied on. Nothing is recomputed, re-scored or reinterpreted. The facts are split into parts:
- **The result:** the outcome's label, then the result's overview, sentence by sentence.
- **Each finding:** its words, who established it, and how firmly.
- **What it means:** the result's explanation. A "what was found" line that isn't one of the findings is still a fact and is kept here.
- **Why it matters:** the result's reason for its attention level.
- **What to do:** every step, one for one with the actions on the screen.
- **What isn't certain**, and **how Apollo checked** (the method and what was in scope).

**Identifiers that must survive word for word:** links, email addresses, domains, registration numbers (ABN, ACN, ARBN, AFSL, ACL, licence and registration numbers), phone numbers of 8 to 15 digits, amounts of money, percentages, dates and durations.

**Contradictions:** any sentence of the result that says "but", "however", "although", "though", "whereas", "inconsistent", "doesn't match", "does not match", "don't match", "unlike", or a form of "contradict" or "differ".

**Step 2: the draft, in this order**
1. **The result:** the outcome by its label first, then whatever the result says that the findings don't already.
2. **How serious:** one fixed line for the attention level, never anything else.
3. **What was established:** every finding, in order, each labelled with who established it and how firmly. The first jargon word in a finding gets one of Apollo's fixed explanations, beside the finding, never as evidence.
4. **What it means**, **why it matters**, **what to do** (every step), **what isn't certain** and **how Apollo checked**.

**How serious**

| Attention | Line shown |
|---|---|
| None | How serious: nothing Apollo found needs action. |
| Review | How serious: worth a careful look before you act on it. |
| Action needed | How serious: you need to act. See what you can do. |
| Urgent | How serious: urgent. Act now. |

**Who established each finding**

| Basis | Label shown |
|---|---|
| Seen directly | Seen directly by TC FlyBy / Seen directly by Magnum DI |
| Told by the person | From what you told Apollo |
| The investigator's reading | TC FlyBy's reading of the evidence, not seen directly / Magnum DI's reading of the evidence, not seen directly |

How firmly: **High confidence**, **Medium confidence**, **Low confidence**.

**Plain-English Renderer rules (10)**

**EXPLAIN** (10)
- **PER-01** · The evidence lock: no fact, identifier, certainty, severity, step or attribution is added, dropped or changed
- **PER-02** · The facts come only from the validated result and the case's own records
- **PER-03** · Identifiers survive word for word
- **PER-04** · The draft follows the fixed order
- **PER-05** · How serious is one fixed line for the attention level
- **PER-06** · Every finding is labelled with who established it and how firmly
- **PER-07** · Markdown is removed, and a link keeps its address
- **PER-08** · Formal words are swapped only from the fixed list
- **PER-09** · Each point is said once, and every finding is always listed
- **PER-10** · Jargon is explained once per result, in Apollo's fixed words

**What the renderer may change, and only this**
- **Markdown** is removed: headings, bold, italics, code marks and bullets. A link keeps its address in brackets.
- **Formal words** are swapped for plain ones from the fixed list below. Quoted words and identifiers are held aside and put back word for word, so they are never touched. A capital first letter stays a capital.
- **Each point is said once.** A sentence that makes the same point as one already said isn't repeated. Findings are placed first, so every finding is always listed.
- **Jargon** is explained once per result, with the fixed explanation from the list below and nothing else.

**Plain swaps (formal → plain)**

| Formal | Plain |
|---|---|
| "in order to" | "to" |
| "prior to" | "before" |
| "approximately" | "about" |
| "utilised" | "used" |
| "utilized" | "used" |
| "utilising" | "using" |
| "utilizing" | "using" |
| "utilises" | "uses" |
| "utilizes" | "uses" |
| "utilise" | "use" |
| "utilize" | "use" |
| "commenced" | "started" |
| "commences" | "starts" |
| "commence" | "start" |
| "insufficient" | "not enough" |
| "sufficient" | "enough" |
| "additional" | "more" |
| "obtained" | "got" |
| "obtain" | "get" |
| "assistance" | "help" |
| "regarding" | "about" |
| "numerous" | "many" |
| "subsequently" | "later" |
| "furthermore" | "also" |
| "moreover" | "also" |
| "additionally" | "also" |
| "nevertheless" | "still" |
| "nonetheless" | "still" |
| "indicates" | "shows" |
| "indicated" | "showed" |
| "indicating" | "showing" |
| "indicate" | "show" |
| "demonstrates" | "shows" |
| "demonstrated" | "showed" |
| "attempts to" | "tries to" |
| "attempted to" | "tried to" |
| "attempt to" | "try to" |
| "is unable to" | "can't" |
| "are unable to" | "can't" |
| "was unable to" | "couldn't" |
| "were unable to" | "couldn't" |
| "cannot" | "can't" |
| "can not" | "can't" |
| "do not" | "don't" |
| "does not" | "doesn't" |
| "did not" | "didn't" |
| "is not" | "isn't" |
| "are not" | "aren't" |
| "was not" | "wasn't" |
| "were not" | "weren't" |
| "has not" | "hasn't" |
| "have not" | "haven't" |
| "had not" | "hadn't" |
| "could not" | "couldn't" |
| "would not" | "wouldn't" |
| "should not" | "shouldn't" |
| "will not" | "won't" |

**Jargon explanations (Apollo's fixed words)**

| Term | Explanation shown |
|---|---|
| registration record | A web address's registration record is the public record of when it was set up and who it was registered through. |
| domain | A domain is the name part of a web or email address, the part that says who runs it. |
| phishing | Phishing is a fake message or website made to trick you into handing over passwords, codes or money. |
| malware | Malware is software made to harm your device or steal from it. |
| redirect | A redirect sends you on from the address you tapped to a different one. |
| Safe Browsing | Google Safe Browsing is Google's list of websites known to be harmful. |
| IPQualityScore | IPQualityScore rates how risky a link or phone number looks. Its score is a likelihood, not proof. |
| blocklist | A blocklist is a list of addresses already known to be harmful. |
| VoIP | A VoIP number runs over the internet, and anyone can set one up in minutes. |
| ABN | An ABN or ACN is the public number of a business registered in Australia. |
| ASIC | ASIC is Australia's company regulator. Its registers list companies and licence holders. |
| AFSL | An AFSL is the licence a business needs in Australia to sell investments or give financial advice. |
| PayID | PayID sends a bank payment to a phone number or email address instead of account details. |
| impersonation | Impersonation means pretending to be a real person or organisation. |
| lookalike | A lookalike address copies a real organisation's name with small changes. |
| one-time code | A one-time code is the short code a service sends to prove it's you. |
| remote access | Remote access lets someone else control your device from somewhere else. |
| spoofing | Spoofing makes a call or message look like it comes from someone it doesn't. |
| cryptocurrency | A cryptocurrency payment is very hard to trace or get back. |

### Fidelity Check {#fidelity-check}

**Job:** compares Higgins' plain English with the facts before anything is shown. It passes only when nothing was lost, added or changed. It is deterministic: no AI is used and it costs nothing. A failure names only the kind of problem and the part where it happened, never anything from the case.

**Fidelity Check rules (3)**

**EXPLAIN** (3)
- **FID-01** · The plain English is shown only when nothing was lost, added or changed
- **FID-02** · At most 2 checks run on each result: plain, then repaired, then Apollo's own wording
- **FID-03** · A renderer error never fails an investigation, and Apollo's own wording is shown

**The failure codes.** Each failure code below is an EXPLAIN rule (33). The check passes only when none of these is found:

| Code | Fails when |
|---|---|
| OUTCOME_CHANGED | The plain English doesn't open with Apollo's outcome as recorded. |
| OUTCOME_CONFLICT | The plain English names a different outcome from Apollo's. |
| SEVERITY_CHANGED | How serious it is doesn't match Apollo's attention level. |
| FINDING_DROPPED | A finding is missing from the plain English. |
| FINDING_ADDED | The plain English lists a finding Apollo didn't record. |
| FINDING_ORDER | The findings are in a different order from Apollo's. |
| FINDING_ALTERED | A finding's meaning changed in the plain English. |
| CONFIDENCE_CHANGED | How sure ApolloSG is about a finding changed. |
| BASIS_CHANGED | Who established a finding, or how, changed. |
| EXPLANATION_NOT_APOLLO | An explanation isn't one of Apollo's fixed explanations. |
| STATEMENT_DROPPED | Something Apollo's result says is missing from the plain English. |
| STATEMENT_ALTERED | Something Apollo's result says changed meaning in the plain English. |
| UNSUPPORTED_STATEMENT | The plain English says something Apollo's result doesn't. |
| ACTION_DROPPED | A step of what to do is missing. |
| ACTION_ALTERED | A step of what to do changed. |
| ENTITY_DROPPED | A link, address, number, date or amount from the result is missing. |
| ENTITY_INVENTED | A link, address, number, date or amount appears that the result doesn't have. |
| QUOTE_ALTERED | Words quoted from what was sent weren't kept word for word. |
| CONTRADICTION_DROPPED | A contradiction in the evidence was smoothed over. |
| CERTAINTY_ADDED | The plain English sounds more certain than Apollo's result. |
| SAFETY_CLAIM_ADDED | The plain English sounds safer than Apollo's result. |
| SEVERITY_SOFTENED | The plain English plays the risk down. |
| SEVERITY_ESCALATED | The plain English plays the risk up. |
| ATTRIBUTION_CHANGED | The plain English credits the wrong investigator. |
| SUBJECT_DROPPED | A finding lost what it is about: the address, website, number or company it names. |
| RESULT_CHANGED | What a check found about its subject isn't what Apollo recorded. |
| RESULT_KIND_CHANGED | Unavailable, failed, no match and not applicable were mixed up. |
| DECISION_REASON_DROPPED | The reason for Apollo's status is missing or changed. |
| UNRESOLVED_DROPPED | Something Apollo left unresolved is missing or changed. |
| ACTION_REASON_DROPPED | The case asks the person to act without the reason Apollo recorded, or drops that reason. |
| STANCE_CHANGED | A finding that supports or goes against Apollo's conclusion is on the wrong side. |
| CAUSAL_DROPPED | A "because" or "so" link between two facts was lost. |
| RENDERER_ERROR | The renderer stopped with an error, so Apollo's own wording was shown. |

**"The same point."** A plain sentence makes the same point as Apollo's sentence only when all of these hold:
- at least 85% of Apollo's meaning-bearing words are in it;
- no more than 25% of its own meaning-bearing words are new;
- it has the same yes-or-no: the same number of neither, never, no, nobody, none, nor, not, nothing, nowhere, without, and n't forms;
- it has the same numbers;
- every quote in Apollo's sentence is in it word for word.

Small words such as "the", "a" and "of" are ignored, and a formal word and its plain swap, or a word and its contraction, count as the same word.

**Tone words.** The plain English may use these words no more often than Apollo's own wording does:
- **More certain (CERTAINTY_ADDED):** "definitely", "certainly", "guaranteed", "proven", "proves", "100%", "without doubt", "no doubt", "for sure", "confirmed", "always"
- **Safer (SAFETY_CLAIM_ADDED):** "safe", "safely", "genuine", "legitimate", "legit", "trustworthy", "harmless", "nothing to worry", "no need to worry", "don't worry", "fine"
- **Milder (SEVERITY_SOFTENED):** "probably", "just", "only", "minor", "slightly", "a little", "low risk", "unlikely", "maybe"
- **More alarming (SEVERITY_ESCALATED):** "urgent", "urgently", "immediately", "dangerous", "emergency", "right now", "critical", "serious", "seriously"

The same count applies to another outcome's label (OUTCOME_CONFLICT) and to the other investigator's name (ATTRIBUTION_CHANGED).

**Attempts, and what the person sees.** At most 2 checks are run on each result.

| Mode | When | What the person sees | Admin shows |
|---|---|---|---|
| plain | The first draft passes. | Higgins' plain English. | PASS |
| repaired | The first draft fails. The parts that failed are put back in Apollo's own wording, and the second check passes. | Plain English, with the failed parts in Apollo's own wording. | PASS |
| literal | The repaired draft fails too, or a failure can't be tied to one part. | Apollo's own wording only. | FAIL |

A renderer error never fails an investigation. It is recorded as RENDERER_ERROR and Apollo's own wording is shown.

**Staff see** PASS or FAIL on every case in the admin portal, what the person was shown, each attempt's reasons, and both texts side by side while the server still holds the case. The DI tab's last step, the Evidence Lock, says whether Higgins' plain English matched the locked result. The DI tab shows no token counts, costs, Magnum DI's prompts or full reply, or rule-book codes: staff see those in the admin portal's investigation drill-down.

### Settling rules: the reason shown on each result {#settling-rules}

Every finished result can show one plain sentence naming the rule that settled it, in the form **"Settled by TC FlyBy — Known scam, every step: …"**. Each settling rule is an EXPLAIN rule (13): it names what settled the result and never changes it. People can turn the sentence off in Settings → App. Staff see the same sentence on each case in the admin portal. The sentence never repeats anything from what the person sent.

| Rule ID | Rule | Settled by | When it applies |
|---|---|---|---|
| FLYBY-THREAT | Confirmed threat | TC FlyBy | A direct safety check, an official scam advisory, or an official source found by the search names this exact link, number, address or company as a scam or threat. |
| FLYBY-PATTERN | Known scam, every step | TC FlyBy | A full match with a known scam pattern in ApolloSG's knowledge base, and nothing contradicts it. |
| FLYBY-IMPERSONATION | Corroborated impersonation | TC FlyBy | An organisation is named, a link isn't its website, and a separate check on that link backs this up. |
| FLYBY-OPENING | Known scam opening | TC FlyBy | The message opens like the family "new number" scam but hasn't asked for anything yet. |
| FLYBY-SIGNS | Established warning signs | TC FlyBy | The checks found an established warning sign (weak signals alone never count), but not enough to call it a scam. |
| FLYBY-CLEAR | Nothing found, everything checked | TC FlyBy | Every planned check ran over everything sent and none found a scam indicator. |
| FLYBY-UNKNOWN | Can't establish more | TC FlyBy | The checks couldn't establish more, and a deeper look couldn't change what to do. |
| FLYBY-ANSWERED | Question answered from a source | TC FlyBy | A general question answered by ApolloSG's knowledge base or a sourced search. |
| MAGNUM-READING | Reading | Magnum DI | Part of what was sent (a picture or scanned page) had to be read directly. |
| MAGNUM-REASONING | Reasoning | Magnum DI | The material asks for money, details or access through a route no official source verified. |
| MAGNUM-RELATING | Relating | Magnum DI | TC FlyBy's findings pointed in different directions and needed weighing up. |
| MAGNUM-QUESTION | Open general question | Magnum DI | Neither the knowledge base nor a targeted search could answer a general question. |
| MAGNUM-SAFETY-NET | Safety net | Magnum DI | TC FlyBy's own result didn't pass Apollo's checks, so Magnum DI looked at the whole case. |

When Magnum DI was needed for more than one reason, the sentence names them together, for example "Reading and reasoning". Results recorded before these rules existed show no sentence rather than a guessed one.

### Outcomes (one system for TC FlyBy and Magnum DI) {#outcomes}

| Outcome | Meaning |
|---|---|
| **Confirmed scam or threat** | An authoritative source names this exact link, number, address or company as a scam or threat. |
| **Likely scam** | The evidence and an established scam pattern point to a scam, without proof about this particular sender. |
| **Concerning** | An established warning sign or a corroborated impersonation, but not enough to call it a scam. Weak signals alone never make a case Concerning. |
| **Unable to determine** | The available evidence can't establish more. With nothing concrete left to act on, the case is filed as "Not fully checked" (see Threats list): no warning and no alert, and never called safe. |
| **No scam indicators found** | The checks performed found nothing. This is **not** proof it's safe, and it is never described as safe. |

Every result shows **"Settled by TC FlyBy"** or **"Settled by Magnum DI"**, in the app and in the admin portal.

### ApolloSG's knowledge base (KB) {#knowledge-base}

**Job:** sourced general knowledge that Higgins and TC FlyBy can use with no AI. KB knowledge is general knowledge. It is never evidence about anything a person asked Apollo to check.

**What is in it**
| Kind | Where it comes from |
|---|---|
| Learn articles | Published Learn with Higgins articles, each linked to its screen |
| Scam alerts | Official alerts and advisories from the government feeds, in the source's own words |
| Official guidance | cyber.gov.au guidance shipped with ApolloSG (CC BY 4.0, attributed) |
| Scam patterns | The Scamwatch patterns TC FlyBy compares material against |
| Researched pages | Pages on trusted websites, found and kept up to date through Tavily |
| Exploited vulnerabilities | CISA's Known Exploited Vulnerabilities catalogue, with the severity from the US National Vulnerability Database (NVD) |
| Attack techniques | MITRE ATT&CK techniques for Mobile and Enterprise (attributed to The MITRE Corporation) |
| Official organisations | The Official Organisation Directory: the published websites, phone numbers and email addresses of the organisations scammers most often pretend to be, each traced to the organisation's own pages |

Exploited vulnerabilities and attack techniques are technical knowledge: they are used only when a question names their exact id (a CVE such as CVE-2024-3400, or a technique such as T1660), never to answer an everyday question.

#### Free threat lists {#free-threat-lists}
**Job:** published lists of known threats, from free public sources only, kept in ApolloSG's own indicator store. No paid source and no separate threat-intelligence system.

| List | What it names | Publisher |
|---|---|---|
| PhishTank | Verified phishing pages that are online | PhishTank (Cisco Talos) |
| OpenPhish | Phishing pages (community feed) | OpenPhish |
| Spamhaus DROP | Networks hijacked or run by criminals (IPv4 and IPv6) | The Spamhaus Project |
| ASIC's investor alert list | Websites, email addresses and phone numbers of unlicensed and imposter financial operators | ASIC (Moneysmart) |
| ACMA's blocked gambling websites | Illegal gambling websites blocked in Australia | ACMA |

- **How they are used:** every link check looks each one up as its own list. A page is matched exactly, query included: page.php?id=1 isn't page.php?id=2, a listing of /login never covers /login?id=2, and a listing of /login?id=1 never covers /login. Google Safe Browsing's answer counts only for the exact address checked (or the website's home page), never for another address that merely contains the website's name. A whole website only when the list names the website, never a shared platform, a free mail provider or an organisation's own domain. A listing of one page is never a claim about the whole website or domain: a match says what the list names, "this exact address, …" or "the whole website …". A website on a Spamhaus DROP network matches by its IP address. Email addresses and phone numbers are matched against ASIC's list only.
- **Provenance:** every entry keeps its list, the list's own reference, the publisher, the licence or terms, when ApolloSG first saw it, when the list last confirmed it, and when it stops counting.
- **Freshness:** each list is refreshed once a day, and retried every 2 hours after a failure. Staff can refresh now from the admin portal. An entry a successful refresh no longer lists stops counting at once; an entry not confirmed within its window (3 days, or 7 for Spamhaus, ASIC and ACMA) stops counting. A download with fewer than half of last time's entries is refused and the existing list is kept.
- **Privacy:** these are published lists. Email addresses and phone numbers are kept only as a one-way code.
- The CISA, NVD and MITRE downloads follow the same schedule and appear on Feed Health with the lists.

#### Official Organisation Directory {#official-organisation-directory}
**Job:** the published websites, phone numbers and email addresses of the organisations scammers most often pretend to be (banks, government, delivery and tolls, phone and internet, shopping and payments), so a check can tell the organisation's own contact from one that only uses its name. It is one KB entry per organisation, never a separate store, and the KB's question search never quotes it.
- **Every entry is traced to the organisation's own pages.** Each needs at least one official source page, over https, on the organisation's own domains or an official authority's website.
- **What counts as official:** a domain counts when it shipped with ApolloSG or a source page is on it or names it. A phone number or email address counts only when ApolloSG found it on one of the source pages within the last 30 days. A successful re-read that no longer shows it stops it counting at once. A page that can't be read keeps the last confirmation until those 30 days run out, and never confirms anything new. A page that refuses cloud servers is read from an Internet Archive copy no older than 30 days.
- **Freshness:** every source page is re-read once a week, and a day after an attempt that couldn't read any of them. Staff can re-check now from the admin portal.
- **Admins** add, edit and remove organisations in the admin portal (Official Organisations). Every change is audit-logged and takes effect at once; a shipped entry an admin changed is never overwritten by a later release.
- **How checks use it (TC FlyBy and every check result):** a number or address on the directory is that organisation's published contact, which settles that check only. A number, email address or website presented as a listed organisation's that isn't one of its published ones is a warning sign that needs corroboration (organisations have many numbers), and the person is shown the official contact to use instead. A website carrying a listed organisation's name that isn't its domain is the lookalike or shared-service warning sign above.
- **Every check result** (link, message, email and call) lists the directory's verdict on each website, number and address it holds: "the organisation's own", or "not the official contact" with the official one to use instead. It never changes the result's outcome. The phone sends only those contacts and the organisation the material names; nothing is fetched and nothing is kept.

#### ApolloSG previous reports {#observed-patterns}
**Job:** ApolloSG's cross-device intelligence: what independent ApolloSG findings on other devices say about a website, phone number, email address, message or file, kept on ApolloSG's servers as one-way codes and per-device marks, never content. It lives in ApolloSG's own indicator store, and it is the only way anything learned on one device reaches another.
- **What is recorded:** each finished, non-simulated case sets one mark per device on each of its websites (their registrable domain), phone numbers and email addresses, and on the message and file themselves (as one-way codes of their content): **supporting** (Concerning, Likely scam or Confirmed scam or threat), **contradicting** (a complete check that found no scam indicators), **inconclusive** (Unable to determine) or **insufficient evidence** (part of the evidence couldn't be checked). A device's latest finding replaces its earlier mark. Which websites, numbers and addresses appeared together in supporting material is recorded too (a possible campaign). Never an organisation's own or official address, a shared platform, a free mail provider's domain, or a number on the Official Organisation Directory.
- **Consensus (on ApolloSG's servers only):** unanimous means no contradicting mark exists; one contradicting mark removes unanimity at once. Inconclusive and insufficient marks never break unanimity and never count as support.
- **No artificial consensus:** when ApolloSG's previous reports asserted something about a subject to a case (in Magnum DI's brief or beside the result), that case's finding on the subject is recorded as dependent and never counts as independent confirmation of the same assertion; a device's dependent finding never replaces its own earlier independent one. A device's own marks are never part of what it is told: its own cases are its related cases.
- **What a device is told (these words only; never which device, how many, when, or anyone's case or verdict):** 3 or more independent supporting findings from other devices, unanimous: "has been previously reported as malicious — High confidence". 2, unanimous: "has been previously reported as concerning — Medium confidence". Supporting and contradicting findings, at least 3 together: "has mixed previous reports" (it adds no weight). Fewer asserts nothing. Seen together on 3 or more independent devices with a website a free threat list lists now: "has been previously reported together with …, which … lists — High confidence". What a person reads never says "knowledge base" or "cases": these are previous reports.
- **Privacy:** every subject is a one-way code. Each device is a mark made from the subject and the device together, so a device can't be followed from one subject to another. A website's name is kept readably only once 3 independent devices support it; numbers, addresses, messages and files never are. ApolloSG staff see the counts in the admin portal; a device never does.
- **Freshness:** marks older than 30 days are dropped.
- **How it is used:** context, never evidence (see Related history).

#### Related history {#related-history}
**Job:** what this device's own earlier cases, and ApolloSG's previous reports, say about the same subjects as the current case. Context, never evidence.
- **Devices are mutually exclusive:** ApolloSG runs only on this device and has no relationship to any other, even one the same person owns. A related case is always one of this device's own cases; another device's case is never shown, named or counted on this one. Anything learned on other devices comes only through ApolloSG's previous reports, in their approved words.
- **What makes an earlier case related:** the same website or link, the same phone number or email address, the same message or file, the same organisation named, or already linked to this case as connected events. This device's case history keeps one-way codes of each case's subjects, its result and when, for 90 days, never content; it is deleted with the device's data.
- **What it can't do:** it is never a finding, a warning sign or a corroboration, and it never changes the outcome, attention, actions or what isn't certain.
- **What it can do:** add weight. When the case's own outcome is Concerning, Likely scam or Confirmed scam or threat and the history agrees (an earlier concern on this device, or a previous report of malicious or concerning; mixed previous reports never agree), each finding about the same subject that supports the outcome moves one confidence step up (Low → Medium → High), once, however many notes agree. A shared message, file or connected event is about the whole case. Each note lists the findings it raised, so where the extra weight came from stays visible. Magnum DI receives the same notes in its brief, labelled as context it must not cite as evidence.

#### Cross-source record {#cross-source}
**Job:** for each website, phone number and email address in a case, what every ApolloSG source says about it, side by side: the free threat lists, Google Safe Browsing, the official-domain register, the Official Organisation Directory, the official scam advisories and ApolloSG's previous reports (in their approved words only). Each row keeps the source's own reference, when it last confirmed it and when it stops counting, plus how many of the sources that answered list it.
- It adds nothing to TC FlyBy's checks. It is context: it goes into Magnum DI's brief so Magnum DI doesn't re-derive what is known and knows how current each piece is. It is never a finding by itself.

Saved AI answers are **not** in the KB. They are reusable intelligence (below), labelled as written by AI and never treated as sourced knowledge.

**Trusted sources.** A page on any other website never becomes ApolloSG knowledge.
- **Tier 1, official authority (24 websites):** government agencies, regulators, police and national cyber-security authorities in Australia, the US, the UK, New Zealand, Canada and the EU.
- **Tier 2, established security research (11 websites):** recognised research organisations and security companies.
- **Tier 3, supporting (5 websites):** credible specialist and consumer sources.
- A source is reproduced as a Learn article only when its licence allows it. Every other source is quoted briefly, with a link to read the rest.

**How Tavily is used**
- Only to find and re-read trusted pages for the KB. Never by TC FlyBy or Magnum DI, never in a live investigation, and never to answer a question as it is asked.
- Tavily is never the source. Its own generated answer is switched off, and every page it returns is checked against the trusted list again.
- **Once a week:** a run is due when the last successful run is 7 days old and no attempt was made in the last day. Staff can also start one from the admin portal.
- **Each run** searches 14 guidance topics on every tier (up to 5 results from Tier 1, 4 from Tier 2 and 3 from Tier 3) and 4 scam-alert topics in Tier 1 news. Up to 40 stored pages last checked 7 or more days ago are read again.
- Afterwards the KB brings in the latest Learn articles, scam alerts, shipped guidance and scam patterns.

**The checks every page must pass**
- It is on a trusted website, over https.
- It isn't a document file (PDF, Word, Excel, PowerPoint, zip, audio or video).
- It isn't a listing, tag, search, category or navigation page, and it has a title.
- No more than 40% of its words are links.
- It has at least 120 words of its own content, in English.

Only the page's own headings, paragraphs and bullet points are kept; menus, footers, banners and link lists are dropped. A page that fails is not stored as knowledge, and the reason is kept for 90 days for the admin portal.

**Nothing is invented, and history is kept**
- Knowledge is the source's own words. A fact the page doesn't state stays missing.
- **Same page:** if its words are at least 92% the same, it is only marked as checked again. If they changed, it becomes a new version and the old version is kept as Superseded. "Updated" shows for 30 days.
- **Same words on another page** (at least 85% the same) are recorded as another place it is published, not a new entry.
- A page ApolloSG already holds from a government feed, the shipped guidance or a Learn article isn't added again.
- **Historical, never deleted:** a page that fails to load on 2 re-reads, or a scam alert published more than 2 years ago.
- When the checks are tightened, a page that no longer passes is removed everywhere: its Learn article is archived and its Scam Alert withdrawn.

**Where a researched page is published**
- **Scam Alerts:** only a Tier 1 page found as an alert, published within the last 180 days, that Scam Alerts' fixed rules rate as a specific scam or an emerging pattern. It is rated by the same rules as the government feeds.
- **Learn with Higgins:** only from a source whose licence allows it, with at least 3 sections, practical bullet points and a summary, passing Learn's quality checks. It ends with a "Source and licence" section. An article staff archived is never brought back.

**How the KB is searched (no AI)**
- The question and each entry are reduced to the same concepts: common words removed, word endings trimmed, and everyday words for the same thing made one (bitcoin and crypto, rang and called, mum and family, itunes and gift card). Words that only frame a question (want, said, real, safe, Australia) don't count.
- Each concept counts by how rare it is in the KB: "toll" or "anydesk" tells more than "email" or "money".
- An entry answers only if it holds at least 30% of the question's weight, its title shares a concept with the question, and its score is at least 0.3. The score is 0.4 × the share of the question it holds, plus 0.25 × the share in its title, plus 0.35 × how much of what its title names the question asks about.
- A match on how something arrived alone (phone, call, text, message, email, online, website, app, money, payment, account, number) doesn't count, unless that is the whole question.
- Order, strictest first: every current entry ranks above every historical one, then an entry whose title names something ranks above one whose title names nothing in particular ("What is a scam?"), then the score. At most 2 entries are used for one answer.
- **Measured:** a fixed benchmark of 60 questions and 47 held-out ones checks every change. Before this rule, the right article came back for about 1 in 5 questions. Now it comes back for about 9 in 10 of the benchmark questions and 2 in 3 of the held-out ones, with fewer than 1 in 20 answers pointing to the wrong article.

**How it is quoted**
- In the source's own words: the passages that best match the question, in their original order.
- Each quote names the publisher, its authority, where it applies and when it was published or last checked, with a link to read the original.
- A historical entry says it may be out of date. Guidance from outside Australia says contacts and reporting steps may differ.
- Every quote ends with: "This is general knowledge from ApolloSG's library. It isn't a finding about anything you've asked Apollo to check."

**Where the KB is used**
- **Higgins:** quoted as general knowledge (Higgins step 6), and for a general question asked about a finished case, kept apart from its findings.
- **TC FlyBy:** stage 2 (scam patterns, claims and general questions). Only sourced, current entries are used; historical pages and saved AI answers never are.
- **Preview:** the preview runs exactly as production does. Only the AI tools are simulated, answered here from the KB, and anything that came from the simulator is tagged **Simulated**. Its rules, processing and wording are production's.

#### Reusable intelligence (not KB knowledge)
**Job:** results ApolloSG already obtained from its approved external providers, kept so the same thing isn't paid for twice. It is not the KB: nothing in it is ever moved into the KB or treated as sourced knowledge, and anything AI-derived stays labelled as AI-derived.

**What it holds**
- Answers an AI tool wrote to general questions before Ask Higgins stopped asking one. They are kept until they expire and are never shown again.
- TC FlyBy's targeted search about a link, phone number, email address, company, ABN, ACN or licence.
- Phone and link reputation (IPQualityScore) and domain registration (RDAP) keep their own stores, with freshness from the same table.
- Each result records who produced it, by which ApolloSG process, when ApolloSG first obtained it, when it was last checked, and when it stops counting as current.

**Never kept:** what the person sent, Magnum DI's findings about a case, quoted phrases from the material, claims, people's names, and a question with a secret or personal detail (no link, email address, number of 6 or more digits, "my name is", "I live at" or "my address"). Phone numbers and email addresses are filed under a one-way code. A simulated result is kept exactly as a live one is, tagged Simulated, and is only ever reused by the preview.

**How long a result counts as current**
| Information | Current for |
|---|---|
| Old AI answer to a general question (never shown) | 90 days |
| TC FlyBy search that found something | 7 days |
| TC FlyBy search that found nothing | 1 day |
| Phone reputation (IPQualityScore) | 24 hours |
| Link reputation (IPQualityScore) | 12 hours |
| Domain registration (RDAP) | 48 hours |

An expired result never counts as current. It is deleted 90 days after it expires.

**The sufficiency check (no AI), before every paid call**
- **Known:** the KB answers, or a current result about this exact subject is complete, backed by a source and not contradicted. It is reused and the call isn't made.
- **Partial:** something relevant, but expired, incomplete, contradicted, or for a check that must be live. The call runs as before and the result is refreshed.
- **Unknown:** nothing relevant. The call runs as before.
- The KB is always checked first. The check only saves calls; it never lowers what a check must establish.

**What the person sees**
- A reused result says when Apollo last checked it, under the source: "From Apollo's check 2 hours ago, still current, so it wasn't looked up again".

**Staff see** the admin portal's Intelligence Reuse page: calls avoided and still needed, results saved, expired results checked again, by call site and by day, what the store holds and how long each kind stays current. Counts only, never content. The same counts go to the server logs.

---

## Privacy and data {#privacy-and-data}

### Privacy and redaction {#privacy}

**The rule:** protect the person, preserve the evidence, share only what is necessary. Secrets are never sent. What shows whether something is a scam (the sender, their number, email address and links, any payment details and the words they used) is kept as evidence.

**Always removed, on the phone (never relaxed)**
Each of these is replaced with "[credential redacted]" before anything leaves the phone:
- a password, passcode or PIN given after "is", "was", ":" or "=";
- one-time, verification, security, sign-in and recovery codes, including "123456 is your verification code" and "code: 1234";
- any mention of a recovery phrase, seed phrase or mnemonic;
- bearer tokens, API keys, secret keys, and access and refresh tokens;
- a username and password written inside a link, and secret values in a link (token, password, secret, key, code or session).

**Removed again, on the server**
- Everything submitted is checked again for passwords, PINs, codes, usernames and login IDs, bearer tokens and secrets in links, and each one is replaced with "[redacted]".
- A word that only describes a secret ("password reset", "code required") is left alone.

**Before every AI request (one privacy boundary)**
- Secrets are stripped once more from the whole request, and a field that holds a credential is dropped.
- A field that holds unrelated personal data is sent as "[personal data withheld]", unless the request is an investigation the person asked for.
- Long tracking links are shortened: tracking parameters (utm, gclid, fbclid and similar) are removed, other values over 80 characters are cut, and any link over 200 characters is cut. The domain and path are always kept.
- Research and public-advisory requests also have personal identifiers replaced with labels: email addresses, phone numbers, card and account numbers, BSBs, TFNs, Medicare, ABN, ACN and licence numbers, passport and social security numbers.
- **ABN, ACN and licence numbers:** an exact number may be sent only to the approved lookup that verifies it: TC FlyBy's register question about that number (who holds it, and is it current). Every other AI or research request (Magnum DI, every other search question and KB research) carries it redacted as a label (an ABN becomes "[business number]"), with the register check's result where there is one.
- The original evidence is never changed; only the copy being sent is.

**Pictures**
- The picture's metadata is stripped first. If that fails, the picture is withheld.
- The phone reads the text in the picture. A password, PIN or code it finds is blacked out on a copy before sending, and the original on the phone is untouched. If it can't be blacked out, the picture isn't sent.
- If the phone's text reader isn't available, the picture isn't sent. The person can type the text instead.
- Personal details and sender information in a picture are kept as evidence.

**What may leave the phone**
- Every request is checked against its own list of allowed fields. Any other field stops the request: "ApolloSG couldn't safely prepare this request. Retry this step."
- Never accepted in any request: contacts, messages, SMS, email bodies, page content, the clipboard, location, IMEI, serial number, phone number or advertising ID. A number the person types to check is sent only as the number to check.
- **What the phone is:** registration, and the check-in each time ApolloSG opens, also carry the phone's make, model, system and version, the country chosen in its region settings (a two-letter code, never location) and the date ApolloSG was installed. One of Google's test phones (Play pre-launch testing) also says so, from a yes/no system setting Google sets on them, so those never count as real users. Anything the phone can't tell is left out.
- **Official contacts:** a link, message, email or call check sends the websites, phone numbers and email addresses it holds, and the organisation the material names, to be looked up in the Official Organisation Directory. Nothing is fetched and nothing is kept.
- **Number details:** a call case's top card sends the call's number (and the region setting's two-letter country, to read a local number) to read its country, line type and original network from the numbering-plan data built into ApolloSG's server. No lookup service is asked, no credit is spent and nothing is kept. The network is the one the number started on; numbers can move.
- **Which features were used:** a Device Check, or opening a Learn article or a scam alert, sends only which one it was. The server keeps a count, and for articles and alerts a one-way code of which one, so opening the same one again counts once. Never the title, the text or what was checked.
- In a link, credentials, the part after "#" and secret values are removed. The path is kept, because a scam page and a real homepage need different answers.
- **Original emails (.eml):** never leave the phone. An email check or investigation may carry only Higgins Triage's structured findings about the email evidence (see Email Gate) — never the subject, body, names, addresses, header text or the file. Any other field stops the request.
- **Who started an investigation:** an investigation (including a call or number check handed to Higgins) also says whether the person started it or Apollo detected it ("user" or "apollo"), so the case's top card reads "What you submitted" or "What Apollo detected". Nothing else about the person travels with it.
- What the person submits leaves the phone only for the check they asked for. It is never copied into Threats records, logs, analytics or background monitoring.
- **Threats records** synced to the server carry fixed wording ("ApolloSG's servers keep only this privacy-protected summary, not the content that was checked."), never the message, screenshot, file or link. Only a domain is kept as an indicator, plus a fixed label for which of the phone's own sources supplied the evidence (Apollo's check, its DNS filter or the phone's built-in protection). Records written earlier are shown in this wording too.
- **Family helpers** see fixed wording ("Security check — review with the protected person"), never the content.
- **Handing a result to Higgins:** at most 8 findings and 4 actions, each line short. Secrets, the person's own details and IP addresses are removed.
- **My Personal Data:** the person's own saved details (such as their name, email address or phone number) are replaced with a label, such as "[Email address redacted]", in message and email checks and in what a result hands to Higgins. IP addresses become "[ip address]".

**What is kept, and for how long:** see Your data.

### Your data: what is kept and for how long {#your-data}

**The rule:** what the person sends ApolloSG lives on their phone. The server keeps only what a feature needs, only for as long as it needs it, and the person can delete all of it.

**On the phone (the person decides)**
| What | How long |
|---|---|
| Finished results | Until the person deletes the check, or deletes all their data |
| ApolloSG's own copy of what was checked: the copied text, an email's body and headers (From, Subject, when it arrived), original email files (.eml) and pictures | Until the person deletes it, the check, or all their data. No clock deletes it on the phone. Headers that arrive later (from the original email, or from ApolloSG's server) fill in what the saved copy is missing; what it already holds is never changed. Only ApolloSG's copy is deleted: the message in Gmail, Messages or any other app is never touched |
| Ask Higgins chat | Up to 1 hour, and at most the last 40 messages |
| Calls Apollo screened (Android) | The last 50 calls, for up to 30 days |
| Email addresses watched for breaches | Until the person removes them. The last 12 scans are kept |
| Settings and preferences | Until the person deletes all their data or uninstalls ApolloSG |

**On ApolloSG's server**
- **Investigations:** the content is encrypted with a key used for nothing else, and the server's working copy expires 1440 minutes after it opens (24 hours). Retries and reads never extend it. The finished record lives on the phone; the server doesn't keep finished investigations.
- **The phone's copy, kept until the phone confirms it.** When a check finishes, the server keeps one copy for the phone that asked: the finished result, the exact text and links submitted, and who sent it, its subject and when it arrived. No clock removes it, not the 15-minute working copy and not the 24 hours: if the phone is offline, it waits. The phone saves its own copy, reads it back to check that it is complete, and only then tells the server; the server checks the phone named every part it holds, and only then deletes it. Sooner when the person deletes the check or all their data.
- **Pictures and files:** everything submitted for a check (pictures, files and text) is deleted from the server within 24 hours of the investigation finishing, whether it was answered, failed or was cancelled. A check that is still running is never cut short: the 24 hours start when it finishes, and start again if a follow-up question sends it back to work. Most of it goes much sooner, as soon as the phone has saved the result or with the 15-minute working copy. The database removes it by itself at 24 hours, even if ApolloSG's own clean-up has stopped, and it is never served after that.
- **The text of a message kept with a Threats record or investigation case** (its preview) is deleted 24 hours after it was kept, by every maintenance cycle — but never before the phone has confirmed it saved that record with its text. If the phone is offline, the 24 hours wait for it. Who sent it, its subject and the website stay: they are the identifiers the case is about.
- **The note on each result.** Every saved result says when its pictures and files were removed from ApolloSG's server, or the latest time they will leave it. Results saved before this note existed say only that they have left, once 24 hours have passed.
- **Ask Higgins:** the question and answer for 5 minutes, then a receipt with no content for 30 days (see Ask Higgins).
- **What Higgins remembers between chats:** a recent result for 7 days, protection status for 1 hour, a preference for 90 days, a goal for 30 days and a permission for 1 day. At most 25 of each kind and 100 in all.
- **Threats records:** fixed wording and a domain only (see Privacy and redaction). Kept until the person deletes them (see Deleting chosen cases), clears the Threats history, which hides them, or deletes all their data, which deletes them.
- **Remembered gate results:** a possible threat for 30 days and no threat for 7 days, kept against a fingerprint (a one-way code) of what was checked.
- **TC FlyBy's search answers:** 7 days for something found and 1 day for nothing found, filed under what was looked up (a one-way code for a phone number or email address). They are shared, never tied to the person who asked, and deleted 90 days after they expire (see Reusable intelligence).
- **Trusted links:** until the person removes the link.
- **Gmail:** an encrypted sign-in token, until the person disconnects. Message content is never stored (see Email Gate).
- **Family links:** until the person unpairs. A pairing code is 6 random digits, works once, and expires after 15 minutes; only the newest code a phone made works, and 5 wrong codes in 15 minutes pause linking on that phone. There is no email invitation. A Family Help session is deleted 30 days after it starts.
- **The phone's anonymous sign-in:** valid for 365 days.
- **ApolloSG previous reports:** one-way codes and per-device marks (supporting, contradicting, inconclusive or insufficient) for websites, numbers, addresses, messages and files, for 30 days, never content and never which device (see ApolloSG previous reports).
- **This device's case history:** one-way codes of each case's subjects, its result and when, for 90 days, read back only on this device and deleted with its data (see Related history).
- **Diagnostics:** device registration, protection-health checks and alert-delivery records, with no personal content. Kept until the person deletes all their data, unless they expire sooner.
- **Usage counts:** with the device record, how many times this phone used TC FlyBy, Magnum DI, Ask Higgins and Device Check, and how many different Learn articles and scam alerts it opened. Kept until the person deletes all their data, or ApolloSG's admin resets the counts (Reset Stats also deletes the AI usage and cost records and finished investigation records).
- **Saved AI answers:** kept only when the question holds no secret and no personal detail. Current for 90 days, then deleted 90 days after that (see Reusable intelligence).

**Deleting everything**
- **Settings → What ApolloSG stores → Delete My ApolloSG Data** first wipes everything ApolloSG keeps on the phone. It then deletes everything the server holds for this phone, in 7 groups: Higgins conversations, Investigations & saved reports, Patrol activity & records, Trusted links, Email & account monitoring, Family links & guardians, and Diagnostics & app signals. Last, it removes the phone's identity, so ApolloSG starts again as a new anonymous device.
- The same screen counts what the server holds in each group before anything is deleted.

**Deleting chosen cases**
- **Threats → Select** and **Patrol history → Select** put a tick on each row, with **Select all** (every row the screen shows) and **Delete (N)**. Nothing is deleted until the person confirms "Delete N cases?" / "Delete N records?".
- On Threats each row is a whole case: every check filed against it and every record of the investigations behind it. On Patrol history each chosen record goes, with every record of the investigations it was part of.
- The server deletes its copies first: the Patrol events and records, each linked investigation (its evidence, uploads, jobs, turns, the copy held for the phone, saved reports, Magnum DI transactions, its Triage record and case history), family-shared copies and notes, and alerts held for the end of quiet hours. Only then does the phone delete its own: the case, the original kept with it, its pictures and .eml files, report progress and the investigation result saved on the phone. Offline, nothing is deleted on either side.
- The phone sends only the ids of what was chosen. A deleted record leaves a marker holding only its id, its device and the reason, so a late copy from the phone's delivery queue is never stored again.
- Kept: usage and cost records (no content) and ApolloSG's previous-report marks (one-way codes). The message in the person's own Messages or email app is never touched.

### Phone permissions {#permissions}

**The rule:** ApolloSG asks only when the person chooses something that needs the permission, and says why first. If the person says no, ApolloSG asks once more at most, when the phone allows it, and after that offers Open Settings. Saying no only switches off that one feature.

| Permission | What it's for | When ApolloSG asks |
|---|---|---|
| Notifications | Receive important threat and family alerts | During setup, or with Allow security alerts in Settings |
| Camera | Scan QR codes and photograph suspicious items for checking | When the person scans a code or takes a photo |
| Photos | Choose screenshots of suspicious messages to check for scams | When the person chooses a picture or a screenshot |
| Site Gate (Android) | Run Apollo's on-device VPN filter | When the person turns on website protection |
| Notification access (Android) | Text Gate reads new text-message notifications | When the person turns on message screening |
| Caller ID & spam app (Android) | Call Gate screens incoming calls | When the person turns on call screening |
| Gmail read-only (an account, not a phone permission) | Check a connected mailbox | When the person connects Gmail |

- **Never asked for:** the microphone and location. Store builds never ask to read text messages or the call log.
- Where a phone hides Wi-Fi details without location permission, ApolloSG shows them as unknown rather than asking.
- A reminder to set up a protection the person skipped comes back after about 3 days, only while it is still off.

---

## Device protections {#device-protections}

### Threats list {#threats-list}

**Job:** one record for each check, showing what Apollo found and what to do next.

**One record, never twins**
- **Where a case begins:** every Threat Case begins on the device that detected it. Server processing, TC FlyBy, Magnum DI, syncing, the privacy-protected server copy and missing evidence never change that, and ApolloSG never says a case or its evidence came from, or is held on, a different device. A detection on a second device is that device's own case, never a continuation of the first.
- Each check creates exactly one entry. The phone's first detection and the later investigation update the same card.
- Records that name the same investigation are one case. Repeat checks of the same subject show as one case with the latest result, and every check stays in its history.
- Two records are the same finding only when they share an investigation, an explicit link between them, or the same verified indicator. A brand, website or scenario in common never merges two findings.
- The same issue with the same details again within 24 hours is recorded as a repeat, not a new finding.

**What each status means**
| Status | When |
|---|---|
| Investigating | Only while an investigation is actually running |
| Blocked | Only when real block evidence confirms it |
| Needs you | Apollo is Barking or Biting |
| Keeping watch | Apollo is Growling, or something is worth a closer look |
| Handled | The person resolved it |
| No threat | It was resolved with nothing found |
| Not fully checked | Some checks couldn't run and nothing was found to act on, or an investigation couldn't decide either way and left nothing concrete to act on (no urgent or action-needed attention and no decision for the person). Never a threat, never an alert or "Needs you", and never called safe. It never lowers a threat established apart from the investigation: a verified block, or a threat list naming the item's link |

**Rules**
- **Biting only for a real block** (see How the gates decide). The server rejects any Biting claim without the block evidence, and an edit can never turn a record into Biting.
- A handled finding reopens only when genuinely new detection evidence arrives. A repeat of old evidence never reopens it, and neither does an investigation's answer, a re-judge or a migration: a record the person handled or trusted, or one already resolved, stays closed: its closure (alert level, status and when it was closed) is kept exactly as it was, and only its findings and their words change.
- Each finished investigation shows "Settled by TC FlyBy" or "Settled by Magnum DI". The badge is left off when the record doesn't say, rather than guessed.
- **Evidence on each card:** every case with an evidence profile shows its level code only, in a small pill ("L3") — its level out of the strongest that kind of evidence can have; screen readers hear the level's name too. Sort cycles Latest first → Oldest first → Strongest evidence (strongest share first, then newest).
- **Threat Case Evidence keeps five facts apart:** Origin (always "Detected on this device"), Evidence (what supplied it: Apollo's check on this device, Apollo's DNS filter, the phone's built-in protection, a connected mailbox, or what this device sent for checking — never ApolloSG's servers, because server processing is not an evidence source), Checked (Higgins Triage on this device or on ApolloSG's servers, TC FlyBy, Magnum DI), Record (summary only, the checks that couldn't be completed, or none unfinished) and Privacy (when ApolloSG's servers worked from, or keep, a privacy-protected version). None is inferred from another.
- **The Evidence tab lists the facts the case established, strongest first** — never the item that was submitted again, and never the verdict. Each fact is listed once, even when Higgins Triage, TC FlyBy and Magnum DI each established it: the first to establish it keeps it in its own words, and a later stage that reached it in its own words is shown as confirming it ("Found by TC FlyBy · Confirmed by Magnum DI"). A later stage repeating the same words is only passing the fact on and confirms nothing. Two statements are one fact only when they report the same check on the same subject, say the same thing, or quote the same words from the material. A fact that points the other way is listed with the rest and marked "Points the other way"; a weak signal is marked "Weak signal". A lookup that found nothing or didn't answer, ApolloSG's knowledge base, a message rule's name and a finding that only states the conclusion are never listed as evidence. A block this device recorded is listed like any other fact, "Found by Apollo on this device". Strongest first means: how firmly it was recorded, how many stages established it and whether it was seen directly; a weak signal, or a fact that points neither way, comes after the rest. The record of who found what is made when the result is committed. A result recorded before that record existed lists its findings in its own words with no "Found by" line — who found what is never guessed.
- **The original, as it arrived, is inert.** The Evidence tab shows the original below the facts, as the item itself, never as a fact about it. Its links and buttons look as they did but do nothing when tapped, nothing in it runs, and nothing it refers to (pictures, fonts, tracking pixels) is fetched. An email is shown from its own HTML part, made inert; its text is shown only when it has no usable HTML part.
- **The evidence source is recorded once,** when the evidence is. Server processing, TC FlyBy, Magnum DI, privacy transformation, syncing and storage never change it, and never change the case's origin. Records written before this rule that named the server as the source are read with their real source (the connected mailbox, or what this device sent), or "Not recorded" when the source was never recorded.
- **Checks that didn't finish** are listed under "Sources ApolloSG used" in this order: what was checked, what happened, why it failed (the reason recorded for it) and what ApolloSG therefore couldn't verify, for example "Final destination — couldn't be verified: The website's address doesn't exist. Couldn't verify where the link finally leads.", "Reputation check — didn't answer: The service timed out. Couldn't verify whether it's listed as a known threat." or "Sender authentication — didn't answer: ApolloSG didn't receive the full email headers." A coverage gap names the evidence its rule needed (page content, redirect chain, domain registration age …), never a vague catch-all, and isn't repeated in generic words when an unfinished check already names it. A block claim without packet proof is listed the same way: "Proof of the block — couldn't be verified: The record doesn't contain a packet drop Apollo observed and matched to this event. Couldn't verify that the connection was actually blocked." The fixed row "Original evidence — not recorded with this case: No reason was recorded." shows only when the record says evidence is missing and nothing records why; it never stands in for a recorded reason, and a known error is never replaced with generic "unavailable" wording. Missing evidence is never evidence of a threat: it only narrows what ApolloSG could verify, and a reason is never invented. The Evidence Pack and Higgins' narration carry the same five facts and the same rows.
- **One way of saying it, everywhere:** Home, the Threats list, alerts, the triage history and the Threat Case read a case's words only through Higgins Luddish: its Higgins Case Briefing, else what Apollo recorded. Internal codes never show. Who sent it, its subject and its text are shown whole, as recorded; only the Home hero's two glanceable lines shorten them.
- **Past cases are judged again when the rules change,** once per rule catalogue version: on ApolloSG's servers from what each Triage record holds, and on the phone from the original kept with the case. No lookup is repeated and no AI is called. A case with an investigation keeps its investigation's result. The earlier judgement stays in the case's history.
- **A summary-only record** (the privacy-protected summary is all the record holds, e.g. after reinstalling) says exactly that — Higgins narrates the kind of check and its result and adds nothing. A summary of an investigation that couldn't decide says "Apollo checked a text message but couldn't settle it", never "found nothing unusual".
- **A record's reasons are what was found, never how it was checked:** an investigation that found nothing specific leaves the reasons empty rather than listing its scope, and a threat kept raised apart from the investigation (a verified block, a listed link) keeps its own reasons and step.
- **Alerts:** Barking and Biting always come through and can't be turned off. Growling and Sniffing alerts can be turned off, and during quiet hours they wait until the quiet time ends; they are never dropped. Family helpers see fixed wording, never the content, unless the person sends them a summary (below).
- **Alert wording:** an alert says what was found in one short line from Higgins and names the item whole (the sender, number, file or website it recorded), with the first concrete thing Apollo recorded about it, for example "The text from +61 448 221 905 has a warning sign: asks for a one-time code. Open ApolloSG to see what I found." Every alert, from the phone or from ApolloSG's server, is worded through Higgins Luddish just before it is sent, and nothing in it is cut short: only the phone's own display limit shortens it. It never carries the full explanation, which stays in the Threat Case unchanged. A case not fully checked never sends an alert. Encoded characters such as `&quot;`, `&amp;` and `&#39;` are decoded once, just before the phone shows the alert. The stored case and evidence are never changed.
- **Send to family** (on every threat): one tap sends linked family in ApolloSG a short summary: the result, what happened, what to do and the website or number involved. "Share another way" opens the phone's share menu (a message, WhatsApp or an email), with the website written as example[.]com so it can't be tapped. The original message, its links and its pictures are never included. ApolloSG sends no email for this. Family can answer with a quick note ("I'm calling you now", "Don't do anything yet" or their own words, up to 140 characters); it shows on that threat on the person's phone and in Family responses.
- **Clear Patrol history** (Settings) hides every record on the phone and on the server. Trusted links are kept.
- **Cases an administrator removed stay removed.** When an administrator removes every case, each device drops its local copies of them, and a device that sends one of those cases again is acknowledged without it being stored, so a removed case can't come back.

---

## General {#general}

### Ask Higgins (the chat screen) {#ask-higgins}

**Job:** the one place to talk to Higgins. A question gets an answer. Something to check goes into the same investigation pipeline as every other check. Ask Higgins never decides whether something is a scam.

**Before anything is sent**
- Passwords, PINs and one-time codes are removed from the message on the phone.
- A message can be up to 4,000 characters.
- A question to Higgins carries only the question and a state-only reading of this phone: protections, permissions, threat counts, alerts and settings. It never carries messages, screenshots, files or secrets.

**Where a message goes (first that applies)**
1. **An investigation is open on screen.** The message goes to that case. Answering Magnum DI's question continues the investigation. Anything else about a finished case is answered on the phone from its record, as in Higgins step 1.
2. **"I want something checked."** The message has a check word *and* a subject word. The matching form opens, and the first subject mentioned wins. Higgins only says what to add, never a verdict. The person still supplies the item, and it goes through the full check.
   - Check words: check, checked, scan, investigate, verify, look at, have a look, "is this / that / it", scam, phishing, suspicious, legit, and safe to open / use / click / pay.
   - Subject words: screenshot, photo, picture, image or QR code; email, inbox or mailbox; message, text, SMS, call, caller, voicemail, number or WhatsApp; link, website, URL, web page, domain or site; app, file, attachment, download, APK or PDF; device, Wi-Fi, internet, network or router.
   - A question that starts "how do I / how can I / how to / where do I / where is" never opens a form: it asks how ApolloSG works, so it goes to step 3.
3. **Where something is, or how to do something** ("where is…", "how do I turn on…", "take me to…", "which screen…") → Higgins on the server, who answers from the ApolloSG User Guide with a tap straight to the screen.
4. **This phone's state:** protection status, device health, website, call, text or app protection, the VPN, permissions, current issues or the last check → answered on the phone from its live reading. Nothing is sent.
5. **Something suspicious, described without the form** ("is this a scam?", "I got a dodgy text", "someone called me…") → Higgins on the server.
6. **About ApolloSG itself:** how ApolloSG works, who Higgins or Magnum DI is, the protections, finding your way around, or what Apollo's states mean → a fixed answer on the phone, with taps to the right screens.
7. **A short message that's still unclear:**
   - Under 60 characters: words about the phone working (working, running, active, on, off, enabled, disabled, status, state, ok, fine, healthy, broken, down) → its protection status, on the phone. Words about a threat (scam, scams, scammed, scammer, scammers, phishing, fraud, fraudulent, suspicious, malware, virus, viruses, hacked, hacker, hackers, compromised, stolen, unsafe, dangerous) → Higgins on the server. Both kinds, or neither, → the next step. Only whole words count, so "on" inside "someone" or "phone" doesn't.
   - Under 40 characters with no question mark → one question back: "Do you mean whether Apollo is protecting your device, or would you like me to investigate something specific?"
8. **Everything else** → Higgins on the server, in the order set out under Higgins above.

**What starts a check from a typed message (on the server)**
- The message has to ask plainly: "is this / could this be" with scam, phishing, fraud, legit, safe, fake, suspicious, malicious or dodgy; or check, investigate, look at, look into, scan, verify, inspect or analyse; or "should I / is it safe to" with click, open, respond, reply, call or trust.
- *And* it has to hold something to check: a link, an email address, a phone number of 8 or more characters, or at least 30 characters of text.
- If either is missing, the message is answered as a question. Missing a check is preferred to starting one by accident.
- A "how do I… / where is…" question ("How do I check a phone number?") is answered as a question from the User Guide. It starts a check only when it holds a real link, email address or phone number.
- Higgins then says the check has started, and offers "View Investigation". If the check can't be started, the message is answered as a question instead.

**The + button: one form per kind of check**
| Form | What the person adds | The question if none is typed |
|---|---|---|
| Screenshot or photo | A screenshot, or a photo of a QR code, letter or screen | Is this a scam? |
| Websites & Links | A link, pasted or shared | Is this website safe? |
| Messages & Calls | A message, number or call details | Is this message a scam? |
| Email & Accounts | An email, pasted or picked from a connected inbox | Is this email legitimate? |
| Apps & Files | An app, file, download or attachment | Is this app safe to use? |
| Device & Internet | Anything noticed (optional) | Check my device and internet connection for security issues. |

- **Pictures.** The phone reads the text in the picture first, and that text goes with it. A picture showing a password, PIN or one-time code isn't sent, and nor is any picture when the phone's text reader isn't available.
- **Size.** A file or picture over 10 MB is refused. An email's attachments over 10 MB in total aren't downloaded; they are listed, with advice to check each one on its own.

**Coming in from elsewhere in ApolloSG**
- **A scam alert:** its title, source, summary and official link go in as the first message, and Higgins answers in the source's own words.
- **A Learn article:** shown in its own words.
- **A Patrol finding, an incident or a Device Check result with no case:** explained on the phone from Apollo's own findings, in fixed wording, with no AI and no investigation. "Ask Apollo to investigate" starts a separate check only when tapped.
- **A result that has a case:** that case opens, and the question goes to it.
- **A screenshot from Check It:** starts a check straight away.

**Taps and offers**
- An answer offers at most 2 screens to tap, and only real Apollo screens.
- Nothing starts a check from an answer until the person taps it.
- **A question nothing trusted answers:** Higgins says ApolloSG's trusted knowledge doesn't cover it (HIG-08). No AI-written answer is ever shown.

**What is kept, and for how long**
- On the phone: the conversation for 1 hour, up to the last 40 messages, in the phone's secure storage.
- On the server: the question and answer for 5 minutes, then only a receipt with no content for 30 days.
- **Clear chat** (the bin icon, after a confirm) deletes the conversation on the phone and on the server, and forgets the person's most-asked questions. It doesn't delete investigations.

**Suggestions**
- There are 20 quick questions. Four show while the chat is empty, and the person's own most-asked questions (asked at least twice) take up to 2 of those places.
- Once a conversation has started, up to 3 of the person's most-asked questions show above the message box while it is empty.
- ApolloSG remembers up to 30 asked questions, skipping any under 6 or over 120 characters.

**When something goes wrong**
- Higgins can't answer: "Higgins couldn't answer right now. No investigation was started.", with Try again.
- **A stopped investigation** (stopped before its Magnum DI call was made, so it can be resubmitted): once it can be resubmitted, one quiet note shows above the conversation. The note goes when the case is resubmitted, answered, removed, dismissed or past its expiry. There is no pop-up anywhere else.

### Scam Alerts and government feeds {#scam-alerts}

**Job:** show the specific scams that official sources are reporting, each explained from the source itself.

**Where alerts come from**
- Recognised government and official cyber-authority sources in Australia, the USA, the UK and the EU, plus Tier 1 pages found for ApolloSG's knowledge base (see ApolloSG's knowledge base).
- Each source is named in full, never as a bare acronym.

**How often feeds are read**
- Each feed is read on its own schedule, between every 15 minutes and once a day (hourly unless set otherwise).
- An item stays for 90 days after it was last seen in its feed.
- In the app, a feed shows as stale when its last successful read is more than 6 hours old, or its latest read failed.
- For staff, a feed is healthy, stale (no successful read in 24 hours) or failing (its latest read failed, with the error in plain words).

**What is shown**
- Only items that have been read and explained. An item that hasn't been read yet is never shown as a scam alert.
- Only specific scam campaigns and emerging patterns. General scam education goes to Learn with Higgins.
- Only recent reports: an item dated more than 60 days ago is left out. An undated item stays, because its age can't be proven.
- The most recent first, up to 50.
- Each alert once: an article its feed lists twice is shown once, and a link a feed wraps in page code is read for the article's real address.
- **Where an alert applies (no AI):** an alert is local to its source's country when its headline or summary names something only that country has: a national agency (FTC, IRS, HMRC, ATO…), a benefit, a payment service, an election, a state or its people. Naming another country as well makes it apply everywhere. Otherwise it applies everywhere.
- **Home is the phone's region setting** (ApolloSG never asks for location). The main list shows alerts that apply everywhere or in the home country. An alert local to another country is hidden there but stays under that country's filter, and the list says how many are hidden.
- An alert local to a country other than Australia is labelled Overseas only and never growls.
- **Growling for an alert:** only for a specific scam rated High or Extreme that has reached Australia, or that may reach Australia and was reported within the last 180 days.

### Cost guardrails at a glance {#cost-guardrails}

- Gate and Higgins Triage: 0 AI calls.
- TC FlyBy: 0 AI calls. One Brave Search request per case, read by fixed rules; a lookup still current from an earlier case is reused, not asked again, and the same lookup already running is waited for, never sent twice.
- Magnum DI: at most 1 Magnum DI call per correlated case, no retry. A case TC FlyBy settles makes none.
- **Daily AI spending limits:** a daily total AI limit of $5.00 (every AI call and paid search), and automatic checks (mailbox monitoring, recovery, advisories, health checks) may use up to $2.00 of it. An admin can change both; the automatic-check limit can't be more than the total. Each paid call's estimated cost is reserved before it is sent, in one atomic step, and settled to the usage the provider reported afterwards. A call whose estimate would go over is refused and nothing is sent. This is an estimated spending guard, not a guaranteed billing ceiling: settling to the reported cost is not checked against the limit again, so a call that costs more than its estimate can take the day's total over the limit by the difference, and every later call that day is refused. When the billing outcome isn't known (a timeout, a dropped connection), the estimate stays held.
- **Usage records:** each AI call and paid search records its model, purpose, time, device, case, job, input, answer, thinking and cached tokens, searches and estimated cost.
- **No repeated processing:** the same evidence on the same device is taken on once (an email seen in two connected accounts, the same check submitted twice), claimed atomically before any work starts. Another device's evidence never matches. Each connected mailbox is read from its own checkpoint, so only newer mail is fetched.
- Higgins and Ask Higgins: 0 AI calls. Plain English and its Fidelity Check: 0 calls.
- Models: Magnum DI calls the one AI provider and model selected in ApolloSG Settings → AI Provider & Model on the admin portal (ApolloSG's default until an admin changes it). Only an approved model that returns the fixed answer shape, reads images sent as evidence and searches the web with sources can be selected, and only when ApolloSG is connected to its provider and the provider's API key is set on the server. ApolloSG is connected to three AI providers; each provider's key is kept only in the server's configuration. API keys are never shown. An investigation keeps the model it started with. A failure is reported as it is: ApolloSG never switches model or provider. Each change records who made it and when, and goes in the admin audit log.

