# Report: the 7 detection, evidence and display fixes, plus your 2 product rules (1 November 2026)

Proof files: `/app/test_reports/owner_fixes_proof/`. That folder holds the before and after test runs, the full test
runs and 4 screenshots.

## How each fix was proved
- **Before and after:** I took the version saved before this work started and ran this work's tests against it. Then I ran the same tests against the current code.
  - **Server tests:** 8 of the 9 new proof tests fail on the old code. The 9th checks that a real concern still warns, and it should pass on both.
  - **App tests:** 17 of 75 tests fail on the old code. All 84 pass on the current code.
  - Logs: `backend_before_HEAD.log`, `backend_after.log`, `frontend_before_HEAD.log`, `frontend_after.log`.
- **Full test runs on the current code:**
  - App: 1,321 of 1,321 pass, with no type errors and no lint errors.
  - Server: 1,621 pass. 2 fail, and both failures are older than this work (see "Not changed").
- **Screenshots from the preview app:** I put sample cases on a fresh preview device using Apollo's real investigation filing code. The screenshots are in the proof folder.
- **No paid calls:** no paid AI or search calls were made.
- **Testing agent:** not run, as you chose.

## The 7 fixes

### 1. Notifications reworded outside Apollo's plain-English wording
- **Before:** the app and the server put an alert's text straight into the notification. Neither went through Higgins Luddish, Apollo's shared plain-English wording.
- **After:** every alert goes through Higgins Luddish just before it is sent, on both the phone and the server.
  - A shared word list and a matching test keep the phone and server wording the same.
  - Alerts now name the first real finding, for example: "Higgins: The text from +61 448 221 905 has a warning sign: asks for a one-time code. Open ApolloSG to see what I found."
  - A reason that starts with a name keeps its capital ("…looks like a scam: PhishTank lists this exact address.").
- **Proof:** `test_notification_text.py`, `test_luddish_parity.py`, `notificationText.test.ts`, `luddishShared.test.ts`.

### 2. Home showed vague lines instead of the finding
- **Before:** Home could say "detected as a possible threat", "flagged for a closer look", "flagged by Apollo" or just "Be careful."
- **After:** Home names the first real thing Apollo recorded, for example: "Text message: "Your parcel is waiting, pay…" from +61 448 221 905, asks for a one-time code."
  - **If nothing specific was recorded:** Home says what the result means instead ("looks like a scam", "has a warning sign").
  - **If the next step is too long for Home:** Home says "See Higgins' steps in the case." The step is never cut short.
- **Found and fixed while checking:**
  - Home could show how a case was checked as if it were the finding, for example "Link: paypa1-secure.top, submitted message." Investigation records no longer list how they checked something as a reason.
  - "PhishTank" was shown as "phishTank". Names now keep their capitals.
- **Proof:**
  - Tests: `homeHeroBrief.test.ts`, `homeAttention.test.ts`, and `test_a_record_never_gives_how_it_was_checked_as_its_reason`.
  - Screenshots: `proof_home_text.jpeg` and `proof_home_link.jpeg`.
  - A text search of Home found no "possible threat", no "Be careful." and no "submitted message".

### 3. Investigations that couldn't decide turned into warnings (your rule 1(a))
- **Before:** an investigation that couldn't decide was shown as Growling, or as "ears up" when the case had ended. It sent an alert.
  - It could also lower a threat found another way, such as a link on a threat list, from Barking to Growling.
- **After:** it is filed as **Not fully checked**.
  - It is closed, sends no alert, and says "Nothing found to act on. This isn't confirmation that it's safe."
  - What couldn't be confirmed is kept in the case.
  - It never lowers a threat found another way (a verified block or a link on a threat list). That threat keeps its state, its reason and its step.
  - The server's privacy summary of such a case now says "Apollo checked a text message but couldn't settle it", never "found nothing unusual".
- **Proof:**
  - Server tests: `test_an_inconclusive_investigation_is_filed_as_not_fully_checked_with_no_alert` and `test_an_inconclusive_investigation_never_lowers_a_threat_list_match`. Both failed on the old code: "growling" where "resting" was expected, and "growling" where "barking" was expected.
  - More server tests: `test_an_investigation_ended_without_deciding_is_not_fully_checked`, `test_a_concerning_investigation_still_warns_and_alerts` and `test_the_privacy_summary_of_an_undecided_investigation_never_says_nothing_unusual`.
  - Screenshots: `proof_inconclusive_case.jpeg` (Verdict: Not fully checked) and `proof_threats_final.jpeg`.

### 4. Fixed cut-off points shortening text
- **Before:** text was cut at fixed points:
  - notifications at 65, 178 and 42 characters
  - Send to family at 400 and 300
  - investigation records at 160, 400 and 600
  - TC FlyBy quotes at 120 to 900
  - request quotes at 120 and 240
- **After:** none of these cuts remain.
  - Only the phone's own notification limit, and the two short lines at the top of Home, shorten anything.
  - Text sent to family and saved records keep the full text, within much higher limits.
- **Proof:** `familySummary.test.ts`, `notificationText.test.ts` ("long identifiers are kept whole, never cut short") and `test_present_push_…_without_cutting…`.

### 5. Negatives confused the request reader
- **Before:** a "not" near a request could cancel it. "Do not delay, send me your password" was missed.
- **After:**
  - Only a negative that actually applies to the request cancels it. These are still caught:
    - "Do not delay, send the payment today"
    - "Don't worry, just reply with the code"
    - "Don't share it with anyone else, but send me your password now"
  - These are still not treated as requests:
    - "We will never ask you to send money or your PIN"
    - "Never, under any circumstances, share your password"
  - The phone, the server and TC FlyBy's pattern matching all use the same rule.
