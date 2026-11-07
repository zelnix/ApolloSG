"""Records saved under TC Hawkeye's old internal name ("teddy") move to its current names, and nothing else changes."""
import uuid

from core.db import db
from services.higgins import repository as repo
from services.higgins.tc_flyby import legacy_names


def test_old_names_are_replaced_everywhere_in_a_record():
    old = {"teddy": {"answeredBy": "teddy_kb", "teddyTokens": 0, "checks": [{"route": "apollo_kb"}]}, "answeredBy": "teddy_search",
           "items": ["teddy-di-checks", "teddy-di-brief", "a message about teddy bears"]}
    assert legacy_names.renamed(old) == {"tc_flyby": {"answeredBy": "tc_flyby_kb", "flybyTokens": 0, "checks": [{"route": "apollo_kb"}]},
                                         "answeredBy": "tc_flyby_search",
                                         "items": ["tc-flyby-di-checks", "tc-flyby-di-brief", "a message about teddy bears"]}


async def test_a_case_saved_under_the_old_names_is_moved_once():
    owner, case_id = f"flyby-legacy-{uuid.uuid4().hex[:8]}", uuid.uuid4().hex
    record = {"decision": {"answeredBy": "teddy_official", "outcome": "concerning"}, "checks": [{"route": "official_source"}]}
    await db.investigation_cases.insert_one({"owner_id": owner, "case_id": case_id, "teddy_ciphertext": repo.enc_json(record),
                                             "routing": {"answeredBy": "teddy_official", "outcome": "concerning",
                                                         "teddy": {"answeredBy": "teddy_official", "resolved": True}}})
    await db.investigation_evidence.insert_one({"owner_id": owner, "case_id": case_id, "client_item_id": "teddy-di-checks"})
    await db.gemini_usage.insert_one({"correlation_id": f"case-{case_id}", "purpose": "teddy_search"})
    try:
        counts = await legacy_names.migrate()
        assert counts["cases"] >= 1 and counts["teddy-di-checks"] >= 1 and counts["gemini_usage"] >= 1
        doc = await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id}, {"_id": 0})
        assert "teddy_ciphertext" not in doc and "teddy" not in doc["routing"]
        assert doc["routing"] == {"answeredBy": "tc_flyby_official", "outcome": "concerning",
                                  "tc_flyby": {"answeredBy": "tc_flyby_official", "resolved": True}}
        assert repo.dec_json(doc["tc_flyby_ciphertext"]) == {"decision": {"answeredBy": "tc_flyby_official", "outcome": "concerning"},
                                                             "checks": [{"route": "official_source"}]}
        assert (await db.investigation_evidence.find_one({"owner_id": owner, "case_id": case_id}))["client_item_id"] == "tc-flyby-di-checks"
        assert (await db.gemini_usage.find_one({"correlation_id": f"case-{case_id}"}))["purpose"] == "tc_flyby_search"
        await legacy_names.migrate()
        assert (await db.investigation_cases.find_one({"owner_id": owner, "case_id": case_id}, {"_id": 0})) == doc, "a second run changes nothing"
        assert "teddy_search_cache" not in await db.list_collection_names()
    finally:
        await db.investigation_cases.delete_many({"owner_id": owner})
        await db.investigation_evidence.delete_many({"owner_id": owner})
        await db.gemini_usage.delete_many({"correlation_id": f"case-{case_id}"})
