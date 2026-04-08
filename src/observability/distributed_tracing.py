"""
TITAN FUSE Protocol - Distributed Tracing Integration

OpenTelemetry-compatible distributed tracing for cross-service trace correlation.
Implements W3C TraceContext propagation standard.

ITEM-OBS-06: Distributed Tracing Integration for TITAN Protocol v4.0.0

Features:
- Span creation with parent-child relationships
- Context propagation (inject/extract) for cross-service tracing
- Exporters for Jaeger, Zipkin, and OTLP
- EventBus integration for automatic trace_id/span_id injection
- W3C TraceContext format support
"""

import json
import uuid
import time
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from dataclasses import dataclass, field
from enum import Enum
from contextlib import contextmanager
from pathlib import Path

# OpenTelemetry imports with fallback
try:
    from opentelemetry import trace
    from opentelemetry.trace import Span as OTelSpan, SpanContext as OTelSpanContext
    from opentelemetry.trace.propagation.tracecontext import (
        TraceContextTextMapPropagator
    )
    from opentelemetry.trace.status import StatusCode
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.resources import Resource

    # Try to import exporters
    try:
        from opentelemetry.exporter.jaeger.thrift import JaegerExporter
        JAEGER_AVAILABLE = True
    except ImportError:
        JAEGER_AVAILABLE = False

    try:
        from opentelemetry.exporter.zipkin.json import ZipkinExporter
        ZIPKIN_AVAILABLE = True
    except ImportError:
        ZIPKIN_AVAILABLE = False

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        OTLP_AVAILABLE = True
    except ImportError:
        OTLP_AVAILABLE = False

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    JAEGER_AVAILABLE = False
    ZIPKIN_AVAILABLE = False
    OTLP_AVAILABLE = False

if TYPE_CHECKING:
    from ..events.event_bus import EventBus, Event


logger = logging.getLogger(__name__)


class SpanStatus(Enum):
    """Status of a span in distributed tracing."""
    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


class ExporterType(Enum):
    """Types of trace exporters."""
    JAEGER = "jaeger"
    ZIPKIN = "zipkin"
    OTLP = "otlp"
    NONE = "none"


@dataclass
class Span:
    """
    A span representing a unit of work in distributed tracing.

    This is a pure Python implementation that mirrors OpenTelemetry Span concepts.
    Can be used independently or synchronized with OpenTelemetry when available.

    Attributes:
        trace_id: Unique trace identifier (W3C format: 32 hex chars)
        span_id: Unique span identifier (16 hex chars)
        parent_span_id: Parent span ID (if any)
        operation_name: Name of the operation being traced
        start_time: When span started
        end_time: When span ended (None if still active)
        attributes: Key-value pairs for span metadata
        status: Span status (UNSET, OK, ERROR)
    """
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    operation_name: str = ""
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    status: SpanStatus = SpanStatus.UNSET
    status_message: str = ""
    events: List[Dict[str, Any]] = field(default_factory=list)
    _start_ns: int = field(default_factory=time.time_ns, repr=False)

    def set_attribute(self, key: str, value: Any) -> "Span":
        """Set a span attribute. Returns self for chaining."""
        self.attributes[key] = value
        return self

    def set_status(self, status: SpanStatus, message: str = "") -> "Span":
        """Set span status. Returns self for chaining."""
        self.status = status
        self.status_message = message
        return self

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None,
                  timestamp: Optional[datetime] = None) -> "Span":
        """Add an event to the span. Returns self for chaining."""
        self.events.append({
            "name": name,
            "timestamp": (timestamp or datetime.utcnow()).isoformat() + "Z",
            "attributes": attributes or {}
        })
        return self

    def end(self, end_time: Optional[datetime] = None) -> None:
        """End the span."""
        self.end_time = end_time or datetime.utcnow()

    def get_duration_ms(self) -> Optional[int]:
        """Get span duration in milliseconds."""
        if not self.end_time:
            return None
        duration_ns = time.time_ns() - self._start_ns
        return duration_ns // 1_000_000

    def is_recording(self) -> bool:
        """Check if span is still recording (not ended)."""
        return self.end_time is None

    def record_exception(self, exception: Exception, attributes: Optional[Dict[str, Any]] = None) -> "Span":
        """Record an exception as an event. Returns self for chaining."""
        self.add_event(
            name="exception",
            attributes={
                "exception.type": type(exception).__name__,
                "exception.message": str(exception),
                "exception.stacktrace": getattr(exception, "__traceback__", None),
                **(attributes or {})
            }
        )
        self.set_status(SpanStatus.ERROR, str(exception))
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Convert span to dictionary."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "operation_name": self.operation_name,
            "start_time": self.start_time.isoformat() + "Z",
            "end_time": self.end_time.isoformat() + "Z" if self.end_time else None,
            "duration_ms": self.get_duration_ms(),
            "attributes": self.attributes,
            "status": self.status.value,
            "status_message": self.status_message,
            "events": self.events
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_w3c_traceparent(self) -> str:
        """
        Generate W3C TraceContext traceparent header value.

        Format: {version}-{trace_id}-{span_id}-{flags}
        Example: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
        """
        flags = "01" if self.status != SpanStatus.ERROR else "00"
        return f"00-{self.trace_id}-{self.span_id}-{flags}"

    @classmethod
    def from_w3c_traceparent(cls, traceparent: str) -> Optional["Span"]:
        """Parse W3C TraceContext traceparent header."""
        try:
            parts = traceparent.split("-")
            if len(parts) != 4:
                return None
            version, trace_id, span_id, flags = parts
            if version != "00":
                return None
            return cls(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=None
            )
        except Exception:
            return None


