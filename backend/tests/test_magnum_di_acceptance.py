"""Magnum DI Universal Investigation — Acceptance Tests

Tests the investigation pipeline, evidence contracts, coordinator prompt structure
and gate integration across all 10 acceptance scenarios from the specification.
No live Gemini calls — verifies that the investigation infrastructure correctly
processes diverse source types and produces well-structured investigation cases.

Run: cd /app/backend && python -m pytest tests/test_magnum_di_acceptance.py -v --timeout=60
"""
import json
import uuid
from typing import Optional

import httpx
import inspect

import pytest

from services.higgins.contracts import Gate
from services.higgins.validation import validate

BASE = "http://localhost:8001/api"


# ------------------------------------------------------------------ helpers

def register_device() -> dict:
    r = httpx.post(f"{BASE}/devices/register", json={"platform": "android", "adapter_mode": "standard", "app_version": "1.0.0"}, timeout=20)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['device_token']}"}


def create_case(headers: dict, gate: str, question: str, submissions: list, findings: Optional[list] = None) -> dict:
    body = {
        "gate": gate,
        "question": question,
        "submissions": submissions,
        "initialFindingRefs": [],
        "initialFindings": findings or [],
        "deviceProfile": None,
    }
    key = str(uuid.uuid4())
    r = httpx.post(f"{BASE}/investigations", json=body, headers={**headers, "Idempotency-Key": key}, timeout=30)
    assert r.status_code == 201, f"Case creation failed ({r.status_code}): {r.text}"
    data = r.json()
    assert "case" in data
    return data["case"]


def get_case(headers: dict, case_id: str) -> dict:
    r = httpx.get(f"{BASE}/investigations/{case_id}", headers=headers, timeout=20)
    assert r.status_code == 200, f"Get case failed ({r.status_code}): {r.text}"
    return r.json()["case"]


def get_evidence(headers: dict, case_id: str) -> list:
    r = httpx.get(f"{BASE}/investigations/{case_id}/evidence", headers=headers, timeout=20)
    assert r.status_code == 200
    return r.json()["items"]


def sub(kind: str, value: str, label: str = "") -> dict:
    return {"clientItemId": str(uuid.uuid4()), "kind": kind, "value": value, "label": label}


# ------------------------------------------------------------------ model configuration

class TestModelConfiguration:
    """Until an admin changes it in ApolloSG Settings, Magnum DI investigates with Gemini 3.1 Flash-Lite."""

    def test_models(self):
        from services.higgins.ai_settings import DEFAULT
        assert DEFAULT == {"provider": "gemini", "model": "gemini-3.1-flash-lite"}, f"default is {DEFAULT}"

    def test_capabilities_registered(self):
        from services.higgins.ai_settings import capabilities
        caps = capabilities("gemini-3.1-flash-lite")
        assert caps, "gemini-3.1-flash-lite is not an approved model"
        for req in ("functions", "vision", "search", "json", "text"):
            assert req in caps, f"Missing capability: {req}"


# ------------------------------------------------------------------ gate contract

class TestVisionGateContract:
    """Section 10: Vision gate is valid in the case contract."""

    def test_vision_is_valid_gate(self):
        # Verify "vision" is in the Gate literal type
        import typing
        args = typing.get_args(Gate)
        assert "vision" in args, f"'vision' not in Gate literal: {args}"

    def test_create_case_with_vision_gate(self):
        h = register_device()
        case = create_case(h, "vision", "Investigate this screenshot", [
            sub("text", "Screenshot shows a bank login page with unusual URL: nab-secure-login.com.au.evil.site")
        ])
        assert "vision" in case["gates"], f"Vision not in case gates: {case['gates']}"
        assert case["status"] in ("created", "queued", "working")

    def test_all_supported_gates_create_case(self):
        """Verify every gate in the contract can create a case."""
        h = register_device()
        for gate in ("site", "link", "text", "call", "email", "app", "file", "device", "vision"):
            case = create_case(h, gate, f"Test {gate} gate", [sub("text", f"Evidence for {gate}")])
            assert gate in case["gates"]


