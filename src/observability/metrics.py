"""
TITAN FUSE Protocol - Metrics Collector

Prometheus-compatible metrics collection for monitoring.
Supports counters, gauges, and histograms.

TASK-002: Advanced Observability & Transparency Layer
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


class MetricType(Enum):
    """Types of metrics."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class MetricValue:
    """A single metric value."""
    value: Union[int, float]
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
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
                self._values[key].timestamp = datetime.utcnow().isoformat() + "Z"
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
                self._values[key].timestamp = datetime.utcnow().isoformat() + "Z"
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
    """

    DEFAULT_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]

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

    def observe(self, value: float) -> None:
        """Observe a value."""
        with self._lock:
            self._sum += value
            self._count += 1

            for bucket in self.buckets:
                if value <= bucket.upper_bound:
                    bucket.count += 1

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
        """Export all metrics as JSON."""
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
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
                    "average": h.get_average()
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
