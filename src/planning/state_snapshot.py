"""
State Snapshot Manager for TITAN FUSE Protocol.

Provides DAG checkpointing with per-node rollback capability
for partial recovery on failure.

Author: TITAN FUSE Team
Version: 3.2.3
"""

import json
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict, field
from datetime import datetime
import logging


@dataclass
class StateSnapshot:
    """
    State snapshot for DAG node rollback.

    Captures complete state at a point in time for recovery.
    """
    node_id: str
    timestamp: str
    chunks_state: Dict
    gates_passed: List[str]
    tokens_used: int
    open_issues: List[str]
    cursor_hash: Optional[str] = None
    phase: int = 0
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'StateSnapshot':
        """Create from dictionary."""
        return cls(
            node_id=data["node_id"],
            timestamp=data["timestamp"],
            chunks_state=data.get("chunks_state", {}),
            gates_passed=data.get("gates_passed", []),
            tokens_used=data.get("tokens_used", 0),
            open_issues=data.get("open_issues", []),
            cursor_hash=data.get("cursor_hash"),
            phase=data.get("phase", 0),
            metadata=data.get("metadata", {})
        )

    def __str__(self) -> str:
        """Human-readable representation."""
        return (
            f"Snapshot({self.node_id}, phase={self.phase}, "
            f"gates={len(self.gates_passed)}, tokens={self.tokens_used})"
        )


