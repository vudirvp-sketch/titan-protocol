"""
Tests for ITEM-OBS-06: Distributed Tracing Integration

Comprehensive tests for the DistributedTracer, Span, and EventBus integration.

Author: TITAN FUSE Team
Version: 4.0.0
"""

import pytest
import time
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

from src.observability.distributed_tracing import (
    Span,
    SpanStatus,
    ExporterType,
    TraceContext,
    DistributedTracer,
    TracingEventBusIntegration,
    get_distributed_tracer,
    init_distributed_tracer,
    start_span,
    end_span,
    get_active_span,
    inject_context,
    extract_context,
    OTEL_AVAILABLE,
    JAEGER_AVAILABLE,
    ZIPKIN_AVAILABLE,
    OTLP_AVAILABLE,
)


class TestSpanStatus:
    """Tests for SpanStatus enum."""

    def test_status_values(self):
        """Test SpanStatus enum values."""
        assert SpanStatus.UNSET.value == "unset"
        assert SpanStatus.OK.value == "ok"
        assert SpanStatus.ERROR.value == "error"

    def test_status_count(self):
        """Test that we have expected number of statuses."""
        assert len(SpanStatus) == 3


class TestExporterType:
    """Tests for ExporterType enum."""

    def test_exporter_type_values(self):
        """Test ExporterType enum values."""
        assert ExporterType.JAEGER.value == "jaeger"
        assert ExporterType.ZIPKIN.value == "zipkin"
        assert ExporterType.OTLP.value == "otlp"
        assert ExporterType.NONE.value == "none"


