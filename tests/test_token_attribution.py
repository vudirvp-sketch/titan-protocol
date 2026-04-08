"""
Tests for ITEM-OBS-85: Granular Token Attribution per Gate

Tests cover:
- Per-gate token tracking
- Active gate management
- Timing and duration tracking
- Thread safety
- Wrap function integration
- Validation criteria: Tokens tracked per gate, Sum matches total tokens
"""

import pytest
import time
import threading
from unittest.mock import Mock, patch
from datetime import datetime

from src.observability.token_attribution import (
    TokenAttributor,
    GateTokenRecord,
    ActiveGate,
    get_token_attributor,
    init_token_attributor,
    start_gate,
    end_gate,
    get_attribution,
    get_total_tokens,
    reset_attribution,
)


class TestGateTokenRecord:
    """Tests for GateTokenRecord dataclass."""

    def test_create_record(self):
        """Test basic record creation."""
        record = GateTokenRecord(gate_id="GATE-00")
        
        assert record.gate_id == "GATE-00"
        assert record.prompt_tokens == 0
        assert record.completion_tokens == 0
        assert record.total_tokens == 0
        assert record.call_count == 0
        assert record.first_started_at is None
        assert record.last_started_at is None
        assert record.last_ended_at is None
        assert record.total_duration_ms == 0.0

    def test_record_to_dict(self):
        """Test record serialization."""
        record = GateTokenRecord(
            gate_id="GATE-01",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            call_count=3,
            first_started_at="2024-01-01T00:00:00.000Z",
            last_started_at="2024-01-01T00:10:00.000Z",
            last_ended_at="2024-01-01T00:10:05.000Z",
            total_duration_ms=15000.0
        )
        
        data = record.to_dict()
        
        assert data["prompt_tokens"] == 100
        assert data["completion_tokens"] == 50
        assert data["total_tokens"] == 150
        assert data["call_count"] == 3
        assert data["avg_tokens_per_call"] == 50.0  # 150/3
        assert data["avg_duration_ms"] == 5000.0  # 15000/3
        assert data["first_started_at"] == "2024-01-01T00:00:00.000Z"

    def test_record_avg_tokens_zero_calls(self):
        """Test average calculation with zero calls."""
        record = GateTokenRecord(gate_id="GATE-00")
        
        data = record.to_dict()
        
        assert data["avg_tokens_per_call"] == 0.0
        assert data["avg_duration_ms"] == 0.0


class TestActiveGate:
    """Tests for ActiveGate dataclass."""

    def test_create_active_gate(self):
        """Test active gate creation."""
        now = datetime(2024, 1, 1, 12, 0, 0)
        
        gate = ActiveGate(
            gate_id="GATE-00",
            started_at="2024-01-01T12:00:00.000Z",
            started_at_dt=now
        )
        
        assert gate.gate_id == "GATE-00"
        assert gate.started_at == "2024-01-01T12:00:00.000Z"
        assert gate.started_at_dt == now


