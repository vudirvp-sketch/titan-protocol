"""
TITAN FUSE Protocol - Observability Module

Advanced Observability & Transparency Layer (TASK-002)

This module provides:
- Reasoning Tracer: Step-by-step reasoning trace
- Metrics Collector: Prometheus/JSON metrics export
- Debug Controller: Debug mode with reasoning locks
- Span Tracker: Distributed tracing for tool calls
- State Validator: Event-state transition contract (ITEM-OBS-06)
- Budget Forecaster: Token velocity forecasting (ITEM-OBS-05)
- Structured Logger: JSON structured logging (ITEM-OBS-07)
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
    observe_histogram,
    BUDGET_METRICS
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

# ITEM-OBS-05: Budget Forecasting
from .budget_forecast import (
    BudgetForecaster,
    UsageRecord,
    ForecastReport,
    WarningLevel,
    get_forecaster,
    init_forecaster,
    record_usage,
    get_budget_report
)

# ITEM-OBS-06: Distributed Tracing Integration
from .distributed_tracing import (
    DistributedTracer,
    Span as DistributedSpan,
    SpanStatus,
    ExporterType,
    TraceContext,
    TracingEventBusIntegration,
    get_distributed_tracer,
    init_distributed_tracer,
    start_span as start_distributed_span,
    end_span as end_distributed_span,
    get_active_span as get_active_distributed_span,
    inject_context,
    extract_context,
    OTEL_AVAILABLE,
    JAEGER_AVAILABLE,
    ZIPKIN_AVAILABLE,
    OTLP_AVAILABLE,
)

# ITEM-OBS-07: Structured Logging Format
from .structured_logging import (
    StructuredLogger,
    JSONLogFormatter,
    LoggingConfig,
    LogLevel,
    OutputDestination,
    OutputFormat,
    LEVEL_ORDER,
    DEFAULT_COMPONENT_LEVELS,
    init_logging,
    get_logger,
    configure_from_yaml,
    shutdown_logging,
    log_event,
    log_error,
    log_gate,
    log_performance,
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
    "BUDGET_METRICS",
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
    "get_state_transition_map",
    # Budget Forecaster (ITEM-OBS-05)
    "BudgetForecaster",
    "UsageRecord",
    "ForecastReport",
    "WarningLevel",
    "get_forecaster",
    "init_forecaster",
    "record_usage",
    "get_budget_report",
    # Structured Logging (ITEM-OBS-07)
    "StructuredLogger",
    "JSONLogFormatter",
    "LoggingConfig",
    "LogLevel",
    "OutputDestination",
    "OutputFormat",
    "LEVEL_ORDER",
    "DEFAULT_COMPONENT_LEVELS",
    "init_logging",
    "get_logger",
    "configure_from_yaml",
    "shutdown_logging",
    "log_event",
    "log_error",
    "log_gate",
    "log_performance",
    # Distributed Tracing (ITEM-OBS-06)
    "DistributedTracer",
    "DistributedSpan",
    "SpanStatus",
    "ExporterType",
    "TraceContext",
    "TracingEventBusIntegration",
    "get_distributed_tracer",
    "init_distributed_tracer",
    "start_distributed_span",
    "end_distributed_span",
    "get_active_distributed_span",
    "inject_context",
    "extract_context",
    "OTEL_AVAILABLE",
    "JAEGER_AVAILABLE",
    "ZIPKIN_AVAILABLE",
    "OTLP_AVAILABLE",
]

__version__ = "4.0.0"
