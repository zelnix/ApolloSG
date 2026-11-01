import json
from pathlib import Path
from urllib.parse import urlparse

from services import government_alerts, learning
from services.higgins import context_tools


ROOT = Path(__file__).resolve().parents[2]


def test_learning_library_has_35_backend_owned_articles():
    package = json.loads((ROOT / "backend" / "content" / "learning_catalogue_au.json").read_text())
    assert len(package["articles"]) >= 35
    assert len({article["slug"] for article in package["articles"]}) == len(package["articles"])
    assert all(len(article["signs"]) >= 3 and len(article["actions"]) >= 3 and len(article["recovery"]) >= 3 for article in package["articles"])
    assert "SEEDS" not in (ROOT / "backend" / "services" / "learning.py").read_text()
    assert "import_learning_catalogue.py" in {path.name for path in (ROOT / "backend" / "scripts").iterdir()}


def test_consumer_learning_bundle_contains_no_article_bodies():
    source = (ROOT / "frontend" / "app" / "higgins" / "learning.tsx").read_text()
    assert "Urgency and pressure" not in source
    assert "Scammers rely on a believable story" not in source
    assert "learningArticles(" in source


def test_registered_chat_context_tools_are_read_only_and_bounded():
    assert set(context_tools.READERS) == {
        "get_protection_summary", "get_recent_cases", "get_last_relevant_outcome", "get_saved_reports",
        "get_recent_patrol_outcomes", "get_user_learning_preferences", "get_new_scams_digest",
        "get_product_capabilities", "get_gate_states", "get_learn_catalogue",
    }
    chat_source = (ROOT / "backend" / "services" / "higgins" / "chat.py").read_text()
    for forbidden in ("coordinator", "investigation_evidence", "web_search", "url_fetch", "file_scrape"):
        assert forbidden not in chat_source


def test_new_scams_sources_and_fallback_are_recognised_government_only():
    package = json.loads((ROOT / "backend" / "content" / "learning_catalogue_au.json").read_text())
    government = {source["sourceId"]: source for source in package["sources"] if source["governmentAuthority"]}
    assert {feed["sourceId"] for feed in package["feeds"]}.issubset(government)
    # Approved international expansion (AU/US/UK/EU): the invariant is that every feed stays inside its own
    # recognised authority's host allowlist and is always reviewed — never a fixed single-country list.
    for feed in package["feeds"]:
        assert urlparse(feed["url"]).hostname in government[feed["sourceId"]]["allowedHosts"]
        assert feed["reviewQueuePolicy"] == "always_review"


def test_history_is_persisted_by_the_projector_before_case_cleanup():
    projector = (ROOT / "backend" / "services" / "investigation_projector.py").read_text()
    assert "higgins_investigation_history.update_one" in projector
    assert '"conclusion": overview,' in projector
    assert '"deleted": False' in projector