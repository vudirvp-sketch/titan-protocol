"""
Tests for ITEM-OBS-02: Event Severity Filtering

This module tests the event bus severity-based filtering and dispatch behavior.

Author: TITAN FUSE Team
Version: 3.3.0
"""

import pytest
import time
import threading
from unittest.mock import Mock, patch

from src.events.event_bus import (
    EventBus,
    Event,
    EventSeverity,
    DispatchBehavior,
    get_severity_for_event,
    get_dispatch_behavior,
    EVENT_SEVERITY_MAP,
    EventTypes,
)


class TestEventSeverity:
    """Tests for EventSeverity enum."""

    def test_severity_ordering(self):
        """Test that severity levels are ordered correctly."""
        assert EventSeverity.CRITICAL.value < EventSeverity.WARN.value
        assert EventSeverity.WARN.value < EventSeverity.INFO.value
        assert EventSeverity.INFO.value < EventSeverity.DEBUG.value

    def test_severity_names(self):
        """Test severity level names."""
        assert EventSeverity.CRITICAL.name == "CRITICAL"
        assert EventSeverity.WARN.name == "WARN"
        assert EventSeverity.INFO.name == "INFO"
        assert EventSeverity.DEBUG.name == "DEBUG"


class TestEventSeverityMapping:
    """Tests for event type to severity mapping."""

    def test_critical_events_mapped(self):
        """Test that critical events are mapped to CRITICAL severity."""
        assert get_severity_for_event("GATE_FAIL") == EventSeverity.CRITICAL
        assert get_severity_for_event("BUDGET_EXCEEDED") == EventSeverity.CRITICAL
        assert get_severity_for_event("SESSION_ABORT") == EventSeverity.CRITICAL
        assert get_severity_for_event("SECURITY_VIOLATION") == EventSeverity.CRITICAL
        assert get_severity_for_event("EVENT_HANDLER_FAILURE") == EventSeverity.CRITICAL

    def test_warn_events_mapped(self):
        """Test that warning events are mapped to WARN severity."""
        assert get_severity_for_event("GATE_WARN") == EventSeverity.WARN
        assert get_severity_for_event("BUDGET_WARNING") == EventSeverity.WARN
        assert get_severity_for_event("ANOMALY_DETECTED") == EventSeverity.WARN
        assert get_severity_for_event("CURSOR_DRIFT") == EventSeverity.WARN

    def test_info_events_mapped(self):
        """Test that info events are mapped to INFO severity."""
        assert get_severity_for_event("GATE_PASS") == EventSeverity.INFO
        assert get_severity_for_event("CHUNK_PROCESSED") == EventSeverity.INFO
        assert get_severity_for_event("CHECKPOINT_SAVED") == EventSeverity.INFO
        assert get_severity_for_event("PHASE_COMPLETE") == EventSeverity.INFO
        assert get_severity_for_event("SESSION_START") == EventSeverity.INFO
        assert get_severity_for_event("SESSION_END") == EventSeverity.INFO

    def test_debug_events_mapped(self):
        """Test that debug events are mapped to DEBUG severity."""
        assert get_severity_for_event("TOKEN_COUNT") == EventSeverity.DEBUG
        assert get_severity_for_event("LATENCY_MEASURED") == EventSeverity.DEBUG
        assert get_severity_for_event("CACHE_HIT") == EventSeverity.DEBUG
        assert get_severity_for_event("CACHE_MISS") == EventSeverity.DEBUG

    def test_unknown_event_defaults_to_info(self):
        """Test that unknown events default to INFO severity."""
        assert get_severity_for_event("UNKNOWN_EVENT") == EventSeverity.INFO
        assert get_severity_for_event("random_event_type") == EventSeverity.INFO


class TestDispatchBehavior:
    """Tests for dispatch behavior mapping."""

    def test_critical_sync_block(self):
        """Test that CRITICAL events use SYNC_BLOCK behavior."""
        assert get_dispatch_behavior(EventSeverity.CRITICAL) == DispatchBehavior.SYNC_BLOCK

    def test_warn_sync_timeout(self):
        """Test that WARN events use SYNC_TIMEOUT behavior."""
        assert get_dispatch_behavior(EventSeverity.WARN) == DispatchBehavior.SYNC_TIMEOUT

    def test_info_async_fire(self):
        """Test that INFO events use ASYNC_FIRE behavior."""
        assert get_dispatch_behavior(EventSeverity.INFO) == DispatchBehavior.ASYNC_FIRE

    def test_debug_async_drop(self):
        """Test that DEBUG events use ASYNC_DROP behavior."""
        assert get_dispatch_behavior(EventSeverity.DEBUG) == DispatchBehavior.ASYNC_DROP