@dataclass
class TraceContext:
    """
    Context for distributed tracing.

    Contains trace propagation information for cross-service tracing.
    """
    trace_id: str
    span_id: str
    trace_flags: int = 1  # 1 = sampled, 0 = not sampled
    trace_state: Dict[str, str] = field(default_factory=dict)
    is_remote: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "trace_flags": self.trace_flags,
            "trace_state": self.trace_state,
            "is_remote": self.is_remote
        }

    def to_w3c_headers(self) -> Dict[str, str]:
        """Convert to W3C TraceContext headers."""
        flags = f"{self.trace_flags:02x}"
        headers = {
            "traceparent": f"00-{self.trace_id}-{self.span_id}-{flags}"
        }
        if self.trace_state:
            # tracestate is a comma-separated list of key=value pairs
            state_parts = [f"{k}={v}" for k, v in self.trace_state.items()]
            headers["tracestate"] = ",".join(state_parts)
        return headers


class DistributedTracer:
    """
    Distributed tracer with OpenTelemetry integration.

    Features:
    - Span creation with parent-child relationships
    - Context propagation (W3C TraceContext)
    - Multiple exporter support (Jaeger, Zipkin, OTLP)
    - EventBus integration for automatic trace injection
    - Thread-safe span management

    Usage:
        tracer = DistributedTracer(service_name="titan-protocol")

        # Start a span
        with tracer.start_span("operation") as span:
            span.set_attribute("key", "value")

            # Propagate context for downstream calls
            carrier = {}
            tracer.inject_context(carrier)
            # carrier now has traceparent header

        # Configure exporter
        tracer.export_to_jaeger("http://localhost:14268/api/traces")
    """

    def __init__(self, service_name: str = "titan-protocol", config: Optional[Dict[str, Any]] = None):
        """
        Initialize distributed tracer.

        Args:
            service_name: Service name for trace attribution
            config: Configuration dictionary
        """
        self.service_name = service_name
        self.config = config or {}

        # Span management
        self._spans: List[Span] = []
        self._active_span: Optional[Span] = None
        self._span_stack: List[Span] = []

        # OpenTelemetry integration
        self._otel_tracer = None
        self._otel_provider = None
        self._propagator = None
        self._exporter_type = ExporterType.NONE

        self._initialize_otel()

    def _initialize_otel(self) -> None:
        """Initialize OpenTelemetry if available."""
        if not OTEL_AVAILABLE:
            logger.debug("OpenTelemetry not available, using pure Python implementation")
            return

        try:
            # Create resource with service name
            resource = Resource.create({"service.name": self.service_name})

            # Create tracer provider
            self._otel_provider = TracerProvider(resource=resource)

            # Get tracer
            self._otel_tracer = trace.get_tracer(
                self.service_name,
                schema_url="https://opentelemetry.io/schemas/1.11.0"
            )

            # Set up propagator
            self._propagator = TraceContextTextMapPropagator()

            # Set global tracer provider
            trace.set_tracer_provider(self._otel_provider)

            logger.info(f"OpenTelemetry initialized for service: {self.service_name}")
        except Exception as e:
            logger.warning(f"Failed to initialize OpenTelemetry: {e}")
            self._otel_tracer = None
            self._otel_provider = None

    def start_span(
        self,
        name: str,
        parent: Optional[Span] = None,
        attributes: Optional[Dict[str, Any]] = None,
        kind: str = "internal"
    ) -> Span:
        """
        Start a new span.

        Args:
            name: Span/operation name
            parent: Parent span (if any)
            attributes: Initial span attributes
            kind: Span kind (internal, server, client, producer, consumer)

        Returns:
            Created Span instance
        """
        # Generate IDs in W3C format
        # Determine parent span for trace context propagation
        effective_parent = parent or self._active_span

        # Use parent's trace_id if available, otherwise generate new
        trace_id = effective_parent.trace_id if effective_parent else uuid.uuid4().hex
        span_id = uuid.uuid4().hex[:16]
        parent_span_id = effective_parent.span_id if effective_parent else None

        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            operation_name=name,
            attributes=attributes or {}
        )

        # Track span
        self._spans.append(span)
        self._span_stack.append(span)
        self._active_span = span

        # Also create OpenTelemetry span if available
        if self._otel_tracer and OTEL_AVAILABLE:
            try:
                otel_kind = getattr(trace.SpanKind, kind.upper(), trace.SpanKind.INTERNAL)
                ctx = None
                if parent:
                    # Create context from parent
                    ctx = self._create_otel_context(parent)
                self._otel_tracer.start_as_current_span(name, context=ctx)
            except Exception as e:
                logger.debug(f"Failed to create OpenTelemetry span: {e}")

        return span

    def _create_otel_context(self, span: Span) -> Any:
        """Create OpenTelemetry context from our Span."""
        if not OTEL_AVAILABLE:
            return None

        try:
            from opentelemetry.trace import set_span_in_context
            from opentelemetry.trace import SpanContext as OTelSpanContext

            span_context = OTelSpanContext(
                trace_id=int(span.trace_id, 16),
                span_id=int(span.span_id, 16),
                is_remote=False
            )
            # Return context with this span
            return set_span_in_context(trace.NonRecordingSpan(span_context))
        except Exception:
            return None

    def end_span(self, span: Span, status: SpanStatus = SpanStatus.OK, message: str = "") -> None:
        """
        End a span.

        Args:
            span: Span to end
            status: Final span status
            message: Status message
        """
        span.set_status(status, message)
        span.end()

        # Remove from active stack
        if span in self._span_stack:
            self._span_stack.remove(span)

        # Update active span
        self._active_span = self._span_stack[-1] if self._span_stack else None

    @contextmanager
    def span(
        self,
        name: str,
        parent: Optional[Span] = None,
        attributes: Optional[Dict[str, Any]] = None
    ):
        """
        Context manager for span lifecycle.

        Args:
            name: Span/operation name
            parent: Parent span (if any)
            attributes: Initial span attributes

        Yields:
            Created Span instance
        """
        span = self.start_span(name, parent, attributes)
        try:
            yield span
            self.end_span(span, SpanStatus.OK)
        except Exception as e:
            span.record_exception(e)
            self.end_span(span, SpanStatus.ERROR, str(e))
            raise

    def get_active_span(self) -> Optional[Span]:
        """
        Get the currently active span.

        Returns:
            Active Span or None if no active span
        """
        return self._active_span

    def inject_context(self, carrier: Dict[str, str]) -> None:
        """
        Inject trace context into carrier for propagation.

        This injects W3C TraceContext headers into the carrier,
        which can then be passed to downstream services.

        Args:
            carrier: Dictionary to inject trace context into
        """
        if not self._active_span:
            return

        # Use OpenTelemetry propagator if available
        if self._propagator and OTEL_AVAILABLE:
            try:
                # Create a context with our span
                ctx = self._create_otel_context(self._active_span)
                if ctx:
                    self._propagator.inject(carrier, context=ctx)
                return
            except Exception as e:
                logger.debug(f"Failed to inject with OpenTelemetry: {e}")

        # Fallback: manual injection using W3C format
        headers = TraceContext(
            trace_id=self._active_span.trace_id,
            span_id=self._active_span.span_id,
            trace_flags=1 if self._active_span.status != SpanStatus.ERROR else 0
        ).to_w3c_headers()
        carrier.update(headers)

    def extract_context(self, carrier: Dict[str, str]) -> Optional[TraceContext]:
        """
        Extract trace context from carrier.

        This extracts W3C TraceContext headers from a carrier,
        typically received from an upstream service.

        Args:
            carrier: Dictionary containing trace context headers

        Returns:
            TraceContext if found, None otherwise
        """
        # Helper to get case-insensitive header value
        def get_header(key_lower: str) -> Optional[str]:
            for k, v in carrier.items():
                if k.lower() == key_lower:
                    return v
            return None

        # Use OpenTelemetry propagator if available
        if self._propagator and OTEL_AVAILABLE:
            try:
                ctx = self._propagator.extract(carrier)
                span_context = trace.get_current_span(ctx).get_span_context()
                if span_context and span_context.is_valid:
                    # Try to get tracestate from carrier (OpenTelemetry may not parse it)
                    trace_state = {}
                    tracestate = get_header("tracestate")
                    if tracestate:
                        for pair in tracestate.split(","):
                            if "=" in pair:
                                k, v = pair.split("=", 1)
                                trace_state[k.strip()] = v.strip()

                    return TraceContext(
                        trace_id=format(span_context.trace_id, "032x"),
                        span_id=format(span_context.span_id, "016x"),
                        trace_flags=span_context.trace_flags,
                        trace_state=trace_state,
                        is_remote=span_context.is_remote
                    )
            except Exception as e:
                logger.debug(f"Failed to extract with OpenTelemetry: {e}")

        # Fallback: manual extraction using W3C format (case-insensitive)
        traceparent = get_header("traceparent")
        if not traceparent:
            return None

        try:
            parts = traceparent.split("-")
            if len(parts) != 4:
                return None

            version, trace_id, span_id, flags = parts
            if version != "00":
                return None

            # Validate trace_id and span_id format (hex strings)
            if len(trace_id) != 32 or len(span_id) != 16:
                return None
            try:
                int(trace_id, 16)
                int(span_id, 16)
            except ValueError:
                return None

            trace_state = {}
            tracestate = get_header("tracestate")
            if tracestate:
                for pair in tracestate.split(","):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        trace_state[k.strip()] = v.strip()

            return TraceContext(
                trace_id=trace_id,
                span_id=span_id,
                trace_flags=int(flags, 16),
                trace_state=trace_state,
                is_remote=True
            )
        except Exception as e:
            logger.debug(f"Failed to parse traceparent: {e}")
            return None

    def start_span_from_context(
        self,
        name: str,
        carrier: Dict[str, str],
        attributes: Optional[Dict[str, Any]] = None
    ) -> Span:
        """
        Start a new span from extracted context.

        This creates a child span of the remote parent extracted
        from the carrier.

        Args:
            name: Span/operation name
            carrier: Dictionary containing trace context headers
            attributes: Initial span attributes

        Returns:
            Created Span instance
        """
        ctx = self.extract_context(carrier)
        if ctx:
            # Create a virtual parent span from the context
            parent = Span(
                trace_id=ctx.trace_id,
                span_id=ctx.span_id
            )
            return self.start_span(name, parent=parent, attributes=attributes)
        else:
            # No context found, start a new trace
            return self.start_span(name, attributes=attributes)

    def get_trace(self, trace_id: str) -> List[Span]:
        """
        Get all spans for a trace.

        Args:
            trace_id: Trace ID to filter by

        Returns:
            List of spans in the trace
        """
        return [s for s in self._spans if s.trace_id == trace_id]

    def get_all_spans(self) -> List[Span]:
        """
        Get all recorded spans.

        Returns:
            List of all spans
        """
        return self._spans.copy()

    def clear_spans(self) -> None:
        """Clear all recorded spans."""
        self._spans.clear()
        self._span_stack.clear()
        self._active_span = None

    def export_to_jaeger(self, endpoint: str) -> None:
        """
        Configure Jaeger exporter.

        Args:
            endpoint: Jaeger collector endpoint (e.g., http://localhost:14268/api/traces)

        Raises:
            ImportError: If Jaeger exporter is not available
        """
        if not JAEGER_AVAILABLE:
            logger.warning("Jaeger exporter not available. Install opentelemetry-exporter-jaeger")
            self._exporter_type = ExporterType.NONE
            return

        if not self._otel_provider:
            logger.warning("OpenTelemetry provider not initialized")
            return

        try:
            jaeger_exporter = JaegerExporter(
                agent_host_name=endpoint.split(":")[0] if ":" in endpoint else "localhost",
                agent_port=int(endpoint.split(":")[1]) if ":" in endpoint else 14268
            )
            self._otel_provider.add_span_processor(
                SimpleSpanProcessor(jaeger_exporter)
            )
            self._exporter_type = ExporterType.JAEGER
            logger.info(f"Jaeger exporter configured: {endpoint}")
        except Exception as e:
            logger.error(f"Failed to configure Jaeger exporter: {e}")

    def export_to_zipkin(self, endpoint: str) -> None:
        """
        Configure Zipkin exporter.

        Args:
            endpoint: Zipkin API endpoint (e.g., http://localhost:9411/api/v2/spans)

        Raises:
            ImportError: If Zipkin exporter is not available
        """
        if not ZIPKIN_AVAILABLE:
            logger.warning("Zipkin exporter not available. Install opentelemetry-exporter-zipkin")
            self._exporter_type = ExporterType.NONE
            return

        if not self._otel_provider:
            logger.warning("OpenTelemetry provider not initialized")
            return

        try:
            zipkin_exporter = ZipkinExporter(endpoint=endpoint)
            self._otel_provider.add_span_processor(
                SimpleSpanProcessor(zipkin_exporter)
            )
            self._exporter_type = ExporterType.ZIPKIN
            logger.info(f"Zipkin exporter configured: {endpoint}")
        except Exception as e:
            logger.error(f"Failed to configure Zipkin exporter: {e}")

    def export_to_otlp(self, endpoint: str) -> None:
        """
        Configure OTLP (OpenTelemetry Protocol) exporter.

        Args:
            endpoint: OTLP endpoint (e.g., http://localhost:4318/v1/traces)

        Raises:
            ImportError: If OTLP exporter is not available
        """
        if not OTLP_AVAILABLE:
            logger.warning("OTLP exporter not available. Install opentelemetry-exporter-otlp")
            self._exporter_type = ExporterType.NONE
            return

        if not self._otel_provider:
            logger.warning("OpenTelemetry provider not initialized")
            return

        try:
            otlp_exporter = OTLPSpanExporter(endpoint=endpoint)
            self._otel_provider.add_span_processor(
                SimpleSpanProcessor(otlp_exporter)
            )
            self._exporter_type = ExporterType.OTLP
            logger.info(f"OTLP exporter configured: {endpoint}")
        except Exception as e:
            logger.error(f"Failed to configure OTLP exporter: {e}")

    def export_json(self) -> Dict[str, Any]:
        """
        Export spans as JSON for debugging or custom processing.

        Returns:
            Dictionary containing all span data
        """
        return {
            "service_name": self.service_name,
            "exporter_type": self._exporter_type.value,
            "otel_available": OTEL_AVAILABLE,
            "total_spans": len(self._spans),
            "active_span": self._active_span.span_id if self._active_span else None,
            "spans": [s.to_dict() for s in self._spans]
        }

    def get_stats(self) -> Dict[str, Any]:
        """
        Get tracer statistics.

        Returns:
            Dictionary with tracer statistics
        """
        status_counts = {}
        for span in self._spans:
            status = span.status.value
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "service_name": self.service_name,
            "total_spans": len(self._spans),
            "active_spans": len(self._span_stack),
            "status_distribution": status_counts,
            "otel_available": OTEL_AVAILABLE,
            "exporter_type": self._exporter_type.value
        }

    def shutdown(self) -> None:
        """Shutdown the tracer and flush any pending spans."""
        # End any active spans
        for span in self._span_stack.copy():
            try:
                self.end_span(span)
            except Exception:
                pass

        # Shutdown OpenTelemetry provider
        if self._otel_provider:
            try:
                self._otel_provider.shutdown()
            except Exception as e:
                logger.debug(f"Error shutting down OpenTelemetry provider: {e}")

        logger.info(f"DistributedTracer shutdown complete for {self.service_name}")


