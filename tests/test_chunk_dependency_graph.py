"""
Tests for Chunk Dependency Graph (ITEM-FEAT-74).

Tests the dependency graph functionality for:
- Chunk status tracking
- Dependency resolution
- Parallel processing determination
- Partial recovery computation
- Checkpoint serialization

Author: TITAN FUSE Team
Version: 4.0.0
"""

import pytest
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from context.chunk_dependency_graph import (
    ChunkDependencyGraph,
    ChunkStatus,
    ChunkNode,
    DependencyGraphStats,
    create_dependency_graph
)
from events.event_bus import EventBus, Event, EventSeverity


class TestChunkStatus:
    """Tests for ChunkStatus enum."""
    
    def test_status_values(self):
        """Test that all required statuses exist."""
        assert ChunkStatus.PENDING.value == "pending"
        assert ChunkStatus.READY.value == "ready"
        assert ChunkStatus.IN_PROGRESS.value == "in_progress"
        assert ChunkStatus.COMPLETED.value == "completed"
        assert ChunkStatus.FAILED.value == "failed"
        assert ChunkStatus.SKIPPED.value == "skipped"
    
    def test_is_terminal(self):
        """Test terminal state detection."""
        assert ChunkStatus.PENDING.is_terminal() is False
        assert ChunkStatus.READY.is_terminal() is False
        assert ChunkStatus.IN_PROGRESS.is_terminal() is False
        assert ChunkStatus.COMPLETED.is_terminal() is True
        assert ChunkStatus.FAILED.is_terminal() is True
        assert ChunkStatus.SKIPPED.is_terminal() is True
    
    def test_is_processable(self):
        """Test processable state detection."""
        assert ChunkStatus.PENDING.is_processable() is False
        assert ChunkStatus.READY.is_processable() is True
        assert ChunkStatus.IN_PROGRESS.is_processable() is False
        assert ChunkStatus.COMPLETED.is_processable() is False
        assert ChunkStatus.FAILED.is_processable() is True  # Can retry
        assert ChunkStatus.SKIPPED.is_processable() is False


class TestChunkNode:
    """Tests for ChunkNode dataclass."""
    
    def test_init_defaults(self):
        """Test default initialization."""
        node = ChunkNode(chunk_id="test_chunk")
        
        assert node.chunk_id == "test_chunk"
        assert node.dependencies == set()
        assert node.status == ChunkStatus.PENDING
        assert node.error_message is None
        assert node.retry_count == 0
        assert node.max_retries == 3
        assert node.metadata == {}
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        node = ChunkNode(
            chunk_id="chunk_1",
            dependencies={"dep_1", "dep_2"},
            status=ChunkStatus.COMPLETED,
            retry_count=2,
            metadata={"size": 1000}
        )
        
        d = node.to_dict()
        
        assert d["chunk_id"] == "chunk_1"
        assert set(d["dependencies"]) == {"dep_1", "dep_2"}
        assert d["status"] == "completed"
        assert d["retry_count"] == 2
        assert d["metadata"]["size"] == 1000
    
    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "chunk_id": "chunk_2",
            "dependencies": ["dep_1"],
            "status": "failed",
            "error_message": "Processing failed",
            "retry_count": 3,
            "max_retries": 5,
            "metadata": {"type": "code"}
        }
        
        node = ChunkNode.from_dict(data)
        
        assert node.chunk_id == "chunk_2"
        assert node.dependencies == {"dep_1"}
        assert node.status == ChunkStatus.FAILED
        assert node.error_message == "Processing failed"
        assert node.retry_count == 3
        assert node.max_retries == 5
    
    def test_update_status(self):
        """Test status update."""
        node = ChunkNode(chunk_id="test")
        
        node.update_status(ChunkStatus.IN_PROGRESS)
        assert node.status == ChunkStatus.IN_PROGRESS
        
        node.update_status(ChunkStatus.COMPLETED)
        assert node.status == ChunkStatus.COMPLETED


