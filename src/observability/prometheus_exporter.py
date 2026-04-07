"""
Prometheus Metrics Exporter for TITAN FUSE Protocol.

ITEM-OBS-01: Provides Prometheus-compatible metrics endpoint
for monitoring and observability.

Author: TITAN FUSE Team
Version: 3.4.0
"""

from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import logging
import time
from collections import defaultdict


@dataclass
class MetricConfig:
    """Prometheus exporter configuration."""
    enabled: bool
    port: int
    path: str
    
    def to_dict(self) -> Dict:
        return {
            "enabled": self.enabled,
            "port": self.port,
            "path": self.path
        }


@dataclass
class Metric:
    """A Prometheus metric."""
    name: str
    metric_type: str  # gauge, counter, histogram, summary
    help_text: str
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)
    
    def to_prometheus_format(self) -> str:
        """Convert to Prometheus text format."""
        lines = []
        
        # Help and type
        lines.append(f"# HELP {self.name} {self.help_text}")
        lines.append(f"# TYPE {self.name} {self.metric_type}")
        
        # Value with labels
        if self.labels:
            label_str = ",".join(f'{k}="{v}"' for k, v in self.labels.items())
            lines.append(f"{self.name}{{{label_str}}} {self.value}")
        else:
            lines.append(f"{self.name} {self.value}")
        
        return "\n".join(lines)


class PrometheusMetricsStore:
    """
    Thread-safe storage for Prometheus metrics.
    
    Stores metrics with support for:
    - Gauges (can go up or down)
    - Counters (only increase)
    - Labeled metrics
    """
    
    def __init__(self):
        self._metrics: Dict[str, Metric] = {}
        self._counters: Dict[str, float] = {}
        self._lock = threading.Lock()
    
    def register_metric(self, name: str, metric_type: str, help_text: str) -> None:
        """Register a new metric."""
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = Metric(
                    name=name,
                    metric_type=metric_type,
                    help_text=help_text
                )
    
    def set_metric(self, name: str, value: float, labels: Dict[str, str] = None) -> None:
        """Set a gauge metric value."""
        with self._lock:
            if name in self._metrics:
                metric = self._metrics[name]
                metric.value = value
                if labels:
                    metric.labels = labels
            else:
                self._metrics[name] = Metric(
                    name=name,
                    metric_type="gauge",
                    help_text="",
                    value=value,
                    labels=labels or {}
                )
    
    def increment_counter(self, name: str, amount: float = 1.0, 
                         labels: Dict[str, str] = None) -> None:
        """Increment a counter metric."""
        with self._lock:
            key = self._make_key(name, labels)
            self._counters[key] = self._counters.get(key, 0) + amount
            
            if name in self._metrics:
                metric = self._metrics[name]
                metric.value = self._counters[key]
                if labels:
                    metric.labels = labels
    
    def _make_key(self, name: str, labels: Dict[str, str] = None) -> str:
        """Create a unique key for a metric with labels."""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"
    
    def get_all_metrics(self) -> List[Metric]:
        """Get all metrics."""
        with self._lock:
            return list(self._metrics.values())
    
    def get_prometheus_output(self) -> str:
        """Get all metrics in Prometheus text format."""
        metrics = self.get_all_metrics()
        return "\n".join(m.to_prometheus_format() for m in metrics) + "\n"


# Global metrics store
_metrics_store: Optional[PrometheusMetricsStore] = None


def get_metrics_store() -> PrometheusMetricsStore:
    """Get the global metrics store."""
    global _metrics_store
    if _metrics_store is None:
        _metrics_store = PrometheusMetricsStore()
    return _metrics_store


class PrometheusRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Prometheus metrics endpoint."""
    
    def log_message(self, format, *args):
        """Override to use custom logger."""
        logging.getLogger(__name__).debug(f"Prometheus: {args[0]}")
    
    def do_GET(self):
        """Handle GET request."""
        if self.path == self.server.metrics_path:
            self._serve_metrics()
        else:
            self.send_error(404, "Not Found")
    
    def _serve_metrics(self):
        """Serve metrics in Prometheus format."""
        try:
            output = get_metrics_store().get_prometheus_output()
            
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(output.encode('utf-8'))
            
        except Exception as e:
            self.send_error(500, f"Internal Error: {e}")


class PrometheusExporter:
    """
    Prometheus metrics exporter for TITAN Protocol.
    
    ITEM-OBS-01: Prometheus metrics endpoint implementation.
    
    Provides:
    - HTTP endpoint for Prometheus scraping
    - Standard TITAN metrics
    - Custom metric registration
    - Thread-safe metric storage
    
    Usage:
        config = {
            "enabled": True,
            "port": 9090,
            "path": "/metrics"
        }
        
        exporter = PrometheusExporter(config)
        exporter.start_server()
        
        # Set metrics
        exporter.set_metric("titan_budget_state", 50000)
        exporter.increment_counter("titan_gates_passed_total")
        
        # Stop when done
        exporter.stop_server()
    """
    
    DEFAULT_CONFIG = MetricConfig(
        enabled=False,
        port=9090,
        path="/metrics"
    )
    
    # Standard TITAN metrics
    STANDARD_METRICS = [
        ("titan_query_p50_tokens", "gauge", "P50 token count for queries"),
        ("titan_query_p95_latency_ms", "gauge", "P95 latency in milliseconds"),
        ("titan_budget_state", "gauge", "Current token budget remaining"),
        ("titan_gates_passed_total", "counter", "Total number of gates passed"),
        ("titan_gates_failed_total", "counter", "Total number of gates failed"),
        ("titan_chunks_processed_total", "counter", "Total chunks processed"),
        ("titan_session_duration_seconds", "gauge", "Current session duration"),
        ("titan_errors_total", "counter", "Total errors encountered"),
        ("titan_checkpoints_saved_total", "counter", "Total checkpoints saved"),
        ("titan_fallback_activations_total", "counter", "Total model fallback activations"),
    ]
    
    def __init__(self, config: Dict = None):
        """
        Initialize Prometheus exporter.
        
        Args:
            config: Exporter configuration dictionary
        """
        if config is None:
            config = {}
        
        self._config = MetricConfig(
            enabled=config.get("enabled", self.DEFAULT_CONFIG.enabled),
            port=config.get("port", self.DEFAULT_CONFIG.port),
            path=config.get("path", self.DEFAULT_CONFIG.path)
        )
        
        self._logger = logging.getLogger(__name__)
        self._server: Optional[HTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._store = get_metrics_store()
        
        # Register standard metrics
        self._register_standard_metrics()
    
    def _register_standard_metrics(self) -> None:
        """Register standard TITAN metrics."""
        for name, metric_type, help_text in self.STANDARD_METRICS:
            self._store.register_metric(name, metric_type, help_text)
    
    def register_metric(self, name: str, metric_type: str, help_text: str) -> None:
        """
        Register a custom metric.
        
        Args:
            name: Metric name (should start with titan_)
            metric_type: Type (gauge, counter, histogram, summary)
            help_text: Description of the metric
        """
        self._store.register_metric(name, metric_type, help_text)
    
    def set_metric(self, name: str, value: float, labels: Dict[str, str] = None) -> None:
        """
        Set a metric value.
        
        Args:
            name: Metric name
            value: Current value
            labels: Optional labels for the metric
        """
        self._store.set_metric(name, value, labels)
    
    def increment_counter(self, name: str, amount: float = 1.0,
                         labels: Dict[str, str] = None) -> None:
        """
        Increment a counter metric.
        
        Args:
            name: Metric name
            amount: Amount to increment
            labels: Optional labels
        """
        self._store.increment_counter(name, amount, labels)
    
    def start_server(self) -> bool:
        """
        Start the Prometheus HTTP server.
        
        Returns:
            True if server started successfully
        """
        if not self._config.enabled:
            self._logger.info("Prometheus exporter disabled")
            return False
        
        if self._server is not None:
            self._logger.warning("Server already running")
            return True
        
        try:
            self._server = HTTPServer(
                ("0.0.0.0", self._config.port),
                PrometheusRequestHandler
            )
            self._server.metrics_path = self._config.path
            
            self._server_thread = threading.Thread(
                target=self._server.serve_forever,
                daemon=True
            )
            self._server_thread.start()
            
            self._logger.info(
                f"Prometheus exporter started on port {self._config.port} "
                f"at {self._config.path}"
            )
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to start Prometheus server: {e}")
            return False
    
    def stop_server(self) -> None:
        """Stop the Prometheus HTTP server."""
        if self._server is not None:
            self._server.shutdown()
            self._server = None
            self._server_thread = None
            self._logger.info("Prometheus exporter stopped")
    
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._server is not None
    
    def get_metrics_output(self) -> str:
        """Get current metrics in Prometheus format."""
        return self._store.get_prometheus_output()
    
    def get_config(self) -> MetricConfig:
        """Get current configuration."""
        return self._config
    
    def update_config(self, config: Dict) -> None:
        """Update configuration (requires server restart)."""
        if "enabled" in config:
            self._config.enabled = config["enabled"]
        if "port" in config:
            self._config.port = config["port"]
        if "path" in config:
            self._config.path = config["path"]
        
        self._logger.info(f"Config updated: {config}")


def create_prometheus_exporter(config: Dict = None) -> PrometheusExporter:
    """
    Factory function to create a PrometheusExporter.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        PrometheusExporter instance
    """
    return PrometheusExporter(config)