class TestTokenAttributor:
    """Tests for TokenAttributor class."""

    def test_init(self):
        """Test basic initialization."""
        attributor = TokenAttributor()
        
        assert attributor.get_gate_count() == 0
        assert attributor.get_total_tokens() == 0
        assert attributor.get_active_gates() == []

    def test_start_gate(self):
        """Test starting a gate."""
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        
        assert "GATE-00" in attributor.get_active_gates()
        assert attributor.is_gate_active("GATE-00")

    def test_end_gate(self):
        """Test ending a gate with token usage."""
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        attributor.end_gate("GATE-00", tokens_used=100)
        
        assert "GATE-00" not in attributor.get_active_gates()
        assert not attributor.is_gate_active("GATE-00")
        
        attribution = attributor.get_attribution()
        assert "GATE-00" in attribution
        assert attribution["GATE-00"]["total_tokens"] == 100

    def test_end_gate_with_breakdown(self):
        """Test ending a gate with prompt/completion breakdown."""
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        attributor.end_gate(
            "GATE-00",
            tokens_used=150,
            prompt_tokens=100,
            completion_tokens=50
        )
        
        attribution = attributor.get_gate_attribution("GATE-00")
        
        assert attribution["total_tokens"] == 150
        assert attribution["prompt_tokens"] == 100
        assert attribution["completion_tokens"] == 50

    def test_multiple_calls_same_gate(self):
        """Test multiple calls to the same gate."""
        attributor = TokenAttributor()
        
        # First call
        attributor.start_gate("GATE-00")
        attributor.end_gate("GATE-00", tokens_used=100)
        
        # Second call
        attributor.start_gate("GATE-00")
        attributor.end_gate("GATE-00", tokens_used=50)
        
        attribution = attributor.get_gate_attribution("GATE-00")
        
        assert attribution["total_tokens"] == 150
        assert attribution["call_count"] == 2
        assert attribution["avg_tokens_per_call"] == 75.0

    def test_multiple_gates(self):
        """Test tracking multiple different gates."""
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        attributor.end_gate("GATE-00", tokens_used=100)
        
        attributor.start_gate("GATE-01")
        attributor.end_gate("GATE-01", tokens_used=200)
        
        attributor.start_gate("GATE-02")
        attributor.end_gate("GATE-02", tokens_used=150)
        
        assert attributor.get_gate_count() == 3
        assert attributor.get_total_tokens() == 450
        
        attribution = attributor.get_attribution()
        assert "GATE-00" in attribution
        assert "GATE-01" in attribution
        assert "GATE-02" in attribution

    def test_start_gate_already_active_raises(self):
        """Test that starting an already active gate raises error."""
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        
        with pytest.raises(ValueError, match="already active"):
            attributor.start_gate("GATE-00")

    def test_end_gate_not_active_raises(self):
        """Test that ending a non-active gate raises error."""
        attributor = TokenAttributor()
        
        with pytest.raises(ValueError, match="not active"):
            attributor.end_gate("GATE-00", tokens_used=100)

    def test_get_attribution(self):
        """Test getting full attribution dict."""
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        attributor.end_gate("GATE-00", tokens_used=100, prompt_tokens=70, completion_tokens=30)
        
        attribution = attributor.get_attribution()
        
        assert isinstance(attribution, dict)
        assert "GATE-00" in attribution
        assert attribution["GATE-00"]["total_tokens"] == 100
        assert attribution["GATE-00"]["prompt_tokens"] == 70
        assert attribution["GATE-00"]["completion_tokens"] == 30
        assert attribution["GATE-00"]["call_count"] == 1

    def test_get_gate_attribution_existing(self):
        """Test getting attribution for existing gate."""
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        attributor.end_gate("GATE-00", tokens_used=100)
        
        attr = attributor.get_gate_attribution("GATE-00")
        
        assert attr is not None
        assert attr["total_tokens"] == 100

    def test_get_gate_attribution_nonexistent(self):
        """Test getting attribution for non-existent gate."""
        attributor = TokenAttributor()
        
        attr = attributor.get_gate_attribution("GATE-99")
        
        assert attr is None

    def test_get_total_tokens(self):
        """Test total tokens calculation."""
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        attributor.end_gate("GATE-00", tokens_used=100)
        
        attributor.start_gate("GATE-01")
        attributor.end_gate("GATE-01", tokens_used=200)
        
        assert attributor.get_total_tokens() == 300

    def test_get_total_prompt_tokens(self):
        """Test total prompt tokens calculation."""
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        attributor.end_gate("GATE-00", tokens_used=100, prompt_tokens=80)
        
        attributor.start_gate("GATE-01")
        attributor.end_gate("GATE-01", tokens_used=200, prompt_tokens=150)
        
        assert attributor.get_total_prompt_tokens() == 230

    def test_get_total_completion_tokens(self):
        """Test total completion tokens calculation."""
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        attributor.end_gate("GATE-00", tokens_used=100, prompt_tokens=80, completion_tokens=20)
        
        attributor.start_gate("GATE-01")
        attributor.end_gate("GATE-01", tokens_used=200, prompt_tokens=150, completion_tokens=50)
        
        assert attributor.get_total_completion_tokens() == 70

    def test_get_total_call_count(self):
        """Test total call count."""
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        attributor.end_gate("GATE-00", tokens_used=100)
        
        attributor.start_gate("GATE-00")
        attributor.end_gate("GATE-00", tokens_used=50)
        
        attributor.start_gate("GATE-01")
        attributor.end_gate("GATE-01", tokens_used=200)
        
        assert attributor.get_total_call_count() == 3

    def test_reset(self):
        """Test resetting attribution data."""
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        attributor.end_gate("GATE-00", tokens_used=100)
        
        assert attributor.get_gate_count() == 1
        
        attributor.reset()
        
        assert attributor.get_gate_count() == 0
        assert attributor.get_total_tokens() == 0
        assert attributor.get_active_gates() == []

    def test_get_stats(self):
        """Test getting summary statistics."""
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        attributor.end_gate("GATE-00", tokens_used=100, prompt_tokens=80, completion_tokens=20)
        
        stats = attributor.get_stats()
        
        assert stats["total_gates"] == 1
        assert stats["total_calls"] == 1
        assert stats["total_tokens"] == 100
        assert stats["total_prompt_tokens"] == 80
        assert stats["total_completion_tokens"] == 20
        assert stats["active_gates"] == 0
        assert "gates" in stats

    def test_duration_tracking(self):
        """Test that duration is tracked."""
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        time.sleep(0.01)  # 10ms
        attributor.end_gate("GATE-00", tokens_used=100)
        
        attribution = attributor.get_gate_attribution("GATE-00")
        
        assert attribution["total_duration_ms"] >= 10.0
        assert attribution["avg_duration_ms"] >= 10.0


