#!/usr/bin/env python3
"""
TITAN PROTOCOL v5.0.0 - ABI Locked Protocol Module

ITEM-GAP-002: ABI_LOCKED_PROTOCOL

Implements dependency cluster management with atomic update operations.
Ensures ABI compatibility within locked clusters and prevents partial updates
that could break ABI consistency.

Classification Types:
- ABI_LOCKED: Dependencies with shared ABI requirements
- CASCADE_NUMPY: Numpy-dependent packages (cascade updates)
- ABANDONED_ANCHOR: Packages with no active maintainers

Rules:
- Simultaneous uninstall + install + assert
- No independent member update within locked cluster
- Thread-safe cluster operations with distributed locking

Usage:
    from src.coordination.abi_locked import (
        AbiLockedProtocol,
        ClusterClassification,
        Dependency,
        Cluster,
    )
    
    protocol = AbiLockedProtocol(config)
    clusters = protocol.detect_clusters(all_dependencies)
    result = protocol.atomic_update(cluster_id, updates)

Author: TITAN Protocol Team
Version: 5.0.0
"""

import json
import hashlib
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Callable
from enum import Enum
import uuid
import copy

from src.observability.structured_logging import get_logger, StructuredLogger
from src.utils.timezone import now_utc, now_utc_iso


class ClusterClassification(Enum):
    """
    Classification types for dependency clusters.
    
    ABI_LOCKED: Dependencies with shared ABI requirements that must be
                updated together to maintain compatibility.
    CASCADE_NUMPY: Numpy-dependent packages that require cascade updates
                   when numpy version changes.
    ABANDONED_ANCHOR: Packages with no active maintainers that should
                      be treated as locked to prevent breaking changes.
    """
    ABI_LOCKED = "abi_locked"
    CASCADE_NUMPY = "cascade_numpy"
    ABANDONED_ANCHOR = "abandoned_anchor"