# ------------------------------------------------------------------ coordinator prompt

class TestGeminiRequestContract:
    """The investigation request contains exactly: the question, the complete evidence, the schema."""

    def test_coordinator_has_no_system_prompt(self):
        from services.higgins import coordinator
        assert not hasattr(coordinator, "SYSTEM"), "the investigation request must carry no system prompt"
        source = inspect.getsource(coordinator.run_turn)
        assert 'provider.generate("", contents' in source, "the system argument must be empty"
        assert "response_schema=response_schema(evidence_ids=" in source, "the response shape must come from the schema"
        assert "web_search=search_on" in inspect.getsource(coordinator), "web search stays attached when needed"
        assert "google" not in inspect.getsource(coordinator).lower().replace("google search", ""), "no provider SDK in feature code"

    def test_request_is_question_then_evidence(self):
        from services.higgins import coordinator
        source = inspect.getsource(coordinator.run_turn)
        assert 'Message("user", [Part(text=payload["message"]), *evidence_parts])' in source, \
            "the request must be the question followed by the evidence parts"
        assert "INVESTIGATION BRIEF" not in source, "the investigation brief must be gone"
        assert "evidenceInventory" not in inspect.getsource(coordinator), "no second representation of evidence"

    def test_schema_matches_the_validator_contract(self):
        from services.higgins.contracts import ModelResponse
        from services.higgins.response_schema import RESPONSE_SCHEMA
        schema_fields = set(RESPONSE_SCHEMA["properties"].keys())
        wire_fields = {field.alias or name for name, field in ModelResponse.model_fields.items()}
        assert schema_fields == wire_fields, f"schema drift: {schema_fields ^ wire_fields}"
        # extra="forbid" on the contract: the schema must not invite unknown fields
        for name in ("overview", "explanationMarkdown", "assessment", "attention", "completion"):
            assert name in (RESPONSE_SCHEMA.get("required") or []), f"{name} must be required"

    def test_evidence_is_complete_and_labelled_once(self):
        from services.higgins import evidence as ev
        source = inspect.getsource(ev.model_parts)
        assert "[evidence {row['evidence_id']} · kind={row['kind']}" in source, "evidence must carry id and kind"
        assert "2000" not in source and "INLINE_TEXT_CHARS" not in source, "evidence must not be truncated"
        assert "inventory" not in source, "evidence must not be duplicated into an inventory"

    def test_triage_intelligence_is_registered_as_evidence(self):
        from services.higgins import coordinator
        source = inspect.getsource(coordinator._register_triage_evidence)
        assert "triage_provider_evidence" in source
        assert "compact_evidence_for_magnum_di" not in inspect.getsource(coordinator), \
            "pre-gathered intelligence must be sent raw, not summarised"


# ------------------------------------------------------------------ higgins voice

class TestHigginsVoice:
    """Section 8: Higgins role as explanation layer."""

    def test_voice_contains_role_separation(self):
        from core.config import HIGGINS_VOICE
        assert "Apollo detects" in HIGGINS_VOICE, "Missing Apollo role"
        assert "Magnum DI" in HIGGINS_VOICE, "Missing Magnum DI role"
        assert "Vision Gate" in HIGGINS_VOICE, "Missing Vision Gate"

    def test_voice_prohibits_passive_language(self):
        from core.config import HIGGINS_VOICE
        # The updated voice no longer lists specific banned phrases but instead requires
        # decisive proportionate guidance — check for that standard
        assert "make the judgement yourself" in HIGGINS_VOICE.lower() or "Do not leave the person" in HIGGINS_VOICE


# ------------------------------------------------------------------ 10 acceptance scenarios

