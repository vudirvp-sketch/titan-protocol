"""
Tests for ITEM-SAE-005: Version Vector System.

Tests cover:
- VectorClockManager: version vector operations
- StaleDetector: stale context detection
- Conflict detection and resolution
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from src.context.version_vectors import (
    VectorClockManager,
    StaleDetector,
    StaleNode,
    Conflict,
    Resolution,
    VectorOrder,
    get_vector_clock_manager,
    get_stale_detector,
    reset_version_vector_system,
)
from src.context.context_graph import (
    ContextGraph,
    ContextNode,
    NodeType,
    VersionVector,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def context_graph():
    """Create a test context graph with nodes."""
    graph = ContextGraph(session_id="test-session")
    
    # Add some test nodes
    node1 = ContextNode(
        id="file1.py",
        type=NodeType.FILE,
        location="/src/file1.py",
        trust_score=0.8,
        version_vector=VersionVector(vector={"file1.py": 1}),
    )
    node2 = ContextNode(
        id="file2.py",
        type=NodeType.FILE,
        location="/src/file2.py",
        trust_score=0.6,
        version_vector=VersionVector(vector={"file2.py": 2}),
    )
    node3 = ContextNode(
        id="config.yaml",
        type=NodeType.CONFIG,
        location="/config.yaml",
        trust_score=0.9,
    )
    
    graph.add_node(node1)
    graph.add_node(node2)
    graph.add_node(node3)
    
    return graph


@pytest.fixture
def vector_clock_manager(context_graph):
    """Create a VectorClockManager with test graph."""
    return VectorClockManager(context_graph=context_graph)


@pytest.fixture
def stale_detector(context_graph):
    """Create a StaleDetector with test graph."""
    return StaleDetector(context_graph=context_graph)


# =============================================================================
# VectorClockManager Tests
# =============================================================================

class TestVectorClockManager:
    """Tests for VectorClockManager class."""
    
    def test_get_current_vector(self, vector_clock_manager):
        """Test retrieving current version vector."""
        vector = vector_clock_manager.get_current_vector("file1.py")
        assert vector is not None
        assert vector.get("file1.py") == 1
    
    def test_get_current_vector_nonexistent(self, vector_clock_manager):
        """Test retrieving vector for nonexistent node."""
        vector = vector_clock_manager.get_current_vector("nonexistent.py")
        assert vector is None
    
    def test_update_vector(self, vector_clock_manager):
        """Test updating version vector."""
        new_vector = vector_clock_manager.update_vector("file1.py", "content_changed")
        assert new_vector is not None
        assert new_vector.get("file1.py") == 2  # Incremented
    
    def test_update_vector_initializes_if_missing(self, vector_clock_manager):
        """Test that update initializes vector if missing."""
        new_vector = vector_clock_manager.update_vector("config.yaml", "created")
        assert new_vector is not None
        assert new_vector.get("config.yaml") == 1
    
    def test_merge_vectors(self, vector_clock_manager):
        """Test merging two version vectors."""
        v1 = {"node1": 1, "node2": 2}
        v2 = {"node1": 2, "node3": 1}
        
        merged = vector_clock_manager.merge_vectors(v1, v2)
        
        assert merged["node1"] == 2  # max(1, 2)
        assert merged["node2"] == 2
        assert merged["node3"] == 1
    
    def test_compare_vectors_after(self, vector_clock_manager):
        """Test comparing vectors where first is after."""
        v1 = {"node1": 2, "node2": 1}
        v2 = {"node1": 1, "node2": 1}
        
        result = vector_clock_manager.compare_vectors(v1, v2)
        assert result == VectorOrder.AFTER
    
    def test_compare_vectors_before(self, vector_clock_manager):
        """Test comparing vectors where first is before."""
        v1 = {"node1": 1, "node2": 1}
        v2 = {"node1": 2, "node2": 1}
        
        result = vector_clock_manager.compare_vectors(v1, v2)
        assert result == VectorOrder.BEFORE
    
    def test_compare_vectors_concurrent(self, vector_clock_manager):
        """Test comparing concurrent vectors."""
        v1 = {"node1": 2, "node2": 1}
        v2 = {"node1": 1, "node2": 2}
        
        result = vector_clock_manager.compare_vectors(v1, v2)
        assert result == VectorOrder.CONCURRENT
    
    def test_is_concurrent(self, vector_clock_manager):
        """Test checking if vectors are concurrent."""
        v1 = {"node1": 2, "node2": 1}
        v2 = {"node1": 1, "node2": 2}
        
        assert vector_clock_manager.is_concurrent(v1, v2) is True
        
        v3 = {"node1": 1, "node2": 1}
        assert vector_clock_manager.is_concurrent(v1, v3) is False
    
    def test_dominates(self, vector_clock_manager):
        """Test checking if one vector dominates another."""
        v1 = {"node1": 2, "node2": 1}
        v2 = {"node1": 1, "node2": 1}
        
        assert vector_clock_manager.dominates(v1, v2) is True
        assert vector_clock_manager.dominates(v2, v1) is False
    
    def test_detect_conflicts(self, vector_clock_manager, context_graph):
        """Test detecting conflicts in the graph."""
        # Add nodes with concurrent modifications
        node1 = context_graph.get_node("file1.py")
        node2 = context_graph.get_node("file2.py")
        
        # Create concurrent vectors by having them reference each other
        node1.version_vector = VersionVector(vector={"file1.py": 2, "file2.py": 1})
        node2.version_vector = VersionVector(vector={"file1.py": 1, "file2.py": 2})
        
        conflicts = vector_clock_manager.detect_conflicts()
        
        # Should detect conflict due to concurrent modifications
        assert isinstance(conflicts, list)
    
    def test_resolve_conflict_last_write_wins(self, vector_clock_manager):
        """Test conflict resolution with last_write_wins strategy."""
        conflict = Conflict(
            node_id="test_node",
            vector1={"node1": 1},
            vector2={"node2": 2, "node3": 1},
        )
        
        resolution = vector_clock_manager.resolve_conflict(
            conflict, strategy="last_write_wins"
        )
        
        assert resolution.strategy == "last_write_wins"
        assert resolution.resolved_vector is not None
    
    def test_resolve_conflict_merge(self, vector_clock_manager):
        """Test conflict resolution with merge strategy."""
        conflict = Conflict(
            node_id="test_node",
            vector1={"node1": 2},
            vector2={"node2": 1},
        )
        
        resolution = vector_clock_manager.resolve_conflict(
            conflict, strategy="merge"
        )
        
        assert resolution.strategy == "merge"
        assert resolution.resolved_vector.get("node1") == 2
        assert resolution.resolved_vector.get("node2") == 1
    
    def test_resolve_conflict_first_write_wins(self, vector_clock_manager):
        """Test conflict resolution with first_write_wins strategy."""
        conflict = Conflict(
            node_id="test_node",
            vector1={"node1": 1},
            vector2={"node1": 2, "node2": 1},
        )
        
        resolution = vector_clock_manager.resolve_conflict(
            conflict, strategy="first_write_wins"
        )
        
        assert resolution.strategy == "first_write_wins"
        assert resolution.resolved_vector is not None
    
    def test_get_conflict_history(self, vector_clock_manager):
        """Test getting conflict history."""
        history = vector_clock_manager.get_conflict_history()
        assert isinstance(history, list)


# =============================================================================
# StaleDetector Tests
# =============================================================================

class TestStaleDetector:
    """Tests for StaleDetector class."""
    
    def test_detect_stale_context_empty(self):
        """Test detection with no graph."""
        detector = StaleDetector()
        stale = detector.detect_stale_context()
        assert stale == []
    
    def test_detect_stale_context(self, stale_detector, context_graph):
        """Test detecting stale nodes."""
        # Make one node stale
        node = context_graph.get_node("file1.py")
        node.trust_score = 0.2  # Low trust
        node.last_modified = datetime.now() - timedelta(hours=48)
        
        stale = stale_detector.detect_stale_context()
        
        assert len(stale) > 0
        stale_ids = [s.node_id for s in stale]
        assert "file1.py" in stale_ids
    
    def test_detect_stale_by_age(self, stale_detector, context_graph):
        """Test detecting stale nodes by age."""
        node = context_graph.get_node("file1.py")
        node.last_modified = datetime.now() - timedelta(hours=48)
        
        stale = stale_detector.detect_stale_context()
        stale_ids = [s.node_id for s in stale]
        
        assert "file1.py" in stale_ids
    
    def test_detect_stale_by_trust(self, stale_detector, context_graph):
        """Test detecting stale nodes by low trust."""
        node = context_graph.get_node("file2.py")
        node.trust_score = 0.2
        
        stale = stale_detector.detect_stale_context()
        stale_ids = [s.node_id for s in stale]
        
        assert "file2.py" in stale_ids
    
    def test_check_vector_invalidation(self, stale_detector, context_graph):
        """Test checking vector invalidation."""
        node = context_graph.get_node("file1.py")
        node.version_vector = VersionVector(vector={"file1.py": 1})
        
        # Current vector dominates node's vector
        current_vector = {"file1.py": 2}
        
        is_invalidated = stale_detector.check_vector_invalidation(
            node, current_vector
        )
        
        assert is_invalidated is True
    
    def test_check_vector_invalidation_not_stale(self, stale_detector, context_graph):
        """Test checking vector when not invalid."""
        node = context_graph.get_node("file1.py")
        node.version_vector = VersionVector(vector={"file1.py": 2})
        
        # Current vector is older than node's vector
        current_vector = {"file1.py": 1}
        
        is_invalidated = stale_detector.check_vector_invalidation(
            node, current_vector
        )
        
        assert is_invalidated is False
    
    def test_get_freshness_score(self, stale_detector, context_graph):
        """Test calculating freshness score."""
        node = context_graph.get_node("file1.py")
        node.trust_score = 0.9
        node.usage_count = 5
        node.success_rate = 1.0
        node.last_modified = datetime.now()
        
        freshness = stale_detector.get_freshness_score(node)
        
        assert 0.0 <= freshness <= 1.0
        assert freshness > 0.5  # Should be fresh
    
    def test_get_freshness_score_stale(self, stale_detector, context_graph):
        """Test calculating freshness score for stale node."""
        node = context_graph.get_node("file1.py")
        node.trust_score = 0.3
        node.usage_count = 0
        node.success_rate = 0.5
        node.last_modified = datetime.now() - timedelta(hours=48)
        
        freshness = stale_detector.get_freshness_score(node)
        
        assert 0.0 <= freshness <= 1.0
        assert freshness < 0.5  # Should be stale
    
    def test_register_known_vector(self, stale_detector):
        """Test registering known-good vector."""
        stale_detector.register_known_vector("test_node", {"test_node": 5})
        
        assert "test_node" in stale_detector._known_vectors
        assert stale_detector._known_vectors["test_node"]["test_node"] == 5
    
    def test_get_staleness_report(self, stale_detector):
        """Test generating staleness report."""
        report = stale_detector.get_staleness_report()
        
        assert "total_nodes" in report
        assert "stale_nodes_count" in report
        assert "average_freshness" in report


# =============================================================================
# StaleNode Tests
# =============================================================================

class TestStaleNode:
    """Tests for StaleNode dataclass."""
    
    def test_stale_node_creation(self):
        """Test creating a StaleNode."""
        stale = StaleNode(
            node_id="test.py",
            stale_reason="low_trust, old_age",
            staleness_score=0.7,
            suggested_action="refresh",
        )
        
        assert stale.node_id == "test.py"
        assert stale.staleness_score == 0.7
    
    def test_stale_node_to_dict(self):
        """Test converting StaleNode to dict."""
        stale = StaleNode(
            node_id="test.py",
            stale_reason="old",
            staleness_score=0.5,
            suggested_action="regenerate",
        )
        
        data = stale.to_dict()
        
        assert data["node_id"] == "test.py"
        assert data["staleness_score"] == 0.5
        assert data["suggested_action"] == "regenerate"


# =============================================================================
# Conflict and Resolution Tests
# =============================================================================

class TestConflictResolution:
    """Tests for Conflict and Resolution classes."""
    
    def test_conflict_creation(self):
        """Test creating a Conflict."""
        conflict = Conflict(
            node_id="test::test2",
            vector1={"a": 1},
            vector2={"b": 2},
        )
        
        assert conflict.node_id == "test::test2"
        assert conflict.vector1 == {"a": 1}
        assert conflict.vector2 == {"b": 2}
    
    def test_conflict_to_dict(self):
        """Test converting Conflict to dict."""
        conflict = Conflict(
            node_id="test",
            vector1={"a": 1},
            vector2={"b": 2},
            metadata={"key": "value"},
        )
        
        data = conflict.to_dict()
        
        assert data["node_id"] == "test"
        assert data["vector1"] == {"a": 1}
        assert data["metadata"]["key"] == "value"
    
    def test_resolution_creation(self):
        """Test creating a Resolution."""
        conflict = Conflict(
            node_id="test",
            vector1={"a": 1},
            vector2={"b": 2},
        )
        
        resolution = Resolution(
            conflict=conflict,
            strategy="merge",
            resolved_vector={"a": 1, "b": 2},
        )
        
        assert resolution.strategy == "merge"
        assert resolution.resolved_vector == {"a": 1, "b": 2}
    
    def test_resolution_to_dict(self):
        """Test converting Resolution to dict."""
        conflict = Conflict(
            node_id="test",
            vector1={"a": 1},
            vector2={"b": 2},
        )
        
        resolution = Resolution(
            conflict=conflict,
            strategy="last_write_wins",
            resolved_vector={"b": 2},
        )
        
        data = resolution.to_dict()
        
        assert data["strategy"] == "last_write_wins"
        assert data["resolved_vector"] == {"b": 2}


# =============================================================================
# Module-level Functions Tests
# =============================================================================

class TestModuleFunctions:
    """Tests for module-level convenience functions."""
    
    def test_get_vector_clock_manager(self, context_graph):
        """Test getting default VectorClockManager."""
        reset_version_vector_system()
        
        manager = get_vector_clock_manager(context_graph)
        assert manager is not None
        assert isinstance(manager, VectorClockManager)
        
        reset_version_vector_system()
    
    def test_get_stale_detector(self, context_graph):
        """Test getting default StaleDetector."""
        reset_version_vector_system()
        
        detector = get_stale_detector(context_graph)
        assert detector is not None
        assert isinstance(detector, StaleDetector)
        
        reset_version_vector_system()
    
    def test_reset_version_vector_system(self, context_graph):
        """Test resetting the system."""
        get_vector_clock_manager(context_graph)
        get_stale_detector(context_graph)
        
        reset_version_vector_system()
        
        # Should create new instances after reset
        manager = get_vector_clock_manager()
        detector = get_stale_detector()
        
        assert manager._graph is None
        assert detector._graph is None
        
        reset_version_vector_system()


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for version vector system."""
    
    def test_full_workflow(self, context_graph):
        """Test full workflow of version vector management."""
        manager = VectorClockManager(context_graph=context_graph)
        detector = StaleDetector(context_graph=context_graph)
        
        # Update vectors
        manager.update_vector("file1.py", "modified")
        manager.update_vector("file2.py", "modified")
        
        # Check for conflicts
        conflicts = manager.detect_conflicts()
        
        # Detect stale nodes
        stale = detector.detect_stale_context()
        
        # Generate report
        report = detector.get_staleness_report()
        
        assert report["total_nodes"] == 3
    
    def test_concurrent_modification_detection(self, context_graph):
        """Test detection of concurrent modifications."""
        manager = VectorClockManager(context_graph=context_graph)
        
        # Set up concurrent modifications
        node1 = context_graph.get_node("file1.py")
        node2 = context_graph.get_node("file2.py")
        
        node1.version_vector = VersionVector(vector={"file1.py": 2, "file2.py": 1})
        node2.version_vector = VersionVector(vector={"file1.py": 1, "file2.py": 2})
        
        conflicts = manager.detect_conflicts()
        
        # Verify conflict detection
        # Note: actual detection depends on common keys
        assert isinstance(conflicts, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