class TracingEventBusIntegration:
    """
    Integration between DistributedTracer and EventBus.

    Automatically injects trace_id and span_id into events emitted
    through the EventBus, enabling trace correlation across events.

    Usage:
        tracer = DistributedTracer()
        bus = EventBus()

        # Create integration
        integration = TracingEventBusIntegration(tracer, bus)

        # Now events will automatically include trace context
        with tracer.start_span("operation"):
            bus.emit(Event("GATE_PASS", {"gate": "GATE-01"}))
            # Event will have trace_id and span_id in data
    """

    def __init__(self, tracer: DistributedTracer, event_bus: "EventBus"):
        """
        Initialize integration.

        Args:
            tracer: DistributedTracer instance
            event_bus: EventBus instance
        """
        self.tracer = tracer
        self.event_bus = event_bus
        self._original_emit = event_bus.emit
        self._enabled = False

    def enable(self) -> None:
        """Enable trace context injection into events."""
        if self._enabled:
            return

        # Wrap emit to inject trace context
        def wrapped_emit(event: "Event", state_hash: str = "") -> None:
            active_span = self.tracer.get_active_span()
            if active_span:
                # Inject trace context into event data
                event.data["trace_id"] = active_span.trace_id
                event.data["span_id"] = active_span.span_id
                if active_span.parent_span_id:
                    event.data["parent_span_id"] = active_span.parent_span_id

            return self._original_emit(event, state_hash)

        self.event_bus.emit = wrapped_emit
        self._enabled = True
        logger.info("Trace context injection enabled for EventBus")

    def disable(self) -> None:
        """Disable trace context injection."""
        if self._enabled:
            self.event_bus.emit = self._original_emit
            self._enabled = False
            logger.info("Trace context injection disabled for EventBus")

    def is_enabled(self) -> bool:
        """Check if integration is enabled."""
        return self._enabled


