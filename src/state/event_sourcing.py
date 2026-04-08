"""
Event Sourcing Manager for TITAN FUSE Protocol.

ITEM-INT-144: State Reconstruction via Event Sourcing

Enables state reconstruction from event history by:
- Recording all state-changing events (GATE_PASS/FAIL, PHASE_*, CHUNK_*, SESSION_*)
- Reconstructing state at any point in time
- Creating snapshots for efficient point-in-time recovery
- Integrating with EventBus for automatic event capture

Usage:
    from src.state.event_sourcing import EventSourcingManager
    
    manager = EventSourcingManager()
    
    # Record events
    manager.record_event(gate_pass_event)
    
    # Reconstruct state
    state = manager.reconstruct_state("evt-123")
    
    # Get state at timestamp
    state = manager.get_state_at(datetime(2024, 1, 15, 12, 0, 0))

Integration with EventBus:
    bus = EventBus()
    sourcing_manager = EventSourcingManager(event_bus=bus)
    # Events are automatically recorded when emitted

Author: TITAN FUSE Team
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Set, TYPE_CHECKING
import logging
import hashlib
import json

from src.utils.timezone import now_utc, now_utc_iso, from_iso8601

if TYPE_CHECKING:
    from src.events.event_bus import EventBus, Event


# Event types that modify state
STATE_CHANGING_EVENTS: Set[str] = {
    # Gate events
    "GATE_PASS",
    "GATE_FAIL",
    "GATE_WARN",
    # Phase events
    "PHASE_START",
    "PHASE_COMPLETE",
    # Chunk events
    "CHUNK_PROCESSED",
    "CHUNK_COMPLETE",
    "CHUNK_AUTO_SPLIT",
    # Session events
    "SESSION_START",
    "SESSION_END",
    "SESSION_ABORT",
    # Checkpoint events
    "CHECKPOINT_SAVED",
    # Budget events
    "BUDGET_WARNING",
    "BUDGET_EXCEEDED",
    # Issue events
    "ISSUE_FOUND",
    "ISSUE_FIXED",
}


@dataclass
class StateSnapshot:
    """
    Snapshot of reconstructed state at a point in time.
    
    ITEM-INT-144: Enables efficient state reconstruction by
    storing intermediate states that can be used as starting
    points for replay.
    
    Attributes:
        snapshot_id: Unique identifier for the snapshot
        event_id: ID of the last event applied before this snapshot
        timestamp: ISO8601 timestamp of the snapshot
        state: The reconstructed state dictionary
        event_count: Number of events applied to reach this state
        checksum: SHA-256 checksum of state for integrity
    """
    snapshot_id: str
    event_id: str
    timestamp: str
    state: Dict[str, Any]
    event_count: int
    checksum: str = ""
    
    def __post_init__(self):
        if not self.checksum:
            self.checksum = self._compute_checksum()
    
    def _compute_checksum(self) -> str:
        """Compute SHA-256 checksum of state."""
        state_str = json.dumps(self.state, sort_keys=True, default=str)
        return hashlib.sha256(state_str.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "snapshot_id": self.snapshot_id,
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "state": self.state,
            "event_count": self.event_count,
            "checksum": self.checksum,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StateSnapshot':
        """Create from dictionary."""
        return cls(
            snapshot_id=data["snapshot_id"],
            event_id=data["event_id"],
            timestamp=data["timestamp"],
            state=data["state"],
            event_count=data["event_count"],
            checksum=data.get("checksum", ""),
        )


@dataclass
class ReconstructedState:
    """
    Result of state reconstruction.
    
    ITEM-INT-144: Contains the reconstructed state along with
    metadata about the reconstruction process.
    
    Attributes:
        state: The reconstructed state dictionary
        last_event_id: ID of the last event applied
        last_event_timestamp: Timestamp of the last event
        events_applied: Number of events applied during reconstruction
        from_snapshot: True if reconstruction started from a snapshot
        snapshot_id: ID of the snapshot used (if any)
        reconstruction_time_ms: Time taken to reconstruct in milliseconds
    """
    state: Dict[str, Any]
    last_event_id: str = ""
    last_event_timestamp: str = ""
    events_applied: int = 0
    from_snapshot: bool = False
    snapshot_id: str = ""
    reconstruction_time_ms: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "state": self.state,
            "last_event_id": self.last_event_id,
            "last_event_timestamp": self.last_event_timestamp,
            "events_applied": self.events_applied,
            "from_snapshot": self.from_snapshot,
            "snapshot_id": self.snapshot_id,
            "reconstruction_time_ms": self.reconstruction_time_ms,
        }


class EventSourcingManager:
    """
    Manager for event sourcing and state reconstruction.
    
    ITEM-INT-144: Implements event sourcing pattern to enable:
    - Recording all state-changing events
    - Reconstructing state at any point in time
    - Point-in-time recovery using snapshots
    
    Features:
    - Automatic event recording via EventBus integration
    - Snapshot-based optimization for efficient reconstruction
    - State transitions for GATE_*, PHASE_*, CHUNK_*, SESSION_* events
    - Filtering events by type, gate, timestamp
    
    Example:
        manager = EventSourcingManager()
        
        # Record events
        manager.record_event(Event("GATE_PASS", {"gate_id": "GATE-00"}))
        
        # Reconstruct state up to an event
        state = manager.reconstruct_state("evt-123")
        
        # Get state at a specific timestamp
        state = manager.get_state_at(datetime(2024, 1, 15, 12, 0))
    """
    
    # Default snapshot interval (create snapshot every N events)
    DEFAULT_SNAPSHOT_INTERVAL = 100
    
    def __init__(
        self,
        event_bus: 'EventBus' = None,
        snapshot_interval: int = None,
        config: Dict = None
    ):
        """
        Initialize the EventSourcingManager.
        
        Args:
            event_bus: Optional EventBus to automatically subscribe to events
            snapshot_interval: Number of events between snapshots (default: 100)
            config: Configuration dictionary
        """
        self.logger = logging.getLogger(__name__)
        
        # Configuration
        self.config = config or {}
        self._snapshot_interval = snapshot_interval or self.config.get(
            "snapshot_interval", self.DEFAULT_SNAPSHOT_INTERVAL
        )
        
        # Event storage
        self._events: List['Event'] = []
        self._event_index: Dict[str, int] = {}  # event_id -> index
        self._event_by_timestamp: List[tuple] = []  # (timestamp, index) for binary search
        
        # Snapshots
        self._snapshots: List[StateSnapshot] = []
        self._snapshot_index: Dict[str, StateSnapshot] = {}  # event_id -> snapshot
        
        # Gate event index for fast lookups
        self._gate_events: Dict[str, List[str]] = {}  # gate_id -> [event_ids]
        
        # Track event count for snapshot interval
        self._event_count = 0
        
        # EventBus integration
        self._event_bus = event_bus
        if event_bus:
            self._subscribe_to_event_bus(event_bus)
        
        self.logger.info(
            f"EventSourcingManager initialized: snapshot_interval={self._snapshot_interval}"
        )
    
    def _subscribe_to_event_bus(self, event_bus: 'EventBus') -> None:
        """
        Subscribe to state-changing events on the EventBus.
        
        ITEM-INT-144 step 03: Integration with EventBus.
        
        Args:
            event_bus: The EventBus to subscribe to
        """
        from src.events.event_bus import EventSeverity
        
        def on_event(event: 'Event') -> None:
            """Handler for all events - records state-changing ones."""
            if event.event_type in STATE_CHANGING_EVENTS:
                self.record_event(event)
        
        # Subscribe to all events with lowest priority
        event_bus.subscribe("*", on_event, priority=100)
        self.logger.info("Subscribed to EventBus for state-changing events")
    
    def record_event(self, event: 'Event') -> None:
        """
        Record a state-changing event.
        
        ITEM-INT-144 step 01: Records events for later reconstruction.
        
        Args:
            event: The event to record
        """
        # Skip if already recorded
        if event.event_id in self._event_index:
            return
        
        # Add to event list
        index = len(self._events)
        self._events.append(event)
        self._event_index[event.event_id] = index
        
        # Add to timestamp index for binary search
        self._event_by_timestamp.append((event.timestamp, index))
        
        # Index by gate_id if present
        gate_id = event.data.get("gate_id")
        if gate_id:
            if gate_id not in self._gate_events:
                self._gate_events[gate_id] = []
            self._gate_events[gate_id].append(event.event_id)
        
        self._event_count += 1
        
        # Auto-create snapshot at interval
        if self._event_count % self._snapshot_interval == 0:
            self.create_snapshot(event.event_id)
        
        self.logger.debug(f"Recorded event: {event.event_type} [{event.event_id}]")
    
    def reconstruct_state(self, up_to_event_id: str = None) -> ReconstructedState:
        """
        Reconstruct state up to a specific event.
        
        ITEM-INT-144 step 02: State reconstruction from event history.
        
        Reconstructs the state by:
        1. Finding the nearest snapshot before the target event
        2. Applying events from the snapshot to the target
        
        Args:
            up_to_event_id: Event ID to reconstruct up to (None = latest)
            
        Returns:
            ReconstructedState with the reconstructed state and metadata
        """
        import time
        start_time = time.time()
        
        # Find target index
        if up_to_event_id:
            if up_to_event_id not in self._event_index:
                self.logger.warning(f"Event not found: {up_to_event_id}")
                return ReconstructedState(state=self._get_initial_state())
            target_index = self._event_index[up_to_event_id]
        else:
            target_index = len(self._events) - 1
        
        if target_index < 0 or not self._events:
            return ReconstructedState(
                state=self._get_initial_state(),
                events_applied=0
            )
        
        # Find nearest snapshot before target
        snapshot, start_index = self._find_nearest_snapshot(target_index)
        
        # Start from snapshot or initial state
        if snapshot:
            state = snapshot.state.copy()
            events_start = start_index + 1
            from_snapshot = True
            snapshot_id = snapshot.snapshot_id
        else:
            state = self._get_initial_state()
            events_start = 0
            from_snapshot = False
            snapshot_id = ""
        
        # Apply events from start to target
        events_applied = 0
        for i in range(events_start, target_index + 1):
            event = self._events[i]
            self._apply_event_to_state(state, event)
            events_applied += 1
        
        # Get last event info
        last_event = self._events[target_index]
        
        reconstruction_time_ms = int((time.time() - start_time) * 1000)
        
        return ReconstructedState(
            state=state,
            last_event_id=last_event.event_id,
            last_event_timestamp=last_event.timestamp,
            events_applied=events_applied,
            from_snapshot=from_snapshot,
            snapshot_id=snapshot_id,
            reconstruction_time_ms=reconstruction_time_ms,
        )
    
    def get_event_history(
        self,
        event_types: List[str] = None,
        gate_id: str = None,
        from_timestamp: str = None,
        to_timestamp: str = None,
        limit: int = None
    ) -> List['Event']:
        """
        Get filtered event history.
        
        ITEM-INT-144: Returns events matching the specified filters.
        
        Args:
            event_types: List of event types to include (None = all)
            gate_id: Filter to events for a specific gate
            from_timestamp: ISO8601 timestamp to start from
            to_timestamp: ISO8601 timestamp to end at
            limit: Maximum number of events to return
            
        Returns:
            List of events matching the filters
        """
        events = self._events
        
        # Filter by gate_id first (uses index)
        if gate_id:
            gate_event_ids = set(self._gate_events.get(gate_id, []))
            events = [e for e in events if e.event_id in gate_event_ids]
        
        # Filter by event types
        if event_types:
            event_type_set = set(event_types)
            events = [e for e in events if e.event_type in event_type_set]
        
        # Filter by timestamp range
        if from_timestamp:
            events = [e for e in events if e.timestamp >= from_timestamp]
        if to_timestamp:
            events = [e for e in events if e.timestamp <= to_timestamp]
        
        # Apply limit
        if limit is not None:
            events = events[-limit:]
        
        return events
    
    def get_state_at(self, timestamp: datetime) -> ReconstructedState:
        """
        Reconstruct state at a specific point in time.
        
        ITEM-INT-144: Point-in-time recovery using timestamp.
        
        Args:
            timestamp: The datetime to reconstruct state at
            
        Returns:
            ReconstructedState at the specified timestamp
        """
        # Convert timestamp to ISO8601 string for comparison
        ts_str = timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        
        # Find the last event before or at the timestamp
        target_index = -1
        for i, event in enumerate(self._events):
            if event.timestamp <= ts_str:
                target_index = i
            else:
                break
        
        if target_index < 0:
            return ReconstructedState(
                state=self._get_initial_state(),
                events_applied=0
            )
        
        # Get the event at the target index
        target_event = self._events[target_index]
        
        # Reconstruct up to this event
        return self.reconstruct_state(target_event.event_id)
    
    def get_state_snapshots(self) -> List[StateSnapshot]:
        """
        Get all state snapshots.
        
        ITEM-INT-144: Returns list of all snapshots for inspection.
        
        Returns:
            List of StateSnapshot objects
        """
        return self._snapshots.copy()
    
    def create_snapshot(self, event_id: str = None) -> Optional[StateSnapshot]:
        """
        Create a state snapshot at an event.
        
        ITEM-INT-144: Creates a snapshot for efficient point-in-time recovery.
        
        Args:
            event_id: Event ID to create snapshot at (None = latest)
            
        Returns:
            The created StateSnapshot or None if failed
        """
        if not self._events:
            return None
        
        # Find target event
        if event_id:
            if event_id not in self._event_index:
                self.logger.warning(f"Cannot create snapshot: event not found {event_id}")
                return None
            target_index = self._event_index[event_id]
        else:
            target_index = len(self._events) - 1
        
        target_event = self._events[target_index]
        
        # Check if snapshot already exists for this event
        if target_event.event_id in self._snapshot_index:
            return self._snapshot_index[target_event.event_id]
        
        # Reconstruct state up to this event
        # Use previous snapshot if available for efficiency
        result = self.reconstruct_state(target_event.event_id)
        
        # Create snapshot
        snapshot = StateSnapshot(
            snapshot_id=f"snap-{target_event.event_id}",
            event_id=target_event.event_id,
            timestamp=target_event.timestamp,
            state=result.state,
            event_count=target_index + 1,
        )
        
        # Store snapshot
        self._snapshots.append(snapshot)
        self._snapshot_index[target_event.event_id] = snapshot
        
        # Keep snapshots sorted by timestamp
        self._snapshots.sort(key=lambda s: s.timestamp)
        
        self.logger.info(
            f"Created snapshot {snapshot.snapshot_id} at event {target_event.event_id}"
        )
        
        return snapshot
    
    def get_events_for_gate(self, gate_id: str) -> List['Event']:
        """
        Get all events related to a specific gate.
        
        ITEM-INT-144: Fast lookup of gate-specific events.
        
        Args:
            gate_id: The gate identifier (e.g., "GATE-00")
            
        Returns:
            List of events for the gate
        """
        event_ids = self._gate_events.get(gate_id, [])
        return [self._events[self._event_index[eid]] for eid in event_ids if eid in self._event_index]
    
    def get_event_by_id(self, event_id: str) -> Optional['Event']:
        """
        Get an event by its ID.
        
        Args:
            event_id: The event identifier
            
        Returns:
            The Event or None if not found
        """
        if event_id in self._event_index:
            return self._events[self._event_index[event_id]]
        return None
    
    def clear_history(self) -> None:
        """
        Clear all recorded events and snapshots.
        
        Warning: This cannot be undone.
        """
        self._events.clear()
        self._event_index.clear()
        self._event_by_timestamp.clear()
        self._snapshots.clear()
        self._snapshot_index.clear()
        self._gate_events.clear()
        self._event_count = 0
        
        self.logger.info("Cleared all event history and snapshots")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the event sourcing manager.
        
        Returns:
            Dictionary with statistics
        """
        # Count events by type
        event_counts = {}
        for event in self._events:
            event_type = event.event_type
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
        
        return {
            "total_events": len(self._events),
            "snapshot_count": len(self._snapshots),
            "snapshot_interval": self._snapshot_interval,
            "event_counts": event_counts,
            "gate_event_counts": {
                gate_id: len(events) for gate_id, events in self._gate_events.items()
            },
            "event_bus_connected": self._event_bus is not None,
        }
    
    # Private helper methods
    
    def _get_initial_state(self) -> Dict[str, Any]:
        """
        Get the initial empty state.
        
        Returns:
            Dictionary representing the initial state before any events
        """
        return {
            "gates": {
                "GATE-00": {"status": "PENDING"},
                "GATE-01": {"status": "PENDING"},
                "GATE-02": {"status": "PENDING"},
                "GATE-03": {"status": "PENDING"},
                "GATE-04": {"status": "PENDING"},
                "GATE-05": {"status": "PENDING"},
            },
            "phases": {
                "current_phase": 0,
                "completed_phases": [],
            },
            "chunks": {
                "total": 0,
                "completed": 0,
                "processed": [],
            },
            "session": {
                "status": "INIT",
                "start_time": None,
                "end_time": None,
            },
            "budget": {
                "tokens_used": 0,
                "warnings": 0,
                "exceeded": False,
            },
            "issues": {
                "found": 0,
                "fixed": 0,
                "open": [],
            },
            "checkpoints": [],
        }
    
    def _apply_event_to_state(self, state: Dict[str, Any], event: 'Event') -> None:
        """
        Apply an event to the state.
        
        ITEM-INT-144: State transition logic for each event type.
        
        Args:
            state: The state dictionary to modify
            event: The event to apply
        """
        event_type = event.event_type
        data = event.data
        
        if event_type == "GATE_PASS":
            gate_id = data.get("gate_id")
            if gate_id and gate_id in state["gates"]:
                state["gates"][gate_id] = {
                    "status": "PASS",
                    "timestamp": event.timestamp,
                    "details": data.get("details", {}),
                }
        
        elif event_type == "GATE_FAIL":
            gate_id = data.get("gate_id")
            if gate_id and gate_id in state["gates"]:
                state["gates"][gate_id] = {
                    "status": "FAIL",
                    "timestamp": event.timestamp,
                    "reason": data.get("reason", "Unknown"),
                    "details": data.get("details", {}),
                }
        
        elif event_type == "GATE_WARN":
            gate_id = data.get("gate_id")
            if gate_id and gate_id in state["gates"]:
                state["gates"][gate_id] = {
                    "status": "WARN",
                    "timestamp": event.timestamp,
                    "reason": data.get("reason", "Unknown"),
                    "details": data.get("details", {}),
                }
        
        elif event_type == "PHASE_START":
            phase = data.get("phase", 0)
            state["phases"]["current_phase"] = phase
        
        elif event_type == "PHASE_COMPLETE":
            phase = data.get("phase", 0)
            state["phases"]["current_phase"] = phase
            if phase not in state["phases"]["completed_phases"]:
                state["phases"]["completed_phases"].append(phase)
        
        elif event_type == "CHUNK_PROCESSED":
            chunk_id = data.get("chunk_id")
            if chunk_id:
                state["chunks"]["processed"].append(chunk_id)
            state["chunks"]["completed"] = data.get("chunks_completed", state["chunks"]["completed"])
        
        elif event_type == "CHUNK_COMPLETE":
            state["chunks"]["total"] = data.get("chunks_total", state["chunks"]["total"])
            state["chunks"]["completed"] = data.get("chunks_completed", state["chunks"]["completed"])
        
        elif event_type == "CHUNK_AUTO_SPLIT":
            # Track auto-split events
            state["chunks"]["auto_split_count"] = state["chunks"].get("auto_split_count", 0) + 1
        
        elif event_type == "SESSION_START":
            state["session"]["status"] = "ACTIVE"
            state["session"]["start_time"] = event.timestamp
            state["session"]["session_id"] = data.get("session_id", "")
        
        elif event_type == "SESSION_END":
            state["session"]["status"] = "COMPLETE"
            state["session"]["end_time"] = event.timestamp
            state["session"]["end_reason"] = data.get("reason", "Normal completion")
        
        elif event_type == "SESSION_ABORT":
            state["session"]["status"] = "ABORTED"
            state["session"]["end_time"] = event.timestamp
            state["session"]["abort_reason"] = data.get("reason", "Unknown")
        
        elif event_type == "CHECKPOINT_SAVED":
            state["checkpoints"].append({
                "timestamp": event.timestamp,
                "checkpoint_id": data.get("checkpoint_id", ""),
                "session_id": data.get("session_id", ""),
            })
        
        elif event_type == "BUDGET_WARNING":
            state["budget"]["warnings"] += 1
            state["budget"]["last_warning"] = data.get("message", "")
        
        elif event_type == "BUDGET_EXCEEDED":
            state["budget"]["exceeded"] = True
            state["budget"]["exceeded_at"] = event.timestamp
            state["budget"]["tokens_used"] = data.get("tokens_used", state["budget"]["tokens_used"])
        
        elif event_type == "ISSUE_FOUND":
            state["issues"]["found"] += 1
            issue_id = data.get("issue_id", "")
            if issue_id:
                state["issues"]["open"].append(issue_id)
        
        elif event_type == "ISSUE_FIXED":
            state["issues"]["fixed"] += 1
            issue_id = data.get("issue_id", "")
            if issue_id and issue_id in state["issues"]["open"]:
                state["issues"]["open"].remove(issue_id)
    
    def _find_nearest_snapshot(self, target_index: int) -> tuple:
        """
        Find the nearest snapshot before a target event index.
        
        Args:
            target_index: The target event index
            
        Returns:
            Tuple of (snapshot, event_index) or (None, -1) if no snapshot
        """
        if not self._snapshots:
            return None, -1
        
        # Find the snapshot with the largest event_count <= target_index + 1
        nearest_snapshot = None
        nearest_index = -1
        
        for snapshot in self._snapshots:
            if snapshot.event_id in self._event_index:
                snap_index = self._event_index[snapshot.event_id]
                if snap_index <= target_index and snap_index > nearest_index:
                    nearest_snapshot = snapshot
                    nearest_index = snap_index
        
        return nearest_snapshot, nearest_index
    
    def export_events(self, filepath: str) -> bool:
        """
        Export events to a JSON file.
        
        Args:
            filepath: Path to export to
            
        Returns:
            True if successful
        """
        try:
            events_data = [e.to_dict() for e in self._events]
            with open(filepath, 'w') as f:
                json.dump({
                    "events": events_data,
                    "snapshots": [s.to_dict() for s in self._snapshots],
                    "exported_at": now_utc_iso(),
                }, f, indent=2)
            return True
        except Exception as e:
            self.logger.error(f"Failed to export events: {e}")
            return False
    
    def import_events(self, filepath: str) -> bool:
        """
        Import events from a JSON file.
        
        Args:
            filepath: Path to import from
            
        Returns:
            True if successful
        """
        from src.events.event_bus import Event
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            # Clear existing data
            self.clear_history()
            
            # Import events
            for event_data in data.get("events", []):
                event = Event.from_dict(event_data)
                self.record_event(event)
            
            # Import snapshots
            for snapshot_data in data.get("snapshots", []):
                snapshot = StateSnapshot.from_dict(snapshot_data)
                self._snapshots.append(snapshot)
                self._snapshot_index[snapshot.event_id] = snapshot
            
            self.logger.info(f"Imported {len(self._events)} events and {len(self._snapshots)} snapshots")
            return True
        except Exception as e:
            self.logger.error(f"Failed to import events: {e}")
            return False
