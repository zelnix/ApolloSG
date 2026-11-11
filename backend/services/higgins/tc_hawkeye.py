"""TC Hawkeye investigation service entry point; historical package retained for compatibility."""
from services.higgins.tc_flyby import (  # noqa: F401
    HawkeyeOutcome, FlyByOutcome, investigate, established,
    PREGATHERED_ITEM_ID, CHECKS_ITEM_ID, BRIEF_ITEM_ID,
)
