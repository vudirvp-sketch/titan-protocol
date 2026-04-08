"""
Tests for ITEM-MODEL-002: Token Attribution Per Gate

Tests cover:
- Tokens tracked per gate during gate_manager execution
- Sum of gate tokens matches total
- Attribution appears in metrics.json format
- Gate timing tracked correctly
"""

import pytest
import time
import json
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from src.observability.token_attribution import (
    TokenAttributor,
    get_token_attributor,
    init_token_attributor,
    start_gate,
    end_gate,
    get_attribution,
    get_total_tokens,
    reset_attribution,
    get_attribution_for_metrics,
    record_gate_usage,
)

from src.policy.gate_manager import (
    GateManager,
    GateType,
    GateResult,
    GateCheck,
    GateCheckResult,
)


class TestGetAttributionForMetrics:
    """Tests for get_attribution_for_metrics function."""

    def test_returns_correct_structure(self):
        """Test that function returns correct top-level structure."""
        init_token_attributor()
        reset_attribution()
        
        metrics = get_attribution_for_metrics()
        
        assert "token_attribution" in metrics
        assert "token_attribution_summary" in metrics
        assert isinstance(metrics["token_attribution"], dict)
        assert isinstance(metrics["token_attribution_summary"], dict)

    def test_summary_fields(self):
        """Test that summary contains all required fields."""
        init_token_attributor()
        reset_attribution()
        
        start_gate("GATE-00")
        end_gate("GATE-00", tokens_used=100, prompt_tokens=70, completion_tokens=30)
        
        metrics = get_attribution_for_metrics()
        summary = metrics["token_attribution_summary"]
        
        assert "total_tokens" in summary
        assert "total_prompt_tokens" in summary
        assert "total_completion_tokens" in summary
        assert "gate_count" in summary
        assert "total_calls" in summary
        
        assert summary["total_tokens"] == 100
        assert summary["total_prompt_tokens"] == 70
        assert summary["total_completion_tokens"] == 30
        assert summary["gate_count"] == 1
        assert summary["total_calls"] == 1

    def test_per_gate_breakdown(self):
        """Test that per-gate breakdown is included."""
        init_token_attributor()
        reset_attribution()
        
        # Record multiple gates
        start_gate("GATE-00")
        end_gate("GATE-00", tokens_used=100, prompt_tokens=70, completion_tokens=30)
        
        start_gate("GATE-01")
        end_gate("GATE-01", tokens_used=200, prompt_tokens=150, completion_tokens=50)
        
        metrics = get_attribution_for_metrics()
        attribution = metrics["token_attribution"]
        
        assert "GATE-00" in attribution
        assert "GATE-01" in attribution
        
        assert attribution["GATE-00"]["total_tokens"] == 100
        assert attribution["GATE-01"]["total_tokens"] == 200

    def test_json_serializable(self):
        """Test that output is JSON serializable for metrics.json."""
        init_token_attributor()
        reset_attribution()
        
        start_gate("GATE-00")
        end_gate("GATE-00", tokens_used=100)
        
        metrics = get_attribution_for_metrics()
        
        # Should not raise
        json_str = json.dumps(metrics)
        parsed = json.loads(json_str)
        
        assert parsed["token_attribution_summary"]["total_tokens"] == 100


class TestRecordGateUsage:
    """Tests for record_gate_usage convenience function."""

    def test_basic_recording(self):
        """Test basic gate usage recording."""
        init_token_attributor()
        reset_attribution()
        
        record_gate_usage("PRE_Policy_Check", tokens_used=0)
        
        attr = get_attribution()
        assert "PRE_Policy_Check" in attr
        assert attr["PRE_Policy_Check"]["total_tokens"] == 0

    def test_with_token_breakdown(self):
        """Test recording with prompt/completion breakdown."""
        init_token_attributor()
        reset_attribution()
        
        record_gate_usage(
            "GATE-00",
            tokens_used=150,
            prompt_tokens=100,
            completion_tokens=50
        )
        
        attr = get_attribution()
        assert attr["GATE-00"]["prompt_tokens"] == 100
        assert attr["GATE-00"]["completion_tokens"] == 50