class TestSpan:
    """Tests for Span dataclass."""

    def test_span_creation_minimal(self):
        """Test creating a span with minimal arguments."""
        span = Span(
            trace_id="0" * 32,
            span_id="0" * 16
        )
        assert span.trace_id == "0" * 32
        assert span.span_id == "0" * 16
        assert span.parent_span_id is None
        assert span.operation_name == ""
        assert span.start_time is not None
        assert span.end_time is None
        assert span.attributes == {}
        assert span.status == SpanStatus.UNSET

    def test_span_creation_full(self):
        """Test creating a span with all arguments."""
        start = datetime.utcnow()
        span = Span(
            trace_id="abc123" + "0" * 26,
            span_id="def456" + "0" * 10,
            parent_span_id="parent123",
            operation_name="test_operation",
            start_time=start,
            end_time=None,
            attributes={"key": "value"},
            status=SpanStatus.OK
        )
        assert span.trace_id == "abc123" + "0" * 26
        assert span.span_id == "def456" + "0" * 10
        assert span.parent_span_id == "parent123"
        assert span.operation_name == "test_operation"
        assert span.start_time == start
        assert span.attributes == {"key": "value"}
        assert span.status == SpanStatus.OK

    def test_span_set_attribute(self):
        """Test setting span attributes."""
        span = Span(trace_id="0" * 32, span_id="0" * 16)

        result = span.set_attribute("key1", "value1")

        assert span.attributes["key1"] == "value1"
        assert result is span  # Returns self for chaining

    def test_span_set_status(self):
        """Test setting span status."""
        span = Span(trace_id="0" * 32, span_id="0" * 16)

        result = span.set_status(SpanStatus.ERROR, "Something went wrong")

        assert span.status == SpanStatus.ERROR
        assert span.status_message == "Something went wrong"
        assert result is span

    def test_span_add_event(self):
        """Test adding events to span."""
        span = Span(trace_id="0" * 32, span_id="0" * 16)

        result = span.add_event("event_name", {"attr": "value"})

        assert len(span.events) == 1
        assert span.events[0]["name"] == "event_name"
        assert span.events[0]["attributes"] == {"attr": "value"}
        assert "timestamp" in span.events[0]
        assert result is span

    def test_span_end(self):
        """Test ending a span."""
        span = Span(trace_id="0" * 32, span_id="0" * 16)
        assert span.end_time is None

        span.end()

        assert span.end_time is not None

    def test_span_end_with_custom_time(self):
        """Test ending a span with custom end time."""
        span = Span(trace_id="0" * 32, span_id="0" * 16)
        custom_time = datetime.utcnow()

        span.end(end_time=custom_time)

        assert span.end_time == custom_time

    def test_span_get_duration_ms(self):
        """Test getting span duration."""
        span = Span(trace_id="0" * 32, span_id="0" * 16)

        # Not ended yet
        assert span.get_duration_ms() is None

        # End it
        span.end()
        duration = span.get_duration_ms()
        assert duration is not None
        assert duration >= 0

    def test_span_is_recording(self):
        """Test checking if span is recording."""
        span = Span(trace_id="0" * 32, span_id="0" * 16)

        assert span.is_recording() is True

        span.end()

        assert span.is_recording() is False

    def test_span_record_exception(self):
        """Test recording an exception."""
        span = Span(trace_id="0" * 32, span_id="0" * 16)

        try:
            raise ValueError("Test error")
        except ValueError as e:
            span.record_exception(e)

        assert span.status == SpanStatus.ERROR
        assert span.status_message == "Test error"
        assert len(span.events) == 1
        assert span.events[0]["name"] == "exception"
        assert span.events[0]["attributes"]["exception.type"] == "ValueError"
        assert span.events[0]["attributes"]["exception.message"] == "Test error"

    def test_span_to_dict(self):
        """Test converting span to dictionary."""
        span = Span(
            trace_id="abc" + "0" * 29,
            span_id="def" + "0" * 13,
            parent_span_id="parent",
            operation_name="test",
            attributes={"key": "value"},
            status=SpanStatus.OK
        )
        span.end()

        d = span.to_dict()

        assert d["trace_id"] == "abc" + "0" * 29
        assert d["span_id"] == "def" + "0" * 13
        assert d["parent_span_id"] == "parent"
        assert d["operation_name"] == "test"
        assert d["attributes"] == {"key": "value"}
        assert d["status"] == "ok"
        assert d["end_time"] is not None

    def test_span_to_json(self):
        """Test converting span to JSON."""
        span = Span(
            trace_id="0" * 32,
            span_id="0" * 16,
            operation_name="test"
        )

        json_str = span.to_json()

        assert '"trace_id"' in json_str
        assert '"operation_name": "test"' in json_str

    def test_span_to_w3c_traceparent(self):
        """Test generating W3C traceparent header."""
        span = Span(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7"
        )

        traceparent = span.to_w3c_traceparent()

        assert traceparent.startswith("00-")
        assert "4bf92f3577b34da6a3ce929d0e0e4736" in traceparent
        assert "00f067aa0ba902b7" in traceparent

    def test_span_from_w3c_traceparent_valid(self):
        """Test parsing valid W3C traceparent header."""
        traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

        span = Span.from_w3c_traceparent(traceparent)

        assert span is not None
        assert span.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert span.span_id == "00f067aa0ba902b7"

    def test_span_from_w3c_traceparent_invalid_version(self):
        """Test parsing W3C traceparent with invalid version."""
        traceparent = "01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

        span = Span.from_w3c_traceparent(traceparent)

        assert span is None

    def test_span_from_w3c_traceparent_invalid_format(self):
        """Test parsing malformed W3C traceparent."""
        span = Span.from_w3c_traceparent("invalid")
        assert span is None

        span = Span.from_w3c_traceparent("00-trace-span")
        assert span is None


