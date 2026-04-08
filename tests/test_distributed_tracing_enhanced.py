"""
Tests for ITEM-OBS-001: OpenTelemetry Traces Enhancement

Comprehensive tests for session lifecycle span hierarchy, gate transitions,
and batch execution spans.

Author: TITAN FUSE Team
Version: 5.0.0
"""

import pytest
import time
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

from src.observability.distributed_tracing import (
    Span,
    SpanStatus,
    SpanKind,
    ExporterType,
    TraceContext,
    DistributedTracer,
    TracingEventBusIntegration,
    SPAN_HIERARCHY,
    get_distributed_tracer,
    init_distributed_tracer,
    start_span,
    end_span,
    get_active_span,
    inject_context,
    extract_context,
    # ITEM-OBS-001: New functions
    get_tracer,
    start_session_span,
    start_phase_span,
    start_gate_span,
    start_batch_span,
    record_event,
    record_exception,
    OTEL_AVAILABLE,
)


class TestSpanKind:
    """Tests for SpanKind enum (ITEM-OBS-001)."""

    def test_span_kind_values(self):
        """Test SpanKind enum values."""
        assert SpanKind.SESSION.value == "session"
        assert SpanKind.INIT.value == "init"
        assert SpanKind.DISCOVERY.value == "discovery"
        assert SpanKind.ANALYSIS.value == "analysis"
        assert SpanKind.PLANNING.value == "planning"
        assert SpanKind.EXECUTION.value == "execution"
        assert SpanKind.DELIVERY.value == "delivery"
        assert SpanKind.TOOL_SCAN.value == "tool_scan"
        assert SpanKind.DAG_BUILD.value == "dag_build"
        assert SpanKind.GATE.value == "gate"
        assert SpanKind.BATCH.value == "batch"
        assert SpanKind.EVENT.value == "event"

    def test_span_kind_count(self):
        """Test that we have expected number of span kinds."""
        assert len(SpanKind) == 12


class TestSpanHierarchy:
    """Tests for SPAN_HIERARCHY definition (ITEM-OBS-001)."""

    def test_session_has_no_parent(self):
        """Test that SESSION is a root span with no parent."""
        assert SPAN_HIERARCHY[SpanKind.SESSION]["parent"] is None

    def test_session_children(self):
        """Test that SESSION has all phase children."""
        children = SPAN_HIERARCHY[SpanKind.SESSION]["children"]
        assert SpanKind.INIT in children
        assert SpanKind.DISCOVERY in children
        assert SpanKind.ANALYSIS in children
        assert SpanKind.PLANNING in children
        assert SpanKind.EXECUTION in children
        assert SpanKind.DELIVERY in children

    def test_discovery_has_tool_scan_child(self):
        """Test that DISCOVERY has TOOL_SCAN child."""
        assert SpanKind.TOOL_SCAN in SPAN_HIERARCHY[SpanKind.DISCOVERY]["children"]
        assert SPAN_HIERARCHY[SpanKind.TOOL_SCAN]["parent"] == SpanKind.DISCOVERY

    def test_planning_has_dag_build_child(self):
        """Test that PLANNING has DAG_BUILD child."""
        assert SpanKind.DAG_BUILD in SPAN_HIERARCHY[SpanKind.PLANNING]["children"]
        assert SPAN_HIERARCHY[SpanKind.DAG_BUILD]["parent"] == SpanKind.PLANNING

    def test_execution_has_gate_child(self):
        """Test that EXECUTION has GATE child."""
        assert SpanKind.GATE in SPAN_HIERARCHY[SpanKind.EXECUTION]["children"]
        assert SPAN_HIERARCHY[SpanKind.GATE]["parent"] == SpanKind.EXECUTION

    def test_gate_has_batch_child(self):
        """Test that GATE has BATCH child."""
        assert SpanKind.BATCH in SPAN_HIERARCHY[SpanKind.GATE]["children"]
        assert SPAN_HIERARCHY[SpanKind.BATCH]["parent"] == SpanKind.GATE


