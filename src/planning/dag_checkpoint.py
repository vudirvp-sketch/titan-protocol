"""
DAG Checkpoint Manager for TITAN FUSE Protocol.

ITEM-FEAT-111: Implements per-node checkpointing with rollback
for DAG execution recovery.

Author: TITAN FUSE Team
Version: 3.4.0
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import json
import logging
import copy


@dataclass
class DAGSnapshot:
    """Snapshot of DAG execution state at a node."""
    snapshot_id: str
    node_id: str
    timestamp: str
    phase: int
    state_data: Dict
    gates_passed: List[str]
    tokens_used: int
    parent_snapshot_id: Optional[str] = None
    stable: bool = True
    rollback_count: int = 0
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "snapshot_id": self.snapshot_id,
            "node_id": self.node_id,
            "timestamp": self.timestamp,
            "phase": self.phase,
            "state_data": self.state_data,
            "gates_passed": self.gates_passed,
            "tokens_used": self.tokens_used,
            "parent_snapshot_id": self.parent_snapshot_id,
            "stable": self.stable,
            "rollback_count": self.rollback_count,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'DAGSnapshot':
        return cls(
            snapshot_id=data["snapshot_id"],
            node_id=data["node_id"],
            timestamp=data["timestamp"],
            phase=data.get("phase", 0),
            state_data=data.get("state_data", {}),
            gates_passed=data.get("gates_passed", []),
            tokens_used=data.get("tokens_used", 0),
            parent_snapshot_id=data.get("parent_snapshot_id"),
            stable=data.get("stable", True),
            rollback_count=data.get("rollback_count", 0),
            metadata=data.get("metadata", {})
        )


class DAGCheckpointManager:
    """
    Manage per-node checkpoints for DAG execution.
    
    ITEM-FEAT-111: DAG checkpointing with rollback.
    
    Provides:
    - Snapshot creation before each node execution
    - Rollback to previous stable snapshot on failure
    - Finding nearest stable snapshot for recovery
    - Checkpoint persistence
    
    Usage:
        manager = DAGCheckpointManager(Path(".titan/dag_checkpoints"))
        
        # Before executing node
        snapshot_id = manager.snapshot_before_node("node_1", current_state)
        
        # On node failure
        rollback_snapshot = manager.rollback_to_node("node_1")
        state = rollback_snapshot.state_data
        
        # List all snapshots
        snapshots = manager.list_snapshots()
    """
    
    def __init__(self, checkpoint_dir: Path = None, max_snapshots: int = 100):
        """
        Initialize DAG checkpoint manager.
        
        Args:
            checkpoint_dir: Directory to store checkpoint files
            max_snapshots: Maximum number of snapshots to keep
        """
        self._checkpoint_dir = checkpoint_dir or Path(".titan/dag_checkpoints")
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._max_snapshots = max_snapshots
        self._logger = logging.getLogger(__name__)
        
        # In-memory cache
        self._snapshots: Dict[str, DAGSnapshot] = {}
        self._node_to_snapshot: Dict[str, str] = {}  # node_id -> snapshot_id
        self._execution_order: List[str] = []
        
        # Load existing snapshots
        self._load_snapshots()
    
    def _load_snapshots(self) -> None:
        """Load existing snapshots from disk."""
        for path in self._checkpoint_dir.glob("*.json"):
            try:
                with open(path) as f:
                    data = json.load(f)
                snapshot = DAGSnapshot.from_dict(data)
                self._snapshots[snapshot.snapshot_id] = snapshot
                self._node_to_snapshot[snapshot.node_id] = snapshot.snapshot_id
            except Exception as e:
                self._logger.error(f"Failed to load snapshot {path}: {e}")
    
    def snapshot_before_node(self, node_id: str, state: Dict,
                            phase: int = 0) -> str:
        """
        Create a snapshot before node execution.
        
        Args:
            node_id: ID of the node about to execute
            state: Current state dictionary
            phase: Current execution phase
            
        Returns:
            Snapshot ID
        """
        snapshot_id = f"snap-{node_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
        
        # Find parent snapshot
        parent_id = None
        if self._execution_order:
            last_node = self._execution_order[-1]
            parent_id = self._node_to_snapshot.get(last_node)
        
        snapshot = DAGSnapshot(
            snapshot_id=snapshot_id,
            node_id=node_id,
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase=phase,
            state_data=copy.deepcopy(state),
            gates_passed=state.get("gates_passed", []),
            tokens_used=state.get("tokens_used", 0),
            parent_snapshot_id=parent_id,
            stable=True,
            metadata=state.get("metadata", {})
        )
        
        self._snapshots[snapshot_id] = snapshot
        self._node_to_snapshot[node_id] = snapshot_id
        self._execution_order.append(node_id)
        
        # Persist to disk
        self._save_snapshot(snapshot)
        
        # Cleanup old snapshots
        self._cleanup_old_snapshots()
        
        self._logger.info(f"Created snapshot: {snapshot_id} for node {node_id}")
        
        return snapshot_id
    
    def _save_snapshot(self, snapshot: DAGSnapshot) -> None:
        """Save snapshot to disk."""
        path = self._checkpoint_dir / f"{snapshot.snapshot_id}.json"
        with open(path, 'w') as f:
            json.dump(snapshot.to_dict(), f, indent=2)
    
    def rollback_to_node(self, node_id: str) -> Optional[DAGSnapshot]:
        """
        Rollback to a specific node's snapshot.
        
        Args:
            node_id: Node ID to rollback to
            
        Returns:
            DAGSnapshot if found, None otherwise
        """
        snapshot_id = self._node_to_snapshot.get(node_id)
        if snapshot_id is None:
            self._logger.warning(f"No snapshot found for node {node_id}")
            return None
        
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            self._logger.warning(f"Snapshot {snapshot_id} not found in memory")
            return None
        
        # Mark rollback
        snapshot.rollback_count += 1
        self._save_snapshot(snapshot)
        
        # Update execution order
        if node_id in self._execution_order:
            idx = self._execution_order.index(node_id)
            self._execution_order = self._execution_order[:idx + 1]
        
        self._logger.info(
            f"Rolled back to node {node_id} (snapshot {snapshot_id}, "
            f"rollback #{snapshot.rollback_count})"
        )
        
        return snapshot
    
    def find_nearest_stable(self, current_node: str,
                           dag_nodes: List[str] = None) -> Optional[str]:
        """
        Find nearest stable snapshot for rollback.
        
        Args:
            current_node: Current failed node
            dag_nodes: List of DAG nodes in order (optional)
            
        Returns:
            Node ID of nearest stable snapshot
        """
        nodes = dag_nodes or self._execution_order
        
        if current_node not in nodes:
            self._logger.warning(f"Node {current_node} not in DAG")
            return None
        
        try:
            current_idx = nodes.index(current_node)
        except ValueError:
            return None
        
        # Search backwards for stable snapshot
        for i in range(current_idx - 1, -1, -1):
            node_id = nodes[i]
            snapshot_id = self._node_to_snapshot.get(node_id)
            
            if snapshot_id:
                snapshot = self._snapshots.get(snapshot_id)
                if snapshot and snapshot.stable:
                    self._logger.info(
                        f"Found stable snapshot at node {node_id} "
                        f"({current_idx - i} nodes back)"
                    )
                    return node_id
        
        self._logger.warning("No stable snapshot found for rollback")
        return None
    
    def mark_unstable(self, node_id: str) -> None:
        """Mark a snapshot as unstable (after failure)."""
        snapshot_id = self._node_to_snapshot.get(node_id)
        if snapshot_id:
            snapshot = self._snapshots.get(snapshot_id)
            if snapshot:
                snapshot.stable = False
                self._save_snapshot(snapshot)
                self._logger.info(f"Marked snapshot {snapshot_id} as unstable")
    
    def mark_stable(self, node_id: str) -> None:
        """Mark a snapshot as stable (after successful completion)."""
        snapshot_id = self._node_to_snapshot.get(node_id)
        if snapshot_id:
            snapshot = self._snapshots.get(snapshot_id)
            if snapshot:
                snapshot.stable = True
                self._save_snapshot(snapshot)
    
    def list_snapshots(self) -> List[Dict]:
        """
        List all snapshots.
        
        Returns:
            List of snapshot info dictionaries
        """
        return [
            {
                "snapshot_id": s.snapshot_id,
                "node_id": s.node_id,
                "timestamp": s.timestamp,
                "phase": s.phase,
                "tokens_used": s.tokens_used,
                "stable": s.stable,
                "rollback_count": s.rollback_count
            }
            for s in sorted(
                self._snapshots.values(),
                key=lambda x: x.timestamp
            )
        ]
    
    def get_snapshot(self, snapshot_id: str) -> Optional[DAGSnapshot]:
        """Get a specific snapshot by ID."""
        return self._snapshots.get(snapshot_id)
    
    def get_node_snapshot(self, node_id: str) -> Optional[DAGSnapshot]:
        """Get the snapshot for a specific node."""
        snapshot_id = self._node_to_snapshot.get(node_id)
        if snapshot_id:
            return self._snapshots.get(snapshot_id)
        return None
    
    def get_rollback_plan(self, current_node: str,
                         dag_nodes: List[str] = None) -> Dict:
        """
        Get a rollback plan from the current node.
        
        Args:
            current_node: Current failed node
            dag_nodes: List of DAG nodes in order
            
        Returns:
            Dict with rollback plan details
        """
        nodes = dag_nodes or self._execution_order
        target_node = self.find_nearest_stable(current_node, nodes)
        
        if not target_node:
            return {
                "can_rollback": False,
                "reason": "No stable snapshot found",
                "current_node": current_node
            }
        
        snapshot = self.get_node_snapshot(target_node)
        
        # Determine nodes to re-execute
        try:
            current_idx = nodes.index(current_node)
            target_idx = nodes.index(target_node)
            nodes_to_reexecute = nodes[target_idx:current_idx + 1]
        except ValueError:
            nodes_to_reexecute = []
        
        return {
            "can_rollback": True,
            "target_node": target_node,
            "snapshot_id": snapshot.snapshot_id if snapshot else None,
            "state": snapshot.state_data if snapshot else None,
            "nodes_to_reexecute": nodes_to_reexecute,
            "reexecute_count": len(nodes_to_reexecute),
            "tokens_to_recover": snapshot.tokens_used if snapshot else 0
        }
    
    def _cleanup_old_snapshots(self) -> None:
        """Remove old snapshots if over limit."""
        if len(self._snapshots) <= self._max_snapshots:
            return
        
        # Sort by timestamp
        sorted_snapshots = sorted(
            self._snapshots.values(),
            key=lambda s: s.timestamp
        )
        
        # Remove oldest
        to_remove = len(self._snapshots) - self._max_snapshots
        for snapshot in sorted_snapshots[:to_remove]:
            del self._snapshots[snapshot.snapshot_id]
            if snapshot.node_id in self._node_to_snapshot:
                if self._node_to_snapshot[snapshot.node_id] == snapshot.snapshot_id:
                    del self._node_to_snapshot[snapshot.node_id]
            
            # Remove from disk
            path = self._checkpoint_dir / f"{snapshot.snapshot_id}.json"
            if path.exists():
                path.unlink()
        
        self._logger.info(f"Cleaned up {to_remove} old snapshots")
    
    def clear(self) -> int:
        """
        Clear all snapshots.
        
        Returns:
            Number of snapshots removed
        """
        count = len(self._snapshots)
        
        # Remove from disk
        for path in self._checkpoint_dir.glob("*.json"):
            path.unlink()
        
        # Clear memory
        self._snapshots.clear()
        self._node_to_snapshot.clear()
        self._execution_order.clear()
        
        self._logger.info(f"Cleared {count} snapshots")
        return count
    
    def get_stats(self) -> Dict:
        """Get checkpoint statistics."""
        stable_count = sum(1 for s in self._snapshots.values() if s.stable)
        
        return {
            "total_snapshots": len(self._snapshots),
            "stable_snapshots": stable_count,
            "unstable_snapshots": len(self._snapshots) - stable_count,
            "max_snapshots": self._max_snapshots,
            "nodes_tracked": len(self._node_to_snapshot),
            "checkpoint_dir": str(self._checkpoint_dir)
        }


def create_dag_checkpoint_manager(
    checkpoint_dir: Path = None,
    max_snapshots: int = 100
) -> DAGCheckpointManager:
    """
    Factory function to create a DAGCheckpointManager.
    
    Args:
        checkpoint_dir: Directory for checkpoint storage
        max_snapshots: Maximum number of snapshots
        
    Returns:
        DAGCheckpointManager instance
    """
    return DAGCheckpointManager(checkpoint_dir, max_snapshots)
