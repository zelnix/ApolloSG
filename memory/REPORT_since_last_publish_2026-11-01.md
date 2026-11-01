# Detailed report: all work since the last production publish (written 1 November 2026)

## 1. When the last publish was
I couldn't see your publish history, so I checked the live app (threat-patrol-1.emergent.host) for features from different days.

| Feature | Added | On the live app? |
|---|---|---|
| Case-delete tool | 29 Oct, 08:55 UTC | Yes (it was used there at 15:01 UTC on 29 Oct) |
| Admin → Screens page | 29 Oct, 14:59 UTC | **Yes**: the page and its upload links answer |
| Threat Domain List wording on the server's check page | 30 Oct, 01:49 UTC | **No**: the live server still says "Bundle v3 generated with 0 rules" |
| Admin → AI spending limits | 31 Oct, 04:40 UTC | **No**: the live server answers "Not Found" |

**So the last publish was after 15:01 UTC on 29 October and before 01:49 UTC on 30 October.** Everything below came after it and is not on the live app yet.

The one exception is item 2.1, a small app-only change from 01:10 UTC on 30 October. It may have gone out in that publish, and it can't be checked from outside.

Times are UTC. "Server" means it goes live when you Publish. "Phone build" means it also needs a new iOS/Android build.

## 2. Work since the last publish, in order

### 2.1 GitHub build check fixed (30 Oct, 01:10). App. May already be live.
- **Problem:** the GitHub check "Native dependency singleton guard" failed. A preview-only sample case ID (`preview-mock-threat-001`) was written into the production app code.
- **Fix:**
  - That ID now exists only in the preview's sample data.
  - Production builds get an empty list instead.
  - No preview content reaches the live app.
- **Checked:**
  - The production build check found no preview content.
  - The preview check found all 9 expected sample markers.
  - The protected Android files are unchanged.
  - All 1,231 app tests passed at the time.

### 2.2 Threat Domain List accepts 0 entries (30 Oct, 01:49). Server, app and phone build.
**Zero entries:**
- A fresh install now accepts a Threat Domain List with 0 entries, and protection keeps starting.
- No placeholder websites were added to fill the list.
- Accepting the list doesn't count as "Protected". That still needs proof that protection is actually running.

**The Gates no longer wait on the list:**
- Private DNS, block records and website-lookup threat reports carry on without it.
- A list problem now shows only on website protection. It no longer appears as "permission needed" or "was on but stopped".

**Private DNS advice:**
- If Android reports Automatic but the network can't encrypt lookups, Apollo confirms the setting, explains the network and says nothing needs changing.
- A setting Apollo couldn't read no longer turns into "set it to Automatic".

**Diagnostics:**
- The server's check page now says "Threat Domain List v9 generated with 0 Threat Domain Entries" and has a new "Threat Domain Entries" check.
- A current list with 0 entries passes everywhere.
- The support screen uses the Threat Domain List name.

**Wording:** every new explanation is written in Higgins Luddish. "Threat Domain List" and "Threat Domain Entry" were added to the Luddish dictionary.

**Tests:**
- 9 new native tests: zero-entry, populated, invalid signature, missing signature, expired, future-dated, rollback, version conflict and malformed entry.
- A clean-install test with 0 entries.
- 6 server tests and the app tests passed (1,284 at the time).

**Needs:** Publish for the server's check page, and a new Android build for the phone part. The 2 Android runtime changes couldn't be compiled in this workspace.

### 2.3 Clean-install test script and rule book update (30 Oct, 03:23). Server.
- A written test for a fresh install with a 0-entry list. As you chose, it was given in the chat only.
- The rule book gained 2 rules that were already in the code:
  - **Repeat Caller Alert:** a repeat call from a blocked or risky number raises an alert, without delaying Android's screening.
  - **Removed cases stay removed:** cases an administrator removed are dropped from every phone. A phone that sends one back is acknowledged but it isn't stored.
- Test data for web-address checks was added for the native tests. The rule book was re-stamped.

### 2.4 AI cost changes (31 Oct, 04:40). Server.
These are the 7 cost changes from your cost review, plus what makes them work.

