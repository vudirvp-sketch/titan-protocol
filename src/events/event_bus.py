"""
TITAN FUSE Protocol - Event Bus

Structured event-driven communication for all phases and GATE operations.
Replaces raw log parsing with typed, machine-readable events.
"""

import json
from datetime import datetime
from typing import Dict, Any, List, Callable, Optional
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path


class EventType(Enum):
    """Standard event types for TITAN Protocol."""
    # Session events
    SESSION_INIT = "session.init"
    SESSION_RESUME = "session.resume"
    SESSION_COMPLETE = "session.complete"
    SESSION_PAUSE = "session.pause"
    SESSION_FAIL = "session.fail"

    # Phase events
    PHASE_START = "phase.start"
    PHASE_COMPLETE = "phase.complete"
    PHASE_FAIL = "phase.fail"

    # Gate events
    GATE_PASS = "gate.pass"
    GATE_FAIL = "gate.fail"
    GATE_WARN = "gate.warn"
    GATE_BLOCK = "gate.block"

    # Chunk events
    CHUNK_START = "chunk.start"
    CHUNK_COMPLETE = "chunk.complete"
    CHUNK_FAIL = "chunk.fail"

    # Tool events
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    TOOL_ERROR = "tool.error"

    # Validation events
    VALIDATION_PASS = "validation.pass"
    VALIDATION_FAIL = "validation.fail"
    PATCH_APPLY = "patch.apply"
    PATCH_SKIP = "patch.skip"

    # Compaction events
    COMPACT_START = "compact.start"
    COMPACT_COMPLETE = "compact.complete"

    # Metric events
    METRIC_EMIT = "metric.emit"
    BUDGET_WARNING = "budget.warning"
    BUDGET_EXCEEDED = "budget.exceeded"


@dataclass
class Event:
    """Structured event for TITAN Protocol."""
    type: str
    timestamp: str
    session_id: Optional[str] = None
    data: Dict[str, Any] = None
    metadata: Dict[str, Any] = None

    def to_json(self) -> str:
        """Serialize event to JSON."""
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, json_str: str) -> "Event":
        """Deserialize event from JSON."""
        data = json.loads(json_str)
        return cls(**data)


