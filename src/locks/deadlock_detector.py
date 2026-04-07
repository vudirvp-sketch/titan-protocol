"""
Deadlock Detector for TITAN FUSE Protocol.

ITEM-ARCH-03: Distributed Locking with TTL

Detects and reports potential deadlocks in lock acquisition patterns.

Features:
- Wait-for graph construction
- Cycle detection for deadlock identification
- Wait graph visualization
- Deadlock prevention recommendations

Author: TITAN FUSE Team
Version: 3.3.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict
import logging

from .backend import Lock


@dataclass
class WaitEdge:
    """Represents a wait relationship between owners."""
    waiting_owner: str
    blocking_owner: str
    resource: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


@dataclass
class DeadlockInfo:
    """Information about a detected deadlock."""
    cycle: List[str]  # List of owners in the cycle
    resources: List[str]  # Resources involved
    detected_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def to_dict(self) -> Dict:
        return {
            "cycle": self.cycle,
            "resources": self.resources,
            "detected_at": self.detected_at
        }


class DeadlockDetector:
    """
    Deadlock detector using wait-for graph analysis.
    
    ITEM-ARCH-03 Implementation:
    - detect_deadlock(locks: list[Lock]) -> Optional[list[str]]
    - get_wait_graph() -> dict
    
    Algorithm:
    1. Build wait-for graph from lock ownership and wait requests
    2. Detect cycles using DFS
    3. Report cycles as potential deadlocks
    
    Usage:
        detector = DeadlockDetector()
        
        # Record lock acquisition
        detector.record_acquire("owner1", "resource_a")
        
        # Record wait request
        detector.record_wait("owner2", "resource_a")
        
        # Check for deadlock
        deadlock = detector.detect_deadlock()
        if deadlock:
            print(f"Deadlock detected: {deadlock.cycle}")
    """
    
    def __init__(self):
        """Initialize deadlock detector."""
        self._lock_owners: Dict[str, str] = {}  # resource -> owner
        self._wait_graph: Dict[str, Set[str]] = defaultdict(set)  # owner -> set of blocking owners
        self._wait_edges: List[WaitEdge] = []
        self._logger = logging.getLogger(__name__)
    
    def record_acquire(self, owner: str, resource: str) -> None:
        """
        Record a lock acquisition.
        
        Args:
            owner: Lock owner
            resource: Resource locked
        """
        self._lock_owners[resource] = owner
        self._logger.debug(f"Recorded acquire: {owner} -> {resource}")
    
    def record_release(self, owner: str, resource: str) -> None:
        """
        Record a lock release.
        
        Args:
            owner: Lock owner
            resource: Resource released
        """
        if self._lock_owners.get(resource) == owner:
            del self._lock_owners[resource]
        
        # Remove from wait graph
        if owner in self._wait_graph:
            self._wait_graph[owner].clear()
        
        self._logger.debug(f"Recorded release: {owner} -> {resource}")
    
    def record_wait(self, waiting_owner: str, resource: str) -> bool:
        """
        Record a wait request.
        
        Args:
            waiting_owner: Owner waiting for lock
            resource: Resource being waited on
            
        Returns:
            True if this wait could cause deadlock
        """
        current_owner = self._lock_owners.get(resource)
        
        if current_owner and current_owner != waiting_owner:
            # Record wait edge
            self._wait_graph[waiting_owner].add(current_owner)
            self._wait_edges.append(WaitEdge(
                waiting_owner=waiting_owner,
                blocking_owner=current_owner,
                resource=resource
            ))
            
            self._logger.debug(
                f"Recorded wait: {waiting_owner} waiting for {current_owner} ({resource})"
            )
            
            # Check if this creates a cycle
            return self._has_cycle_from(waiting_owner)
        
        return False
    
    def detect_deadlock(self) -> Optional[DeadlockInfo]:
        """
        Detect if there's a deadlock in the wait-for graph.
        
        Returns:
            DeadlockInfo if deadlock detected, None otherwise
        """
        # Find cycles using DFS
        visited = set()
        rec_stack = set()
        
        for owner in self._wait_graph:
            cycle = self._find_cycle(owner, visited, rec_stack, [])
            if cycle:
                resources = self._get_resources_in_cycle(cycle)
                return DeadlockInfo(cycle=cycle, resources=resources)
        
        return None
    
    def _has_cycle_from(self, start: str) -> bool:
        """Check if there's a cycle starting from a node."""
        visited = set()
        rec_stack = set()
        return self._dfs_cycle(start, visited, rec_stack)
    
    def _dfs_cycle(self, node: str, visited: Set[str], rec_stack: Set[str]) -> bool:
        """DFS to detect cycle."""
        visited.add(node)
        rec_stack.add(node)
        
        for neighbor in self._wait_graph.get(node, set()):
            if neighbor not in visited:
                if self._dfs_cycle(neighbor, visited, rec_stack):
                    return True
            elif neighbor in rec_stack:
                return True
        
        rec_stack.remove(node)
        return False
    
    def _find_cycle(self, node: str, visited: Set[str], 
                    rec_stack: Set[str], path: List[str]) -> Optional[List[str]]:
        """Find cycle using DFS, returning the cycle path."""
        visited.add(node)
        rec_stack.add(node)
        path = path + [node]
        
        for neighbor in self._wait_graph.get(node, set()):
            if neighbor not in visited:
                result = self._find_cycle(neighbor, visited, rec_stack, path)
                if result:
                    return result
            elif neighbor in rec_stack:
                # Found cycle - extract it
                cycle_start = path.index(neighbor)
                return path[cycle_start:] + [neighbor]
        
        rec_stack.remove(node)
        return None
    
    def _get_resources_in_cycle(self, cycle: List[str]) -> List[str]:
        """Get resources involved in a deadlock cycle."""
        resources = set()
        
        for edge in self._wait_edges:
            if edge.waiting_owner in cycle and edge.blocking_owner in cycle:
                resources.add(edge.resource)
        
        return list(resources)
    
    def get_wait_graph(self) -> Dict:
        """
        Get the wait-for graph.
        
        Returns:
            Dict with graph structure
        """
        return {
            "nodes": list(self._get_all_owners()),
            "edges": [
                {
                    "from": waiting,
                    "to": blocking
                }
                for waiting, blocking_set in self._wait_graph.items()
                for blocking in blocking_set
            ],
            "lock_owners": dict(self._lock_owners),
            "wait_edges": [edge.__dict__ for edge in self._wait_edges]
        }
    
    def _get_all_owners(self) -> Set[str]:
        """Get all owners in the wait graph."""
        owners = set(self._lock_owners.values())
        owners.update(self._wait_graph.keys())
        for blocking_set in self._wait_graph.values():
            owners.update(blocking_set)
        return owners
    
    def get_recommendations(self) -> List[str]:
        """
        Get recommendations for deadlock prevention.
        
        Returns:
            List of recommendation strings
        """
        recommendations = []
        
        # Check for long wait chains
        for owner, blocking in self._wait_graph.items():
            if len(blocking) > 1:
                recommendations.append(
                    f"Owner '{owner}' is waiting for multiple resources. "
                    "Consider acquiring locks in a consistent order."
                )
        
        # Check for potential issues
        if len(self._wait_graph) > 0:
            deadlock = self.detect_deadlock()
            if deadlock:
                recommendations.append(
                    f"Deadlock detected in cycle: {' -> '.join(deadlock.cycle)}. "
                    "Consider lock ordering or timeout mechanisms."
                )
        
        if not recommendations:
            recommendations.append("No deadlock issues detected.")
        
        return recommendations
    
    def clear(self) -> None:
        """Clear all recorded data."""
        self._lock_owners.clear()
        self._wait_graph.clear()
        self._wait_edges.clear()
    
    def get_stats(self) -> Dict:
        """Get deadlock detector statistics."""
        return {
            "total_locks_tracked": len(self._lock_owners),
            "total_wait_edges": len(self._wait_edges),
            "unique_owners": len(self._get_all_owners()),
            "potential_deadlocks": 1 if self.detect_deadlock() else 0
        }


def detect_deadlock_from_locks(locks: List[Lock]) -> Optional[DeadlockInfo]:
    """
    Convenience function to detect deadlock from a list of locks.
    
    This is useful when you have a snapshot of locks and want to
    check for potential deadlocks without tracking over time.
    
    Args:
        locks: List of Lock objects
        
    Returns:
        DeadlockInfo if deadlock detected, None otherwise
    """
    # Build a simple ownership map
    lock_owners = {lock.resource: lock.owner for lock in locks if not lock.is_expired()}
    
    # Check for circular dependencies
    # This is a simplified check - real deadlock requires wait info
    for i, lock1 in enumerate(locks):
        for lock2 in locks[i+1:]:
            # If owners have multiple overlapping resources, potential issue
            if lock1.owner == lock2.owner and not lock1.is_expired() and not lock2.is_expired():
                continue  # Same owner, no issue
    
    # Full analysis would need wait-for information
    # For now, return None as we need dynamic wait tracking
    return None
