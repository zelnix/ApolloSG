# Report: what the phone keeps, and how the server deletes its copies (1 November 2026)

Proof files are in `/app/test_reports/evidence_retention_proof/`. That folder holds both full test runs and 3 screenshots.

## Your 5 rules
1. **The phone keeps everything until you delete it.** This covers the message text, the headers and the original files. The phone no longer deletes them after 24 hours.
2. **The 24-hour rule applies only to the server's copies.** The server keeps its copy until the phone confirms it has saved its own. If the phone is offline, the server waits.
3. **The phone checks its copy before it confirms.** It saves the result, the original and the headers, then reads them back from its own storage. It confirms only if nothing is missing. If anything is missing, the server keeps its copy and the phone tries again every minute and each time the app is opened.
4. **Headers that arrive later fill in gaps.** They fill in only what the phone's record was missing. What the phone first recorded is never overwritten.
5. **Emails look the same on Home and in the Threat Case.** Both show the sender, subject and received date the case recorded. If a part was never recorded, it says "Not provided", never "Not captured". An email always gets the email icon, even when the server filed it as a text message.

## Tests
- **App:** 1,289 of 1,289 tests pass. The 12 new tests are in `evidenceRetention.test.ts` and `emailRecord.test.ts`.
- **Server:** 1,628 pass and 1 fails. The 6 new tests are in `test_device_pickup.py`.
  - **The failure:** this is the "moneysmart" scam alert source name, which you chose not to fix.
  - **Fixed in this session:** an old migration test failed because it expected at least 2,932 records in the preview database. Most of those were deleted in the 29 October clean-up. The test now runs the migration again without saving anything, and checks that it reports no errors and creates no duplicate records.

## Screenshots (preview app)
I set up a fresh preview device and filed 2 sample email cases on it. Both used Apollo's real investigation filing code. One case was deliberately filed by the server as "text", with no sender, subject or date.
- `proof_home_email_not_provided.jpeg` — **Home:** "Email: Subject not provided, sender not provided… Received: Not provided." It has an email icon, not a text-message icon.
- `proof_case_email_not_provided.jpeg` — **Threat Case:** "From: Not provided / Subject: Not provided / Received: Not provided", with the email icon.
- `proof_case_email_recorded.jpeg` — **Threat Case** for an email with a recorded sender and subject: "From: PayID Support <alerts@payid-secure.top> / Subject: Payment on hold / Received: Not provided". Home shows the same sender and subject.

I removed the sample devices afterwards.

## Before you rely on it
- **Production:** the server-side rules reach production when you next Publish.
- **Installed phones:** they need a new build. Until then, an installed phone does not send the confirmation, so the server keeps its copies. Nothing is lost.
- **Testing agent:** not run, as you chose. No paid AI or search calls were made.
