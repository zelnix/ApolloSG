# Higgins wording that may say more than the evidence supports (for owner review — NOT changed)

Found during the revision 2 implementation audit (EXPLAIN rules). Owner's choice: "List it for me to review first".
Nothing below has been changed in the code.

1. **TC FlyBy "no scam indicators", link with a verified official domain** — `backend/services/higgins/tc_flyby/report.py` `clear()`:
   "… Nothing Apollo checked raises a concern, so nothing here needs action."
   Rule book: a verified check settles that one check only, never the whole case.
2. **TC FlyBy "no scam indicators", message** — `report.py` `clear()`:
   "Apollo checked the links, numbers, addresses and names in it against official sources and its knowledge base."
   Said every time, even when the material holds none of these, or some weren't checked that way.
3. **TC FlyBy "Concerning", corroborated impersonation** — `report.py` `impersonation_result()`:
   "A genuine {brand} message has no reason to send you to another domain …" and
   "Anything typed into that link goes to whoever runs {place}, not {brand}."
   Stated as fact. Organisations sometimes send people through other services' domains.
4. **TC FlyBy "Concerning", warning signs** — `report.py` `signals_result()`:
   "Apollo's checks established the warning sign(s) above."
   The list above it now also holds weak signals, which aren't warning signs.
5. **TC FlyBy "Unable to determine"** — `report.py` `undetermined()`:
   "Some of what would settle this couldn't be checked …" and "Something ApolloSG couldn't fully check may still be unsafe."
   Also used when every check ran and only weak signals stood in the way, so nothing actually went unchecked.
   (Related: "Nothing it found raises a concern" sits beside the listed weak signals.)
6. **Patrol state "resting" shown as "all clear"** — `backend/services/higgins/presenter.py` `STATE_TEXT` and
   `frontend/src/higgins/issueExplanation.ts` `STATE_LABEL`.
   Rule book: nothing is ever called safe; "no concern" covers only the checks that completed.
7. **Plain English severity line for attention "none"** — `backend/services/higgins/explain/words.py` `SEVERITY`:
   "How serious: nothing needs doing." On a "No scam indicators found" result this can read as an all-clear.