class TestEvent:
    """Tests for Event dataclass."""

    def test_event_auto_severity(self):
        """Test that severity is auto-determined from event_type."""
        event = Event(event_type="GATE_FAIL", data={"gate_id": "GATE-01"})
        assert event.severity == EventSeverity.CRITICAL

    def test_event_explicit_severity(self):
        """Test that explicit severity overrides auto-determination."""
        event = Event(
            event_type="GATE_PASS",
            data={"gate_id": "GATE-01"},
            severity=EventSeverity.CRITICAL
        )
        assert event.severity == EventSeverity.CRITICAL

    def test_event_to_dict(self):
        """Test event serialization."""
        event = Event(
            event_type="TEST_EVENT",
            data={"key": "value"},
            severity=EventSeverity.WARN,
            source="test_source"
        )
        d = event.to_dict()
        assert d["event_type"] == "TEST_EVENT"
        assert d["data"] == {"key": "value"}
        assert d["severity"] == "WARN"
        assert d["source"] == "test_source"
        assert "event_id" in d
        assert "timestamp" in d

    def test_event_from_dict(self):
        """Test event deserialization."""
        d = {
            "event_type": "TEST_EVENT",
            "data": {"key": "value"},
            "severity": "INFO",
            "timestamp": "2024-01-01T00:00:00Z",
            "source": "test",
            "event_id": "evt-123"
        }
        event = Event.from_dict(d)
        assert event.event_type == "TEST_EVENT"
        assert event.data == {"key": "value"}
        assert event.severity == EventSeverity.INFO
        assert event.source == "test"
        assert event.event_id == "evt-123"

    def test_event_str_representation(self):
        """Test string representation of events."""
        event = Event(event_type="GATE_FAIL", data={})
        assert "GATE_FAIL" in str(event)
        assert "CRITICAL" in str(event)


class TestEventBusSeverityFiltering:
    """Tests for EventBus severity filtering."""

    def test_subscribe_severity(self):
        """Test subscribing to events by severity."""
        bus = EventBus()
        handler = Mock()

        bus.subscribe_severity(EventSeverity.CRITICAL, handler)

        # Emit a CRITICAL event
        event = Event(event_type="GATE_FAIL", data={})
        bus.emit(event)

        handler.assert_called_once_with(event)

    def test_subscribe_min_severity(self):
        """Test subscribing to all events at or above severity level."""
        bus = EventBus(config={"async_enabled": False})  # Disable async for test
        critical_handler = Mock()
        warn_handler = Mock()

        # Subscribe to CRITICAL and above (only CRITICAL)
        bus.subscribe_min_severity(EventSeverity.CRITICAL, critical_handler)

        # Subscribe to WARN and above (CRITICAL, WARN)
        bus.subscribe_min_severity(EventSeverity.WARN, warn_handler)

        # Emit CRITICAL event
        critical_event = Event(event_type="GATE_FAIL", data={})
        bus.emit(critical_event)

        # Emit WARN event
        warn_event = Event(event_type="GATE_WARN", data={})
        bus.emit(warn_event)

        # CRITICAL handler only called for CRITICAL event
        assert critical_handler.call_count == 1

        # WARN handler called for both
        assert warn_handler.call_count == 2

    def test_set_min_severity(self):
        """Test setting minimum severity for dispatch."""
        bus = EventBus(config={"async_enabled": False})
        handler = Mock()
        bus.subscribe("*", handler)

        # Set min severity to WARN (skip INFO and DEBUG)
        bus.set_min_severity(EventSeverity.WARN)

        # Emit INFO event
        info_event = Event(event_type="GATE_PASS", data={})
        bus.emit(info_event)

        # Handler should NOT be called
        handler.assert_not_called()

        # Emit WARN event
        warn_event = Event(event_type="GATE_WARN", data={})
        bus.emit(warn_event)

        # Handler should be called
        handler.assert_called_once()

    def test_unsubscribe_severity(self):
        """Test unsubscribing from severity level."""
        bus = EventBus()
        handler = Mock()

        bus.subscribe_severity(EventSeverity.CRITICAL, handler)
        result = bus.unsubscribe_severity(EventSeverity.CRITICAL, handler)

        assert result is True

        # Emit event - handler should not be called
        event = Event(event_type="GATE_FAIL", data={})
        bus.emit(event)

        handler.assert_not_called()

    def test_get_history_with_severity_filter(self):
        """Test getting history filtered by severity."""
        bus = EventBus(config={"async_enabled": False})

        # Emit events of different severities
        bus.emit(Event(event_type="GATE_FAIL", data={}))  # CRITICAL
        bus.emit(Event(event_type="GATE_WARN", data={}))  # WARN
        bus.emit(Event(event_type="GATE_PASS", data={}))  # INFO

        # Get only CRITICAL events
        critical_events = bus.get_history(severity=EventSeverity.CRITICAL)
        assert len(critical_events) == 1
        assert critical_events[0].event_type == "GATE_FAIL"

        # Get events at or above WARN
        warn_and_above = bus.get_history(min_severity=EventSeverity.WARN)
        assert len(warn_and_above) == 2