class TestTraceContext:
    """Tests for TraceContext dataclass."""

    def test_trace_context_creation(self):
        """Test creating a trace context."""
        ctx = TraceContext(
            trace_id="0" * 32,
            span_id="0" * 16,
            trace_flags=1,
            trace_state={"vendor": "value"},
            is_remote=True
        )
        assert ctx.trace_id == "0" * 32
        assert ctx.span_id == "0" * 16
        assert ctx.trace_flags == 1
        assert ctx.trace_state == {"vendor": "value"}
        assert ctx.is_remote is True

    def test_trace_context_to_dict(self):
        """Test converting trace context to dictionary."""
        ctx = TraceContext(
            trace_id="abc" + "0" * 29,
            span_id="def" + "0" * 13
        )

        d = ctx.to_dict()

        assert d["trace_id"] == "abc" + "0" * 29
        assert d["span_id"] == "def" + "0" * 13
        assert d["trace_flags"] == 1
        assert d["is_remote"] is False

    def test_trace_context_to_w3c_headers(self):
        """Test converting trace context to W3C headers."""
        ctx = TraceContext(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
            trace_flags=1,
            trace_state={"rojo": "span=123", "congo": "t=1397"}
        )

        headers = ctx.to_w3c_headers()

        assert "traceparent" in headers
        assert headers["traceparent"] == "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        assert "tracestate" in headers
        assert "rojo=span=123" in headers["tracestate"]
        assert "congo=t=1397" in headers["tracestate"]

    def test_trace_context_to_w3c_headers_no_state(self):
        """Test W3C headers without trace state."""
        ctx = TraceContext(
            trace_id="0" * 32,
            span_id="0" * 16
        )

        headers = ctx.to_w3c_headers()

        assert "traceparent" in headers
        assert "tracestate" not in headers


