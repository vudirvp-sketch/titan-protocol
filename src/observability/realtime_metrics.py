"""
TITAN FUSE Protocol - Real-time Metrics Exporter

ITEM-OBS-81: Real-time p50/p95 Export

Provides real-time percentile calculations (p50, p95) for metrics
with efficient circular buffer implementation and Prometheus integration.

Features:
- Rolling window / circular buffer for efficient percentile calculation
- Thread-safe operations
- Prometheus push gateway integration
- Configurable export intervals
- Integration with existing MetricsCollector

Author: TITAN FUSE Team
Version: 4.1.0
"""

import threading
import time
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
import math

from src.utils.timezone import now_utc_iso


@dataclass
class RealtimeConfig:
    """Configuration for real-time metrics exporter."""
    enabled: bool = True
    export_interval_seconds: int = 30
    window_size: int = 100
    include: List[str] = field(default_factory=lambda: [
        "token_count_p50",
        "token_count_p95",
        "latency_p50",
        "latency_p95"
    ])

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RealtimeConfig":
        """Create config from dictionary."""
        return cls(
            enabled=data.get("enabled", True),
            export_interval_seconds=data.get("export_interval_seconds", 30),
            window_size=data.get("window_size", 100),
            include=data.get("include", [
                "token_count_p50",
                "token_count_p95",
                "latency_p50",
                "latency_p95"
            ])
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "enabled": self.enabled,
            "export_interval_seconds": self.export_interval_seconds,
            "window_size": self.window_size,
            "include": self.include
        }


class CircularBuffer:
    """
    Thread-safe circular buffer for efficient rolling window calculations.

    Uses a fixed-size ring buffer to store values, automatically overwriting
    oldest values when full. Provides O(1) insertion and O(n log n) percentile
    calculation.

    Usage:
        buffer = CircularBuffer(size=100)
        buffer.append(1.5)
        buffer.append(2.3)
        p50 = buffer.percentile(50)  # 50th percentile
        p95 = buffer.percentile(95)  # 95th percentile
    """

    def __init__(self, size: int = 100):
        """
        Initialize circular buffer.

        Args:
            size: Maximum number of values to store
        """
        self._size = size
        self._buffer: List[Optional[float]] = [None] * size
        self._head = 0  # Next write position
        self._count = 0  # Number of elements written
        self._lock = threading.Lock()

    def append(self, value: float) -> None:
        """
        Add a value to the buffer.

        Thread-safe operation that overwrites oldest value if buffer is full.

        Args:
            value: The value to add
        """
        with self._lock:
            self._buffer[self._head] = value
            self._head = (self._head + 1) % self._size
            if self._count < self._size:
                self._count += 1

    def extend(self, values: List[float]) -> None:
        """
        Add multiple values to the buffer.

        Args:
            values: List of values to add
        """
        with self._lock:
            for value in values:
                self._buffer[self._head] = value
                self._head = (self._head + 1) % self._size
                if self._count < self._size:
                    self._count += 1

    def get_values(self) -> List[float]:
        """
        Get all current values in insertion order.

        Returns:
            List of values currently in buffer
        """
        with self._lock:
            if self._count == 0:
                return []

            if self._count < self._size:
                # Buffer not yet full, return values written so far
                return [v for v in self._buffer[:self._count] if v is not None]

            # Buffer is full, reconstruct order starting from oldest
            # (head points to next write position, which is the oldest)
            result = []
            for i in range(self._size):
                idx = (self._head + i) % self._size
                if self._buffer[idx] is not None:
                    result.append(self._buffer[idx])
            return result

    def get_sorted_values(self) -> List[float]:
        """
        Get all values sorted in ascending order.

        Returns:
            Sorted list of values
        """
        values = self.get_values()
        return sorted(values)

    def percentile(self, p: float) -> float:
        """
        Calculate the p-th percentile.

        Uses linear interpolation between values for accurate results.

        Args:
            p: Percentile to calculate (0-100)

        Returns:
            The p-th percentile value, or 0.0 if buffer is empty
        """
        values = self.get_sorted_values()
        if not values:
            return 0.0

        return self._calculate_percentile(values, p)

    @staticmethod
    def _calculate_percentile(sorted_values: List[float], p: float) -> float:
        """
        Calculate percentile from sorted values.

        Uses the "nearest rank" method with linear interpolation.

        Args:
            sorted_values: Values sorted in ascending order
            p: Percentile (0-100)

        Returns:
            Percentile value
        """
        n = len(sorted_values)
        if n == 0:
            return 0.0
        if n == 1:
            return sorted_values[0]

        # Use linear interpolation method
        # p-th percentile is at position (p/100) * (n-1)
        rank = (p / 100.0) * (n - 1)
        lower_idx = int(math.floor(rank))
        upper_idx = int(math.ceil(rank))

        if lower_idx == upper_idx:
            return sorted_values[lower_idx]

        # Linear interpolation between adjacent values
        fraction = rank - lower_idx
        return sorted_values[lower_idx] + fraction * (sorted_values[upper_idx] - sorted_values[lower_idx])

    def clear(self) -> None:
        """Clear all values from the buffer."""
        with self._lock:
            self._buffer = [None] * self._size
            self._head = 0
            self._count = 0

    def __len__(self) -> int:
        """Return the number of elements in the buffer."""
        return self._count

    def is_empty(self) -> bool:
        """Check if buffer is empty."""
        return self._count == 0

    def is_full(self) -> bool:
        """Check if buffer is at capacity."""
        return self._count >= self._size

    def get_stats(self) -> Dict[str, float]:
        """
        Get basic statistics for current values.

        Returns:
            Dictionary with min, max, mean, count stats
        """
        values = self.get_values()
        if not values:
            return {
                "count": 0,
                "min": 0.0,
                "max": 0.0,
                "mean": 0.0,
                "p50": 0.0,
                "p95": 0.0
            }

        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
            "p50": self.percentile(50),
            "p95": self.percentile(95)
        }


