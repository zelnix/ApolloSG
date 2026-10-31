# Apollo operating rules — as the code enforces them (2026-10)

## Apollo — detects and protects
1. Six states: Checking, Patrolling, Sniffing, Growling, Barking, Biting (`frontend/src/domain/types.ts`).
2. Biting only from a real, fresh, verified block: a packet the active runtime actually observed and dropped. The backend re-derives this itself (`patrol_policy.packet_verified`). Link, email and text checks can go no higher than Barking.
3. Unknown is not unsafe. A setting Apollo couldn't read is never a "change", and "no concern" only covers the checks that completed. Nothing is ever called safe.
4. Gate checks (`services/triage_engine.py`, Tier 1): fixed catalogue rules, zero Gemini calls. Result: no threat / possible threat / limited. Only a possible threat opens an investigation case. Missing evidence is a coverage gap: it can block "no threat", but it never creates a threat and never weakens real threat evidence. Limited results are never cached.
5. Privacy before anything leaves the phone. Passwords and codes are removed on the device (an image showing one isn't sent). Only allow-listed fields are sent (`privacy.ts enforceEgress`). The evidence boundary (`llm_boundary.py`) strips secrets again before every Gemini request.
6. Protection changes report only what changed, never who changed it or why. The "what to do" lines are fixed text.
7. Production never runs simulation. The preview simulator exists only in preview.

## Higgins Triage (inside a case) — prepares, doesn't investigate
1. Runs on its own logic: no network and no AI (`tc_flyby/triage.py`).
2. Extracts every input before TC FlyBy sees it: text, links, the text the phone read from a screenshot, and a document's text layer (`tc_flyby/__init__._material`).
3. Structures what it finds: links, emails, phone numbers, companies and ABNs, brands, payment details, claims, and requests to act.
4. Records anything it couldn't extract as a gap, and never guesses its content. Images are marked "Magnum DI can read this".
5. Plans the checks, each with a narrow factual question about one exact value.
6. A request counts only if it asks the person to send money, codes or details, install something, or give remote access. Negated requests ("we will never ask…") don't count.

## TC FlyBy — fast, low-cost investigation
1. Route, cheapest first: official sources → Apollo KB → one targeted Brave search. No AI call. One search request per case, claimed before it is sent, read by fixed rules: a result counts only if its own words name the exact value. Earlier lookups are reused (7 days found, 1 day nothing found). The search looks facts up; it never judges.
2. Stopping rule: stop as soon as more investigation couldn't change Apollo's finding or Higgins' action. "Unable to determine" is a valid result.
3. It stops early only for a confirmed threat. Every other result waits until the planned checks have run.
4. How the outcome is chosen:
   - confirmed threat;
   - likely scam (a full KB pattern match that nothing contradicts);
   - corroborated impersonation;
   - opening of a known scam;
   - established warning signs (concerning);
   - no scam indicators, only when every check ran over everything and nothing was left unextracted;
   - otherwise unable to determine.
5. KB patterns: a full match needs every defining indicator as a phrase, plus the ask. Impersonation patterns also need a link that isn't the organisation's own. Isolated keywords never match.
6. A name mentioned beside someone else's address needs corroboration. A lookalike address (the name inside the domain) is a warning sign on its own. Bare links follow the same rule.
7. Magnum DI gets only what the deciding test can't settle:
   - reading: an image Triage couldn't extract;
   - reasoning: a request to act through a route nobody verified, with nothing established;
   - relating: findings that contradict each other.
   There is no fixed list.
8. Magnum DI's web search is turned on only when a fact may be missing.

## Magnum DI — deep investigation
1. Runs only when TC FlyBy sends it issues.
2. At most one call per correlated case, to the configured Gemini model, claimed before anything is sent and never retried. A failed call or invalid answer stops the case with its reason and TC FlyBy's findings. No Pro escalation, no tool rounds, no second call to present the answer.
3. Receives the question once, TC FlyBy's brief ("For Magnum DI to settle — only these"), the evidence each issue needs, and anything TC FlyBy didn't examine. There is no system prompt; the response schema carries the shape and the outcome definitions.
4. It can't override what's already established, and it isn't called to move a case between concern outcomes.
5. Validation:
   - findings must cite registered evidence;
   - a concern needs a finding;
   - outcome and assessment must match;
   - "action needed" needs an action and a reason;
   - "complete" only if everything was examined.
   An invalid answer is never replaced with an invented one.
6. Only Magnum DI asks the person a question or requests a fresh device reading.

## Higgins — communicates, explains, guides
1. Never investigates. It may change how something is presented, never what it means (`presenter.py`).
2. Order before any AI is used:
   - a request to check something goes to the pipeline;
   - an existing result, scam alert, Patrol record, phone state or product knowledge is shown as is;
   - the knowledge base is quoted, labelled as general knowledge.
   Only a general scam-safety question that none of these answer reaches Gemini: one call, the question alone, cached.
3. Follow-ups on a finished investigation are answered from its record. No AI, the case is never reopened, and anything new is named as not covered. The answer credits whoever settled it (TC FlyBy or Magnum DI).
4. Strict scope, with a fixed reply for anything off-topic. The phone's live reading is the truth: never contradict it or guess past it, and never invent a concern.
5. Plain Australian English, no internal codes (`scrubMessage`), 2–4 short paragraphs.
6. Every TC FlyBy / Magnum DI result gets a plain-English explanation in Apollo's wording only (`explain/`, no AI), under the
   evidence lock. The Fidelity Check runs before it is shown; failed parts go back to Apollo's wording, and a second FAIL shows
   Apollo's wording only. PASS/FAIL and reasons are in the admin portal.

## Outcomes (one system for all layers — `services/higgins/outcomes.py`)
- No scam indicators found
- Concerning
- Likely scam
- Confirmed scam or threat
- Unable to determine