class TestScenario01_BankImpersonationEmail:
    """ATO and NAB impersonation through email, SMS and websites."""

    def test_email_impersonation_case(self):
        h = register_device()
        case = create_case(h, "email", "Is this email from NAB real?", [
            sub("text", "From: nab-security@nab-alerts.com.au\nSubject: Urgent: Your NAB account has been compromised\n\nDear Customer, We have detected suspicious activity on your account. Click here to verify: https://nab-secure.com.au.verify-now.site/login"),
            sub("url", "https://nab-secure.com.au.verify-now.site/login", "Suspicious NAB link"),
        ])
        evidence = get_evidence(h, case["id"])
        assert len(evidence) >= 2, f"Expected 2+ evidence items, got {len(evidence)}"
        url_evidence = [e for e in evidence if e["kind"] == "url"]
        assert len(url_evidence) >= 1, "URL evidence not ingested"

    def test_sms_impersonation_case(self):
        h = register_device()
        case = create_case(h, "text", "Got this SMS claiming to be from ATO", [
            sub("text", "ATO: You have an outstanding tax debt of $3,847.20. Pay immediately to avoid legal action. Call 1800-XXX-XXX or visit ato-payment.com.au"),
        ])
        evidence = get_evidence(h, case["id"])
        assert len(evidence) >= 1


class TestScenario02_LegitBankStatement:
    """Legitimate bank statement requiring verification and AutoPay explanation."""

    def test_legitimate_document_case(self):
        h = register_device()
        case = create_case(h, "vision", "Is this bank statement legitimate?", [
            sub("text", "NAB Personal Transaction Account\nBSB: 083-004\nAccount: 12-345-6789\n\nDate        Description              Debit    Credit   Balance\n01/06/2026  AutoPay - AGL Energy     $187.50           $4,312.50\n02/06/2026  Direct Credit - SALARY            $3,200.00 $7,512.50\n03/06/2026  BPAY - Telstra           $89.00            $7,423.50"),
        ])
        evidence = get_evidence(h, case["id"])
        assert len(evidence) >= 1
        text_items = [e for e in evidence if e["kind"] == "text"]
        assert len(text_items) >= 1, "Text evidence for statement not ingested"


class TestScenario03_FraudulentInvoice:
    """Fraudulent invoice with changed payment instructions."""

    def test_invoice_fraud_case(self):
        h = register_device()
        case = create_case(h, "email", "Our supplier sent updated bank details on this invoice", [
            sub("text", "INVOICE #INV-2026-4471\nFrom: Smith & Partners Pty Ltd\nABN: 12 345 678 901\n\nIMPORTANT: Our bank details have changed.\nNew BSB: 062-000\nNew Account: 1234 5678\nPlease update your records immediately.\n\nAmount Due: $24,750.00\nDue: 15 June 2026"),
        ])
        evidence = get_evidence(h, case["id"])
        assert len(evidence) >= 1


class TestScenario04_RemoteAccessCall:
    """Suspicious phone call requesting remote access."""

    def test_remote_access_scam_call(self):
        h = register_device()
        case = create_case(h, "call", "Someone called claiming to be from Telstra and asked me to install TeamViewer", [
            sub("text", "Caller said they detected malware on my internet connection. They want me to install TeamViewer and give them the access code. The caller ID showed +61 2 9999 0001. They said my IP address was compromised."),
        ])
        evidence = get_evidence(h, case["id"])
        assert len(evidence) >= 1


class TestScenario05_InvestmentPromotion:
    """Questionable investment or cryptocurrency promotion."""

    def test_crypto_investment_case(self):
        h = register_device()
        case = create_case(h, "text", "Is this crypto investment legitimate?", [
            sub("text", "EXCLUSIVE OPPORTUNITY: Bitcoin AI Trading Platform\nGuaranteed 340% returns in 30 days\nEndorsed by Elon Musk\nRegulated by ASIC (License #000000)\nMinimum investment: $250\nSign up: https://btc-ai-profits.com/register"),
            sub("url", "https://btc-ai-profits.com/register", "Investment signup page"),
        ])
        evidence = get_evidence(h, case["id"])
        assert len(evidence) >= 2


