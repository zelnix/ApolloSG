# Regression tests for corrected alert-selection rules (scam_analysis + government_alerts).
# Each test uses a headline from the owner's screenshots or a constructed scenario that exercises
# the specific rule. No AI calls.
import services.scam_analysis as sa
from datetime import datetime, timedelta, timezone
from core.db import now_utc
from services import government_alerts as ga


class TestNewsExclusion:
    """Sentencing, arrests, prosecutions and general news are classified as 'news', not alerts."""

    def test_sentencing_headline_is_news(self):
        out = sa.analyse({"title": "Man sentenced to 10 years for $5M investment fraud scheme",
                          "summary": "A California man was sentenced today for running a fraudulent investment scheme."})
        assert out["tier"] == "news", f"Expected 'news', got {out['tier']}"
        assert out["severity"] == "LOW"

    def test_russian_actor_arrest_is_news(self):
        out = sa.analyse({"title": "Russian actor charged in international phishing campaign",
                          "summary": "The Department of Justice announced charges against a Russian national for orchestrating a phishing scheme."})
        assert out["tier"] == "news", f"Expected 'news', got {out['tier']}"

    def test_farm_equipment_prosecution_is_news(self):
        out = sa.analyse({"title": "Farm equipment dealer convicted of fraud in machinery scam",
                          "summary": "A farm equipment dealer was convicted of defrauding buyers of heavy machinery."})
        assert out["tier"] == "news", f"Expected 'news', got {out['tier']}"

    def test_prosecution_with_active_warning_is_still_alert(self):
        """A prosecution report that includes a separate, current consumer warning stays an alert."""
        out = sa.analyse({"title": "Scam ring leaders arrested — warning: scammers are still actively targeting victims",
                          "summary": "While the leaders have been arrested, the scam network is still actively sending phishing texts to consumers."})
        assert out["tier"] == "specific_scam", f"Expected 'specific_scam', got {out['tier']}"

    def test_news_is_not_general_education(self):
        """News must not be sent to Learn (general_education)."""
        out = sa.analyse({"title": "Three arrested for romance scam targeting elderly",
                          "summary": "Police arrested three suspects in connection with a romance scam."})
        assert out["tier"] == "news"
        assert out["tier"] != "general_education"


class TestPreparednessExclusion:
    """Preparedness advice without a current consumer warning is general_education, not an alert."""

    def test_preparedness_headline_is_education(self):
        out = sa.analyse({"title": "Be prepared: how to protect yourself from online scams",
                          "summary": "Follow these tips to stay safe from scams online."})
        assert out["tier"] == "general_education", f"Expected 'general_education', got {out['tier']}"

    def test_preparedness_with_active_alert_stays_alert(self):
        out = sa.analyse({"title": "Be prepared: scam alert — fake toll texts circulating",
                          "summary": "Scammers are actively sending fake toll text messages. Be prepared to recognise these."})
        assert out["tier"] == "specific_scam", f"Expected 'specific_scam', got {out['tier']}"


class TestSeverityNotInflatedByAdvice:
    """Advice containing 'immediately' must never produce Extreme severity."""

    def test_immediately_report_is_not_extreme(self):
        out = sa.analyse({"title": "Scam alert: fake tax refund texts",
                          "summary": "Scammers are sending fake ATO texts. Immediately report any suspicious text to Scamwatch.",
                          "_source_region": "AU", "_source_name": "Scamwatch"})
        assert out["severity"] != "EXTREME", f"'Immediately report...' advice must not produce EXTREME, got {out['severity']}"

    def test_immediately_contact_is_not_extreme(self):
        out = sa.analyse({"title": "Warning: phishing emails targeting bank customers",
                          "summary": "Scammers are actively sending emails. Immediately contact your bank if you shared details.",
                          "_source_region": "AU", "_source_name": "Scamwatch"})
        assert out["severity"] != "EXTREME", f"'Immediately contact...' advice must not produce EXTREME, got {out['severity']}"

    def test_genuine_urgent_threat_can_be_extreme(self):
        """A source that describes urgent, active harm (not advice) can reach Extreme."""
        out = sa.analyse({"title": "Urgent warning: scam causing significant losses",
                          "summary": "Scammers are actively draining bank accounts. Significant losses reported across the country.",
                          "_source_region": "AU", "_source_name": "Scamwatch"})
        assert out["severity"] == "EXTREME", f"Genuine urgent threat should be EXTREME, got {out['severity']}"


