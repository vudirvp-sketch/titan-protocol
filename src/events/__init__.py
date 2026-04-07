# TITAN FUSE Protocol - Events Module
"""
Event bus for event-driven architecture.

ITEM-RESILIENCE-01: Dead Letter Queue for failed event handling.
"""

from .event_bus import EventBus, Event, EventSeverity, EventTypes, SyncResult
from .dead_letter_queue import (
    DeadLetterQueue,
    FailedEvent,
    RetryPolicy,
    RetryResult,
    DLQStats
)

__all__ = [
    # Event Bus
    'EventBus',
    'Event',
    'EventSeverity',
    'EventTypes',
    # ITEM-RESILIENCE-02: Sync operations
    'SyncResult',
    # Dead Letter Queue (ITEM-RESILIENCE-01)
    'DeadLetterQueue',
    'FailedEvent',
    'RetryPolicy',
    'RetryResult',
    'DLQStats'
]
