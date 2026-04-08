"""
Tests for ITEM-INT-144: Event Sourcing Manager

This module tests the EventSourcingManager class which enables
state reconstruction from event history.

Author: TITAN FUSE Team
Version: 1.0.0
"""

import pytest
import tempfile
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from src.state.event_sourcing import (
    EventSourcingManager,
    StateSnapshot,
    ReconstructedState,
    STATE_CHANGING_EVENTS,
)
from src.events.event_bus import Event, EventBus, EventSeverity


class TestStateSnapshot:
    """Tests for StateSnapshot dataclass."""

    def test_create_snapshot(self):
        """Test creating a state snapshot."""
        state = {"gates": {"GATE-00": {"status": "PASS"}}}
        snapshot = StateSnapshot(
            snapshot_id="snap-001",
            event_id="evt-001",
            timestamp="2024-01-15T12:00:00.000Z",
            state=state,
            event_count=10,
        )
        
        assert snapshot.snapshot_id == "snap-001"
        assert snapshot.event_id == "evt-001"
        assert snapshot.state == state
        assert snapshot.event_count == 10
        assert snapshot.checksum  # Should be computed

    def test_snapshot_checksum(self):
        """Test that checksum is computed correctly."""
        state1 = {"key": "value1"}
        state2 = {"key": "value2"}
        
        snapshot1 = StateSnapshot(
            snapshot_id="snap-001",
            event_id="evt-001",
            timestamp="2024-01-15T12:00:00.000Z",
            state=state1,
            event_count=1,
        )
        
        snapshot2 = StateSnapshot(
            snapshot_id="snap-002",
            event_id="evt-002",
            timestamp="2024-01-15T12:00:00.000Z",
            state=state2,
            event_count=1,
        )
        
        # Different states should have different checksums
        assert snapshot1.checksum != snapshot2.checksum

    def test_snapshot_to_dict(self):
        """Test snapshot serialization."""
        state = {"test": "data"}
        snapshot = StateSnapshot(
            snapshot_id="snap-001",
            event_id="evt-001",
            timestamp="2024-01-15T12:00:00.000Z",
            state=state,
            event_count=5,
        )
        
        d = snapshot.to_dict()
        
        assert d["snapshot_id"] == "snap-001"
        assert d["event_id"] == "evt-001"
        assert d["state"] == state
        assert d["event_count"] == 5
        assert "checksum" in d

    def test_snapshot_from_dict(self):
        """Test snapshot deserialization."""
        d = {
            "snapshot_id": "snap-001",
            "event_id": "evt-001",
            "timestamp": "2024-01-15T12:00:00.000Z",
            "state": {"key": "value"},
            "event_count": 5,
            "checksum": "abc123",
        }
        
        snapshot = StateSnapshot.from_dict(d)
        
        assert snapshot.snapshot_id == "snap-001"
        assert snapshot.event_id == "evt-001"
        assert snapshot.state == {"key": "value"}
        assert snapshot.event_count == 5


class TestReconstructedState:
    """Tests for ReconstructedState dataclass."""

    def test_create_reconstructed_state(self):
        """Test creating a reconstructed state result."""
        state = {"gates": {"GATE-00": {"status": "PASS"}}}
        result = ReconstructedState(
            state=state,
            last_event_id="evt-010",
            last_event_timestamp="2024-01-15T12:30:00.000Z",
            events_applied=10,
            from_snapshot=True,
            snapshot_id="snap-005",
            reconstruction_time_ms=15,
        )
        
        assert result.state == state
        assert result.last_event_id == "evt-010"
        assert result.events_applied == 10
        assert result.from_snapshot is True
        assert result.reconstruction_time_ms == 15

    def test_reconstructed_state_to_dict(self):
        """Test reconstructed state serialization."""
        result = ReconstructedState(
            state={"test": "data"},
            events_applied=5,
        )
        
        d = result.to_dict()
        
        assert d["state"] == {"test": "data"}
        assert d["events_applied"] == 5
        assert d["from_snapshot"] is False


