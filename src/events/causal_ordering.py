"""
Causal Event Ordering for TITAN FUSE Protocol.

ITEM-ARCH-09: Implements Lamport timestamps and vector clocks
for causal ordering of events across distributed sessions.

Provides:
- LamportClock: Simple logical timestamps for causal ordering
- VectorClock: Per-node timestamps for detecting concurrent events
- Causal violation detection and reporting

Author: TITAN FUSE Team
Version: 3.4.0
"""

from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime
import logging


@dataclass
class CausalEventMetadata:
    """Metadata for causal ordering attached to events."""
    lamport_time: int
    vector_clock: Dict[str, int]
    causal_deps: List[str] = field(default_factory=list)
    node_id: str = "default"
    
    def to_dict(self) -> Dict:
        return {
            "lamport_time": self.lamport_time,
            "vector_clock": self.vector_clock,
            "causal_deps": self.causal_deps,
            "node_id": self.node_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'CausalEventMetadata':
        return cls(
            lamport_time=data.get("lamport_time", 0),
            vector_clock=data.get("vector_clock", {}),
            causal_deps=data.get("causal_deps", []),
            node_id=data.get("node_id", "default")
        )


class LamportClock:
    """
    Lamport logical clock for simple causal ordering.
    
    Provides monotonically increasing timestamps that capture
    "happened-before" relationships between events.
    
    Usage:
        clock1 = LamportClock(node_id="node1")
        clock2 = LamportClock(node_id="node2")
        
        # Local event
        t1 = clock1.tick()
        
        # Send message (include timestamp)
        msg = {"data": "...", "lamport_time": t1}
        
        # Receive message
        t2 = clock2.receive(msg["lamport_time"])
    """
    
    def __init__(self, node_id: str = "default", initial_time: int = 0):
        """
        Initialize Lamport clock.
        
        Args:
            node_id: Identifier for this node
            initial_time: Starting time value
        """
        self.node_id = node_id
        self._time = initial_time
        self._logger = logging.getLogger(__name__)
    
    def tick(self) -> int:
        """
        Increment clock for local event.
        
        Returns:
            New timestamp after increment
        """
        self._time += 1
        self._logger.debug(f"LamportClock[{self.node_id}].tick() -> {self._time}")
        return self._time
    
    def receive(self, remote_time: int) -> int:
        """
        Update clock when receiving message from remote.
        
        The clock is set to max(local, remote) + 1 to ensure
        causal ordering is maintained.
        
        Args:
            remote_time: Timestamp from remote message
            
        Returns:
            New timestamp after update
        """
        self._time = max(self._time, remote_time) + 1
        self._logger.debug(
            f"LamportClock[{self.node_id}].receive({remote_time}) -> {self._time}"
        )
        return self._time
    
    def get_time(self) -> int:
        """Get current clock time without incrementing."""
        return self._time
    
    def set_time(self, time: int) -> None:
        """Set clock time (use with caution, mainly for recovery)."""
        if time > self._time:
            self._time = time
    
    def reset(self) -> None:
        """Reset clock to initial state."""
        self._time = 0


class VectorClock:
    """
    Vector clock for detecting concurrent events.
    
    Each node maintains a vector of timestamps, one entry per node.
    This allows detection of concurrent (not causally related) events.
    
    Comparison results:
    - "before": This event happened before the other (causal dependency)
    - "after": This event happened after the other
    - "concurrent": Events are not causally related
    
    Usage:
        vc1 = VectorClock(node_id="node1", all_nodes=["node1", "node2"])
        vc2 = VectorClock(node_id="node2", all_nodes=["node1", "node2"])
        
        # Local events
        vc1.increment("node1")
        vc2.increment("node2")
        
        # Compare
        result = vc1.compare(vc2.clock)  # "concurrent"
    """
    
    def __init__(self, node_id: str, all_nodes: List[str] = None):
        """
        Initialize vector clock.
        
        Args:
            node_id: Identifier for this node
            all_nodes: List of all known node IDs
        """
        self.node_id = node_id
        self._all_nodes = set(all_nodes or [node_id])
        self._clock: Dict[str, int] = {node: 0 for node in self._all_nodes}
        self._logger = logging.getLogger(__name__)
    
    @property
    def clock(self) -> Dict[str, int]:
        """Get current vector clock (read-only copy)."""
        return dict(self._clock)
    
    def increment(self, node_id: str = None) -> Dict[str, int]:
        """
        Increment clock entry for a node (usually this node).
        
        Args:
            node_id: Node to increment (defaults to self.node_id)
            
        Returns:
            Updated vector clock
        """
        node = node_id or self.node_id
        self._ensure_node(node)
        self._clock[node] += 1
        self._logger.debug(f"VectorClock.increment({node}) -> {self._clock}")
        return self.clock
    
    def merge(self, other: Dict[str, int]) -> Dict[str, int]:
        """
        Merge with another vector clock (receive operation).
        
        Each entry becomes max(local, remote).
        
        Args:
            other: Vector clock from remote message
            
        Returns:
            Merged vector clock
        """
        # Ensure all nodes from other are known
        for node in other:
            self._ensure_node(node)
        
        # Take max of each entry
        for node in self._clock:
            self._clock[node] = max(
                self._clock.get(node, 0),
                other.get(node, 0)
            )
        
        self._logger.debug(f"VectorClock.merge() -> {self._clock}")
        return self.clock
    
    def compare(self, other: Dict[str, int]) -> str:
        """
        Compare this vector clock with another.
        
        Returns:
            "before": This clock is causally before other
            "after": This clock is causally after other
            "concurrent": Neither is before the other
        """
        self_before = False
        other_before = False
        
        all_nodes = set(self._clock.keys()) | set(other.keys())
        
        for node in all_nodes:
            this_val = self._clock.get(node, 0)
            other_val = other.get(node, 0)
            
            if this_val < other_val:
                self_before = True
            elif this_val > other_val:
                other_before = True
        
        if self_before and not other_before:
            return "before"
        elif other_before and not self_before:
            return "after"
        else:
            return "concurrent"
    
    def _ensure_node(self, node_id: str) -> None:
        """Ensure node exists in clock."""
        if node_id not in self._clock:
            self._clock[node_id] = 0
            self._all_nodes.add(node_id)
    
    def get_time(self, node_id: str = None) -> int:
        """Get time for a specific node."""
        node = node_id or self.node_id
        return self._clock.get(node, 0)
    
    def reset(self) -> None:
        """Reset all clock entries to 0."""
        self._clock = {node: 0 for node in self._all_nodes}


class CausalOrderingManager:
    """
    Manages causal ordering for the EventBus.
    
    Combines LamportClock and VectorClock to provide comprehensive
    causal ordering with violation detection.
    
    ITEM-ARCH-09: Integration point for EventBus.
    
    Usage:
        manager = CausalOrderingManager(node_id="session-1")
        
        # Before emitting event
        metadata = manager.create_event_metadata()
        event.lamport_time = metadata.lamport_time
        event.vector_clock = metadata.vector_clock
        
        # On receiving event
        manager.process_incoming_event(event)
        
        # Check for violations
        if manager.check_violation(event):
            emit_gap("[gap: causal_violation_detected]")
    """
    
    def __init__(self, node_id: str = "default", all_nodes: List[str] = None):
        """
        Initialize causal ordering manager.
        
        Args:
            node_id: Identifier for this node/session
            all_nodes: List of all known node IDs
        """
        self.node_id = node_id
        self._lamport = LamportClock(node_id)
        self._vector = VectorClock(node_id, all_nodes)
        self._event_history: List[Dict] = []
        self._max_history = 1000
        self._logger = logging.getLogger(__name__)
    
    def create_event_metadata(self, causal_deps: List[str] = None) -> CausalEventMetadata:
        """
        Create metadata for a new event.
        
        Increments both clocks and returns metadata to attach to event.
        
        Args:
            causal_deps: List of event IDs this event depends on
            
        Returns:
            CausalEventMetadata to attach to event
        """
        lamport_time = self._lamport.tick()
        vector_clock = self._vector.increment()
        
        return CausalEventMetadata(
            lamport_time=lamport_time,
            vector_clock=vector_clock,
            causal_deps=causal_deps or [],
            node_id=self.node_id
        )
    
    def process_incoming_event(self, event_metadata: CausalEventMetadata) -> None:
        """
        Process an incoming event from another node.
        
        Updates local clocks based on the received event's timestamps.
        
        Args:
            event_metadata: Causal metadata from the incoming event
        """
        # Update Lamport clock
        self._lamport.receive(event_metadata.lamport_time)
        
        # Update vector clock
        self._vector.merge(event_metadata.vector_clock)
        self._vector.increment()
        
        # Record in history
        self._event_history.append({
            "event_id": getattr(event_metadata, 'event_id', 'unknown'),
            "lamport_time": event_metadata.lamport_time,
            "vector_clock": event_metadata.vector_clock,
            "node_id": event_metadata.node_id
        })
        
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]
        
        self._logger.debug(
            f"Processed incoming event from {event_metadata.node_id}, "
            f"lamport={event_metadata.lamport_time}"
        )
    
    def check_violation(self, event_metadata: CausalEventMetadata) -> bool:
        """
        Check if an event represents a causal ordering violation.
        
        A violation occurs when an event arrives "before" a previously
        processed event that should have happened after it.
        
        Args:
            event_metadata: Metadata of the event to check
            
        Returns:
            True if violation detected
        """
        for past_event in self._event_history:
            past_vc = past_event["vector_clock"]
            incoming_vc = event_metadata.vector_clock
            
            # Check if past event is after incoming event
            # but incoming event wasn't seen when past was processed
            comparison = self._compare_vectors(incoming_vc, past_vc)
            
            if comparison == "after":
                # Past event happened after incoming
                # But we didn't see incoming when past was processed
                # This is a violation
                self._logger.warning(
                    f"[gap: causal_violation_detected] "
                    f"Event from {event_metadata.node_id} arrived after "
                    f"event from {past_event['node_id']} that depends on it"
                )
                return True
        
        return False
    
    def _compare_vectors(self, v1: Dict[str, int], v2: Dict[str, int]) -> str:
        """Compare two vector clocks."""
        v1_before = False
        v2_before = False
        
        all_nodes = set(v1.keys()) | set(v2.keys())
        
        for node in all_nodes:
            v1_val = v1.get(node, 0)
            v2_val = v2.get(node, 0)
            
            if v1_val < v2_val:
                v1_before = True
            elif v1_val > v2_val:
                v2_before = True
        
        if v1_before and not v2_before:
            return "before"
        elif v2_before and not v1_before:
            return "after"
        else:
            return "concurrent"
    
    def get_lamport_time(self) -> int:
        """Get current Lamport time."""
        return self._lamport.get_time()
    
    def get_vector_clock(self) -> Dict[str, int]:
        """Get current vector clock."""
        return self._vector.clock
    
    def get_history(self, limit: int = 100) -> List[Dict]:
        """Get recent event history."""
        return self._event_history[-limit:]
    
    def reset(self) -> None:
        """Reset all clocks and history."""
        self._lamport.reset()
        self._vector.reset()
        self._event_history.clear()
        self._logger.info(f"CausalOrderingManager[{self.node_id}] reset")
    
    def get_stats(self) -> Dict:
        """Get statistics about causal ordering."""
        return {
            "node_id": self.node_id,
            "lamport_time": self._lamport.get_time(),
            "vector_clock": self._vector.clock,
            "event_history_count": len(self._event_history),
            "known_nodes": list(self._vector._all_nodes)
        }
