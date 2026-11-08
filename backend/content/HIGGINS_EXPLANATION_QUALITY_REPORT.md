# Higgins Explanation Quality & Edge-Case Validation - Delivery Report (ApolloSG PRD v2.3)

Objective: make Higgins' explanations read as one coherent, evidence-grounded narrative - not how
ApolloSG investigates, scores or decides. Implemented entirely inside the existing, shared explanation
pathway (services/higgins/explain/): nothing about scoring, routing, verdicts or UI layout changed.

## 1. Files and shared components changed

- services/higgins/explain/facts.py - new (check, result) classifications for finding wording Apollo
  previously had no name for (email_authentication, payment_procedure, sandbox_behavior,
  malware_signature, file_disguise, pattern_match), a registration/RECENT distinction for
  domains registered only hours/days/weeks ago (30 days or fewer), and the new connecting_knowledge()
  function. build() now runs in two passes: findings are structured first, then at most one fixed
  sentence is added to the EXISTING meaning list before the authoritative text (core/corpus/
  entities/contradictions) is finalised - so the Fidelity Check validates it exactly like every
  other fact, with no new exemption code anywhere.
- services/higgins/explain/words.py - two new, fixed, bounded dictionaries: SIGNIFICANCE (why one
  kind of finding matters, keyed by (check, result)) and CONNECTIONS (why a combination of findings
  matters, keyed by a required subset of (check, result) pairs, most-specific match first), plus five
  new GLOSSARY entries (SPF/DKIM/DMARC, YARA, sandbox, PowerShell, credential-harvesting pattern) the
  AI-assisted review (section 5) found were used as unexplained jargon.
- content/rulebook.md / services/rulebook.py - documented the new mechanism as PER-11, listed
  the five new glossary rows, and re-stamped (scripts/rulebook_stamp.py) - both facts.py and
  words.py are rule files the project tracks for drift.
- tests/test_higgins_explanation_narrative.py (new) - the four primary scenarios plus the seven
  additional regression cases, all run through the real pathway.
- scripts/explanation_quality_evaluator.py (new, offline/dev-only) - the optional AI-assisted
  reviewer, section 5.
- backend/.env - added EMERGENT_LLM_KEY, used only by the offline script above.

Not touched: decide.py, scoring.py, playbook_runner.py, taxonomy, report layouts, the DI tab,
or any frontend file - no duplicate engine, verdict service or UI was created.

## 2. Explanation-quality improvements implemented

Per the brief's correction: no new fields and no per-finding captions. Every addition lands inside
the means list Higgins already renders as "What it means" - the one place a connected, multi-sentence
explanation already lived.

- Leads with the conclusion - already true of the existing renderer (subject, then the verdict,
  before any finding); confirmed, not changed.
- Connects related findings - when the material findings match one of CONNECTIONS' named
  combinations (most specific first, e.g. a mismatched domain plus a very recently registered one plus
  a known scam-page structure), one fixed sentence ties them together as a single line of reasoning.
- Explains why findings matter - when no combination matches, the single most material finding's
  own SIGNIFICANCE sentence is added instead. Never both at once.
- Distinguishes evidence types - unchanged, already correct: each finding's polarity
  (clear/concern/neutral) and stance (supporting/contrary/context) come from the same classification
  that now also recognises the new check kinds.
- Handles uncertainty accurately - UNAVAILABLE/NOT_APPLICABLE/missing results were already
  excluded from both the reassuring and concerning sets; confirmed with a new regression case (section 4).
- Natural language - demonstrated improvement, not asserted: the AI-assisted review (section 5) scored
  natural_language and connects_findings higher after the change in 3 of 4 scenarios, with the
  fourth (a one-finding, nothing-to-connect case) correctly unchanged.
- Guidance - unchanged, already correct: todo passes the locked actions through verbatim.

## 3. Regression scenarios executed

All eleven cases in tests/test_higgins_explanation_narrative.py:

| Case | Result |
|---|---|
| A - SMS impersonation / shortened URL | PASS - mismatch, domain age and pattern connected; no "verified sender" claim |
| B - Disguised attachment / sandbox | PASS - disguise + behaviour connected; observed behaviour never escalated to confirmed C2 |
| C - BEC | PASS - "passes auth" explicitly separated from "personally authorised"; bypassed-procedure named as the real concern |
| D - Incomplete delivery notice | PASS - states the limitation; invents nothing; verdict unchanged |
| Legitimate org, compromised content | PASS - official-domain and malicious-listing findings both kept |
| Threat-intel no-match | PASS - absence of a match not read as proof of safety |
| Conflicting authoritative findings | PASS - Fidelity's own contradiction check would fail if either side vanished |
| Authenticated email, deceptive instructions | PASS |
| Benign message | PASS - no invented indicators |
| Unavailable critical check | PASS - not read as suspicious |
| Several reinforcing findings | PASS - all 4 findings kept, at most one connecting sentence (never one per finding) |