class TestOverseasNewsExcluded:
    """Overseas news defaults to unknown relevance and is excluded, not 'everywhere'."""

    def test_us_sentencing_not_everywhere(self):
        out = sa.analyse({"title": "Man sentenced for $10M fraud",
                          "summary": "A federal court sentenced a man for running a fraud scheme.",
                          "_source_region": "US", "_source_name": "FTC"})
        # Should be news (sentencing) AND not relevant to Australia
        assert out["tier"] == "news"

    def test_overseas_scam_without_au_mention(self):
        """A non-AU source with no Australia mention and no global threat type stays out."""
        out = sa.analyse({"title": "Scam alert: fake council tax refund emails",
                          "summary": "HMRC warns of scammers sending fake council tax refund emails.",
                          "_source_region": "UK", "_source_name": "HMRC"})
        assert out["australianRelevance"] != "confirmed"

    def test_unknown_relevance_stays_out(self):
        applies, _ = sa.applies_in("Some alert about local benefits", "Local government warns residents.", "UK")
        assert applies in ("UK", "unknown"), f"Expected local or unknown, got {applies}"


class TestAustralianWarningsStillAppear:
    """Positive tests: genuine Australian warnings must still appear."""

    def test_scamwatch_consumer_warning(self):
        out = sa.analyse({"title": "Scam alert: fake Centrelink texts targeting Australians",
                          "summary": "Scamwatch warns Australians about scammers sending fake Centrelink text messages.",
                          "_source_region": "AU", "_source_name": "Scamwatch"})
        assert out["tier"] == "specific_scam"
        assert out["australianRelevance"] == "confirmed"
        assert out["severity"] in ("HIGH", "EXTREME", "MODERATE")

    def test_au_source_defaults_to_au_relevant(self):
        out = sa.analyse({"title": "Scam alert: impersonation calls",
                          "summary": "Scammers pretend to be from Services Australia.",
                          "_source_region": "AU", "_source_name": "Services Australia"})
        assert out["australianRelevance"] == "confirmed"

    def test_au_source_applies_in_au(self):
        applies, _ = sa.applies_in("Scam alert: fake toll texts", "Scammers sending fake Linkt texts.", "AU")
        assert applies == "AU"


class TestVerifiedGlobalThreatsAppear:
    """Verified global consumer threats applicable to Australia must appear."""

    def test_global_phishing_campaign(self):
        out = sa.analyse({"title": "Warning: global phishing campaign targeting online banking",
                          "summary": "Scammers are actively sending phishing emails impersonating major banks worldwide.",
                          "_source_region": "US", "_source_name": "FBI IC3"})
        assert out["tier"] == "specific_scam"
        # Should be potential (global threat applicable to AU) not unknown
        assert out["australianRelevance"] in ("confirmed", "potential"), f"Global threat should be eligible, got {out['australianRelevance']}"

    def test_global_romance_scam(self):
        out = sa.analyse({"title": "Alert: romance scam networks targeting victims worldwide",
                          "summary": "Romance scam networks are actively targeting victims across multiple countries.",
                          "_source_region": "US", "_source_name": "FBI IC3"})
        assert out["tier"] == "specific_scam"
        assert out["australianRelevance"] in ("confirmed", "potential")

    def test_overseas_source_mentioning_australia(self):
        out = sa.analyse({"title": "Scam warning: tech support fraud",
                          "summary": "Tech support scammers are targeting people in Australia and New Zealand.",
                          "_source_region": "US", "_source_name": "FBI IC3"})
        assert out["australianRelevance"] == "confirmed"


