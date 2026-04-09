#!/usr/bin/env python3
"""
Tests for TITAN Self-Awareness Engine (SAE) Modules.

ITEM-SAE-003 through ITEM-SAE-008: Test Coverage

Tests for:
- ContextGraph (ITEM-SAE-003)
- TrustEngine (ITEM-SAE-004)
- VersionVectors (ITEM-SAE-005)
- SemanticChecksum (ITEM-SAE-006)
- DriftDetector (ITEM-SAE-007)
- RecursiveSummarizer (ITEM-SAE-008)

Author: TITAN FUSE Team
Version: 1.0.0
"""

import pytest
import tempfile
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch


# =============================================================================
# ITEM-SAE-003: Context Graph Tests
# =============================================================================

class TestContextGraph:
    """Tests for ContextGraph module."""
    
    def test_node_creation(self):
        """Test ContextNode creation with defaults."""
        from src.context.context_graph import ContextNode, NodeType
        
        node = ContextNode(
            id="test/file.py",
            type=NodeType.FILE,
            location="test/file.py"
        )
        
        assert node.id == "test/file.py"
        assert node.type == NodeType.FILE
        assert node.trust_score == 0.5  # Default
        assert node.usage_count == 0
        assert node.success_rate == 1.0
    
    def test_node_trust_tier(self):
        """Test trust tier classification."""
        from src.context.context_graph import ContextNode, NodeType, TrustTier
        
        # TIER_1_TRUSTED
        node1 = ContextNode(id="t1", type=NodeType.FILE, location="t1", trust_score=0.9)
        assert node1.trust_tier == TrustTier.TIER_1_TRUSTED
        
        # TIER_2_RELIABLE
        node2 = ContextNode(id="t2", type=NodeType.FILE, location="t2", trust_score=0.7)
        assert node2.trust_tier == TrustTier.TIER_2_RELIABLE
        
        # TIER_3_UNCERTAIN
        node3 = ContextNode(id="t3", type=NodeType.FILE, location="t3", trust_score=0.5)
        assert node3.trust_tier == TrustTier.TIER_3_UNCERTAIN
        
        # TIER_4_UNTRUSTED
        node4 = ContextNode(id="t4", type=NodeType.FILE, location="t4", trust_score=0.2)
        assert node4.trust_tier == TrustTier.TIER_4_UNTRUSTED
    
    def test_node_trust_update(self):
        """Test trust score updates with clamping."""
        from src.context.context_graph import ContextNode, NodeType
        
        node = ContextNode(id="test", type=NodeType.FILE, location="test", trust_score=0.5)
        
        # Increase trust
        node.update_trust(0.3)
        assert node.trust_score == 0.8
        
        # Try to exceed 1.0
        node.update_trust(0.5)
        assert node.trust_score == 1.0  # Clamped
        
        # Decrease trust
        node.update_trust(-0.3)
        assert node.trust_score == 0.7
        
        # Try to go below 0.0
        node.update_trust(-1.0)
        assert node.trust_score == 0.0  # Clamped
    
    def test_graph_add_node(self):
        """Test adding nodes to graph."""
        from src.context.context_graph import ContextGraph, ContextNode, NodeType
        
        graph = ContextGraph()
        node = ContextNode(id="test.py", type=NodeType.FILE, location="test.py")
        
        graph.add_node(node)
        
        assert graph.has_node("test.py")
        assert graph.get_node("test.py") == node
    
    def test_graph_add_edge(self):
        """Test adding edges to graph."""
        from src.context.context_graph import (
            ContextGraph, ContextNode, ContextEdge,
            NodeType, EdgeRelation
        )
        
        graph = ContextGraph()
        
        n1 = ContextNode(id="a.py", type=NodeType.FILE, location="a.py")
        n2 = ContextNode(id="b.py", type=NodeType.FILE, location="b.py")
        
        graph.add_node(n1)
        graph.add_node(n2)
        
        edge = ContextEdge(from_id="a.py", to_id="b.py", relation=EdgeRelation.IMPORTS)
        graph.add_edge(edge)
        
        edges = graph.get_edges_from("a.py")
        assert len(edges) == 1
        assert edges[0].to_id == "b.py"
    
    def test_graph_low_trust_nodes(self):
        """Test getting low trust nodes."""
        from src.context.context_graph import ContextGraph, ContextNode, NodeType
        
        graph = ContextGraph()
        
        # Add nodes with different trust scores
        for i, score in enumerate([0.9, 0.7, 0.3, 0.2]):
            node = ContextNode(
                id=f"file{i}.py",
                type=NodeType.FILE,
                location=f"file{i}.py",
                trust_score=score
            )
            graph.add_node(node)
        
        low_trust = graph.get_low_trust_nodes(threshold=0.5)
        assert len(low_trust) == 2
    
    def test_graph_serialization(self):
        """Test graph to_json and from_json."""
        from src.context.context_graph import (
            ContextGraph, ContextNode, ContextEdge,
            NodeType, EdgeRelation
        )
        
        graph = ContextGraph(session_id="test-session")
        
        n1 = ContextNode(id="a.py", type=NodeType.FILE, location="a.py", trust_score=0.8)
        n2 = ContextNode(id="b.py", type=NodeType.FILE, location="b.py", trust_score=0.6)
        
        graph.add_node(n1)
        graph.add_node(n2)
        
        edge = ContextEdge(from_id="a.py", to_id="b.py", relation=EdgeRelation.IMPORTS)
        graph.add_edge(edge)
        
        # Serialize
        json_str = graph.to_json()
        data = json.loads(json_str)
        
        assert data["version"] == "1.0.0"
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        
        # Deserialize
        graph2 = ContextGraph.from_json(json_str)
        assert graph2.has_node("a.py")
        assert graph2.has_node("b.py")
        assert graph2.session_id == "test-session"


