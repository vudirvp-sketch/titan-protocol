"""
Agent Metrics Collector for TITAN Protocol

Collects and exposes metrics for the Multi-Agent Orchestrator and related modules.
Integrates with Prometheus for monitoring and alerting.

Usage:
    from src.observability.agent_metrics_collector import AgentMetricsCollector

    metrics = AgentMetricsCollector()
    metrics.record_task_completion("agent_001", "file_processing", success=True)
    metrics.record_nav_fallback("agent_001")
    print(metrics.export_prometheus())
"""

import time
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class MetricValue:
    """Represents a single metric measurement."""
    name: str
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    metric_type: str = "gauge"  # gauge, counter


class AgentMetricsCollector:
    """
    Collects and aggregates metrics for agent operations.

    Provides Prometheus-compatible metric export and integrates
    with the Multi-Agent Orchestrator for observability.
    """

    def __init__(self, prefix: str = "titan", enabled: bool = True):
        """
        Initialize the metrics collector.

        Args:
            prefix: Metric name prefix for Prometheus export
            enabled: Whether metrics collection is enabled
        """
        self.prefix = prefix
        self.enabled = enabled
        self._lock = threading.RLock()

        # Storage for different metric types
        self._gauges: Dict[str, MetricValue] = {}
        self._counters: Dict[str, float] = defaultdict(float)
        self._histograms: Dict[str, List[float]] = defaultdict(list)

        # Task completion tracking
        self._task_attempts: Dict[str, int] = defaultdict(int)
        self._task_successes: Dict[str, int] = defaultdict(int)

        # Navigation tracking
        self._nav_lookups: int = 0
        self._nav_fallbacks: int = 0

        # Onboarding tracking
        self._onboarding_times: Dict[str, float] = {}

        # Version drift tracking
        self._drift_events: List[Dict[str, Any]] = []

        # Default labels applied to all metrics
        self._default_labels: Dict[str, str] = {
            "protocol_version": "4.1.0",
            "tier": "TIER_7_PRODUCTION",
        }

        logger.info(f"AgentMetricsCollector initialized (prefix={prefix}, enabled={enabled})")

    def record_task_completion(
        self,
        agent_id: str,
        task_type: str,
        success: bool,
        latency_ms: Optional[float] = None
    ) -> None:
        """
        Record a task completion event.

        Args:
            agent_id: Identifier of the agent
            task_type: Type of task performed
            success: Whether the task succeeded
            latency_ms: Optional task latency in milliseconds
        """
        if not self.enabled:
            return

        with self._lock:
            key = f"{agent_id}:{task_type}"
            self._task_attempts[key] += 1

            if success:
                self._task_successes[key] += 1

            # Update counter
            counter_key = f"agent_task_total"
            labels = {
                "agent_id": agent_id,
                "task_type": task_type,
                "status": "success" if success else "failure"
            }
            self._increment_counter(counter_key, labels)

            # Record latency if provided
            if latency_ms is not None:
                self._record_latency(agent_id, latency_ms)

            # Update completion rate gauge
            self._update_completion_rate(agent_id, task_type)

        logger.debug(f"Recorded task completion: {agent_id}/{task_type} success={success}")

    def record_nav_fallback(self, agent_id: str) -> None:
        """
        Record a navigation fallback event.

        Args:
            agent_id: Identifier of the agent
        """
        if not self.enabled:
            return

        with self._lock:
            self._nav_lookups += 1
            self._nav_fallbacks += 1

            # Increment counter
            self._increment_counter("nav_map_lookup_total", {
                "agent_id": agent_id,
                "result": "fallback"
            })

            # Update fallback rate
            self._update_fallback_rate()

        logger.debug(f"Recorded nav fallback for {agent_id}")

    def record_nav_success(self, agent_id: str) -> None:
        """
        Record a successful navigation lookup.

        Args:
            agent_id: Identifier of the agent
        """
        if not self.enabled:
            return

        with self._lock:
            self._nav_lookups += 1

            self._increment_counter("nav_map_lookup_total", {
                "agent_id": agent_id,
                "result": "success"
            })

            self._update_fallback_rate()

    def record_onboarding_time(self, agent_id: str, seconds: float) -> None:
        """
        Record agent onboarding time.

        Args:
            agent_id: Identifier of the agent
            seconds: Time in seconds for onboarding
        """
        if not self.enabled:
            return

        with self._lock:
            self._onboarding_times[agent_id] = seconds
            self._gauges["agent_onboarding_time_seconds"] = MetricValue(
                name="agent_onboarding_time_seconds",
                value=seconds,
                labels={"agent_id": agent_id}
            )

        logger.debug(f"Recorded onboarding time for {agent_id}: {seconds}s")

    def record_version_drift(
        self,
        source: str,
        detected_version: str,
        expected_version: str
    ) -> None:
        """
        Record a version drift detection event.

        Args:
            source: Source where drift was detected
            detected_version: The version that was found
            expected_version: The version that was expected
        """
        if not self.enabled:
            return

        with self._lock:
            event = {
                "source": source,
                "detected_version": detected_version,
                "expected_version": expected_version,
                "timestamp": time.time()
            }
            self._drift_events.append(event)

            # Increment counter
            self._increment_counter("version_drift_events", {
                "source": source,
                "detected_version": detected_version,
                "expected_version": expected_version
            })

            # Update sync status gauge
            self._gauges["version_sync_status"] = MetricValue(
                name="version_sync_status",
                value=0,  # 0 = drift detected
                labels={"source": source}
            )

        logger.warning(
            f"Version drift detected: {source} "
            f"(found={detected_version}, expected={expected_version})"
        )

    def record_migration(
        self,
        from_version: str,
        to_version: str,
        success: bool
    ) -> None:
        """
        Record a migration event.

        Args:
            from_version: Source version
            to_version: Target version
            success: Whether the migration succeeded
        """
        if not self.enabled:
            return

        with self._lock:
            self._increment_counter("migration_total", {
                "from_version": from_version,
                "to_version": to_version,
                "status": "success" if success else "failed"
            })

        logger.debug(f"Recorded migration: {from_version} → {to_version} success={success}")

    def record_checkpoint_operation(
        self,
        operation: str,
        status: str,
        size_bytes: Optional[int] = None
    ) -> None:
        """
        Record a checkpoint operation.

        Args:
            operation: Operation type (save/load)
            status: Operation status (success/failed)
            size_bytes: Optional checkpoint size
        """
        if not self.enabled:
            return

        with self._lock:
            if operation == "save":
                self._increment_counter("checkpoint_save_total", {"status": status})
            elif operation == "load":
                self._increment_counter("checkpoint_load_total", {"status": status})

            if size_bytes is not None:
                self._gauges["checkpoint_size_bytes"] = MetricValue(
                    name="checkpoint_size_bytes",
                    value=size_bytes,
                    labels={"operation": operation}
                )

    def record_eventbus_event(
        self,
        event_type: str,
        source: str,
        success: bool = True
    ) -> None:
        """
        Record an EventBus event.

        Args:
            event_type: Type of event
            source: Event source
            success: Whether the event was processed successfully
        """
        if not self.enabled:
            return

        with self._lock:
            if success:
                self._increment_counter("eventbus_events_total", {
                    "event_type": event_type,
                    "source": source
                })
            else:
                self._increment_counter("eventbus_dlq_total", {
                    "event_type": event_type,
                    "error_reason": "processing_failed"
                })

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get all collected metrics as a dictionary.

        Returns:
            Dictionary containing all metrics
        """
        with self._lock:
            metrics = {
                "gauges": {
                    name: {
                        "value": m.value,
                        "labels": m.labels,
                        "timestamp": m.timestamp
                    }
                    for name, m in self._gauges.items()
                },
                "counters": dict(self._counters),
                "summary": {
                    "total_nav_lookups": self._nav_lookups,
                    "total_nav_fallbacks": self._nav_fallbacks,
                    "total_drift_events": len(self._drift_events),
                    "onboarding_times": dict(self._onboarding_times)
                }
            }
            return metrics

    def export_prometheus(self) -> str:
        """
        Export metrics in Prometheus text format.

        Returns:
            Prometheus-formatted metrics string
        """
        if not self.enabled:
            return "# Metrics collection disabled\n"

        lines = []
        lines.append("# HELP titan_agent_info TITAN Protocol Agent Information")
        lines.append("# TYPE titan_agent_info gauge")
        lines.append(f'titan_agent_info{{version="{self._default_labels["protocol_version"]}",'
                    f'tier="{self._default_labels["tier"]}"}} 1')

        # Export gauges
        for name, metric in self._gauges.items():
            prom_name = f"{self.prefix}_{name}"
            labels_str = self._format_labels(metric.labels)
            lines.append(f"{prom_name}{labels_str} {metric.value}")

        # Export counters
        for key, value in self._counters.items():
            prom_name = f"{self.prefix}_{key}"
            lines.append(f"{prom_name} {value}")

        # Export histograms/latencies
        for agent_id, latencies in self._histograms.items():
            if latencies:
                sorted_latencies = sorted(latencies)
                count = len(sorted_latencies)

                p50_idx = int(count * 0.50)
                p95_idx = int(count * 0.95)
                p99_idx = int(count * 0.99)

                lines.append(f'{self.prefix}_agent_task_latency_p50{{agent_id="{agent_id}"}} '
                           f'{sorted_latencies[min(p50_idx, count-1)]:.2f}')
                lines.append(f'{self.prefix}_agent_task_latency_p95{{agent_id="{agent_id}"}} '
                           f'{sorted_latencies[min(p95_idx, count-1)]:.2f}')
                lines.append(f'{self.prefix}_agent_task_latency_p99{{agent_id="{agent_id}"}} '
                           f'{sorted_latencies[min(p99_idx, count-1)]:.2f}')

        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        """Reset all metrics (useful for testing)."""
        with self._lock:
            self._gauges.clear()
            self._counters.clear()
            self._histograms.clear()
            self._task_attempts.clear()
            self._task_successes.clear()
            self._nav_lookups = 0
            self._nav_fallbacks = 0
            self._onboarding_times.clear()
            self._drift_events.clear()

    def _increment_counter(self, name: str, labels: Dict[str, str]) -> None:
        """Increment a counter metric."""
        key = f"{name}:{self._format_labels(labels)}"
        self._counters[key] += 1

    def _record_latency(self, agent_id: str, latency_ms: float) -> None:
        """Record latency for histogram calculation."""
        self._histograms[agent_id].append(latency_ms)
        # Keep only last 1000 measurements
        if len(self._histograms[agent_id]) > 1000:
            self._histograms[agent_id] = self._histograms[agent_id][-1000:]

    def _update_completion_rate(self, agent_id: str, task_type: str) -> None:
        """Update the task completion rate gauge."""
        key = f"{agent_id}:{task_type}"
        attempts = self._task_attempts[key]
        successes = self._task_successes[key]

        if attempts > 0:
            rate = successes / attempts
            self._gauges["agent_task_completion_rate"] = MetricValue(
                name="agent_task_completion_rate",
                value=rate,
                labels={"agent_id": agent_id, "task_type": task_type}
            )

    def _update_fallback_rate(self) -> None:
        """Update the navigation fallback rate gauge."""
        if self._nav_lookups > 0:
            rate = self._nav_fallbacks / self._nav_lookups
            self._gauges["nav_map_fallback_rate"] = MetricValue(
                name="nav_map_fallback_rate",
                value=rate,
                labels={}
            )

    def _format_labels(self, labels: Dict[str, str]) -> str:
        """Format labels for Prometheus export."""
        if not labels:
            return ""

        combined = {**self._default_labels, **labels}
        pairs = [f'{k}="{v}"' for k, v in combined.items()]
        return "{" + ", ".join(pairs) + "}"


# Singleton instance for global access
_collector_instance: Optional[AgentMetricsCollector] = None


def get_metrics_collector() -> AgentMetricsCollector:
    """Get the global metrics collector instance."""
    global _collector_instance
    if _collector_instance is None:
        _collector_instance = AgentMetricsCollector()
    return _collector_instance