class EventBus:
    """
    Event bus for structured event-driven communication.

    Features:
    - Typed event emission
    - Event subscription/handlers
    - Event logging/replay
    - Prometheus-compatible metrics export
    """

    def __init__(self, log_path: Optional[Path] = None):
        self.handlers: Dict[str, List[Callable]] = {}
        self.event_log: List[Event] = []
        self.log_path = log_path
        self.session_id: Optional[str] = None

        # Metrics collectors
        self.metrics = {
            "events_total": 0,
            "events_by_type": {},
            "gates_passed": 0,
            "gates_failed": 0,
            "chunks_completed": 0,
            "patches_applied": 0,
            "tokens_used": 0
        }

    def set_session(self, session_id: str) -> None:
        """Set current session ID for events."""
        self.session_id = session_id

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """
        Subscribe a handler to an event type.

        Args:
            event_type: Event type to subscribe to
            handler: Callable to handle the event
        """
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        """Unsubscribe a handler from an event type."""
        if event_type in self.handlers:
            self.handlers[event_type] = [
                h for h in self.handlers[event_type] if h != handler
            ]

    def emit(self, event_type: str, data: Dict[str, Any] = None,
             metadata: Dict[str, Any] = None) -> Event:
        """
        Emit a structured event.

        Args:
            event_type: Type of event
            data: Event payload
            metadata: Additional metadata

        Returns:
            The emitted event
        """
        event = Event(
            type=event_type,
            timestamp=datetime.utcnow().isoformat() + "Z",
            session_id=self.session_id,
            data=data or {},
            metadata=metadata or {}
        )

        # Update metrics
        self.metrics["events_total"] += 1
        self.metrics["events_by_type"][event_type] = \
            self.metrics["events_by_type"].get(event_type, 0) + 1

        # Track specific metrics
        if "gate" in event_type:
            if "pass" in event_type:
                self.metrics["gates_passed"] += 1
            elif "fail" in event_type or "block" in event_type:
                self.metrics["gates_failed"] += 1

        if "chunk" in event_type and "complete" in event_type:
            self.metrics["chunks_completed"] += 1

        if "patch" in event_type and "apply" in event_type:
            self.metrics["patches_applied"] += 1

        # Add to event log
        self.event_log.append(event)

        # Write to log file if configured
        if self.log_path:
            self._write_to_log(event)

        # Call handlers
        handlers = self.handlers.get(event_type, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                # Log handler error but don't fail
                print(f"Handler error for {event_type}: {e}")

        # Also call wildcard handlers
        for handler in self.handlers.get("*", []):
            try:
                handler(event)
            except Exception as e:
                print(f"Wildcard handler error: {e}")

        return event

    def _write_to_log(self, event: Event) -> None:
        """Write event to log file."""
        try:
            with open(self.log_path, "a") as f:
                f.write(event.to_json() + "\n")
        except Exception as e:
            print(f"Failed to write event log: {e}")

    def get_events(self, event_type: Optional[str] = None,
                   limit: int = 100) -> List[Event]:
        """
        Get events from the log.

        Args:
            event_type: Filter by event type (optional)
            limit: Maximum number of events to return

        Returns:
            List of events
        """
        events = self.event_log

        if event_type:
            events = [e for e in events if e.type == event_type]

        return events[-limit:]

    def replay_events(self, events: List[Event]) -> None:
        """
        Replay events through handlers.

        Args:
            events: List of events to replay
        """
        for event in events:
            handlers = self.handlers.get(event.type, [])
            for handler in handlers:
                try:
                    handler(event)
                except Exception as e:
                    print(f"Replay handler error: {e}")

    def export_metrics(self) -> Dict[str, Any]:
        """
        Export metrics in Prometheus-compatible format.

        Returns:
            Metrics dictionary
        """
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": self.session_id,
            "metrics": self.metrics.copy()
        }

    def export_prometheus(self) -> str:
        """
        Export metrics in Prometheus text format.

        Returns:
            Prometheus-formatted metrics string
        """
        lines = []

        lines.append("# HELP titan_events_total Total number of events emitted")
        lines.append("# TYPE titan_events_total counter")
        lines.append(f"titan_events_total {self.metrics['events_total']}")

        lines.append("# HELP titan_gates_passed Number of gates passed")
        lines.append("# TYPE titan_gates_passed counter")
        lines.append(f"titan_gates_passed {self.metrics['gates_passed']}")

        lines.append("# HELP titan_gates_failed Number of gates failed")
        lines.append("# TYPE titan_gates_failed counter")
        lines.append(f"titan_gates_failed {self.metrics['gates_failed']}")

        lines.append("# HELP titan_chunks_completed Number of chunks completed")
        lines.append("# TYPE titan_chunks_completed counter")
        lines.append(f"titan_chunks_completed {self.metrics['chunks_completed']}")

        lines.append("# HELP titan_patches_applied Number of patches applied")
        lines.append("# TYPE titan_patches_applied counter")
        lines.append(f"titan_patches_applied {self.metrics['patches_applied']}")

        # Events by type
        lines.append("# HELP titan_events_by_type Events by type")
        lines.append("# TYPE titan_events_by_type counter")
        for event_type, count in self.metrics["events_by_type"].items():
            safe_type = event_type.replace(".", "_")
            lines.append(f'titan_events_by_type{{type="{safe_type}"}} {count}')

        return "\n".join(lines)

    def clear_log(self) -> None:
        """Clear the event log."""
        self.event_log.clear()

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the event log."""
        return {
            "total_events": len(self.event_log),
            "event_types": list(set(e.type for e in self.event_log)),
            "session_id": self.session_id,
            "metrics": self.metrics.copy()
        }


# Global event bus instance
_global_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus


def init_event_bus(log_path: Optional[Path] = None) -> EventBus:
    """Initialize the global event bus."""
    global _global_event_bus
    _global_event_bus = EventBus(log_path=log_path)
    return _global_event_bus