1. **TC FlyBy uses no AI.**
   - It runs official sources, then Apollo's knowledge base, then at most one Brave search per case.
   - The search is claimed for the case before it's sent, so no retry, job or restart can send a second one.
   - Results are read by fixed rules. A result counts only if its own words name the exact value.
   - An earlier lookup is reused: something found counts for 7 days, "nothing found" for 1 day.
   - If the same lookup is already running for another case, Apollo waits for it and reuses its answer.
   - Lookups about the message itself (a phrase or a person's name) are never saved or reused.
2. **Magnum DI is limited.**
   - It makes at most 1 AI call per case, claimed before it is sent, and never retries.
   - If the call fails or its answer fails Apollo's checks, the case stops and says why. What TC FlyBy found is kept.
   - Only a case that stopped before its call can be submitted again.
   - Follow-up questions are answered from the case's locked findings, with no AI.
3. **Email-sending services settle nothing on their own.** These are click-tracking services such as Mailchimp, SendGrid and HubSpot.
   - A link through one is never treated as a sender/link mismatch.
   - On its own, it never makes an email a threat and never sends it to Magnum DI.
   - It never proves an email is genuine either.
4. **No repeated work for the same thing.**
   - The same email or the same check on the same device is taken on only once. This covers one email in 2 connected mailboxes, or a check submitted twice.
   - The second time opens the existing case.
   - Another device's evidence never matches yours.
5. **Daily spending limits.**
   - $5.00 a day in total for all AI calls and paid searches.
   - Automatic checks (mailbox monitoring, recovery, advisories, health checks) may use up to $2.00 of that.
   - Each call's estimated cost is reserved before it's sent, in one step that concurrent calls can't get around. A call whose estimate would go over is refused and nothing is sent.
   - **This is an estimated spending guard, not a guaranteed billing ceiling.** After a call, its reservation is replaced by the cost the provider reported, with no second check against the limit. If a call costs more than its estimate, the day's total can go over the limit by the difference. The estimate assumes 3 characters per input token, a fixed allowance for each picture or audio part, and 5 model searches, and a provider can bill more than that. Once the total is over the limit, every further call is refused until the next day or until the limit is raised.
   - An admin can change both limits on the new **Admin → AI budget** setting.
6. **Full usage records.** Each AI call and paid search records:
   - the model, purpose, time, device, case and job
   - the tokens used (input, answer, thinking and cached)
   - the searches made and the estimated cost
7. **Mailbox reading only fetches new mail.** Each connected mailbox keeps its own place and only newer mail is fetched. Mail paused by the spending limit is read again later.

**Wording updated to match:**
- The "How Apollo checks" screen now says Magnum DI makes at most 1 call and never retries, and that TC FlyBy uses no AI.
- The admin cost report no longer has a "retry" column. Any case with more than 1 Magnum DI call is flagged as over the limit.
- The rule book matches.

**Checked:**
- 1,547 server tests passed. 2 failed: one was fixed, and the other is the old preview-data check (see section 4).
- All 1,240 app tests passed.
- No paid calls were made.

### 2.5 "Teddy" renamed to "TC FlyBy" everywhere (31 Oct, 04:40). Server and app.
- **What was renamed:** file and folder names, internal names, saved labels, cost records, admin figures and screen labels.
- **Your existing data:** updated automatically when the server started. In preview this moved 146 cases, 120 evidence items, 1,741 usage records and 1 Magnum DI record.
- **On the live app:** this runs by itself the first time the server starts after you Publish.
- **Kept as recorded:** the locked step-by-step history of each investigation can't be edited, so it keeps the old name.
- **Old results on phones:** results already saved on phones still show as TC FlyBy.
- **Removed:** an old, unused store of saved search results.
- **Checked today:** no code, screen, rule book entry or database record still says Teddy.

### 2.6 Brave Search key in secure storage (31 Oct). Server.
- Your Brave Search key is saved in secure storage for preview and live. It isn't in any project file.
- The live server uses it after you Publish.
- No real search has been made with it yet.
- As you chose, it's the same key that was pasted in the chat earlier.

### 2.7 The first 8 detection, evidence and display fixes, plus the re-check of past cases (31 Oct to 1 Nov, 03:22). Server and app.
1. **Requests are read sentence by sentence.** Words like "password" or "code" alone no longer count as a request. These are not requests:
   - a code being delivered
   - an account notice
   - advice like "we will never ask for your PIN"
   - general talk about passwords

   A plain "log in" request counts only when something suspicious backs it up.
2. **Triage reads the whole message.**
   - It reads the full text (no longer just the first 300 characters), the reply-to address, and each link's shown text and real destination.
   - Sender checks are taken only from the record added when the email arrived.
   - Apollo's own notes are never treated as evidence.
3. **Senders and links are read correctly.**
   - Apollo works out who the email says it's from: the sender name, how it introduces itself, and its sign-off. A brand that's only mentioned isn't treated as the sender.
   - Each link is classed as the organisation's own site, its country site, a lookalike, a shared service or unrelated.
4. **A first warning can be cleared.** If official sources confirm every link, number and address is the organisation's own, the warning is dropped before the result is locked. A note explains why.
5. **Checks that couldn't run are no longer threats.** They show as "Not fully checked", are filed as handled and send no alert.
6. **Same wording everywhere.** Home, Threats, the Threat Case screen, notifications and Send to family use the same plain words.
7. **Details kept whole.** The full sender, subject and preview are saved. Each finding quotes the sentence it's based on.
8. **Threat lists match exact pages.** Only a listing that names the whole website covers the whole website.

**Re-check of past cases:**
- It ran once in preview:
  - 6 past results re-judged
  - 17,827 threat-list entries updated to exact addresses
  - 21 old lookup results and 20 old check results cleared
- Cases with a full investigation kept their result. Only the wording changed.

**Your review:** you found 7 problems still left and 2 rules not yet met, so you rejected this as finished. That led to 2.8.

### 2.8 The 7 remaining flaws, your 2 rules and the extra fixes (1 Nov, this session). Server, app and phone build.
Full detail and proof: `/app/memory/REPORT_2026-11-01_detection_display_fixes.md`.

**The 7 fixes:**
1. Every notification, from the phone or the server, now goes through Higgins Luddish and names the real finding.
2. Home names the first real finding. It never says "possible threat" or "Be careful", or gives how something was checked as the reason.
3. An investigation that can't decide is "Not fully checked", with no alert. It never lowers a threat Apollo found another way.
4. No more fixed cut-off points in text.
5. A "not" cancels a request only when it really applies to that request.
6. Nothing reopens a case you closed or handled. (Corrected 1 Nov: the server's re-check kept the status and closing time, but it still changed the record's alert level. A case you had handled could then look like one Apollo closed itself. Now the whole closure stays exactly as it was: the alert level, the status and the time it was closed. Only the findings and their wording are updated. This applies on the server and on the phone.)
7. A threat-list or Google Safe Browsing match counts only for the exact address.

**Your 2 rules:**
- **1(a):** checks that couldn't decide never alert and never hide another threat.
- **2(a), as corrected by your later rule:**
  - ApolloSG's server copies are deleted 24 hours after they were made, and only once the phone has confirmed it saved a complete copy of its own.
  - Your device's evidence (the original text, headers, .eml files and pictures) stays until you delete it.
  - There is no 24-hour deletion on the phone.

**Also fixed:**
- "PhishTank" lost its capital letter.
- Undecided cases were summarised as "found nothing unusual".
- Handled cases showed "No threat". You approved this fix.

**Proof:**
- Before and after tests: the proof tests fail on the old code and pass now.
- 4 screenshots.
- All 1,321 app tests passed at the time. 1,621 server tests passed and 2 failed, both older than this work. The current counts are in section 5.

## 3. What happens on the live app when you Publish
These steps run by themselves, once, when the live server first starts:
1. Records saved under the name "Teddy" move to the TC FlyBy names.
2. Past cases are re-checked under the current rules. A case you closed or handled keeps its alert level, its status and when it was closed. Only its findings and their wording are updated.
3. Threat-list entries are updated to exact addresses. Old saved lookups from the old matching are cleared.
4. The daily spending limits switch on: $5 in total, with $2 for automatic checks. They are an estimated guard, as described in 2.4. The rule against repeated work switches on too.
5. The 24-hour deletion of the server's copies starts, checking about every 20 seconds. A copy is deleted only after the phone has confirmed it saved its own.

**For the phone side, you also need a new build.** This covers:
- the phone saving, checking and confirming its copy of each case
- the Threat Domain List changes (2.2)

Until phones have the new build, the server keeps its copies. There is no 24-hour deletion on the phone.

## 4. Not done, or still open
- **"moneysmart" source name:** one government scam alert still names its source "moneysmart". You chose not to fix this.
- **1 old server test fails:** the "moneysmart" name above. (The preview-data test that needed records from before the 29 October clean-up now re-runs the migration without saving and passes.)
- **Never tried for real:** the Brave key and the new spending limits haven't been used with a paid call yet.
- **Not compiled here:** the Threat Domain List's phone-side Android changes. The next Android build will compile them.
- **Testing agent:** not run on any of this work, as you chose.

## 5. Corrections after your code review (1 November)
**What you reviewed:** you checked commit e294425 on GitHub main, made at 03:26 UTC. The work below came after it and isn't on GitHub yet. To review it there, save to GitHub first.

| Your finding | Status now |
|---|---|
| Phone copies deleted after 24 hours | **Removed from this report.** The phone has no 24-hour deletion. Server copies are deleted 24 hours after they were made, and only once the phone has confirmed it saved its own. Your device's evidence stays until you delete it. |
| A re-check can reopen closed cases | **Fixed on the server and the phone.** The re-check now reads each record's alert level, status and closing time, and never changes them on a closed record. Only the findings and their wording change. A case you handled stays handled. Proof: `test_a_rejudge_never_reopens_a_closed_triage_record` and 2 tests in `triageRejudge.test.ts`. |
| Spending limits can't be overspent | **Reworded.** It is an estimated spending guard, not a guaranteed billing ceiling (see 2.4). The rule book and the code's own description now say the same. |
| Missing source headers: an incomplete copy wins, and a copy is saved only once | **Fixed.** A copy is no longer saved only once: headers that arrive later fill in what is missing. Every screen now reads a case's copies under all of its keys as one copy. An incomplete copy under one key can no longer hide headers saved under another. The first copy's own text and time stay exactly as they were. Proof: `evidenceRetention.test.ts`. |

**Tests now, in this workspace:**
- **App:** 1,291 of 1,291 pass.
  - This is fewer than the 1,321 reported earlier because the tests for the phone's 24-hour deletion were removed along with that deletion.
  - In your environment, 6 test files failed to load. Those tests use ApolloSG's native build plugins, which need `@expo/config-plugins`. That package comes with the app's installed dependencies.
- **Server:** 1,628 pass. 1 fails: the "moneysmart" source name you chose not to fix.

**Not verified here:** native compilation of the Threat Domain List, live secrets, paid calls, and production deployment history.