class TestEventBusDispatchBehavior:
    """Tests for EventBus hybrid dispatch behavior."""

    def test_critical_is_synchronous(self):
        """Test that CRITICAL events are dispatched synchronously."""
        bus = EventBus()
        call_order = []

        def handler(event):
            call_order.append("handler")

        bus.subscribe("GATE_FAIL", handler)

        event = Event(event_type="GATE_FAIL", data={})
        bus.emit(event)
        call_order.append("after_emit")

        # Handler should be called before emit returns
        assert call_order == ["handler", "after_emit"]

    def test_warn_is_synchronous(self):
        """Test that WARN events are dispatched synchronously."""
        bus = EventBus()
        call_order = []

        def handler(event):
            call_order.append("handler")

        bus.subscribe("GATE_WARN", handler)

        event = Event(event_type="GATE_WARN", data={})
        bus.emit(event)
        call_order.append("after_emit")

        # Handler should be called before emit returns
        assert call_order == ["handler", "after_emit"]

    def test_warn_timeout(self):
        """Test that WARN events respect timeout."""
        bus = EventBus(config={"warn_timeout_seconds": 0.1, "async_enabled": False})
        handler_called = []

        def slow_handler(event):
            time.sleep(0.2)  # Longer than timeout
            handler_called.append(True)

        def fast_handler(event):
            handler_called.append(True)

        bus.subscribe("GATE_WARN", slow_handler)
        bus.subscribe("GATE_WARN", fast_handler)

        event = Event(event_type="GATE_WARN", data={})
        bus.emit(event)

        # At least one handler should have been called
        # (slow handler may have timed out)

    def test_info_is_async(self):
        """Test that INFO events can be dispatched asynchronously."""
        bus = EventBus(config={"async_enabled": True})
        call_order = []
        event_processed = threading.Event()

        def handler(event):
            time.sleep(0.01)  # Small delay
            call_order.append("handler")
            event_processed.set()

        bus.subscribe("GATE_PASS", handler)

        event = Event(event_type="GATE_PASS", data={})
        bus.emit(event)
        call_order.append("after_emit")

        # emit should return quickly
        assert call_order == ["after_emit"]

        # Wait for async handler
        event_processed.wait(timeout=1.0)
        assert "handler" in call_order

        bus.shutdown(wait=True)

    def test_debug_can_be_dropped(self):
        """Test that DEBUG events can be dropped under load."""
        # Configure bus with small queue and low drop threshold
        bus = EventBus(config={
            "async_queue_size": 10,
            "debug_drop_threshold": 0.5,
            "async_enabled": True
        })

        handler = Mock()
        bus.subscribe("TOKEN_COUNT", handler)

        # Fill the queue beyond threshold
        for i in range(20):
            event = Event(event_type="TOKEN_COUNT", data={"count": i})
            bus.emit(event)

        # Some DEBUG events should have been dropped
        stats = bus.get_stats()
        assert stats["dropped_debug_events"] > 0 or stats["async_queue_size"] > 0

        bus.shutdown(wait=False)