class TestVersionVector:
    """Tests for VersionVector in context_graph module."""
    
    def test_version_vector_increment(self):
        """Test version vector increment."""
        from src.context.context_graph import VersionVector
        
        vv = VersionVector()
        vv.increment("node1")
        vv.increment("node1")
        vv.increment("node2")
        
        assert vv.vector["node1"] == 2
        assert vv.vector["node2"] == 1
    
    def test_version_vector_merge(self):
        """Test version vector merge."""
        from src.context.context_graph import VersionVector
        
        vv1 = VersionVector(vector={"a": 1, "b": 2})
        vv2 = VersionVector(vector={"a": 2, "c": 1})
        
        merged = vv1.merge(vv2)
        
        assert merged.vector["a"] == 2  # Max
        assert merged.vector["b"] == 2
        assert merged.vector["c"] == 1
    
    def test_version_vector_compare(self):
        """Test version vector comparison."""
        from src.context.context_graph import VersionVector
        
        vv1 = VersionVector(vector={"a": 1, "b": 2})
        vv2 = VersionVector(vector={"a": 2, "b": 2})
        vv3 = VersionVector(vector={"a": 1, "c": 1})
        
        # vv2 dominates vv1
        assert vv1.compare(vv2) == -1
        assert vv2.compare(vv1) == 1
        
        # vv1 and vv3 are concurrent
        assert vv1.compare(vv3) == 0
        assert vv1.is_concurrent(vv3)


# =============================================================================
# ITEM-SAE-004: Trust Engine Tests
# =============================================================================

