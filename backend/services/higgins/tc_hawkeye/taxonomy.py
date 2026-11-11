"""TC Hawkeye — Master Scam Taxonomy (Apollo PRD v2.2 Phase 2: Taxonomy Expansion).

Eight approved master domains, each with its own Operational Variant Code range (001-1000), used
to classify what a case's established scam mechanism actually is — for the Findings Brief's "What
ApolloSG Found" section and to connect Verification Playbooks, Findings Calibration Intelligence
and Higgins Explanation Intelligence back to one consistent classification.

    #  Master domain                                     Variant codes
    1  Account Takeover & Authentication Exploitation     001-125
    2  Brand & Corporate Impersonation                    126-275
    3  Financial, Investment & Cryptocurrency Fraud       276-425
    4  Social Engineering & Relationship Exploitation     426-575
    5  Retail, E-Commerce & Employment                    576-725
    6  Cyber Extortion & Threats                           726-825
    7  Government, Tax & Legal Impersonation               826-925
    8  Real Estate, Rental & Credit Fraud                  926-1000

This extends the approved taxonomy — it never replaces it. Existing KB scam patterns
(services.higgins.tc_flyby.patterns.PATTERNS) and the scoring engine's decisive mechanisms
(services.higgins.tc_flyby.scoring._decisive_mechanism) are mapped into these eight domains as
subcategories; no KB record, identifier or evidence is renamed, removed or restructured by this
classification — it is purely an additional label attached to what was already established.
Phishing, credential theft, tech-support and investment/crypto scams are represented here as
subcategories/mechanisms of the eight domains, not as additional master domains.

Cross-domain relationships: a case carries one primary domain and zero or more secondary domains
when its mechanism spans more than one approved domain (e.g. a bank-impersonation call asking for
an OTP is primarily Account Takeover & Authentication Exploitation, with Brand & Corporate
Impersonation as a secondary domain).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from services.higgins.tc_flyby.finding_rules import IPDMCChecks
from services.higgins.tc_flyby.triage import Plan

MASTER_DOMAINS: tuple[dict, ...] = (
    {"code": 1, "name": "Account Takeover & Authentication Exploitation", "range": [1, 125]},
    {"code": 2, "name": "Brand & Corporate Impersonation", "range": [126, 275]},
    {"code": 3, "name": "Financial, Investment & Cryptocurrency Fraud", "range": [276, 425]},
    {"code": 4, "name": "Social Engineering & Relationship Exploitation", "range": [426, 575]},
    {"code": 5, "name": "Retail, E-Commerce & Employment", "range": [576, 725]},
    {"code": 6, "name": "Cyber Extortion & Threats", "range": [726, 825]},
    {"code": 7, "name": "Government, Tax & Legal Impersonation", "range": [826, 925]},
    {"code": 8, "name": "Real Estate, Rental & Credit Fraud", "range": [926, 1000]},
)
_BY_CODE = {d["code"]: d for d in MASTER_DOMAINS}


def _variant(domain_code: int, offset: int, label: str) -> dict:
    """A code within domain_code's own range — offset 0 is reserved for that domain's generic/
    catch-all classification; named KB patterns and mechanisms start at offset 1."""
    start = _BY_CODE[domain_code]["range"][0]
    code = start + offset
    return {"variantCode": f"{code:03d}", "domainCode": domain_code, "domainName": _BY_CODE[domain_code]["name"], "label": label}


def _domain_ref(code: int) -> dict:
    return {"domainCode": code, "domainName": _BY_CODE[code]["name"]}


# Known KB scam pattern (patterns.PATTERNS "key") -> (primary variant, [secondary domain codes]).
# Phishing/credential-theft/tech-support/investment patterns are deliberately subcategories of the
# eight domains below (Account Takeover, Financial Fraud, Retail/Employment, ...), never master
# domains of their own.
_PATTERN_MAP: dict[str, tuple[dict, list[int]]] = {
    "otp_bypass":            (_variant(1, 1, "OTP or verification-code sharing (account takeover)"), []),
    "bank_code_call":        (_variant(1, 2, "Bank-impersonation call requesting a code, PIN or password"), [2]),
    "remote_access":         (_variant(1, 3, "Remote-access / tech-support device takeover"), [2]),
    "tech_support_call":     (_variant(1, 4, "Tech-support call \u2014 device/account access"), [2]),
    "organisation_phishing": (_variant(1, 6, "Organisation phishing \u2014 login/verification link"), [2]),
    "investment_returns":    (_variant(3, 1, "Guaranteed/high-return investment fraud"), []),
    "investment_mentor_referral": (_variant(3, 4, "Investment fraud via a personal \u201ctrading mentor\u201d or referral"), []),
    "unexpected_money":      (_variant(3, 2, "Unexpected money or prize \u2014 advance-fee fraud"), []),
    "family_new_number":     (_variant(4, 1, "Family-member \u201cnew number\u201d impersonation"), []),
    "romance_grooming":      (_variant(4, 2, "Romance or relationship-grooming scam"), []),
    "job_task":              (_variant(5, 1, "Job or paid-task employment scam"), []),
    "delivery_toll":         (_variant(5, 2, "Parcel delivery or unpaid-toll fee request"), [2]),
    "delivery_call":         (_variant(5, 3, "Delivery/courier fee impersonation call"), [2]),
    "money_mule_recruitment": (_variant(5, 4, "Money-mule recruitment \u2014 receive-and-forward job offer"), [3]),
    "fake_online_store":     (_variant(5, 5, "Fake online store \u2014 steep-discount checkout fraud"), []),
    "government_threat":     (_variant(7, 1, "Government or authority threat"), []),
    "government_call":       (_variant(7, 2, "Government or police impersonation call"), []),
}

# scoring._decisive_mechanism() label prefix -> (primary variant, [secondary domain codes]).
_MECHANISM_MAP: tuple[tuple[str, dict, list[int]], ...] = (
    ("OTP, password or account-credential harvesting",
     _variant(1, 7, "Credential/OTP harvesting through a falsified identity or domain"), [2]),
    ("Credential phishing through a verified deceptive destination",
     _variant(1, 8, "Credential phishing via a confirmed deceptive destination"), [2]),
    ("Wallet or recovery-phrase exploitation",
     _variant(3, 3, "Crypto wallet or recovery-phrase exploitation"), [1]),
    ("Extortion or ransomware demand",
     _variant(6, 1, "Extortion or ransomware demand"), []),
    ("Severe-consequence manipulation",
     _variant(4, 3, "Severe-consequence manipulation \u2014 secrecy, distress or authority-threat coercion"), [6, 7]),
    ("Money-mule recruitment",
     _variant(5, 6, "Money-mule recruitment established directly from the request"), [3]),
)

# consequential_requests "type" (triage._requests) -> generic fallback domain, most decisive first.
_REQUEST_DOMAIN: tuple[tuple[str, int, str], ...] = (
    ("credentials", 1, "Credential harvesting request"),
    ("remote_access", 1, "Remote-access request"),
    ("personal_details", 1, "Personal/identity-document harvesting request"),
    ("gift_cards_crypto", 3, "Gift-card or cryptocurrency payment demand"),
    ("payment_details_change", 3, "Payment-redirection / invoice fraud request"),
    ("payment", 3, "Direct payment or funds-transfer request"),
)


@dataclass
class Classification:
    primary: dict
    secondary: list[dict] = field(default_factory=list)

    def wire(self) -> dict:
        return {"primary": self.primary, "secondaryDomains": self.secondary}


def _secondary_for_impersonation(ipdmc: IPDMCChecks, primary_domain: int, already: list[int]) -> list[dict]:
    """Brand & Corporate Impersonation is tagged as a secondary domain whenever a false identity or
    impersonation was established and isn't already the primary or a listed secondary domain."""
    if primary_domain == 2 or 2 in already:
        return []
    if ipdmc.identity_is_false or ipdmc.has_impersonation:
        return [_domain_ref(2)]
    return []