class TestDistributedTracer:
    """Tests for DistributedTracer class."""

    def test_tracer_creation(self):
        """Test creating a tracer."""
        tracer = DistributedTracer(service_name="test-service")

        assert tracer.service_name == "test-service"
        assert tracer._spans == []
        assert tracer._active_span is None

    def test_start_span(self):
        """Test starting a span."""
        tracer = DistributedTracer()

        span = tracer.start_span("test_operation")

        assert span is not None
        assert span.operation_name == "test_operation"
        assert span.trace_id is not None
        assert span.span_id is not None
        assert span.parent_span_id is None
        assert tracer._active_span == span
        assert span in tracer._spans

    def test_start_span_with_attributes(self):
        """Test starting a span with attributes."""
        tracer = DistributedTracer()

        span = tracer.start_span("test_operation", attributes={"key": "value"})

        assert span.attributes == {"key": "value"}

    def test_start_child_span(self):
        """Test starting a child span."""
        tracer = DistributedTracer()

        parent = tracer.start_span("parent_operation")
        child = tracer.start_span("child_operation", parent=parent)

        assert child.parent_span_id == parent.span_id
        assert child.trace_id == parent.trace_id

    def test_end_span(self):
        """Test ending a span."""
        tracer = DistributedTracer()

        span = tracer.start_span("test_operation")
        assert span.end_time is None

        tracer.end_span(span)

        assert span.end_time is not None
        assert span.status == SpanStatus.OK

    def test_end_span_with_error(self):
        """Test ending a span with error status."""
        tracer = DistributedTracer()

        span = tracer.start_span("test_operation")
        tracer.end_span(span, status=SpanStatus.ERROR, message="Failed")

        assert span.status == SpanStatus.ERROR
        assert span.status_message == "Failed"

    def test_span_context_manager(self):
        """Test using span as context manager."""
        tracer = DistributedTracer()

        with tracer.span("test_operation") as span:
            assert span.is_recording()
            span.set_attribute("key", "value")

        assert not span.is_recording()
        assert span.status == SpanStatus.OK

    def test_span_context_manager_with_exception(self):
        """Test span context manager with exception."""
        tracer = DistributedTracer()

        with pytest.raises(ValueError):
            with tracer.span("test_operation") as span:
                raise ValueError("Test error")

        assert span.status == SpanStatus.ERROR
        assert span.status_message == "Test error"

    def test_get_active_span(self):
        """Test getting active span."""
        tracer = DistributedTracer()

        assert tracer.get_active_span() is None

        span = tracer.start_span("test_operation")
        assert tracer.get_active_span() == span

        tracer.end_span(span)
        assert tracer.get_active_span() is None

    def test_nested_spans(self):
        """Test nested span tracking."""
        tracer = DistributedTracer()

        parent = tracer.start_span("parent")
        assert tracer.get_active_span() == parent

        child = tracer.start_span("child")
        assert tracer.get_active_span() == child
        assert child.parent_span_id == parent.span_id

        grandchild = tracer.start_span("grandchild")
        assert tracer.get_active_span() == grandchild
        assert grandchild.parent_span_id == child.span_id

        tracer.end_span(grandchild)
        assert tracer.get_active_span() == child

        tracer.end_span(child)
        assert tracer.get_active_span() == parent

        tracer.end_span(parent)
        assert tracer.get_active_span() is None

    def test_inject_context_no_active_span(self):
        """Test inject context with no active span."""
        tracer = DistributedTracer()
        carrier = {}

        tracer.inject_context(carrier)

        assert "traceparent" not in carrier

    def test_inject_context_with_active_span(self):
        """Test inject context with active span."""
        tracer = DistributedTracer()

        span = tracer.start_span("test_operation")
        carrier = {}
        tracer.inject_context(carrier)

        assert "traceparent" in carrier
        assert span.trace_id in carrier["traceparent"]
        assert span.span_id in carrier["traceparent"]

    def test_extract_context_valid(self):
        """Test extracting valid context."""
        tracer = DistributedTracer()
        carrier = {
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        }

        ctx = tracer.extract_context(carrier)

        assert ctx is not None
        assert ctx.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert ctx.span_id == "00f067aa0ba902b7"
        assert ctx.is_remote is True

    def test_extract_context_with_tracestate(self):
        """Test extracting context with tracestate."""
        tracer = DistributedTracer()
        carrier = {
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            "tracestate": "rojo=span=123,congo=t=1397"
        }

        ctx = tracer.extract_context(carrier)

        assert ctx is not None
        assert ctx.trace_state == {"rojo": "span=123", "congo": "t=1397"}

    def test_extract_context_no_traceparent(self):
        """Test extracting context with no traceparent."""
        tracer = DistributedTracer()
        carrier = {}

        ctx = tracer.extract_context(carrier)

        assert ctx is None

    def test_start_span_from_context(self):
        """Test starting span from extracted context."""
        tracer = DistributedTracer()
        carrier = {
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        }

        span = tracer.start_span_from_context("child_operation", carrier)

        assert span.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert span.parent_span_id == "00f067aa0ba902b7"

    def test_start_span_from_context_no_context(self):
        """Test starting span when no context in carrier."""
        tracer = DistributedTracer()
        carrier = {}

        span = tracer.start_span_from_context("new_operation", carrier)

        assert span is not None
        assert span.trace_id is not None
        assert span.parent_span_id is None

    def test_get_trace(self):
        """Test getting all spans for a trace."""
        tracer = DistributedTracer()

        parent = tracer.start_span("parent")
        child = tracer.start_span("child", parent=parent)

        # End current spans to start a new trace
        tracer.end_span(child)
        tracer.end_span(parent)

        # Start a completely new trace (no active span)
        other = tracer.start_span("other")  # Different trace

        spans = tracer.get_trace(parent.trace_id)

        assert len(spans) == 2
        assert parent in spans
        assert child in spans
        assert other not in spans

    def test_get_all_spans(self):
        """Test getting all spans."""
        tracer = DistributedTracer()

        span1 = tracer.start_span("op1")
        span2 = tracer.start_span("op2")

        spans = tracer.get_all_spans()

        assert len(spans) == 2
        assert span1 in spans
        assert span2 in spans

    def test_clear_spans(self):
        """Test clearing all spans."""
        tracer = DistributedTracer()

        tracer.start_span("op1")
        tracer.start_span("op2")

        assert len(tracer.get_all_spans()) == 2

        tracer.clear_spans()

        assert len(tracer.get_all_spans()) == 0
        assert tracer.get_active_span() is None

    def test_export_json(self):
        """Test exporting spans as JSON."""
        tracer = DistributedTracer()

        tracer.start_span("op1")
        tracer.start_span("op2")

        data = tracer.export_json()

        assert data["service_name"] == "titan-protocol"
        assert data["total_spans"] == 2
        assert len(data["spans"]) == 2

    def test_get_stats(self):
        """Test getting tracer statistics."""
        tracer = DistributedTracer()

        span1 = tracer.start_span("op1")
        span2 = tracer.start_span("op2")
        tracer.end_span(span1, SpanStatus.OK)
        tracer.end_span(span2, SpanStatus.ERROR)

        stats = tracer.get_stats()

        assert stats["service_name"] == "titan-protocol"
        assert stats["total_spans"] == 2
        assert stats["active_spans"] == 0
        assert stats["status_distribution"]["ok"] == 1
        assert stats["status_distribution"]["error"] == 1

    def test_shutdown(self):
        """Test tracer shutdown."""
        tracer = DistributedTracer()

        tracer.start_span("op1")
        tracer.start_span("op2")

        # Should not raise
        tracer.shutdown()

        # Spans should be ended
        assert len(tracer._span_stack) == 0