class TestFreshnessRules:
    """Publication date, campaign activity and source-refresh time are separate."""

    def _row(self, published_at=None, source_id="scamwatch"):
        return {"source_id": source_id, "title": "Scam alert: X", "url": "https://x/alert",
                "summary": "Scammers are actively targeting consumers.", "content_type": "official_advice",
                "trust_status": "recognised_government", "last_checked_at": now_utc(),
                "published_at": published_at}

    def _analysis(self, tier="specific_scam", severity="HIGH", relevance="confirmed", verified_ongoing=False, verified_evidence=""):
        return {"tier": tier, "severity": severity, "audience": "consumer",
                "australianRelevance": relevance, "australianRelevanceReason": "r",
                "severityReason": "r", "confidence": "high", "facts": {}, "sections": {},
                "analysisVersion": sa.ANALYSIS_VERSION,
                "verifiedOngoing": verified_ongoing, "verifiedOngoingEvidence": verified_evidence,
                "verifiedOngoingAt": now_utc() if verified_ongoing else None}

    def test_recent_alert_is_eligible(self):
        now = now_utc()
        built = ga._alert(self._row(now - timedelta(days=30)), {"name": "Scamwatch"}, self._analysis(), now)
        assert ga.is_eligible(built, now)

    def test_old_alert_without_ongoing_excluded(self):
        now = now_utc()
        built = ga._alert(self._row(now - timedelta(days=90)), {"name": "Scamwatch"}, self._analysis(), now)
        assert not ga.is_eligible(built, now)

    def test_old_alert_with_verified_ongoing_stays(self):
        now = now_utc()
        analysis = self._analysis(verified_ongoing=True, verified_evidence="Scammers are actively targeting consumers.")
        built = ga._alert(self._row(now - timedelta(days=90)), {"name": "Scamwatch"}, analysis, now)
        assert ga.is_eligible(built, now)

    def test_undated_without_ongoing_excluded(self):
        now = now_utc()
        built = ga._alert(self._row(None), {"name": "Scamwatch"}, self._analysis(), now)
        assert not ga.is_eligible(built, now)

    def test_undated_with_ongoing_included(self):
        now = now_utc()
        analysis = self._analysis(verified_ongoing=True, verified_evidence="Scammers are actively sending fake texts.")
        built = ga._alert(self._row(None), {"name": "Scamwatch"}, analysis, now)
        assert ga.is_eligible(built, now)

    def test_rechecking_old_article_not_current(self):
        """Source-refresh time (last_checked_at) must not make an old article current."""
        now = now_utc()
        row = self._row(now - timedelta(days=200))
        row["last_checked_at"] = now  # rechecked just now
        built = ga._alert(row, {"name": "Scamwatch"}, self._analysis(), now)
        assert not ga.is_eligible(built, now), "Rechecking an old article must not make it current"


class TestVerifiedOngoingKeywords:
    """Keywords aren't verification: 'active'/'ongoing'/'currently' must describe the consumer threat."""

    def test_active_in_advice_not_verified(self):
        verified, _ = sa._has_verified_active_threat([
            "If you see a suspicious text, immediately report it to your local police.",
            "Currently, the best way to protect yourself is to use strong passwords.",
        ])
        assert not verified, "Advice sentences must not count as verified ongoing"

    def test_active_in_navigation_not_verified(self):
        verified, _ = sa._has_verified_active_threat([
            "This page is currently being updated with the latest information.",
        ])
        assert not verified, "Navigation text must not count as verified ongoing"

    def test_active_in_threat_description_verified(self):
        verified, sentence = sa._has_verified_active_threat([
            "Scammers are actively sending fake toll text messages to people across the country.",
        ])
        assert verified, "Threat description with active keyword should be verified"
        assert "actively" in sentence

    def test_historical_quote_not_verified(self):
        verified, _ = sa._has_verified_active_threat([
            "In 2019, scammers were actively targeting elderly people through phone calls.",
        ])
        assert not verified, "Historical text must not count as verified ongoing"


class TestGrowlUsesEligibility:
    """The growl rule uses the same eligibility gate as the feed and badge."""

    def _row(self, published_at=None):
        return {"source_id": "scamwatch", "title": "Scam alert: X", "url": "https://x/alert",
                "summary": "s", "content_type": "official_advice",
                "trust_status": "recognised_government", "last_checked_at": now_utc(),
                "published_at": published_at}

    def _analysis(self, tier="specific_scam", severity="HIGH", relevance="confirmed", verified_ongoing=False):
        return {"tier": tier, "severity": severity, "audience": "consumer",
                "australianRelevance": relevance, "australianRelevanceReason": "r",
                "severityReason": "r", "confidence": "high", "facts": {}, "sections": {},
                "analysisVersion": sa.ANALYSIS_VERSION,
                "verifiedOngoing": verified_ongoing, "verifiedOngoingEvidence": "", "verifiedOngoingAt": None}

    def test_eligible_high_growls(self):
        now = now_utc()
        built = ga._alert(self._row(now - timedelta(days=10)), {"name": "Scamwatch"}, self._analysis(), now)
        assert built["growling"] is True

    def test_ineligible_old_does_not_growl(self):
        now = now_utc()
        built = ga._alert(self._row(now - timedelta(days=90)), {"name": "Scamwatch"}, self._analysis(), now)
        assert built["growling"] is False, "An ineligible old alert must not growl"

    def test_education_never_growls(self):
        now = now_utc()
        built = ga._alert(self._row(now - timedelta(days=10)), {"name": "Scamwatch"}, self._analysis(tier="general_education", severity="LOW"), now)
        assert built["growling"] is False

    def test_news_never_growls(self):
        now = now_utc()
        built = ga._alert(self._row(now - timedelta(days=10)), {"name": "Scamwatch"}, self._analysis(tier="news", severity="LOW"), now)
        assert built["growling"] is False
