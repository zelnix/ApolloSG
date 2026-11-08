# Higgins Explanation Quality Evaluation (offline, dev-only)

Model: `anthropic/claude-sonnet-5-5` via the Emergent LLM key. Not part of the production pipeline; does not gate pytest; informs manual review only.

## Scenario A - SMS impersonation and shortened URLs

### Before
```
This is likely a scam. This claims to be from Australia Post, but the link goes to au-post-tracking.cc, which isn't Australia Post's domain. Don't use the link.

What was found:
- The message claims to be from Australia Post.
- The shortened link expands to au-post-tracking.cc, which isn't Australia Post's domain (auspost.com.au).
- au-post-tracking.cc was registered 12 hours ago.
- The investigation identified a credential-harvesting pattern.

What it means:
The message claims to be from Australia Post, but the link doesn't go to Australia Post's own domain.

Still unresolved:
- Apollo can't confirm who actually sent this.

What to do:
- Don't open au-post-tracking.cc and don't enter anything on it.
- Contact Australia Post using the number on their official website.
```
**Scores (before):** {"natural_language": 2, "connects_findings": 2, "explains_significance": 2, "evidence_balance": 3, "avoids_mechanical_repetition": 2, "accurate_representation": 4}

### After
```
This is likely a scam. This claims to be from Australia Post, but the link goes to au-post-tracking.cc, which isn't Australia Post's domain. Don't use the link.

What was found:
- The message claims to be from Australia Post.
- The shortened link expands to au-post-tracking.cc, which isn't Australia Post's domain (auspost.com.au).
- au-post-tracking.cc was registered 12 hours ago.
- The investigation identified a credential-harvesting pattern.

What it means:
The message claims to be from Australia Post, but the link doesn't go to Australia Post's own domain.
Together, these point the same way: an address that only carries the organisation's name, a destination set up shortly before this message was sent, and a message structure that matches a known credential-harvesting pattern. On their own, none of these proves intent; together, they fit a page built to collect logins, not a genuine mistake.

Still unresolved:
- Apollo can't confirm who actually sent this.

What to do:
- Don't open au-post-tracking.cc and don't enter anything on it.
- Contact Australia Post using the number on their official website.
```
**Scores (after):** {"natural_language": 3, "connects_findings": 4, "explains_significance": 3, "evidence_balance": 4, "avoids_mechanical_repetition": 2, "accurate_representation": 4}

**Strengths (after):** ["Clear, actionable advice: don't open the link, and contact Australia Post via its official website.", "Honest caveat that no single item proves intent, plus the unresolved sender.", "Synthesis sentence ties three findings into one picture.", "Includes the real domain (auspost.com.au) for comparison."]
**Weaknesses (after):** ["Heavy repetition of the Australia Post / wrong domain point.", "Jargon ('credential-harvesting pattern') is unexplained.", "Does not say why a 12-hour-old domain or a shortened link is suspicious.", "Rigid template headings and bullets make it feel mechanical.", "Slight inference beyond the findings ('set up shortly before this message was sent', 'page built to collect logins')."]
**Suggested wording (after):** ["Open with: 'This looks like a scam. The text says it's from Australia Post, but the link actually leads to au-post-tracking.cc, not auspost.com.au.'", "Replace 'credential-harvesting pattern' with 'the same pattern used by fake pages designed to steal usernames and passwords'.", "Explain the age: 'The site was registered only 12 hours ago, which is unusual for a real postal service and common for throwaway scam sites.'", "Delete the repeated opening sentence of 'What it means' and begin with the 'Taken together' reasoning.", "Say 'Apollo can't tell who actually sent this message, so treat it as suspicious rather than proven.'"]

## Scenario B - Suspicious password-protected attachment

### Before
```
This is a scam. This file is disguised as a PDF but is really a program, and it behaves like malware when run. Delete it.

What was found:
- The archive is a password-protected ZIP.
- The extracted filename ends in ".pdf.exe".
- The file produced suspicious YARA matches.
- Sandbox execution launches PowerShell and attempts an external connection.

What it means:
The apparent PDF is actually a program, and it behaves like malware once run.

What to do:
- Delete the attachment without opening it.
```
**Scores (before):** {"natural_language": 2, "connects_findings": 2, "explains_significance": 2, "evidence_balance": 2, "avoids_mechanical_repetition": 2, "accurate_representation": 4}

### After
```
This is a scam. This file is disguised as a PDF but is really a program, and it behaves like malware when run. Delete it.

What was found:
- The archive is a password-protected ZIP.
- The extracted filename ends in ".pdf.exe".
- The file produced suspicious YARA matches.
- Sandbox execution launches PowerShell and attempts an external connection.

What it means:
The apparent PDF is actually a program, and it behaves like malware once run.
Together, a file disguised as a document and a program that then tried to run further commands and reach outside the device once opened point the same way: the disguise exists to get a harmful program run.

What to do:
- Delete the attachment without opening it.
```
**Scores (after):** {"natural_language": 3, "connects_findings": 3, "explains_significance": 2, "evidence_balance": 2, "avoids_mechanical_repetition": 2, "accurate_representation": 4}