class TestDistributedTracerExporters:
    """Tests for exporter configuration."""

    def test_export_to_jaeger_not_available(self):
        """Test Jaeger export when not available."""
        with patch('src.observability.distributed_tracing.JAEGER_AVAILABLE', False):
            tracer = DistributedTracer()
            tracer.export_to_jaeger("http://localhost:14268/api/traces")
            assert tracer._exporter_type == ExporterType.NONE

    def test_export_to_zipkin_not_available(self):
        """Test Zipkin export when not available."""
        with patch('src.observability.distributed_tracing.ZIPKIN_AVAILABLE', False):
            tracer = DistributedTracer()
            tracer.export_to_zipkin("http://localhost:9411/api/v2/spans")
            assert tracer._exporter_type == ExporterType.NONE

    def test_export_to_otlp_not_available(self):
        """Test OTLP export when not available."""
        with patch('src.observability.distributed_tracing.OTLP_AVAILABLE', False):
            tracer = DistributedTracer()
            tracer.export_to_otlp("http://localhost:4318/v1/traces")
            assert tracer._exporter_type == ExporterType.NONE


class TestTracingEventBusIntegration:
    """Tests for EventBus integration."""

    def test_integration_creation(self):
        """Test creating integration."""
        tracer = DistributedTracer()
        bus = Mock()

        integration = TracingEventBusIntegration(tracer, bus)

        assert integration.tracer == tracer
        assert integration.event_bus == bus
        assert not integration.is_enabled()

    def test_integration_enable(self):
        """Test enabling integration."""
        tracer = DistributedTracer()
        bus = Mock()
        bus.emit = Mock()

        integration = TracingEventBusIntegration(tracer, bus)
        integration.enable()

        assert integration.is_enabled()

    def test_integration_disable(self):
        """Test disabling integration."""
        tracer = DistributedTracer()
        bus = Mock()
        original_emit = Mock()
        bus.emit = original_emit

        integration = TracingEventBusIntegration(tracer, bus)
        integration.enable()
        integration.disable()

        assert not integration.is_enabled()
        assert bus.emit == original_emit

    def test_integration_injects_trace_context(self):
        """Test that trace context is injected into events."""
        tracer = DistributedTracer()
        bus = Mock()

        # Track the emit calls
        emitted_events = []

        def mock_emit(event, state_hash=""):
            emitted_events.append(event)

        bus.emit = mock_emit

        integration = TracingEventBusIntegration(tracer, bus)
        integration.enable()

        # Create a span and emit an event
        span = tracer.start_span("test_operation")

        event = Mock()
        event.data = {}
        event.severity = Mock()
        event.event_type = "TEST_EVENT"

        bus.emit(event)

        # Check that trace context was injected
        assert "trace_id" in event.data
        assert event.data["trace_id"] == span.trace_id
        assert "span_id" in event.data
        assert event.data["span_id"] == span.span_id

    def test_integration_injects_parent_span_id(self):
        """Test that parent span ID is injected when available."""
        tracer = DistributedTracer()

        parent = tracer.start_span("parent")
        child = tracer.start_span("child", parent=parent)

        bus = Mock()
        emitted_events = []

        def mock_emit(event, state_hash=""):
            emitted_events.append(event)

        bus.emit = mock_emit

        integration = TracingEventBusIntegration(tracer, bus)
        integration.enable()

        event = Mock()
        event.data = {}
        event.severity = Mock()
        event.event_type = "TEST_EVENT"

        bus.emit(event)

        assert "parent_span_id" in event.data
        assert event.data["parent_span_id"] == child.parent_span_id

    def test_integration_no_span_no_injection(self):
        """Test that nothing is injected when no active span."""
        tracer = DistributedTracer()
        bus = Mock()

        def mock_emit(event, state_hash=""):
            pass

        bus.emit = mock_emit

        integration = TracingEventBusIntegration(tracer, bus)
        integration.enable()

        event = Mock()
        event.data = {}
        event.severity = Mock()
        event.event_type = "TEST_EVENT"

        bus.emit(event)

        # No trace context should be injected
        assert "trace_id" not in event.data
        assert "span_id" not in event.data


