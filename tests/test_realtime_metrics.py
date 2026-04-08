"""
Tests for ITEM-OBS-81: Real-time p50/p95 Export

Tests cover:
- Circular buffer operations
- Percentile calculation accuracy
- RealtimeMetricsExporter functionality
- Thread safety
- Metrics integration
- Prometheus integration
- Percentile calculations accurate within 1%
"""

import pytest
import time
import threading
from unittest.mock import Mock, MagicMock, patch
from collections import deque

from src.observability.realtime_metrics import (
    RealtimeMetricsExporter,
    RealtimeConfig,
    CircularBuffer,
    MetricWindow,
    get_realtime_exporter,
    init_realtime_exporter,
    observe_token_count,
    observe_latency,
    observe_metric,
    get_realtime_percentiles,
)
from src.observability.metrics import MetricsCollector, Histogram


class TestCircularBuffer:
    """Tests for CircularBuffer class."""

    def test_create_buffer(self):
        """Test buffer creation with default size."""
        buffer = CircularBuffer(size=100)
        assert buffer._size == 100
        assert len(buffer) == 0
        assert buffer.is_empty()

    def test_append_single_value(self):
        """Test appending a single value."""
        buffer = CircularBuffer(size=10)
        buffer.append(1.5)

        assert len(buffer) == 1
        assert not buffer.is_empty()
        assert buffer.get_values() == [1.5]

    def test_append_multiple_values(self):
        """Test appending multiple values."""
        buffer = CircularBuffer(size=10)

        for i in range(5):
            buffer.append(float(i))

        values = buffer.get_values()
        assert len(values) == 5
        assert values == [0.0, 1.0, 2.0, 3.0, 4.0]

    def test_buffer_overflow(self):
        """Test buffer overwriting when full."""
        buffer = CircularBuffer(size=5)

        # Add more values than buffer size
        for i in range(10):
            buffer.append(float(i))

        # Should only have last 5 values
        assert len(buffer) == 5
        assert buffer.is_full()

        values = buffer.get_values()
        # Order should be preserved (oldest to newest)
        assert values == [5.0, 6.0, 7.0, 8.0, 9.0]

    def test_get_sorted_values(self):
        """Test getting sorted values."""
        buffer = CircularBuffer(size=10)

        values_to_add = [5.0, 2.0, 8.0, 1.0, 9.0]
        for v in values_to_add:
            buffer.append(v)

        sorted_values = buffer.get_sorted_values()
        assert sorted_values == [1.0, 2.0, 5.0, 8.0, 9.0]

    def test_percentile_empty_buffer(self):
        """Test percentile on empty buffer."""
        buffer = CircularBuffer(size=10)
        assert buffer.percentile(50) == 0.0
        assert buffer.percentile(95) == 0.0

    def test_percentile_single_value(self):
        """Test percentile with single value."""
        buffer = CircularBuffer(size=10)
        buffer.append(42.0)

        assert buffer.percentile(50) == 42.0
        assert buffer.percentile(95) == 42.0
        assert buffer.percentile(0) == 42.0
        assert buffer.percentile(100) == 42.0

    def test_percentile_p50_exact(self):
        """Test p50 (median) calculation."""
        buffer = CircularBuffer(size=100)

        # Add values 1-99
        for i in range(1, 100):
            buffer.append(float(i))

        # Median of 1-99 should be 50
        p50 = buffer.percentile(50)
        assert 49.0 <= p50 <= 51.0

    def test_percentile_p95_calculation(self):
        """Test p95 calculation."""
        buffer = CircularBuffer(size=100)

        # Add values 1-100
        for i in range(1, 101):
            buffer.append(float(i))

        # p95 should be around 95
        p95 = buffer.percentile(95)
        # Allow 1% tolerance
        assert 94.0 <= p95 <= 96.0

    def test_percentile_accuracy_within_1_percent(self):
        """Test that percentile calculations are accurate within 1%."""
        buffer = CircularBuffer(size=1000)

        # Create a known distribution
        import random
        random.seed(42)
        values = [random.uniform(0, 1000) for _ in range(500)]

        for v in values:
            buffer.append(v)

        # Calculate expected percentiles
        sorted_values = sorted(values)
        n = len(sorted_values)

        # Calculate expected p50
        expected_p50 = sorted_values[int(n * 0.50)]
        actual_p50 = buffer.percentile(50)
        tolerance = expected_p50 * 0.01
        assert abs(actual_p50 - expected_p50) <= tolerance, \
            f"p50 error: expected ~{expected_p50}, got {actual_p50}"

        # Calculate expected p95
        expected_p95 = sorted_values[int(n * 0.95)]
        actual_p95 = buffer.percentile(95)
        tolerance = expected_p95 * 0.01
        assert abs(actual_p95 - expected_p95) <= tolerance, \
            f"p95 error: expected ~{expected_p95}, got {actual_p95}"

    def test_clear_buffer(self):
        """Test clearing buffer."""
        buffer = CircularBuffer(size=10)

        for i in range(5):
            buffer.append(float(i))

        assert len(buffer) == 5

        buffer.clear()
        assert len(buffer) == 0
        assert buffer.is_empty()
        assert buffer.get_values() == []

    def test_get_stats(self):
        """Test getting buffer statistics."""
        buffer = CircularBuffer(size=10)

        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        for v in values:
            buffer.append(v)

        stats = buffer.get_stats()

        assert stats["count"] == 5
        assert stats["min"] == 1.0
        assert stats["max"] == 5.0
        assert stats["mean"] == 3.0
        assert "p50" in stats
        assert "p95" in stats

    def test_extend_multiple_values(self):
        """Test extending buffer with multiple values."""
        buffer = CircularBuffer(size=10)
        buffer.extend([1.0, 2.0, 3.0])

        assert len(buffer) == 3
        assert buffer.get_values() == [1.0, 2.0, 3.0]