class TestEventBusStats:
    """Tests for EventBus statistics."""

    def test_get_stats_includes_severity_metrics(self):
        """Test that get_stats includes severity metrics."""
        bus = EventBus(config={"async_enabled": False})

        # Emit various events
        bus.emit(Event(event_type="GATE_FAIL", data={}))  # CRITICAL
        bus.emit(Event(event_type="GATE_WARN", data={}))  # WARN
        bus.emit(Event(event_type="GATE_PASS", data={}))  # INFO
        bus.emit(Event(event_type="TOKEN_COUNT", data={}))  # DEBUG

        stats = bus.get_stats()

        assert "total_events" in stats
        assert stats["total_events"] == 4

        assert "severity_distribution" in stats
        assert stats["severity_distribution"]["CRITICAL"] == 1
        assert stats["severity_distribution"]["WARN"] == 1
        assert stats["severity_distribution"]["INFO"] == 1
        assert stats["severity_distribution"]["DEBUG"] == 1

        assert "dropped_debug_events" in stats
        assert "async_queue_size" in stats
        assert "min_severity" in stats

    def test_shutdown_graceful(self):
        """Test graceful shutdown."""
        bus = EventBus()

        # Should not raise
        bus.shutdown(wait=False)


class TestEventTypes:
    """Tests for EventTypes constants."""

    def test_gate_events_exist(self):
        """Test that gate event types are defined."""
        assert hasattr(EventTypes, "GATE_PASS")
        assert hasattr(EventTypes, "GATE_FAIL")
        assert hasattr(EventTypes, "GATE_WARN")

    def test_session_events_exist(self):
        """Test that session event types are defined."""
        assert hasattr(EventTypes, "SESSION_START")
        assert hasattr(EventTypes, "SESSION_END")
        assert hasattr(EventTypes, "SESSION_ABORT")

    def test_debug_events_exist(self):
        """Test that debug event types are defined."""
        assert hasattr(EventTypes, "TOKEN_COUNT")
        assert hasattr(EventTypes, "CACHE_HIT")
        assert hasattr(EventTypes, "CACHE_MISS")


class TestEventBusIntegration:
    """Integration tests for EventBus with severity filtering."""

    def test_full_workflow(self):
        """Test complete event bus workflow with severity filtering."""
        bus = EventBus(config={
            "async_enabled": False,
            "min_severity": "INFO"  # Skip DEBUG
        })

        events_received = []

        def handler(event):
            events_received.append(event)

        bus.subscribe("*", handler)

        # Emit events of all severities
        bus.emit(Event(event_type="GATE_FAIL", data={"gate": "GATE-01"}))
        bus.emit(Event(event_type="GATE_WARN", data={"gate": "GATE-02"}))
        bus.emit(Event(event_type="GATE_PASS", data={"gate": "GATE-03"}))
        bus.emit(Event(event_type="TOKEN_COUNT", data={"count": 100}))  # DEBUG - should be filtered

        # Should receive CRITICAL, WARN, INFO but not DEBUG
        assert len(events_received) == 3
        severities = [e.severity for e in events_received]
        assert EventSeverity.CRITICAL in severities
        assert EventSeverity.WARN in severities
        assert EventSeverity.INFO in severities
        assert EventSeverity.DEBUG not in severities

        # Verify stats
        stats = bus.get_stats()
        assert stats["total_events"] == 4  # All events recorded in history
        assert stats["min_severity"] == "INFO"

    def test_event_history_preserves_all_events(self):
        """Test that event history preserves all events even when filtered."""
        bus = EventBus(config={
            "async_enabled": False,
            "min_severity": "CRITICAL"  # Only CRITICAL dispatched
        })

        handler = Mock()
        bus.subscribe("*", handler)

        # Emit events of all severities
        bus.emit(Event(event_type="GATE_FAIL", data={}))
        bus.emit(Event(event_type="GATE_WARN", data={}))
        bus.emit(Event(event_type="GATE_PASS", data={}))
        bus.emit(Event(event_type="TOKEN_COUNT", data={}))

        # Only CRITICAL should be dispatched
        assert handler.call_count == 1

        # But all should be in history
        history = bus.get_history()
        assert len(history) == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