class MetricWindow:
    """
    A metric with its rolling window buffer.

    Tracks a specific metric with a circular buffer for percentile calculations.
    """

    def __init__(self, name: str, window_size: int = 100):
        """
        Initialize metric window.

        Args:
            name: Metric name
            window_size: Size of the rolling window
        """
        self.name = name
        self._buffer = CircularBuffer(window_size)
        self._last_value: Optional[float] = None
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        """
        Record a new observation.

        Args:
            value: The observed value
        """
        with self._lock:
            self._buffer.append(value)
            self._last_value = value

    def get_last_value(self) -> Optional[float]:
        """Get the most recently observed value."""
        with self._lock:
            return self._last_value

    def get_percentile(self, p: float) -> float:
        """Get the p-th percentile of observed values."""
        return self._buffer.percentile(p)

    def get_values(self) -> List[float]:
        """Get all values in the window."""
        return self._buffer.get_values()

    def clear(self) -> None:
        """Clear all observations."""
        with self._lock:
            self._buffer.clear()
            self._last_value = None

    def get_count(self) -> int:
        """Get the number of observations in the window."""
        return len(self._buffer)


class RealtimeMetricsExporter:
    """
    Real-time metrics exporter for p50/p95 percentiles.

    ITEM-OBS-81: Provides real-time percentile calculations and export
    to Prometheus push gateway.

    Features:
    - Efficient circular buffer for rolling window calculations
    - Thread-safe operations
    - Configurable export intervals
    - Prometheus push gateway integration
    - Integration with existing MetricsCollector

    Usage:
        config = {
            "enabled": True,
            "export_interval_seconds": 30,
            "window_size": 100,
            "include": ["token_count_p50", "token_count_p95", "latency_p50", "latency_p95"]
        }

        exporter = RealtimeMetricsExporter(config)
        exporter.start_export(interval_seconds=30)

        # Record values
        exporter.observe_token_count(150)
        exporter.observe_latency(45.2)

        # Get current percentiles
        percentiles = exporter.get_current_percentiles()

        # Stop when done
        exporter.stop_export()
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        metrics_collector: Optional[Any] = None,
        prometheus_pushgateway_url: Optional[str] = None
    ):
        """
        Initialize the real-time metrics exporter.

        Args:
            config: Configuration dictionary
            metrics_collector: Optional MetricsCollector instance to integrate with
            prometheus_pushgateway_url: Optional Prometheus push gateway URL
        """
        if config is None:
            config = {}

        self._config = RealtimeConfig.from_dict(config)
        self._metrics_collector = metrics_collector
        self._pushgateway_url = prometheus_pushgateway_url
        self._logger = logging.getLogger(__name__)

        # Create metric windows
        self._windows: Dict[str, MetricWindow] = {}
        self._windows_lock = threading.Lock()

        # Pre-create standard windows
        self._init_standard_windows()

        # Export thread management
        self._export_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._export_interval = self._config.export_interval_seconds

        # Track if exporting is active
        self._is_exporting = False

    def _init_standard_windows(self) -> None:
        """Initialize standard metric windows."""
        window_size = self._config.window_size

        # Token count windows
        self._token_count_window = MetricWindow("token_count", window_size)
        self._windows["token_count"] = self._token_count_window

        # Latency windows
        self._latency_window = MetricWindow("latency", window_size)
        self._windows["latency"] = self._latency_window

    def register_metric(self, name: str) -> None:
        """
        Register a new metric for tracking.

        Args:
            name: Metric name
        """
        with self._windows_lock:
            if name not in self._windows:
                self._windows[name] = MetricWindow(name, self._config.window_size)

    def observe(self, metric_name: str, value: float) -> None:
        """
        Observe a value for a metric.

        Args:
            metric_name: Name of the metric
            value: The observed value
        """
        with self._windows_lock:
            if metric_name not in self._windows:
                self._windows[metric_name] = MetricWindow(metric_name, self._config.window_size)
            self._windows[metric_name].observe(value)

    def observe_token_count(self, count: float) -> None:
        """
        Observe a token count value.

        Args:
            count: The token count
        """
        self._token_count_window.observe(count)

    def observe_latency(self, latency_ms: float) -> None:
        """
        Observe a latency value.

        Args:
            latency_ms: Latency in milliseconds
        """
        self._latency_window.observe(latency_ms)

    # ========================
    # Percentile Calculation Methods
    # ========================

    @staticmethod
    def calculate_p50(values: List[float]) -> float:
        """
        Calculate the 50th percentile (median) of a list of values.

        Args:
            values: List of float values

        Returns:
            The p50 (median) value
        """
        if not values:
            return 0.0

        sorted_values = sorted(values)
        return CircularBuffer._calculate_percentile(sorted_values, 50)

    @staticmethod
    def calculate_p95(values: List[float]) -> float:
        """
        Calculate the 95th percentile of a list of values.

        Args:
            values: List of float values

        Returns:
            The p95 value
        """
        if not values:
            return 0.0

        sorted_values = sorted(values)
        return CircularBuffer._calculate_percentile(sorted_values, 95)

    @staticmethod
    def calculate_percentile(values: List[float], p: float) -> float:
        """
        Calculate the p-th percentile of a list of values.

        Args:
            values: List of float values
            p: Percentile to calculate (0-100)

        Returns:
            The p-th percentile value
        """
        if not values:
            return 0.0

        sorted_values = sorted(values)
        return CircularBuffer._calculate_percentile(sorted_values, p)

    # ========================
    # Export Methods
    # ========================

    def start_export(self, interval_seconds: int = 30) -> None:
        """
        Start the periodic export of metrics.

        Args:
            interval_seconds: Interval between exports in seconds
        """
        if not self._config.enabled:
            self._logger.info("Real-time metrics export is disabled")
            return

        if self._is_exporting:
            self._logger.warning("Export already running")
            return

        self._export_interval = interval_seconds
        self._stop_event.clear()
        self._is_exporting = True

        self._export_thread = threading.Thread(
            target=self._export_loop,
            daemon=True,
            name="RealtimeMetricsExporter"
        )
        self._export_thread.start()

        self._logger.info(f"Started real-time metrics export with {interval_seconds}s interval")

    def stop_export(self) -> None:
        """Stop the periodic export of metrics."""
        if not self._is_exporting:
            return

        self._stop_event.set()
        self._is_exporting = False

        if self._export_thread is not None:
            self._export_thread.join(timeout=5)
            self._export_thread = None

        self._logger.info("Stopped real-time metrics export")

    def _export_loop(self) -> None:
        """Main export loop running in background thread."""
        while not self._stop_event.is_set():
            try:
                self._do_export()
            except Exception as e:
                self._logger.error(f"Error in metrics export: {e}")

            # Wait for next interval or stop signal
            self._stop_event.wait(self._export_interval)

    def _do_export(self) -> None:
        """Perform the actual export of metrics."""
        percentiles = self.get_current_percentiles()

        # Log current percentiles
        self._logger.debug(f"Exporting percentiles: {percentiles}")

        # Update metrics collector if available
        if self._metrics_collector is not None:
            self._update_metrics_collector(percentiles)

        # Push to Prometheus push gateway if configured
        if self._pushgateway_url:
            self._push_to_prometheus(percentiles)

    def _update_metrics_collector(self, percentiles: Dict[str, float]) -> None:
        """Update the metrics collector with current percentiles."""
        try:
            for key, value in percentiles.items():
                gauge = self._metrics_collector.get_gauge(key)
                if gauge is None:
                    gauge = self._metrics_collector.register_gauge(
                        key,
                        f"Real-time {key} metric"
                    )
                gauge.set(value)
        except Exception as e:
            self._logger.error(f"Error updating metrics collector: {e}")

    def _push_to_prometheus(self, percentiles: Dict[str, float]) -> None:
        """Push metrics to Prometheus push gateway."""
        try:
            # Use prometheus_client if available
            from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

            registry = CollectorRegistry()

            for key, value in percentiles.items():
                gauge = Gauge(
                    f"titan_{key}",
                    f"Real-time {key} metric",
                    registry=registry
                )
                gauge.set(value)

            push_to_gateway(
                self._pushgateway_url,
                job="titan_realtime_metrics",
                registry=registry
            )

            self._logger.debug(f"Pushed metrics to Prometheus: {self._pushgateway_url}")

        except ImportError:
            self._logger.warning(
                "prometheus_client not installed, skipping Prometheus push"
            )
        except Exception as e:
            self._logger.error(f"Error pushing to Prometheus: {e}")

    # ========================
    # Query Methods
    # ========================

    def get_current_percentiles(self) -> Dict[str, float]:
        """
        Get current percentile values for all tracked metrics.

        Returns:
            Dictionary of metric_name_p50/p95: value pairs
        """
        result = {}

        with self._windows_lock:
            for name, window in self._windows.items():
                values = window.get_values()
                if values:
                    p50 = self.calculate_p50(values)
                    p95 = self.calculate_p95(values)

                    # Add both p50 and p95
                    p50_key = f"{name}_p50"
                    p95_key = f"{name}_p95"

                    # Only include if in config.include or always include standard metrics
                    if self._should_include(p50_key):
                        result[p50_key] = p50
                    if self._should_include(p95_key):
                        result[p95_key] = p95

        return result

    def _should_include(self, metric_key: str) -> bool:
        """Check if a metric should be included in output."""
        if not self._config.include:
            return True
        return metric_key in self._config.include

    def get_window_stats(self, metric_name: str) -> Dict[str, Any]:
        """
        Get statistics for a specific metric window.

        Args:
            metric_name: Name of the metric

        Returns:
            Dictionary with count, min, max, mean, p50, p95
        """
        with self._windows_lock:
            if metric_name not in self._windows:
                return {
                    "count": 0,
                    "min": 0.0,
                    "max": 0.0,
                    "mean": 0.0,
                    "p50": 0.0,
                    "p95": 0.0
                }

            window = self._windows[metric_name]
            return window._buffer.get_stats()

    def get_all_window_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Get statistics for all metric windows.

        Returns:
            Dictionary of metric_name: stats_dict
        """
        result = {}
        with self._windows_lock:
            for name, window in self._windows.items():
                result[name] = window._buffer.get_stats()
        return result

    def clear_all(self) -> None:
        """Clear all metric windows."""
        with self._windows_lock:
            for window in self._windows.values():
                window.clear()

    def is_exporting(self) -> bool:
        """Check if export is currently running."""
        return self._is_exporting

    def get_config(self) -> RealtimeConfig:
        """Get current configuration."""
        return self._config

    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the exporter state.

        Returns:
            Dictionary with configuration and current metrics
        """
        return {
            "enabled": self._config.enabled,
            "exporting": self._is_exporting,
            "export_interval_seconds": self._export_interval,
            "window_size": self._config.window_size,
            "metrics_count": len(self._windows),
            "current_percentiles": self.get_current_percentiles()
        }


# ========================
# Global Instance and Convenience Functions
# # ========================

_global_exporter: Optional[RealtimeMetricsExporter] = None
_global_lock = threading.Lock()


def get_realtime_exporter() -> RealtimeMetricsExporter:
    """
    Get the global RealtimeMetricsExporter instance.

    Returns:
        The global exporter instance
    """
    global _global_exporter
    with _global_lock:
        if _global_exporter is None:
            _global_exporter = RealtimeMetricsExporter()
        return _global_exporter


def init_realtime_exporter(
    config: Optional[Dict[str, Any]] = None,
    metrics_collector: Optional[Any] = None,
    prometheus_pushgateway_url: Optional[str] = None
) -> RealtimeMetricsExporter:
    """
    Initialize the global RealtimeMetricsExporter instance.

    Args:
        config: Configuration dictionary
        metrics_collector: Optional MetricsCollector instance
        prometheus_pushgateway_url: Optional Prometheus push gateway URL

    Returns:
        The initialized exporter instance
    """
    global _global_exporter
    with _global_lock:
        _global_exporter = RealtimeMetricsExporter(
            config=config,
            metrics_collector=metrics_collector,
            prometheus_pushgateway_url=prometheus_pushgateway_url
        )
        return _global_exporter


def observe_token_count(count: float) -> None:
    """
    Observe a token count in the global exporter.

    Args:
        count: The token count
    """
    get_realtime_exporter().observe_token_count(count)


def observe_latency(latency_ms: float) -> None:
    """
    Observe a latency value in the global exporter.

    Args:
        latency_ms: Latency in milliseconds
    """
    get_realtime_exporter().observe_latency(latency_ms)


def observe_metric(name: str, value: float) -> None:
    """
    Observe a value for a metric in the global exporter.

    Args:
        name: Metric name
        value: The observed value
    """
    get_realtime_exporter().observe(name, value)


def get_realtime_percentiles() -> Dict[str, float]:
    """
    Get current percentiles from the global exporter.

    Returns:
        Dictionary of percentile values
    """
    return get_realtime_exporter().get_current_percentiles()