- **Proof:** `test_request_reading.py` (4 new real requests and 3 new safe sentences) and `requestSignals.test.ts`. 4 of these failed on the old code.

### 6. Re-checks reopened closed cases
- **Before:** when past cases were re-checked under new rules, a case you had closed could become open again. A late investigation answer could also reopen a case you had handled.
- **After:**
  - A case that is closed, handled or trusted stays closed. Only its wording changes.
  - Phones and the server follow the same rule.
- **Proof:** `test_a_rejudge_never_reopens_a_closed_triage_record`, `test_an_investigation_answer_never_reopens_a_record_the_person_handled` and `triageRejudge.test.ts`. All failed on the old code.

### 7. Exact web-address matching was too broad
- **Before:**
  - A listed page with no "?" part also matched the same page with any "?" part.
  - Google Safe Browsing's answer counted for any address that merely contained the website's name, such as `evil.example.com.attacker.net`.
- **After:**
  - A listed page matches only that exact address, including what comes after "?".
  - Safe Browsing's answer counts only for the exact address checked, or the website's home page.
  - Saved answers from the old matching are cleared once, on the next start.
- **Proof:** `test_threat_feeds.py` and `test_safe_browsing_counts_only_for_the_exact_address`.

## Your rule 2(a), as corrected by your later rule: only the server's copies are deleted after 24 hours
- **On the server:** the text of a message kept with a record or case is deleted 24 hours after it was kept, and only once the phone has confirmed it saved a complete copy. If the phone is offline, the server waits.
  - The clean-up runs about every 20 seconds as part of the server's regular maintenance.
  - Who sent it, the subject and the website stay. What Apollo found stays.
- **On the phone:** nothing is deleted after 24 hours. Your device's evidence (the original text, headers, .eml files and pictures) stays until you delete it.
  - This corrects the first version of this report. That version said the phone also deleted its copies after 24 hours, which went against your rule. The phone-side deletion has since been removed.
  - The message itself in Gmail or Messages is never touched.
- **Proof:** `test_held_copies_older_than_24_hours_are_deleted_and_identifiers_kept`, `test_device_pickup.py`, `evidenceRetention.test.ts` and `heldCopies.test.ts`. The `triageRejudge.test.ts` test "an original kept on the phone for more than 24 hours is still there" shows the phone keeps its copy.

## Also fixed (you approved this)
- **"Handled" label:** a case you handled showed "No threat" on a phone that only had the server's copy. It now shows "Handled". A case closed with nothing found still shows "No threat".
- **Proof:** `phase2Authoritative.test.ts` and `proof_threats_final.jpeg`.

## The old name "Teddy"
- **Checked:** the app's code and screens, the server's code, the rule book and all 116 database collections. Nothing still says Teddy.
- **Two places keep the old name on purpose:**
  - the one-time rename step that updates old records when the server starts
  - the phone's reading of old saved results, so they still show as TC FlyBy's

## Not changed
- **"moneysmart" source name:** one scam alert still names its source as "moneysmart". You chose not to fix this.
- **2 old server tests still fail.** Neither was caused by this work:
  - One expects at least 2,932 records in the preview database. Most were deleted in the 29 October clean-up.
  - The other is the "moneysmart" source name above.
- **Server-only cases after the app syncs:** in the preview, a case the phone only received from the server later shows the server's short privacy summary. It also did this before this work, and the wording of that summary is now correct.
- **Phones need a new build:** an installed phone confirms its saved copies only after you make a new build. Until then, the server keeps its copies.

## Work since the last publish
Your last publish was most likely before 14:59 UTC on 29 October. Production had the case-delete tool then, but not the Screens page. I can't see the publish history, so everything below may still need publishing:
1. **Admin → Screens:** every screen at phone and tablet size, with zip download (29 Oct).
2. **Production delete:** all cases and Patrol records were deleted on production (29 Oct, 15:01 UTC).
3. **GitHub check fix:** fixed the "Native dependency singleton guard" check, so no preview sample ID ends up in production builds (30 Oct).
4. **Threat Domain List:** a list with 0 entries is now accepted, and the Gates no longer wait on it (30 Oct). This needs a new Android build.
5. **Clean-install test script:** written and shown in chat only (30 Oct).
6. **AI cost and names:** the AI cost limits were checked, Teddy was renamed TC FlyBy everywhere, and the Brave key was moved into secure storage (31 Oct).
7. **The first 8 detection, evidence and display fixes, plus the re-check of past cases** (31 Oct to 1 Nov). You rejected that work's completion, so this session did it again.
8. **This session (1 Nov):**
   - finished the 7 fixes and your 2 rules above
   - fixed the extra problems found while checking
   - fixed the "Handled" label
   - updated the rule book
   - added 12 new server tests and 6 new app tests

## What you need to do
- **Publish** to get all of this onto the live app.
  - On its first start, the live server re-checks past cases under the new rules. A closed case keeps its alert level, its status and when it was closed. Only its findings change.
  - It also clears answers saved under the old web-address matching, then starts deleting the server's copies 24 hours after they were made, once the phone has confirmed it saved its own.
- **Make a new build** for the phone side. This covers the phone saving and confirming its copies, and the Threat Domain List change. There is no 24-hour deletion on the phone.