class TestWrapGateExecution:
    """Tests for wrap_gate_execution method."""

    def test_wrap_successful_execution(self):
        """Test wrapping a successful function."""
        attributor = TokenAttributor()
        
        def my_func():
            return "result"
        
        result = attributor.wrap_gate_execution(
            "GATE-00",
            my_func,
            tokens_used=100,
            prompt_tokens=70,
            completion_tokens=30
        )
        
        assert result == "result"
        
        attribution = attributor.get_gate_attribution("GATE-00")
        assert attribution["total_tokens"] == 100

    def test_wrap_with_exception(self):
        """Test wrapping a function that raises."""
        attributor = TokenAttributor()
        
        def failing_func():
            raise RuntimeError("Test error")
        
        with pytest.raises(RuntimeError, match="Test error"):
            attributor.wrap_gate_execution(
                "GATE-00",
                failing_func,
                tokens_used=100
            )
        
        # Gate should not be active after exception
        assert not attributor.is_gate_active("GATE-00")

    def test_wrap_with_args(self):
        """Test wrapping a function with arguments."""
        attributor = TokenAttributor()
        
        def add(a, b):
            return a + b
        
        # Use functools.partial to pass args
        import functools
        result = attributor.wrap_gate_execution(
            "GATE-00",
            functools.partial(add, 1, 2),
            tokens_used=50
        )
        
        assert result == 3


class TestRecordExistingUsage:
    """Tests for record_existing_usage method."""

    def test_record_existing(self):
        """Test recording usage without start/end."""
        attributor = TokenAttributor()
        
        attributor.record_existing_usage(
            "GATE-00",
            tokens_used=100,
            prompt_tokens=70,
            completion_tokens=30
        )
        
        attribution = attributor.get_gate_attribution("GATE-00")
        
        assert attribution["total_tokens"] == 100
        assert attribution["prompt_tokens"] == 70
        assert attribution["completion_tokens"] == 30
        assert attribution["call_count"] == 1

    def test_record_existing_multiple(self):
        """Test multiple recordings to same gate."""
        attributor = TokenAttributor()
        
        attributor.record_existing_usage("GATE-00", tokens_used=100)
        attributor.record_existing_usage("GATE-00", tokens_used=50)
        
        attribution = attributor.get_gate_attribution("GATE-00")
        
        assert attribution["total_tokens"] == 150
        assert attribution["call_count"] == 2


class TestTokenAttributorThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_start_end(self):
        """Test concurrent gate operations."""
        attributor = TokenAttributor()
        errors = []
        
        def worker(gate_id):
            try:
                for i in range(10):
                    attributor.start_gate(gate_id)
                    time.sleep(0.001)
                    attributor.end_gate(gate_id, tokens_used=10)
            except Exception as e:
                errors.append((gate_id, e))
        
        threads = [
            threading.Thread(target=worker, args=(f"GATE-{i:02d}",))
            for i in range(5)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert attributor.get_gate_count() == 5
        assert attributor.get_total_tokens() == 5 * 10 * 10  # 5 gates, 10 calls, 10 tokens

    def test_concurrent_read_write(self):
        """Test concurrent reads and writes."""
        attributor = TokenAttributor()
        errors = []
        
        def writer():
            try:
                for i in range(50):
                    attributor.start_gate("GATE-00")
                    attributor.end_gate("GATE-00", tokens_used=1)
            except Exception as e:
                errors.append(e)
        
        def reader():
            try:
                for _ in range(100):
                    attributor.get_attribution()
                    attributor.get_total_tokens()
                    attributor.get_stats()
            except Exception as e:
                errors.append(e)
        
        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0

    def test_concurrent_record_existing(self):
        """Test concurrent record_existing_usage."""
        attributor = TokenAttributor()
        errors = []
        
        def recorder():
            try:
                for i in range(100):
                    attributor.record_existing_usage("GATE-00", tokens_used=1)
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=recorder) for _ in range(5)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert attributor.get_total_tokens() == 500


class TestGlobalFunctions:
    """Tests for module-level convenience functions."""

    def test_get_token_attributor_singleton(self):
        """Test that get_token_attributor returns singleton."""
        # Reset first
        init_token_attributor()
        
        a1 = get_token_attributor()
        a2 = get_token_attributor()
        
        assert a1 is a2

    def test_init_token_attributor(self):
        """Test init creates new instance."""
        a1 = init_token_attributor()
        a2 = init_token_attributor()
        
        assert a1 is not a2  # Each init creates new
        assert get_token_attributor() is a2  # Global is latest

    def test_start_end_gate_globals(self):
        """Test global start_gate and end_gate functions."""
        init_token_attributor()
        
        start_gate("GATE-00")
        end_gate("GATE-00", tokens_used=100)
        
        attribution = get_attribution()
        assert "GATE-00" in attribution
        assert attribution["GATE-00"]["total_tokens"] == 100

    def test_get_total_tokens_global(self):
        """Test global get_total_tokens function."""
        init_token_attributor()
        
        start_gate("GATE-00")
        end_gate("GATE-00", tokens_used=100)
        
        start_gate("GATE-01")
        end_gate("GATE-01", tokens_used=200)
        
        assert get_total_tokens() == 300

    def test_reset_attribution_global(self):
        """Test global reset_attribution function."""
        init_token_attributor()
        
        start_gate("GATE-00")
        end_gate("GATE-00", tokens_used=100)
        
        assert get_total_tokens() == 100
        
        reset_attribution()
        
        assert get_total_tokens() == 0