class TestSpanWithKind:
    """Tests for Span with span_kind attribute (ITEM-OBS-001)."""

    def test_span_with_kind(self):
        """Test creating a span with span_kind."""
        span = Span(
            trace_id="0" * 32,
            span_id="0" * 16,
            span_kind=SpanKind.SESSION
        )
        assert span.span_kind == SpanKind.SESSION

    def test_span_to_dict_includes_kind(self):
        """Test that to_dict includes span_kind."""
        span = Span(
            trace_id="0" * 32,
            span_id="0" * 16,
            span_kind=SpanKind.GATE
        )
        span.end()

        d = span.to_dict()
        assert "span_kind" in d
        assert d["span_kind"] == "gate"

    def test_span_to_dict_none_kind(self):
        """Test that to_dict handles None span_kind."""
        span = Span(
            trace_id="0" * 32,
            span_id="0" * 16
        )
        span.end()

        d = span.to_dict()
        assert d["span_kind"] is None


class TestSessionLifecycleMethods:
    """Tests for session lifecycle span methods (ITEM-OBS-001)."""

    def test_start_session_span(self):
        """Test starting a session span."""
        tracer = DistributedTracer()

        span = tracer.start_session_span("test-session-123")

        assert span is not None
        assert span.operation_name == "session.test-session-123"
        assert span.span_kind == SpanKind.SESSION
        assert span.parent_span_id is None  # Root span
        assert span.attributes["session.id"] == "test-session-123"
        assert span.attributes["titan.version"] == "5.0.0"
        assert tracer.get_span_by_kind(SpanKind.SESSION) == span

    def test_start_session_span_with_attributes(self):
        """Test starting a session span with custom attributes."""
        tracer = DistributedTracer()

        span = tracer.start_session_span(
            "test-session-456",
            attributes={"custom.attr": "value"}
        )

        assert span.attributes["custom.attr"] == "value"

    def test_start_phase_span(self):
        """Test starting a phase span."""
        tracer = DistributedTracer()

        session_span = tracer.start_session_span("test-session")
        phase_span = tracer.start_phase_span(SpanKind.INIT)

        assert phase_span is not None
        assert phase_span.span_kind == SpanKind.INIT
        assert phase_span.parent_span_id == session_span.span_id
        assert phase_span.attributes["phase.type"] == "init"

    def test_start_phase_span_all_phases(self):
        """Test starting all phase types."""
        tracer = DistributedTracer()

        tracer.start_session_span("test-session")

        phases = [
            SpanKind.INIT, SpanKind.DISCOVERY, SpanKind.ANALYSIS,
            SpanKind.PLANNING, SpanKind.EXECUTION, SpanKind.DELIVERY
        ]

        for phase in phases:
            span = tracer.start_phase_span(phase)
            assert span.span_kind == phase
            assert span.attributes["phase.type"] == phase.value

    def test_start_phase_span_invalid(self):
        """Test that invalid phase raises error."""
        tracer = DistributedTracer()

        with pytest.raises(ValueError, match="Invalid phase type"):
            tracer.start_phase_span(SpanKind.GATE)

    def test_start_gate_span(self):
        """Test starting a gate span."""
        tracer = DistributedTracer()

        tracer.start_session_span("test-session")
        tracer.start_phase_span(SpanKind.EXECUTION)
        gate_span = tracer.start_gate_span("GATE-01", gate_type="validation")

        assert gate_span is not None
        assert gate_span.span_kind == SpanKind.GATE
        assert gate_span.attributes["gate.id"] == "GATE-01"
        assert gate_span.attributes["gate.type"] == "validation"
        assert tracer.get_gate_span("GATE-01") == gate_span

    def test_start_gate_span_without_execution(self):
        """Test starting a gate span without execution phase (fallback to session)."""
        tracer = DistributedTracer()

        session_span = tracer.start_session_span("test-session")
        gate_span = tracer.start_gate_span("GATE-02")

        # Should still work, with session as parent
        assert gate_span.parent_span_id == session_span.span_id

    def test_start_batch_span(self):
        """Test starting a batch span."""
        tracer = DistributedTracer()

        tracer.start_session_span("test-session")
        tracer.start_phase_span(SpanKind.EXECUTION)
        gate_span = tracer.start_gate_span("GATE-01")
        batch_span = tracer.start_batch_span("batch-001", gate_id="GATE-01")

        assert batch_span is not None
        assert batch_span.span_kind == SpanKind.BATCH
        assert batch_span.attributes["batch.id"] == "batch-001"
        assert batch_span.attributes["gate.id"] == "GATE-01"
        assert batch_span.parent_span_id == gate_span.span_id
        assert tracer.get_batch_span("batch-001") == batch_span

    def test_start_batch_span_without_gate(self):
        """Test starting a batch span without specifying gate."""
        tracer = DistributedTracer()

        tracer.start_session_span("test-session")
        tracer.start_phase_span(SpanKind.EXECUTION)
        batch_span = tracer.start_batch_span("batch-002")

        assert batch_span is not None
        assert batch_span.span_kind == SpanKind.BATCH

    def test_start_tool_scan_span(self):
        """Test starting a tool scan span."""
        tracer = DistributedTracer()

        tracer.start_session_span("test-session")
        discovery_span = tracer.start_phase_span(SpanKind.DISCOVERY)
        tool_span = tracer.start_tool_scan_span("file_scanner")

        assert tool_span is not None
        assert tool_span.span_kind == SpanKind.TOOL_SCAN
        assert tool_span.attributes["tool.name"] == "file_scanner"
        assert tool_span.parent_span_id == discovery_span.span_id

    def test_start_dag_build_span(self):
        """Test starting a DAG build span."""
        tracer = DistributedTracer()

        tracer.start_session_span("test-session")
        planning_span = tracer.start_phase_span(SpanKind.PLANNING)
        dag_span = tracer.start_dag_build_span("main_dag")

        assert dag_span is not None
        assert dag_span.span_kind == SpanKind.DAG_BUILD
        assert dag_span.attributes["dag.name"] == "main_dag"
        assert dag_span.parent_span_id == planning_span.span_id