def classify(plan_: Plan, ipdmc: IPDMCChecks, decisive_mechanism: str | None) -> dict | None:
    """The master domain(s) this case's established mechanism belongs to, or None when nothing
    concerning enough was established to categorise (e.g. a "not a scam" result)."""
    pattern = plan_.pattern
    if pattern and pattern.get("key") in _PATTERN_MAP:
        variant, extra_secondary = _PATTERN_MAP[pattern["key"]]
        secondary = [_domain_ref(c) for c in extra_secondary if c != variant["domainCode"]]
        secondary += _secondary_for_impersonation(ipdmc, variant["domainCode"], extra_secondary)
        return Classification(variant, secondary).wire()

    if decisive_mechanism:
        for prefix, variant, extra_secondary in _MECHANISM_MAP:
            if decisive_mechanism.startswith(prefix):
                secondary = [_domain_ref(c) for c in extra_secondary if c != variant["domainCode"]]
                secondary += _secondary_for_impersonation(ipdmc, variant["domainCode"], extra_secondary)
                return Classification(variant, secondary).wire()

    if ipdmc.consequential_requests:
        present = {r.get("type") for r in ipdmc.consequential_requests}
        for rtype, domain_code, label in _REQUEST_DOMAIN:
            if rtype in present:
                variant = _variant(domain_code, 0, label)
                secondary = _secondary_for_impersonation(ipdmc, domain_code, [])
                return Classification(variant, secondary).wire()

    if ipdmc.identity_is_false or ipdmc.has_impersonation:
        return Classification(_variant(2, 0, "Brand or corporate impersonation"), []).wire()

    return None
