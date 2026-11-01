# Deterministic scam analysis: fixed rules on the source's own words (no AI), the free pre-filter and the growl rule.
import services.scam_analysis as sa
from services import government_alerts as ga


class TestDeterministicAnalysis:
    def test_unclear_item_is_safe_education(self):
        out = sa.analyse({"title": "Annual report", "summary": "Statistics on reports received."})
        assert out["tier"] == "general_education" and out["severity"] == "LOW"
        assert out["method"] == "deterministic_source_rules" and out["analysisVersion"] == sa.ANALYSIS_VERSION

    def test_organisation_advisory_is_never_a_consumer_alert(self):
        out = sa.analyse({"title": "Critical vulnerability in VPN firmware", "summary": "Threat actors exploit CVE-2026-1234; patch now."})
        assert out["audience"] == "organisation" and out["tier"] == "general_education"

    def test_active_consumer_warning_quotes_the_source(self):
        out = sa.analyse({"title": "Scam alert: fake toll texts", "summary": "Scammers are actively sending fake toll text messages to Australians.",
                          "_source_name": "Scamwatch", "_source_region": "AU"})
        assert out["tier"] == "specific_scam" and out["severity"] == "HIGH"
        assert "actively" in out["severityReason"] and out["australianRelevance"] == "confirmed"

    def test_sections_only_hold_the_sources_own_sentences(self):
        article = ("Scammers pretend to be from your bank and ask you to move money. "
                   "Never share your one-time code with anyone who calls you. Report it to Scamwatch if you lost money.")
        title = "Bank impersonation scam warning"
        out = sa.analyse({"title": title, "summary": ""}, article)
        source_words = f"{title}. {article}"
        for text in (out["sections"]["whatHappened"], out["sections"]["whatToWatch"], out["sections"]["whatToDo"]):
            for line in filter(None, text.split("\n")):
                assert line in source_words


class TestPreFilter:
    def test_fragment_urls_and_nav_titles_are_not_alerts(self):
        assert sa._obviously_not_an_alert({"url": "https://x/a#megamenu-skip", "title": "Foo"})
        assert sa._obviously_not_an_alert({"url": "https://x/a", "title": "Skip to content"})
        assert sa._obviously_not_an_alert({"url": "https://x/a", "title": "Next page »"})
        assert sa._obviously_not_an_alert({"url": "https://x/a", "title": "Current page 1"})

    def test_real_alert_titles_pass(self):
        assert not sa._obviously_not_an_alert({"url": "https://x/news-and-alerts/ato-impersonation", "title": "Scam alert: ATO and myGov impersonation"})


def _analysis(tier, severity, relevance, verified_ongoing=False, verified_evidence=""):
    return {"tier": tier, "severity": severity, "audience": "consumer", "australianRelevance": relevance, "australianRelevanceReason": "",
            "severityReason": "r", "confidence": "high", "facts": {}, "sections": {}, "analysisVersion": sa.ANALYSIS_VERSION,
            "verifiedOngoing": verified_ongoing, "verifiedOngoingEvidence": verified_evidence, "verifiedOngoingAt": None}


class TestGrowlRule:
    def _row(self):
        from core.db import now_utc
        return {"source_id": "scamwatch", "title": "Scam alert: X", "url": "https://x/news-and-alerts/x", "summary": "s",
                "content_type": "official_advice", "trust_status": "recognised_government", "last_checked_at": now_utc()}

    def test_confirmed_au_high_with_ongoing_growls(self):
        """An undated confirmed-AU high alert growls only when it has verified ongoing activity."""
        from core.db import now_utc
        built = ga._alert(self._row(), {"name": "Scamwatch"},
                          _analysis("specific_scam", "HIGH", "confirmed", verified_ongoing=True, verified_evidence="Scammers are actively targeting."),
                          now_utc())
        assert built["growling"] is True and built["severity"] == "HIGH"

    def test_confirmed_au_high_without_ongoing_does_not_growl(self):
        """An undated confirmed-AU high alert without verified ongoing activity does not growl."""
        from core.db import now_utc
        built = ga._alert(self._row(), {"name": "Scamwatch"}, _analysis("specific_scam", "HIGH", "confirmed"), now_utc())
        assert built["growling"] is False

    def test_education_never_growls(self):
        from core.db import now_utc
        built = ga._alert(self._row(), {"name": "Scamwatch"}, _analysis("general_education", "LOW", "confirmed"), now_utc())
        assert built["growling"] is False and built["tier"] == "general_education"

    def test_overseas_potential_without_date_does_not_growl(self):
        from core.db import now_utc
        row = self._row(); row["published_at"] = None
        built = ga._alert(row, {"name": "FTC"}, _analysis("specific_scam", "HIGH", "potential"), now_utc())
        assert built["growling"] is False  # stale/undated overseas technique must not hold a growl