class TestDependencyGraphStats:
    """Tests for DependencyGraphStats."""
    
    def test_init_defaults(self):
        """Test default initialization."""
        stats = DependencyGraphStats()
        
        assert stats.total_chunks == 0
        assert stats.pending_count == 0
        assert stats.completed_count == 0
        assert stats.failed_count == 0
    
    def test_to_dict(self):
        """Test serialization."""
        stats = DependencyGraphStats(
            total_chunks=10,
            pending_count=3,
            completed_count=5,
            failed_count=2
        )
        
        d = stats.to_dict()
        
        assert d["total_chunks"] == 10
        assert d["pending_count"] == 3
        assert d["completed_count"] == 5
        assert d["failed_count"] == 2


class TestChunkDependencyGraph:
    """Tests for ChunkDependencyGraph class."""
    
    def test_init(self):
        """Test graph initialization."""
        graph = ChunkDependencyGraph()
        
        assert len(graph) == 0
        assert graph.get_all_chunks() == []
    
    def test_add_chunk_no_dependencies(self):
        """Test adding a chunk with no dependencies."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        
        assert "chunk_1" in graph
        assert graph.get_dependencies("chunk_1") == []
        assert graph.get_dependents("chunk_1") == []
    
    def test_add_chunk_with_dependencies(self):
        """Test adding a chunk with dependencies."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", ["chunk_1"])
        graph.add_chunk("chunk_3", ["chunk_1"])
        
        assert graph.get_dependencies("chunk_2") == ["chunk_1"]
        assert graph.get_dependencies("chunk_3") == ["chunk_1"]
        assert sorted(graph.get_dependents("chunk_1")) == ["chunk_2", "chunk_3"]
    
    def test_get_dependencies_nonexistent(self):
        """Test getting dependencies for nonexistent chunk."""
        graph = ChunkDependencyGraph()
        
        deps = graph.get_dependencies("nonexistent")
        assert deps == []
    
    def test_can_process_no_dependencies(self):
        """Test can_process with no dependencies."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        
        assert graph.can_process("chunk_1", set()) is True
    
    def test_can_process_with_dependencies(self):
        """Test can_process with unsatisfied dependencies."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", ["chunk_1"])
        
        # Dependencies not satisfied
        assert graph.can_process("chunk_2", set()) is False
        
        # Dependencies satisfied
        assert graph.can_process("chunk_2", {"chunk_1"}) is True
    
    def test_can_process_nonexistent(self):
        """Test can_process for nonexistent chunk."""
        graph = ChunkDependencyGraph()
        
        assert graph.can_process("nonexistent", set()) is False
    
    def test_get_parallel_chunks(self):
        """Test getting parallel chunks."""
        graph = ChunkDependencyGraph()
        
        # Linear dependency: 1 -> 2 -> 3
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", ["chunk_1"])
        graph.add_chunk("chunk_3", ["chunk_2"])
        
        # Only chunk_1 can be processed initially
        parallel = graph.get_parallel_chunks(set())
        assert parallel == ["chunk_1"]
        
        # After chunk_1 completes, chunk_2 can be processed
        parallel = graph.get_parallel_chunks({"chunk_1"})
        assert parallel == ["chunk_2"]
        
        # After chunk_1 and chunk_2 complete, chunk_3 can be processed
        parallel = graph.get_parallel_chunks({"chunk_1", "chunk_2"})
        assert parallel == ["chunk_3"]
    
    def test_get_parallel_chunks_multiple(self):
        """Test getting multiple parallel chunks."""
        graph = ChunkDependencyGraph()
        
        # Diamond dependency:
        #       1
        #      / \
        #     2   3
        #      \ /
        #       4
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", ["chunk_1"])
        graph.add_chunk("chunk_3", ["chunk_1"])
        graph.add_chunk("chunk_4", ["chunk_2", "chunk_3"])
        
        # Only chunk_1 initially
        parallel = graph.get_parallel_chunks(set())
        assert parallel == ["chunk_1"]
        
        # chunk_2 and chunk_3 can be processed in parallel after chunk_1
        parallel = graph.get_parallel_chunks({"chunk_1"})
        assert sorted(parallel) == ["chunk_2", "chunk_3"]
        
        # After chunk_2 and chunk_3, only chunk_4
        parallel = graph.get_parallel_chunks({"chunk_1", "chunk_2", "chunk_3"})
        assert parallel == ["chunk_4"]
    
    def test_get_recovery_chunks_single(self):
        """Test recovery set for single failed chunk."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        
        recovery = graph.get_recovery_chunks("chunk_1")
        assert recovery == ["chunk_1"]
    
    def test_get_recovery_chunks_with_dependents(self):
        """Test recovery set includes dependents."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", ["chunk_1"])
        graph.add_chunk("chunk_3", ["chunk_1"])
        graph.add_chunk("chunk_4", ["chunk_2"])
        
        recovery = graph.get_recovery_chunks("chunk_1")
        assert sorted(recovery) == ["chunk_1", "chunk_2", "chunk_3", "chunk_4"]
        
        recovery = graph.get_recovery_chunks("chunk_2")
        assert sorted(recovery) == ["chunk_2", "chunk_4"]
    
    def test_get_recovery_chunks_nonexistent(self):
        """Test recovery set for nonexistent chunk."""
        graph = ChunkDependencyGraph()
        
        recovery = graph.get_recovery_chunks("nonexistent")
        assert recovery == []
    
    def test_update_status(self):
        """Test updating chunk status."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        
        assert graph.get_chunk_status("chunk_1") == ChunkStatus.PENDING
        
        result = graph.update_status("chunk_1", ChunkStatus.IN_PROGRESS)
        assert result is True
        assert graph.get_chunk_status("chunk_1") == ChunkStatus.IN_PROGRESS
        
        result = graph.update_status("chunk_1", ChunkStatus.COMPLETED)
        assert result is True
        assert graph.get_chunk_status("chunk_1") == ChunkStatus.COMPLETED
    
    def test_update_status_nonexistent(self):
        """Test updating status for nonexistent chunk."""
        graph = ChunkDependencyGraph()
        
        result = graph.update_status("nonexistent", ChunkStatus.COMPLETED)
        assert result is False
    
    def test_update_status_marks_dependents_skipped(self):
        """Test that failed chunk causes dependents to be skipped."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", ["chunk_1"])
        graph.add_chunk("chunk_3", ["chunk_2"])
        
        graph.update_status("chunk_1", ChunkStatus.FAILED, "Processing error")
        
        assert graph.get_chunk_status("chunk_1") == ChunkStatus.FAILED
        assert graph.get_chunk_status("chunk_2") == ChunkStatus.SKIPPED
        assert graph.get_chunk_status("chunk_3") == ChunkStatus.SKIPPED
    
    def test_get_stats(self):
        """Test getting graph statistics."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", [])
        graph.add_chunk("chunk_3", [])
        
        graph.update_status("chunk_1", ChunkStatus.COMPLETED)
        graph.update_status("chunk_2", ChunkStatus.FAILED)
        
        stats = graph.get_stats()
        
        assert stats.total_chunks == 3
        assert stats.completed_count == 1
        assert stats.failed_count == 1
        assert stats.pending_count == 1
    
    def test_is_complete(self):
        """Test checking if graph is complete."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", [])
        
        assert graph.is_complete() is False
        
        graph.update_status("chunk_1", ChunkStatus.COMPLETED)
        assert graph.is_complete() is False
        
        graph.update_status("chunk_2", ChunkStatus.COMPLETED)
        assert graph.is_complete() is True
    
    def test_completion_percentage(self):
        """Test completion percentage calculation."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", [])
        graph.add_chunk("chunk_3", [])
        graph.add_chunk("chunk_4", [])
        
        assert graph.get_completion_percentage() == 0.0
        
        graph.update_status("chunk_1", ChunkStatus.COMPLETED)
        assert graph.get_completion_percentage() == 25.0
        
        graph.update_status("chunk_2", ChunkStatus.COMPLETED)
        assert graph.get_completion_percentage() == 50.0
        
        graph.update_status("chunk_3", ChunkStatus.COMPLETED)
        graph.update_status("chunk_4", ChunkStatus.COMPLETED)
        assert graph.get_completion_percentage() == 100.0
    
    def test_update_ready_status(self):
        """Test updating ready status for pending chunks."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", ["chunk_1"])
        graph.add_chunk("chunk_3", ["chunk_1"])
        
        # Initially only chunk_1 has satisfied dependencies
        updated = graph.update_ready_status()
        assert updated == 1  # Only chunk_1
        assert graph.get_chunk_status("chunk_1") == ChunkStatus.READY
        assert graph.get_chunk_status("chunk_2") == ChunkStatus.PENDING
        
        # Complete chunk_1
        graph.update_status("chunk_1", ChunkStatus.COMPLETED)
        
        # Now chunk_2 and chunk_3 should be ready
        updated = graph.update_ready_status()
        assert updated == 2
    
    def test_get_ready_chunks(self):
        """Test getting ready chunks."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", [])
        
        graph.update_status("chunk_1", ChunkStatus.READY)
        
        ready = graph.get_ready_chunks()
        assert "chunk_1" in ready
        assert "chunk_2" not in ready  # Still PENDING


class TestChunkDependencyGraphSerialization:
    """Tests for serialization and deserialization."""
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", ["chunk_1"])
        graph.update_status("chunk_1", ChunkStatus.COMPLETED)
        
        d = graph.to_dict()
        
        assert "version" in d
        assert "chunks" in d
        assert "chunk_1" in d["chunks"]
        assert "chunk_2" in d["chunks"]
        assert d["chunks"]["chunk_1"]["status"] == "completed"
    
    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "version": "4.0.0",
            "chunks": {
                "chunk_1": {
                    "chunk_id": "chunk_1",
                    "dependencies": [],
                    "status": "completed",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "retry_count": 0,
                    "max_retries": 3,
                    "metadata": {}
                },
                "chunk_2": {
                    "chunk_id": "chunk_2",
                    "dependencies": ["chunk_1"],
                    "status": "pending",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "retry_count": 0,
                    "max_retries": 3,
                    "metadata": {}
                }
            }
        }
        
        graph = ChunkDependencyGraph.from_dict(data)
        
        assert len(graph) == 2
        assert graph.get_chunk_status("chunk_1") == ChunkStatus.COMPLETED
        assert graph.get_chunk_status("chunk_2") == ChunkStatus.PENDING
        assert graph.get_dependencies("chunk_2") == ["chunk_1"]
        assert graph.get_dependents("chunk_1") == ["chunk_2"]
    
    def test_to_json(self):
        """Test serialization to JSON."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        
        json_str = graph.to_json()
        
        assert '"chunk_1"' in json_str
        assert '"version"' in json_str
    
    def test_from_json(self):
        """Test deserialization from JSON."""
        graph = ChunkDependencyGraph()
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", ["chunk_1"])
        
        json_str = graph.to_json()
        restored = ChunkDependencyGraph.from_json(json_str)
        
        assert len(restored) == 2
        assert restored.get_dependencies("chunk_2") == ["chunk_1"]
    
    def test_roundtrip(self):
        """Test serialization roundtrip."""
        graph = ChunkDependencyGraph()
        
        # Create a complex graph
        graph.add_chunk("chunk_1", [], metadata={"type": "header"})
        graph.add_chunk("chunk_2", ["chunk_1"], metadata={"type": "body"})
        graph.add_chunk("chunk_3", ["chunk_1"], metadata={"type": "body"})
        graph.add_chunk("chunk_4", ["chunk_2", "chunk_3"], metadata={"type": "footer"})
        
        graph.update_status("chunk_1", ChunkStatus.COMPLETED)
        graph.update_status("chunk_2", ChunkStatus.IN_PROGRESS)
        
        # Roundtrip
        restored = ChunkDependencyGraph.from_dict(graph.to_dict())
        
        assert len(restored) == len(graph)
        assert restored.get_chunk_status("chunk_1") == ChunkStatus.COMPLETED
        assert restored.get_chunk_status("chunk_2") == ChunkStatus.IN_PROGRESS
        assert sorted(restored.get_dependencies("chunk_4")) == ["chunk_2", "chunk_3"]