**Strengths (after):** ["Clear, decisive verdict and action up front", "The 'Together...' sentence explains that the disguise exists to get a harmful program run", "Findings are listed without invented details", "The advice is simple and actionable"]
**Weaknesses (after):** ["The opening and 'What it means' repeat the same claim in nearly the same words", "The password-protected ZIP and YARA matches are listed but never explained or connected", "Jargon (YARA, sandbox, PowerShell) goes unexplained for a non-technical reader", "No uncertainty or confidence level is given", "The format reads like a checklist rather than a person explaining"]
**Suggested wording (after):** ["Replace the repeated sentence in 'What it means' with an explanation of the double extension: 'The name ends in .pdf.exe, so the real file type is .exe, a program, and .pdf is only there to make it look like a document.'", "Explain the password protection: 'Password-protected archives are often used because they stop email security tools from looking inside.'", "Give plain-language glosses: 'A sandbox is a safe test environment; when the file ran there, it started PowerShell, a Windows tool that can run commands, and tried to contact something outside the computer.'", "Describe YARA as 'security pattern checks that flagged the file as resembling known malicious files', and say it supports the picture rather than proving it on its own", "Merge 'Delete it' and 'Delete the attachment without opening it' into one closing instruction"]

## Scenario C - Business Email Compromise

### Before
```
This is likely a scam. This message passes authentication but asks for an urgent wire transfer that bypasses normal approval. Verify independently before paying.

What was found:
- SPF, DKIM and DMARC all pass for this message.
- The sender appears to be a company executive.
- The message requests an urgent wire transfer.
- The payment instructions bypass the established company procedure.

What it means:
Passing authentication doesn't establish that the executive personally sent or authorised this request.

What to do:
- Confirm the request by phone, using a number you already have on file — not one from this message.
```
**Scores (before):** {"natural_language": 2, "connects_findings": 2, "explains_significance": 3, "evidence_balance": 3, "avoids_mechanical_repetition": 3, "accurate_representation": 4}

### After
```
This is likely a scam. This message passes authentication but asks for an urgent wire transfer that bypasses normal approval. Verify independently before paying.

What was found:
- SPF, DKIM and DMARC all pass for this message.
- The sender appears to be a company executive.
- The message requests an urgent wire transfer.
- The payment instructions bypass the established company procedure.

What it means:
Passing authentication doesn't establish that the executive personally sent or authorised this request.
Passing authentication only confirms the message's technical path, so on its own it doesn't resolve the more telling sign here: payment instructions that skip the organisation's normal approval steps.

What to do:
- Confirm the request by phone, using a number you already have on file — not one from this message.
```
**Scores (after):** {"natural_language": 3, "connects_findings": 4, "explains_significance": 4, "evidence_balance": 4, "avoids_mechanical_repetition": 3, "accurate_representation": 4}

**Strengths (after):** ["Honestly states that passing authentication is not reassurance", "Gives a concrete, safe action: call a number already on file, not one from the message", "Hedged verdict ('likely') and a clear structure", "Points to the procedure bypass as the key red flag"]
**Weaknesses (after):** ["Repeats the 'passing authentication' point several times", "SPF/DKIM/DMARC are unexplained jargon", "Findings are listed without being tied together in a narrative", "Urgency and impersonation of authority are not explained as common pressure tactics", "Templated headings make it read like a checklist"]
**Suggested wording (after):** ["Replace 'SPF, DKIM and DMARC all pass' with 'The email's technical sender checks (SPF, DKIM and DMARC) all passed, meaning it came from a properly set-up mail system.'", "Merge the repeated sentences into one: 'Those checks only show how the message was delivered, not whether the executive actually wrote or approved it. The bigger warning sign is that it asks you to skip the usual approval steps.'", "Add a link between findings: 'Combined with the urgency and the apparent seniority of the sender, bypassing approval is a typical way of pressuring someone into paying before anyone can check.'", "Trim the opening summary so it does not restate the later explanation, e.g. 'This looks like a scam: an urgent wire request that skips normal approval.'"]

## Scenario D - Incomplete delivery notification

### Before
```
This is unlikely a scam. There isn't enough information in this short message to reach a reliable conclusion.

What was found:
- The message is a short delivery notification with no extractable link.

What it means:
There isn't enough information here to check anything meaningful.

Still unresolved:
- Apollo couldn't find a link, sender information or any other identifying detail to check.
```
**Scores (before):** {"natural_language": 2, "connects_findings": 2, "explains_significance": 2, "evidence_balance": 2, "avoids_mechanical_repetition": 2, "accurate_representation": 3}

### After
```
This is unlikely a scam. There isn't enough information in this short message to reach a reliable conclusion.

What was found:
- The message is a short delivery notification with no extractable link.

What it means:
There isn't enough information here to check anything meaningful.

Still unresolved:
- Apollo couldn't find a link, sender information or any other identifying detail to check.
```
**Scores (after):** {"natural_language": 2, "connects_findings": 2, "explains_significance": 2, "evidence_balance": 2, "avoids_mechanical_repetition": 2, "accurate_representation": 3}

**Strengths (after):** ["Short and easy to scan.", "Honestly says the message is too thin to analyse.", "Names what is missing (link, sender, identifying detail)."]
**Weaknesses (after):** ["The verdict and the \"not enough information\" statement seem to contradict each other without explanation.", "It repeats the same insufficiency point several times.", "It does not explain why the missing details matter.", "The headers and bullets make it read like a template.", "It gives no practical next step and no reason why the message is rated low-risk."]
**Suggested wording (after):** ["Replace the opening with something like: \"This message doesn't show clear signs of a scam, but it's also too short to say much either way.\"", "Add a reason: \"Normally we'd check where a link leads and who sent it; with neither present, there's nothing to test.\"", "Replace \"no extractable link\" with \"no link we could look at\".", "Merge the \"What it means\" and \"Still unresolved\" sections into one so the same point is not made three times.", "Make it clear that the lower risk rating reflects the absence of red flags, not positive proof that the message is safe."]