class TestEventSourcingManager:
    """Tests for EventSourcingManager class."""

    def test_init(self):
        """Test initialization."""
        manager = EventSourcingManager()
        
        assert manager._snapshot_interval == 100
        assert len(manager._events) == 0
        assert len(manager._snapshots) == 0

    def test_init_with_custom_snapshot_interval(self):
        """Test initialization with custom snapshot interval."""
        manager = EventSourcingManager(snapshot_interval=50)
        
        assert manager._snapshot_interval == 50

    def test_record_event(self):
        """Test recording an event."""
        manager = EventSourcingManager()
        event = Event("GATE_PASS", {"gate_id": "GATE-00"})
        
        manager.record_event(event)
        
        assert len(manager._events) == 1
        assert event.event_id in manager._event_index

    def test_record_event_duplicate(self):
        """Test that duplicate events are not recorded twice."""
        manager = EventSourcingManager()
        event = Event("GATE_PASS", {"gate_id": "GATE-00"})
        
        manager.record_event(event)
        manager.record_event(event)
        
        assert len(manager._events) == 1

    def test_record_event_indexes_gate(self):
        """Test that events are indexed by gate_id."""
        manager = EventSourcingManager()
        event = Event("GATE_PASS", {"gate_id": "GATE-00"})
        
        manager.record_event(event)
        
        assert "GATE-00" in manager._gate_events
        assert event.event_id in manager._gate_events["GATE-00"]

    def test_get_initial_state(self):
        """Test initial state structure."""
        manager = EventSourcingManager()
        state = manager._get_initial_state()
        
        assert "gates" in state
        assert "phases" in state
        assert "chunks" in state
        assert "session" in state
        assert "budget" in state
        
        # Check initial gate states
        for gate_id in ["GATE-00", "GATE-01", "GATE-02", "GATE-03", "GATE-04", "GATE-05"]:
            assert gate_id in state["gates"]
            assert state["gates"][gate_id]["status"] == "PENDING"

    def test_reconstruct_state_empty(self):
        """Test reconstructing state with no events."""
        manager = EventSourcingManager()
        
        result = manager.reconstruct_state()
        
        assert result.state["gates"]["GATE-00"]["status"] == "PENDING"
        assert result.events_applied == 0

    def test_reconstruct_state_single_event(self):
        """Test reconstructing state with a single event."""
        manager = EventSourcingManager()
        event = Event("GATE_PASS", {"gate_id": "GATE-00"})
        manager.record_event(event)
        
        result = manager.reconstruct_state(event.event_id)
        
        assert result.state["gates"]["GATE-00"]["status"] == "PASS"
        assert result.last_event_id == event.event_id
        assert result.events_applied == 1

    def test_reconstruct_state_multiple_events(self):
        """Test reconstructing state with multiple events."""
        manager = EventSourcingManager()
        
        # Record a series of events
        manager.record_event(Event("GATE_PASS", {"gate_id": "GATE-00"}))
        manager.record_event(Event("GATE_PASS", {"gate_id": "GATE-01"}))
        manager.record_event(Event("GATE_FAIL", {"gate_id": "GATE-02", "reason": "Test failure"}))
        
        result = manager.reconstruct_state()
        
        assert result.state["gates"]["GATE-00"]["status"] == "PASS"
        assert result.state["gates"]["GATE-01"]["status"] == "PASS"
        assert result.state["gates"]["GATE-02"]["status"] == "FAIL"
        assert result.events_applied == 3

    def test_reconstruct_state_up_to_event(self):
        """Test reconstructing state up to a specific event."""
        manager = EventSourcingManager()
        
        event1 = Event("GATE_PASS", {"gate_id": "GATE-00"})
        event2 = Event("GATE_PASS", {"gate_id": "GATE-01"})
        event3 = Event("GATE_FAIL", {"gate_id": "GATE-02", "reason": "Test"})
        
        manager.record_event(event1)
        manager.record_event(event2)
        manager.record_event(event3)
        
        # Reconstruct up to event2
        result = manager.reconstruct_state(event2.event_id)
        
        assert result.state["gates"]["GATE-00"]["status"] == "PASS"
        assert result.state["gates"]["GATE-01"]["status"] == "PASS"
        assert result.state["gates"]["GATE-02"]["status"] == "PENDING"  # Not yet failed

    def test_reconstruct_state_phases(self):
        """Test reconstructing state with phase events."""
        manager = EventSourcingManager()
        
        manager.record_event(Event("PHASE_START", {"phase": 1}))
        manager.record_event(Event("PHASE_COMPLETE", {"phase": 1}))
        manager.record_event(Event("PHASE_START", {"phase": 2}))
        
        result = manager.reconstruct_state()
        
        assert result.state["phases"]["current_phase"] == 2
        assert 1 in result.state["phases"]["completed_phases"]

    def test_reconstruct_state_chunks(self):
        """Test reconstructing state with chunk events."""
        manager = EventSourcingManager()
        
        manager.record_event(Event("CHUNK_PROCESSED", {"chunk_id": "chunk-1", "chunks_completed": 1}))
        manager.record_event(Event("CHUNK_PROCESSED", {"chunk_id": "chunk-2", "chunks_completed": 2}))
        manager.record_event(Event("CHUNK_COMPLETE", {"chunks_total": 2, "chunks_completed": 2}))
        
        result = manager.reconstruct_state()
        
        assert result.state["chunks"]["total"] == 2
        assert result.state["chunks"]["completed"] == 2
        assert "chunk-1" in result.state["chunks"]["processed"]
        assert "chunk-2" in result.state["chunks"]["processed"]

    def test_reconstruct_state_session(self):
        """Test reconstructing state with session events."""
        manager = EventSourcingManager()
        
        manager.record_event(Event("SESSION_START", {"session_id": "session-123"}))
        manager.record_event(Event("SESSION_END", {"reason": "Complete"}))
        
        result = manager.reconstruct_state()
        
        assert result.state["session"]["status"] == "COMPLETE"
        assert result.state["session"]["session_id"] == "session-123"

    def test_reconstruct_state_budget(self):
        """Test reconstructing state with budget events."""
        manager = EventSourcingManager()
        
        manager.record_event(Event("BUDGET_WARNING", {"message": "Approaching limit"}))
        manager.record_event(Event("BUDGET_EXCEEDED", {"tokens_used": 100000}))
        
        result = manager.reconstruct_state()
        
        assert result.state["budget"]["exceeded"] is True
        assert result.state["budget"]["warnings"] == 1

    def test_reconstruct_state_issues(self):
        """Test reconstructing state with issue events."""
        manager = EventSourcingManager()
        
        manager.record_event(Event("ISSUE_FOUND", {"issue_id": "issue-1"}))
        manager.record_event(Event("ISSUE_FOUND", {"issue_id": "issue-2"}))
        manager.record_event(Event("ISSUE_FIXED", {"issue_id": "issue-1"}))
        
        result = manager.reconstruct_state()
        
        assert result.state["issues"]["found"] == 2
        assert result.state["issues"]["fixed"] == 1
        assert "issue-2" in result.state["issues"]["open"]
        assert "issue-1" not in result.state["issues"]["open"]

    def test_get_event_history(self):
        """Test getting event history."""
        manager = EventSourcingManager()
        
        manager.record_event(Event("GATE_PASS", {"gate_id": "GATE-00"}))
        manager.record_event(Event("GATE_WARN", {"gate_id": "GATE-01"}))
        manager.record_event(Event("GATE_FAIL", {"gate_id": "GATE-02"}))
        
        history = manager.get_event_history()
        
        assert len(history) == 3

    def test_get_event_history_filtered_by_type(self):
        """Test getting event history filtered by type."""
        manager = EventSourcingManager()
        
        manager.record_event(Event("GATE_PASS", {"gate_id": "GATE-00"}))
        manager.record_event(Event("GATE_WARN", {"gate_id": "GATE-01"}))
        manager.record_event(Event("GATE_FAIL", {"gate_id": "GATE-02"}))
        
        history = manager.get_event_history(event_types=["GATE_PASS", "GATE_FAIL"])
        
        assert len(history) == 2
        event_types = [e.event_type for e in history]
        assert "GATE_PASS" in event_types
        assert "GATE_FAIL" in event_types
        assert "GATE_WARN" not in event_types

    def test_get_event_history_filtered_by_gate(self):
        """Test getting event history filtered by gate."""
        manager = EventSourcingManager()
        
        manager.record_event(Event("GATE_PASS", {"gate_id": "GATE-00"}))
        manager.record_event(Event("GATE_WARN", {"gate_id": "GATE-01"}))
        manager.record_event(Event("GATE_FAIL", {"gate_id": "GATE-02"}))
        
        history = manager.get_event_history(gate_id="GATE-01")
        
        assert len(history) == 1
        assert history[0].data["gate_id"] == "GATE-01"

    def test_get_event_history_with_limit(self):
        """Test getting event history with limit."""
        manager = EventSourcingManager()
        
        for i in range(10):
            manager.record_event(Event("GATE_PASS", {"gate_id": f"GATE-0{i}"}))
        
        history = manager.get_event_history(limit=5)
        
        assert len(history) == 5

    def test_get_events_for_gate(self):
        """Test getting events for a specific gate."""
        manager = EventSourcingManager()
        
        manager.record_event(Event("GATE_PASS", {"gate_id": "GATE-00"}))
        manager.record_event(Event("GATE_WARN", {"gate_id": "GATE-00"}))
        manager.record_event(Event("GATE_FAIL", {"gate_id": "GATE-01"}))
        
        events = manager.get_events_for_gate("GATE-00")
        
        assert len(events) == 2
        for event in events:
            assert event.data["gate_id"] == "GATE-00"

    def test_get_state_at_timestamp(self):
        """Test getting state at a specific timestamp."""
        manager = EventSourcingManager()
        
        # Record events with specific timestamps
        event1 = Event("GATE_PASS", {"gate_id": "GATE-00"})
        event1.timestamp = "2024-01-15T10:00:00.000Z"
        manager.record_event(event1)
        
        event2 = Event("GATE_PASS", {"gate_id": "GATE-01"})
        event2.timestamp = "2024-01-15T11:00:00.000Z"
        manager.record_event(event2)
        
        event3 = Event("GATE_FAIL", {"gate_id": "GATE-02"})
        event3.timestamp = "2024-01-15T12:00:00.000Z"
        manager.record_event(event3)
        
        # Get state at 10:30
        ts = datetime(2024, 1, 15, 10, 30, 0)
        result = manager.get_state_at(ts)
        
        assert result.state["gates"]["GATE-00"]["status"] == "PASS"
        assert result.state["gates"]["GATE-01"]["status"] == "PENDING"  # Not yet passed

    def test_create_snapshot(self):
        """Test creating a snapshot."""
        manager = EventSourcingManager()
        
        event = Event("GATE_PASS", {"gate_id": "GATE-00"})
        manager.record_event(event)
        
        snapshot = manager.create_snapshot(event.event_id)
        
        assert snapshot is not None
        assert snapshot.event_id == event.event_id
        assert snapshot.state["gates"]["GATE-00"]["status"] == "PASS"
        assert len(manager._snapshots) == 1

    def test_create_snapshot_auto(self):
        """Test auto-creation of snapshots at interval."""
        manager = EventSourcingManager(snapshot_interval=3)
        
        for i in range(6):
            manager.record_event(Event("GATE_PASS", {"gate_id": f"GATE-0{i}"}))
        
        # Should have created snapshots at event 3 and 6
        assert len(manager._snapshots) == 2

    def test_get_state_snapshots(self):
        """Test getting all snapshots."""
        manager = EventSourcingManager()
        
        for i in range(3):
            event = Event("GATE_PASS", {"gate_id": f"GATE-0{i}"})
            manager.record_event(event)
            manager.create_snapshot(event.event_id)
        
        snapshots = manager.get_state_snapshots()
        
        assert len(snapshots) == 3

    def test_reconstruct_uses_snapshot(self):
        """Test that reconstruction uses snapshots for efficiency."""
        # Use large interval to prevent auto-snapshots
        manager = EventSourcingManager(snapshot_interval=1000)
        
        # Record 5 events
        for i in range(5):
            manager.record_event(Event("GATE_PASS", {"gate_id": f"GATE-0{i}"}))
        
        # Create snapshot at event 3
        event3_id = manager._events[2].event_id
        manager.create_snapshot(event3_id)
        
        # Record more events (now 10 total)
        for i in range(5):
            manager.record_event(Event("GATE_FAIL", {"gate_id": f"GATE-{i}", "reason": "Test"}))
        
        # Reconstruct - should use snapshot
        result = manager.reconstruct_state()
        
        assert result.from_snapshot is True
        # Should only apply events after snapshot (10 total - 3 in snapshot = 7)
        assert result.events_applied == 7

    def test_event_bus_integration(self):
        """Test integration with EventBus."""
        bus = EventBus(config={"async_enabled": False})
        manager = EventSourcingManager(event_bus=bus)
        
        # Emit events through bus
        bus.emit(Event("GATE_PASS", {"gate_id": "GATE-00"}))
        bus.emit(Event("GATE_WARN", {"gate_id": "GATE-01"}))
        
        # Events should be recorded in manager
        assert len(manager._events) == 2
        
        result = manager.reconstruct_state()
        assert result.state["gates"]["GATE-00"]["status"] == "PASS"

    def test_get_stats(self):
        """Test getting statistics."""
        manager = EventSourcingManager(snapshot_interval=5)
        
        for i in range(10):
            manager.record_event(Event("GATE_PASS", {"gate_id": f"GATE-0{i % 3}"}))
        
        stats = manager.get_stats()
        
        assert stats["total_events"] == 10
        assert stats["snapshot_count"] == 2  # Auto-created at 5 and 10
        assert "GATE_PASS" in stats["event_counts"]
        assert stats["event_counts"]["GATE_PASS"] == 10

    def test_get_event_by_id(self):
        """Test getting an event by ID."""
        manager = EventSourcingManager()
        
        event = Event("GATE_PASS", {"gate_id": "GATE-00"})
        manager.record_event(event)
        
        found = manager.get_event_by_id(event.event_id)
        
        assert found is not None
        assert found.event_id == event.event_id
        
        not_found = manager.get_event_by_id("non-existent")
        assert not_found is None

    def test_clear_history(self):
        """Test clearing history."""
        manager = EventSourcingManager()
        
        manager.record_event(Event("GATE_PASS", {"gate_id": "GATE-00"}))
        manager.create_snapshot()
        
        manager.clear_history()
        
        assert len(manager._events) == 0
        assert len(manager._snapshots) == 0

    def test_export_import_events(self):
        """Test exporting and importing events."""
        manager = EventSourcingManager()
        
        # Record some events
        for i in range(5):
            manager.record_event(Event("GATE_PASS", {"gate_id": f"GATE-0{i}"}))
        manager.create_snapshot()
        
        # Export to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
        
        try:
            # Export
            assert manager.export_events(temp_path) is True
            
            # Create new manager and import
            new_manager = EventSourcingManager()
            assert new_manager.import_events(temp_path) is True
            
            # Verify data
            assert len(new_manager._events) == 5
            assert len(new_manager._snapshots) == 1
        finally:
            os.unlink(temp_path)