class TestTokensTrackedPerGate:
    """Tests for tokens tracked per gate during gate execution."""

    def test_pre_exec_gates_tracked(self):
        """Test that pre-exec gates have token attribution tracked."""
        init_token_attributor()
        reset_attribution()
        
        manager = GateManager()
        
        # Create a simple context
        context = {
            "policies": {"test": {}},
            "execution_mode": "direct"
        }
        
        # Run pre-exec gates
        result = manager.run_pre_exec_gates(context)
        
        # Check attribution was recorded
        attribution = get_attribution()
        
        # Should have attribution for each pre-exec gate
        assert len(attribution) > 0
        
        # Check that gate IDs are prefixed with PRE_
        for gate_id in attribution.keys():
            assert gate_id.startswith("PRE_")

    def test_post_exec_gates_tracked(self):
        """Test that post-exec gates have token attribution tracked."""
        init_token_attributor()
        reset_attribution()
        
        manager = GateManager()
        
        context = {
            "policies": {"test": {}},
            "execution_mode": "direct"
        }
        output = {"result": "test"}
        
        # Run post-exec gates
        result = manager.run_post_exec_gates(context, output)
        
        # Check attribution was recorded
        attribution = get_attribution()
        
        # Should have attribution for each post-exec gate
        assert len(attribution) > 0
        
        # Check that gate IDs are prefixed with POST_
        for gate_id in attribution.keys():
            assert gate_id.startswith("POST_")

    def test_gate_timing_tracked(self):
        """Test that gate execution timing is tracked."""
        init_token_attributor()
        reset_attribution()
        
        start_gate("TIMING_TEST")
        time.sleep(0.01)  # 10ms
        end_gate("TIMING_TEST", tokens_used=0)
        
        attr = get_attribution()
        
        assert "TIMING_TEST" in attr
        assert attr["TIMING_TEST"]["total_duration_ms"] >= 10.0
        assert attr["TIMING_TEST"]["avg_duration_ms"] >= 10.0


class TestSumMatchesTotal:
    """Tests for validation that sum of gate tokens matches total."""

    def test_sum_matches_total_single_gate(self):
        """Test sum matches total for single gate."""
        init_token_attributor()
        reset_attribution()
        
        start_gate("GATE-00")
        end_gate("GATE-00", tokens_used=100, prompt_tokens=70, completion_tokens=30)
        
        metrics = get_attribution_for_metrics()
        
        attribution = metrics["token_attribution"]
        summary = metrics["token_attribution_summary"]
        
        calculated_total = sum(g["total_tokens"] for g in attribution.values())
        assert calculated_total == summary["total_tokens"]

    def test_sum_matches_total_multiple_gates(self):
        """Test sum matches total for multiple gates."""
        init_token_attributor()
        reset_attribution()
        
        gate_usages = {
            "GATE-00": (150, 100, 50),
            "GATE-01": (200, 150, 50),
            "GATE-02": (300, 200, 100),
        }
        
        for gate_id, (total, prompt, completion) in gate_usages.items():
            start_gate(gate_id)
            end_gate(gate_id, tokens_used=total, prompt_tokens=prompt, completion_tokens=completion)
        
        metrics = get_attribution_for_metrics()
        
        attribution = metrics["token_attribution"]
        summary = metrics["token_attribution_summary"]
        
        # Calculate sum of individual gates
        calculated_total = sum(g["total_tokens"] for g in attribution.values())
        calculated_prompt = sum(g["prompt_tokens"] for g in attribution.values())
        calculated_completion = sum(g["completion_tokens"] for g in attribution.values())
        
        # Verify sums match
        assert calculated_total == summary["total_tokens"]
        assert calculated_prompt == summary["total_prompt_tokens"]
        assert calculated_completion == summary["total_completion_tokens"]

    def test_sum_matches_total_multiple_calls(self):
        """Test sum matches total with multiple calls to same gate."""
        init_token_attributor()
        reset_attribution()
        
        # Multiple calls to same gate
        usages = [100, 150, 200, 50, 75]
        
        for tokens in usages:
            start_gate("GATE-00")
            end_gate("GATE-00", tokens_used=tokens)
        
        metrics = get_attribution_for_metrics()
        
        expected_total = sum(usages)
        assert metrics["token_attribution_summary"]["total_tokens"] == expected_total
        assert metrics["token_attribution"]["GATE-00"]["call_count"] == len(usages)