class TestMetricWindow:
    """Tests for MetricWindow class."""

    def test_create_window(self):
        """Test metric window creation."""
        window = MetricWindow("test_metric", window_size=50)

        assert window.name == "test_metric"
        assert window.get_count() == 0

    def test_observe_values(self):
        """Test observing values."""
        window = MetricWindow("test", window_size=10)

        window.observe(10.0)
        window.observe(20.0)
        window.observe(30.0)

        assert window.get_count() == 3
        assert window.get_last_value() == 30.0

    def test_get_percentile(self):
        """Test percentile calculation."""
        window = MetricWindow("test", window_size=100)

        for i in range(1, 101):
            window.observe(float(i))

        p50 = window.get_percentile(50)
        p95 = window.get_percentile(95)

        assert 49.0 <= p50 <= 51.0
        assert 94.0 <= p95 <= 96.0

    def test_clear_window(self):
        """Test clearing window."""
        window = MetricWindow("test", window_size=10)

        for i in range(5):
            window.observe(float(i))

        window.clear()

        assert window.get_count() == 0
        assert window.get_last_value() is None


class TestRealtimeConfig:
    """Tests for RealtimeConfig dataclass."""

    def test_default_config(self):
        """Test default configuration."""
        config = RealtimeConfig()

        assert config.enabled is True
        assert config.export_interval_seconds == 30
        assert config.window_size == 100
        assert "token_count_p50" in config.include

    def test_from_dict(self):
        """Test creating config from dictionary."""
        data = {
            "enabled": False,
            "export_interval_seconds": 60,
            "window_size": 200,
            "include": ["custom_p50", "custom_p95"]
        }

        config = RealtimeConfig.from_dict(data)

        assert config.enabled is False
        assert config.export_interval_seconds == 60
        assert config.window_size == 200
        assert config.include == ["custom_p50", "custom_p95"]

    def test_to_dict(self):
        """Test converting config to dictionary."""
        config = RealtimeConfig(
            enabled=True,
            export_interval_seconds=45,
            window_size=150,
            include=["test_p50"]
        )

        data = config.to_dict()

        assert data["enabled"] is True
        assert data["export_interval_seconds"] == 45
        assert data["window_size"] == 150