class TestSpanHierarchyValidation:
    """Tests for span hierarchy validation (ITEM-OBS-001)."""

    def test_validate_session_hierarchy(self):
        """Test validating session span hierarchy."""
        tracer = DistributedTracer()

        session_span = tracer.start_session_span("test-session")

        assert tracer.validate_span_hierarchy(session_span) is True

    def test_validate_phase_hierarchy(self):
        """Test validating phase span hierarchy."""
        tracer = DistributedTracer()

        tracer.start_session_span("test-session")
        phase_span = tracer.start_phase_span(SpanKind.INIT)

        assert tracer.validate_span_hierarchy(phase_span) is True

    def test_validate_gate_hierarchy(self):
        """Test validating gate span hierarchy."""
        tracer = DistributedTracer()

        tracer.start_session_span("test-session")
        tracer.start_phase_span(SpanKind.EXECUTION)
        gate_span = tracer.start_gate_span("GATE-01")

        assert tracer.validate_span_hierarchy(gate_span) is True

    def test_validate_batch_hierarchy(self):
        """Test validating batch span hierarchy."""
        tracer = DistributedTracer()

        tracer.start_session_span("test-session")
        tracer.start_phase_span(SpanKind.EXECUTION)
        tracer.start_gate_span("GATE-01")
        batch_span = tracer.start_batch_span("batch-001", gate_id="GATE-01")

        assert tracer.validate_span_hierarchy(batch_span) is True


class TestHierarchyStats:
    """Tests for hierarchy statistics (ITEM-OBS-001)."""

    def test_get_hierarchy_stats_empty(self):
        """Test hierarchy stats with no spans."""
        tracer = DistributedTracer()

        stats = tracer.get_hierarchy_stats()

        assert stats["session_started"] is False
        assert stats["phases_started"] == []
        assert stats["gates_count"] == 0
        assert stats["batches_count"] == 0

    def test_get_hierarchy_stats_with_session(self):
        """Test hierarchy stats after starting session."""
        tracer = DistributedTracer()

        tracer.start_session_span("test-session")

        stats = tracer.get_hierarchy_stats()

        assert stats["session_started"] is True
        assert stats["phases_started"] == []

    def test_get_hierarchy_stats_full(self):
        """Test hierarchy stats with full hierarchy."""
        tracer = DistributedTracer()

        tracer.start_session_span("test-session")
        tracer.start_phase_span(SpanKind.INIT)
        tracer.start_phase_span(SpanKind.EXECUTION)
        tracer.start_gate_span("GATE-01")
        tracer.start_batch_span("batch-001", gate_id="GATE-01")

        stats = tracer.get_hierarchy_stats()

        assert stats["session_started"] is True
        assert "init" in stats["phases_started"]
        assert "execution" in stats["phases_started"]
        assert stats["gates_count"] == 1
        assert stats["batches_count"] == 1