class SnapshotManager:
    """
    Manage state snapshots for rollback.

    Provides:
    - Save/load snapshots for each DAG node
    - Find nearest stable node for rollback
    - Automatic cleanup of old snapshots
    - Rollback planning

    Usage:
        manager = SnapshotManager(Path("snapshots/"))

        # Save before node execution
        manager.save_snapshot("node_1", current_state)

        # On failure, find rollback point
        rollback_node = manager.find_nearest_stable("node_5", dag_nodes)

        # Load and restore
        snapshot = manager.load_snapshot(rollback_node)
    """

    def __init__(self, snapshot_dir: Path, max_snapshots: int = 50):
        """
        Initialize SnapshotManager.

        Args:
            snapshot_dir: Directory to store snapshots
            max_snapshots: Maximum number of snapshots to keep
        """
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.max_snapshots = max_snapshots
        self._logger = logging.getLogger(__name__)

    def save_snapshot(self, node_id: str, state: Dict) -> Path:
        """
        Save state snapshot before node execution.

        Args:
            node_id: Unique identifier for the DAG node
            state: Current state dictionary

        Returns:
            Path to saved snapshot file
        """
        snapshot = StateSnapshot(
            node_id=node_id,
            timestamp=datetime.utcnow().isoformat() + "Z",
            chunks_state=state.get("chunks", {}),
            gates_passed=[
                g for g, s in state.get("gates", {}).items()
                if s.get("status") == "PASS"
            ],
            tokens_used=state.get("tokens_used", 0),
            open_issues=state.get("open_issues", []),
            cursor_hash=state.get("cursor_hash"),
            phase=state.get("phase", 0),
            metadata=state.get("metadata", {})
        )

        path = self.snapshot_dir / f"{node_id}.json"
        with open(path, 'w') as f:
            json.dump(snapshot.to_dict(), f, indent=2)

        self._logger.info(f"Saved snapshot: {node_id}")
        self._cleanup_old_snapshots()
        return path

    def load_snapshot(self, node_id: str) -> Optional[StateSnapshot]:
        """
        Load snapshot for rollback.

        Args:
            node_id: Node identifier to load

        Returns:
            StateSnapshot or None if not found
        """
        path = self.snapshot_dir / f"{node_id}.json"
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                self._logger.info(f"Loaded snapshot: {node_id}")
                return StateSnapshot.from_dict(data)
            except Exception as e:
                self._logger.error(f"Failed to load snapshot {node_id}: {e}")
                return None
        return None

    def delete_snapshot(self, node_id: str) -> bool:
        """
        Delete a snapshot.

        Returns:
            True if deleted, False if not found
        """
        path = self.snapshot_dir / f"{node_id}.json"
        if path.exists():
            path.unlink()
            self._logger.debug(f"Deleted snapshot: {node_id}")
            return True
        return False

    def find_nearest_stable(self, current_node: str,
                           dag_nodes: List[str]) -> Optional[str]:
        """
        Find nearest stable node for rollback.

        Args:
            current_node: Current node where failure occurred
            dag_nodes: List of all DAG nodes in order

        Returns:
            Node ID of nearest stable snapshot, or None
        """
        try:
            current_idx = dag_nodes.index(current_node)
        except ValueError:
            self._logger.warning(f"Current node {current_node} not in DAG")
            return None

        # Search backwards for a node with a valid snapshot
        for i in range(current_idx - 1, -1, -1):
            node = dag_nodes[i]
            if self.load_snapshot(node):
                self._logger.info(
                    f"Found stable rollback point: {node} "
                    f"({current_idx - i} nodes back)"
                )
                return node

        self._logger.warning("No stable snapshot found for rollback")
        return None

    def list_snapshots(self) -> List[str]:
        """List all saved snapshot IDs."""
        return [p.stem for p in self.snapshot_dir.glob("*.json")]

    def get_rollback_plan(self, current_node: str,
                         dag_nodes: List[str]) -> Dict:
        """
        Get rollback plan from current node.

        Args:
            current_node: Node where failure occurred
            dag_nodes: List of all DAG nodes in order

        Returns:
            Dict with rollback plan details
        """
        nearest = self.find_nearest_stable(current_node, dag_nodes)

        if not nearest:
            return {
                "can_rollback": False,
                "reason": "No stable snapshot found",
                "current_node": current_node,
                "available_snapshots": self.list_snapshots()
            }

        snapshot = self.load_snapshot(nearest)
        try:
            current_idx = dag_nodes.index(current_node)
            nearest_idx = dag_nodes.index(nearest)
            nodes_to_reexecute = dag_nodes[nearest_idx + 1:current_idx + 1]
        except ValueError:
            nodes_to_reexecute = []

        return {
            "can_rollback": True,
            "target_node": nearest,
            "snapshot": snapshot.to_dict() if snapshot else None,
            "nodes_to_reexecute": nodes_to_reexecute,
            "reexecute_count": len(nodes_to_reexecute),
            "tokens_to_recover": snapshot.tokens_used if snapshot else 0
        }

    def get_snapshot_info(self, node_id: str) -> Optional[Dict]:
        """Get snapshot info without full content."""
        path = self.snapshot_dir / f"{node_id}.json"
        if path.exists():
            stat = path.stat()
            return {
                "node_id": node_id,
                "file_size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat() + "Z"
            }
        return None

    def get_disk_usage(self) -> Dict:
        """Get total disk usage of snapshots."""
        total_size = 0
        count = 0
        for path in self.snapshot_dir.glob("*.json"):
            total_size += path.stat().st_size
            count += 1

        return {
            "total_bytes": total_size,
            "total_mb": round(total_size / (1024 * 1024), 2),
            "snapshot_count": count,
            "average_size_bytes": total_size // max(count, 1)
        }

    def _cleanup_old_snapshots(self) -> None:
        """Remove old snapshots if count exceeds max."""
        snapshots = sorted(
            self.snapshot_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True  # Newest first
        )

        while len(snapshots) > self.max_snapshots:
            oldest = snapshots.pop()
            oldest.unlink()
            self._logger.debug(f"Removed old snapshot: {oldest.stem}")

    def clear_all(self) -> int:
        """Clear all snapshots.

        Returns:
            Number of snapshots removed
        """
        count = 0
        for path in self.snapshot_dir.glob("*.json"):
            path.unlink()
            count += 1
        self._logger.info(f"Cleared {count} snapshots")
        return count
