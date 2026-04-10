"""Tests for scripts/generate_metrics.py

FIX-011: Test coverage for metrics generation script
"""

import pytest
import json
from datetime import datetime


class TestCalculatePercentiles:
    """Tests for calculate_percentiles function."""

    def test_empty_list_returns_zeros(self):
        """Empty list should return zero percentiles."""
        from scripts.generate_metrics import calculate_percentiles
        
        result = calculate_percentiles([])
        assert result["p50"] == 0.0
        assert result["p95"] == 0.0
        assert result["p99"] == 0.0

    def test_single_value_returns_same_for_all(self):
        """Single value should return that value for all percentiles."""
        from scripts.generate_metrics import calculate_percentiles
        
        result = calculate_percentiles([100.0])
        assert result["p50"] == 100.0
        assert result["p95"] == 100.0
        assert result["p99"] == 100.0

    def test_two_values(self):
        """Two values should calculate correctly."""
        from scripts.generate_metrics import calculate_percentiles
        
        result = calculate_percentiles([100.0, 200.0])
        # p50 = sorted[int(2 * 0.5)] = sorted[1] = 200.0
        assert result["p50"] == 200.0
        # p95 = sorted[int(2 * 0.95)] = sorted[1] = 200.0
        assert result["p95"] == 200.0

    def test_ten_values(self):
        """Ten values should calculate correct percentiles."""
        from scripts.generate_metrics import calculate_percentiles
        
        values = list(range(10, 110, 10))  # [10, 20, 30, ..., 100]
        result = calculate_percentiles(values)
        
        # p50 = 5th value (0-indexed: int(10 * 0.5) = 5)
        assert result["p50"] == 60.0
        # p95 = 9th value (0-indexed: int(10 * 0.95) = 9)
        assert result["p95"] == 100.0
        # p99 = 9th value (0-indexed: int(10 * 0.99) = 9)
        assert result["p99"] == 100.0

    def test_unsorted_list(self):
        """Unsorted list should still work correctly."""
        from scripts.generate_metrics import calculate_percentiles
        
        result = calculate_percentiles([300.0, 100.0, 200.0])
        assert result["p50"] == 200.0


class TestQueryMetrics:
    """Tests for QueryMetrics dataclass."""

    def test_dataclass_fields(self):
        """QueryMetrics should have all required fields."""
        from scripts.generate_metrics import QueryMetrics
        
        metrics = QueryMetrics(
            query_id="test-001",
            model_used="gpt-4o-mini",
            latency_ms=150.0,
            per_query_p50=100.0,
            per_query_p95=200.0,
            tokens_used=500
        )
        
        assert metrics.query_id == "test-001"
        assert metrics.model_used == "gpt-4o-mini"
        assert metrics.latency_ms == 150.0
        assert metrics.per_query_p50 == 100.0
        assert metrics.per_query_p95 == 200.0
        assert metrics.tokens_used == 500
        assert metrics.fallback_used is False

    def test_fallback_used_default_false(self):
        """fallback_used should default to False."""
        from scripts.generate_metrics import QueryMetrics
        
        metrics = QueryMetrics(
            query_id="test-002",
            model_used="test-model",
            latency_ms=100.0,
            per_query_p50=50.0,
            per_query_p95=100.0,
            tokens_used=100
        )
        
        assert metrics.fallback_used is False

    def test_fallback_used_can_be_set(self):
        """fallback_used can be explicitly set to True."""
        from scripts.generate_metrics import QueryMetrics
        
        metrics = QueryMetrics(
            query_id="test-003",
            model_used="fallback-model",
            latency_ms=200.0,
            per_query_p50=150.0,
            per_query_p95=300.0,
            tokens_used=200,
            fallback_used=True
        )
        
        assert metrics.fallback_used is True