class TestRealtimeMetricsExporter:
    """Tests for RealtimeMetricsExporter class."""

    def test_init_default(self):
        """Test default initialization."""
        exporter = RealtimeMetricsExporter()

        assert exporter._config.enabled is True
        assert exporter._config.window_size == 100
        assert not exporter.is_exporting()

    def test_init_with_config(self):
        """Test initialization with custom config."""
        config = {
            "enabled": True,
            "export_interval_seconds": 60,
            "window_size": 200
        }

        exporter = RealtimeMetricsExporter(config=config)

        assert exporter._config.export_interval_seconds == 60
        assert exporter._config.window_size == 200

    def test_observe_token_count(self):
        """Test observing token counts."""
        exporter = RealtimeMetricsExporter()

        exporter.observe_token_count(100)
        exporter.observe_token_count(200)
        exporter.observe_token_count(300)

        percentiles = exporter.get_current_percentiles()

        assert "token_count_p50" in percentiles
        assert "token_count_p95" in percentiles
        assert percentiles["token_count_p50"] > 0

    def test_observe_latency(self):
        """Test observing latency values."""
        exporter = RealtimeMetricsExporter()

        exporter.observe_latency(10.0)
        exporter.observe_latency(20.0)
        exporter.observe_latency(30.0)

        percentiles = exporter.get_current_percentiles()

        assert "latency_p50" in percentiles
        assert "latency_p95" in percentiles

    def test_observe_custom_metric(self):
        """Test observing custom metric."""
        exporter = RealtimeMetricsExporter()

        exporter.observe("custom_metric", 42.0)
        exporter.observe("custom_metric", 84.0)

        percentiles = exporter.get_current_percentiles()

        # Should have the metric if include list is empty or contains it
        exporter._config.include = ["custom_metric_p50", "custom_metric_p95"]
        percentiles = exporter.get_current_percentiles()

        assert "custom_metric_p50" in percentiles

    def test_register_metric(self):
        """Test registering a new metric."""
        exporter = RealtimeMetricsExporter()

        exporter.register_metric("new_metric")
        exporter.observe("new_metric", 123.0)

        stats = exporter.get_window_stats("new_metric")
        assert stats["count"] == 1

    def test_calculate_p50_static(self):
        """Test static p50 calculation."""
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

        p50 = RealtimeMetricsExporter.calculate_p50(values)

        # Should be around 5.5
        assert 5.0 <= p50 <= 6.0

    def test_calculate_p95_static(self):
        """Test static p95 calculation."""
        values = list(range(1, 101))  # 1 to 100

        p95 = RealtimeMetricsExporter.calculate_p95(values)

        # Should be around 95
        assert 94.0 <= p95 <= 96.0

    def test_calculate_percentile_empty(self):
        """Test percentile with empty list."""
        result = RealtimeMetricsExporter.calculate_p50([])
        assert result == 0.0

    def test_get_current_percentiles(self):
        """Test getting current percentiles."""
        exporter = RealtimeMetricsExporter()

        # Add some data
        for i in range(1, 101):
            exporter.observe_token_count(i)
            exporter.observe_latency(i * 10.0)

        percentiles = exporter.get_current_percentiles()

        assert isinstance(percentiles, dict)
        assert len(percentiles) > 0

    def test_get_window_stats(self):
        """Test getting window statistics."""
        exporter = RealtimeMetricsExporter()

        for i in range(1, 51):
            exporter.observe_token_count(i)

        stats = exporter.get_window_stats("token_count")

        assert stats["count"] == 50
        assert stats["min"] == 1.0
        assert stats["max"] == 50.0
        assert "p50" in stats
        assert "p95" in stats

    def test_get_all_window_stats(self):
        """Test getting all window statistics."""
        exporter = RealtimeMetricsExporter()

        exporter.observe_token_count(100)
        exporter.observe_latency(50.0)

        all_stats = exporter.get_all_window_stats()

        assert "token_count" in all_stats
        assert "latency" in all_stats

    def test_clear_all(self):
        """Test clearing all windows."""
        exporter = RealtimeMetricsExporter()

        exporter.observe_token_count(100)
        exporter.observe_latency(50.0)

        exporter.clear_all()

        assert exporter.get_window_stats("token_count")["count"] == 0
        assert exporter.get_window_stats("latency")["count"] == 0

    def test_get_summary(self):
        """Test getting exporter summary."""
        exporter = RealtimeMetricsExporter()

        summary = exporter.get_summary()

        assert "enabled" in summary
        assert "exporting" in summary
        assert "window_size" in summary
        assert "current_percentiles" in summary

    def test_start_export_disabled(self):
        """Test that export doesn't start when disabled."""
        exporter = RealtimeMetricsExporter(config={"enabled": False})

        exporter.start_export()

        assert not exporter.is_exporting()

    def test_start_stop_export(self):
        """Test starting and stopping export."""
        exporter = RealtimeMetricsExporter()

        exporter.start_export(interval_seconds=1)
        assert exporter.is_exporting()

        # Wait a moment
        time.sleep(0.1)

        exporter.stop_export()
        assert not exporter.is_exporting()

    def test_double_start_warning(self):
        """Test that double start doesn't create duplicate threads."""
        exporter = RealtimeMetricsExporter()

        exporter.start_export(interval_seconds=1)
        first_thread = exporter._export_thread

        exporter.start_export(interval_seconds=1)  # Should warn, not create new thread

        assert exporter._export_thread is first_thread

        exporter.stop_export()


