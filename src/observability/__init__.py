"""
TITAN FUSE Protocol - Observability Module

Advanced Observability & Transparency Layer (TASK-002)

This module provides:
- Reasoning Tracer: Step-by-step reasoning trace
- Metrics Collector: Prometheus/JSON metrics export
- Debug Controller: Debug mode with reasoning locks
- Span Tracker: Distributed tracing for tool calls
- State Validator: Event-state transition contract (ITEM-OBS-06)
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

# ITEM-OBS-06: State Transition Validator
from .state_validator import (
    StateTransitionValidator,
    StateSnapshot,
    StateMutation,
    TransitionResult,
    TransitionValidation,
    validate_event_transition,
    get_state_transition_map
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
    "get_active_spans",
    # State Validator (ITEM-OBS-06)
    "StateTransitionValidator",
    "StateSnapshot",
    "StateMutation",
    "TransitionResult",
    "TransitionValidation",
    "validate_event_transition",
    "get_state_transition_map"
]

__version__ = "3.3.0"