class TestGlobalFunctions:
    """Tests for global convenience functions (ITEM-OBS-001)."""

    def test_get_tracer_alias(self):
        """Test that get_tracer is an alias for get_distributed_tracer."""
        import src.observability.distributed_tracing as dt
        dt._global_tracer = None  # Reset

        assert get_tracer() is get_distributed_tracer()

    def test_start_session_span_global(self):
        """Test start_session_span with global tracer."""
        import src.observability.distributed_tracing as dt
        dt._global_tracer = None  # Reset

        span = start_session_span("global-session")

        assert span.operation_name == "session.global-session"
        assert span.span_kind == SpanKind.SESSION

    def test_start_phase_span_global(self):
        """Test start_phase_span with global tracer."""
        import src.observability.distributed_tracing as dt
        dt._global_tracer = None  # Reset

        start_session_span("global-session")
        phase_span = start_phase_span(SpanKind.PLANNING)

        assert phase_span.span_kind == SpanKind.PLANNING

    def test_start_gate_span_global(self):
        """Test start_gate_span with global tracer."""
        import src.observability.distributed_tracing as dt
        dt._global_tracer = None  # Reset

        start_session_span("global-session")
        start_phase_span(SpanKind.EXECUTION)
        gate_span = start_gate_span("GATE-01", gate_type="security")

        assert gate_span.span_kind == SpanKind.GATE
        assert gate_span.attributes["gate.type"] == "security"

    def test_start_batch_span_global(self):
        """Test start_batch_span with global tracer."""
        import src.observability.distributed_tracing as dt
        dt._global_tracer = None  # Reset

        start_session_span("global-session")
        start_phase_span(SpanKind.EXECUTION)
        start_gate_span("GATE-01")
        batch_span = start_batch_span("batch-001", gate_id="GATE-01")

        assert batch_span.span_kind == SpanKind.BATCH

    def test_record_event_global(self):
        """Test record_event with global tracer."""
        import src.observability.distributed_tracing as dt
        dt._global_tracer = None  # Reset

        span = start_session_span("global-session")
        record_event("custom_event", {"key": "value"})

        assert len(span.events) == 1
        assert span.events[0]["name"] == "custom_event"

    def test_record_exception_global(self):
        """Test record_exception with global tracer."""
        import src.observability.distributed_tracing as dt
        dt._global_tracer = None  # Reset

        span = start_session_span("global-session")

        try:
            raise ValueError("Test error")
        except ValueError as e:
            record_exception(e)

        assert span.status == SpanStatus.ERROR
        assert len(span.events) == 1
        assert span.events[0]["name"] == "exception"


