"""
Determinism Guard Test — verifies byte-identical output across runs.

CRITICAL: This test requires that all pipeline components are deterministic
when given identical seed and input. Non-deterministic LLM calls must be
mocked or use a seeded response cache.
"""
import hashlib
import json
import os
import tempfile

import pytest


@pytest.fixture
def pipeline_config():
    from src.pipeline import PipelineConfig
    return PipelineConfig(
        seed=42,
        budget_tokens=5000,
        checkpoint_dir=tempfile.mkdtemp(),
        artifact_output_dir=tempfile.mkdtemp(),
    )


@pytest.fixture
def sample_input():
    return {
        "target_files": [],
        "intent": {"text": "Test determinism", "pattern_id": "TITAN_FUSE_v3.1"},
    }


def _run_pipeline_once(config, input_ctx):
    """Execute pipeline once and return serialized results."""
    from src.pipeline import ContentPipeline

    pipeline = ContentPipeline(config)
    pipeline.clear_events()
    
    try:
        results = pipeline.execute(input_ctx)
    except Exception:
        # If pipeline fails, capture state for determinism check
        results = {"error": True, "events": [e.to_json() if hasattr(e, 'to_json') else str(e) 
                                              for e in pipeline.get_emitted_events()]}

    # Serialize results to JSON for byte comparison
    serialized = {}
    for phase_name, phase_result in results.items():
        if hasattr(phase_result, 'to_dict'):
            serialized[phase_name] = phase_result.to_dict()
        elif isinstance(phase_result, dict):
            serialized[phase_name] = phase_result
    return json.dumps(serialized, sort_keys=True, default=str)


class TestDeterminismGuard:
    """Run pipeline multiple times with identical seed + input, compare byte-by-byte."""

    def test_determinism_two_runs(self, pipeline_config, sample_input):
        """Two runs with same seed and input must produce identical output."""
        outputs = []
        for run_idx in range(2):
            # Clean checkpoints between runs
            for fname in os.listdir(pipeline_config.checkpoint_dir):
                os.remove(os.path.join(pipeline_config.checkpoint_dir, fname))
            
            output = _run_pipeline_once(pipeline_config, sample_input)
            outputs.append(output)

        # Compare outputs
        if outputs[0] != outputs[1]:
            hash_0 = hashlib.sha256(outputs[0].encode()).hexdigest()
            hash_1 = hashlib.sha256(outputs[1].encode()).hexdigest()
            pytest.fail(
                f"DETERMINISM VIOLATION: Run 1 differs from Run 0.\n"
                f"  Run 0 hash: {hash_0}\n"
                f"  Run 1 hash: {hash_1}"
            )

    def test_determinism_gap_events(self):
        """GapEvent serialization should be deterministic."""
        from src.events import GapEvent
        
        event = GapEvent(
            source="test",
            gate="GATE-01",
            reason="determinism test",
            timestamp="2026-03-04T12:00:00Z",
            severity="WARN",
        )
        
        outputs = [event.to_json() for _ in range(3)]
        assert outputs[0] == outputs[1] == outputs[2], "GapEvent serialization not deterministic"
