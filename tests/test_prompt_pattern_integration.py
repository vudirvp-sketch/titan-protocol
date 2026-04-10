"""Unit tests for prompt pattern integration — comprehensive functional tests."""
import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import yaml


# =====================================================================
# test_pattern_registry_load
# =====================================================================
class TestPatternRegistryLoad:
    """Verify 4 canonical patterns load correctly from registry."""

    @pytest.fixture
    def registry(self):
        reg_path = "config/prompt_registry.yaml"
        if not os.path.exists(reg_path):
            pytest.skip("prompt_registry.yaml not found — run Plan B first")
        with open(reg_path, "r") as f:
            return yaml.safe_load(f)

    def test_registry_has_patterns_key(self, registry):
        assert "patterns" in registry, "Registry missing 'patterns' key"

    def test_four_canonical_patterns_exist(self, registry):
        expected = {"TITAN_FUSE_v3.1", "GUARDIAN_v1.1", "AGENT_GEN_SPEC_v4.1", "DEP_AUDIT"}
        actual = set(registry["patterns"].keys())
        missing = expected - actual
        assert not missing, f"Missing canonical patterns: {missing}"

    def test_each_pattern_has_required_fields(self, registry):
        required = ["version", "description", "activation_triggers", "titan_mapping"]
        for pid, pattern in registry["patterns"].items():
            for field in required:
                assert field in pattern, f"Pattern {pid} missing field: {field}"

    def test_activation_triggers_are_lists(self, registry):
        for pid, pattern in registry["patterns"].items():
            triggers = pattern.get("activation_triggers", [])
            assert isinstance(triggers, list), f"Pattern {pid} triggers not a list"

    def test_titan_mapping_is_dict(self, registry):
        for pid, pattern in registry["patterns"].items():
            mapping = pattern.get("titan_mapping", {})
            assert isinstance(mapping, dict), f"Pattern {pid} titan_mapping not a dict"


# =====================================================================
# test_gap_event_serialization
# =====================================================================
class TestGapEventSerialization:
    """Verify GapEvent conforms to PAT-06 serialization."""

    def test_gap_event_to_json(self):
        from src.events import GapEvent

        event = GapEvent(
            source="ContentPipeline.INIT",
            gate="GATE-00",
            reason="Preflight check failed",
            timestamp="2026-03-04T00:00:00Z",
            severity="CRITICAL",
        )
        json_str = event.to_json()
        parsed = json.loads(json_str)

        assert parsed["source"] == "ContentPipeline.INIT"
        assert parsed["gate"] == "GATE-00"
        assert parsed["reason"] == "Preflight check failed"
        assert parsed["severity"] == "CRITICAL"

    def test_gap_event_pat06_fields(self):
        """PAT-06 requires: source, gate, reason, timestamp, severity."""
        from src.events import GapEvent

        event = GapEvent(
            source="test", gate="GATE-01", reason="test",
            timestamp="2026-03-04T00:00:00Z", severity="INFO",
        )
        data = json.loads(event.to_json())
        pat06_fields = {"source", "gate", "reason", "timestamp", "severity"}
        assert pat06_fields.issubset(set(data.keys())), \
            f"Missing PAT-06 fields: {pat06_fields - set(data.keys())}"

    def test_gap_event_roundtrip(self):
        from src.events import GapEvent

        original = GapEvent(
            source="test", gate="GATE-02", reason="roundtrip",
            timestamp="2026-03-04T00:00:00Z", severity="WARN",
        )
        json_str = original.to_json()
        restored = GapEvent.from_json(json_str)
        assert restored.source == original.source
        assert restored.gate == original.gate
        assert restored.reason == original.reason
        assert restored.severity == original.severity


# =====================================================================
# test_pipeline_infrastructure
# =====================================================================
class TestPipelineInfrastructure:
    """Verify pipeline infrastructure is properly set up."""

    def test_pipeline_phase_enum(self):
        from src.pipeline import PipelinePhase
        
        assert hasattr(PipelinePhase, 'INIT')
        assert hasattr(PipelinePhase, 'DISCOVER')
        assert hasattr(PipelinePhase, 'ANALYZE')
        assert hasattr(PipelinePhase, 'PLAN')
        assert hasattr(PipelinePhase, 'EXEC')
        assert hasattr(PipelinePhase, 'DELIVER')

    def test_pipeline_config_defaults(self):
        from src.pipeline import PipelineConfig
        
        config = PipelineConfig()
        assert config.max_validation_passes == 2
        assert config.budget_tokens == 50000

    def test_pipeline_error_hierarchy(self):
        from src.pipeline import PipelineError, GateFailedError, PhaseAbortedError
        
        assert issubclass(GateFailedError, PipelineError)
        assert issubclass(PhaseAbortedError, PipelineError)


# =====================================================================
# test_content_pipeline_init
# =====================================================================
class TestContentPipelineInit:
    """Verify ContentPipeline INIT phase."""

    def test_pipeline_creates_snapshot(self):
        from src.pipeline import ContentPipeline, PipelineConfig
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config = PipelineConfig(checkpoint_dir=tmpdir)
            pipeline = ContentPipeline(config)
            
            snapshot = pipeline._create_state_snapshot()
            assert "timestamp" in snapshot
            assert "files" in snapshot
            assert "config_checksums" in snapshot


# =====================================================================
# test_content_pipeline_discover
# =====================================================================
class TestContentPipelineDiscover:
    """Verify ContentPipeline DISCOVER phase."""

    def test_four_pass_strategy(self):
        from src.pipeline import ContentPipeline, PipelineConfig
        
        config = PipelineConfig()
        pipeline = ContentPipeline(config)
        
        # Create a temp file for testing
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('def test_function():\n    pass\n')
            temp_file = f.name
        
        try:
            grep_chunks = pipeline._pass_grep([temp_file])
            regex_chunks = pipeline._pass_regex([temp_file])
            ast_chunks = pipeline._pass_ast([temp_file])
            chunk_chunks = pipeline._pass_chunk([temp_file])
            
            assert isinstance(grep_chunks, list)
            assert isinstance(regex_chunks, list)
            assert isinstance(ast_chunks, list)
            assert isinstance(chunk_chunks, list)
        finally:
            os.unlink(temp_file)