class TestGlobalFunctions:
    """Tests for global convenience functions."""

    def test_get_distributed_tracer_singleton(self):
        """Test that get_distributed_tracer returns singleton."""
        import src.observability.distributed_tracing as dt
        dt._global_tracer = None  # Reset

        tracer1 = get_distributed_tracer()
        tracer2 = get_distributed_tracer()

        assert tracer1 is tracer2

    def test_init_distributed_tracer(self):
        """Test initializing global tracer."""
        import src.observability.distributed_tracing as dt
        dt._global_tracer = None  # Reset

        tracer = init_distributed_tracer(service_name="custom-service")

        assert tracer.service_name == "custom-service"
        assert get_distributed_tracer() is tracer

    def test_start_span_global(self):
        """Test start_span with global tracer."""
        import src.observability.distributed_tracing as dt
        dt._global_tracer = None  # Reset

        span = start_span("test_operation")

        assert span.operation_name == "test_operation"

    def test_end_span_global(self):
        """Test end_span with global tracer."""
        import src.observability.distributed_tracing as dt
        dt._global_tracer = None  # Reset

        span = start_span("test_operation")
        end_span(span)

        assert not span.is_recording()

    def test_get_active_span_global(self):
        """Test get_active_span with global tracer."""
        import src.observability.distributed_tracing as dt
        dt._global_tracer = None  # Reset

        assert get_active_span() is None

        span = start_span("test_operation")
        assert get_active_span() == span

        end_span(span)
        assert get_active_span() is None

    def test_inject_context_global(self):
        """Test inject_context with global tracer."""
        import src.observability.distributed_tracing as dt
        dt._global_tracer = None  # Reset

        carrier = {}
        inject_context(carrier)

        # No active span, so nothing injected
        assert "traceparent" not in carrier

        span = start_span("test_operation")
        inject_context(carrier)

        assert "traceparent" in carrier

    def test_extract_context_global(self):
        """Test extract_context with global tracer."""
        import src.observability.distributed_tracing as dt
        dt._global_tracer = None  # Reset

        carrier = {
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        }

        ctx = extract_context(carrier)

        assert ctx is not None
        assert ctx.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"