class TestScenario06_OnlineRetailer:
    """Online retailer or marketplace listing of uncertain legitimacy."""

    def test_suspicious_retailer_case(self):
        h = register_device()
        case = create_case(h, "site", "Found this shop selling discounted electronics, is it real?", [
            sub("url", "https://mega-deals-electronics-au.shop/product/iphone-15-pro-299", "Suspicious retail URL"),
            sub("text", "iPhone 15 Pro Max 256GB - ONLY $299 (RRP $2,199)\nFree shipping Australia-wide\n90% OFF - LIMITED TIME\nPayment: Bank transfer only\nNo returns policy"),
        ])
        evidence = get_evidence(h, case["id"])
        url_items = [e for e in evidence if e["kind"] == "url"]
        assert len(url_items) >= 1


class TestScenario07_JobScam:
    """Job or recruitment opportunity requesting sensitive information."""

    def test_employment_scam_case(self):
        h = register_device()
        case = create_case(h, "email", "Got this job offer but they want my ID before interview", [
            sub("text", "Congratulations! You have been selected for a Data Entry Specialist position.\nSalary: $85,000/year, work from home.\n\nTo proceed, please provide:\n- Copy of your driver's licence (front and back)\n- Tax File Number\n- Bank account details for direct deposit setup\n\nReply to: hr@global-recruitment-hub.com"),
        ])
        evidence = get_evidence(h, case["id"])
        assert len(evidence) >= 1


class TestScenario08_SocialMediaAd:
    """Social media advertisement containing misleading claims."""

    def test_misleading_ad_case(self):
        h = register_device()
        case = create_case(h, "text", "Saw this ad on Facebook, seems too good to be true", [
            sub("text", "SPONSORED - @deals.australia.official\n🔥 GOVERNMENT SOLAR REBATE: Get solar panels installed for FREE!\nThe Australian Government is paying 100% of installation costs.\nOnly 50 spots left in your area!\nClick link in bio to claim.\nwww.free-solar-gov-au.com/claim"),
            sub("url", "https://free-solar-gov-au.com/claim", "Solar scam ad link"),
        ])
        evidence = get_evidence(h, case["id"])
        assert len(evidence) >= 2


class TestScenario09_UnfamiliarAppAlert:
    """Unfamiliar app, file or account alert."""

    def test_unfamiliar_app_alert_case(self):
        h = register_device()
        case = create_case(h, "app", "Got this notification from an app I don't remember installing", [
            sub("text", "App: SecureVault Pro\nNotification: Your cloud backup is 98% full. Upgrade to Premium ($9.99/week) to avoid data loss. Tap to upgrade now.\n\nApp permissions requested: Camera, Contacts, SMS, Phone, Location, Storage"),
        ])
        evidence = get_evidence(h, case["id"])
        assert len(evidence) >= 1


class TestScenario10_NovelScenario:
    """Previously unseen scenario requiring Magnum DI to determine its own approach."""

    def test_novel_scenario_case(self):
        h = register_device()
        case = create_case(h, "text", "Someone in a Telegram group says they can recover funds I lost to a scam last year", [
            sub("text", "Message from @RecoveryExpertAU in Telegram:\n\n'I'm a certified recovery agent working with the ACCC. I recovered $45,000 for a client last week. I can recover your stolen funds guaranteed. My fee is only 10% of recovered amount, paid upfront via crypto. WhatsApp me: +44 7XXX XXXXXX. Don't tell your bank as they will block the recovery process.'"),
        ])
        evidence = get_evidence(h, case["id"])
        assert len(evidence) >= 1

    def test_cross_source_scenario(self):
        """Section 5: Cross-source investigation — email → website → login page."""
        h = register_device()
        case = create_case(h, "email", "Received email about NAB security update with a link to verify my account", [
            sub("text", "From: security@nab-customer-portal.com\nSubject: Action Required: Verify Your Identity\n\nDear Valued Customer,\n\nDue to recent security upgrades, you must verify your identity within 24 hours or your account will be suspended.\n\nVerify now: https://nab-customer-portal.com/verify"),
            sub("url", "https://nab-customer-portal.com/verify", "Verification page from email"),
            sub("url", "https://nab-customer-portal.com", "Root domain of sender"),
        ])
        evidence = get_evidence(h, case["id"])
        assert len(evidence) >= 3, "Cross-source evidence not fully ingested"
        url_items = [e for e in evidence if e["kind"] == "url"]
        assert len(url_items) >= 2, "Multiple URLs should be ingested for cross-source investigation"