class UpdateStatus(Enum):
    """Status of an atomic update operation."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass
class Dependency:
    """
    Represents a dependency with ABI and maintainer information.
    
    Attributes:
        name: Package name
        version: Current version string
        abi_version: ABI version if applicable (e.g., for C extensions)
        maintainer_status: One of 'active', 'maintenance', 'abandoned'
        dependencies: List of dependency names this package depends on
        abi_requirements: Set of ABI requirements this package has
    """
    name: str
    version: str
    abi_version: Optional[str] = None
    maintainer_status: str = "active"
    dependencies: List[str] = field(default_factory=list)
    abi_requirements: Set[str] = field(default_factory=set)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "version": self.version,
            "abi_version": self.abi_version,
            "maintainer_status": self.maintainer_status,
            "dependencies": self.dependencies,
            "abi_requirements": list(self.abi_requirements)
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Dependency":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            version=data["version"],
            abi_version=data.get("abi_version"),
            maintainer_status=data.get("maintainer_status", "active"),
            dependencies=data.get("dependencies", []),
            abi_requirements=set(data.get("abi_requirements", []))
        )
    
    def __hash__(self) -> int:
        """Make Dependency hashable for use in sets."""
        return hash(self.name)
    
    def __eq__(self, other: object) -> bool:
        """Equality based on name."""
        if isinstance(other, Dependency):
            return self.name == other.name
        return False


@dataclass
class Cluster:
    """
    Represents a cluster of dependencies with shared constraints.
    
    Attributes:
        cluster_id: Unique identifier for the cluster
        classification: Type of cluster classification
        members: List of Dependency objects in this cluster
        locked: Whether the cluster is currently locked for updates
        lock_holder: ID of the operation holding the lock
        abi_compatible_set: Set of ABI versions that are compatible
        created_at: Timestamp of cluster creation
        updated_at: Timestamp of last update
    """
    cluster_id: str
    classification: ClusterClassification
    members: List[Dependency] = field(default_factory=list)
    locked: bool = False
    lock_holder: Optional[str] = None
    abi_compatible_set: Set[str] = field(default_factory=set)
    created_at: str = field(default_factory=now_utc_iso)
    updated_at: str = field(default_factory=now_utc_iso)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "cluster_id": self.cluster_id,
            "classification": self.classification.value,
            "members": [m.to_dict() for m in self.members],
            "locked": self.locked,
            "lock_holder": self.lock_holder,
            "abi_compatible_set": list(self.abi_compatible_set),
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Cluster":
        """Create from dictionary."""
        return cls(
            cluster_id=data["cluster_id"],
            classification=ClusterClassification(data["classification"]),
            members=[Dependency.from_dict(m) for m in data.get("members", [])],
            locked=data.get("locked", False),
            lock_holder=data.get("lock_holder"),
            abi_compatible_set=set(data.get("abi_compatible_set", [])),
            created_at=data.get("created_at", now_utc_iso()),
            updated_at=data.get("updated_at", now_utc_iso())
        )
    
    def get_member_names(self) -> Set[str]:
        """Get set of member names."""
        return {m.name for m in self.members}
    
    def get_member_by_name(self, name: str) -> Optional[Dependency]:
        """Get a member by name."""
        for m in self.members:
            if m.name == name:
                return m
        return None


@dataclass
class UpdateOperation:
    """
    Represents a single update operation within an atomic update.
    
    Attributes:
        operation_id: Unique identifier for this operation
        dep_name: Name of the dependency to update
        old_version: Version to uninstall
        new_version: Version to install
        operation_type: 'uninstall', 'install', or 'update'
        status: Current status of the operation
        error_message: Error message if operation failed
    """
    operation_id: str = field(default_factory=lambda: f"op-{uuid.uuid4().hex[:8]}")
    dep_name: str = ""
    old_version: Optional[str] = None
    new_version: str = ""
    operation_type: str = "update"
    status: UpdateStatus = UpdateStatus.PENDING
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "operation_id": self.operation_id,
            "dep_name": self.dep_name,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "operation_type": self.operation_type,
            "status": self.status.value,
            "error_message": self.error_message
        }


@dataclass
class UpdateResult:
    """
    Result of an atomic update operation.
    
    Attributes:
        success: Whether the update succeeded
        cluster_id: ID of the cluster that was updated
        updates_applied: List of applied update operations
        rollback_needed: Whether rollback is needed
        rollback_performed: Whether rollback was performed
        error_message: Error message if update failed
        pre_state: Captured state before update
        post_state: State after update (if successful)
        duration_ms: Duration of the operation in milliseconds
    """
    success: bool
    cluster_id: str
    updates_applied: List[Dict] = field(default_factory=list)
    rollback_needed: bool = False
    rollback_performed: bool = False
    error_message: Optional[str] = None
    pre_state: Optional[Dict] = None
    post_state: Optional[Dict] = None
    duration_ms: float = 0.0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "cluster_id": self.cluster_id,
            "updates_applied": self.updates_applied,
            "rollback_needed": self.rollback_needed,
            "rollback_performed": self.rollback_performed,
            "error_message": self.error_message,
            "duration_ms": self.duration_ms
        }


class AbiUpdateFailed(Exception):
    """Exception raised when an ABI update fails."""
    
    def __init__(self, message: str, cluster_id: str, rollback_needed: bool = True):
        super().__init__(message)
        self.cluster_id = cluster_id
        self.rollback_needed = rollback_needed


class ClusterLockedError(Exception):
    """Exception raised when trying to update a locked cluster."""
    
    def __init__(self, cluster_id: str, lock_holder: str):
        super().__init__(f"Cluster {cluster_id} is locked by {lock_holder}")
        self.cluster_id = cluster_id
        self.lock_holder = lock_holder


class AbiLockedProtocol:
    """
    ABI Locked Protocol for dependency cluster management.
    
    Implements ITEM-GAP-002: ABI_LOCKED_PROTOCOL
    
    Features:
    - Cluster detection and classification
    - Atomic update operations with rollback
    - Thread-safe cluster locking
    - ABI compatibility checking
    - Integration with distributed locking
    
    Usage:
        config = {
            "enabled": True,
            "clusters_path": ".titan/abi_clusters.json",
            "auto_detect": True,
            "rollback_on_failure": True
        }
        
        protocol = AbiLockedProtocol(config)
        
        # Detect clusters from dependencies
        deps = [Dependency(...), ...]
        clusters = protocol.detect_clusters(deps)
        
        # Perform atomic update
        updates = [
            {"dep_name": "numpy", "old_version": "1.20.0", "new_version": "1.21.0"},
            {"dep_name": "pandas", "old_version": "1.3.0", "new_version": "1.4.0"}
        ]
        result = protocol.atomic_update("cluster-001", updates)
    """
    
    # Known ABI-sensitive packages
    ABI_SENSITIVE_PACKAGES = {
        "numpy", "pandas", "scipy", "numba", "tensorflow",
        "torch", "cupy", "arrow", "pyarrow", "h5py"
    }
    
    # Known cascade dependencies (package -> packages that depend on it)
    CASCADE_DEPENDENCIES = {
        "numpy": ["pandas", "scipy", "numba", "matplotlib", "sklearn"],
        "torch": ["torchvision", "torchaudio", "transformers"],
        "tensorflow": ["tensorflow-hub", "tensorflow-datasets"]
    }
    
    def __init__(
        self,
        config: Optional[Dict] = None,
        event_bus: Optional[Any] = None,
        lock_backend: Optional[Any] = None
    ):
        """
        Initialize the ABI Locked Protocol.
        
        Args:
            config: Configuration dictionary
            event_bus: Optional event bus for emitting events
            lock_backend: Optional distributed lock backend
        """
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.clusters_path = Path(self.config.get("clusters_path", ".titan/abi_clusters.json"))
        self.auto_detect = self.config.get("auto_detect", True)
        self.rollback_on_failure = self.config.get("rollback_on_failure", True)
        
        self._event_bus = event_bus
        self._lock_backend = lock_backend
        
        # Internal state
        self._clusters: Dict[str, Cluster] = {}
        self._clusters_lock = threading.RLock()
        self._operation_locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)
        
        # Logger with [ITEM-GAP-002] prefix
        self._logger = get_logger("abi_locked")
        
        # Load existing clusters
        if self.enabled:
            self._load_clusters()
    
    def _log(self, level: str, message: str, **kwargs) -> None:
        """Log with [ITEM-GAP-002] prefix."""
        prefixed_message = f"[ITEM-GAP-002] {message}"
        getattr(self._logger, level)(prefixed_message, **kwargs)
    
    def _load_clusters(self) -> None:
        """Load clusters from storage."""
        try:
            if self.clusters_path.exists():
                with open(self.clusters_path) as f:
                    data = json.load(f)
                
                for cluster_data in data.get("clusters", []):
                    cluster = Cluster.from_dict(cluster_data)
                    self._clusters[cluster.cluster_id] = cluster
                
                self._log("info", f"Loaded {len(self._clusters)} clusters from storage")
        except Exception as e:
            self._log("warn", f"Failed to load clusters: {e}")
    
    def _save_clusters(self) -> None:
        """Save clusters to storage."""
        try:
            self.clusters_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "version": "1.0.0",
                "clusters": [c.to_dict() for c in self._clusters.values()],
                "updated_at": now_utc_iso()
            }
            
            with open(self.clusters_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            self._log("debug", f"Saved {len(self._clusters)} clusters to storage")
        except Exception as e:
            self._log("error", f"Failed to save clusters: {e}")
    
    def classify_cluster(self, deps: List[Dependency]) -> ClusterClassification:
        """
        Classify a group of dependencies into a cluster type.
        
        Classification rules:
        1. ABANDONED_ANCHOR: Any package with maintainer_status == "abandoned"
        2. CASCADE_NUMPY: Packages that depend on numpy
        3. ABI_LOCKED: Packages with shared ABI requirements
        
        Args:
            deps: List of dependencies to classify
            
        Returns:
            ClusterClassification for the group
        """
        # Check for abandoned packages first (highest priority)
        for dep in deps:
            if dep.maintainer_status == "abandoned":
                return ClusterClassification.ABANDONED_ANCHOR
        
        # Check for numpy cascade
        dep_names = {d.name for d in deps}
        for cascade_root, cascade_deps in self.CASCADE_DEPENDENCIES.items():
            if cascade_root in dep_names:
                # Check if any cascade dependencies are present
                if any(cd in dep_names for cd in cascade_deps):
                    return ClusterClassification.CASCADE_NUMPY
        
        # Check for ABI-sensitive packages
        for dep in deps:
            if dep.name in self.ABI_SENSITIVE_PACKAGES:
                return ClusterClassification.ABI_LOCKED
            
            # Check ABI requirements
            if dep.abi_requirements:
                return ClusterClassification.ABI_LOCKED
            
            if dep.abi_version:
                return ClusterClassification.ABI_LOCKED
        
        # Default to ABI_LOCKED for any dependency cluster
        return ClusterClassification.ABI_LOCKED
    
    def detect_clusters(self, all_deps: List[Dependency]) -> List[Cluster]:
        """
        Detect and classify dependency clusters.
        
        Groups dependencies that should be updated together based on:
        - Shared ABI requirements
        - Cascade dependencies
        - Abandoned status
        
        Args:
            all_deps: List of all dependencies
            
        Returns:
            List of detected Cluster objects
        """
        if not self.enabled:
            return []
        
        with self._clusters_lock:
            self._log("info", f"Detecting clusters from {len(all_deps)} dependencies")
            
            # Build dependency graph
            dep_map: Dict[str, Dependency] = {d.name: d for d in all_deps}
            dependency_graph: Dict[str, Set[str]] = defaultdict(set)
            
            for dep in all_deps:
                for dep_name in dep.dependencies:
                    if dep_name in dep_map:
                        dependency_graph[dep.name].add(dep_name)
            
            # Find connected components
            visited: Set[str] = set()
            clusters: List[Cluster] = []
            
            for dep in all_deps:
                if dep.name in visited:
                    continue
                
                # BFS to find connected component
                component: Set[str] = set()
                queue = [dep.name]
                
                while queue:
                    current = queue.pop(0)
                    if current in visited:
                        continue
                    
                    visited.add(current)
                    component.add(current)
                    
                    # Add dependencies
                    for neighbor in dependency_graph.get(current, []):
                        if neighbor not in visited:
                            queue.append(neighbor)
                    
                    # Add dependents (reverse dependencies)
                    for other_dep in all_deps:
                        if current in other_dep.dependencies and other_dep.name not in visited:
                            queue.append(other_dep.name)
                
                # Create cluster from component
                if len(component) > 1:  # Only clusters with multiple members
                    cluster_deps = [dep_map[n] for n in component if n in dep_map]
                    classification = self.classify_cluster(cluster_deps)
                    
                    cluster = Cluster(
                        cluster_id=f"cluster-{uuid.uuid4().hex[:8]}",
                        classification=classification,
                        members=cluster_deps,
                        abi_compatible_set=self._compute_abi_set(cluster_deps)
                    )
                    
                    clusters.append(cluster)
                    self._clusters[cluster.cluster_id] = cluster
            
            # Save detected clusters
            self._save_clusters()
            
            self._log("info", f"Detected {len(clusters)} clusters")
            self._emit_event("CLUSTERS_DETECTED", {"count": len(clusters)})
            
            return clusters
    
    def _compute_abi_set(self, deps: List[Dependency]) -> Set[str]:
        """Compute the set of ABI requirements for a cluster."""
        abi_set: Set[str] = set()
        
        for dep in deps:
            if dep.abi_version:
                abi_set.add(f"{dep.name}:{dep.abi_version}")
            abi_set.update(dep.abi_requirements)
        
        return abi_set
    
    def lock_cluster(self, cluster_id: str, holder: Optional[str] = None) -> bool:
        """
        Lock a cluster for update operations.
        
        Thread-safe locking with optional distributed lock backend.
        
        Args:
            cluster_id: ID of the cluster to lock
            holder: Optional identifier for the lock holder
            
        Returns:
            True if lock acquired, False otherwise
        """
        with self._clusters_lock:
            cluster = self._clusters.get(cluster_id)
            if not cluster:
                self._log("warn", f"Cluster not found: {cluster_id}")
                return False
            
            if cluster.locked:
                self._log("warn", f"Cluster already locked by {cluster.lock_holder}")
                return False
            
            # Acquire distributed lock if available
            if self._lock_backend:
                lock_key = f"abi_cluster:{cluster_id}"
                if not self._lock_backend.acquire(lock_key, holder or "unknown"):
                    return False
            
            # Set local lock
            cluster.locked = True
            cluster.lock_holder = holder or f"op-{uuid.uuid4().hex[:8]}"
            cluster.updated_at = now_utc_iso()
            
            self._save_clusters()
            self._log("info", f"Locked cluster {cluster_id}", holder=cluster.lock_holder)
            self._emit_event("CLUSTER_LOCKED", {"cluster_id": cluster_id, "holder": cluster.lock_holder})
            
            return True
    
    def unlock_cluster(self, cluster_id: str, holder: Optional[str] = None) -> bool:
        """
        Unlock a cluster after update operations.
        
        Args:
            cluster_id: ID of the cluster to unlock
            holder: Optional identifier to verify lock ownership
            
        Returns:
            True if lock released, False otherwise
        """
        with self._clusters_lock:
            cluster = self._clusters.get(cluster_id)
            if not cluster:
                self._log("warn", f"Cluster not found: {cluster_id}")
                return False
            
            if not cluster.locked:
                return True  # Already unlocked
            
            # Verify ownership if holder provided
            if holder and cluster.lock_holder != holder:
                self._log("warn", f"Lock ownership mismatch: {holder} != {cluster.lock_holder}")
                return False
            
            # Release distributed lock if available
            if self._lock_backend:
                lock_key = f"abi_cluster:{cluster_id}"
                self._lock_backend.release(lock_key)
            
            # Clear local lock
            old_holder = cluster.lock_holder
            cluster.locked = False
            cluster.lock_holder = None
            cluster.updated_at = now_utc_iso()
            
            self._save_clusters()
            self._log("info", f"Unlocked cluster {cluster_id}", previous_holder=old_holder)
            self._emit_event("CLUSTER_UNLOCKED", {"cluster_id": cluster_id})
            
            return True
    
    def is_update_allowed(self, cluster: Cluster, dep_name: str) -> bool:
        """
        Check if an individual update is allowed within a cluster.
        
        Rule: No independent member update within locked cluster.
        All members must be updated together atomically.
        
        Args:
            cluster: The cluster to check
            dep_name: Name of the dependency to update
            
        Returns:
            True if update is allowed, False otherwise
        """
        # Check if dependency is in cluster
        if dep_name not in cluster.get_member_names():
            return True  # Not in cluster, allowed
        
        # For ABI_LOCKED and CASCADE_NUMPY, individual updates not allowed
        if cluster.classification in (
            ClusterClassification.ABI_LOCKED,
            ClusterClassification.CASCADE_NUMPY
        ):
            self._log(
                "warn",
                f"Individual update blocked for {dep_name} in {cluster.classification.value} cluster",
                cluster_id=cluster.cluster_id
            )
            return False
        
        # For ABANDONED_ANCHOR, updates are always blocked
        if cluster.classification == ClusterClassification.ABANDONED_ANCHOR:
            self._log(
                "warn",
                f"Update blocked for {dep_name} - abandoned package",
                cluster_id=cluster.cluster_id
            )
            return False
        
        return True
    
    def capture_state(self, cluster: Cluster) -> Dict:
        """
        Capture the current state of a cluster for rollback.
        
        Args:
            cluster: Cluster to capture state for
            
        Returns:
            Dictionary containing the captured state
        """
        return {
            "cluster_id": cluster.cluster_id,
            "members": [m.to_dict() for m in cluster.members],
            "abi_compatible_set": list(cluster.abi_compatible_set),
            "captured_at": now_utc_iso()
        }
    
    def atomic_update(
        self,
        cluster_id: str,
        updates: List[Dict],
        uninstall_fn: Optional[Callable] = None,
        install_fn: Optional[Callable] = None,
        assert_fn: Optional[Callable] = None
    ) -> UpdateResult:
        """
        Perform an atomic update on a cluster.
        
        Implements the rule: simultaneous uninstall + install + assert
        
        Steps:
        1. Lock the cluster
        2. Capture pre-state for rollback
        3. For each update:
           - Uninstall old version
           - Install new version
        4. Assert ABI compatibility
        5. On failure, rollback to pre-state
        
        Args:
            cluster_id: ID of the cluster to update
            updates: List of update dictionaries with keys:
                     - dep_name: Name of dependency
                     - old_version: Version to uninstall
                     - new_version: Version to install
            uninstall_fn: Optional function to perform uninstall
            install_fn: Optional function to perform install
            assert_fn: Optional function to assert ABI compatibility
            
        Returns:
            UpdateResult with operation outcome
        """
        start_time = now_utc()
        
        if not self.enabled:
            return UpdateResult(
                success=False,
                cluster_id=cluster_id,
                error_message="ABI Locked Protocol is disabled"
            )
        
        # Get cluster
        with self._clusters_lock:
            cluster = self._clusters.get(cluster_id)
            if not cluster:
                return UpdateResult(
                    success=False,
                    cluster_id=cluster_id,
                    error_message=f"Cluster not found: {cluster_id}"
                )
        
        # Check if cluster is already locked
        if cluster.locked:
            raise ClusterLockedError(cluster_id, cluster.lock_holder)
        
        # Validate all updates target cluster members
        member_names = cluster.get_member_names()
        for update in updates:
            if update.get("dep_name") not in member_names:
                return UpdateResult(
                    success=False,
                    cluster_id=cluster_id,
                    error_message=f"Update target {update.get('dep_name')} not in cluster"
                )
        
        # Lock the cluster
        operation_id = f"op-{uuid.uuid4().hex[:8]}"
        if not self.lock_cluster(cluster_id, operation_id):
            return UpdateResult(
                success=False,
                cluster_id=cluster_id,
                error_message="Failed to acquire cluster lock"
            )
        
        try:
            # Capture pre-state
            pre_state = self.capture_state(cluster)
            
            self._log(
                "info",
                f"Starting atomic update for cluster {cluster_id}",
                operation_id=operation_id,
                update_count=len(updates)
            )
            self._emit_event("ATOMIC_UPDATE_STARTED", {
                "cluster_id": cluster_id,
                "operation_id": operation_id,
                "update_count": len(updates)
            })
            
            # Create update operations
            operations: List[UpdateOperation] = []
            for update in updates:
                op = UpdateOperation(
                    dep_name=update["dep_name"],
                    old_version=update.get("old_version"),
                    new_version=update["new_version"],
                    operation_type="update"
                )
                operations.append(op)
            
            applied_updates: List[Dict] = []
            
            # Execute updates
            for op in operations:
                try:
                    op.status = UpdateStatus.IN_PROGRESS
                    
                    # Uninstall old version
                    if op.old_version and uninstall_fn:
                        self._log("debug", f"Uninstalling {op.dep_name}=={op.old_version}")
                        uninstall_fn(op.dep_name, op.old_version)
                    
                    # Install new version
                    if install_fn:
                        self._log("debug", f"Installing {op.dep_name}=={op.new_version}")
                        install_fn(op.dep_name, op.new_version)
                    
                    # Update cluster member version
                    member = cluster.get_member_by_name(op.dep_name)
                    if member:
                        member.version = op.new_version
                    
                    op.status = UpdateStatus.COMPLETED
                    applied_updates.append(op.to_dict())
                    
                except Exception as e:
                    op.status = UpdateStatus.FAILED
                    op.error_message = str(e)
                    
                    self._log("error", f"Update failed for {op.dep_name}: {e}")
                    
                    # Rollback if configured
                    if self.rollback_on_failure:
                        self._rollback(cluster, pre_state, applied_updates, uninstall_fn, install_fn)
                        return UpdateResult(
                            success=False,
                            cluster_id=cluster_id,
                            rollback_needed=True,
                            rollback_performed=True,
                            error_message=f"Update failed: {e}",
                            pre_state=pre_state
                        )
                    else:
                        raise AbiUpdateFailed(str(e), cluster_id)
            
            # Assert ABI compatibility
            if assert_fn:
                try:
                    self._log("debug", "Asserting ABI compatibility")
                    assert_fn(cluster)
                except AssertionError as e:
                    self._log("error", f"ABI assertion failed: {e}")
                    
                    if self.rollback_on_failure:
                        self._rollback(cluster, pre_state, applied_updates, uninstall_fn, install_fn)
                        return UpdateResult(
                            success=False,
                            cluster_id=cluster_id,
                            rollback_needed=True,
                            rollback_performed=True,
                            error_message=f"ABI assertion failed: {e}",
                            pre_state=pre_state
                        )
                    else:
                        raise AbiUpdateFailed(f"ABI assertion failed: {e}", cluster_id)
            
            # Update cluster metadata
            cluster.updated_at = now_utc_iso()
            self._save_clusters()
            
            duration_ms = (now_utc() - start_time).total_seconds() * 1000
            
            self._log(
                "info",
                f"Atomic update completed for cluster {cluster_id}",
                operation_id=operation_id,
                duration_ms=duration_ms
            )
            self._emit_event("ATOMIC_UPDATE_COMPLETED", {
                "cluster_id": cluster_id,
                "operation_id": operation_id,
                "success": True,
                "duration_ms": duration_ms
            })
            
            return UpdateResult(
                success=True,
                cluster_id=cluster_id,
                updates_applied=applied_updates,
                pre_state=pre_state,
                post_state=self.capture_state(cluster),
                duration_ms=duration_ms
            )
            
        except Exception as e:
            self._log("error", f"Atomic update failed: {e}")
            self._emit_event("ATOMIC_UPDATE_FAILED", {
                "cluster_id": cluster_id,
                "operation_id": operation_id,
                "error": str(e)
            })
            raise
        finally:
            # Always unlock the cluster
            self.unlock_cluster(cluster_id, operation_id)
    
    def _rollback(
        self,
        cluster: Cluster,
        pre_state: Dict,
        applied_updates: List[Dict],
        uninstall_fn: Optional[Callable],
        install_fn: Optional[Callable]
    ) -> None:
        """
        Rollback an atomic update to a previous state.
        
        Args:
            cluster: Cluster to rollback
            pre_state: Captured state before update
            applied_updates: Updates that were applied
            uninstall_fn: Function to uninstall packages
            install_fn: Function to install packages
        """
        self._log("warn", f"Rolling back cluster {cluster.cluster_id}")
        self._emit_event("ROLLBACK_STARTED", {"cluster_id": cluster.cluster_id})
        
        # Reverse the applied updates
        for update in reversed(applied_updates):
            try:
                # Uninstall the new version
                if uninstall_fn:
                    uninstall_fn(update["dep_name"], update["new_version"])
                
                # Reinstall the old version
                if install_fn and update.get("old_version"):
                    install_fn(update["dep_name"], update["old_version"])
                
                # Restore member version
                member = cluster.get_member_by_name(update["dep_name"])
                if member and update.get("old_version"):
                    member.version = update["old_version"]
                    
            except Exception as e:
                self._log("error", f"Rollback failed for {update['dep_name']}: {e}")
        
        # Restore cluster state
        cluster.abi_compatible_set = set(pre_state.get("abi_compatible_set", []))
        cluster.updated_at = now_utc_iso()
        
        self._save_clusters()
        self._emit_event("ROLLBACK_COMPLETED", {"cluster_id": cluster.cluster_id})
    
    def get_cluster(self, cluster_id: str) -> Optional[Cluster]:
        """
        Get a cluster by ID.
        
        Args:
            cluster_id: ID of the cluster
            
        Returns:
            Cluster if found, None otherwise
        """
        return self._clusters.get(cluster_id)
    
    def get_all_clusters(self) -> List[Cluster]:
        """Get all clusters."""
        return list(self._clusters.values())
    
    def get_clusters_for_dependency(self, dep_name: str) -> List[Cluster]:
        """
        Get all clusters containing a dependency.
        
        Args:
            dep_name: Name of the dependency
            
        Returns:
            List of clusters containing the dependency
        """
        return [
            c for c in self._clusters.values()
            if dep_name in c.get_member_names()
        ]
    
    def _emit_event(self, event_type: str, data: Dict) -> None:
        """Emit an event if event bus is available."""
        if self._event_bus:
            try:
                self._event_bus.emit(event_type, {
                    "source": "abi_locked_protocol",
                    **data
                })
            except Exception as e:
                self._log("warn", f"Failed to emit event: {e}")
    
    def get_stats(self) -> Dict:
        """
        Get statistics about the protocol state.
        
        Returns:
            Dictionary with statistics
        """
        with self._clusters_lock:
            classification_counts = defaultdict(int)
            locked_count = 0
            
            for cluster in self._clusters.values():
                classification_counts[cluster.classification.value] += 1
                if cluster.locked:
                    locked_count += 1
            
            return {
                "enabled": self.enabled,
                "total_clusters": len(self._clusters),
                "locked_clusters": locked_count,
                "by_classification": dict(classification_counts),
                "clusters_path": str(self.clusters_path)
            }


def create_abi_locked_protocol(
    config: Optional[Dict] = None,
    event_bus: Optional[Any] = None,
    lock_backend: Optional[Any] = None
) -> AbiLockedProtocol:
    """
    Factory function to create AbiLockedProtocol.
    
    Args:
        config: Configuration dictionary
        event_bus: Optional event bus for events
        lock_backend: Optional distributed lock backend
        
    Returns:
        Configured AbiLockedProtocol instance
    """
    return AbiLockedProtocol(
        config=config,
        event_bus=event_bus,
        lock_backend=lock_backend
    )
