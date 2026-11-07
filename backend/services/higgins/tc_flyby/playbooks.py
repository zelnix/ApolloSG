"""TC Hawkeye — the Ten Verification Playbooks (PRD v2.3 §7.5, PB-01..PB-10).

Static definitions, transcribed field-for-field from the PRD table (id, title, status, applicable
variant-code ranges, jurisdictions, triggers, inputs, ordered steps, source identifiers, timeout,
fallback behaviour, evidence output, escalation conditions). `playbook_runner.py` is what actually
*executes* a playbook's steps against a real investigation; this module only carries the structure.

Each step also carries a `resolver` key naming which of ApolloSG's own, already-integrated checks can
answer it today (link/company/abn/acn/licence/phone/email/person/impersonation checks, or a KB pattern
match) — per the Phase 1 Capability Review and PRD §8.5 ("a lookup that fails is recorded as
unavailable — never as safe"), a step with no real source behind it (a blockchain explorer, a
government portal, a land registry, a marketplace seller API — none of which ApolloSG has access to)
is honestly marked `unavailable`/`not_applicable` by the runner, never answered by pattern-matching
standing in for genuine verification.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlaybookStep:
    order: int
    description: str
    source_ids: tuple[str, ...]
    resolver: str   # dispatch key for playbook_runner._STEP_RESOLVERS


@dataclass(frozen=True)
class Playbook:
    id: str
    title: str
    purpose: str
    status: str
    variant_ranges: tuple[tuple[int, int], ...]
    jurisdictions: tuple[str, ...]
    triggers: str
    required_inputs: tuple[str, ...]
    optional_inputs: tuple[str, ...]
    steps: tuple[PlaybookStep, ...]
    timeout_ms_per_step: int
    fallback_behaviour: str
    evidence_output_fields: tuple[str, ...]
    escalation_conditions: str

    def wire(self) -> dict:
        return {"id": self.id, "title": self.title, "purpose": self.purpose, "status": self.status,
                "variantRanges": [list(r) for r in self.variant_ranges], "jurisdictions": list(self.jurisdictions),
                "triggers": self.triggers, "requiredInputs": list(self.required_inputs), "optionalInputs": list(self.optional_inputs),
                "steps": [{"order": s.order, "description": s.description, "sourceIds": list(s.source_ids)} for s in self.steps],
                "timeoutMsPerStep": self.timeout_ms_per_step, "fallbackBehaviour": self.fallback_behaviour,
                "evidenceOutputFields": list(self.evidence_output_fields), "escalationConditions": self.escalation_conditions}


PLAYBOOKS: tuple[Playbook, ...] = (
    Playbook(
        id="PB-01", title="Business Identity", purpose="Verify business identity and legitimacy.", status="Active",
        variant_ranges=((126, 275), (576, 725), (826, 925)), jurisdictions=("AU", "CA", "GB", "US", "EU"),
        triggers="Business name, website URL, contact details, registration number.",
        required_inputs=("Business Name",), optional_inputs=("Website URL", "Registration Number", "Contact Email/Phone"),
        steps=(
            PlaybookStep(1, "Search for official business registration databases (e.g., ASIC, Companies House).",
                        ("ASIC (AU)", "Companies House (GB)", "BBB (US)"), "company_registry"),
            PlaybookStep(2, "Verify website domain registration and reputation.", ("DomainTools",), "link_reputation"),
            PlaybookStep(3, "Cross-reference contact details with official directories.", ("Official business registries",), "contact_crossref"),
            PlaybookStep(4, "Check for active trade licences or certifications.", ("Official business registries",), "licence_check"),
            PlaybookStep(5, "Search for public company information and news.", ("LinkedIn",), "unavailable_source"),
        ),
        timeout_ms_per_step=3000,
        fallback_behaviour="Mark step as inconclusive or unavailable; continue to next step; escalate if critical information is missing.",
        evidence_output_fields=("businessRegistrationStatus", "registeredAddress", "directorInformation", "websiteDomainAgeRegistrar",
                                "contactNumberValidation", "licenceStatus"),
        escalation_conditions="If primary sources are unavailable or contradictory, and the investigation is critical.",
    ),
    Playbook(
        id="PB-02", title="Financial Investments", purpose="Verify financial investment claims and associated entities.", status="Active",
        variant_ranges=((276, 425),), jurisdictions=("AU", "CA", "GB", "US", "EU", "SG"),
        triggers="Investment name, company name, website, broker details, claimed returns.",
        required_inputs=("Investment Name", "Company Name"), optional_inputs=("Website URL", "Broker Details", "Claimed Returns"),
        steps=(
            PlaybookStep(1, "Search official financial regulator databases for licensed entities.", ("ASIC (AU)", "FCA (GB)", "SEC (US)", "MAS (SG)"), "licence_check"),
            PlaybookStep(2, "Verify investment product details against prospectuses or official documentation.", ("Official financial regulator databases",), "unavailable_source"),
            PlaybookStep(3, "Check for known scam warnings or blacklists related to the investment.", ("Scam warning sites",), "scam_pattern_match"),
            PlaybookStep(4, "Analyse website for signs of deception (e.g., pressure tactics, unrealistic promises).", ("FINRA",), "link_reputation"),
            PlaybookStep(5, "Verify credentials of individuals if presented as brokers or advisors.", ("Official financial regulator databases",), "person_crossref"),
        ),
        timeout_ms_per_step=4000,
        fallback_behaviour="Mark step as unavailable and continue investigation; degrade to inconclusive if verification fails.",
        evidence_output_fields=("licenceStatus", "authorisedActivities", "registeredEntity", "investmentProductLegitimacy",
                                "scamWarnings", "brokerVerification"),
        escalation_conditions="If unlicensed or suspicious entities are identified, or if claimed returns are highly unrealistic and unverified.",
    ),
    Playbook(
        id="PB-03", title="Cryptocurrency", purpose="Verify cryptocurrency-related claims, addresses, and entities.", status="Active",
        variant_ranges=((276, 425), (726, 825)), jurisdictions=("Global",),
        triggers="Cryptocurrency name, wallet address, exchange name, claim of high returns, transaction ID.",
        required_inputs=("Cryptocurrency Name", "Wallet Address"), optional_inputs=("Exchange Name", "Transaction ID", "Claimed Returns"),
        steps=(
            PlaybookStep(1, "Check wallet address on blockchain explorers for transaction history and patterns.", ("Etherscan", "BscScan"), "unavailable_source"),
            PlaybookStep(2, "Verify the legitimacy of associated cryptocurrency exchanges or platforms.", ("Reputable exchange websites",), "link_reputation"),
            PlaybookStep(3, "Search for known scams or fraudulent tokens associated with the provided details.", ("Scam warning lists",), "scam_pattern_match"),
            PlaybookStep(4, "Analyse website or communications for unrealistic return promises or pressure tactics.", ("CoinMarketCap", "CoinGecko"), "claims_and_urgency"),
            PlaybookStep(5, "Check for security vulnerabilities or red flags related to smart contracts.", ("Reputable exchange websites",), "unavailable_source"),
        ),
        timeout_ms_per_step=3500,
        fallback_behaviour="Mark step as unavailable and continue; degrade to inconclusive if verification fails.",
        evidence_output_fields=("walletTransactionHistory", "exchangeLegitimacy", "tokenProjectReputation",
                                "knownScamAssociations", "smartContractAnalysis"),
        escalation_conditions="If a wallet address is linked to known fraudulent activity, or if the exchange is unverified and high risk.",
    ),
    Playbook(
        id="PB-04", title="Courier & Delivery", purpose="Verify courier and delivery claims, tracking information, and associated fees.", status="Active",
        variant_ranges=((576, 725), (826, 925)), jurisdictions=("AU", "CA", "GB", "US", "EU"),
        triggers="Courier name, tracking number, delivery address, claimed fee, parcel status.",
        required_inputs=("Courier Name", "Tracking Number"), optional_inputs=("Website URL", "Claimed Fee"),
        steps=(
            PlaybookStep(1, "Verify tracking number against official courier tracking systems.", ("Official courier websites (e.g., FedEx, UPS, DHL, Australia Post)",), "unavailable_source"),
            PlaybookStep(2, "Check the legitimacy of the courier company's official website and contact details.", ("National postal services",), "link_reputation"),
            PlaybookStep(3, "Cross-reference delivery status with originating sender if possible.", ("Trusted delivery aggregators",), "unavailable_source"),
            PlaybookStep(4, "Analyse claimed fees for reasonableness and compare with standard courier rates.", ("Official courier websites",), "claims_and_urgency"),
            PlaybookStep(5, "Check for common phishing patterns associated with delivery scams.", ("National postal services",), "scam_pattern_match"),
        ),
        timeout_ms_per_step=2500,
        fallback_behaviour="Mark step as unavailable and continue; mark as not applicable if no tracking number is provided.",
        evidence_output_fields=("trackingNumberValidity", "parcelStatus", "courierLegitimacy", "feeReasonableness", "phishingIndicators"),
        escalation_conditions="If tracking information is fake, the courier is unrecognisable or a known scam, or if payment is requested via an insecure channel.",
    ),
    Playbook(
        id="PB-05", title="Banking & Payments", purpose="Verify banking and payment-related claims, instructions, and entities.", status="Active",
        variant_ranges=((126, 275), (276, 425), (826, 925)), jurisdictions=("AU", "CA", "GB", "US", "EU"),
        triggers="Bank name, account number, payment instruction, transaction ID, alleged security alert.",
        required_inputs=("Bank Name", "Payment Instruction Details"), optional_inputs=("Account Number", "Transaction ID", "Security Alert Details"),
        steps=(
            PlaybookStep(1, "Verify bank's official website and contact details.", ("Official bank websites",), "link_reputation"),
            PlaybookStep(2, "Cross-reference payment instructions with official bank communication channels.", ("Bank fraud departments",), "unavailable_source"),
            PlaybookStep(3, "Check for known bank impersonation scams or fraudulent payment schemes.", ("Known scam alerts from financial institutions",), "scam_pattern_match"),
            PlaybookStep(4, "Analyse transaction details for anomalies or suspicious patterns.", ("Official payment network sites (e.g., SWIFT)",), "unavailable_source"),
            PlaybookStep(5, "If a security alert is claimed, verify official communication channels from the bank.", ("Official bank websites",), "contact_crossref"),
        ),
        timeout_ms_per_step=3500,
        fallback_behaviour="Mark step as unavailable and continue; degrade to inconclusive if verification fails.",
        evidence_output_fields=("bankLegitimacy", "instructionAuthenticity", "transactionLegitimacy", "accountDetailsValidity", "securityAlertVerification"),
        escalation_conditions="If payment instructions lead to suspicious accounts, the bank is impersonated, or if a security alert is confirmed as a phishing attempt.",
    ),
    Playbook(
        id="PB-06", title="Government & Tax", purpose="Verify government and tax-related claims, notices, and entities.", status="Active",
        variant_ranges=((826, 925),), jurisdictions=("AU", "CA", "GB", "US", "EU"),
        triggers="Government agency name, notice type (e.g., tax, fine, grant), reference number, payment amount.",
        required_inputs=("Government Agency Name", "Notice Reference Number"), optional_inputs=("Website URL", "Contact Phone/Email"),
        steps=(
            PlaybookStep(1, "Verify the official government agency website and contact information.", ("Official government agency websites (e.g., ATO, IRS, HMRC)",), "link_reputation"),
            PlaybookStep(2, "Cross-reference notice details with official government portals or known communication methods.", ("Official government portals",), "unavailable_source"),
            PlaybookStep(3, "Check for common impersonation tactics used by government scam actors.", ("National tax authorities",), "scam_pattern_match"),
            PlaybookStep(4, "Verify the legitimacy of any claimed fines, debts, or grants.", ("Department of Justice",), "unavailable_source"),
            PlaybookStep(5, "Search for public records or official announcements related to the notice.", ("Official government portals",), "unavailable_source"),
        ),
        timeout_ms_per_step=4000,
        fallback_behaviour="Mark step as unavailable and continue; escalate if a credible threat is identified.",
        evidence_output_fields=("agencyLegitimacy", "noticeAuthenticity", "referenceNumberValidation", "claimedAmountVerification", "impersonationIndicators"),
        escalation_conditions="If the notice is confirmed as fraudulent, the agency is impersonated, or if an immediate, unverified payment is demanded.",
    ),
    Playbook(
        id="PB-07", title="Employment", purpose="Verify employment offers, task requests, and associated entities.", status="Active",
        variant_ranges=((576, 725),), jurisdictions=("AU", "CA", "GB", "US", "EU"),
        triggers="Company name, job title, recruiter name, website, claimed salary, task description.",
        required_inputs=("Company Name", "Job Title"), optional_inputs=("Recruiter Name", "Website URL", "Claimed Salary"),
        steps=(
            PlaybookStep(1, "Verify the legitimacy of the company and its official website.", ("Company websites",), "company_registry"),
            PlaybookStep(2, "Cross-reference job offer details with the company's official career pages or known recruitment channels.", ("Official job boards",), "unavailable_source"),
            PlaybookStep(3, "Check the recruiter's credentials and affiliation.", ("LinkedIn",), "person_crossref"),
            PlaybookStep(4, "Analyse the offered salary and benefits for reasonableness.", ("Recruitment agency directories",), "claims_and_urgency"),
            PlaybookStep(5, "Investigate any task requests for signs of money mule or phishing activity.", ("Company registration databases",), "scam_pattern_match"),
        ),
        timeout_ms_per_step=3000,
        fallback_behaviour="Mark step as unavailable and continue; degrade to inconclusive if verification fails.",
        evidence_output_fields=("companyLegitimacy", "jobOfferAuthenticity", "recruiterVerification", "salaryBenefitReasonableness", "taskLegitimacy"),
        escalation_conditions="If the company is fake, the job offer is a known scam, or if the tasks involve illegal activities like money laundering.",
    ),
    Playbook(
        id="PB-08", title="Property & Rentals", purpose="Verify property listings, rental agreements, and associated entities.", status="Active",
        variant_ranges=((926, 1000),), jurisdictions=("AU", "CA", "GB", "US", "EU"),
        triggers="Property address, agent name, rental amount, listing website, landlord details.",
        required_inputs=("Property Address", "Rental Amount"), optional_inputs=("Agent Name", "Listing Website URL"),
        steps=(
            PlaybookStep(1, "Verify property ownership and listing details through official property registries.", ("Official property registries",), "unavailable_source"),
            PlaybookStep(2, "Check the legitimacy of the real estate agent or property management company.", ("Estate agent directories",), "person_crossref"),
            PlaybookStep(3, "Analyse rental amount and terms for reasonableness against market rates.", ("Reputable real estate listing sites (e.g., Zillow, Rightmove, Domain)",), "claims_and_urgency"),
            PlaybookStep(4, "Cross-reference listing details with multiple reputable property portals.", ("Reputable real estate listing sites",), "unavailable_source"),
            PlaybookStep(5, "Investigate any requests for upfront payments before viewing or signing agreements.", ("Land registry offices",), "consequential_request"),
        ),
        timeout_ms_per_step=3500,
        fallback_behaviour="Mark step as unavailable and continue; degrade to inconclusive if verification fails.",
        evidence_output_fields=("propertyOwnership", "listingAuthenticity", "agentLandlordLegitimacy", "rentalMarketComparison", "paymentTerms"),
        escalation_conditions="If the property ownership is disputed, the agent is unverified or fraudulent, or if payment is demanded before secure verification.",
    ),
    Playbook(
        id="PB-09", title="Account Security", purpose="Verify account security claims, alerts, and verification processes.", status="Active",
        variant_ranges=((1, 125), (11, 275)), jurisdictions=("AU", "CA", "GB", "US", "EU"),
        triggers="Service name, account ID, security alert type, verification method, username/password.",
        required_inputs=("Service Name", "Security Alert Details"), optional_inputs=("Account ID", "Verification Method"),
        steps=(
            PlaybookStep(1, "Verify the official service provider's website and contact information.", ("Official service provider websites",), "link_reputation"),
            PlaybookStep(2, "Cross-reference security alerts with official communications from the service provider.", ("Company security portals",), "unavailable_source"),
            PlaybookStep(3, "Analyse the requested verification method for known phishing or credential harvesting techniques.", ("Known phishing alert sources",), "scam_pattern_match"),
            PlaybookStep(4, "Check for common account takeover scam patterns.", ("Known phishing alert sources",), "consequential_request"),
            PlaybookStep(5, "If an OTP is involved, verify the legitimacy of the OTP request source.", ("SMS/Email authentication service providers",), "otp_request_check"),
        ),
        timeout_ms_per_step=3000,
        fallback_behaviour="Mark step as unavailable and continue; degrade to inconclusive if verification fails.",
        evidence_output_fields=("serviceProviderLegitimacy", "alertAuthenticity", "verificationMethodLegitimacy", "credentialHarvestingIndicators", "otpLegitimacy"),
        escalation_conditions="If the alert is confirmed as phishing, the verification request is fraudulent, or if credentials are being harvested.",
    ),
    Playbook(
        id="PB-10", title="Retail & Marketplace", purpose="Verify retail and marketplace transactions, product claims, and seller information.", status="Active",
        variant_ranges=((576, 725),), jurisdictions=("AU", "CA", "GB", "US", "EU"),
        triggers="Seller name, product name, order ID, marketplace name, payment method, claimed shipping/delivery.",
        required_inputs=("Seller Name", "Product Name", "Marketplace Name"), optional_inputs=("Order ID", "Website URL"),
        steps=(
            PlaybookStep(1, "Verify the legitimacy of the seller and their profile on the marketplace.", ("Marketplace websites (e.g., Amazon, eBay, Etsy)",), "person_crossref"),
            PlaybookStep(2, "Cross-reference product details and pricing with official manufacturer or retailer information.", ("Manufacturer websites",), "unavailable_source"),
            PlaybookStep(3, "Check seller reviews and reputation on the marketplace and external platforms.", ("Trusted review sites",), "unavailable_source"),
            PlaybookStep(4, "Analyse payment requests for unusual methods or requests outside the marketplace's secure system.", ("Payment processor verification",), "consequential_request"),
            PlaybookStep(5, "Investigate shipping and delivery claims for reasonableness and common scam indicators.", ("Seller profiles",), "scam_pattern_match"),
        ),
        timeout_ms_per_step=3000,
        fallback_behaviour="Mark step as unavailable and continue; degrade to inconclusive if verification fails.",
        evidence_output_fields=("sellerLegitimacy", "productAuthenticity", "marketplaceTransactionSecurity", "reviewCredibility", "shippingDeliveryClaimValidation"),
        escalation_conditions="If the seller is confirmed as fraudulent, the product is fake, payment is requested insecurely, or if there are significant discrepancies in delivery claims.",
    ),
)

BY_ID: dict[str, Playbook] = {p.id: p for p in PLAYBOOKS}


def applicable(variant_code: str | None) -> list[Playbook]:
    """Every playbook whose variant-code range covers this case's taxonomy variant code. Returns
    none when the case has no taxonomy classification (nothing concerning enough was established)."""
    if not variant_code:
        return []
    try:
        code = int(variant_code)
    except (TypeError, ValueError):
        return []
    return [p for p in PLAYBOOKS if any(lo <= code <= hi for lo, hi in p.variant_ranges)]
