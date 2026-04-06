"""
TITAN FUSE Protocol - Observability Module

Advanced Observability & Transparency Layer (TASK-002)

This module provides:
- Reasoning Tracer: Step-by-step reasoning trace
- Metrics Collector: Prometheus/JSON metrics export
- Debug Controller: Debug mode with reasoning locks
- Span Tracker: Distributed tracing for tool calls
"""

from .tracer import (
    ReasoningTracer,
    ReasoningStep,
    ReasoningTrace,
    start_trace,
    add_step,
    end_trace,
    get_current_trace
)

from .metrics import (
    MetricsCollector,
    MetricType,
    Counter,
    Gauge,
    Histogram,
    get_metrics,
    increment_counter,
    set_gauge,
    observe_histogram
)

from .debug_controller import (
    DebugController,
    DebugMode,
    DebugLock,
    Breakpoint,
    enable_debug,
    disable_debug,
    set_breakpoint,
    step_through
)

from .span_tracker import (
    SpanTracker,
    Span,
    SpanContext,
    start_span,
    end_span,
    get_active_spans
)

__all__ = [
    # Tracer
    "ReasoningTracer",
    "ReasoningStep",
    "ReasoningTrace",
    "start_trace",
    "add_step",
    "end_trace",
    "get_current_trace",
    # Metrics
    "MetricsCollector",
    "MetricType",
    "Counter",
    "Gauge",
    "Histogram",
    "get_metrics",
    "increment_counter",
    "set_gauge",
    "observe_histogram",
    # Debug Controller
    "DebugController",
    "DebugMode",
    "DebugLock",
    "Breakpoint",
    "enable_debug",
    "disable_debug",
    "set_breakpoint",
    "step_through",
    # Span Tracker
    "SpanTracker",
    "Span",
    "SpanContext",
    "start_span",
    "end_span",
    "get_active_spans"
]

__version__ = "1.0.0"
