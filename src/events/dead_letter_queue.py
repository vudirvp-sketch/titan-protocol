"""
Dead Letter Queue (DLQ) for TITAN FUSE Protocol.

ITEM-RESILIENCE-01: Dead Letter Queue Implementation

Provides resilient event handling with:
- Persistent storage of failed events
- Configurable retry policies with exponential backoff
- Event severity-based categorization
- Queue statistics and monitoring

Features:
- FailedEvent capture with full context
- RetryPolicy with exponential backoff
- DLQStats for monitoring
- Integration with StorageBackend for persistence
- Automatic loading of pending events on startup

Author: TITAN FUSE Team
Version: 3.4.0
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, TYPE_CHECKING
import logging
import traceback
import uuid
import json

from .event_bus import Event, EventSeverity

if TYPE_CHECKING:
    from ..storage.backend import StorageBackend


@dataclass
class RetryPolicy:
    """
    Policy for retrying failed events.

    Attributes:
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay_ms: Base delay between retries in milliseconds (default: 1000)
        exponential_backoff: Whether to use exponential backoff (default: True)
    """
    max_retries: int = 3
    base_delay_ms: int = 1000
    exponential_backoff: bool = True

    def get_delay_ms(self, retry_count: int) -> int:
        """
        Calculate delay for a given retry attempt.

        Args:
            retry_count: Current retry attempt number (0-indexed)

        Returns:
            Delay in milliseconds
        """
        if not self.exponential_backoff:
            return self.base_delay_ms

        # Exponential backoff: base_delay * 2^retry_count
        delay = self.base_delay_ms * (2 ** retry_count)
        return min(delay, 60000)  # Cap at 60 seconds

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "max_retries": self.max_retries,
            "base_delay_ms": self.base_delay_ms,
            "exponential_backoff": self.exponential_backoff
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RetryPolicy':
        """Create from dictionary."""
        return cls(
            max_retries=data.get("max_retries", 3),
            base_delay_ms=data.get("base_delay_ms", 1000),
            exponential_backoff=data.get("exponential_backoff", True)
        )


@dataclass
class RetryResult:
    """
    Result of a retry attempt.

    Attributes:
        success: Whether the retry was successful
        event_id: ID of the event that was retried
        error_message: Error message if retry failed (None if successful)
    """
    success: bool
    event_id: str
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "event_id": self.event_id,
            "error_message": self.error_message
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RetryResult':
        """Create from dictionary."""
        return cls(
            success=data["success"],
            event_id=data["event_id"],
            error_message=data.get("error_message")
        )


@dataclass
class DLQStats:
    """
    Statistics for the Dead Letter Queue.

    Attributes:
        total_events: Total number of events in the queue
        pending_retry: Number of events pending retry
        permanently_failed: Number of events that exceeded max retries
        by_severity: Count of events by severity level
        oldest_event_age_hours: Age of the oldest event in hours
        total_retries: Total number of retry attempts made
        successful_retries: Number of successful retries
    """
    total_events: int = 0
    pending_retry: int = 0
    permanently_failed: int = 0
    by_severity: Dict[str, int] = field(default_factory=dict)
    oldest_event_age_hours: Optional[float] = None
    total_retries: int = 0
    successful_retries: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_events": self.total_events,
            "pending_retry": self.pending_retry,
            "permanently_failed": self.permanently_failed,
            "by_severity": self.by_severity,
            "oldest_event_age_hours": self.oldest_event_age_hours,
            "total_retries": self.total_retries,
            "successful_retries": self.successful_retries
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DLQStats':
        """Create from dictionary."""
        return cls(
            total_events=data.get("total_events", 0),
            pending_retry=data.get("pending_retry", 0),
            permanently_failed=data.get("permanently_failed", 0),
            by_severity=data.get("by_severity", {}),
            oldest_event_age_hours=data.get("oldest_event_age_hours"),
            total_retries=data.get("total_retries", 0),
            successful_retries=data.get("successful_retries", 0)
        )


@dataclass
class FailedEvent:
    """
    Represents an event that failed processing.

    ITEM-RESILIENCE-01: Captures all context needed for retry or analysis.

    Attributes:
        event_id: Unique identifier for this failed event
        original_event: The original Event that failed
        error_type: Type of the exception that caused the failure
        error_message: Human-readable error message
        traceback: Full stack trace of the error
        retry_count: Number of retry attempts made so far
        max_retries: Maximum retries allowed
        first_failed_at: ISO timestamp when first failure occurred
        last_failed_at: ISO timestamp of most recent failure
        context: Additional context about the failure
    """
    event_id: str
    original_event: Event
    error_type: str
    error_message: str
    traceback: str
    retry_count: int
    max_retries: int
    first_failed_at: str
    last_failed_at: str
    context: Dict[str, Any] = field(default_factory=dict)

    def can_retry(self) -> bool:
        """
        Check if this event can be retried.

        Returns:
            True if retry_count < max_retries
        """
        return self.retry_count < self.max_retries

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns:
            Dictionary representation suitable for JSON storage
        """
        return {
            "event_id": self.event_id,
            "original_event": self.original_event.to_dict(),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "traceback": self.traceback,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "first_failed_at": self.first_failed_at,
            "last_failed_at": self.last_failed_at,
            "context": self.context
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FailedEvent':
        """
        Create FailedEvent from dictionary.

        Args:
            data: Dictionary containing FailedEvent data

        Returns:
            FailedEvent instance
        """
        original_event = Event.from_dict(data["original_event"])
        return cls(
            event_id=data["event_id"],
            original_event=original_event,
            error_type=data["error_type"],
            error_message=data["error_message"],
            traceback=data["traceback"],
            retry_count=data["retry_count"],
            max_retries=data["max_retries"],
            first_failed_at=data["first_failed_at"],
            last_failed_at=data["last_failed_at"],
            context=data.get("context", {})
        )


class DeadLetterQueue:
    """
    Dead Letter Queue for managing failed events.

    ITEM-RESILIENCE-01: Provides resilient event handling with:
    - Persistent storage of failed events
    - Configurable retry policies
    - Event severity-based categorization
    - Queue statistics and monitoring

    The DLQ stores events that failed processing, allowing for:
    - Manual inspection and retry
    - Automatic retry with backoff
    - Purging of old failed events
    - Monitoring via statistics

    Usage:
        dlq = DeadLetterQueue(storage_backend=local_storage)
        event_id = dlq.enqueue(event, error, {"handler": "process_chunk"})

        # Later, retry the event
        result = dlq.retry(event_id)
        if result.success:
            print("Event retried successfully")
    """

    DLQ_PREFIX = "dlq"
    EVENTS_PATH = "events"
    STATS_PATH = "stats.json"

    def __init__(
        self,
        storage_backend: 'StorageBackend',
        retry_policy: Optional[RetryPolicy] = None,
        session_id: Optional[str] = None
    ):
        """
        Initialize the Dead Letter Queue.

        Args:
            storage_backend: StorageBackend instance for persistence
            retry_policy: Optional retry policy (default: RetryPolicy())
            session_id: Optional session ID for namespace isolation
        """
        self._storage = storage_backend
        self._retry_policy = retry_policy or RetryPolicy()
        self._session_id = session_id or "default"
        self._logger = logging.getLogger(__name__)

        # In-memory cache of failed events
        self._failed_events: Dict[str, FailedEvent] = {}

        # Statistics tracking
        self._total_retries = 0
        self._successful_retries = 0

        # Load pending events on startup
        self._load_pending()

    def _get_event_path(self, event_id: str) -> str:
        """Get storage path for an event."""
        return f"{self.DLQ_PREFIX}/{self._session_id}/{self.EVENTS_PATH}/{event_id}.json"

    def _get_stats_path(self) -> str:
        """Get storage path for statistics."""
        return f"{self.DLQ_PREFIX}/{self._session_id}/{self.STATS_PATH}"

    def enqueue(
        self,
        event: Event,
        error: Exception,
        context: Dict[str, Any]
    ) -> str:
        """
        Add a failed event to the Dead Letter Queue.

        Args:
            event: The original Event that failed
            error: The exception that caused the failure
            context: Additional context about the failure

        Returns:
            The event_id of the enqueued failed event
        """
        now = datetime.utcnow().isoformat() + "Z"

        failed_event = FailedEvent(
            event_id=f"dlq-{uuid.uuid4().hex[:12]}",
            original_event=event,
            error_type=type(error).__name__,
            error_message=str(error),
            traceback=traceback.format_exc(),
            retry_count=0,
            max_retries=self._retry_policy.max_retries,
            first_failed_at=now,
            last_failed_at=now,
            context=context
        )

        # Store in memory
        self._failed_events[failed_event.event_id] = failed_event

        # Persist to storage
        self._persist_event(failed_event)

        self._logger.warning(
            f"[DLQ] Enqueued failed event: {failed_event.event_id} "
            f"(type={event.event_type}, error={failed_event.error_type})"
        )

        return failed_event.event_id

    def dequeue(self, event_id: str) -> Optional[FailedEvent]:
        """
        Remove and return a failed event from the queue.

        Args:
            event_id: ID of the event to dequeue

        Returns:
            The FailedEvent if found, None otherwise
        """
        failed_event = self._failed_events.pop(event_id, None)
        if failed_event:
            # Delete from storage
            try:
                event_path = self._get_event_path(event_id)
                self._storage.delete(event_path)
                self._logger.info(f"[DLQ] Dequeued event: {event_id}")
            except Exception as e:
                self._logger.error(f"[DLQ] Failed to delete event from storage: {e}")
            return failed_event
        return None

    def retry(self, event_id: str) -> RetryResult:
        """
        Attempt to retry a failed event.

        This method increments the retry count and updates the last_failed_at
        timestamp. The actual retry logic (re-processing) should be handled
        by the caller based on the returned FailedEvent.

        Args:
            event_id: ID of the event to retry

        Returns:
            RetryResult indicating success or failure
        """
        failed_event = self._failed_events.get(event_id)
        if not failed_event:
            return RetryResult(
                success=False,
                event_id=event_id,
                error_message=f"Event {event_id} not found in DLQ"
            )

        if not failed_event.can_retry():
            return RetryResult(
                success=False,
                event_id=event_id,
                error_message=f"Event {event_id} exceeded max retries ({failed_event.max_retries})"
            )

        # Increment retry count
        failed_event.retry_count += 1
        failed_event.last_failed_at = datetime.utcnow().isoformat() + "Z"

        # Update in storage
        self._persist_event(failed_event)

        self._total_retries += 1

        self._logger.info(
            f"[DLQ] Retry attempt {failed_event.retry_count}/{failed_event.max_retries} "
            f"for event: {event_id}"
        )

        return RetryResult(
            success=True,
            event_id=event_id
        )

    def mark_retry_success(self, event_id: str) -> bool:
        """
        Mark a retry as successful and remove the event from DLQ.

        Args:
            event_id: ID of the event that was successfully retried

        Returns:
            True if the event was found and removed
        """
        if event_id in self._failed_events:
            self.dequeue(event_id)
            self._successful_retries += 1
            self._logger.info(f"[DLQ] Retry successful for event: {event_id}")
            return True
        return False

    def get_failed_events(
        self,
        severity: Optional[EventSeverity] = None
    ) -> List[FailedEvent]:
        """
        Get failed events, optionally filtered by severity.

        Args:
            severity: Optional EventSeverity to filter by

        Returns:
            List of FailedEvent objects
        """
        events = list(self._failed_events.values())

        if severity:
            events = [
                e for e in events
                if e.original_event.severity == severity
            ]

        # Sort by first_failed_at (oldest first)
        events.sort(key=lambda e: e.first_failed_at)

        return events

    def get_event(self, event_id: str) -> Optional[FailedEvent]:
        """
        Get a specific failed event by ID.

        Args:
            event_id: ID of the event to retrieve

        Returns:
            FailedEvent if found, None otherwise
        """
        return self._failed_events.get(event_id)

    def purge(self, max_age_hours: int = 24) -> int:
        """
        Remove old failed events from the queue.

        Args:
            max_age_hours: Maximum age in hours for events to keep

        Returns:
            Number of events purged
        """
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        cutoff_str = cutoff.isoformat() + "Z"

        to_purge = [
            event_id for event_id, event in self._failed_events.items()
            if event.last_failed_at < cutoff_str
        ]

        for event_id in to_purge:
            self.dequeue(event_id)

        if to_purge:
            self._logger.info(f"[DLQ] Purged {len(to_purge)} events older than {max_age_hours} hours")

        return len(to_purge)

    def get_stats(self) -> DLQStats:
        """
        Get statistics about the Dead Letter Queue.

        Returns:
            DLQStats with current queue statistics
        """
        events = list(self._failed_events.values())

        # Count by severity
        by_severity: Dict[str, int] = {}
        for event in events:
            sev_name = event.original_event.severity.name
            by_severity[sev_name] = by_severity.get(sev_name, 0) + 1

        # Find oldest event
        oldest_age_hours: Optional[float] = None
        if events:
            oldest = min(events, key=lambda e: e.first_failed_at)
            oldest_time = datetime.fromisoformat(oldest.first_failed_at.rstrip('Z'))
            oldest_age_hours = (datetime.utcnow() - oldest_time).total_seconds() / 3600

        # Count pending vs permanently failed
        pending = sum(1 for e in events if e.can_retry())
        permanently = len(events) - pending

        return DLQStats(
            total_events=len(events),
            pending_retry=pending,
            permanently_failed=permanently,
            by_severity=by_severity,
            oldest_event_age_hours=oldest_age_hours,
            total_retries=self._total_retries,
            successful_retries=self._successful_retries
        )

    def _persist_event(self, failed_event: FailedEvent) -> None:
        """
        Persist a failed event to storage.

        Args:
            failed_event: FailedEvent to persist
        """
        try:
            event_path = self._get_event_path(failed_event.event_id)
            self._storage.save_json(event_path, failed_event.to_dict())
        except Exception as e:
            self._logger.error(
                f"[DLQ] Failed to persist event {failed_event.event_id}: {e}"
            )

    def _load_pending(self) -> List[FailedEvent]:
        """
        Load pending failed events from storage on startup.

        Returns:
            List of loaded FailedEvent objects
        """
        events_path = f"{self.DLQ_PREFIX}/{self._session_id}/{self.EVENTS_PATH}/"

        try:
            event_files = self._storage.list(events_path)
            loaded_count = 0

            for event_file in event_files:
                if not event_file.endswith('.json'):
                    continue

                try:
                    data = self._storage.load_json(event_file)
                    failed_event = FailedEvent.from_dict(data)
                    self._failed_events[failed_event.event_id] = failed_event
                    loaded_count += 1
                except Exception as e:
                    self._logger.error(f"[DLQ] Failed to load event {event_file}: {e}")

            if loaded_count > 0:
                self._logger.info(f"[DLQ] Loaded {loaded_count} pending events from storage")

        except Exception as e:
            self._logger.debug(f"[DLQ] No existing DLQ events found or error loading: {e}")

        return list(self._failed_events.values())

    def clear(self) -> int:
        """
        Remove all events from the Dead Letter Queue.

        Returns:
            Number of events cleared
        """
        count = len(self._failed_events)
        event_ids = list(self._failed_events.keys())

        for event_id in event_ids:
            self.dequeue(event_id)

        self._logger.info(f"[DLQ] Cleared {count} events from queue")
        return count

    def __len__(self) -> int:
        """Return number of events in the queue."""
        return len(self._failed_events)

    def __contains__(self, event_id: str) -> bool:
        """Check if an event is in the queue."""
        return event_id in self._failed_events
