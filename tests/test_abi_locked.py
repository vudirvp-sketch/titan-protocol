"""
Tests for ITEM-GAP-002: ABI_LOCKED_PROTOCOL

This module tests the AbiLockedProtocol implementation for dependency
cluster management with atomic update operations.

Author: TITAN Protocol Team
Version: 5.0.0
"""

import pytest
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from src.coordination.abi_locked import (
    AbiLockedProtocol,
    ClusterClassification,
    Dependency,
    Cluster,
    UpdateResult,
    UpdateOperation,
    UpdateStatus,
    AbiUpdateFailed,
    ClusterLockedError,
    create_abi_locked_protocol,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_clusters_path():
    """Create a temporary path for clusters storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "abi_clusters.json"


@pytest.fixture
def mock_event_bus():
    """Create a mock event bus for testing."""
    bus = MagicMock()
    bus.emit = MagicMock()
    return bus


@pytest.fixture
def mock_lock_backend():
    """Create a mock lock backend for testing."""
    backend = MagicMock()
    backend.acquire = MagicMock(return_value=True)
    backend.release = MagicMock()
    return backend


@pytest.fixture
def abi_config(temp_clusters_path):
    """Create an ABI locked protocol configuration for testing."""
    return {
        "enabled": True,
        "clusters_path": str(temp_clusters_path),
        "auto_detect": True,
        "rollback_on_failure": True
    }


@pytest.fixture
def protocol(abi_config, mock_event_bus, mock_lock_backend):
    """Create an AbiLockedProtocol instance for testing."""
    return AbiLockedProtocol(
        config=abi_config,
        event_bus=mock_event_bus,
        lock_backend=mock_lock_backend
    )


@pytest.fixture
def sample_dependencies():
    """Create sample dependencies for testing."""
    return [
        Dependency(
            name="numpy",
            version="1.20.0",
            abi_version="1.20",
            dependencies=[]
        ),
        Dependency(
            name="pandas",
            version="1.3.0",
            abi_version=None,
            dependencies=["numpy"]
        ),
        Dependency(
            name="scipy",
            version="1.7.0",
            abi_version=None,
            dependencies=["numpy"]
        ),
        Dependency(
            name="requests",
            version="2.26.0",
            abi_version=None,
            dependencies=[]
        ),
        Dependency(
            name="old-package",
            version="0.1.0",
            abi_version=None,
            dependencies=[],
            maintainer_status="abandoned"
        ),
    ]


# =============================================================================
# Test ClusterClassification Enum
# =============================================================================

class TestClusterClassification:
    """Tests for ClusterClassification enum."""

    def test_abi_locked_exists(self):
        """Test ABI_LOCKED classification exists."""
        assert hasattr(ClusterClassification, "ABI_LOCKED")
        assert ClusterClassification.ABI_LOCKED.value == "abi_locked"

    def test_cascade_numpy_exists(self):
        """Test CASCADE_NUMPY classification exists."""
        assert hasattr(ClusterClassification, "CASCADE_NUMPY")
        assert ClusterClassification.CASCADE_NUMPY.value == "cascade_numpy"

    def test_abandoned_anchor_exists(self):
        """Test ABANDONED_ANCHOR classification exists."""
        assert hasattr(ClusterClassification, "ABANDONED_ANCHOR")
        assert ClusterClassification.ABANDONED_ANCHOR.value == "abandoned_anchor"

    def test_all_values_are_strings(self):
        """Test all classification values are strings."""
        for classification in ClusterClassification:
            assert isinstance(classification.value, str)


# =============================================================================
# Test Dependency
# =============================================================================

class TestDependency:
    """Tests for Dependency dataclass."""

    def test_create_dependency(self):
        """Test creating a Dependency instance."""
        dep = Dependency(
            name="numpy",
            version="1.20.0"
        )
        assert dep.name == "numpy"
        assert dep.version == "1.20.0"
        assert dep.abi_version is None
        assert dep.maintainer_status == "active"

    def test_dependency_with_abi_version(self):
        """Test creating a dependency with ABI version."""
        dep = Dependency(
            name="numpy",
            version="1.20.0",
            abi_version="1.20"
        )
        assert dep.abi_version == "1.20"

    def test_dependency_with_abandoned_status(self):
        """Test creating a dependency with abandoned status."""
        dep = Dependency(
            name="old-package",
            version="0.1.0",
            maintainer_status="abandoned"
        )
        assert dep.maintainer_status == "abandoned"

    def test_to_dict(self):
        """Test Dependency serialization."""
        dep = Dependency(
            name="numpy",
            version="1.20.0",
            abi_version="1.20",
            dependencies=["other"],
            abi_requirements={"abi:1.20"}
        )
        d = dep.to_dict()
        assert d["name"] == "numpy"
        assert d["version"] == "1.20.0"
        assert d["abi_version"] == "1.20"
        assert "other" in d["dependencies"]

    def test_from_dict(self):
        """Test Dependency deserialization."""
        d = {
            "name": "pandas",
            "version": "1.3.0",
            "abi_version": None,
            "maintainer_status": "active",
            "dependencies": ["numpy"],
            "abi_requirements": []
        }
        dep = Dependency.from_dict(d)
        assert dep.name == "pandas"
        assert dep.version == "1.3.0"
        assert dep.dependencies == ["numpy"]

    def test_hash_and_equality(self):
        """Test Dependency hash and equality."""
        dep1 = Dependency(name="numpy", version="1.20.0")
        dep2 = Dependency(name="numpy", version="1.21.0")
        dep3 = Dependency(name="pandas", version="1.3.0")
        
        assert dep1 == dep2  # Same name
        assert dep1 != dep3  # Different name
        assert hash(dep1) == hash(dep2)


# =============================================================================
# Test Cluster
# =============================================================================

class TestCluster:
    """Tests for Cluster dataclass."""

    def test_create_cluster(self):
        """Test creating a Cluster instance."""
        members = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0")
        ]
        cluster = Cluster(
            cluster_id="cluster-001",
            classification=ClusterClassification.ABI_LOCKED,
            members=members
        )
        assert cluster.cluster_id == "cluster-001"
        assert cluster.classification == ClusterClassification.ABI_LOCKED
        assert len(cluster.members) == 2
        assert not cluster.locked

    def test_cluster_locked(self):
        """Test cluster locking."""
        cluster = Cluster(
            cluster_id="cluster-001",
            classification=ClusterClassification.ABI_LOCKED,
            locked=True,
            lock_holder="op-123"
        )
        assert cluster.locked
        assert cluster.lock_holder == "op-123"

    def test_get_member_names(self):
        """Test getting member names."""
        members = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0")
        ]
        cluster = Cluster(
            cluster_id="cluster-001",
            classification=ClusterClassification.ABI_LOCKED,
            members=members
        )
        names = cluster.get_member_names()
        assert "numpy" in names
        assert "pandas" in names

    def test_get_member_by_name(self):
        """Test getting a member by name."""
        numpy_dep = Dependency(name="numpy", version="1.20.0")
        pandas_dep = Dependency(name="pandas", version="1.3.0")
        cluster = Cluster(
            cluster_id="cluster-001",
            classification=ClusterClassification.ABI_LOCKED,
            members=[numpy_dep, pandas_dep]
        )
        
        found = cluster.get_member_by_name("numpy")
        assert found == numpy_dep
        
        not_found = cluster.get_member_by_name("scipy")
        assert not_found is None

    def test_to_dict(self):
        """Test Cluster serialization."""
        cluster = Cluster(
            cluster_id="cluster-001",
            classification=ClusterClassification.CASCADE_NUMPY,
            members=[Dependency(name="numpy", version="1.20.0")],
            abi_compatible_set={"abi:1.20"}
        )
        d = cluster.to_dict()
        assert d["cluster_id"] == "cluster-001"
        assert d["classification"] == "cascade_numpy"
        assert len(d["members"]) == 1

    def test_from_dict(self):
        """Test Cluster deserialization."""
        d = {
            "cluster_id": "cluster-restore",
            "classification": "abi_locked",
            "members": [
                {"name": "numpy", "version": "1.20.0"}
            ],
            "locked": False,
            "lock_holder": None,
            "abi_compatible_set": [],
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z"
        }
        cluster = Cluster.from_dict(d)
        assert cluster.cluster_id == "cluster-restore"
        assert cluster.classification == ClusterClassification.ABI_LOCKED
        assert len(cluster.members) == 1


# =============================================================================
# Test UpdateResult
# =============================================================================

class TestUpdateResult:
    """Tests for UpdateResult dataclass."""

    def test_create_success_result(self):
        """Test creating a successful UpdateResult."""
        result = UpdateResult(
            success=True,
            cluster_id="cluster-001",
            updates_applied=[{"dep_name": "numpy"}]
        )
        assert result.success
        assert result.cluster_id == "cluster-001"
        assert not result.rollback_needed

    def test_create_failure_result(self):
        """Test creating a failed UpdateResult."""
        result = UpdateResult(
            success=False,
            cluster_id="cluster-001",
            rollback_needed=True,
            rollback_performed=True,
            error_message="ABI assertion failed"
        )
        assert not result.success
        assert result.rollback_needed
        assert result.rollback_performed

    def test_to_dict(self):
        """Test UpdateResult serialization."""
        result = UpdateResult(
            success=True,
            cluster_id="cluster-001",
            updates_applied=[],
            duration_ms=150.5
        )
        d = result.to_dict()
        assert d["success"]
        assert d["duration_ms"] == 150.5


# =============================================================================
# Test AbiLockedProtocol - Cluster Classification
# =============================================================================

class TestAbiLockedProtocolClassification:
    """Tests for cluster classification."""

    def test_classify_abi_locked(self, protocol):
        """Test classifying ABI-locked dependencies."""
        # Use packages that don't trigger CASCADE_NUMPY classification
        deps = [
            Dependency(name="h5py", version="3.7.0", abi_version="3.7"),
            Dependency(name="pyarrow", version="8.0.0")
        ]
        classification = protocol.classify_cluster(deps)
        assert classification == ClusterClassification.ABI_LOCKED

    def test_classify_cascade_numpy(self, protocol):
        """Test classifying cascade numpy dependencies."""
        deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        classification = protocol.classify_cluster(deps)
        assert classification == ClusterClassification.CASCADE_NUMPY

    def test_classify_abandoned_anchor(self, protocol):
        """Test classifying abandoned dependencies."""
        deps = [
            Dependency(name="old-package", version="0.1.0", maintainer_status="abandoned")
        ]
        classification = protocol.classify_cluster(deps)
        assert classification == ClusterClassification.ABANDONED_ANCHOR

    def test_classify_abandoned_priority(self, protocol):
        """Test that abandoned takes priority over other classifications."""
        deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="old-package", version="0.1.0", maintainer_status="abandoned")
        ]
        classification = protocol.classify_cluster(deps)
        assert classification == ClusterClassification.ABANDONED_ANCHOR


# =============================================================================
# Test AbiLockedProtocol - Cluster Detection
# =============================================================================

class TestAbiLockedProtocolDetection:
    """Tests for cluster detection."""

    def test_clusters_detected(self, protocol, sample_dependencies):
        """Test that ABI-locked clusters are detected."""
        clusters = protocol.detect_clusters(sample_dependencies)
        
        # Should have at least one cluster (numpy/pandas/scipy group)
        assert len(clusters) >= 1
        
        # Check that numpy cluster was detected
        numpy_clusters = [c for c in clusters if "numpy" in c.get_member_names()]
        assert len(numpy_clusters) >= 1

    def test_empty_dependencies(self, protocol):
        """Test detection with empty dependencies."""
        clusters = protocol.detect_clusters([])
        assert len(clusters) == 0

    def test_single_dependency_no_cluster(self, protocol):
        """Test detection with single dependency (no cluster)."""
        deps = [Dependency(name="requests", version="2.26.0")]
        clusters = protocol.detect_clusters(deps)
        # Single dependency with no dependencies shouldn't form a cluster
        assert len(clusters) == 0

    def test_connected_dependencies_form_cluster(self, protocol):
        """Test that connected dependencies form a cluster."""
        deps = [
            Dependency(name="numpy", version="1.20.0", abi_version="1.20"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"]),
            Dependency(name="scipy", version="1.7.0", dependencies=["numpy"])
        ]
        clusters = protocol.detect_clusters(deps)
        
        assert len(clusters) >= 1
        
        # All three should be in the same cluster
        all_names = set()
        for c in clusters:
            all_names.update(c.get_member_names())
        
        assert "numpy" in all_names
        assert "pandas" in all_names
        assert "scipy" in all_names

    def test_classification_types(self, protocol):
        """Test that different classification types are applied."""
        # Test CASCADE_NUMPY
        cascade_deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        cascade_clusters = protocol.detect_clusters(cascade_deps)
        
        for c in cascade_clusters:
            if "numpy" in c.get_member_names():
                assert c.classification == ClusterClassification.CASCADE_NUMPY
                break


# =============================================================================
# Test AbiLockedProtocol - Cluster Locking
# =============================================================================

class TestAbiLockedProtocolLocking:
    """Tests for cluster locking."""

    def test_lock_cluster(self, protocol):
        """Test locking a cluster."""
        # Create a cluster first
        deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        clusters = protocol.detect_clusters(deps)
        cluster = clusters[0]
        
        # Lock the cluster
        result = protocol.lock_cluster(cluster.cluster_id)
        assert result
        
        # Verify cluster is locked
        locked_cluster = protocol.get_cluster(cluster.cluster_id)
        assert locked_cluster.locked
        assert locked_cluster.lock_holder is not None

    def test_lock_nonexistent_cluster(self, protocol):
        """Test locking a non-existent cluster."""
        result = protocol.lock_cluster("nonexistent-cluster")
        assert not result

    def test_unlock_cluster(self, protocol):
        """Test unlocking a cluster."""
        deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        clusters = protocol.detect_clusters(deps)
        cluster = clusters[0]
        
        # Lock then unlock
        protocol.lock_cluster(cluster.cluster_id, "holder-001")
        result = protocol.unlock_cluster(cluster.cluster_id, "holder-001")
        assert result
        
        # Verify cluster is unlocked
        unlocked_cluster = protocol.get_cluster(cluster.cluster_id)
        assert not unlocked_cluster.locked

    def test_unlock_with_wrong_holder(self, protocol):
        """Test unlocking with wrong holder."""
        deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        clusters = protocol.detect_clusters(deps)
        cluster = clusters[0]
        
        protocol.lock_cluster(cluster.cluster_id, "holder-001")
        result = protocol.unlock_cluster(cluster.cluster_id, "wrong-holder")
        assert not result

    def test_double_lock_fails(self, protocol):
        """Test that double locking fails."""
        deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        clusters = protocol.detect_clusters(deps)
        cluster = clusters[0]
        
        # First lock should succeed
        result1 = protocol.lock_cluster(cluster.cluster_id, "holder-001")
        assert result1
        
        # Second lock should fail
        result2 = protocol.lock_cluster(cluster.cluster_id, "holder-002")
        assert not result2


# =============================================================================
# Test AbiLockedProtocol - Update Rules
# =============================================================================

class TestAbiLockedProtocolUpdateRules:
    """Tests for update rule enforcement."""

    def test_is_update_allowed_for_non_member(self, protocol):
        """Test update is allowed for non-cluster members."""
        cluster = Cluster(
            cluster_id="cluster-001",
            classification=ClusterClassification.ABI_LOCKED,
            members=[Dependency(name="numpy", version="1.20.0")]
        )
        
        # Update for non-member should be allowed
        allowed = protocol.is_update_allowed(cluster, "requests")
        assert allowed

    def test_partial_update_blocked_abi_locked(self, protocol):
        """Test that partial updates are blocked for ABI_LOCKED clusters."""
        cluster = Cluster(
            cluster_id="cluster-001",
            classification=ClusterClassification.ABI_LOCKED,
            members=[
                Dependency(name="numpy", version="1.20.0"),
                Dependency(name="pandas", version="1.3.0")
            ]
        )
        
        # Individual update should be blocked
        allowed = protocol.is_update_allowed(cluster, "numpy")
        assert not allowed

    def test_partial_update_blocked_cascade(self, protocol):
        """Test that partial updates are blocked for CASCADE_NUMPY clusters."""
        cluster = Cluster(
            cluster_id="cluster-001",
            classification=ClusterClassification.CASCADE_NUMPY,
            members=[
                Dependency(name="numpy", version="1.20.0"),
                Dependency(name="pandas", version="1.3.0")
            ]
        )
        
        # Individual update should be blocked
        allowed = protocol.is_update_allowed(cluster, "pandas")
        assert not allowed

    def test_update_blocked_abandoned(self, protocol):
        """Test that updates are blocked for ABANDONED_ANCHOR clusters."""
        cluster = Cluster(
            cluster_id="cluster-001",
            classification=ClusterClassification.ABANDONED_ANCHOR,
            members=[Dependency(name="old-package", version="0.1.0")]
        )
        
        # Update should be blocked
        allowed = protocol.is_update_allowed(cluster, "old-package")
        assert not allowed


# =============================================================================
# Test AbiLockedProtocol - Atomic Updates
# =============================================================================

class TestAbiLockedProtocolAtomicUpdate:
    """Tests for atomic update operations."""

    def test_atomic_update_works(self, protocol):
        """Test that atomic update succeeds."""
        deps = [
            Dependency(name="numpy", version="1.20.0", abi_version="1.20"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        clusters = protocol.detect_clusters(deps)
        cluster = clusters[0]
        
        # Mock operations
        uninstall_calls = []
        install_calls = []
        
        def mock_uninstall(name, version):
            uninstall_calls.append((name, version))
        
        def mock_install(name, version):
            install_calls.append((name, version))
        
        def mock_assert_abi(cluster):
            pass  # ABI compatible
        
        updates = [
            {"dep_name": "numpy", "old_version": "1.20.0", "new_version": "1.21.0"},
            {"dep_name": "pandas", "old_version": "1.3.0", "new_version": "1.4.0"}
        ]
        
        result = protocol.atomic_update(
            cluster.cluster_id,
            updates,
            uninstall_fn=mock_uninstall,
            install_fn=mock_install,
            assert_fn=mock_assert_abi
        )
        
        assert result.success
        assert len(result.updates_applied) == 2
        assert len(uninstall_calls) == 2
        assert len(install_calls) == 2

    def test_atomic_update_rolls_back_on_failure(self, protocol):
        """Test that atomic update rolls back on failure."""
        deps = [
            Dependency(name="numpy", version="1.20.0", abi_version="1.20"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        clusters = protocol.detect_clusters(deps)
        cluster = clusters[0]
        
        def mock_uninstall(name, version):
            pass
        
        def mock_install(name, version):
            if name == "pandas":
                raise Exception("Install failed")
        
        updates = [
            {"dep_name": "numpy", "old_version": "1.20.0", "new_version": "1.21.0"},
            {"dep_name": "pandas", "old_version": "1.3.0", "new_version": "1.4.0"}
        ]
        
        result = protocol.atomic_update(
            cluster.cluster_id,
            updates,
            uninstall_fn=mock_uninstall,
            install_fn=mock_install
        )
        
        assert not result.success
        assert result.rollback_needed
        assert result.rollback_performed

    def test_atomic_update_blocked_on_locked_cluster(self, protocol):
        """Test that atomic update is blocked on locked cluster."""
        deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        clusters = protocol.detect_clusters(deps)
        cluster = clusters[0]
        
        # Lock the cluster
        protocol.lock_cluster(cluster.cluster_id, "other-operation")
        
        updates = [
            {"dep_name": "numpy", "old_version": "1.20.0", "new_version": "1.21.0"}
        ]
        
        with pytest.raises(ClusterLockedError):
            protocol.atomic_update(cluster.cluster_id, updates)

    def test_atomic_update_nonexistent_cluster(self, protocol):
        """Test atomic update on non-existent cluster."""
        updates = [
            {"dep_name": "numpy", "old_version": "1.20.0", "new_version": "1.21.0"}
        ]
        
        result = protocol.atomic_update("nonexistent-cluster", updates)
        assert not result.success
        assert "not found" in result.error_message.lower()

    def test_atomic_update_target_not_in_cluster(self, protocol):
        """Test atomic update when target not in cluster."""
        deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        clusters = protocol.detect_clusters(deps)
        cluster = clusters[0]
        
        updates = [
            {"dep_name": "requests", "old_version": "2.25.0", "new_version": "2.26.0"}
        ]
        
        result = protocol.atomic_update(cluster.cluster_id, updates)
        assert not result.success
        assert "not in cluster" in result.error_message.lower()


# =============================================================================
# Test AbiLockedProtocol - State Capture and Rollback
# =============================================================================

class TestAbiLockedProtocolStateCapture:
    """Tests for state capture and rollback."""

    def test_capture_state(self, protocol):
        """Test capturing cluster state."""
        cluster = Cluster(
            cluster_id="cluster-001",
            classification=ClusterClassification.ABI_LOCKED,
            members=[
                Dependency(name="numpy", version="1.20.0", abi_version="1.20"),
                Dependency(name="pandas", version="1.3.0")
            ],
            abi_compatible_set={"numpy:1.20"}
        )
        
        state = protocol.capture_state(cluster)
        
        assert state["cluster_id"] == "cluster-001"
        assert len(state["members"]) == 2
        assert "numpy:1.20" in state["abi_compatible_set"]

    def test_rollback_restores_state(self, protocol):
        """Test that rollback restores previous state."""
        deps = [
            Dependency(name="numpy", version="1.20.0", abi_version="1.20"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        clusters = protocol.detect_clusters(deps)
        cluster = clusters[0]
        
        # Capture initial state
        initial_state = protocol.capture_state(cluster)
        
        # Simulate failed update with rollback
        rollback_calls = []
        
        def mock_uninstall(name, version):
            rollback_calls.append(("uninstall", name, version))
        
        def mock_install(name, version):
            if version == "1.4.0":
                raise Exception("Failed to install pandas")
            rollback_calls.append(("install", name, version))
        
        updates = [
            {"dep_name": "numpy", "old_version": "1.20.0", "new_version": "1.21.0"},
            {"dep_name": "pandas", "old_version": "1.3.0", "new_version": "1.4.0"}
        ]
        
        result = protocol.atomic_update(
            cluster.cluster_id,
            updates,
            uninstall_fn=mock_uninstall,
            install_fn=mock_install
        )
        
        assert not result.success
        assert result.rollback_performed
        # Rollback should have restored old versions
        assert any("1.20.0" in str(call) for call in rollback_calls)


# =============================================================================
# Test AbiLockedProtocol - Utility Methods
# =============================================================================

class TestAbiLockedProtocolUtilities:
    """Tests for utility methods."""

    def test_get_cluster(self, protocol):
        """Test getting a cluster by ID."""
        deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        clusters = protocol.detect_clusters(deps)
        cluster = clusters[0]
        
        retrieved = protocol.get_cluster(cluster.cluster_id)
        assert retrieved == cluster

    def test_get_all_clusters(self, protocol):
        """Test getting all clusters."""
        deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"]),
            Dependency(name="requests", version="2.26.0", dependencies=[])
        ]
        protocol.detect_clusters(deps)
        
        all_clusters = protocol.get_all_clusters()
        assert isinstance(all_clusters, list)

    def test_get_clusters_for_dependency(self, protocol):
        """Test getting clusters for a specific dependency."""
        deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        protocol.detect_clusters(deps)
        
        numpy_clusters = protocol.get_clusters_for_dependency("numpy")
        assert len(numpy_clusters) >= 1
        
        # Non-existent dependency
        other_clusters = protocol.get_clusters_for_dependency("nonexistent")
        assert len(other_clusters) == 0

    def test_get_stats(self, protocol):
        """Test getting protocol statistics."""
        deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        protocol.detect_clusters(deps)
        
        stats = protocol.get_stats()
        
        assert stats["enabled"]
        assert stats["total_clusters"] >= 1
        assert "by_classification" in stats


# =============================================================================
# Test AbiLockedProtocol - Events
# =============================================================================

class TestAbiLockedProtocolEvents:
    """Tests for event emission."""

    def test_cluster_detection_emits_event(self, protocol, mock_event_bus):
        """Test that cluster detection emits event."""
        deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        protocol.detect_clusters(deps)
        
        # Check that event was emitted
        assert mock_event_bus.emit.called
        
        # Check event type
        call_args = mock_event_bus.emit.call_args[0]
        assert call_args[0] == "CLUSTERS_DETECTED"

    def test_cluster_lock_emits_event(self, protocol, mock_event_bus):
        """Test that cluster lock emits event."""
        deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        clusters = protocol.detect_clusters(deps)
        cluster = clusters[0]
        
        protocol.lock_cluster(cluster.cluster_id)
        
        # Check for lock event
        lock_calls = [c for c in mock_event_bus.emit.call_args_list 
                      if c[0][0] == "CLUSTER_LOCKED"]
        assert len(lock_calls) >= 1

    def test_atomic_update_emits_events(self, protocol, mock_event_bus):
        """Test that atomic update emits events."""
        deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        clusters = protocol.detect_clusters(deps)
        cluster = clusters[0]
        
        updates = [
            {"dep_name": "numpy", "old_version": "1.20.0", "new_version": "1.21.0"},
            {"dep_name": "pandas", "old_version": "1.3.0", "new_version": "1.4.0"}
        ]
        
        protocol.atomic_update(
            cluster.cluster_id,
            updates,
            uninstall_fn=lambda n, v: None,
            install_fn=lambda n, v: None,
            assert_fn=lambda c: None
        )
        
        # Check for start event
        start_calls = [c for c in mock_event_bus.emit.call_args_list 
                       if c[0][0] == "ATOMIC_UPDATE_STARTED"]
        assert len(start_calls) >= 1
        
        # Check for complete event
        complete_calls = [c for c in mock_event_bus.emit.call_args_list 
                          if c[0][0] == "ATOMIC_UPDATE_COMPLETED"]
        assert len(complete_calls) >= 1


# =============================================================================
# Test Factory Function
# =============================================================================

class TestFactoryFunction:
    """Tests for factory function."""

    def test_create_abi_locked_protocol(self, abi_config, mock_event_bus, mock_lock_backend):
        """Test creating protocol via factory function."""
        protocol = create_abi_locked_protocol(
            config=abi_config,
            event_bus=mock_event_bus,
            lock_backend=mock_lock_backend
        )
        
        assert protocol.enabled
        assert protocol._event_bus == mock_event_bus
        assert protocol._lock_backend == mock_lock_backend

    def test_create_protocol_defaults(self):
        """Test creating protocol with defaults."""
        protocol = create_abi_locked_protocol()
        
        assert protocol.enabled  # Default enabled


# =============================================================================
# Integration Tests
# =============================================================================

class TestAbiLockedProtocolIntegration:
    """Integration tests for AbiLockedProtocol."""

    def test_full_workflow(self, protocol):
        """Test complete workflow: detect, lock, update, unlock."""
        # 1. Create dependencies
        deps = [
            Dependency(name="numpy", version="1.20.0", abi_version="1.20"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"]),
            Dependency(name="scipy", version="1.7.0", dependencies=["numpy"])
        ]
        
        # 2. Detect clusters
        clusters = protocol.detect_clusters(deps)
        assert len(clusters) >= 1
        
        cluster = clusters[0]
        assert cluster.classification == ClusterClassification.CASCADE_NUMPY
        
        # 3. Verify update rules
        assert not protocol.is_update_allowed(cluster, "numpy")
        
        # 4. Perform atomic update
        updates = [
            {"dep_name": "numpy", "old_version": "1.20.0", "new_version": "1.21.0"},
            {"dep_name": "pandas", "old_version": "1.3.0", "new_version": "1.4.0"},
            {"dep_name": "scipy", "old_version": "1.7.0", "new_version": "1.8.0"}
        ]
        
        result = protocol.atomic_update(
            cluster.cluster_id,
            updates,
            uninstall_fn=lambda n, v: None,
            install_fn=lambda n, v: None,
            assert_fn=lambda c: None
        )
        
        assert result.success
        assert len(result.updates_applied) == 3

    def test_protocol_disabled(self, temp_clusters_path):
        """Test that disabled protocol does nothing."""
        config = {
            "enabled": False,
            "clusters_path": str(temp_clusters_path)
        }
        protocol = AbiLockedProtocol(config=config)
        
        deps = [
            Dependency(name="numpy", version="1.20.0"),
            Dependency(name="pandas", version="1.3.0", dependencies=["numpy"])
        ]
        
        clusters = protocol.detect_clusters(deps)
        assert len(clusters) == 0
        
        result = protocol.atomic_update("any-cluster", [])
        assert not result.success


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
