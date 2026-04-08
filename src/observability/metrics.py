"""
TITAN FUSE Protocol - Metrics Collector

Prometheus-compatible metrics collection for monitoring.
Supports counters, gauges, and histograms.

TASK-002: Advanced Observability & Transparency Layer

ITEM-OBS-03: Metrics Schema Versioning
- schema_version field in all metrics output
- Version validation and migration support
- Backward compatibility with older metrics formats
"""

import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Union, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from collections import defaultdict
import threading

from src.utils.timezone import now_utc_iso


# ITEM-OBS-03: Current metrics schema version
METRICS_SCHEMA_VERSION = "3.7.1"

# ITEM-OBS-03: Supported schema versions for migration
SUPPORTED_VERSIONS = ["unknown", "3.2.0", "3.3.0", "3.4.0", "3.7.1"]

# ITEM-OBS-05: Budget Forecasting Metrics
# These metrics are registered by BudgetForecaster when initialized:
# - titan_budget_forecast_tokens: Predicted token usage at completion (gauge)
# - titan_budget_velocity_tps: Token velocity in tokens per second (gauge)
# - titan_budget_remaining_seconds: Estimated seconds until budget exhaustion (gauge)
# - titan_budget_warning_level: Budget warning level 0=OK, 1=WARNING, 2=CRITICAL (gauge)
BUDGET_METRICS = {
    "budget_forecast_tokens": "Predicted token usage at completion",
    "budget_velocity_tps": "Token velocity in tokens per second",
    "budget_remaining_seconds": "Estimated seconds until budget exhaustion",
    "budget_warning_level": "Budget warning level (0=OK, 1=WARNING, 2=CRITICAL)"
}


class UnsupportedSchemaVersionError(Exception):
    """ITEM-OBS-03: Raised when unsupported metrics schema version is encountered."""
    def __init__(self, version: str):
        self.version = version
        super().__init__(
            f"Unsupported metrics schema version: {version}. "
            f"Supported versions: {SUPPORTED_VERSIONS}"
        )


