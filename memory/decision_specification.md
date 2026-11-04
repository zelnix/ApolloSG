# ApolloSG Threat Decision Specification

## Root-Cause Analysis: Commense False Positive

### What happened
A legitimate promotional email from Commense (a clothing retailer) was classified as **High Risk** (concerning + impersonation). The email was sent from `commense.com` and mentioned other fashion brands (e.g., Nike) in product descriptions.

### Root cause
The pipeline created impersonation checks for **every brand** mentioned in the text, not just the sender. When the impersonation check for Nike found that `commense.com ≠ nike.com`, it flagged an "unrelated domain" anomaly. Weak third-party signals on `commense.com` (IPQS score, domain age) then "corroborated" this mismatch, escalating the case to "concerning."

Three compounding failures:
1. **No sender identification**: The pipeline didn't distinguish between the sender's brand and brands merely mentioned in the text.
2. **Overly weak corroboration**: Any signal (even "weak" IPQS scores or young domain registration) counted as corroboration for an impersonation finding, even when the domain made no attempt to look like the mentioned brand.
3. **No hypothesis testing**: The pipeline never asked "Is there a legitimate explanation?" — it only accumulated suspicious signals.

### Fix applied
1. **Verified-sender guard** (`decide.py`): When another brand's impersonation check resolves "clear" (the links genuinely belong to that brand), domain mismatches for other brands are excluded — the sender is identified.
2. **Corroboration strength** (`decide.py`): Unrelated domains (those that don't carry the brand's name) now require "concern"-level corroboration from authoritative sources. Lookalike domains still flag on any corroboration.
3. **Four-stage evidence evaluation** (`evidence_evaluation.py`): A new pipeline reviews provisional decisions through relevance gating, deduplication, dual-hypothesis testing, and calibrated risk assessment.
4. **Validation rules** (`validation.py`): Concern outcomes now require at least one medium/high confidence finding. Partial investigations cannot exceed "concerning."

---

## Evidence Admissibility Rules

### What counts as evidence
| Source type | Examples | Role in decision |
|---|---|---|
| **Authoritative** | Google Safe Browsing, ASIC alerts, Apollo blocklist, official scam advisories | Primary evidence. Can independently establish "confirmed_threat." |
| **Deterministic** | Domain registry (RDAP), brand domain classification, check-digit validation (ABN/ACN) | Primary evidence. Can establish domain ownership and factual claims. |
| **Third-party** | IPQS scores, newly-registered domain age, redirects, reputation databases | Supporting context only. Cannot independently establish any concern outcome. |
| **Device/user** | User's question, forwarded email, screenshot | Input material. Basis for investigation, not evidence of threat. |

### What is excluded (with audit trail)
- Impersonation findings for brands that are merely **mentioned** (not the sender)
- Facts from checks that couldn't run (status "unavailable") — gaps, not evidence
- Search results that don't name the actual subject of investigation

---

## Deduplication Rules

Findings are grouped by **correlation key**: `{check_kind}:{registrable_domain}`.

- Multiple signals about the same domain (IPQS + domain age + redirect) form one group
- The strongest signal in each group is the representative
- Only representatives count toward risk assessment
- Distinct domains, URLs, and independent malicious behaviours are never merged

---

## Dual-Hypothesis Evaluation

For each representative finding with a warning signal (concern/anomaly):

| Finding type | Legitimate hypothesis | Malicious hypothesis | Balance |
|---|---|---|---|
| **Decisive authoritative listing** | (none) | Confirmed by authoritative source | `verified_threat` |
| **Authoritative concern** | Rare false positives | Listed by reliable source | `malicious` |
| **Lookalike domain** | (none — actively mimics the brand) | Domain carries the brand's name without authorization | `malicious` |
| **Newly registered domain** | New legitimate business | Scam sites register fresh domains | `ambiguous` |
| **IPQS/reputation score** | Many legit new sites score high | Correlates with scam patterns | `ambiguous` |
| **Redirect (weak)** | URL shortening, email tracking, CDN | Hides final destination | `legitimate` |
| **Unrelated domain for mentioned brand** | Sender is a different entity | Impersonation attempt | `legitimate` (if verified sender exists) |
| **Freemail sender** | Individuals and small businesses | Anonymity for scammers | `ambiguous` |