class TestGenerateMetrics:
    """Tests for generate_metrics function."""

    def test_generate_metrics_returns_valid_dict(self):
        """generate_metrics should return a valid dictionary."""
        from scripts.generate_metrics import generate_metrics
        
        result = generate_metrics(
            session_id="test-session",
            source_file="test.md",
            source_lines=100,
            source_chunks=5,
            issues_found=10,
            issues_fixed=8,
            issues_deferred=2,
            gaps=1,
            gap_severity={"SEV-1": 0, "SEV-2": 1, "SEV-3": 0, "SEV-4": 0},
            tokens_used=5000,
            tokens_max=10000,
            gates={"GATE-00": "PASS", "GATE-01": "PASS"},
            duration_seconds=60,
            confidence_score=95.0
        )
        
        assert isinstance(result, dict)
        assert "session" in result
        assert "source" in result
        assert "processing" in result
        assert "budget" in result
        assert "gates" in result
        assert "quality" in result

    def test_generate_metrics_includes_telemetry_fields(self):
        """generate_metrics should include v3.4.0 telemetry fields."""
        from scripts.generate_metrics import generate_metrics
        
        result = generate_metrics(
            session_id="test-session",
            source_file="test.md",
            source_lines=100,
            source_chunks=5,
            issues_found=10,
            issues_fixed=8,
            issues_deferred=2,
            gaps=1,
            gap_severity={"SEV-1": 0, "SEV-2": 1, "SEV-3": 0, "SEV-4": 0},
            tokens_used=5000,
            tokens_max=10000,
            gates={"GATE-00": "PASS", "GATE-01": "PASS"},
            duration_seconds=60,
            confidence_score=95.0,
            model_used="gpt-4o-mini",
            latency_ms=250,
            per_query_p50=150.0,
            per_query_p95=350.0,
            fallback_used=False
        )
        
        assert "llm_telemetry" in result
        assert result["llm_telemetry"]["per_query_p50"] == 150.0
        assert result["llm_telemetry"]["per_query_p95"] == 350.0
        assert result["llm_telemetry"]["model_used"] == "gpt-4o-mini"
        assert result["llm_telemetry"]["fallback_used"] is False

    def test_generate_metrics_includes_multi_agent(self):
        """generate_metrics should include multi-agent metrics when applicable."""
        from scripts.generate_metrics import generate_metrics
        
        result = generate_metrics(
            session_id="test-session",
            source_file="test.md",
            source_lines=100,
            source_chunks=5,
            issues_found=10,
            issues_fixed=8,
            issues_deferred=2,
            gaps=1,
            gap_severity={"SEV-1": 0, "SEV-2": 1, "SEV-3": 0, "SEV-4": 0},
            tokens_used=5000,
            tokens_max=10000,
            gates={"GATE-00": "PASS", "GATE-01": "PASS"},
            duration_seconds=60,
            confidence_score=95.0,
            agents_dispatched=5,
            agents_completed=5,
            sync_latency_ms=100
        )
        
        assert "multi_agent" in result
        assert result["multi_agent"]["agents_dispatched"] == 5
        assert result["multi_agent"]["agents_completed"] == 5


class TestExampleMetrics:
    """Tests for EXAMPLE_METRICS constant."""

    def test_example_metrics_is_valid_json(self):
        """EXAMPLE_METRICS should be a valid JSON-serializable dict."""
        from scripts.generate_metrics import EXAMPLE_METRICS
        
        # Should not raise
        json_str = json.dumps(EXAMPLE_METRICS)
        parsed = json.loads(json_str)
        
        assert isinstance(parsed, dict)

    def test_example_metrics_has_telemetry(self):
        """EXAMPLE_METRICS should include llm_telemetry."""
        from scripts.generate_metrics import EXAMPLE_METRICS
        
        assert "llm_telemetry" in EXAMPLE_METRICS
        assert "per_query_p50" in EXAMPLE_METRICS["llm_telemetry"]
        assert "per_query_p95" in EXAMPLE_METRICS["llm_telemetry"]
        assert "model_used" in EXAMPLE_METRICS["llm_telemetry"]

    def test_example_metrics_has_model_breakdown(self):
        """EXAMPLE_METRICS should include model_breakdown."""
        from scripts.generate_metrics import EXAMPLE_METRICS
        
        assert "model_breakdown" in EXAMPLE_METRICS["llm_telemetry"]
        assert "gpt-4o-mini" in EXAMPLE_METRICS["llm_telemetry"]["model_breakdown"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
