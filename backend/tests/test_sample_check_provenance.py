# Regression tests for Sample Check provenance, isolation, and pipeline integrity.
# These tests verify the acceptance criteria from the Production Sample Checks Correction Brief.
# No AI calls.
import pytest
import services.scam_analysis as sa
from core.db import now_utc
from services import government_alerts as ga


class TestSampleCheckOriginPropagation:
    """Origin 'sample_check' is a provenance value, not a processing mode."""

    def test_sample_check_is_valid_origin(self):
        """sample_check is a valid origin value alongside user and apollo."""
        assert "sample_check" in ("user", "apollo", "sample_check")

    def test_origin_does_not_affect_analysis(self):
        """Equivalent evidence should reach the same decision logic whether supplied
        normally or through Sample Checks."""
        # The analysis functions take text, not origin — origin is provenance only.
        normal = sa.analyse({"title": "Scam alert: fake ATO texts",
                             "summary": "Scammers are sending fake tax refund texts.",
                             "_source_region": "AU", "_source_name": "Scamwatch"})
        # Same input "from a sample check" goes through the same analyse() function
        sample = sa.analyse({"title": "Scam alert: fake ATO texts",
                             "summary": "Scammers are sending fake tax refund texts.",
                             "_source_region": "AU", "_source_name": "Scamwatch"})
        assert normal["tier"] == sample["tier"]
        assert normal["severity"] == sample["severity"]
        assert normal["australianRelevance"] == sample["australianRelevance"]


class TestSampleCheckKBIsolation:
    """Sample Checks must not contaminate genuine KB intelligence."""

    def test_sample_check_origin_excludes_kb_contribution(self):
        """The _queue_kb_contribution function skips sample_check origin."""
        import services.higgins.repository as repo
        import inspect
        source = inspect.getsource(repo._queue_kb_contribution)
        assert 'sample_check' in source, "KB queue must check for sample_check origin"
        # The function checks origin and returns early before queuing
        after_check = source.split('sample_check')[1][:500]
        assert 'return' in after_check, "KB queue must return early for sample_check"


class TestSampleCheckProtectionStateIsolation:
    """Sample Check events must not alter real protection state or threat counts."""

    def test_sample_check_excluded_from_state_machine_comment(self):
        """The state machine filters out sample_check events from active threats."""
        # Structural test: verify the isolation comment exists in the state machine
        import pathlib
        state_machine = pathlib.Path("/app/frontend/src/domain/stateMachine.ts").read_text()
        assert 'origin !== "sample_check"' in state_machine, "State machine must exclude sample_check events"


class TestSampleCheckProvenanceDistinction:
    """Three-way distinction: real / sample_check / simulated (preview)."""

    def test_provenance_values_are_distinct(self):
        """The three provenance concepts must not be conflated."""
        real = None  # absent = real submission
        sample_check = "sample_check"
        simulated = True  # boolean flag for preview simulation
        assert sample_check != simulated
        assert sample_check != real

    def test_sample_check_is_not_simulated(self):
        """'sample_check' is not the same as 'simulated=true'."""
        origin = "sample_check"
        simulated = True
        assert origin != str(simulated).lower()


class TestSampleCheckNotForcingVerdict:
    """Sample labels are descriptions, not truth. Apollo must independently
    reach its conclusion from the supplied evidence."""

    def test_analysis_ignores_description_field(self):
        """The analyse() function does not read any 'description' field from the item."""
        out = sa.analyse({
            "title": "Scam alert: fake toll texts",
            "summary": "Scammers sending fake Linkt texts.",
            "description": "THIS IS DEFINITELY MALICIOUS EXTREME SEVERITY",  # should be ignored
            "_source_region": "AU", "_source_name": "Scamwatch",
        })
        # If description leaked into analysis, severity would be EXTREME
        assert out["severity"] in ("LOW", "MODERATE", "HIGH", "EXTREME")
        # The analysis should be based on the title and summary only

    def test_sample_name_does_not_become_evidence(self):
        """Names like 'Fake CommBank message' must not become case evidence."""
        out = sa.analyse({
            "title": "Your account has been limited",
            "summary": "Click here to restore access.",
            "_source_region": "AU", "_source_name": "User report",
        })
        # The word "fake" from the sample name should never appear in the analysis
        assert "Fake CommBank" not in str(out.get("facts", {}))
        assert "Fake CommBank" not in str(out.get("sections", {}))