class TestChunkDependencyGraphAdvanced:
    """Tests for advanced graph operations."""
    
    def test_get_critical_path(self):
        """Test critical path calculation."""
        graph = ChunkDependencyGraph()
        
        # Linear path: 1 -> 2 -> 3
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", ["chunk_1"])
        graph.add_chunk("chunk_3", ["chunk_2"])
        
        path = graph.get_critical_path()
        assert path == ["chunk_1", "chunk_2", "chunk_3"]
    
    def test_get_critical_path_diamond(self):
        """Test critical path with diamond dependency."""
        graph = ChunkDependencyGraph()
        
        # Diamond: 1 -> 2 -> 4, 1 -> 3 -> 4
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", ["chunk_1"])
        graph.add_chunk("chunk_3", ["chunk_1"])
        graph.add_chunk("chunk_4", ["chunk_2", "chunk_3"])
        
        path = graph.get_critical_path()
        # Critical path should start with chunk_1 and end with chunk_4
        # In a diamond shape, the path length is 3 (one of the branches)
        assert len(path) >= 3
        assert path[0] == "chunk_1"
        assert path[-1] == "chunk_4"
    
    def test_get_processing_order(self):
        """Test topological sort for processing order."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_3", ["chunk_1", "chunk_2"])
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", ["chunk_1"])
        
        order = graph.get_processing_order()
        
        # chunk_1 must come before chunk_2 and chunk_3
        assert order.index("chunk_1") < order.index("chunk_2")
        assert order.index("chunk_1") < order.index("chunk_3")
        assert order.index("chunk_2") < order.index("chunk_3")
    
    def test_clear(self):
        """Test clearing the graph."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", ["chunk_1"])
        
        graph.clear()
        
        assert len(graph) == 0
        assert graph.get_all_chunks() == []
    
    def test_remove_chunk(self):
        """Test removing a chunk."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", ["chunk_1"])
        
        result = graph.remove_chunk("chunk_1")
        
        assert result is True
        assert "chunk_1" not in graph
        # Note: chunk_2 still has chunk_1 as a dependency
        assert "chunk_1" in graph.get_dependencies("chunk_2")
    
    def test_remove_chunk_nonexistent(self):
        """Test removing nonexistent chunk."""
        graph = ChunkDependencyGraph()
        
        result = graph.remove_chunk("nonexistent")
        assert result is False


class TestChunkDependencyGraphEventBus:
    """Tests for EventBus integration."""
    
    def test_emit_chunk_added_event(self):
        """Test that CHUNK_ADDED event is emitted."""
        event_bus = EventBus()
        graph = ChunkDependencyGraph(event_bus=event_bus)
        
        emitted_events = []
        
        def handler(event: Event):
            emitted_events.append(event)
        
        event_bus.subscribe("CHUNK_ADDED", handler)
        
        graph.add_chunk("chunk_1", [])
        
        assert len(emitted_events) == 1
        assert emitted_events[0].event_type == "CHUNK_ADDED"
        assert emitted_events[0].data["chunk_id"] == "chunk_1"
    
    def test_emit_status_changed_event(self):
        """Test that CHUNK_STATUS_CHANGED event is emitted."""
        event_bus = EventBus()
        graph = ChunkDependencyGraph(event_bus=event_bus)
        
        emitted_events = []
        
        def handler(event: Event):
            emitted_events.append(event)
        
        event_bus.subscribe("CHUNK_STATUS_CHANGED", handler)
        
        graph.add_chunk("chunk_1", [])
        graph.update_status("chunk_1", ChunkStatus.COMPLETED)
        
        # Give time for async dispatch
        import time
        time.sleep(0.1)
        
        # Event should be emitted (may include other events)
        status_events = [e for e in emitted_events if e.event_type == "CHUNK_STATUS_CHANGED"]
        assert len(status_events) >= 1
        assert status_events[0].data["old_status"] == "pending"
        assert status_events[0].data["new_status"] == "completed"
    
    def test_emit_recovery_computed_event(self):
        """Test that RECOVERY_COMPUTED event is emitted."""
        event_bus = EventBus()
        graph = ChunkDependencyGraph(event_bus=event_bus)
        
        emitted_events = []
        
        def handler(event: Event):
            emitted_events.append(event)
        
        event_bus.subscribe("RECOVERY_COMPUTED", handler)
        
        graph.add_chunk("chunk_1", [])
        graph.get_recovery_chunks("chunk_1")
        
        # Give time for async dispatch
        import time
        time.sleep(0.1)
        
        # Event should be emitted
        recovery_events = [e for e in emitted_events if e.event_type == "RECOVERY_COMPUTED"]
        assert len(recovery_events) >= 1
    
    def test_without_event_bus(self):
        """Test that graph works without EventBus."""
        graph = ChunkDependencyGraph()
        
        # Should not raise errors
        graph.add_chunk("chunk_1", [])
        graph.update_status("chunk_1", ChunkStatus.COMPLETED)
        graph.get_recovery_chunks("chunk_1")
        
        assert graph.get_chunk_status("chunk_1") == ChunkStatus.COMPLETED


class TestFactoryFunction:
    """Tests for factory function."""
    
    def test_create_dependency_graph(self):
        """Test create_dependency_graph factory."""
        graph = create_dependency_graph()
        
        assert isinstance(graph, ChunkDependencyGraph)
        assert len(graph) == 0
    
    def test_create_dependency_graph_with_event_bus(self):
        """Test factory with EventBus."""
        event_bus = EventBus()
        graph = create_dependency_graph(event_bus=event_bus)
        
        assert graph._event_bus is event_bus


class TestRetryLogic:
    """Tests for retry logic."""
    
    def test_retry_count_increments(self):
        """Test that retry count increments on failure."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [])
        
        node = graph.get_chunk_node("chunk_1")
        assert node.retry_count == 0
        
        graph.update_status("chunk_1", ChunkStatus.FAILED)
        assert node.retry_count == 1
        
        graph.update_status("chunk_1", ChunkStatus.FAILED)
        assert node.retry_count == 2
    
    def test_max_retries_warning(self, caplog):
        """Test warning when max retries exceeded."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [], max_retries=2)
        
        graph.update_status("chunk_1", ChunkStatus.FAILED)
        graph.update_status("chunk_1", ChunkStatus.FAILED)
        
        # Third failure should trigger warning
        graph.update_status("chunk_1", ChunkStatus.FAILED)
        
        # Check that retry count equals max_retries
        node = graph.get_chunk_node("chunk_1")
        assert node.retry_count >= node.max_retries


class TestChunkNodeMetadata:
    """Tests for chunk metadata handling."""
    
    def test_metadata_persistence(self):
        """Test that metadata persists through serialization."""
        graph = ChunkDependencyGraph()
        
        graph.add_chunk("chunk_1", [], metadata={
            "size": 5000,
            "type": "code",
            "language": "python"
        })
        
        # Roundtrip
        restored = ChunkDependencyGraph.from_dict(graph.to_dict())
        
        node = restored.get_chunk_node("chunk_1")
        assert node.metadata["size"] == 5000
        assert node.metadata["type"] == "code"
        assert node.metadata["language"] == "python"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
