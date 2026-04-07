"""
Event Bus for TITAN FUSE Protocol.

Provides event-driven architecture with severity-based dispatch
and handler failure escalation.

ITEM-ARCH-02: Integration with EventJournal for crash recovery.
- EventJournal.append() called before event handlers execute
- CRITICAL and WARN events: sync write
- INFO and DEBUG events: async write (buffered)

ITEM-OBS-02: Event Severity Filtering
- Event type to severity mapping
- subscribe_severity() for filtered subscriptions
- Hybrid dispatch: sync CRITICAL/WARN, async INFO/DEBUG
- May drop DEBUG events under load

Author: TITAN FUSE Team
Version: 3.3.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Callable, Any, Optional, TYPE_CHECKING, Set
import logging
import traceback
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue, Full

if TYPE_CHECKING:
    from ..state.event_journal import EventJournal


# ITEM-OBS-02: Event type to severity mapping
EVENT_SEVERITY_MAP: Dict[str, 'EventSeverity'] = {}
# Will be populated in _initialize_severity_map()


def _initialize_severity_map() -> None:
    """
    ITEM-OBS-02: Initialize event type to severity mapping.

    This mapping determines the default severity for event types,
    enabling automatic severity assignment when not explicitly provided.
    """
    global EVENT_SEVERITY_MAP

    EVENT_SEVERITY_MAP = {
        # CRITICAL: Sync dispatch, block until handlers complete
        "GATE_FAIL": None,  # Will be set after EventSeverity is defined
        "BUDGET_EXCEEDED": None,
        "SESSION_ABORT": None,
        "SECURITY_VIOLATION": None,
        "EVENT_HANDLER_FAILURE": None,
        "CRASH_DETECTED": None,

        # WARN: Sync dispatch with timeout
        "GATE_WARN": None,
        "BUDGET_WARNING": None,
        "ANOMALY_DETECTED": None,
        "CURSOR_DRIFT": None,
        "DEADLOCK_DETECTED": None,
        "RESOURCE_WARNING": None,

        # INFO: Async dispatch, fire-and-forget
        "GATE_PASS": None,
        "CHUNK_PROCESSED": None,
        "CHUNK_COMPLETE": None,
        "CHECKPOINT_SAVED": None,
        "PHASE_COMPLETE": None,
        "PHASE_START": None,
        "SESSION_START": None,
        "SESSION_END": None,
        "CURSOR_UPDATED": None,
        "ISSUE_FIXED": None,
        "INVENTORY_READY": None,

        # DEBUG: Async, may be dropped under load
        "TOKEN_COUNT": None,
        "LATENCY_MEASURED": None,
        "CACHE_HIT": None,
        "CACHE_MISS": None,
        "DEBUG_TRACE": None,
        "HANDLER_CALLED": None,
    }


def get_severity_for_event(event_type: str) -> 'EventSeverity':
    """
    ITEM-OBS-02: Get default severity for event type.

    Args:
        event_type: The event type string

    Returns:
        EventSeverity (defaults to INFO if not mapped)
    """
    # Initialize map if needed
    if not EVENT_SEVERITY_MAP:
        _initialize_severity_map()
        # Set actual severity values after enum is defined
        EVENT_SEVERITY_MAP.update({
            # CRITICAL
            "GATE_FAIL": EventSeverity.CRITICAL,
            "BUDGET_EXCEEDED": EventSeverity.CRITICAL,
            "SESSION_ABORT": EventSeverity.CRITICAL,
            "SECURITY_VIOLATION": EventSeverity.CRITICAL,
            "EVENT_HANDLER_FAILURE": EventSeverity.CRITICAL,
            "CRASH_DETECTED": EventSeverity.CRITICAL,
            # WARN
            "GATE_WARN": EventSeverity.WARN,
            "BUDGET_WARNING": EventSeverity.WARN,
            "ANOMALY_DETECTED": EventSeverity.WARN,
            "CURSOR_DRIFT": EventSeverity.WARN,
            "DEADLOCK_DETECTED": EventSeverity.WARN,
            "RESOURCE_WARNING": EventSeverity.WARN,
            # INFO
            "GATE_PASS": EventSeverity.INFO,
            "CHUNK_PROCESSED": EventSeverity.INFO,
            "CHUNK_COMPLETE": EventSeverity.INFO,
            "CHECKPOINT_SAVED": EventSeverity.INFO,
            "PHASE_COMPLETE": EventSeverity.INFO,
            "PHASE_START": EventSeverity.INFO,
            "SESSION_START": EventSeverity.INFO,
            "SESSION_END": EventSeverity.INFO,
            "CURSOR_UPDATED": EventSeverity.INFO,
            "ISSUE_FIXED": EventSeverity.INFO,
            "INVENTORY_READY": EventSeverity.INFO,
            # DEBUG
            "TOKEN_COUNT": EventSeverity.DEBUG,
            "LATENCY_MEASURED": EventSeverity.DEBUG,
            "CACHE_HIT": EventSeverity.DEBUG,
            "CACHE_MISS": EventSeverity.DEBUG,
            "DEBUG_TRACE": EventSeverity.DEBUG,
            "HANDLER_CALLED": EventSeverity.DEBUG,
        })

    return EVENT_SEVERITY_MAP.get(event_type, EventSeverity.INFO)


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

    ITEM-OBS-02: Severity can be auto-determined from event_type
    if not explicitly provided.
    """
    event_type: str
    data: Dict[str, Any]
    severity: EventSeverity = None  # Will be auto-determined if None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    source: Optional[str] = None
    event_id: str = field(default_factory=lambda: f"evt-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}")

    def __post_init__(self):
        """ITEM-OBS-02: Auto-determine severity from event_type if not set."""
        if self.severity is None:
            self.severity = get_severity_for_event(self.event_type)

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
        severity_str = data.get("severity", "INFO")
        severity = EventSeverity[severity_str] if severity_str else None
        return cls(
            event_type=data["event_type"],
            data=data["data"],
            severity=severity,
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
        return f"{marker} [{self.event_type}] {self.severity.name if self.severity else 'UNKNOWN'}"


# ITEM-OBS-02: Dispatch behavior configuration
class DispatchBehavior(Enum):
    """How events should be dispatched based on severity."""
    SYNC_BLOCK = "sync_block"      # CRITICAL: Block until all handlers complete
    SYNC_TIMEOUT = "sync_timeout"  # WARN: Sync with timeout
    ASYNC_FIRE = "async_fire"      # INFO: Async, fire-and-forget
    ASYNC_DROP = "async_drop"      # DEBUG: Async, may be dropped under load


def get_dispatch_behavior(severity: EventSeverity) -> DispatchBehavior:
    """
    ITEM-OBS-02: Get dispatch behavior for severity level.

    Args:
        severity: Event severity level

    Returns:
        DispatchBehavior enum value
    """
    behavior_map = {
        EventSeverity.CRITICAL: DispatchBehavior.SYNC_BLOCK,
        EventSeverity.WARN: DispatchBehavior.SYNC_TIMEOUT,
        EventSeverity.INFO: DispatchBehavior.ASYNC_FIRE,
        EventSeverity.DEBUG: DispatchBehavior.ASYNC_DROP,
    }
    return behavior_map.get(severity, DispatchBehavior.ASYNC_FIRE)


class EventBus:
    """
    Event bus with severity-based dispatch and handler failure escalation.

    Features:
    - Type-specific handler subscription
    - Severity-based handler subscription
    - Synchronous dispatch for CRITICAL events
    - Handler failure escalation with EVENT_HANDLER_FAILURE events

    ITEM-OBS-02: Hybrid dispatch based on severity:
    - CRITICAL: Sync, block until all handlers complete
    - WARN: Sync with timeout
    - INFO: Async, fire-and-forget
    - DEBUG: Async, may be dropped under load

    Usage:
        bus = EventBus()

        # Subscribe to specific event type
        bus.subscribe("GATE_FAIL", on_gate_fail)

        # Subscribe to all CRITICAL events
        bus.subscribe_severity(EventSeverity.CRITICAL, on_critical)

        # Emit event (severity auto-determined from event_type)
        bus.emit(Event("GATE_PASS", {"gate_id": "GATE-00"}))
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

        # ITEM-OBS-02: Async dispatch infrastructure
        self._async_queue: Queue = Queue(maxsize=self.config.get("async_queue_size", 1000))
        self._debug_drop_threshold = self.config.get("debug_drop_threshold", 0.8)
        self._warn_timeout_seconds = self.config.get("warn_timeout_seconds", 5.0)
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="eventbus-")
        self._dropped_debug_count = 0
        self._async_enabled = self.config.get("async_enabled", True)

        # Minimum severity to dispatch (for filtering)
        self._min_severity = self._parse_min_severity(
            self.config.get("min_severity", "DEBUG")
        )

    def _parse_min_severity(self, severity_str: str) -> EventSeverity:
        """Parse minimum severity from config string."""
        try:
            return EventSeverity[severity_str.upper()]
        except KeyError:
            self._logger.warning(f"Invalid min_severity '{severity_str}', defaulting to DEBUG")
            return EventSeverity.DEBUG

    def set_min_severity(self, severity: EventSeverity) -> None:
        """
        ITEM-OBS-02: Set minimum severity for event dispatch.

        Events with severity below this threshold will not be dispatched
        (though they will still be recorded in history and journal).

        Args:
            severity: Minimum EventSeverity to dispatch
        """
        self._min_severity = severity
        self._logger.info(f"Minimum dispatch severity set to {severity.name}")

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
        ITEM-OBS-02: Subscribe handler to all events of given severity or higher.

        Note: Lower severity number = higher priority.
        CRITICAL=1, WARN=2, INFO=3, DEBUG=4

        Args:
            severity: Minimum event severity level to receive
            handler: Function to call when matching event is emitted
        """
        if severity not in self._severity_handlers:
            self._severity_handlers[severity] = []
        self._severity_handlers[severity].append(handler)
        self._logger.debug(f"Subscribed handler to severity {severity.name}")

    def subscribe_min_severity(self, min_severity: EventSeverity, handler: Callable[[Event], None]) -> None:
        """
        ITEM-OBS-02: Subscribe to all events at or above severity level.

        Args:
            min_severity: Minimum severity (CRITICAL=1 is highest)
            handler: Function to call
        """
        # Subscribe to each severity level at or above the minimum
        for sev in EventSeverity:
            if sev.value <= min_severity.value:  # Lower value = higher severity
                self.subscribe_severity(sev, handler)

    def unsubscribe(self, event_type: str, handler: Callable) -> bool:
        """Unsubscribe handler from event type."""
        if event_type in self._handlers and handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)
            return True
        return False

    def unsubscribe_severity(self, severity: EventSeverity, handler: Callable) -> bool:
        """Unsubscribe handler from severity level."""
        if severity in self._severity_handlers and handler in self._severity_handlers[severity]:
            self._severity_handlers[severity].remove(handler)
            return True
        return False

    def emit(self, event: Event, state_hash: str = "") -> None:
        """
        Emit event with severity-based hybrid dispatch.

        ITEM-ARCH-02: Event is written to journal BEFORE handlers execute.
        This ensures crash recovery can replay unprocessed events.

        ITEM-OBS-02: Dispatch behavior based on severity:
        - CRITICAL: Synchronous, block until all handlers complete
        - WARN: Synchronous with configurable timeout
        - INFO: Async, fire-and-forget (queued)
        - DEBUG: Async, may be dropped under load

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

        # ITEM-OBS-02: Check minimum severity filter
        if event.severity.value > self._min_severity.value:
            self._logger.debug(f"Event {event.event_type} below min severity, skipping dispatch")
            return

        # ITEM-OBS-02: Hybrid dispatch based on severity
        behavior = get_dispatch_behavior(event.severity)

        if behavior == DispatchBehavior.SYNC_BLOCK:
            self._dispatch_sync_block(event)
        elif behavior == DispatchBehavior.SYNC_TIMEOUT:
            self._dispatch_sync_timeout(event)
        elif behavior == DispatchBehavior.ASYNC_FIRE:
            self._dispatch_async_fire(event)
        elif behavior == DispatchBehavior.ASYNC_DROP:
            self._dispatch_async_drop(event)

    def _dispatch_sync_block(self, event: Event) -> None:
        """CRITICAL: Synchronous dispatch, block until all handlers complete."""
        # Dispatch to type-specific handlers
        for handler in self._get_handlers(event.event_type):
            self._safe_dispatch_sync(handler, event)

        # Dispatch to severity-specific handlers
        for handler in self._severity_handlers.get(event.severity, []):
            self._safe_dispatch_sync(handler, event)

    def _dispatch_sync_timeout(self, event: Event) -> None:
        """WARN: Synchronous dispatch with timeout."""
        import time

        start_time = time.time()
        remaining_time = self._warn_timeout_seconds

        # Dispatch to type-specific handlers with timeout
        for handler in self._get_handlers(event.event_type):
            if remaining_time <= 0:
                self._logger.warning(f"Timeout exceeded for {event.event_type}, skipping remaining handlers")
                break
            self._safe_dispatch_sync(handler, event)
            remaining_time = self._warn_timeout_seconds - (time.time() - start_time)

        # Dispatch to severity-specific handlers
        for handler in self._severity_handlers.get(event.severity, []):
            if remaining_time <= 0:
                self._logger.warning(f"Timeout exceeded for severity handlers")
                break
            self._safe_dispatch_sync(handler, event)
            remaining_time = self._warn_timeout_seconds - (time.time() - start_time)

    def _dispatch_async_fire(self, event: Event) -> None:
        """INFO: Async dispatch, fire-and-forget."""
        if not self._async_enabled:
            # Fallback to sync if async disabled
            self._dispatch_sync_block(event)
            return

        try:
            # Queue the dispatch
            self._async_queue.put_nowait(event)
            # Process in thread pool
            self._executor.submit(self._process_async_queue)
        except Full:
            self._logger.warning(f"Async queue full, dropping INFO event: {event.event_type}")

    def _dispatch_async_drop(self, event: Event) -> None:
        """DEBUG: Async dispatch, may be dropped under load."""
        if not self._async_enabled:
            return  # Drop immediately if async disabled

        # Check queue fill level
        fill_level = self._async_queue.qsize() / self._async_queue.maxsize

        if fill_level > self._debug_drop_threshold:
            self._dropped_debug_count += 1
            self._logger.debug(f"Dropping DEBUG event under load: {event.event_type} (dropped: {self._dropped_debug_count})")
            return

        try:
            self._async_queue.put_nowait(event)
            self._executor.submit(self._process_async_queue)
        except Full:
            self._dropped_debug_count += 1
            self._logger.debug(f"Queue full, dropping DEBUG event: {event.event_type}")

    def _process_async_queue(self) -> None:
        """Process events from async queue."""
        try:
            event = self._async_queue.get_nowait()
            # Dispatch synchronously (but in background thread)
            for handler in self._get_handlers(event.event_type):
                self._safe_dispatch(handler, event)
            for handler in self._severity_handlers.get(event.severity, []):
                self._safe_dispatch(handler, event)
            self._async_queue.task_done()
        except Exception:
            pass  # Queue empty or other error

    def _safe_dispatch_sync(self, handler: Callable, event: Event) -> None:
        """Dispatch synchronously with failure handling."""
        try:
            handler(event)
        except Exception as e:
            self._handle_handler_failure(handler, e, event)

    def emit_simple(self, event_type: str, data: Dict,
                    severity: EventSeverity = None,
                    source: str = None) -> Event:
        """
        Convenience method to create and emit event.

        ITEM-OBS-02: Severity is auto-determined if not provided.

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
        # Use sync dispatch for failure events to avoid recursion
        self._dispatch_sync_block(failure_event)

        # Escalate based on config
        action = self._handler_failure_action
        if action == "abort":
            self._logger.critical(f"Aborting due to handler failure: {handler_name}")
            raise error
        elif action == "warn":
            self._logger.warning(f"Handler failure escalated: {handler_name}")

    def _dispatch_critical(self, event: Event) -> None:
        """Synchronous dispatch for CRITICAL events (legacy support)."""
        self._dispatch_sync_block(event)

    def get_history(self, limit: int = 100, severity: EventSeverity = None,
                    min_severity: EventSeverity = None) -> List[Event]:
        """
        Get recent event history.

        Args:
            limit: Maximum number of events to return
            severity: Filter to exact severity (optional)
            min_severity: Filter to severity at or above this level (optional)

        Returns:
            List of events
        """
        events = self._event_history

        if severity:
            events = [e for e in events if e.severity == severity]
        elif min_severity:
            events = [e for e in events if e.severity.value <= min_severity.value]

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
        """Get event bus statistics including ITEM-OBS-02 metrics."""
        severity_counts = {}
        for sev in EventSeverity:
            severity_counts[sev.name] = len([e for e in self._event_history if e.severity == sev])

        stats = {
            "total_events": len(self._event_history),
            "handler_count": sum(len(h) for h in self._handlers.values()),
            "severity_handlers": {s.name: len(h) for s, h in self._severity_handlers.items()},
            "severity_distribution": severity_counts,
            "journal_enabled": self._journal is not None,
            # ITEM-OBS-02: Additional metrics
            "async_queue_size": self._async_queue.qsize(),
            "async_queue_max": self._async_queue.maxsize,
            "dropped_debug_events": self._dropped_debug_count,
            "min_severity": self._min_severity.name,
            "async_enabled": self._async_enabled,
        }

        # Add journal stats if available
        if self._journal:
            stats["journal"] = self._journal.get_stats()

        return stats

    def shutdown(self, wait: bool = True) -> None:
        """
        ITEM-OBS-02: Gracefully shutdown the event bus.

        Args:
            wait: If True, wait for async queue to empty
        """
        self._logger.info("Shutting down EventBus")

        # Flush any remaining async events
        if wait:
            try:
                self._async_queue.join()
            except Exception:
                pass

        # Shutdown executor
        self._executor.shutdown(wait=wait)

        # Flush journal
        if self._journal:
            self._journal.sync_flush()

        self._logger.info(f"EventBus shutdown complete. Dropped {self._dropped_debug_count} DEBUG events")


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
    CHUNK_PROCESSED = "CHUNK_PROCESSED"
    CHUNK_COMPLETE = "CHUNK_COMPLETE"
    CURSOR_UPDATED = "CURSOR_UPDATED"

    # Issue events
    ISSUE_FOUND = "ISSUE_FOUND"
    ISSUE_FIXED = "ISSUE_FIXED"

    # Budget events
    BUDGET_WARNING = "BUDGET_WARNING"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"

    # Session events
    SESSION_START = "SESSION_START"
    SESSION_END = "SESSION_END"
    SESSION_ABORT = "SESSION_ABORT"

    # Security events
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    CRASH_DETECTED = "CRASH_DETECTED"

    # Error events
    EVENT_HANDLER_FAILURE = "EVENT_HANDLER_FAILURE"
    CURSOR_DRIFT = "CURSOR_DRIFT"
    DEADLOCK_DETECTED = "DEADLOCK_DETECTED"
    RESOURCE_WARNING = "RESOURCE_WARNING"

    # Debug events
    TOKEN_COUNT = "TOKEN_COUNT"
    LATENCY_MEASURED = "LATENCY_MEASURED"
    CACHE_HIT = "CACHE_HIT"
    CACHE_MISS = "CACHE_MISS"
    DEBUG_TRACE = "DEBUG_TRACE"
    HANDLER_CALLED = "HANDLER_CALLED"

    # v3.2.1 Module events
    INVENTORY_READY = "INVENTORY_READY"
    CROSSREF_BROKEN = "CROSSREF_BROKEN"
    ANOMALY_DETECTED = "ANOMALY_DETECTED"
    CHECKPOINT_SAVED = "CHECKPOINT_SAVED"