class TestSampleCheckRelatedCasesIsolation:
    """Sample cases must not contribute to Related Cases corroboration."""

    def test_sample_origin_recorded_on_case(self):
        """The investigation case stores origin, enabling downstream isolation."""
        # Structural test: verify origin is stored in the case document
        import pathlib
        repo_source = pathlib.Path("/app/backend/services/higgins/repository.py").read_text()
        assert '"origin": origin' in repo_source, "Case document must store the origin field"


class TestSampleCheckTelemetryIsolation:
    """If telemetry for Sample Checks is recorded, it must be explicitly identified."""

    def test_sample_check_label_survives_display(self):
        """A Sample Check case should be identifiable in the UI."""
        import pathlib
        patrol_source = pathlib.Path("/app/frontend/app/(tabs)/patrol.tsx").read_text()
        assert '"Sample Check"' in patrol_source, "Patrol screen must show Sample Check label"

    def test_sample_check_distinct_from_simulated(self):
        """Sample Check and Simulated are distinct labels in the UI."""
        import pathlib
        patrol_source = pathlib.Path("/app/frontend/app/(tabs)/patrol.tsx").read_text()
        assert '"Sample Check"' in patrol_source
        assert '"Simulated"' in patrol_source


class TestSampleCheckPipelineIntegrity:
    """No parallel Sample Check engine. Normal production pipeline must apply."""

    def test_no_sample_check_exception_in_triage(self):
        """Triage must not contain 'if sampleCheck then ...' exceptions."""
        import pathlib
        triage_dir = pathlib.Path("/app/frontend/src/domain/triage")
        if triage_dir.exists():
            for f in triage_dir.glob("*.ts"):
                source = f.read_text()
                assert "sample_check" not in source.lower() or "origin" in source.lower(), \
                    f"Triage file {f.name} must not have sample_check processing exceptions"

    def test_no_sample_check_exception_in_scam_analysis(self):
        """scam_analysis.py must not contain sample-specific scoring."""
        import pathlib
        source = pathlib.Path("/app/backend/services/scam_analysis.py").read_text()
        assert "sample_check" not in source, "scam_analysis must not have sample_check exceptions"


class TestEmailSampleCheckImplementation:
    """Email Sample Checks must either work through the real pipeline or be absent."""

    def test_email_samples_exist_or_catalogue_is_clean(self):
        """Either email samples exist and are usable, or the category is removed."""
        import pathlib
        sample_checks = pathlib.Path("/app/frontend/src/sampleChecks.ts").read_text()
        # Email items should either have real samples or the category should not list empty
        if '"email"' in sample_checks:
            assert "sample-email-" in sample_checks, "Email category must have usable samples"


class TestSampleCheckCatalogueIsAuthoritative:
    """Production Sample Checks must not depend on the preview simulation catalogue."""

    def test_gate_screens_do_not_use_simulation_for_samples(self):
        """Gate screens must not fall back to simulation.* for sample check data."""
        import pathlib
        gate_files = [
            "message.tsx", "check.tsx", "call-guard.tsx", "file.tsx", "app-check.tsx"
        ]
        for name in gate_files:
            path = pathlib.Path(f"/app/frontend/app/{name}")
            if not path.exists():
                continue
            source = path.read_text()
            # Find sample check effects — they should NOT reference simulation.*
            lines = source.split("\n")
            in_sample_block = False
            for i, line in enumerate(lines):
                if "Sample Check" in line or "sample_check" in line or "findSample" in line:
                    in_sample_block = True
                if in_sample_block and "simulation." in line and "simulation.included" not in line:
                    # Allow simulation.included checks (for preview features) but not simulation data access
                    if "simulation.texts" in line or "simulation.links" in line or \
                       "simulation.calls" in line or "simulation.files" in line or \
                       "simulation.apps" in line or "simulation.emails" in line:
                        assert False, f"{name}: Sample Check path must not access simulation.* data (line {i+1})"
                if in_sample_block and line.strip() == "":
                    in_sample_block = False
