"""Integration tests — end-to-end pattern flow validation."""
import json
import os
import tempfile

import pytest


# =====================================================================
# Test TITAN_FUSE_v3.1 full flow
# =====================================================================
class TestTitanFusePattern:
    """End-to-end: input → classifier → router → pipeline → output."""

    def test_titan_fuse_pattern_registered(self):
        """Verify TITAN_FUSE_v3.1 is in the registry."""
        import yaml
        
        reg_path = "config/prompt_registry.yaml"
        if not os.path.exists(reg_path):
            pytest.skip("prompt_registry.yaml not found")
        
        with open(reg_path, "r") as f:
            registry = yaml.safe_load(f)
        
        assert "TITAN_FUSE_v3.1" in registry.get("patterns", {})

    def test_pipeline_init_phase(self):
        """Test INIT phase execution."""
        from src.pipeline import ContentPipeline, PipelineConfig
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config = PipelineConfig(checkpoint_dir=tmpdir)
            pipeline = ContentPipeline(config)
            
            # INIT should work even without target files
            # It will fail on nav_map but that's expected
            try:
                result = pipeline._phase_init({"target_files": []})
                assert result.phase.value == "INIT"
            except Exception as e:
                # Expected to fail without nav_map.json
                assert "nav_map" in str(e).lower() or "GATE-00" in str(e)


# =====================================================================
# Test GapEvent emission on gate failures
# =====================================================================
class TestGapEventOnGateFailure:
    def test_gate_failure_produces_gap_event(self):
        """Verify that a GATE failure emits a GapEvent."""
        from src.pipeline import ContentPipeline, PipelineConfig
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config = PipelineConfig(
                checkpoint_dir=tmpdir,
                nav_map_path="/nonexistent/nav_map.json"
            )
            pipeline = ContentPipeline(config)
            pipeline.clear_events()

            with pytest.raises(Exception):
                pipeline._phase_init({"target_files": []})

            events = pipeline.get_emitted_events()
            assert len(events) > 0, "Gate failure should emit at least one GapEvent"

    def test_halt_with_gap_emits_event(self):
        """FIX-02: Verify _halt_with_gap emits event before raising."""
        from src.pipeline import ContentPipeline, PipelineConfig
        
        config = PipelineConfig()
        pipeline = ContentPipeline(config)
        pipeline.clear_events()

        with pytest.raises(Exception):
            pipeline._halt_with_gap("TEST", "GATE-XX", "Test halt")

        events = pipeline.get_emitted_events()
        assert len(events) == 1, "_halt_with_gap should emit exactly one event"
        assert events[0].gate == "GATE-XX"
        assert events[0].reason == "Test halt"


# =====================================================================
# Test fallback routing
# =====================================================================
class TestFallbackRouting:
    def test_no_pattern_match_falls_back(self):
        """Test that unknown patterns don't crash the system."""
        from src.orchestrator.universal_router import UniversalRouter
        
        router = UniversalRouter(config={})
        result = router.process("Random query with no specific pattern")
        
        assert result is not None
        assert result.success or result.error is not None
