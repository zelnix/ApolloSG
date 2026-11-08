# ApolloSG — Master Scam Taxonomy Coverage Report

Scope: `services/higgins/tc_flyby/taxonomy.py`'s eight approved master domains (001–1000
operational variant codes), expanded from the ~19 named variants already wired in (14 KB patterns +
4 decisive mechanisms + 1 generic impersonation fallback) by adding **4 new, individually-defined,
evidence-backed variants** discovered while closing the calibration gaps — no codes were
manufactured to fill the range, and every existing assignment is untouched.

## How a variant gets its code

Each case is classified by `taxonomy.classify()` in this priority order: (1) a matched KB scam
pattern (`patterns.PATTERNS`), (2) a decisive mechanism established directly from the request/text
(`scoring._decisive_mechanism`), (3) a generic fallback by request type, (4) a bare impersonation
fallback. Offset `0` within a domain's range is always reserved for that domain's generic/catch-all
classification; named patterns and mechanisms start at offset `1`. A case carries one primary domain
and zero or more secondary domains (e.g. a bank-impersonation call asking for an OTP is primarily
domain 1, with domain 2 as secondary).

## Domain 1 — Account Takeover & Authentication Exploitation (001–125)

| Code | Variant | Source |
|---|---|---|
| 002 | OTP or verification-code sharing (account takeover) | KB pattern `otp_bypass` |
| 003 | Bank-impersonation call requesting a code, PIN or password | KB pattern `bank_code_call` (call-only) |
| 004 | Remote-access / tech-support device takeover | KB pattern `remote_access` |
| 005 | Tech-support call — device/account access | KB pattern `tech_support_call` (call-only) |
| 007 | Organisation phishing — login/verification link | KB pattern `organisation_phishing` |
| 008 | Credential/OTP harvesting through a falsified identity or domain | Decisive mechanism |
| 009 | Credential phishing via a confirmed deceptive destination | Decisive mechanism |
| 001 | Credential harvesting / remote-access / personal-details request (generic) | Request-type fallback |
| 006, 010–125 | *reserved, unassigned* | — |

## Domain 2 — Brand & Corporate Impersonation (126–275)

| Code | Variant | Source |
|---|---|---|
| 126 | Brand or corporate impersonation (generic) | Bare impersonation fallback |
| 127–275 | *reserved, unassigned* — every pattern/mechanism above that establishes a false identity already attaches domain 2 as a **secondary** domain automatically (`_secondary_for_impersonation`); no case currently has impersonation as its sole, primary classification without a more specific domain 1/3/4/5/7 mechanism also applying | — |

## Domain 3 — Financial, Investment & Cryptocurrency Fraud (276–425)

| Code | Variant | Source |
|---|---|---|
| 277 | Guaranteed/high-return investment fraud | KB pattern `investment_returns` |
| 278 | Unexpected money or prize — advance-fee fraud | KB pattern `unexpected_money` |
| 279 | Crypto wallet or recovery-phrase exploitation | Decisive mechanism |
| 280 | Investment fraud via a personal "trading mentor" or referral (pig-butchering) | KB pattern `investment_mentor_referral` |
| 276 | Gift-card / crypto payment, invoice-fraud or direct transfer request (generic) | Request-type fallback |
| 281–425 | *reserved, unassigned* | — |

## Domain 4 — Social Engineering & Relationship Exploitation (426–575)

| Code | Variant | Source |
|---|---|---|
| 427 | Family-member "new number" impersonation | KB pattern `family_new_number` |
| 428 | Romance or relationship-grooming scam | KB pattern `romance_grooming` |
| 429 | **Severe-consequence manipulation** — secrecy, distress or authority-threat coercion *(new)* | Decisive mechanism, secondary domains 6 & 7 |
| 426, 430–575 | *reserved, unassigned* | — |

## Domain 5 — Retail, E-Commerce & Employment (576–725)

