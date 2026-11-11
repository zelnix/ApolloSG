"""Compatibility import for the historical TC FlyBy module path.

Implementation: services.higgins.tc_hawkeye.evidence_evaluation. Persisted case identifiers are unchanged.
"""
import importlib as _importlib
import sys as _sys
_sys.modules[__name__] = _importlib.import_module("services.higgins.tc_hawkeye.evidence_evaluation")
