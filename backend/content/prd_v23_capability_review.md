# ApolloSG PRD v2.3 — Phase 1: Capability Review & Implementation Gap Analysis

**Date:** 2026-11-07 · **Reviewer:** Engineering (automated code review against PRD v2.3 text) ·
**Method:** every PRD v2.3 section below was checked directly against the current backend code and
test suite (`cd /app/backend && python -m pytest -q` — 1898 passed at time of review). No code was
changed to produce this document.

Legend: ✅ Done and matches the PRD exactly · 🟡 Partially done / exists under a different name ·
❌ Not implemented.

## §2 — Four-Tier Findings & Six-Dimension Scoring

| PRD requirement | Status | Where |
|---|---|---|
| §2.1 Four exact Findings tiers (85–100 Scam / 60–84 Likely / 25–59 Unlikely / 0–24 Not) | ✅ | `scoring.classify_finding()` — boundaries `24→not_scam, 25→unlikely_scam, 59→unlikely_scam, 60→likely_scam, 84→likely_scam, 85→scam` are asserted in the function's own docstring contract |
| §2.2 Six weighted dimensions (25/20/20/15/10/10 = 100) | ✅ | `scoring.DIMENSION_MAXIMA = {scam_mechanism:25, requested_action:20, identity_destination:20, manipulation_behaviour:15, knowledge_base:10, evidence_corroboration:10}`, one function per dimension |
| §2.3 Benign baseline, legitimacy credits, decisive floors, 0–100 clamp | ✅ | `BENIGN_BASELINE=28`, `_legitimacy_credit()`, `DECISIVE_FLOOR=85`, `IMPERSONATION_FLOOR=65`, clamped in `score_plan()` |
| §2.4 Ordinary benign message → 28/100 Unlikely a Scam | ✅ | Exact value already in code as `BENIGN_BASELINE` |
| §2.5 Legitimacy credits 20–30 pts for positive evidence | ✅ | `_legitimacy_credit()` |
| §2.6 Decisive mechanism floor ≥85 (OTP, phishing, seed phrase, wallet-drain, extortion) | ✅ | `_decisive_mechanism()` + `_OTP_ASK` / `_WALLET_ASK` / `_EXTORTION_ASK` regexes |
| §2.7 Reference scoring cases (50 scenarios with target scores) | ❌ | No reference library exists. `content/kb_benchmark_cases.json` is a **different**, pre-existing system (KB *article* retrieval benchmark, not scam-case scoring calibration) |
| §2.8 Boundary tests at 24/25, 59/60, 84/85; versioned scoring config | 🟡 | The boundaries are correct and documented, but no test file asserts them at the exact edge values yet, and there is no `SCORING_VERSION` constant recorded on the breakdown |