# ------------------------------------------------------------------ evidence provenance and inventory

class TestEvidenceProvenance:
    """Section 7: Evidence and verification standards."""

    def test_evidence_has_coverage_tracking(self):
        h = register_device()
        long_text = "This is a detailed phishing email. " * 200
        case = create_case(h, "email", "Check this", [sub("text", long_text)])
        evidence = get_evidence(h, case["id"])
        text_item = next(e for e in evidence if e["kind"] == "text")
        assert "coverage" in text_item, "Evidence missing coverage tracking"
        assert text_item["coverage"]["total"] > 0, "Coverage total should be positive"

    def test_url_evidence_separate_from_text(self):
        h = register_device()
        case = create_case(h, "site", "Check these", [
            sub("url", "https://example.com/page1"),
            sub("url", "https://example.com/page2"),
            sub("text", "Some context about these URLs"),
        ])
        evidence = get_evidence(h, case["id"])
        url_count = sum(1 for e in evidence if e["kind"] == "url")
        text_count = sum(1 for e in evidence if e["kind"] == "text")
        assert url_count >= 2 and text_count >= 1, "URL and text evidence should be separately tracked"


# ------------------------------------------------------------------ privacy and security

class TestPrivacyBoundaries:
    """Section 11: Privacy, security and cost."""

    def test_cross_owner_isolation(self):
        h1, h2 = register_device(), register_device()
        case = create_case(h1, "text", "Private investigation", [sub("text", "Confidential data")])
        r = httpx.get(f"{BASE}/investigations/{case['id']}", headers=h2, timeout=20)
        assert r.status_code == 404, "Cross-owner access should be denied"

    def test_deleted_case_returns_410(self):
        h = register_device()
        case = create_case(h, "text", "Temporary", [sub("text", "Test")])
        httpx.delete(f"{BASE}/investigations/{case['id']}", headers=h, timeout=20)
        r = httpx.get(f"{BASE}/investigations/{case['id']}", headers=h, timeout=20)
        assert r.status_code == 410, "Deleted case should return 410 Gone"


# ------------------------------------------------------------------ response validation contract