class TestTrustEngine:
    """Tests for TrustEngine module."""
    
    def test_trust_engine_initialization(self):
        """Test TrustEngine initialization."""
        from src.context.trust_engine import TrustEngine, TrustEngineConfig
        
        config = TrustEngineConfig(
            min_trust_threshold=0.6,
            decay_rate=0.02,
            boost_on_hit=0.1,
            penalty_on_miss=0.15,
        )
        
        engine = TrustEngine(config=config)
        
        assert engine.config.min_trust_threshold == 0.6
        assert engine.config.decay_rate == 0.02
    
    def test_calculate_initial_score(self):
        """Test initial trust score calculation."""
        from src.context.trust_engine import TrustEngine
        from src.context.context_graph import ContextNode, NodeType
        
        engine = TrustEngine()
        
        # High quality node
        node = ContextNode(
            id="core.py",
            type=NodeType.FILE,
            location="src/core.py",
            usage_count=10,
            success_rate=1.0,
        )
        node.metadata["validated"] = True
        
        score = engine.calculate_initial_score(node)
        assert score > 0.5  # Should be above average
    
    def test_update_on_hit(self):
        """Test trust update on successful operation."""
        from src.context.trust_engine import TrustEngine
        from src.context.context_graph import ContextGraph, ContextNode, NodeType
        
        graph = ContextGraph()
        node = ContextNode(id="test.py", type=NodeType.FILE, location="test.py", trust_score=0.5)
        graph.add_node(node)
        
        engine = TrustEngine(context_graph=graph)
        new_score = engine.update_on_hit("test.py")
        
        assert new_score > 0.5
        assert node.trust_score > 0.5
    
    def test_update_on_miss(self):
        """Test trust update on failed operation."""
        from src.context.trust_engine import TrustEngine
        from src.context.context_graph import ContextGraph, ContextNode, NodeType
        
        graph = ContextGraph()
        node = ContextNode(id="test.py", type=NodeType.FILE, location="test.py", trust_score=0.5)
        graph.add_node(node)
        
        engine = TrustEngine(context_graph=graph)
        new_score = engine.update_on_miss("test.py")
        
        assert new_score < 0.5
        assert node.trust_score < 0.5
    
    def test_apply_time_decay(self):
        """Test time-based trust decay."""
        from src.context.trust_engine import TrustEngine, TrustEngineConfig
        from src.context.context_graph import ContextGraph, ContextNode, NodeType
        
        config = TrustEngineConfig(decay_rate=0.1, decay_after_hours=0)
        graph = ContextGraph()
        node = ContextNode(id="test.py", type=NodeType.FILE, location="test.py", trust_score=0.8)
        graph.add_node(node)
        
        engine = TrustEngine(config=config, context_graph=graph)
        new_score = engine.apply_time_decay("test.py", hours=5)
        
        # Should decay by decay_rate * hours = 0.1 * 5 = 0.5 (capped at 0.3)
        assert new_score < 0.8


# =============================================================================
# ITEM-SAE-005: Version Vector System Tests
# =============================================================================

class TestVectorClockManager:
    """Tests for VectorClockManager module."""
    
    def test_vector_clock_manager_init(self):
        """Test VectorClockManager initialization."""
        from src.context.version_vectors import VectorClockManager
        
        manager = VectorClockManager()
        assert manager is not None
    
    def test_get_and_update_vector(self):
        """Test getting and updating version vectors."""
        from src.context.version_vectors import VectorClockManager
        from src.context.context_graph import ContextGraph, ContextNode, NodeType
        
        graph = ContextGraph()
        node = ContextNode(id="test.py", type=NodeType.FILE, location="test.py")
        graph.add_node(node)
        
        manager = VectorClockManager(context_graph=graph)
        
        # Update vector
        v1 = manager.update_vector("test.py", "content_changed")
        assert v1 is not None
        assert "test.py" in v1
        
        # Update again
        v2 = manager.update_vector("test.py", "another_change")
        assert v2["test.py"] > v1["test.py"]
    
    def test_conflict_detection(self):
        """Test conflict detection."""
        from src.context.version_vectors import VectorClockManager
        from src.context.context_graph import ContextGraph, ContextNode, NodeType, VersionVector
        
        graph = ContextGraph()
        
        # Create nodes with concurrent version vectors
        n1 = ContextNode(id="a.py", type=NodeType.FILE, location="a.py")
        n1.version_vector = VersionVector(vector={"a.py": 2, "b.py": 1})
        
        n2 = ContextNode(id="b.py", type=NodeType.FILE, location="b.py")
        n2.version_vector = VersionVector(vector={"a.py": 1, "b.py": 2})
        
        graph.add_node(n1)
        graph.add_node(n2)
        
        manager = VectorClockManager(context_graph=graph)
        conflicts = manager.detect_conflicts()
        
        # Should detect concurrent modifications
        assert len(conflicts) >= 1


