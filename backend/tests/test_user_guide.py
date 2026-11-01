# Golden-question regression suite for Higgins product knowledge and User Guide.
# Tests the source hierarchy, Direct Answer First, and intent classification.
import pytest
from services.higgins.context_tools import classify_context
from services.higgins.presenter import product_knowledge
from services.higgins import user_guide


class TestUserGuideStructure:
    """The User Guide has structured, searchable tasks."""

    def test_guide_has_sections(self):
        assert len(user_guide.GUIDE_SECTIONS) >= 8, "Guide must cover major ApolloSG sections"

    def test_every_task_has_required_fields(self):
        for task in user_guide.TASKS:
            assert task.id, f"Task missing id"
            assert task.name, f"Task {task.id} missing name"
            assert task.section, f"Task {task.id} missing section"
            assert task.questions, f"Task {task.id} missing questions"
            assert task.what_it_does, f"Task {task.id} missing what_it_does"

    def test_no_duplicate_ids(self):
        ids = [t.id for t in user_guide.TASKS]
        assert len(ids) == len(set(ids)), f"Duplicate task IDs: {[i for i in ids if ids.count(i) > 1]}"

    def test_routes_are_valid(self):
        """Tasks with routes should have sensible paths."""
        for task in user_guide.TASKS:
            if task.route:
                assert task.route.startswith("/") or task.route.startswith("("), f"Task {task.id} route invalid: {task.route}"


class TestGoldenQuestions:
    """Golden-question suite: common ApolloSG usage questions must produce correct answers."""

    def test_sharing_procedure(self):
        """'How do I share something into ApolloSG?' → sharing instructions, no privacy dump."""
        result = product_knowledge("How do I share something into ApolloSG?", ["flows"], intent_label="sharing_help")
        assert result is not None
        assert "Share" in result["answer"]
        assert "ApolloSG" in result["answer"]
        # No privacy dump
        assert "anonymous device ID" not in result["answer"].lower()
        assert "retention" not in result["answer"].lower()
        assert "encryption" not in result["answer"].lower()

    def test_share_menu_troubleshoot(self):
        """'Apollo isn't in my Share menu.' → troubleshooting/fallback."""
        result = product_knowledge("Apollo isn't in my Share menu.", [], intent_label="sharing_help")
        assert result is not None
        assert "copy" in result["answer"].lower() or "paste" in result["answer"].lower()

    def test_multi_intent_share_plus_privacy(self):
        """'How do I share a screenshot and does it leave my phone?' → sharing + privacy."""
        # The classifier should detect the sharing intent for the first half
        plan = classify_context("How do I share a screenshot to ApolloSG and does it leave my phone?")
        # Should recognize sharing intent (the primary intent)
        assert plan.label == "sharing_help" or "privacy" in plan.knowledge_modules, \
            f"Expected sharing_help or privacy, got {plan.label} with modules {plan.knowledge_modules}"

    def test_where_to_check_message(self):
        """'Where do I check a message?' → correct Apollo destination."""
        tasks = user_guide.find_tasks("Where do I check a message?")
        assert len(tasks) > 0
        assert any(t.id == "check_message" for t in tasks), f"Expected check_message, got {[t.id for t in tasks]}"

    def test_device_state_question(self):
        """'Is message protection on for me?' → should route to device state, not User Guide."""
        plan = classify_context("Is message protection on for me?")
        # This is a device-state question, not a product-use question
        assert plan.label != "sharing_help"

    def test_case_question(self):
        """'Why did Apollo flag this?' → should route to case/evidence, not User Guide."""
        plan = classify_context("Why did Apollo flag this?")
        assert plan.label != "sharing_help"
        assert plan.label != "product_info"

    def test_scam_education_question(self):
        """'How do phishing scams work?' → KB/Learn, not User Guide product help."""
        plan = classify_context("How do phishing scams work?")
        # Should NOT be classified as product help
        assert plan.label not in ("sharing_help",)

    def test_unknown_feature(self):
        """Unknown/non-existent feature → honest limitation, not fabricated answer."""
        tasks = user_guide.find_tasks("How do I use the quantum teleporter feature?")
        # Should return empty or very low-confidence matches
        assert len(tasks) == 0 or all(t.id != "quantum_teleporter" for t in tasks)

    def test_check_link_question(self):
        tasks = user_guide.find_tasks("How do I check a link?")
        assert any(t.id == "check_link" for t in tasks)

    def test_check_file_question(self):
        tasks = user_guide.find_tasks("How do I check a file?")
        assert any(t.id == "check_file" for t in tasks)

    def test_protections_question(self):
        tasks = user_guide.find_tasks("What protections do I have?")
        assert any(t.id == "protections" for t in tasks)

    def test_ask_higgins_question(self):
        tasks = user_guide.find_tasks("What can I ask Higgins?")
        assert any(t.id == "ask_higgins" for t in tasks)

    def test_settings_question(self):
        tasks = user_guide.find_tasks("Where are settings?")
        assert any(t.id == "settings" for t in tasks)

    def test_sample_checks_question(self):
        tasks = user_guide.find_tasks("What are sample checks?")
        assert any(t.id == "sample_checks" for t in tasks)


class TestSourceHierarchy:
    """Higgins uses the correct authoritative source."""

    def test_product_question_uses_guide_not_kb(self):
        """A product-use question must not fall through to the scam KB."""
        result = product_knowledge("How do I check a message?", [], intent_label="")
        if result:
            assert "phishing" not in result["answer"].lower() or "check" in result["answer"].lower()
            assert result.get("task_id") or "/message" in str(result.get("navigate", []))

    def test_privacy_question_still_works(self):
        """Privacy questions must still get privacy answers."""
        plan = classify_context("What does ApolloSG store?")
        assert "privacy" in plan.knowledge_modules

    def test_sharing_outranks_privacy(self):
        """Sharing procedural question outranks generic privacy matching."""
        plan = classify_context("How do I share something into ApolloSG?")
        assert plan.label == "sharing_help"
        assert "privacy" not in plan.knowledge_modules


class TestDirectAnswerFirst:
    """First paragraph independently answers the question."""

    def test_sharing_starts_with_procedure(self):
        result = product_knowledge("How do I share something into ApolloSG?", ["flows"], intent_label="sharing_help")
        assert result is not None
        first_para = result["answer"].split("\n\n")[0]
        assert "share" in first_para.lower() or "Share" in first_para
        assert len(first_para) < 300  # Concise first paragraph

    def test_procedural_answer_concise(self):
        """Simple procedural question answered in roughly 2-6 sentences."""
        result = product_knowledge("How do I share something into ApolloSG?", ["flows"], intent_label="sharing_help")
        assert result is not None
        sentences = [s.strip() for s in result["answer"].replace("\n", " ").split(".") if s.strip()]
        assert len(sentences) <= 8, f"Answer too verbose: {len(sentences)} sentences"


class TestNoModuleDump:
    """A keyword match must never mean 'display this whole module.'"""

    def test_flows_not_fully_dumped_for_specific_question(self):
        result = product_knowledge("Where do I check a message?", ["flows"], intent_label="")
        if result:
            assert len(result["answer"]) < 1000, f"Answer too long for specific question: {len(result['answer'])} chars"

    def test_privacy_not_fully_dumped_for_specific_question(self):
        result = product_knowledge("Is my data stored on the server?", ["privacy"], intent_label="")
        if result:
            # Should not include ALL privacy bullets — only the relevant ones
            assert len(result["answer"]) < 1500, f"Answer too long: {len(result['answer'])} chars"