class TestStateChangingEvents:
    """Tests for STATE_CHANGING_EVENTS set."""

    def test_gate_events_included(self):
        """Test that gate events are tracked."""
        assert "GATE_PASS" in STATE_CHANGING_EVENTS
        assert "GATE_FAIL" in STATE_CHANGING_EVENTS
        assert "GATE_WARN" in STATE_CHANGING_EVENTS

    def test_phase_events_included(self):
        """Test that phase events are tracked."""
        assert "PHASE_START" in STATE_CHANGING_EVENTS
        assert "PHASE_COMPLETE" in STATE_CHANGING_EVENTS

    def test_chunk_events_included(self):
        """Test that chunk events are tracked."""
        assert "CHUNK_PROCESSED" in STATE_CHANGING_EVENTS
        assert "CHUNK_COMPLETE" in STATE_CHANGING_EVENTS

    def test_session_events_included(self):
        """Test that session events are tracked."""
        assert "SESSION_START" in STATE_CHANGING_EVENTS
        assert "SESSION_END" in STATE_CHANGING_EVENTS
        assert "SESSION_ABORT" in STATE_CHANGING_EVENTS

    def test_checkpoint_events_included(self):
        """Test that checkpoint events are tracked."""
        assert "CHECKPOINT_SAVED" in STATE_CHANGING_EVENTS