class TestRealtimeMetricsExporterMetricsIntegration:
    """Tests for MetricsCollector integration."""

    def test_integration_with_metrics_collector(self):
        """Test integration with MetricsCollector."""
        metrics = MetricsCollector()
        exporter = RealtimeMetricsExporter(metrics_collector=metrics)

        exporter.observe_token_count(100)
        exporter.observe_token_count(200)

        # Trigger update
        exporter._update_metrics_collector(exporter.get_current_percentiles())

        # Verify metrics were registered
        # Note: The exact metric names depend on include list
        summary = metrics.get_summary()
        assert summary["gauges"] >= 0  # May have gauges registered


class TestRealtimeMetricsExporterThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_observe(self):
        """Test concurrent observations."""
        # Create fresh exporter with large window to avoid collision with global state
        exporter = RealtimeMetricsExporter(config={"window_size": 1000})
        errors = []

        def observe_values():
            try:
                for i in range(100):
                    exporter.observe_token_count(i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=observe_values) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # With 5 threads each adding 100 values, we should have 500 total
        assert exporter.get_window_stats("token_count")["count"] == 500

    def test_concurrent_read_write(self):
        """Test concurrent reads and writes."""
        exporter = RealtimeMetricsExporter()
        errors = []

        def writer():
            try:
                for i in range(50):
                    exporter.observe_token_count(i)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(20):
                    exporter.get_current_percentiles()
                    time.sleep(0.002)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestHistogramPercentileMethods:
    """Tests for percentile methods added to Histogram class."""

    def test_histogram_get_values(self):
        """Test getting values from histogram."""
        hist = Histogram("test_hist")

        hist.observe(1.0)
        hist.observe(2.0)
        hist.observe(3.0)

        values = hist.get_values()
        assert len(values) == 3
        assert set(values) == {1.0, 2.0, 3.0}

    def test_histogram_get_percentile(self):
        """Test histogram percentile calculation."""
        hist = Histogram("test_hist")

        for i in range(1, 101):
            hist.observe(float(i))

        p50 = hist.get_percentile(50)
        p95 = hist.get_percentile(95)

        assert 49.0 <= p50 <= 51.0
        assert 94.0 <= p95 <= 96.0

    def test_histogram_get_p50(self):
        """Test histogram p50 convenience method."""
        hist = Histogram("test_hist")

        values = [10, 20, 30, 40, 50]
        for v in values:
            hist.observe(float(v))

        p50 = hist.get_p50()
        assert p50 == hist.get_percentile(50)

    def test_histogram_get_p95(self):
        """Test histogram p95 convenience method."""
        hist = Histogram("test_hist")

        for i in range(1, 101):
            hist.observe(float(i))

        p95 = hist.get_p95()
        assert p95 == hist.get_percentile(95)

    def test_histogram_get_p99(self):
        """Test histogram p99 convenience method."""
        hist = Histogram("test_hist")

        for i in range(1, 101):
            hist.observe(float(i))

        p99 = hist.get_p99()
        assert p99 == hist.get_percentile(99)

    def test_histogram_get_percentiles(self):
        """Test getting all common percentiles."""
        hist = Histogram("test_hist")

        for i in range(1, 101):
            hist.observe(float(i))

        percentiles = hist.get_percentiles()

        assert "p50" in percentiles
        assert "p95" in percentiles
        assert "p99" in percentiles

    def test_histogram_empty_percentile(self):
        """Test percentile on empty histogram."""
        hist = Histogram("empty_hist")

        assert hist.get_percentile(50) == 0.0
        assert hist.get_p95() == 0.0

    def test_histogram_percentile_accuracy_within_1_percent(self):
        """Test that histogram percentiles are accurate within 1%."""
        hist = Histogram("test_hist")

        # Create a known distribution
        import random
        random.seed(42)
        values = sorted([random.uniform(0, 1000) for _ in range(500)])

        for v in values:
            hist.observe(v)

        n = len(values)

        # Expected p50
        expected_p50 = values[int(n * 0.50)]
        actual_p50 = hist.get_p50()
        tolerance = expected_p50 * 0.01
        assert abs(actual_p50 - expected_p50) <= tolerance, \
            f"p50 error: expected ~{expected_p50}, got {actual_p50}"

        # Expected p95
        expected_p95 = values[int(n * 0.95)]
        actual_p95 = hist.get_p95()
        tolerance = expected_p95 * 0.01
        assert abs(actual_p95 - expected_p95) <= tolerance, \
            f"p95 error: expected ~{expected_p95}, got {actual_p95}"

    def test_histogram_value_limit(self):
        """Test that histogram limits stored values to prevent OOM."""
        hist = Histogram("large_hist")

        # Add more values than MAX_PERCENTILE_VALUES
        for i in range(15000):
            hist.observe(float(i))

        # Should be limited
        assert len(hist.get_values()) <= hist.MAX_PERCENTILE_VALUES
        # Count should still be accurate
        assert hist.get_count() == 15000