class TestValidationCriteria:
    """Tests for validation criteria from requirements."""

    def test_per_gate_tracking_criterion(self):
        """
        VALIDATION CRITERION: per_gate_tracking
        Tokens tracked per gate.
        """
        attributor = TokenAttributor()
        
        # Track multiple gates with different usage
        attributor.start_gate("GATE-00")
        attributor.end_gate("GATE-00", tokens_used=100)
        
        attributor.start_gate("GATE-01")
        attributor.end_gate("GATE-01", tokens_used=200)
        
        attributor.start_gate("GATE-02")
        attributor.end_gate("GATE-02", tokens_used=150)
        
        # Verify each gate has its own tracking
        attr = attributor.get_attribution()
        
        assert attr["GATE-00"]["total_tokens"] == 100
        assert attr["GATE-01"]["total_tokens"] == 200
        assert attr["GATE-02"]["total_tokens"] == 150
        
        # Verify call counts
        assert attr["GATE-00"]["call_count"] == 1
        assert attr["GATE-01"]["call_count"] == 1
        assert attr["GATE-02"]["call_count"] == 1

    def test_accurate_attribution_criterion(self):
        """
        VALIDATION CRITERION: accurate_attribution
        Sum matches total tokens.
        """
        attributor = TokenAttributor()
        
        # Track usage across multiple gates with multiple calls
        gate_usage = {
            "GATE-00": [100, 50, 75],
            "GATE-01": [200, 150],
            "GATE-02": [300],
        }
        
        for gate_id, usages in gate_usage.items():
            for tokens in usages:
                attributor.start_gate(gate_id)
                attributor.end_gate(gate_id, tokens_used=tokens)
        
        # Calculate expected total
        expected_total = sum(sum(usages) for usages in gate_usage.values())
        
        # Verify total matches
        assert attributor.get_total_tokens() == expected_total
        
        # Verify sum of individual gate totals matches
        attribution = attributor.get_attribution()
        calculated_total = sum(a["total_tokens"] for a in attribution.values())
        assert calculated_total == expected_total

    def test_prompt_completion_breakdown_criterion(self):
        """
        VALIDATION: Prompt and completion tokens tracked separately.
        """
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        attributor.end_gate(
            "GATE-00",
            tokens_used=150,
            prompt_tokens=100,
            completion_tokens=50
        )
        
        attr = attributor.get_gate_attribution("GATE-00")
        
        assert attr["prompt_tokens"] == 100
        assert attr["completion_tokens"] == 50
        assert attr["prompt_tokens"] + attr["completion_tokens"] == attr["total_tokens"]

    def test_multiple_calls_aggregation_criterion(self):
        """
        VALIDATION: Multiple calls to same gate aggregate correctly.
        """
        attributor = TokenAttributor()
        
        # Multiple calls to same gate
        usages = [
            (100, 70, 30),
            (150, 100, 50),
            (200, 150, 50),
        ]
        
        for total, prompt, completion in usages:
            attributor.start_gate("GATE-00")
            attributor.end_gate(
                "GATE-00",
                tokens_used=total,
                prompt_tokens=prompt,
                completion_tokens=completion
            )
        
        attr = attributor.get_gate_attribution("GATE-00")
        
        # Verify aggregation
        assert attr["total_tokens"] == 450  # Sum of totals
        assert attr["prompt_tokens"] == 320  # Sum of prompts
        assert attr["completion_tokens"] == 130  # Sum of completions
        assert attr["call_count"] == 3
        assert attr["avg_tokens_per_call"] == 150.0  # 450/3


class TestIntegrationWithMetrics:
    """Tests for integration with metrics system."""

    def test_attribution_exportable(self):
        """Test that attribution can be exported for metrics."""
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        attributor.end_gate("GATE-00", tokens_used=100)
        
        # Get exportable dict
        attribution = attributor.get_attribution()
        
        # Should be JSON serializable
        import json
        json_str = json.dumps(attribution)
        
        # Should be able to parse back
        parsed = json.loads(json_str)
        assert parsed["GATE-00"]["total_tokens"] == 100

    def test_stats_exportable(self):
        """Test that stats can be exported for metrics."""
        attributor = TokenAttributor()
        
        attributor.start_gate("GATE-00")
        attributor.end_gate("GATE-00", tokens_used=100)
        
        stats = attributor.get_stats()
        
        # Should be JSON serializable
        import json
        json_str = json.dumps(stats)
        
        parsed = json.loads(json_str)
        assert parsed["total_tokens"] == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