| Code | Variant | Source |
|---|---|---|
| 577 | Job or paid-task employment scam | KB pattern `job_task` |
| 578 | Parcel delivery or unpaid-toll fee request | KB pattern `delivery_toll` |
| 579 | Delivery/courier fee impersonation call | KB pattern `delivery_call` (call-only) |
| 580 | **Money-mule recruitment — receive-and-forward job offer** *(new)* | KB pattern `money_mule_recruitment`, secondary domain 3 |
| 581 | **Fake online store — steep-discount checkout fraud** *(new)* | KB pattern `fake_online_store` |
| 582 | **Money-mule recruitment established directly from the request** *(new)* | Decisive mechanism (fallback when the full pattern doesn't match but the ask itself is unambiguous), secondary domain 3 |
| 576, 583–725 | *reserved, unassigned* | — |

## Domain 6 — Cyber Extortion & Threats (726–825)

| Code | Variant | Source |
|---|---|---|
| 727 | Extortion or ransomware demand | Decisive mechanism |
| 726, 728–825 | *reserved, unassigned* | — |

## Domain 7 — Government, Tax & Legal Impersonation (826–925)

| Code | Variant | Source |
|---|---|---|
| 827 | Government or authority threat | KB pattern `government_threat` |
| 828 | Government or police impersonation call | KB pattern `government_call` (call-only) |
| 826, 829–925 | *reserved, unassigned* | — |

## Domain 8 — Real Estate, Rental & Credit Fraud (926–1000)

| Code | Variant | Source |
|---|---|---|
| 926–1000 | *reserved, unassigned* — cases 086–090 (rental deposit fraud, property-listing pressure, conveyancing redirection, credit-repair fraud, property-settlement impersonation) have no KB pattern or decisive mechanism of their own yet; they currently escalate to Magnum DI correctly rather than being forced into a domain-8 classification they haven't earned | — |

## What was added this session, and why each is a genuine new mechanism (not a split of an existing one)

1. **Money-mule recruitment** (KB pattern `money_mule_recruitment`, codes 580/582) — an unsolicited
   job offer to *receive* money and forward it on for a commission is the inverse of every existing
   `job_task`-family pattern (which asks the *victim* to pay an upfront fee). It has its own
   Scamwatch category (jobs-and-employment / money-mule warnings) and its own harm model (the victim
   becomes a money-laundering conduit, not just a fee victim) — genuinely distinct, not a duplicate.
2. **Fake online store** (KB pattern `fake_online_store`, code 581) — a steep time-limited discount
   pushing an unfamiliar checkout page is Scamwatch's own distinct "online shopping scams" category,
   separate from delivery/toll fee requests (which impersonate an existing parcel) and from generic
   credential phishing (which impersonates an existing account).
3. **Severe-consequence manipulation** (decisive mechanism, code 429) — an explicit secrecy/isolation
   instruction, an acute personal-danger appeal, or a threat of arrest/prosecution is a distinct,
   independently-identifiable coercion mechanism from ordinary urgency wording (the pre-existing
   `manipulation_behaviour` dimension), and from the four PRD-named critical mechanisms (OTP, wallet,
   extortion, verified deceptive destination) — it's what separates the four `confirmed_scam`
   calibration cases this pass fixed (029, 065, 080, 083) from their textually-similar `suspicious`
   siblings (026, 067), which use only mild urgency wording.
4. **Money-mule recruitment via decisive mechanism** (code 582) — a narrower, text-only fallback of
   #1 above, for a case whose phrasing doesn't complete the full KB pattern's hallmark+ask structure
   but still unambiguously describes receiving and forwarding funds for a commission.

No other codes were added. Domains 2, 6, 7 and 8 remain mostly reserved — Scamwatch doesn't document
as many distinct *mechanisms* in those categories as in 1, 3, 4 and 5, and inventing variants without
a matching detector (KB pattern or decisive-mechanism regex) would fail the "no code-filling" rule.
