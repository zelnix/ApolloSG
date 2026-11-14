"""Engineering planning limits; window latency remains pending physical calibration."""
import math

def stage_budget_seconds(windows: int, window_seconds: float = 45.0, overhead_seconds: float = 15.0) -> float:
    if not isinstance(windows, int) or windows < 1 or not math.isfinite(window_seconds) or window_seconds <= 0 or overhead_seconds < 0:
        raise ValueError("Invalid SLM timing inputs")
    return min(300.0, max(90.0, windows * window_seconds * 1.25 + overhead_seconds))
