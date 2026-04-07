"""
Tests for Causal Event Ordering.

ITEM-ARCH-09: Tests for Lamport timestamps, vector clocks,
and causal violation detection.
"""

import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from events.causal_ordering import (
    LamportClock, VectorClock, CausalOrderingManager,
    CausalEventMetadata
)


class TestLamportClock:
    """Tests for Lamport logical clock."""
    
    def test_initial_time(self):
        """Test initial time is 0."""
        clock = LamportClock()
        assert clock.get_time() == 0
    
    def test_tick_increments(self):
        """Test tick increments clock."""
        clock = LamportClock()
        t1 = clock.tick()
        t2 = clock.tick()
        assert t1 == 1
        assert t2 == 2
        assert clock.get_time() == 2
    
    def test_receive_updates(self):
        """Test receive updates clock correctly."""
        clock = LamportClock()
        t1 = clock.tick()  # t1 = 1
        t2 = clock.receive(5)  # max(1, 5) + 1 = 6
        assert t2 == 6
    
    def test_receive_lower_value(self):
        """Test receive with lower remote time."""
        clock = LamportClock()
        clock.tick()  # 1
        clock.tick()  # 2
        t = clock.receive(1)  # max(2, 1) + 1 = 3
        assert t == 3
    
    def test_reset(self):
        """Test reset clears clock."""
        clock = LamportClock()
        clock.tick()
        clock.tick()
        clock.reset()
        assert clock.get_time() == 0
    
    def test_monotonic_timestamps(self):
        """Test that events have monotonically increasing timestamps."""
        clock = LamportClock()
        timestamps = [clock.tick() for _ in range(10)]
        assert timestamps == list(range(1, 11))


class TestVectorClock:
    """Tests for vector clock."""
    
    def test_initial_clock(self):
        """Test initial vector clock is all zeros."""
        vc = VectorClock(node_id="node1", all_nodes=["node1", "node2"])
        assert vc.clock == {"node1": 0, "node2": 0}
    
    def test_increment(self):
        """Test increment updates node's clock."""
        vc = VectorClock(node_id="node1", all_nodes=["node1", "node2"])
        vc.increment()
        assert vc.clock["node1"] == 1
        assert vc.clock["node2"] == 0
    
    def test_merge(self):
        """Test merge combines clocks correctly."""
        vc1 = VectorClock(node_id="node1", all_nodes=["node1", "node2"])
        vc1.increment()  # node1: 1
        
        vc2 = VectorClock(node_id="node2", all_nodes=["node1", "node2"])
        vc2.increment()  # node2: 1
        
        # Merge vc2's clock into vc1
        vc1.merge({"node1": 0, "node2": 1})
        assert vc1.clock["node1"] == 1  # max(1, 0)
        assert vc1.clock["node2"] == 1  # max(0, 1)
    
    def test_compare_before(self):
        """Test comparison when one clock is before another."""
        vc1 = VectorClock(node_id="node1", all_nodes=["node1", "node2"])
        vc1.increment()  # node1: 1
        
        vc2 = VectorClock(node_id="node2", all_nodes=["node1", "node2"])
        
        # vc1 is "after" vc2 (vc1 has higher value)
        assert vc2.compare(vc1.clock) == "before"
        assert vc1.compare(vc2.clock) == "after"
    
    def test_compare_concurrent(self):
        """Test comparison of concurrent events."""
        vc1 = VectorClock(node_id="node1", all_nodes=["node1", "node2"])
        vc2 = VectorClock(node_id="node2", all_nodes=["node1", "node2"])
        
        vc1.increment("node1")  # node1: 1, node2: 0
        vc2.increment("node2")  # node1: 0, node2: 1
        
        # These are concurrent (neither happened before the other)
        assert vc1.compare(vc2.clock) == "concurrent"
        assert vc2.compare(vc1.clock) == "concurrent"


class TestCausalOrderingManager:
    """Tests for causal ordering manager."""
    
    def test_create_event_metadata(self):
        """Test creating event metadata."""
        manager = CausalOrderingManager(node_id="test")
        metadata = manager.create_event_metadata()
        
        assert metadata.lamport_time == 1
        assert metadata.node_id == "test"
        assert metadata.node_id in metadata.vector_clock
    
    def test_process_incoming_event(self):
        """Test processing incoming events."""
        manager = CausalOrderingManager(node_id="node1")
        
        # Create metadata from another "node"
        incoming = CausalEventMetadata(
            lamport_time=5,
            vector_clock={"node2": 3, "node1": 0},
            node_id="node2"
        )
        
        manager.process_incoming_event(incoming)
        
        # Lamport should be max(0, 5) + 1 = 6
        assert manager.get_lamport_time() == 6
    
    def test_no_violation_initially(self):
        """Test no violation for first event."""
        manager = CausalOrderingManager(node_id="test")
        metadata = manager.create_event_metadata()
        
        assert not manager.check_violation(metadata)
    
    def test_get_stats(self):
        """Test getting statistics."""
        manager = CausalOrderingManager(node_id="test")
        manager.create_event_metadata()
        
        stats = manager.get_stats()
        assert stats["node_id"] == "test"
        assert stats["lamport_time"] == 1


class TestCausalEventMetadata:
    """Tests for CausalEventMetadata dataclass."""
    
    def test_to_dict(self):
        """Test serialization."""
        metadata = CausalEventMetadata(
            lamport_time=5,
            vector_clock={"node1": 3, "node2": 2},
            causal_deps=["evt-1", "evt-2"],
            node_id="test"
        )
        
        data = metadata.to_dict()
        assert data["lamport_time"] == 5
        assert data["vector_clock"] == {"node1": 3, "node2": 2}
        assert data["causal_deps"] == ["evt-1", "evt-2"]
    
    def test_from_dict(self):
        """Test deserialization."""
        data = {
            "lamport_time": 10,
            "vector_clock": {"node1": 5},
            "causal_deps": [],
            "node_id": "test"
        }
        
        metadata = CausalEventMetadata.from_dict(data)
        assert metadata.lamport_time == 10
        assert metadata.vector_clock == {"node1": 5}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