class TestStaleDetector:
    """Tests for StaleDetector module."""
    
    def test_detect_stale_context(self):
        """Test stale context detection."""
        from src.context.version_vectors import StaleDetector
        from src.context.context_graph import ContextGraph, ContextNode, NodeType
        
        graph = ContextGraph()
        
        # Add old node (stale by age)
        old_node = ContextNode(
            id="old.py",
            type=NodeType.FILE,
            location="old.py",
            trust_score=0.2,
            last_modified=datetime.now() - timedelta(hours=48)
        )
        
        # Add fresh node
        fresh_node = ContextNode(
            id="fresh.py",
            type=NodeType.FILE,
            location="fresh.py",
            trust_score=0.9,
            last_modified=datetime.now()
        )
        
        graph.add_node(old_node)
        graph.add_node(fresh_node)
        
        detector = StaleDetector(context_graph=graph, max_age_hours=24)
        stale_nodes = detector.detect_stale_context()
        
        assert len(stale_nodes) >= 1
        assert any(s.node_id == "old.py" for s in stale_nodes)
    
    def test_get_freshness_score(self):
        """Test freshness score calculation."""
        from src.context.version_vectors import StaleDetector
        from src.context.context_graph import ContextNode, NodeType
        
        detector = StaleDetector()
        
        # Fresh node
        fresh = ContextNode(
            id="fresh.py",
            type=NodeType.FILE,
            location="fresh.py",
            trust_score=0.9,
            last_modified=datetime.now(),
            usage_count=5
        )
        fresh_score = detector.get_freshness_score(fresh)
        assert fresh_score > 0.5
        
        # Stale node
        stale = ContextNode(
            id="stale.py",
            type=NodeType.FILE,
            location="stale.py",
            trust_score=0.3,
            last_modified=datetime.now() - timedelta(days=7),
            usage_count=0
        )
        stale_score = detector.get_freshness_score(stale)
        assert stale_score < fresh_score


# =============================================================================
# ITEM-SAE-006: Semantic Checksum Tests
# =============================================================================

class TestSemanticChecksum:
    """Tests for SemanticChecksum module."""
    
    def test_compute_semantic_hash_python(self):
        """Test semantic hash for Python code."""
        from src.context.semantic_checksum import SemanticChecksum, Language
        
        checksum = SemanticChecksum()
        
        code1 = '''
def hello():
    """Say hello."""
    print("Hello, World!")
'''
        
        code2 = '''
def hello():
    # Changed comment
    print("Hello, World!")
'''
        
        code3 = '''
def goodbye():  # Different function name
    print("Goodbye!")
'''
        
        hash1 = checksum.compute_ast_hash(code1, Language.PYTHON, "test.py")
        hash2 = checksum.compute_ast_hash(code2, Language.PYTHON, "test.py")
        hash3 = checksum.compute_ast_hash(code3, Language.PYTHON, "test.py")
        
        # code1 and code2 should have similar semantic hashes (only comment changed)
        # code3 should have different hash
        assert hash1.semantic_hash != hash3.semantic_hash
    
    def test_checksum_diff(self):
        """Test checksum difference detection."""
        from src.context.semantic_checksum import SemanticChecksum, Language, ChecksumDiff
        
        checksum = SemanticChecksum()
        
        old_code = "def foo(): pass"
        new_code = "def bar(): pass"
        
        old_hash = checksum.compute_ast_hash(old_code, Language.PYTHON, "test.py")
        new_hash = checksum.compute_ast_hash(new_code, Language.PYTHON, "test.py")
        
        diff = checksum.compare_checksums(old_hash.semantic_hash, new_hash.semantic_hash)
        
        assert diff.changed


# =============================================================================
# ITEM-SAE-007: Drift Detector Tests
# =============================================================================

class TestDriftDetector:
    """Tests for DriftDetector module."""
    
    def test_drift_level_classification(self):
        """Test drift level from score."""
        from src.context.drift_detector import DriftLevel
        
        assert DriftLevel.from_score(0.05) == DriftLevel.NONE
        assert DriftLevel.from_score(0.2) == DriftLevel.MINOR
        assert DriftLevel.from_score(0.4) == DriftLevel.MODERATE
        assert DriftLevel.from_score(0.8) == DriftLevel.SEVERE
    
    def test_detect_drift_missing_file(self):
        """Test drift detection for missing file."""
        from src.context.drift_detector import DriftDetector
        from src.context.context_graph import ContextNode, NodeType
        
        detector = DriftDetector()
        
        node = ContextNode(
            id="nonexistent.py",
            type=NodeType.FILE,
            location="/nonexistent/path.py",
            content_hash="abc123"
        )
        
        result = detector.detect_drift(node)
        
        assert result.drift_level.value == "SEVERE"
        assert result.recommended_action == "file_missing"
    
    def test_detect_all_drift(self):
        """Test detecting drift for all nodes."""
        from src.context.drift_detector import DriftDetector
        from src.context.context_graph import ContextGraph, ContextNode, NodeType
        
        graph = ContextGraph()
        
        # Add a node
        node = ContextNode(
            id="test.py",
            type=NodeType.FILE,
            location="test.py",
            trust_score=0.5
        )
        graph.add_node(node)
        
        detector = DriftDetector(context_graph=graph)
        report = detector.detect_all_drift()
        
        assert report.total_nodes == 1