class TestIntegrationScenarios:
    """Integration tests for distributed tracing."""

    def test_full_tracing_workflow(self):
        """Test complete distributed tracing workflow."""
        tracer = DistributedTracer(service_name="test-service")

        # Start a parent span
        with tracer.span("http_request", attributes={"http.method": "GET"}) as parent:
            parent.set_attribute("http.url", "/api/users")

            # Start a child span for database call
            with tracer.span("db_query", attributes={"db.system": "postgresql"}) as child:
                child.set_attribute("db.statement", "SELECT * FROM users")

            # Inject context for outgoing call
            carrier = {}
            tracer.inject_context(carrier)
            assert "traceparent" in carrier

        # Verify spans
        spans = tracer.get_all_spans()
        assert len(spans) == 2

        # Both should have same trace_id
        assert spans[0].trace_id == spans[1].trace_id

        # One should be parent of other
        parent_spans = [s for s in spans if s.parent_span_id is None]
        child_spans = [s for s in spans if s.parent_span_id is not None]
        assert len(parent_spans) == 1
        assert len(child_spans) == 1
        assert child_spans[0].parent_span_id == parent_spans[0].span_id

    def test_cross_service_trace_propagation(self):
        """Test trace propagation across service boundaries."""
        # Service A
        tracer_a = DistributedTracer(service_name="service-a")

        with tracer_a.span("operation_a") as span_a:
            carrier = {}
            tracer_a.inject_context(carrier)

            # Simulate sending carrier to Service B
            tracer_b = DistributedTracer(service_name="service-b")

            span_b = tracer_b.start_span_from_context("operation_b", carrier)

            assert span_b.trace_id == span_a.trace_id
            assert span_b.parent_span_id == span_a.span_id

            tracer_b.end_span(span_b)

    def test_error_recording(self):
        """Test error recording in spans."""
        tracer = DistributedTracer()

        with pytest.raises(ValueError):
            with tracer.span("failing_operation") as span:
                span.set_attribute("attempt", 1)
                raise ValueError("Something went wrong")

        spans = tracer.get_all_spans()
        assert len(spans) == 1
        assert spans[0].status == SpanStatus.ERROR
        assert "Something went wrong" in spans[0].status_message

    def test_multiple_concurrent_traces(self):
        """Test handling multiple concurrent traces."""
        tracer = DistributedTracer()

        # Start trace 1
        trace1_parent = tracer.start_span("trace1_parent")

        # Start trace 2 (different trace)
        trace2_parent = tracer.start_span("trace2_parent")
        trace2_parent._trace_id = "different_trace_id" * 2  # Force different trace ID

        # Start children
        trace1_child = tracer.start_span("trace1_child", parent=trace1_parent)
        trace2_child = tracer.start_span("trace2_child", parent=trace2_parent)

        # Verify isolation
        assert trace1_parent.trace_id == trace1_child.trace_id
        assert trace2_parent.trace_id == trace2_child.trace_id

    def test_span_events_and_attributes(self):
        """Test comprehensive span with events and attributes."""
        tracer = DistributedTracer()

        with tracer.span("complex_operation") as span:
            span.set_attribute("user.id", "123")
            span.set_attribute("operation.type", "write")

            span.add_event("cache_hit", {"key": "user:123"})
            span.add_event("validation_passed")

            # Simulate some work
            time.sleep(0.01)

        spans = tracer.get_all_spans()
        assert len(spans) == 1

        span_data = spans[0].to_dict()
        assert span_data["attributes"]["user.id"] == "123"
        assert len(span_data["events"]) == 2
        assert span_data["duration_ms"] > 0


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_carrier_extract(self):
        """Test extracting from empty carrier."""
        tracer = DistributedTracer()
        ctx = tracer.extract_context({})
        assert ctx is None

    def test_malformed_traceparent(self):
        """Test extracting malformed traceparent."""
        tracer = DistributedTracer()

        for malformed in [
            {"traceparent": ""},
            {"traceparent": "invalid"},
            {"traceparent": "00-short-short-01"},
            {"traceparent": "02-trace-span-01"},  # Invalid version
        ]:
            ctx = tracer.extract_context(malformed)
            assert ctx is None, f"Should be None for {malformed}"

    def test_case_insensitive_headers(self):
        """Test case-insensitive header extraction."""
        tracer = DistributedTracer()

        # Test with different case variations
        for carrier in [
            {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"},
            {"Traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"},
            {"TRACEPARENT": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"},
        ]:
            ctx = tracer.extract_context(carrier)
            assert ctx is not None

    def test_span_id_uniqueness(self):
        """Test that span IDs are unique."""
        tracer = DistributedTracer()

        span_ids = set()
        for _ in range(100):
            span = tracer.start_span("test")
            span_ids.add(span.span_id)
            tracer.end_span(span)

        assert len(span_ids) == 100  # All unique

    def test_trace_id_consistency_in_span_tree(self):
        """Test that all spans in a tree share the same trace ID."""
        tracer = DistributedTracer()

        root = tracer.start_span("root")
        child1 = tracer.start_span("child1", parent=root)
        grandchild1 = tracer.start_span("grandchild1", parent=child1)
        child2 = tracer.start_span("child2", parent=root)

        trace_id = root.trace_id
        assert child1.trace_id == trace_id
        assert grandchild1.trace_id == trace_id
        assert child2.trace_id == trace_id


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=src/observability/distributed_tracing", "--cov-report=term-missing"])