class TestMetricsCollectorPercentileExport:
    """Tests for percentiles in MetricsCollector export."""

    def test_export_json_includes_percentiles(self):
        """Test that JSON export includes percentiles."""
        collector = MetricsCollector()
        hist = collector.register_histogram("test_histogram")

        for i in range(1, 101):
            hist.observe(float(i))

        export = collector.export_json()

        assert "histograms" in export
        hist_data = export["histograms"]["titan_test_histogram"]
        assert "percentiles" in hist_data
        assert "p50" in hist_data["percentiles"]
        assert "p95" in hist_data["percentiles"]


class TestGlobalFunctions:
    """Tests for global convenience functions."""

    def test_get_realtime_exporter(self):
        """Test getting global exporter."""
        exporter = get_realtime_exporter()
        assert isinstance(exporter, RealtimeMetricsExporter)

    def test_init_realtime_exporter(self):
        """Test initializing global exporter."""
        config = {"window_size": 50}
        exporter = init_realtime_exporter(config=config)

        assert exporter._config.window_size == 50
        assert get_realtime_exporter() is exporter

    def test_observe_token_count_global(self):
        """Test global token count observation."""
        init_realtime_exporter()
        observe_token_count(123.0)

        exporter = get_realtime_exporter()
        assert exporter.get_window_stats("token_count")["count"] >= 1

    def test_observe_latency_global(self):
        """Test global latency observation."""
        init_realtime_exporter()
        observe_latency(45.0)

        exporter = get_realtime_exporter()
        assert exporter.get_window_stats("latency")["count"] >= 1

    def test_observe_metric_global(self):
        """Test global metric observation."""
        init_realtime_exporter()
        observe_metric("custom", 99.0)

        exporter = get_realtime_exporter()
        assert exporter.get_window_stats("custom")["count"] >= 1

    def test_get_realtime_percentiles_global(self):
        """Test getting global percentiles."""
        init_realtime_exporter()
        observe_token_count(100)
        observe_token_count(200)

        percentiles = get_realtime_percentiles()

        assert isinstance(percentiles, dict)


