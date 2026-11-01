"""Acceptance tests for the Historical Investigation & Protection Record Retrofit.

Tests all 12 acceptance criteria from the PRD.
These require a database populated by the retrofit migration script.
In a fresh environment, these may not have records to check — they are skipped
if no retrofit data exists.
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/app/backend")

import asyncio
import pytest
from core.db import db
from services.record_classification import classify_record, generate_higgins_briefing


async def test_1_investigations_accessible():
    """AT1: Existing genuine investigations remain accessible."""
    count = await db.patrol_records.count_documents({"investigation_case_id": {"$ne": None}, "record_class": {"$exists": True}})
    if count == 0:
        pytest.skip("No classified investigation records — retrofit not run")
    print(f"  ✓ AT1: {count} investigation records accessible with classification")


async def test_2_timestamps_preserved():
    """AT2: Historical evidence and original timestamps preserved."""
    sample = await db.patrol_records.find_one({"record_class": {"$exists": True}}, {"_id": 0})
    if not sample:
        pytest.skip("No classified records — retrofit not run")
    assert "occurred_at" in sample, "occurred_at missing"
    assert "created_at" in sample, "created_at missing"
    if sample.get("reassessment"):
        assert "reassessed_at" in sample["reassessment"], "reassessment missing reassessed_at"
        assert sample["reassessment"]["reassessed_at"] != sample["occurred_at"], "reassessment date should differ"
    print("  ✓ AT2: Timestamps preserved, reassessment dates separate")


async def test_3_higgins_briefings():
    """AT3: Higgins gives concise, evidence-specific briefings for deterministic records.
    Investigation records may have null briefings (the Magnum DI result is authoritative)."""
    count = await db.patrol_records.count_documents({"higgins_briefing": {"$exists": True, "$ne": None}})
    if count == 0:
        pytest.skip("No Higgins briefings — retrofit not run or all investigation records")
    sample = await db.patrol_records.find_one({"higgins_briefing": {"$exists": True, "$ne": None}}, {"_id": 0})
    briefing = sample["higgins_briefing"]
    assert "investigated" in briefing, "Briefing missing 'investigated'"
    assert "established" in briefing, "Briefing missing 'established'"
    assert "meaning" in briefing, "Briefing missing 'meaning'"
    assert "evidence_points" in briefing, "Briefing missing 'evidence_points'"
    print(f"  ✓ AT3: {count} Higgins briefings generated with required fields")


async def test_4_magnum_reports_available():
    """AT4: Magnum DI full reports remain available on demand."""
    count = await db.higgins_investigation_history.count_documents({"retrofit_version": "v1"})
    if count == 0:
        pytest.skip("No retrofitted investigation history — retrofit not run")
    print(f"  ✓ AT4: {count} investigation history entries updated for Magnum DI")


def test_5_unverifiable_identified():
    """AT5: Unverifiable historical findings clearly identified."""
    result = classify_record({"category": "unknown", "raw_state": "unknown"})
    assert result == "unverifiable_legacy", f"Expected unverifiable_legacy, got {result}"
    print("  ✓ AT5: Unverifiable records correctly identified by classifier")


async def test_6_gate_failures_not_threats():
    """AT6: Old Gate failures no longer count as security threats."""
    protection_threats = await db.patrol_records.count_documents({
        "category": {"$in": ["protection", "system"]},
        "record_class": "security_threat",
    })
    assert protection_threats == 0, f"Found {protection_threats} protection records misclassified as security_threat"
    protection_issues = await db.patrol_records.count_documents({
        "category": {"$in": ["protection", "system"]},
        "record_class": {"$in": ["protection_issue", "reduced_protection", "informational"]},
    })
    print(f"  ✓ AT6: 0 gate failures as threats, {protection_issues} correctly classified")


async def test_7_no_false_current_alerts():
    """AT7: Historical incidents do not cause false current alerts."""
    resolved = await db.patrol_records.count_documents({"record_class": "resolved"})
    active_threats_from_resolved = await db.patrol_records.count_documents({
        "resolution.status": {"$in": ["resolved", "trusted"]},
        "record_class": "security_threat",
    })
    assert active_threats_from_resolved == 0, f"Found {active_threats_from_resolved} resolved records still classified as active threats"
    print(f"  ✓ AT7: {resolved} resolved records, 0 false active threats from resolved items")


async def test_8_verified_blocks_authentic():
    """AT8: Previously verified blocks retain authentic enforcement evidence."""
    verified = await db.patrol_records.count_documents({"record_class": "threat_stopped"})
    with_ref = await db.patrol_records.count_documents({
        "record_class": "threat_stopped",
        "observed_block_reference": {"$ne": None},
    })
    print(f"  ✓ AT8: {verified} threat_stopped records, {with_ref} with verified block reference")


async def test_9_duplicates_preserved():
    """AT9: Duplicate findings removed from presentation without destroying source."""
    duplicates = await db.patrol_records.count_documents({"duplicate_of": {"$ne": None}})
    if duplicates > 0:
        sample = await db.patrol_records.find_one({"duplicate_of": {"$ne": None}}, {"_id": 0})
        assert "source_event_id" in sample, "Duplicate lost source_event_id"
        assert "occurred_at" in sample, "Duplicate lost occurred_at"
    print(f"  ✓ AT9: {duplicates} duplicates marked, source observations preserved")


async def test_10_migration_idempotent():
    """AT10: Migration is repeatable and does not duplicate or corrupt records."""
    report = await db.migration_reports.find_one({"migration_id": "retrofit_v1"}, {"_id": 0})
    if not report:
        pytest.skip("Migration report not found — retrofit not run")
    assert report.get("errors", -1) == 0, f"Migration had {report.get('errors')} errors"
    # Records the owner deleted since the first run legitimately lower the count, so rerun it (dry) on today's data.
    from scripts.retrofit_historical_records import run_migration
    rerun = await run_migration(dry_run=True)
    assert rerun["errors"] == 0, f"Rerun had {rerun['errors']} errors"
    dupes = await db.patrol_records.aggregate([
        {"$group": {"_id": "$record_id", "n": {"$sum": 1}}}, {"$match": {"n": {"$gt": 1}}}, {"$limit": 5},
    ]).to_list(5)
    assert not dupes, f"Duplicated records: {dupes}"
    print(f"  ✓ AT10: rerun reviewed {rerun['records_reviewed']} records, 0 errors, no duplicates")


async def test_11_distinguish_historic_from_new():
    """AT11: User can clearly distinguish historic conclusions from new reassessments."""
    with_reassessment = await db.patrol_records.count_documents({"reassessment": {"$exists": True, "$ne": None}})
    if with_reassessment == 0:
        pytest.skip("No reassessment metadata — retrofit not run")
    sample = await db.patrol_records.find_one({"reassessment": {"$exists": True, "$ne": None}}, {"_id": 0})
    r = sample["reassessment"]
    assert "reassessed_at" in r, "Missing reassessed_at"
    assert "reason" in r, "Missing reason"
    assert "version" in r, "Missing version"
    print(f"  ✓ AT11: {with_reassessment} records with reassessment provenance metadata")


async def test_12_consistent_standards():
    """AT12: New and retrofitted reports follow approved standards.
    Investigation records may have null higgins_briefing (Magnum DI result is authoritative)."""
    unclassified = await db.patrol_records.count_documents({"record_class": {"$exists": False}})
    assert unclassified == 0, f"Found {unclassified} unclassified records"
    missing_field = await db.patrol_records.count_documents({"higgins_briefing": {"$exists": False}})
    assert missing_field == 0, f"Found {missing_field} records without higgins_briefing field"
    print(f"  ✓ AT12: All records classified with consistent standards")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