class TestResponseValidation:
    """Verify the coordinator response JSON schema is enforced."""

    def test_valid_response_passes_validation(self):
        valid = {
            "overview": "This appears to be a phishing email impersonating NAB.",
            "explanationMarkdown": "## Investigation\n\nThe email was sent from nab-alerts.com.au which is not an official NAB domain.",
            "assessment": "concern_found",
            "attention": "urgent",
            "attentionReason": "Phishing attempt impersonating NAB",
            "findings": [
                {
                    "text": "The sender domain nab-alerts.com.au is not owned by NAB.",
                    "basis": "inference",
                    "confidence": "high",
                    "evidenceIds": ["ev-001"],
                    "sourceIds": ["src-001"],
                    "supersedesFindingIds": [],
                }
            ],
            "uncertainties": ["Unable to verify if the recipient's account was actually accessed"],
            "scope": "Examined email headers, sender domain, and linked URL",
            "sourceIds": ["src-001"],
            "remainingEvidenceIds": [],
            "actions": [
                {
                    "kind": "instruction",
                    "label": "Delete the email",
                    "instruction": "Delete this email immediately. Do not click any links or reply.",
                    "capabilityId": None,
                    "sourceIds": [],
                    "desiredField": None,
                    "desiredValue": None,
                }
            ],
            "recommendedActionIndex": 0,
            "question": None,
            "completion": "complete",
        }
        resp, errors = validate(valid, revision=1, evidence_ids={"ev-001"}, source_ids={"src-001"},
                                capability_ids=set(), pending_question=None, provider_complete=True)
        assert not errors, f"Valid response rejected: {errors}"
        assert resp is not None

    def test_invalid_assessment_fails(self):
        invalid = {
            "overview": "Test",
            "explanationMarkdown": "Test",
            "assessment": "maybe_bad",  # invalid enum
            "attention": "none",
            "attentionReason": None,
            "findings": [],
            "uncertainties": [],
            "scope": "test",
            "sourceIds": [],
            "remainingEvidenceIds": [],
            "actions": [],
            "recommendedActionIndex": 0,
            "question": None,
            "completion": "complete",
        }
        resp, errors = validate(invalid, revision=1, evidence_ids=set(), source_ids=set(),
                                capability_ids=set(), pending_question=None, provider_complete=True)
        assert len(errors) > 0, "Invalid assessment should be rejected"


class TestMagnumAssessmentReconciliation:
    """Field mapping must not discard supported Magnum findings or override threats."""

    @staticmethod
    def _response():
        return {
            "overview": "The available checks did not establish a scam.",
            "explanationMarkdown": "Some sender details remain unverified.",
            "assessment": "uncertain",
            "outcome": "unlikely_scam",
            "attention": "none",
            "findings": [],
            "uncertainties": ["Sender identity not independently verified"],
            "scope": "Only the supplied message and available lookups",
            "sourceIds": [],
            "remainingEvidenceIds": [],
            "actions": [],
            "recommendedActionIndex": None,
            "question": None,
            "completion": "complete",
        }

    def test_unlikely_scam_uncertain_field_reconciles_without_losing_gaps(self):
        response, errors = validate(self._response(), revision=1, evidence_ids=set(),
                                    source_ids=set(), capability_ids=set(),
                                    pending_question=None, provider_complete=True)
        assert not errors
        assert response is not None
        assert response.outcome == "unlikely_scam"
        assert response.assessment == "no_concern_found_within_scope"
        assert response.uncertainties == ["Sender identity not independently verified"]

    def test_action_needed_still_requires_an_action(self):
        data = self._response()
        data["attention"] = "action_needed"
        response, errors = validate(data, revision=1, evidence_ids=set(),
                                    source_ids=set(), capability_ids=set(),
                                    pending_question=None, provider_complete=True)
        assert response is None
        assert any("requires at least one action" in e for e in errors)

    def test_deeper_investigator_can_overturn_hawkeye_floor(self):
        response, errors = validate(self._response(), revision=1, evidence_ids=set(),
                                    source_ids=set(), capability_ids=set(),
                                    pending_question=None, provider_complete=True,
                                    floor={"outcome": "scam", "established": True})
        assert not errors
        assert response is not None
        assert response.outcome == "unlikely_scam"

    def test_partial_investigation_can_report_decisive_scam_evidence(self):
        data = self._response()
        data.update(assessment="concern_found", outcome="scam", completion="partial",
                    overview="A verified malicious destination was found.",
                    findings=[{"text": "The destination is listed as malicious.",
                               "basis": "observation", "confidence": "low",
                               "evidenceIds": ["evidence-1"], "sourceIds": [],
                               "supersedesFindingIds": []}],
                    uncertainties=["A separate company lookup was unavailable"])
        response, errors = validate(data, revision=1, evidence_ids={"evidence-1"},
                                    source_ids=set(), capability_ids=set(),
                                    pending_question=None, provider_complete=True)
        assert not errors
        assert response is not None
        assert response.outcome == "scam"
        assert response.completion == "partial"
        assert response.findings[0].confidence == "low"
        assert response.uncertainties