class TestEventSourcingIntegration:
    """Integration tests for EventSourcingManager."""

    def test_full_workflow(self):
        """Test complete event sourcing workflow."""
        manager = EventSourcingManager(snapshot_interval=5)
        
        # Simulate a session
        manager.record_event(Event("SESSION_START", {"session_id": "test-session"}))
        
        # Phase 1
        manager.record_event(Event("PHASE_START", {"phase": 1}))
        manager.record_event(Event("GATE_PASS", {"gate_id": "GATE-00", "details": {"check": "passed"}}))
        manager.record_event(Event("GATE_PASS", {"gate_id": "GATE-01"}))
        manager.record_event(Event("PHASE_COMPLETE", {"phase": 1}))
        
        # Phase 2
        manager.record_event(Event("PHASE_START", {"phase": 2}))
        manager.record_event(Event("CHUNK_PROCESSED", {"chunk_id": "chunk-1", "chunks_completed": 1}))
        manager.record_event(Event("CHUNK_PROCESSED", {"chunk_id": "chunk-2", "chunks_completed": 2}))
        manager.record_event(Event("ISSUE_FOUND", {"issue_id": "issue-1"}))
        manager.record_event(Event("ISSUE_FIXED", {"issue_id": "issue-1"}))
        manager.record_event(Event("GATE_PASS", {"gate_id": "GATE-02"}))
        
        # Reconstruct state
        result = manager.reconstruct_state()
        
        assert result.state["session"]["status"] == "ACTIVE"
        assert result.state["phases"]["current_phase"] == 2
        assert 1 in result.state["phases"]["completed_phases"]
        assert result.state["gates"]["GATE-00"]["status"] == "PASS"
        assert result.state["gates"]["GATE-01"]["status"] == "PASS"
        assert result.state["gates"]["GATE-02"]["status"] == "PASS"
        assert result.state["chunks"]["completed"] == 2
        assert result.state["issues"]["found"] == 1
        assert result.state["issues"]["fixed"] == 1
        
        # Should have auto-created snapshots
        assert len(manager._snapshots) >= 1

    def test_point_in_time_recovery(self):
        """Test recovering state at different points in time."""
        manager = EventSourcingManager()
        
        # Simulate a session with issues
        manager.record_event(Event("SESSION_START", {"session_id": "recovery-test"}))
        manager.record_event(Event("GATE_PASS", {"gate_id": "GATE-00"}))
        manager.record_event(Event("GATE_FAIL", {"gate_id": "GATE-01", "reason": "Validation error"}))
        manager.record_event(Event("GATE_WARN", {"gate_id": "GATE-02", "reason": "Warning"}))
        manager.record_event(Event("SESSION_ABORT", {"reason": "Critical failure"}))
        
        # Get all events
        all_events = manager.get_event_history()
        
        # Reconstruct at each point
        for i, event in enumerate(all_events):
            result = manager.reconstruct_state(event.event_id)
            
            # Verify state matches expected
            if i == 0:
                assert result.state["session"]["status"] == "ACTIVE"
            elif i == 2:
                assert result.state["gates"]["GATE-01"]["status"] == "FAIL"
            elif i == 4:
                assert result.state["session"]["status"] == "ABORTED"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
