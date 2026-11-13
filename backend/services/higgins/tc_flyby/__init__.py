"""Historical import names resolve to the canonical Hawkeye modules.

No second investigator, module state, cache or scoring implementation exists.
Persisted record compatibility is handled by hawkeye_record separately.
"""
import importlib
import sys

from services.higgins import tc_hawkeye

for name in ("checks", "decide", "evidence_evaluation", "finding_rules", "findings_brief",
             "mechanisms", "official", "patterns", "playbook_runner", "playbooks", "report",
             "scoring", "search", "taxonomy", "triage"):
    sys.modules[__name__ + "." + name] = importlib.import_module("services.higgins.tc_hawkeye." + name)
sys.modules[__name__] = tc_hawkeye