class TestAttributionInMetrics:
    """Tests for attribution inclusion in metrics output."""

    def test_metrics_format_valid(self):
        """Test that metrics format matches expected schema."""
        init_token_attributor()
        reset_attribution()
        
        start_gate("PRE_Policy_Check")
        end_gate("PRE_Policy_Check", tokens_used=0)
        
        start_gate("GATE-00")
        end_gate("GATE-00", tokens_used=150, prompt_tokens=100, completion_tokens=50)
        
        metrics = get_attribution_for_metrics()
        
        # Verify structure matches schema requirements
        assert isinstance(metrics["token_attribution"], dict)
        assert isinstance(metrics["token_attribution_summary"], dict)
        
        # Verify required summary fields
        summary = metrics["token_attribution_summary"]
        assert "total_tokens" in summary
        assert "gate_count" in summary
        assert "total_calls" in summary
        
        # Verify per-gate required fields
        for gate_id, gate_data in metrics["token_attribution"].items():
            assert "prompt_tokens" in gate_data
            assert "completion_tokens" in gate_data
            assert "total_tokens" in gate_data
            assert "call_count" in gate_data

    def test_empty_attribution(self):
        """Test metrics with no attribution data."""
        init_token_attributor()
        reset_attribution()
        
        metrics = get_attribution_for_metrics()
        
        assert metrics["token_attribution"] == {}
        assert metrics["token_attribution_summary"]["total_tokens"] == 0
        assert metrics["token_attribution_summary"]["gate_count"] == 0
        assert metrics["token_attribution_summary"]["total_calls"] == 0

    def test_integration_with_full_flow(self):
        """Test integration with full gate manager flow."""
        init_token_attributor()
        reset_attribution()
        
        manager = GateManager()
        
        # Setup context for successful gate passes
        context = {
            "policies": {"policy1": {"enabled": True}},
            "user": {"permissions": ["read", "write"]},
            "required_permissions": [],
            "resources": {
                "required": {},
                "available": {}
            },
            "input": {},
            "input_schema": {},
            "budget": {
                "available": 10000,
                "required": 100
            },
            "execution_mode": "direct",
            "llm_params": {
                "temperature": 0.0,
                "top_p": 0.1,
                "seed": 42
            }
        }
        
        output = {
            "result": "success",
            "changes": [],
            "gaps": []
        }
        
        # Run full flow
        pre_result = manager.run_pre_exec_gates(context)
        post_result = manager.run_post_exec_gates(context, output)
        
        # Get attribution
        metrics = get_attribution_for_metrics()
        
        # Verify we have attribution data
        assert metrics["token_attribution_summary"]["gate_count"] > 0
        assert metrics["token_attribution_summary"]["total_calls"] > 0


class TestGateTimingTracked:
    """Tests for gate timing tracking."""

    def test_timing_recorded_for_each_gate(self):
        """Test that timing is recorded for each gate."""
        init_token_attributor()
        reset_attribution()
        
        # Track multiple gates with different timings
        gates = ["GATE-00", "GATE-01", "GATE-02"]
        
        for gate in gates:
            start_gate(gate)
            time.sleep(0.005)  # 5ms
            end_gate(gate, tokens_used=10)
        
        attribution = get_attribution()
        
        # Each gate should have timing data
        for gate in gates:
            assert attribution[gate]["total_duration_ms"] >= 5.0
            assert attribution[gate]["avg_duration_ms"] >= 5.0

    def test_timing_aggregates_multiple_calls(self):
        """Test that timing aggregates across multiple calls."""
        init_token_attributor()
        reset_attribution()
        
        # Multiple calls with delays
        for _ in range(3):
            start_gate("GATE-00")
            time.sleep(0.01)  # 10ms each
            end_gate("GATE-00", tokens_used=10)
        
        attribution = get_attribution()
        
        # Total duration should be at least 30ms
        assert attribution["GATE-00"]["total_duration_ms"] >= 30.0
        # Average should be around 10ms
        assert attribution["GATE-00"]["avg_duration_ms"] >= 10.0
        # Call count should be 3
        assert attribution["GATE-00"]["call_count"] == 3

    def test_timestamps_recorded(self):
        """Test that timestamps are recorded for gates."""
        init_token_attributor()
        reset_attribution()
        
        start_gate("GATE-00")
        end_gate("GATE-00", tokens_used=10)
        
        attribution = get_attribution()
        
        assert attribution["GATE-00"]["first_started_at"] is not None
        assert attribution["GATE-00"]["last_started_at"] is not None
        assert attribution["GATE-00"]["last_ended_at"] is not None


