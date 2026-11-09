"""Real Mongo concurrency acceptance tests. Never contact Google."""
import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from core.db import db
from services import google_web_risk as wr


@pytest.mark.asyncio
async def test_atomic_testing_budget_under_concurrency():
    month = "test-" + uuid.uuid4().hex
    with patch.object(wr, "period", return_value=month), patch.object(wr, "TEST_BUDGET", 7):
        try:
            results = await asyncio.gather(*(wr.reserve(testing=True) for _ in range(60)))
            assert results.count(True) == 7
            assert results.count(False) == 53
            assert None not in results
            row = await db.web_risk_quota.find_one({"_id": month})
            assert row["reserved"] == 7
            assert row["testing_reserved"] == 7
            assert row["production_reserved"] == 0
        finally:
            await db.web_risk_quota.delete_one({"_id": month})


@pytest.mark.asyncio
async def test_both_budgets_share_global_cutoff():
    month = "test-" + uuid.uuid4().hex
    with patch.object(wr, "period", return_value=month), patch.object(wr, "TEST_BUDGET", 6), patch.object(wr, "PRODUCTION_BUDGET", 6), patch.object(wr, "OPERATIONAL_STOP", 9):
        try:
            results = await asyncio.gather(
                *(wr.reserve(testing=True) for _ in range(15)),
                *(wr.reserve(testing=False) for _ in range(15)),
            )
            assert results.count(True) == 9
            assert results.count(False) == 21
            assert None not in results
            row = await db.web_risk_quota.find_one({"_id": month})
            assert row["reserved"] == 9
            assert row["testing_reserved"] <= 6
            assert row["production_reserved"] <= 6
            assert row["testing_reserved"] + row["production_reserved"] == 9
        finally:
            await db.web_risk_quota.delete_one({"_id": month})


@pytest.mark.asyncio
async def test_legacy_quota_row_respects_previous_reservations():
    month = "test-" + uuid.uuid4().hex
    with patch.object(wr, "period", return_value=month), patch.object(wr, "OPERATIONAL_STOP", 9):
        try:
            await db.web_risk_quota.insert_one({"_id": month, "reserved": 8})
            assert await wr.reserve(testing=True) is True
            assert await wr.reserve(testing=False) is False
            row = await db.web_risk_quota.find_one({"_id": month})
            assert row["reserved"] == 9
            assert row["testing_reserved"] == 1
        finally:
            await db.web_risk_quota.delete_one({"_id": month})