---

## Decision Precedence

From highest to lowest priority:

1. **Verified malicious evidence** (decisive concern from authoritative source) → `confirmed_threat`
2. **Full scam pattern match** (KB pattern at "full" stage, not contradicted) → `likely_scam`
3. **Corroborated impersonation** (lookalike/shared-service domain + any signal) → `concerning` (unless evidence evaluation advises downgrade)
4. **Opening scam pattern** (KB pattern at "opening" stage) → `concerning`
5. **Warning signals** (concern/anomaly, non-ambiguous or corroborated) → `concerning` (unless evidence evaluation advises downgrade)
6. **All checks clear, complete investigation** → `no_scam_indicators`
7. **Incomplete investigation or unresolved signals** → `unable_to_determine`

### When the evidence evaluation downgrades a provisional concern
A provisional "concerning" outcome (from impersonation or signals) is downgraded to `None` (case continues to Magnum DI) when:
- ALL representative warning findings have a `legitimate` or `ambiguous` hypothesis balance
- NONE have `verified_threat` or `malicious` balance
- No authoritative source confirms a threat

This does NOT dismiss the case — it sends it to Magnum DI for deeper analysis instead of prematurely flagging it.

---

## Decision vs Enforcement Separation

| Layer | Responsibility |
|---|---|
| **Threat Decision Engine** (this spec) | Recommends an outcome based on evidence |
| **Apollo Protection** (existing) | Determines whether an action is technically supported and authorized |
| **TC FlyBy** | Deterministic checks — no AI involved |
| **Magnum DI** | AI-assisted investigation — conclusions are not trusted evidence |
| **Higgins** | Explains the decision in plain English |

An AI-generated conclusion (from Magnum DI) never independently establishes verified evidence. It must be validated against the structured evidence schema.

---

## Uncertainty Handling

When the outcome is `unable_to_determine`:
- Prefer passive handling (don't alarm the user)
- Continue investigation if Magnum DI has unresolved issues
- Never convert uncertainty into a false concern
- Clearly distinguish "we didn't find anything" from "we confirmed it's safe"

---

## Confidence Calibration

| Confidence | Meaning |
|---|---|
| **High** | An authoritative source directly establishes the conclusion |
| **Medium** | Multiple independent signals support the conclusion |
| **Low** | Inferred from context, or based on a single non-authoritative signal |

Confidence and risk level are independent: a high-risk scenario with thin evidence is high risk but low confidence.

---

## Test Coverage

| Test class | Count | What it validates |
|---|---|---|
| `TestCommenseRegression` | 3 | The specific Commense false positive is fixed |
| `TestVerifiedThreats` | 3 | Safe Browsing, scam advisories, and lookalikes are never downgraded |
| `TestDualHypothesis` | 3 | Ambiguous, legitimate, and downgrade scenarios |
| `TestDeduplication` | 2 | Same-domain grouping and cross-domain separation |
| `TestRelevanceGate` | 2 | Unavailable checks excluded, third-party marked as supporting |
| `TestCalibratedDecision` | 3 | No-findings, clear-only, and decisive concern scenarios |
| `TestDecideIntegration` | 2 | Downgrade never applied to confirmed threats or non-concerns |
| **Total** | **18** | All four stages + integration |

---

## Outstanding Risks

1. **Novel scam patterns**: The evaluation relies on known signal types. A novel scam that doesn't match any existing pattern could slip through if it uses legitimate-looking infrastructure.
2. **Adversarial manipulation**: A sophisticated attacker could craft content that passes the relevance gate by avoiding brand mentions while still impersonating.
3. **Third-party data quality**: IPQS and similar services have their own false-positive rates that we cannot control.
4. **Shadow mode**: The evaluation is deployed directly (not in shadow mode) because it only DOWNGRADES provisional concerns — it never UPGRADES and cannot introduce new false negatives for established threats.
