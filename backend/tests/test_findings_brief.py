"""Higgins Findings Brief — services.higgins.tc_flyby.findings_brief (Apollo PRD v2.2 Phase 5).

Covers: the six required headers are always present, in the required content (exact Finding
label, the 0-100 Findings Rating, the actual findings/evidence, the plain-language mechanism
explanation, what was verified plus its limitations, and one clear primary recommended action
with any additional steps only when there's more than one action).
"""
from services.higgins import outcomes
from services.higgins.tc_flyby import findings_brief
from services.higgins.tc_flyby.scoring import ScoreBreakdown

_REQUIRED_HEADERS = {"finding", "findingsRating", "whatApolloFound", "whyThisMatters", "whatWasVerified", "recommendedAction"}


def _breakdown(rating: int, finding: str) -> ScoreBreakdown:
    return ScoreBreakdown(rating=rating, finding=finding)


def _result(**over) -> dict:
    base = dict(outcome="likely_scam",
               explanationMarkdown="**What was found**\n- a lookalike domain was used\n\n**What it means**\n"
                                   "This is the hallmark of a phishing attempt — a lookalike domain is designed to "
                                   "trick you into entering real credentials on a fake page.\n\n**How ApolloSG checked**\nChecked it.",
               findings=[{"text": "linkt-au-pay.top carries Linkt's name but isn't Linkt's domain."}],
               actions=[{"label": "Don't click the link", "instruction": "Delete the message without tapping the link."},
                        {"label": "Report it", "instruction": "Report the message to Scamwatch."}],
               recommendedActionIndex=0, scope="TC Hawkeye checked the domain against Apollo's knowledge base.",
               uncertainties=["Apollo can't confirm who actually sent this."],
               attentionReason="Tapping the link could lead to a fake login page.", overview="A lookalike domain was used.")
    base.update(over)
    return base


class TestAllSixHeadersPresent:
    def test_every_required_header_is_present(self):
        brief = findings_brief.build(_result(), _breakdown(72, "likely_scam"), None)
        assert _REQUIRED_HEADERS.issubset(brief.keys())


class TestFinding:
    def test_finding_is_one_of_the_four_approved_labels_exactly(self):
        for outcome in outcomes.OUTCOMES:
            brief = findings_brief.build(_result(outcome=outcome), _breakdown(50, outcome), None)
            assert brief["finding"] == outcomes.LABELS[outcome]

    def test_no_outcome_reads_as_unable_to_determine(self):
        brief = findings_brief.build(_result(outcome=None), _breakdown(0, "not_scam"), None)
        assert brief["finding"] == "Unable to determine"


class TestFindingsRating:
    def test_rating_comes_straight_from_the_breakdown(self):
        brief = findings_brief.build(_result(), _breakdown(91, "scam"), None)
        assert brief["findingsRating"] == 91


class TestWhatApolloFound:
    def test_lists_the_actual_findings_text(self):
        brief = findings_brief.build(_result(), _breakdown(72, "likely_scam"), None)
        assert brief["whatApolloFound"] == ["linkt-au-pay.top carries Linkt's name but isn't Linkt's domain."]

    def test_empty_findings_gets_an_explicit_placeholder_not_an_empty_list(self):
        brief = findings_brief.build(_result(findings=[]), _breakdown(28, "unlikely_scam"), None)
        assert brief["whatApolloFound"] and isinstance(brief["whatApolloFound"][0], str)


class TestWhyThisMatters:
    def test_pulls_the_what_it_means_section_from_the_explanation_markdown(self):
        brief = findings_brief.build(_result(), _breakdown(72, "likely_scam"), None)
        assert "lookalike domain is designed to" in brief["whyThisMatters"]

    def test_falls_back_to_attention_reason_when_no_what_it_means_section(self):
        brief = findings_brief.build(_result(explanationMarkdown="Just an overview, no sections."), _breakdown(72, "likely_scam"), None)
        assert brief["whyThisMatters"] == "Tapping the link could lead to a fake login page."


class TestWhatWasVerified:
    def test_carries_the_scope_summary_and_the_uncertainties_as_limitations(self):
        brief = findings_brief.build(_result(), _breakdown(72, "likely_scam"), None)
        assert brief["whatWasVerified"]["summary"] == "TC Hawkeye checked the domain against Apollo's knowledge base."
        assert brief["whatWasVerified"]["limitations"] == ["Apollo can't confirm who actually sent this."]


class TestRecommendedAction:
    def test_primary_is_the_recommended_action_and_the_rest_are_additional(self):
        brief = findings_brief.build(_result(), _breakdown(72, "likely_scam"), None)
        assert brief["recommendedAction"]["primary"]["label"] == "Don't click the link"
        assert [a["label"] for a in brief["recommendedAction"]["additional"]] == ["Report it"]

    def test_no_actions_means_no_primary_and_no_additional(self):
        brief = findings_brief.build(_result(actions=[], recommendedActionIndex=None), _breakdown(10, "not_scam"), None)
        assert brief["recommendedAction"]["primary"] is None
        assert brief["recommendedAction"]["additional"] == []


class TestTaxonomyPassThrough:
    def test_taxonomy_classification_is_carried_into_the_brief(self):
        tax = {"primary": {"domainCode": 1, "domainName": "Account Takeover & Authentication Exploitation"}, "secondaryDomains": []}
        brief = findings_brief.build(_result(), _breakdown(85, "scam"), tax)
        assert brief["taxonomy"] == tax