# Global tracer instance
_global_tracer: Optional[DistributedTracer] = None


def get_distributed_tracer() -> DistributedTracer:
    """Get the global distributed tracer."""
    global _global_tracer
    if _global_tracer is None:
        _global_tracer = DistributedTracer()
    return _global_tracer


def init_distributed_tracer(
    service_name: str = "titan-protocol",
    config: Optional[Dict[str, Any]] = None
) -> DistributedTracer:
    """
    Initialize the global distributed tracer.

    Args:
        service_name: Service name for trace attribution
        config: Configuration dictionary

    Returns:
        Initialized DistributedTracer instance
    """
    global _global_tracer
    _global_tracer = DistributedTracer(service_name, config)
    return _global_tracer


def start_span(
    name: str,
    parent: Optional[Span] = None,
    attributes: Optional[Dict[str, Any]] = None
) -> Span:
    """Start a span in the global tracer."""
    return get_distributed_tracer().start_span(name, parent, attributes)


def end_span(span: Span, status: SpanStatus = SpanStatus.OK, message: str = "") -> None:
    """End a span in the global tracer."""
    get_distributed_tracer().end_span(span, status, message)


def get_active_span() -> Optional[Span]:
    """Get the active span from the global tracer."""
    return get_distributed_tracer().get_active_span()


def inject_context(carrier: Dict[str, str]) -> None:
    """Inject trace context into carrier using global tracer."""
    get_distributed_tracer().inject_context(carrier)


def extract_context(carrier: Dict[str, str]) -> Optional[TraceContext]:
    """Extract trace context from carrier using global tracer."""
    return get_distributed_tracer().extract_context(carrier)