class TestGateManagerIntegration:
    """Tests for GateManager integration with token attribution."""

    def test_gate_manager_creates_attribution(self):
        """Test that GateManager creates attribution records."""
        init_token_attributor()
        reset_attribution()
        
        manager = GateManager()
        context = {
            "policies": {"test": {}},
            "execution_mode": "direct"
        }
        
        result = manager.run_pre_exec_gates(context)
        
        attribution = get_attribution()
        
        # Should have created attribution for gates
        assert len(attribution) > 0

    def test_gate_manager_handles_exceptions(self):
        """Test that attribution is cleaned up on exceptions."""
        init_token_attributor()
        reset_attribution()
        
        attributor = get_token_attributor()
        
        # Start a gate
        start_gate("GATE-00")
        
        # Simulate an exception scenario by using wrap_gate_execution
        def failing_func():
            raise RuntimeError("Test error")
        
        with pytest.raises(RuntimeError):
            attributor.wrap_gate_execution("GATE-01", failing_func, tokens_used=0)
        
        # GATE-00 should still be active (we didn't end it)
        # But we should be able to start GATE-01 again
        start_gate("GATE-01")
        end_gate("GATE-01", tokens_used=0)

    def test_gate_manager_multiple_runs(self):
        """Test GateManager with multiple gate runs."""
        init_token_attributor()
        reset_attribution()
        
        manager = GateManager()
        
        context = {
            "policies": {"test": {}},
            "execution_mode": "direct"
        }
        
        # Run gates multiple times
        for _ in range(3):
            manager.run_pre_exec_gates(context)
        
        attribution = get_attribution()
        
        # Each gate should have call_count > 1 due to multiple runs
        for gate_data in attribution.values():
            assert gate_data["call_count"] >= 3


class TestValidationCriteria:
    """Tests for ITEM-MODEL-002 validation criteria."""

    def test_tokens_tracked_per_gate(self):
        """
        VALIDATION CRITERION: tokens_tracked_per_gate
        Each gate has its own token tracking.
        """
        init_token_attributor()
        reset_attribution()
        
        # Different token usage for different gates
        gate_usage = {
            "GATE-00": 100,
            "GATE-01": 200,
            "GATE-02": 300,
        }
        
        for gate, tokens in gate_usage.items():
            start_gate(gate)
            end_gate(gate, tokens_used=tokens)
        
        attribution = get_attribution()
        
        # Verify each gate has correct individual tracking
        assert attribution["GATE-00"]["total_tokens"] == 100
        assert attribution["GATE-01"]["total_tokens"] == 200
        assert attribution["GATE-02"]["total_tokens"] == 300

    def test_sum_matches_total_validation(self):
        """
        VALIDATION CRITERION: sum_matches_total
        Sum of all gate tokens equals total tokens.
        """
        init_token_attributor()
        reset_attribution()
        
        # Record usage across multiple gates
        usages = [
            ("GATE-00", 100, 70, 30),
            ("GATE-01", 200, 150, 50),
            ("GATE-02", 300, 200, 100),
        ]
        
        for gate, total, prompt, completion in usages:
            start_gate(gate)
            end_gate(gate, tokens_used=total, prompt_tokens=prompt, completion_tokens=completion)
        
        metrics = get_attribution_for_metrics()
        
        # Calculate expected totals
        expected_total = sum(u[1] for u in usages)
        expected_prompt = sum(u[2] for u in usages)
        expected_completion = sum(u[3] for u in usages)
        
        # Verify
        assert metrics["token_attribution_summary"]["total_tokens"] == expected_total
        assert metrics["token_attribution_summary"]["total_prompt_tokens"] == expected_prompt
        assert metrics["token_attribution_summary"]["total_completion_tokens"] == expected_completion

    def test_attribution_in_metrics_json(self):
        """
        VALIDATION CRITERION: attribution_in_metrics
        Token attribution appears in metrics.json format.
        """
        init_token_attributor()
        reset_attribution()
        
        start_gate("GATE-00")
        end_gate("GATE-00", tokens_used=150, prompt_tokens=100, completion_tokens=50)
        
        metrics = get_attribution_for_metrics()
        
        # Verify metrics.json format
        assert "token_attribution" in metrics
        assert "token_attribution_summary" in metrics
        
        # Verify JSON serializable
        json_str = json.dumps(metrics)
        parsed = json.loads(json_str)
        
        assert "token_attribution" in parsed
        assert "GATE-00" in parsed["token_attribution"]

    def test_gate_timing_validation(self):
        """
        VALIDATION CRITERION: gate_timing_tracked
        Gate execution timing is tracked.
        """
        init_token_attributor()
        reset_attribution()
        
        start_gate("GATE-00")
        time.sleep(0.02)  # 20ms
        end_gate("GATE-00", tokens_used=100)
        
        attribution = get_attribution()
        
        assert attribution["GATE-00"]["total_duration_ms"] >= 20.0
        assert attribution["GATE-00"]["avg_duration_ms"] >= 20.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