class MetricType(Enum):
    """Types of metrics."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class MetricValue:
    """A single metric value."""
    value: Union[int, float]
    timestamp: str = field(default_factory=now_utc_iso)
    labels: Dict[str, str] = field(default_factory=dict)


class Counter:
    """
    A monotonically increasing counter.

    Usage:
        counter = Counter("requests_total", "Total requests")
        counter.increment()
        counter.increment(5)
        counter.increment(labels={"method": "GET"})
    """

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._values: Dict[str, MetricValue] = {}
        self._lock = threading.Lock()

    def _labels_key(self, labels: Optional[Dict[str, str]] = None) -> str:
        """Generate key for labels."""
        if not labels:
            return ""
        return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))

    def increment(self, value: int = 1,
                  labels: Optional[Dict[str, str]] = None) -> None:
        """Increment the counter."""
        with self._lock:
            key = self._labels_key(labels)
            if key in self._values:
                self._values[key].value += value
                self._values[key].timestamp = now_utc_iso()
            else:
                self._values[key] = MetricValue(
                    value=value,
                    labels=labels or {}
                )

    def get(self, labels: Optional[Dict[str, str]] = None) -> int:
        """Get counter value."""
        with self._lock:
            key = self._labels_key(labels)
            return int(self._values.get(key, MetricValue(value=0)).value)

    def get_all(self) -> List[MetricValue]:
        """Get all values."""
        with self._lock:
            return list(self._values.values())

    def to_prometheus(self) -> str:
        """Export to Prometheus format."""
        lines = []
        lines.append(f"# HELP {self.name} {self.description}")
        lines.append(f"# TYPE {self.name} counter")

        for value in self._values.values():
            if value.labels:
                label_str = ",".join(f'{k}="{v}"' for k, v in value.labels.items())
                lines.append(f"{self.name}{{{label_str}}} {value.value}")
            else:
                lines.append(f"{self.name} {value.value}")

        return "\n".join(lines)


class Gauge:
    """
    A gauge that can go up and down.

    Usage:
        gauge = Gauge("memory_usage_bytes", "Current memory usage")
        gauge.set(1024)
        gauge.increment(100)
        gauge.decrement(50)
    """

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._values: Dict[str, MetricValue] = {}
        self._lock = threading.Lock()

    def _labels_key(self, labels: Optional[Dict[str, str]] = None) -> str:
        """Generate key for labels."""
        if not labels:
            return ""
        return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))

    def set(self, value: Union[int, float],
            labels: Optional[Dict[str, str]] = None) -> None:
        """Set the gauge value."""
        with self._lock:
            key = self._labels_key(labels)
            self._values[key] = MetricValue(
                value=value,
                labels=labels or {}
            )

    def increment(self, value: Union[int, float] = 1,
                  labels: Optional[Dict[str, str]] = None) -> None:
        """Increment the gauge."""
        with self._lock:
            key = self._labels_key(labels)
            if key in self._values:
                self._values[key].value += value
                self._values[key].timestamp = now_utc_iso()
            else:
                self._values[key] = MetricValue(
                    value=value,
                    labels=labels or {}
                )

    def decrement(self, value: Union[int, float] = 1,
                  labels: Optional[Dict[str, str]] = None) -> None:
        """Decrement the gauge."""
        self.increment(-value, labels)

    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        """Get gauge value."""
        with self._lock:
            key = self._labels_key(labels)
            return self._values.get(key, MetricValue(value=0)).value

    def get_all(self) -> List[MetricValue]:
        """Get all values."""
        with self._lock:
            return list(self._values.values())

    def to_prometheus(self) -> str:
        """Export to Prometheus format."""
        lines = []
        lines.append(f"# HELP {self.name} {self.description}")
        lines.append(f"# TYPE {self.name} gauge")

        for value in self._values.values():
            if value.labels:
                label_str = ",".join(f'{k}="{v}"' for k, v in value.labels.items())
                lines.append(f"{self.name}{{{label_str}}} {value.value}")
            else:
                lines.append(f"{self.name} {value.value}")

        return "\n".join(lines)


@dataclass
class HistogramBucket:
    """A histogram bucket."""
    upper_bound: float
    count: int = 0


class Histogram:
    """
    A histogram for observing distributions.

    Usage:
        histogram = Histogram(
            "request_duration_seconds",
            "Request duration",
            buckets=[0.1, 0.5, 1.0, 2.5, 5.0]
        )
        histogram.observe(0.42)
        histogram.observe(1.5)

    ITEM-OBS-81: Added percentile calculation methods (p50, p95).
    """

    DEFAULT_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]

    # ITEM-OBS-81: Maximum values to store for percentile calculation
    MAX_PERCENTILE_VALUES = 10000

    def __init__(self, name: str, description: str = "",
                 buckets: Optional[List[float]] = None):
        self.name = name
        self.description = description
        self.buckets = [
            HistogramBucket(upper_bound=b)
            for b in sorted(buckets or self.DEFAULT_BUCKETS)
        ]
        # Add +Inf bucket
        self.buckets.append(HistogramBucket(upper_bound=float("inf")))
        self._sum = 0.0
        self._count = 0
        self._lock = threading.Lock()
        # ITEM-OBS-81: Store raw values for percentile calculation
        self._values: List[float] = []

    def observe(self, value: float) -> None:
        """Observe a value."""
        with self._lock:
            self._sum += value
            self._count += 1

            for bucket in self.buckets:
                if value <= bucket.upper_bound:
                    bucket.count += 1

            # ITEM-OBS-81: Store value for percentile calculation
            # Limit stored values to prevent memory issues
            if len(self._values) < self.MAX_PERCENTILE_VALUES:
                self._values.append(value)
            else:
                # Circular buffer behavior: overwrite oldest
                idx = self._count % self.MAX_PERCENTILE_VALUES
                self._values[idx] = value

    def get_sum(self) -> float:
        """Get sum of observed values."""
        with self._lock:
            return self._sum

    def get_count(self) -> int:
        """Get count of observations."""
        with self._lock:
            return self._count

    def get_average(self) -> float:
        """Get average of observed values."""
        with self._lock:
            return self._sum / self._count if self._count > 0 else 0

    # ========================
    # ITEM-OBS-81: Percentile Methods
    # ========================

    def get_values(self) -> List[float]:
        """
        Get all stored values for percentile calculation.

        ITEM-OBS-81: Returns a copy of stored values.

        Returns:
            List of observed values
        """
        with self._lock:
            return list(self._values)

    def get_percentile(self, p: float) -> float:
        """
        Calculate the p-th percentile of observed values.

        ITEM-OBS-81: Uses linear interpolation for accurate percentile calculation.

        Args:
            p: Percentile to calculate (0-100)

        Returns:
            The p-th percentile value, or 0.0 if no observations
        """
        import math

        with self._lock:
            if not self._values:
                return 0.0

            values = sorted(self._values)
            n = len(values)

            if n == 1:
                return values[0]

            # Use linear interpolation method
            rank = (p / 100.0) * (n - 1)
            lower_idx = int(math.floor(rank))
            upper_idx = int(math.ceil(rank))

            if lower_idx == upper_idx:
                return values[lower_idx]

            fraction = rank - lower_idx
            return values[lower_idx] + fraction * (values[upper_idx] - values[lower_idx])

    def get_p50(self) -> float:
        """
        Calculate the 50th percentile (median) of observed values.

        ITEM-OBS-81: Convenience method for median calculation.

        Returns:
            The median value
        """
        return self.get_percentile(50)

    def get_p95(self) -> float:
        """
        Calculate the 95th percentile of observed values.

        ITEM-OBS-81: Convenience method for p95 calculation.

        Returns:
            The p95 value
        """
        return self.get_percentile(95)

    def get_p99(self) -> float:
        """
        Calculate the 99th percentile of observed values.

        ITEM-OBS-81: Convenience method for p99 calculation.

        Returns:
            The p99 value
        """
        return self.get_percentile(99)

    def get_percentiles(self) -> Dict[str, float]:
        """
        Get common percentiles (p50, p95, p99).

        ITEM-OBS-81: Returns a dictionary of percentile values.

        Returns:
            Dictionary with p50, p95, p99 values
        """
        return {
            "p50": self.get_p50(),
            "p95": self.get_p95(),
            "p99": self.get_p99()
        }

    def to_prometheus(self) -> str:
        """Export to Prometheus format."""
        lines = []
        lines.append(f"# HELP {self.name} {self.description}")
        lines.append(f"# TYPE {self.name} histogram")

        for bucket in self.buckets:
            bound = "+Inf" if bucket.upper_bound == float("inf") else bucket.upper_bound
            lines.append(f'{self.name}_bucket{{le="{bound}"}} {bucket.count}')

        lines.append(f"{self.name}_sum {self._sum}")
        lines.append(f"{self.name}_count {self._count}")

        return "\n".join(lines)


class MetricsCollector:
    """
    Central metrics collector.

    Features:
    - Register counters, gauges, histograms
    - Prometheus export
    - JSON export
    - File export
    - Automatic collection intervals

    Usage:
        collector = MetricsCollector()

        # Register metrics
        requests = collector.register_counter("requests_total", "Total requests")
        memory = collector.register_gauge("memory_bytes", "Memory usage")
        duration = collector.register_histogram("request_duration_seconds")

        # Update metrics
        requests.increment()
        memory.set(1024)
        duration.observe(0.5)

        # Export
        print(collector.export_prometheus())
    """

    def __init__(self, namespace: str = "titan"):
        self.namespace = namespace
        self._counters: Dict[str, Counter] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._lock = threading.Lock()
        self._start_time = time.time()

    def register_counter(self, name: str, description: str = "") -> Counter:
        """Register a counter metric."""
        with self._lock:
            full_name = f"{self.namespace}_{name}"
            counter = Counter(full_name, description)
            self._counters[full_name] = counter
            return counter

    def register_gauge(self, name: str, description: str = "") -> Gauge:
        """Register a gauge metric."""
        with self._lock:
            full_name = f"{self.namespace}_{name}"
            gauge = Gauge(full_name, description)
            self._gauges[full_name] = gauge
            return gauge

    def register_histogram(self, name: str, description: str = "",
                           buckets: Optional[List[float]] = None) -> Histogram:
        """Register a histogram metric."""
        with self._lock:
            full_name = f"{self.namespace}_{name}"
            histogram = Histogram(full_name, description, buckets)
            self._histograms[full_name] = histogram
            return histogram

    def get_counter(self, name: str) -> Optional[Counter]:
        """Get a counter by name."""
        full_name = f"{self.namespace}_{name}"
        return self._counters.get(full_name)

    def get_gauge(self, name: str) -> Optional[Gauge]:
        """Get a gauge by name."""
        full_name = f"{self.namespace}_{name}"
        return self._gauges.get(full_name)

    def get_histogram(self, name: str) -> Optional[Histogram]:
        """Get a histogram by name."""
        full_name = f"{self.namespace}_{name}"
        return self._histograms.get(full_name)

    def export_prometheus(self) -> str:
        """Export all metrics in Prometheus format."""
        lines = []

        # Add process info
        lines.append(f"# HELP {self.namespace}_process_uptime_seconds Process uptime")
        lines.append(f"# TYPE {self.namespace}_process_uptime_seconds gauge")
        uptime = time.time() - self._start_time
        lines.append(f"{self.namespace}_process_uptime_seconds {uptime:.2f}")

        # Export counters
        for counter in self._counters.values():
            lines.append(counter.to_prometheus())

        # Export gauges
        for gauge in self._gauges.values():
            lines.append(gauge.to_prometheus())

        # Export histograms
        for histogram in self._histograms.values():
            lines.append(histogram.to_prometheus())

        return "\n".join(lines)

    def export_json(self) -> Dict[str, Any]:
        """
        Export all metrics as JSON.

        ITEM-OBS-03: Includes schema_version for format detection and migration.
        ITEM-OBS-81: Includes percentiles (p50, p95, p99) for histograms.
        """
        return {
            "schema_version": METRICS_SCHEMA_VERSION,  # ITEM-OBS-03
            "timestamp": now_utc_iso(),
            "namespace": self.namespace,
            "uptime_seconds": time.time() - self._start_time,
            "counters": {
                name: [v.__dict__ for v in c.get_all()]
                for name, c in self._counters.items()
            },
            "gauges": {
                name: [v.__dict__ for v in g.get_all()]
                for name, g in self._gauges.items()
            },
            "histograms": {
                name: {
                    "sum": h.get_sum(),
                    "count": h.get_count(),
                    "average": h.get_average(),
                    "percentiles": h.get_percentiles()  # ITEM-OBS-81
                }
                for name, h in self._histograms.items()
            }
        }

    def export_to_file(self, path: Path, format: str = "json") -> None:
        """Export metrics to a file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if format == "prometheus":
            content = self.export_prometheus()
        else:
            content = json.dumps(self.export_json(), indent=2)

        with open(path, "w") as f:
            f.write(content)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all metrics."""
        return {
            "namespace": self.namespace,
            "counters": len(self._counters),
            "gauges": len(self._gauges),
            "histograms": len(self._histograms),
            "uptime_seconds": time.time() - self._start_time
        }


# Global metrics collector
_global_collector: Optional[MetricsCollector] = None


def get_metrics() -> MetricsCollector:
    """Get the global metrics collector."""
    global _global_collector
    if _global_collector is None:
        _global_collector = MetricsCollector()
    return _global_collector


def increment_counter(name: str, value: int = 1,
                      labels: Optional[Dict[str, str]] = None) -> None:
    """Increment a counter in the global collector."""
    counter = get_metrics().get_counter(name)
    if counter:
        counter.increment(value, labels)


def set_gauge(name: str, value: Union[int, float],
              labels: Optional[Dict[str, str]] = None) -> None:
    """Set a gauge in the global collector."""
    gauge = get_metrics().get_gauge(name)
    if gauge:
        gauge.set(value, labels)


def observe_histogram(name: str, value: float) -> None:
    """Observe a value in a histogram."""
    histogram = get_metrics().get_histogram(name)
    if histogram:
        histogram.observe(value)


def validate_schema_version(data: Dict) -> bool:
    """
    ITEM-OBS-03: Validate metrics schema version.

    Args:
        data: Metrics data dictionary

    Returns:
        True if version is supported

    Raises:
        UnsupportedSchemaVersionError: If version is not supported
    """
    version = data.get("schema_version", "unknown")
    if version not in SUPPORTED_VERSIONS:
        raise UnsupportedSchemaVersionError(version)
    return True


def load_metrics_with_migration(path: Path) -> Dict[str, Any]:
    """
    ITEM-OBS-03: Load metrics from file with automatic migration.

    Loads metrics data and migrates to current schema version if needed.

    Args:
        path: Path to metrics JSON file

    Returns:
        Metrics data at current schema version
    """
    path = Path(path)
    if not path.exists():
        return {}

    with open(path, 'r') as f:
        data = json.load(f)

    version = data.get("schema_version", "unknown")

    # Already current version
    if version == METRICS_SCHEMA_VERSION:
        return data

    # Need migration - import here to avoid circular dependency
    try:
        from ..schema.migrations import migrate_metrics
        return migrate_metrics(data, version)
    except ImportError:
        # Migration module not available, return as-is with warning
        import logging
        logging.getLogger(__name__).warning(
            f"[gap: metrics_migration_unavailable] "
            f"Cannot migrate metrics from version {version}"
        )
        return data