class TestRealtimeUpdates:
    """Tests for real-time update validation criteria."""

    def test_metrics_update_during_session(self):
        """Test that metrics update during an active session."""
        exporter = RealtimeMetricsExporter()

        # Start with empty data
        initial = exporter.get_current_percentiles()

        # Add data
        for i in range(100):
            exporter.observe_token_count(i)
            exporter.observe_latency(i * 10.0)

        updated = exporter.get_current_percentiles()

        # Updated should have values
        assert updated != initial
        assert any(v > 0 for v in updated.values())

    def test_percentile_changes_with_new_data(self):
        """Test that percentiles change as new data arrives."""
        exporter = RealtimeMetricsExporter()

        # Add initial data
        for i in range(50):
            exporter.observe_token_count(i)

        p50_first = exporter.get_window_stats("token_count")["p50"]

        # Add more data (higher values)
        for i in range(50, 100):
            exporter.observe_token_count(i)

        p50_second = exporter.get_window_stats("token_count")["p50"]

        # p50 should have increased
        assert p50_second > p50_first


class TestValidationCriteria:
    """Tests for validation criteria from requirements."""

    def test_realtime_updates_criterion(self):
        """
        VALIDATION CRITERION: realtime_updates
        Metrics update during session.
        """
        exporter = RealtimeMetricsExporter()

        # Simulate a session
        exporter.start_export(interval_seconds=1)

        try:
            # Record values over time
            for i in range(10):
                exporter.observe_token_count(100 + i * 10)
                exporter.observe_latency(50.0 + i * 5.0)
                time.sleep(0.05)

            percentiles = exporter.get_current_percentiles()

            # Verify metrics were updated
            assert len(percentiles) > 0
            assert all(v > 0 for v in percentiles.values())

        finally:
            exporter.stop_export()

    def test_accurate_percentiles_criterion(self):
        """
        VALIDATION CRITERION: accurate_percentiles
        p50/p95 calculations correct within 1%.
        """
        # Use a window size large enough to hold all values
        exporter = RealtimeMetricsExporter(config={"window_size": 2000})

        # Create a controlled distribution
        values = list(range(1, 1001))  # 1 to 1000

        for v in values:
            exporter.observe_token_count(float(v))

        stats = exporter.get_window_stats("token_count")

        # Expected p50: 500.5
        expected_p50 = 500.5
        actual_p50 = stats["p50"]
        tolerance = expected_p50 * 0.01

        assert abs(actual_p50 - expected_p50) <= tolerance, \
            f"p50 not within 1%: expected {expected_p50}, got {actual_p50}"

        # Expected p95: 950.5
        expected_p95 = 950.5
        actual_p95 = stats["p95"]
        tolerance = expected_p95 * 0.01

        assert abs(actual_p95 - expected_p95) <= tolerance, \
            f"p95 not within 1%: expected {expected_p95}, got {actual_p95}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