class TestCompleteSessionWorkflow:
    """Integration tests for complete session workflows (ITEM-OBS-001)."""

    def test_complete_session_lifecycle(self):
        """Test a complete session with all phases."""
        tracer = DistributedTracer()

        # Start session
        session = tracer.start_session_span("session-001")

        # INIT phase
        init = tracer.start_phase_span(SpanKind.INIT)
        tracer.end_span(init)

        # DISCOVERY phase with tool scans
        discovery = tracer.start_phase_span(SpanKind.DISCOVERY)
        tool1 = tracer.start_tool_scan_span("file_scanner")
        tracer.end_span(tool1)
        tool2 = tracer.start_tool_scan_span("tool_registry")
        tracer.end_span(tool2)
        tracer.end_span(discovery)

        # ANALYSIS phase
        analysis = tracer.start_phase_span(SpanKind.ANALYSIS)
        tracer.end_span(analysis)

        # PLANNING phase with DAG build
        planning = tracer.start_phase_span(SpanKind.PLANNING)
        dag = tracer.start_dag_build_span("execution_dag")
        tracer.end_span(dag)
        tracer.end_span(planning)

        # EXECUTION phase with gates and batches
        execution = tracer.start_phase_span(SpanKind.EXECUTION)
        
        gate1 = tracer.start_gate_span("GATE-01", gate_type="validation")
        batch1 = tracer.start_batch_span("batch-001", gate_id="GATE-01")
        tracer.end_span(batch1)
        tracer.end_span(gate1)

        gate2 = tracer.start_gate_span("GATE-02", gate_type="security")
        batch2 = tracer.start_batch_span("batch-002", gate_id="GATE-02")
        tracer.end_span(batch2)
        tracer.end_span(gate2)

        tracer.end_span(execution)

        # DELIVERY phase
        delivery = tracer.start_phase_span(SpanKind.DELIVERY)
        tracer.end_span(delivery)

        # End session
        tracer.end_span(session)

        # Verify hierarchy
        stats = tracer.get_hierarchy_stats()
        # Note: session_started tracks if session was ever started (not if currently active)
        # Spans are tracked even after ending for reference
        assert stats["gates_count"] == 2
        assert stats["batches_count"] == 2
        # Total spans: 1 session + 6 phases + 2 tools + 1 dag + 2 gates + 2 batches = 14
        assert stats["total_spans"] == 14

    def test_traces_complete(self):
        """Test that all defined traces are generated."""
        tracer = DistributedTracer()

        # Start and complete a full session
        session = tracer.start_session_span("test-session")
        
        # All phases
        for phase in [SpanKind.INIT, SpanKind.DISCOVERY, SpanKind.ANALYSIS,
                      SpanKind.PLANNING, SpanKind.EXECUTION, SpanKind.DELIVERY]:
            span = tracer.start_phase_span(phase)
            tracer.end_span(span)

        tracer.end_span(session)

        # Verify all phases were tracked
        all_spans = tracer.get_all_spans()
        span_kinds = [s.span_kind for s in all_spans if s.span_kind]

        assert SpanKind.SESSION in span_kinds
        assert SpanKind.INIT in span_kinds
        assert SpanKind.DISCOVERY in span_kinds
        assert SpanKind.ANALYSIS in span_kinds
        assert SpanKind.PLANNING in span_kinds
        assert SpanKind.EXECUTION in span_kinds
        assert SpanKind.DELIVERY in span_kinds

    def test_hierarchy_correct(self):
        """Test that span hierarchy matches protocol definition."""
        tracer = DistributedTracer()

        session = tracer.start_session_span("test-session")
        execution = tracer.start_phase_span(SpanKind.EXECUTION)
        gate = tracer.start_gate_span("GATE-01")
        batch = tracer.start_batch_span("batch-001", gate_id="GATE-01")

        # Verify parent-child relationships
        assert batch.parent_span_id == gate.span_id
        assert gate.parent_span_id == execution.span_id
        assert execution.parent_span_id == session.span_id
        assert session.parent_span_id is None


class TestContextPropagationWithHierarchy:
    """Tests for context propagation with hierarchy spans (ITEM-OBS-001)."""

    def test_inject_context_from_session(self):
        """Test injecting context from session span."""
        tracer = DistributedTracer()

        session = tracer.start_session_span("test-session")
        carrier = {}
        tracer.inject_context(carrier)

        assert "traceparent" in carrier
        assert session.trace_id in carrier["traceparent"]

    def test_inject_context_from_gate(self):
        """Test injecting context from gate span."""
        tracer = DistributedTracer()

        tracer.start_session_span("test-session")
        tracer.start_phase_span(SpanKind.EXECUTION)
        gate = tracer.start_gate_span("GATE-01")
        
        carrier = {}
        tracer.inject_context(carrier)

        assert "traceparent" in carrier
        assert gate.span_id in carrier["traceparent"]

    def test_extract_and_continue_trace(self):
        """Test extracting context and continuing trace."""
        tracer_a = DistributedTracer(service_name="service-a")

        # Service A starts a trace
        session_a = tracer_a.start_session_span("session-001")
        carrier = {}
        tracer_a.inject_context(carrier)

        # Service B continues the trace
        tracer_b = DistributedTracer(service_name="service-b")
        span_b = tracer_b.start_span_from_context("remote_operation", carrier)

        assert span_b.trace_id == session_a.trace_id


class TestClearSpansWithHierarchy:
    """Tests for clearing spans with hierarchy tracking (ITEM-OBS-001)."""

    def test_clear_spans_clears_hierarchy(self):
        """Test that clear_spans clears hierarchy tracking."""
        tracer = DistributedTracer()

        tracer.start_session_span("test-session")
        tracer.start_phase_span(SpanKind.EXECUTION)
        tracer.start_gate_span("GATE-01")
        tracer.start_batch_span("batch-001", gate_id="GATE-01")

        tracer.clear_spans()

        assert len(tracer._spans) == 0
        assert len(tracer._kind_spans) == 0
        assert len(tracer._gate_spans) == 0
        assert len(tracer._batch_spans) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=src/observability/distributed_tracing", "--cov-report=term-missing"])
