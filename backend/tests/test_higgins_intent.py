# Regression tests for Higgins intent classification and Direct Answer First contract.
# Tests the fix for "How do I share something into ApolloSG?" returning a privacy dump.
import re
import pytest
from services.higgins.context_tools import classify_context, _PRIVACY_RE, _SHARING_HELP_RE
from services.higgins.presenter import product_knowledge, sharing_help


class TestSharingIntentClassification:
    """Sharing/procedural questions must not activate the privacy module."""

    def test_share_into_apollo_is_sharing_help(self):
        plan = classify_context("How do I share something into ApolloSG?")
        assert plan.label == "sharing_help", f"Expected 'sharing_help', got {plan.label}"
        assert "privacy" not in plan.knowledge_modules, "Sharing question must not include privacy module"

    def test_send_screenshot_is_sharing_help(self):
        plan = classify_context("How do I send Apollo a screenshot?")
        assert plan.label == "sharing_help", f"Expected 'sharing_help', got {plan.label}"
        assert "privacy" not in plan.knowledge_modules

    def test_share_from_another_app(self):
        plan = classify_context("Can I share something from another app?")
        assert plan.label == "sharing_help"

    def test_share_to_apollo(self):
        plan = classify_context("How do I share to Apollo?")
        assert plan.label == "sharing_help"

    def test_how_to_get_into_apollo(self):
        plan = classify_context("How do I get something into Apollo for checking?")
        assert plan.label == "sharing_help"

    def test_not_in_share_menu(self):
        plan = classify_context("ApolloSG isn't in my Share menu.")
        assert plan.label == "sharing_help"

    def test_send_message_to_apollo(self):
        plan = classify_context("How do I send a message to ApolloSG?")
        assert plan.label == "sharing_help"


class TestPrivacyStillWorks:
    """Legitimate privacy questions must still activate the privacy module."""

    def test_what_does_apollo_share(self):
        plan = classify_context("What information does ApolloSG share?")
        assert "privacy" in plan.knowledge_modules, "Privacy question must include privacy module"

    def test_what_does_apollo_store(self):
        plan = classify_context("What does ApolloSG store?")
        assert "privacy" in plan.knowledge_modules

    def test_does_data_leave_device(self):
        plan = classify_context("Does anything leave my device when I share a screenshot?")
        assert "privacy" in plan.knowledge_modules

    def test_who_can_see_my_data(self):
        plan = classify_context("Who can see what I share?")
        assert "privacy" in plan.knowledge_modules

    def test_is_my_data_private(self):
        plan = classify_context("Is my data private?")
        assert "privacy" in plan.knowledge_modules

    def test_personal_data(self):
        plan = classify_context("What personal data does Apollo collect?")
        assert "privacy" in plan.knowledge_modules


class TestPrivacyRegexContextSensitive:
    """Generic action verbs alone must not activate privacy."""

    def test_share_alone_no_privacy(self):
        # "share" without privacy/data context should NOT match _PRIVACY_RE
        assert not _PRIVACY_RE.search("How do I share something into ApolloSG?"), \
            "'share' in a procedural context must not match _PRIVACY_RE"

    def test_send_alone_no_privacy(self):
        assert not _PRIVACY_RE.search("How do I send a screenshot to Apollo?"), \
            "'send' in a procedural context must not match _PRIVACY_RE"

    def test_upload_alone_no_privacy(self):
        assert not _PRIVACY_RE.search("How do I upload something for checking?"), \
            "'upload' in a procedural context must not match _PRIVACY_RE"

    def test_share_with_privacy_context_matches(self):
        assert _PRIVACY_RE.search("What information does Apollo share?"), \
            "'share' with privacy context must match _PRIVACY_RE"

    def test_data_retention_matches(self):
        assert _PRIVACY_RE.search("How long is my data retained?"), \
            "Data retention question must match _PRIVACY_RE"


class TestSharingHelpPresenter:
    """The sharing procedure is concise and actionable — no privacy dump."""

    def test_sharing_answer_is_concise(self):
        result = sharing_help("How do I share something into ApolloSG?")
        assert "Share" in result["answer"]
        assert "ApolloSG" in result["answer"]
        answer = result["answer"]
        # Must NOT contain privacy dump content
        assert "anonymous device ID" not in answer.lower(), "Sharing answer must not contain privacy dump"
        assert "server retention" not in answer.lower()
        assert "encryption" not in answer.lower()
        assert "background" not in answer.lower()
        # Must be reasonably concise (under 500 chars for standard sharing question)
        assert len(answer) < 500, f"Sharing answer too long: {len(answer)} chars"

    def test_sharing_answer_has_navigation(self):
        result = sharing_help("How do I share something into ApolloSG?")
        assert result.get("navigate"), "Sharing answer must include navigation"

    def test_troubleshoot_answer(self):
        result = sharing_help("ApolloSG isn't in my Share menu.")
        assert "copy" in result["answer"].lower() or "paste" in result["answer"].lower()
        assert "screenshot" in result["answer"].lower()

    def test_screenshot_answer(self):
        result = sharing_help("How do I send Apollo a screenshot?")
        assert "screenshot" in result["answer"].lower()


class TestDirectAnswerFirst:
    """The first paragraph should independently answer the user's question."""

    def test_sharing_answer_starts_with_procedure(self):
        result = sharing_help("How do I share something into ApolloSG?")
        first_paragraph = result["answer"].split("\n\n")[0]
        assert "share" in first_paragraph.lower() or "Share" in first_paragraph
        assert "ApolloSG" in first_paragraph

    def test_procedural_answer_no_unrelated_privacy(self):
        """A procedural answer must not contain unrelated privacy bullets."""
        result = product_knowledge("How do I share something into ApolloSG?", ["flows"], intent_label="sharing_help")
        if result:
            answer = result["answer"]
            # Must not contain privacy content
            assert "No account, no email, no ad tracking" not in answer
            assert "Anonymous device ID only" not in answer
            assert "Credentials" not in answer
            assert "Conversations and speech" not in answer


class TestNavigationForSharing:
    """Sharing questions should navigate to Check a message, not Device capabilities."""

    def test_sharing_navigates_to_message(self):
        result = sharing_help("How do I share something into ApolloSG?")
        navigate = result.get("navigate", [])
        assert "/message" in navigate, f"Expected /message in navigate, got {navigate}"


class TestProductKnowledgeSelectsMinimum:
    """product_knowledge must select minimum relevant facts, not dump whole modules."""

    def test_flows_not_fully_dumped(self):
        result = product_knowledge("Where do I check a message?", ["flows"], intent_label="")
        if result:
            answer = result["answer"]
            # Should NOT contain the entire flows module
            assert "Apollo states:" not in answer or len(answer) < 800, \
                "product_knowledge should not dump the entire flows module for a specific question"
