from services.higgins.slm_timing import stage_budget_seconds
import pytest

def test_window_planning_floor_ceiling_and_invalid_measurements():
    assert stage_budget_seconds(1, 1) == 90
    assert stage_budget_seconds(3, 60) == 240
    assert stage_budget_seconds(30, 90) == 300
    with pytest.raises(ValueError):
        stage_budget_seconds(0)
