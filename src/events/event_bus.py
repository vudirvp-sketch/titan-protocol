"""
Event Bus for TITAN FUSE Protocol.

Provides event-driven architecture with severity-based dispatch
and handler failure escalation.

ITEM-ARCH-02: Integration with EventJournal for crash recovery.
- EventJournal.append() called before event handlers execute
- CRITICAL and WARN events: sync write
- INFO and DEBUG events: async write (buffered)

Author: TITAN FUSE Team
Version: 3.3.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Callable, Any, Optional, TYPE_CHECKING
import logging
import traceback
from pathlib import Path

if TYPE_CHECKING:
    from ..state.event_journal import EventJournal


class EventSeverity(Enum):
    """Event severity levels determining dispatch behavior."""
    CRITICAL = 1  # GATE_FAIL, BUDGET_EXCEEDED - sync dispatch
    WARN = 2      # GATE_WARN, ANOMALY_DETECTED
    INFO = 3      # GATE_PASS, CURSOR_UPDATED
    DEBUG = 4     # Detailed trace events


@dataclass
class Event:
    """
    An event in the TITAN FUSE event system.

    Events carry typed data with severity classification,
    enabling prioritized dispatch and handling.
    """
    event_type: str
    data: Dict[str, Any]
    severity: EventSeverity = EventSeverity.INFO
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    source: Optional[str] = None
    event_id: str = field(default_factory=lambda: f"evt-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}")

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "data": self.data,
            "severity": self.severity.name,
            "timestamp": self.timestamp,
            "source": self.source
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Event':
        """Create from dictionary."""
        return cls(
            event_type=data["event_type"],
            data=data["data"],
            severity=EventSeverity[data.get("severity", "INFO")],
            timestamp=data.get("timestamp", datetime.utcnow().isoformat() + "Z"),
            source=data.get("source"),
            event_id=data.get("event_id", f"evt-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}")
        )

    def __str__(self) -> str:
        """Human-readable representation."""
        severity_markers = {
            EventSeverity.CRITICAL: "⛔",
            EventSeverity.WARN: "⚠️",
            EventSeverity.INFO: "ℹ️",
            EventSeverity.DEBUG: "🔍"
        }
        marker = severity_markers.get(self.severity, "•")
        return f"{marker} [{self.event_type}] {self.severity.name}"


class EventBus:
    """
    Event bus with severity-based dispatch and handler failure escalation.

    Features:
    - Type-specific handler subscription
    - Severity-based handler subscription
    - Synchronous dispatch for CRITICAL events
    - Handler failure escalation with EVENT_HANDLER_FAILURE events

    Usage:
        bus = EventBus()

        # Subscribe to specific event type
        bus.subscribe("GATE_FAIL", on_gate_fail)

        # Subscribe to all CRITICAL events
        bus.subscribe_severity(EventSeverity.CRITICAL, on_critical)

        # Emit event
        bus.emit(Event("GATE_PASS", {"gate_id": "GATE-00"}, EventSeverity.INFO))
    """

    def __init__(self, config: Dict = None, journal: 'EventJournal' = None):
        self.config = config or {}
        self._journal = journal  # ITEM-ARCH-02: Event journal for WAL
        self._handlers: Dict[str, List[Callable]] = {}
        self._severity_handlers: Dict[EventSeverity, List[Callable]] = {}
        self._logger = logging.getLogger(__name__)
        self._handler_failure_action = self.config.get("handler_failure_action", "log")
        self._event_history: List[Event] = []
        self._max_history = self.config.get("max_history", 1000)

    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        """
        Subscribe handler to event type.

        Args:
            event_type: Event type to subscribe to (or "*" for all)
            handler: Function to call when event is emitted
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        self._logger.debug(f"Subscribed handler to {event_type}")

    def subscribe_severity(self, severity: EventSeverity, handler: Callable[[Event], None]) -> None:
        """
        Subscribe handler to all events of given severity.

        Args:
            severity: Event severity level
            handler: Function to call when matching event is emitted
        """
        if severity not in self._severity_handlers:
            self._severity_handlers[severity] = []
        self._severity_handlers[severity].append(handler)
        self._logger.debug(f"Subscribed handler to severity {severity.name}")

    def unsubscribe(self, event_type: str, handler: Callable) -> bool:
        """Unsubscribe handler from event type."""
        if event_type in self._handlers and handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)
            return True
        return False

    def emit(self, event: Event, state_hash: str = "") -> None:
        """
        Emit event with handler failure escalation.

        ITEM-ARCH-02: Event is written to journal BEFORE handlers execute.
        This ensures crash recovery can replay unprocessed events.

        Args:
            event: Event to emit
            state_hash: Optional hash of current state for recovery
        """
        # ITEM-ARCH-02: Write to journal BEFORE handlers execute
        if self._journal:
            sync = event.severity in (EventSeverity.CRITICAL, EventSeverity.WARN)
            self._journal.append(
                event=event.to_dict(),
                state_hash=state_hash,
                sync=sync
            )

        # Record in history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]

        self._logger.debug(f"Emitting event: {event.event_type} ({event.severity.name})")

        # Dispatch to type-specific handlers
        for handler in self._get_handlers(event.event_type):
            self._safe_dispatch(handler, event)

        # Dispatch to severity-specific handlers
        for handler in self._severity_handlers.get(event.severity, []):
            self._safe_dispatch(handler, event)

        # Sync dispatch for CRITICAL events
        if event.severity == EventSeverity.CRITICAL:
            self._dispatch_critical(event)

    def emit_simple(self, event_type: str, data: Dict,
                    severity: EventSeverity = EventSeverity.INFO,
                    source: str = None) -> Event:
        """
        Convenience method to create and emit event.

        Returns:
            The emitted event
        """
        event = Event(
            event_type=event_type,
            data=data,
            severity=severity,
            source=source
        )
        self.emit(event)
        return event

    def _get_handlers(self, event_type: str) -> List[Callable]:
        """Get handlers for event type, including wildcard."""
        handlers = self._handlers.get(event_type, [])
        wildcard_handlers = self._handlers.get("*", [])
        return handlers + wildcard_handlers

    def _safe_dispatch(self, handler: Callable, event: Event) -> None:
        """Dispatch with failure handling."""
        try:
            handler(event)
        except Exception as e:
            self._handle_handler_failure(handler, e, event)

    def _handle_handler_failure(self, handler: Callable, error: Exception, event: Event) -> None:
        """Handle handler failure with escalation."""
        handler_name = getattr(handler, '__name__', str(handler))
        self._logger.error(f"Handler {handler_name} failed: {error}\n{traceback.format_exc()}")

        # Emit failure event
        failure_event = Event(
            event_type="EVENT_HANDLER_FAILURE",
            data={
                "failed_handler": handler_name,
                "original_event": event.event_type,
                "original_event_id": event.event_id,
                "error": str(error),
                "error_type": type(error).__name__,
                "traceback": traceback.format_exc()
            },
            severity=EventSeverity.CRITICAL,
            source="EventBus"
        )
        self._dispatch_critical(failure_event)

        # Escalate based on config
        action = self._handler_failure_action
        if action == "abort":
            self._logger.critical(f"Aborting due to handler failure: {handler_name}")
            raise error
        elif action == "warn":
            self._logger.warning(f"Handler failure escalated: {handler_name}")

    def _dispatch_critical(self, event: Event) -> None:
        """Synchronous dispatch for CRITICAL events."""
        for handler in self._get_handlers(event.event_type):
            try:
                handler(event)
            except Exception as e:
                # CRITICAL handler failure - log and continue
                handler_name = getattr(handler, '__name__', str(handler))
                self._logger.critical(f"CRITICAL handler failed: {handler_name}: {e}")

    def get_history(self, limit: int = 100, severity: EventSeverity = None) -> List[Event]:
        """Get recent event history."""
        events = self._event_history
        if severity:
            events = [e for e in events if e.severity == severity]
        return events[-limit:]

    def clear_history(self) -> None:
        """Clear event history."""
        self._event_history.clear()

    def set_journal(self, journal: 'EventJournal') -> None:
        """
        ITEM-ARCH-02: Set the event journal for WAL.

        Args:
            journal: EventJournal instance
        """
        self._journal = journal
        self._logger.info("Event journal attached to EventBus")

    def get_journal(self) -> Optional['EventJournal']:
        """Get the current event journal."""
        return self._journal

    def flush_journal(self) -> None:
        """Flush buffered events to journal."""
        if self._journal:
            self._journal.sync_flush()

    def get_stats(self) -> Dict:
        """Get event bus statistics."""
        severity_counts = {}
        for sev in EventSeverity:
            severity_counts[sev.name] = len([e for e in self._event_history if e.severity == sev])

        stats = {
            "total_events": len(self._event_history),
            "handler_count": sum(len(h) for h in self._handlers.values()),
            "severity_handlers": {s.name: len(h) for s, h in self._severity_handlers.items()},
            "severity_distribution": severity_counts,
            "journal_enabled": self._journal is not None
        }

        # Add journal stats if available
        if self._journal:
            stats["journal"] = self._journal.get_stats()

        return stats


# Pre-defined event types
class EventTypes:
    """Standard event types for TITAN FUSE Protocol."""

    # Gate events
    GATE_PASS = "GATE_PASS"
    GATE_FAIL = "GATE_FAIL"
    GATE_WARN = "GATE_WARN"

    # Phase events
    PHASE_START = "PHASE_START"
    PHASE_COMPLETE = "PHASE_COMPLETE"

    # Processing events
    CHUNK_START = "CHUNK_START"
    CHUNK_COMPLETE = "CHUNK_COMPLETE"
    CURSOR_UPDATED = "CURSOR_UPDATED"

    # Issue events
    ISSUE_FOUND = "ISSUE_FOUND"
    ISSUE_FIXED = "ISSUE_FIXED"

    # Budget events
    BUDGET_WARNING = "BUDGET_WARNING"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"

    # Error events
    EVENT_HANDLER_FAILURE = "EVENT_HANDLER_FAILURE"
    CURSOR_DRIFT = "CURSOR_DRIFT"

    # v3.2.1 Module events
    INVENTORY_READY = "INVENTORY_READY"
    CROSSREF_BROKEN = "CROSSREF_BROKEN"
    ANOMALY_DETECTED = "ANOMALY_DETECTED"