**Verdict:** the scoring *engine* already fully matches the PRD. What's missing is entirely the
**calibration layer** around it (§2.7/§2.8, PRD Phase 4's remaining scope) — the 50-case reference
library, boundary tests, and a versioned, reproducible scoring record.

## §3 — Master Scam Taxonomy

| PRD requirement | Status | Where |
|---|---|---|
| 8 master domains, exact names, exact 001–1000 ranges | ✅ | `tc_flyby/taxonomy.py::MASTER_DOMAINS` (added this session, cross-checked line for line against §3.1) |
| Domain 1–8 subcategory lists (§3.2–§3.9) | 🟡 | Covered where a KB pattern or decisive mechanism already exists (OTP/2FA, phishing, impersonation, investment, "Hi Mum", job/task, extortion placeholder). **Not yet covered**: SIM swaps, session hijacking, OAuth abuse (domain 1); executive impersonation, invoice redirection, supplier-payment substitution (domain 2); pig butchering, Ponzi, fake token sales (domain 3); romance fraud, wrong-number grooming, charity/celebrity impersonation (domain 4); money mules, fake escrow, ticket fraud (domain 5); ransomware, hacking claims, DDoS threats (domain 6); traffic fines, grants, licence notices (domain 7); fake listings, title fraud, mortgage scams (domain 8) — these are exactly the gaps Phase 3's §3.10 variant catalogue and new detection work needs to fill |
| §3.10 Operational Variant Records (full metadata: indicators, channels, jurisdictions, playbook refs, calibration refs, explanation refs, provenance, version) | 🟡 | `taxonomy.py`'s variants currently carry only `variantCode`/`domainCode`/`domainName`/`label` — no jurisdiction, playbook/calibration/explanation cross-references, or version field yet |
| §3.11 Cross-domain correlation (primary + secondary domains) | ✅ | `taxonomy.classify()` returns `primary` + `secondaryDomains` |

**Verdict:** the taxonomy *shape* is done and correct. The variant *catalogue* is sparse (13 KB
patterns mapped vs. ~90+ named subcategories in the PRD) and variant records lack the richer
metadata (jurisdiction/playbook/calibration/explanation links) Phase 3 needs to attach.

## §4 — TC Hawkeye Technical & Behavioural Detection Framework (D01–D14)

No code currently names these as "D01"–"D14". Mapping each to what exists:

| # | Mechanism | Status | Where |
|---|---|---|---|
| D01 | Structural Asymmetry (identity/structure/channel/action inconsistency) | 🟡 | `brand_domains.classify()` (identity vs. domain), but no unified "structural asymmetry" check spanning channel+action together |
| D02 | Channel Redirection (to private chat/phone/payment channel) | 🟡 | `triage.REQUESTS` has `call_back`/`reply`/`open_link`, but nothing explicitly scores "moved off the original channel" |
| D03 | Domain Deception (lookalikes, subdomain abuse, shorteners, redirects) | ✅ | `brand_domains._deobfuscate()` (homoglyphs/punycode/l33t), `official.py` redirect-chain + tracking-domain detection |
| D04 | Payment Rail Manipulation (unusual destination, crypto, gift cards, substitution) | ✅ | `triage.CONSEQUENTIAL` = payment / gift_cards_crypto / payment_details_change |
| D05 | Urgency & Time Pressure | ✅ | `plan.entities.urgency`, scored in `_manipulation_behaviour()` |
| D06 | Authority Impersonation (bank/government/employer) | ✅ | `official.py` brand + government checks, `patterns.py` bank/government patterns |
| D07 | Emotional Manipulation (fear/affection/guilt/sympathy/secrecy) | 🟡 | `family_new_number` pattern only; romance/charity/celebrity/guilt mechanisms not covered |
| D08 | Credential Extraction (password/OTP/recovery code/seed phrase) | ✅ | `_OTP_ASK`/`_WALLET_ASK`, `otp_bypass`/`bank_code_call` patterns |
| D09 | Remote Access Manipulation | ✅ | `remote_access`/`tech_support_call` patterns |
| D10 | Transaction Inconsistency (vs. authenticated transaction context) | 🟡 | Email SPF/DKIM/DMARC evidence exists (`evidence_evaluation.py`), but nothing compares a *claim* against an *actual authenticated transaction* record |
| D11 | Investment Deception (unrealistic returns, fake endorsements, withdrawal barriers) | 🟡 | `investment_returns` pattern covers returns/pressure; "fake endorsements" and "withdrawal barriers" aren't separately detected |
| D12 | Relationship Grooming (trust-building toward exploitation) | ❌ | Not implemented — this is the romance-scam / "wrong-number" gap |
| D13 | Identity Mismatch (claimed vs. independently verified identity) | ✅ | `brand_domains.classify()` + impersonation check |
| D14 | Verification Contradiction (material conflicts with authoritative evidence) | 🟡 | `PatternMatch.contradicted` exists per-pattern; no general-purpose cross-check against authoritative evidence independent of a KB pattern match |

**Verdict:** 6 of 14 are solid, 6 are partial (same underlying signal exists but isn't named/scored
as this specific mechanism), 1 (D12 Relationship Grooming) is a true gap, and the connecting idea —
a *named*, independently-testable function per mechanism, each feeding a specific evidence item —
doesn't exist. This is Phase 3's main engineering task.

### §4.5 Structured per-investigation output

🟡 — `report.compose()` already records mechanisms (via `decisiveMechanism`), variants (via the new
`taxonomy`), entities, dimension breakdown, rating, label, and evidence references. It does **not**
yet record which of D01–D14 fired, which playbooks ran, or per-check confidence/completeness beyond
what `uncertainties`/uncertainty text already carries in prose form.

## §5 — Expanded Reference Investigation Library

❌ **Does not exist.** No case matches the 50 scenarios in §5.2 (IDs 001–105). This is the entirety
of Phase 4's remaining scope, approved to be built next as **synthetic, clearly-labelled fixtures**
(per your direction) rather than real sanitised user data, since none is available.

## §6 — Higgins Findings Brief

| PRD requirement | Status | Where |
|---|---|---|
| Exact six headers, exact order | ✅ | `findings_brief.build()` (added this session) — `finding, findingsRating, whatApolloFound, whyThisMatters, whatWasVerified, recommendedAction` |
| §6.2 One exact approved label | ✅ | `outcomes.label()` |
| §6.3 0–100 rating + access to dimension breakdown | ✅ | `result["findingsRatingBreakdown"]` carried alongside |
| §6.4 Actual organisations/senders/domains/numbers/requests/mechanisms/contradictions | 🟡 | Currently lists finding *text* (already mentions these entities in prose); doesn't yet expose them as separate structured fields |
| §6.5 Why This Matters via explanation intelligence | 🟡 | Pulls the existing "What it means" prose block — there's no separate, versioned "Higgins Explanation Intelligence" KB record behind it yet (§7.7 gap, below) |
| §6.6 What Was Verified incl. inconclusive/unavailable + limitations | ✅ | `scope` + `uncertainties` |
| §6.7 One primary action + necessary extra steps | ✅ | `recommendedAction.primary` / `.additional` |
| §6.8 Progressive disclosure | ✅ | `DetailedFindingsBrief.tsx`, collapsed by default |

**Verdict:** structurally complete and matches the PRD. The gap is §6.4/§6.5's dependency on the
not-yet-built Explanation Intelligence KB (§7.7) — today the text comes from the plain-English
renderer's prose, not from dedicated, versioned explanation records.

## §7 — ApolloSG Knowledge Base Intelligence

| PRD requirement | Status | Where |
|---|---|---|
| §7.2 Existing capabilities (patterns, sources, official orgs, indicators, provenance, caching) | ✅ | `apollo_kb.py`, `knowledge.py`, `kb_sources.py`, `patterns.py`, `brand_domains.py` |
| §7.5 Ten Verification Playbooks (PB-01…PB-10) | ❌ | No playbook infrastructure exists at all — confirmed via full-repo search |
| §7.6 Findings Calibration Intelligence (reference cases, metrics, held-out validation) | ❌ | Doesn't exist — this is the Phase 4 scope approved next |
| §7.7 Higgins Explanation Intelligence (versioned explanation records) | ❌ | The `explain/` module (`briefing.py`, `facts.py`, `fidelity.py`, `render.py`, `words.py`) produces plain-English text deterministically from locked facts, but there's no separate *KB record* per mechanism (ID, variant refs, plain description, warning signs, recovery steps, jurisdiction, provenance) — today the wording lives in code, not in versioned KB data |

## §8 — Performance & Operational Requirements

| PRD requirement | Status | Where |
|---|---|---|
| §8.1 Deterministic-first (regex/patterns before contextual analysis) | ✅ | `patterns.py`/`official.py` run before any Magnum DI escalation — already the architecture |
| §8.2 Efficient, targeted KB retrieval | ✅ | `knowledge.py`/`apollo_kb.py` retrieve by key, not full scans |
| §8.3 Parallel checks, timeouts, dedup, reuse | 🟡 | `LOOKUP_SECONDS=8.0` timeout + 2-retry IPQS handling exist; no explicit cross-check dedup/reuse layer |
| §8.4 Record completeness (completed/inconclusive/unavailable/N-A/not performed) | 🟡 | `uncertainties` captures this in prose; not a structured per-check status enum yet |
| §8.5 Reliability (fallback per playbook, escalate on need) | ✅ (for existing checks) | "A lookup that fails is recorded as unavailable — never as safe" (`official.py` docstring); `decide.py`'s technical-issue halt (built previous session) |
| §8.6 Observability | ✅ | existing logging throughout `services/higgins/` |

## §9 — Privacy, Security & Evidence Integrity

| PRD requirement | Status | Where |
|---|---|---|
| §9.1 Evidence provenance (submitted / extracted / external / KB / inference / finding / explanation, kept distinct) | ✅ | `fact()`'s `class` field (`live_evidence` vs. KB `context`), `source_ref()` |
| §9.2 Evidence Lock (reproducible, authoritative, locked result) | ✅ (concept exists under "Fidelity Check" + "Evidence Lock" naming in the DI tab/rulebook) | `rulebook.md` §Fidelity Check; the locked `result` dict is what Higgins' plain English is checked against |
| §9.3 Source integrity (source/time/validation/confidence/freshness/version) | 🟡 | `source_ref()` has publisher/url/authority/basis/checkedAt — no explicit freshness/version field |
| §9.4 User privacy (on-device protections, pre-upload redaction) | ✅ | exists elsewhere in the app (outside TC Hawkeye's scope) |
| §9.5 Safe evidence presentation (inert links) | 🟡 | not verified in this review — outside backend scope, frontend viewer behaviour |
| §9.6 Historical reproducibility (retain scoring config/KB refs/evidence per historical Finding) | ❌ | no version stamp is stored on a Finding's scoring/taxonomy config today |

## Summary: what's genuinely new work

1. **Phase 4 remaining (next, per your approved sequence):** 50-case synthetic reference library,
   boundary tests at 24/25·59/60·84/85, a calibration test runner that runs real cases through the
   real pipeline and reports actual-vs-expected — **no scoring-engine changes**, since §2's engine
   already matches the PRD.
2. **Phase 3 (after Phase 4):** name and test the 8 partial/missing D01–D14 mechanisms explicitly
   (especially D12 Relationship Grooming — the romance-scam gap); build the 10 Verification
   Playbooks' *structure* (steps/sources/timeouts/fallback/escalation), wired to real sources where
   ApolloSG already has them (brand/domain/pattern/KB data), with any step needing an unavailable
   external source (e.g. ASIC business-licence lookup, government registries) explicitly recorded as
   `unavailable` — never answered by pattern-matching standing in for real verification.
3. **Phase 6 (last):** a full Validation & Acceptance Testing report once 3 and 4 exist.
4. **Smaller, cross-cutting gaps** to pick up opportunistically while doing the above: version stamps
   on scoring/taxonomy/explanation records (§9.6/§12.3), richer Operational Variant Records
   (§3.10's jurisdiction/playbook/calibration/explanation cross-references), and a dedicated
   Explanation Intelligence KB layer (§7.7) behind the Findings Brief's prose.

**Acceptance check (§11 Phase 1):** every enhancement area above now has a documented integration
point (which file/module it extends) and nothing here required a code change to establish.