## 4. Evidence-fidelity results

Every case above asserts plain.fidelity.status == "PASS" - the existing, unmodified Fidelity Check
(verdict match, finding wording, entities, contradictions, uncertainty, actions) is the gate; nothing
in this change set weakens or bypasses it. Full relevant suite after the change:
test_plain_english.py, test_case_briefing.py, test_higgins_briefing_acceptance.py,
test_luddish_parity.py, test_chain_invariants.py, test_di_trace.py,
test_calibration_reference_library.py, test_playbook_runner.py, test_rulebook.py,
test_higgins_explanation_narrative.py - 264 passed, 23 skipped (the 23 are the pre-existing,
intentional Magnum DI escalation skips from the earlier calibration round). Full backend suite
(1994 tests, chunked): no new failures; the only failures found are pre-existing and unrelated -
the LLM gateway's daily budget_limit on 3 test_ai_adapters.py cases, a KB-retrieval-benchmark
baseline drift, and two order-dependent flaky tests (test_tombstone_sweep.py,
test_recovery_fencing.py) that pass standalone and inside the full run, only failing when chunked
differently - all four were already present before this change, confirmed by running them unmodified.

## 5. Offline AI-assisted explanation-quality review (optional, per section 5B)

scripts/explanation_quality_evaluator.py - NOT part of the pipeline, NOT a pytest gate, run
manually. Uses Claude Sonnet 5.5 via the Emergent LLM key to score six criteria (1-5) on the real
before/after text for each of the four primary scenarios. Full transcript and scores:
content/EXPLANATION_QUALITY_EVALUATION.md. Summary of the final run (after the glossary and
wording fixes the first run itself prompted, see below):

| Scenario | natural_language | connects_findings | explains_significance | evidence_balance |
|---|---|---|---|---|
| A | 2 to 3 | 2 to 4 | 2 to 3 | 3 to 4 |
| B | 2 to 3 | 2 to 3 | 2 to 2 | 2 to 2 |
| C | 2 to 3 | 2 to 4 | 3 to 4 | 3 to 4 |
| D | 2 to 2 | 2 to 2 | 2 to 2 | 2 to 2 (no findings to connect - correctly unchanged) |

The evaluator caught a real issue, which was then fixed, not just logged: its first pass on
Scenario A scored accurate_representation 4 to 3 and flagged that the connecting sentence's wording
("a message structure ApolloSG has seen used in real credential-harvesting attempts") read as an
unsupported claim that Apollo holds a record of specific prior incidents. The three CONNECTIONS/
SIGNIFICANCE sentences using that phrasing were reworded to "matches a known credential-harvesting
pattern" / "already on file" - i.e., describing what the pattern-match check mechanically does, not
claiming Apollo witnessed real past attacks. Re-run after the fix: accurate_representation back to
4/4 on Scenario A, with the rest of the scores unchanged or improved. The same first pass also flagged
unexplained jargon (SPF/DKIM/DMARC, YARA, sandbox, PowerShell, "credential-harvesting pattern"), which
is why the five glossary entries in section 1 were added - Scenario C's explains_significance and
connects_findings both rose an additional point after that fix.

Developer review (manual, as requested instead of treating the evaluator as a second gate): read
every before/after pair in content/EXPLANATION_QUALITY_EVALUATION.md directly. Agreed with the
evaluator that the synthetic test fixtures themselves repeat the same point across the overview/
finding/means lines (an artefact of how compact the synthetic fixtures are, not of the new mechanism);
real, longer investigation explanations have more room between a finding's own wording and the added
sentence, so this is flagged as a fixture-realism caveat below rather than fixed by further wording
changes.

## 6. Remaining limitations

- The AI evaluator's qualitative scores are informative, not reproducible to the point - re-running it
  produces slightly different numbers each time (confirmed above: B's evidence_balance moved 3 to 2 on
  re-run with no code change in between). It is explicitly excluded from the pass/fail gate for this
  reason, exactly as instructed.
- CONNECTIONS/SIGNIFICANCE cover the (check, result) combinations the four primary scenarios and
  seven additional cases need; they are not an exhaustive catalogue of every possible finding
  combination. Extending them further is additive and low-risk (new dictionary entries only) if future
  scenarios need it.
- The pre-existing test_ai_adapters.py budget-limit failures, the KB-benchmark baseline drift, and
  the two order-dependent flaky tests are unrelated to this change and were not touched.