# =============================================================================
# ITEM-SAE-008: Recursive Summarizer Tests
# =============================================================================

class TestRecursiveSummarizer:
    """Tests for RecursiveSummarizer module."""
    
    def test_summarizer_init(self):
        """Test summarizer initialization."""
        from src.context.summarization import RecursiveSummarizer
        
        summarizer = RecursiveSummarizer(
            max_stages_to_retain=5,
            summary_compression_ratio=0.2
        )
        
        assert summarizer.max_stages_to_retain == 5
    
    def test_stage_summary(self):
        """Test stage summarization."""
        from src.context.summarization import RecursiveSummarizer, ExecutionStage, StageType
        
        summarizer = RecursiveSummarizer()
        
        stage = ExecutionStage(
            stage_id="exec-001",
            stage_type=StageType.EXEC,
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(minutes=5),
            files_processed=["file1.py", "file2.py"],
            patches_applied=["patch1"],
            gates_passed=["GATE-01", "GATE-02"],
        )
        
        summary = summarizer.summarize_stage(stage)
        
        assert summary.stage_id == "exec-001"
        assert summary.files_processed_count == 2


class TestPruningPolicy:
    """Tests for PruningPolicy module."""
    
    def test_pruning_policy_init(self):
        """Test pruning policy initialization."""
        from src.context.pruning_policy import PruningPolicy, PruningPolicyConfig
        
        config = PruningPolicyConfig(
            max_age_hours=24,
            min_trust_threshold=0.3,
            max_stages=10,
        )
        
        policy = PruningPolicy(config=config)
        
        assert policy.config.max_age_hours == 24
    
    def test_should_prune(self):
        """Test pruning decision."""
        from src.context.pruning_policy import PruningPolicy
        from src.context.summarization import ExecutionStage, StageType, StageStatus
        
        policy = PruningPolicy()
        
        # Old completed stage
        old_stage = ExecutionStage(
            stage_id="old",
            stage_type=StageType.EXEC,
            start_time=datetime.now() - timedelta(hours=48),
            end_time=datetime.now() - timedelta(hours=47),
            status=StageStatus.COMPLETE,
        )
        
        # Fresh stage
        fresh_stage = ExecutionStage(
            stage_id="fresh",
            stage_type=StageType.EXEC,
            start_time=datetime.now(),
            status=StageStatus.IN_PROGRESS,
        )
        
        # Old completed stages should be prunable
        assert policy.should_prune(old_stage, None) is True
        assert policy.should_prune(fresh_stage, None) is False


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for SAE modules."""
    
    def test_context_graph_with_trust_engine(self):
        """Test ContextGraph integration with TrustEngine."""
        from src.context.context_graph import ContextGraph, ContextNode, NodeType
        from src.context.trust_engine import TrustEngine
        
        graph = ContextGraph()
        node = ContextNode(id="test.py", type=NodeType.FILE, location="test.py")
        graph.add_node(node)
        
        engine = TrustEngine(context_graph=graph)
        
        # Simulate hits and misses
        engine.update_on_hit("test.py")
        engine.update_on_hit("test.py")
        engine.update_on_miss("test.py")
        
        # Trust should have changed
        assert node.trust_score != 0.5
    
    def test_full_sae_workflow(self):
        """Test complete SAE workflow."""
        from src.context.context_graph import ContextGraph, ContextNode, NodeType
        from src.context.trust_engine import TrustEngine
        from src.context.version_vectors import StaleDetector
        from src.context.drift_detector import DriftDetector
        
        # Create graph
        graph = ContextGraph(session_id="test-workflow")
        
        # Add nodes
        for i, score in enumerate([0.9, 0.7, 0.5, 0.3]):
            node = ContextNode(
                id=f"file{i}.py",
                type=NodeType.FILE,
                location=f"file{i}.py",
                trust_score=score
            )
            graph.add_node(node)
        
        # Initialize components
        trust_engine = TrustEngine(context_graph=graph)
        stale_detector = StaleDetector(context_graph=graph)
        drift_detector = DriftDetector(context_graph=graph)
        
        # Get low trust nodes
        low_trust = trust_engine.get_low_trust_nodes(threshold=0.5)
        assert len(low_trust) == 2
        
        # Get stats
        stats = graph.get_stats()
        assert stats["total_nodes"] == 4


# =============================================================================
# Test Runner
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
