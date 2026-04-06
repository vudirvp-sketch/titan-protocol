"""
TITAN FUSE Protocol - Span Tracker

Distributed tracing for tool calls and operations.
Supports OpenTelemetry-compatible spans.

TASK-002: Advanced Observability & Transparency Layer
"""

import json
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import time


class SpanKind(Enum):
    """Kind of span."""
    INTERNAL = "internal"
    SERVER = "server"
    CLIENT = "client"
    PRODUCER = "producer"
    CONSUMER = "consumer"


class SpanStatus(Enum):
    """Status of a span."""
    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


@dataclass
class SpanContext:
    """
    Context for a span.

    Attributes:
        trace_id: Unique trace identifier
        span_id: Unique span identifier
        parent_span_id: Parent span ID (if any)
        trace_flags: Trace flags (e.g., sampled)
    """
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    parent_span_id: Optional[str] = None
    trace_flags: int = 1  # Sampled by default

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "trace_flags": self.trace_flags
        }


@dataclass
class SpanEvent:
    """An event within a span."""
    name: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "timestamp": self.timestamp,
            "attributes": self.attributes
        }


@dataclass
class Span:
    """
    A span representing a unit of work.

    Attributes:
        context: Span context
        name: Span name
        kind: Span kind
        start_time: When span started
        end_time: When span ended
        status: Span status
        attributes: Span attributes
        events: Span events
        links: Links to other spans
    """
    context: SpanContext
    name: str
    kind: SpanKind = SpanKind.INTERNAL
    start_time: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    end_time: Optional[str] = None
    status: SpanStatus = SpanStatus.UNSET
    status_message: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[SpanEvent] = field(default_factory=list)
    links: List[Dict[str, Any]] = field(default_factory=list)
    _start_ns: int = field(default_factory=time.time_ns, repr=False)

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self.attributes[key] = value

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        """Add an event to the span."""
        self.events.append(SpanEvent(
            name=name,
            attributes=attributes or {}
        ))

    def set_status(self, status: SpanStatus, message: str = "") -> None:
        """Set span status."""
        self.status = status
        self.status_message = message

    def end(self) -> None:
        """End the span."""
        self.end_time = datetime.utcnow().isoformat() + "Z"

    def get_duration_ms(self) -> Optional[int]:
        """Get span duration in milliseconds."""
        if not self.end_time:
            return None

        end_ns = time.time_ns()
        duration_ns = end_ns - self._start_ns
        return duration_ns // 1_000_000

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "context": self.context.to_dict(),
            "name": self.name,
            "kind": self.kind.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.get_duration_ms(),
            "status": self.status.value,
            "status_message": self.status_message,
            "attributes": self.attributes,
            "events": [e.to_dict() for e in self.events],
            "links": self.links
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class SpanTracker:
    """
    Tracker for distributed spans.

    Features:
    - Span creation and management
    - Parent-child span relationships
    - Span export (JSON, OpenTelemetry)
    - Active span tracking
    - Event recording

    Usage:
        tracker = SpanTracker()

        # Start a span
        parent = tracker.start_span("operation")

        # Start a child span
        child = tracker.start_span("sub_operation", parent_context=parent.context)

        # Add events and attributes
        child.set_attribute("key", "value")
        child.add_event("milestone")

        # End spans
        child.end()
        parent.end()

        # Export
        print(tracker.export_json())
    """

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path
        self._spans: List[Span] = []
        self._active_spans: Dict[str, Span] = {}
        self._lock = None  # For thread safety if needed

    def start_span(self,
                   name: str,
                   kind: SpanKind = SpanKind.INTERNAL,
                   parent_context: Optional[SpanContext] = None,
                   attributes: Optional[Dict[str, Any]] = None) -> Span:
        """
        Start a new span.

        Args:
            name: Span name
            kind: Span kind
            parent_context: Parent span context (for child spans)
            attributes: Initial attributes

        Returns:
            The created span
        """
        context = SpanContext()

        if parent_context:
            context.trace_id = parent_context.trace_id
            context.parent_span_id = parent_context.span_id

        span = Span(
            context=context,
            name=name,
            kind=kind,
            attributes=attributes or {}
        )

        self._spans.append(span)
        self._active_spans[context.span_id] = span

        # Write to log if configured
        if self.log_path:
            self._write_span_event("start", span)

        return span

    def end_span(self, span: Span) -> None:
        """End a span."""
        span.end()

        if span.context.span_id in self._active_spans:
            del self._active_spans[span.context.span_id]

        if self.log_path:
            self._write_span_event("end", span)

    def get_span(self, span_id: str) -> Optional[Span]:
        """Get a span by ID."""
        return self._active_spans.get(span_id)

    def get_active_spans(self) -> List[Span]:
        """Get all active spans."""
        return list(self._active_spans.values())

    def get_trace(self, trace_id: str) -> List[Span]:
        """Get all spans for a trace."""
        return [
            s for s in self._spans
            if s.context.trace_id == trace_id
        ]

    def get_spans(self) -> List[Span]:
        """Get all spans."""
        return self._spans

    def export_json(self) -> Dict[str, Any]:
        """Export all spans as JSON."""
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "total_spans": len(self._spans),
            "active_spans": len(self._active_spans),
            "spans": [s.to_dict() for s in self._spans]
        }

    def export_opentelemetry(self) -> List[Dict[str, Any]]:
        """
        Export in OpenTelemetry format.

        Returns:
            List of span data in OTLP format
        """
        return [
            {
                "traceId": s.context.trace_id,
                "spanId": s.context.span_id,
                "parentSpanId": s.context.parent_span_id,
                "name": s.name,
                "kind": s.kind.value,
                "startTime": s.start_time,
                "endTime": s.end_time,
                "status": {
                    "code": s.status.value
                },
                "attributes": s.attributes,
                "events": [e.to_dict() for e in s.events]
            }
            for s in self._spans
        ]

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of tracked spans."""
        by_kind = {}
        by_status = {}
        total_duration_ms = 0

        for span in self._spans:
            kind = span.kind.value
            status = span.status.value
            by_kind[kind] = by_kind.get(kind, 0) + 1
            by_status[status] = by_status.get(status, 0) + 1

            duration = span.get_duration_ms()
            if duration:
                total_duration_ms += duration

        return {
            "total_spans": len(self._spans),
            "active_spans": len(self._active_spans),
            "total_duration_ms": total_duration_ms,
            "by_kind": by_kind,
            "by_status": by_status
        }

    def clear(self) -> None:
        """Clear all spans."""
        self._spans.clear()
        self._active_spans.clear()

    def _write_span_event(self, event: str, span: Span) -> None:
        """Write span event to log file."""
        if not self.log_path:
            return

        try:
            with open(self.log_path, "a") as f:
                log_entry = {
                    "event": event,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "span": span.to_dict()
                }
                f.write(json.dumps(log_entry) + "\n")
        except Exception as e:
            print(f"Failed to write span log: {e}")


# Global span tracker
_global_tracker: Optional[SpanTracker] = None


def get_span_tracker() -> SpanTracker:
    """Get the global span tracker."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = SpanTracker()
    return _global_tracker


def start_span(name: str,
               kind: SpanKind = SpanKind.INTERNAL,
               parent_context: Optional[SpanContext] = None,
               attributes: Optional[Dict[str, Any]] = None) -> Span:
    """Start a span in the global tracker."""
    return get_span_tracker().start_span(name, kind, parent_context, attributes)


def end_span(span: Span) -> None:
    """End a span in the global tracker."""
    get_span_tracker().end_span(span)


def get_active_spans() -> List[Span]:
    """Get active spans from the global tracker."""
    return get_span_tracker().get_active_spans()
