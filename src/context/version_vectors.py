"""
Version Vector System for TITAN FUSE Protocol.

ITEM-SAE-005: Version Vector System Implementation

This module implements a vector clock system for tracking context modifications
and detecting inconsistencies. It enables:
- Detection of stale context
- Cache invalidation
- Conflict detection for concurrent modifications
- Causal ordering of events

Key Components:
- VersionVector: Vector clock for a single node
- VectorClockManager: Manages version vectors across the context graph
- StaleDetector: Detects stale context nodes based on version vectors

Author: TITAN FUSE Team
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any, Set, Tuple
import logging
import threading
import json

from src.utils.timezone import now_utc, now_utc_iso
from src.context.context_graph import (
    ContextNode,
    ContextGraph,
    VersionVector as ContextVersionVector,
    TrustTier,
)


class VectorOrder(Enum):
    """Ordering relationship between two version vectors."""
    BEFORE = -1      # This vector is before (older than) the other
    CONCURRENT = 0   # Vectors are concurrent (no ordering)
    AFTER = 1        # This vector is after (newer than) the other


@dataclass
class Conflict:
    """
    Represents a detected conflict between concurrent modifications.
    
    Attributes:
        node_id: ID of the node with conflict
        vector1: First concurrent version vector
        vector2: Second concurrent version vector
        detected_at: Timestamp of conflict detection
        metadata: Additional conflict metadata
    """
    node_id: str
    vector1: Dict[str, int]
    vector2: Dict[str, int]
    detected_at: str = field(default_factory=now_utc_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "node_id": self.node_id,
            "vector1": self.vector1,
            "vector2": self.vector2,
            "detected_at": self.detected_at,
            "metadata": self.metadata,
        }


@dataclass
class Resolution:
    """
    Represents a resolution for a detected conflict.
    
    Attributes:
        conflict: The conflict being resolved
        strategy: Resolution strategy used
        resolved_vector: The winning/resolved version vector
        resolved_at: Timestamp of resolution
        metadata: Additional resolution metadata
    """
    conflict: Conflict
    strategy: str
    resolved_vector: Dict[str, int]
    resolved_at: str = field(default_factory=now_utc_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "conflict_id": f"{self.conflict.node_id}@{self.conflict.detected_at}",
            "strategy": self.strategy,
            "resolved_vector": self.resolved_vector,
            "resolved_at": self.resolved_at,
            "metadata": self.metadata,
        }


@dataclass
class StaleNode:
    """
    Represents a stale context node detected by StaleDetector.
    
    Attributes:
        node_id: ID of the stale node
        stale_reason: Reason why the node is considered stale
        last_modified: When the node was last modified
        current_vector: Current version vector of the node
        expected_vector: Expected version vector (if different)
        staleness_score: Score indicating how stale (0.0 to 1.0)
        suggested_action: Suggested action to resolve staleness
    """
    node_id: str
    stale_reason: str
    last_modified: Optional[datetime] = None
    current_vector: Optional[Dict[str, int]] = None
    expected_vector: Optional[Dict[str, int]] = None
    staleness_score: float = 0.0
    suggested_action: str = "refresh"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "node_id": self.node_id,
            "stale_reason": self.stale_reason,
            "last_modified": self.last_modified.isoformat() if self.last_modified else None,
            "current_vector": self.current_vector,
            "expected_vector": self.expected_vector,
            "staleness_score": self.staleness_score,
            "suggested_action": self.suggested_action,
        }


class VectorClockManager:
    """
    Manages version vectors across the context graph.
    
    The VectorClockManager provides:
    - Version vector retrieval and updates
    - Conflict detection between concurrent modifications
    - Conflict resolution strategies
    - Integration with ContextGraph for automatic tracking
    
    Thread-safe implementation for concurrent access.
    
    Usage:
        manager = VectorClockManager(context_graph)
        
        # Get current vector for a node
        vector = manager.get_current_vector("src/main.py")
        
        # Update vector on modification
        new_vector = manager.update_vector("src/main.py", "content_changed")
        
        # Detect conflicts
        conflicts = manager.detect_conflicts()
        
        # Resolve a conflict
        resolution = manager.resolve_conflict(conflicts[0], strategy="last_write_wins")
    """
    
    def __init__(self, context_graph: Optional[ContextGraph] = None):
        """
        Initialize the VectorClockManager.
        
        Args:
            context_graph: Optional ContextGraph to operate on
        """
        self._graph = context_graph
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)
        self._conflict_history: List[Conflict] = []
        self._resolution_history: List[Resolution] = []
        
        # Global version counter for generating unique event IDs
        self._global_counter: Dict[str, int] = {}
    
    def set_context_graph(self, graph: ContextGraph) -> None:
        """Set the context graph to operate on."""
        self._graph = graph
    
    # =========================================================================
    # Vector Operations
    # =========================================================================
    
    def get_current_vector(self, node_id: str) -> Optional[Dict[str, int]]:
        """
        Get the current version vector for a node.
        
        Args:
            node_id: Node identifier
            
        Returns:
            Version vector as dict, or None if node not found
        """
        if not self._graph:
            return None
        
        node = self._graph.get_node(node_id)
        if node and node.version_vector:
            return node.version_vector.to_dict()
        return None
    
    def update_vector(
        self,
        node_id: str,
        event: str,
        increment_local: bool = True
    ) -> Optional[Dict[str, int]]:
        """
        Update version vector for a node after an event.
        
        Args:
            node_id: Node identifier
            event: Type of event (e.g., "content_changed", "metadata_updated")
            increment_local: Whether to increment local counter
            
        Returns:
            Updated version vector, or None if node not found
        """
        with self._lock:
            if not self._graph:
                self._logger.warning("No context graph set")
                return None
            
            node = self._graph.get_node(node_id)
            if not node:
                return None
            
            # Initialize version vector if not present
            if node.version_vector is None:
                node.version_vector = ContextVersionVector()
            
            # Increment the node's own counter
            if increment_local:
                node.version_vector.increment(node_id)
            
            # Update global counter for this event type
            event_key = f"{node_id}:{event}"
            self._global_counter[event_key] = self._global_counter.get(event_key, 0) + 1
            
            # Update last modified timestamp
            node.last_modified = now_utc()
            
            self._logger.debug(
                f"Updated version vector for {node_id}: {node.version_vector.to_dict()}"
            )
            
            return node.version_vector.to_dict()
    
    def merge_vectors(
        self,
        v1: Dict[str, int],
        v2: Dict[str, int]
    ) -> Dict[str, int]:
        """
        Merge two version vectors (takes max of each counter).
        
        Args:
            v1: First version vector
            v2: Second version vector
            
        Returns:
            Merged version vector
        """
        result = v1.copy()
        for node_id, counter in v2.items():
            result[node_id] = max(result.get(node_id, 0), counter)
        return result
    
    def compare_vectors(
        self,
        v1: Dict[str, int],
        v2: Dict[str, int]
    ) -> VectorOrder:
        """
        Compare two version vectors.
        
        Args:
            v1: First version vector
            v2: Second version vector
            
        Returns:
            VectorOrder indicating the relationship
        """
        v1_dominates = False
        v2_dominates = False
        
        all_keys = set(v1.keys()) | set(v2.keys())
        
        for key in all_keys:
            v1_val = v1.get(key, 0)
            v2_val = v2.get(key, 0)
            
            if v1_val > v2_val:
                v1_dominates = True
            elif v2_val > v1_val:
                v2_dominates = True
        
        if v1_dominates and not v2_dominates:
            return VectorOrder.AFTER
        elif v2_dominates and not v1_dominates:
            return VectorOrder.BEFORE
        else:
            return VectorOrder.CONCURRENT
    
    def is_concurrent(
        self,
        v1: Dict[str, int],
        v2: Dict[str, int]
    ) -> bool:
        """Check if two vectors are concurrent (neither dominates)."""
        return self.compare_vectors(v1, v2) == VectorOrder.CONCURRENT
    
    def dominates(
        self,
        v1: Dict[str, int],
        v2: Dict[str, int]
    ) -> bool:
        """Check if v1 dominates v2."""
        return self.compare_vectors(v1, v2) == VectorOrder.AFTER
    
    # =========================================================================
    # Conflict Detection and Resolution
    # =========================================================================
    
    def detect_conflicts(self) -> List[Conflict]:
        """
        Detect all conflicts (concurrent modifications) in the graph.
        
        Returns:
            List of detected conflicts
        """
        if not self._graph:
            return []
        
        conflicts = []
        nodes = self._graph.get_all_nodes()
        
        # Check each pair of nodes for concurrent modifications
        for i, n1 in enumerate(nodes):
            if not n1.version_vector:
                continue
            
            v1 = n1.version_vector.to_dict()
            
            for n2 in nodes[i+1:]:
                if not n2.version_vector:
                    continue
                
                v2 = n2.version_vector.to_dict()
                
                if self.is_concurrent(v1, v2):
                    # Check if they share any common keys (indicating potential conflict)
                    common_keys = set(v1.keys()) & set(v2.keys())
                    if common_keys:
                        conflict = Conflict(
                            node_id=f"{n1.id}::{n2.id}",
                            vector1=v1,
                            vector2=v2,
                            metadata={"common_keys": list(common_keys)}
                        )
                        conflicts.append(conflict)
                        self._conflict_history.append(conflict)
        
        self._logger.info(f"Detected {len(conflicts)} conflicts")
        return conflicts
    
    def resolve_conflict(
        self,
        conflict: Conflict,
        strategy: str = "last_write_wins"
    ) -> Resolution:
        """
        Resolve a conflict using the specified strategy.
        
        Strategies:
        - "last_write_wins": Use the vector with higher local counter
        - "merge": Merge both vectors
        - "first_write_wins": Use the vector with lower counter
        - "manual": Mark for manual resolution
        
        Args:
            conflict: Conflict to resolve
            strategy: Resolution strategy
            
        Returns:
            Resolution object
        """
        v1 = conflict.vector1
        v2 = conflict.vector2
        
        if strategy == "last_write_wins":
            # Use the vector with the higher sum of counters
            sum1 = sum(v1.values())
            sum2 = sum(v2.values())
            resolved = v1 if sum1 >= sum2 else v2
            
        elif strategy == "merge":
            resolved = self.merge_vectors(v1, v2)
            
        elif strategy == "first_write_wins":
            sum1 = sum(v1.values())
            sum2 = sum(v2.values())
            resolved = v1 if sum1 <= sum2 else v2
            
        elif strategy == "manual":
            # Mark for manual resolution
            resolved = {}
            conflict.metadata["requires_manual_resolution"] = True
            
        else:
            raise ValueError(f"Unknown resolution strategy: {strategy}")
        
        resolution = Resolution(
            conflict=conflict,
            strategy=strategy,
            resolved_vector=resolved,
        )
        
        self._resolution_history.append(resolution)
        self._logger.info(f"Resolved conflict using strategy '{strategy}'")
        
        return resolution
    
    def get_conflict_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent conflict history."""
        return [c.to_dict() for c in self._conflict_history[-limit:]]
    
    def get_resolution_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent resolution history."""
        return [r.to_dict() for r in self._resolution_history[-limit:]]


class StaleDetector:
    """
    Detects stale context nodes based on version vectors and other factors.
    
    Stale nodes are identified based on:
    - Age (last modified time)
    - Version vector inconsistencies
    - Trust score degradation
    - Content hash mismatches
    
    Usage:
        detector = StaleDetector(context_graph)
        
        # Detect all stale nodes
        stale_nodes = detector.detect_stale_context()
        
        # Check if a specific node is stale
        is_stale = detector.check_vector_invalidation(node, current_vector)
        
        # Get freshness score for a node
        freshness = detector.get_freshness_score(node)
    """
    
    def __init__(
        self,
        context_graph: Optional[ContextGraph] = None,
        max_age_hours: float = 24.0,
        staleness_threshold: float = 0.5
    ):
        """
        Initialize the StaleDetector.
        
        Args:
            context_graph: Optional ContextGraph to operate on
            max_age_hours: Maximum age before considering stale
            staleness_threshold: Score threshold for staleness
        """
        self._graph = context_graph
        self._max_age_hours = max_age_hours
        self._staleness_threshold = staleness_threshold
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)
        
        # Cache of known-good version vectors
        self._known_vectors: Dict[str, Dict[str, int]] = {}
    
    def set_context_graph(self, graph: ContextGraph) -> None:
        """Set the context graph to operate on."""
        self._graph = graph
    
    def detect_stale_context(
        self,
        graph: Optional[ContextGraph] = None
    ) -> List[StaleNode]:
        """
        Detect all stale nodes in the context graph.
        
        Args:
            graph: Optional graph to use (defaults to stored graph)
            
        Returns:
            List of StaleNode objects
        """
        graph = graph or self._graph
        if not graph:
            return []
        
        stale_nodes = []
        threshold_time = now_utc() - timedelta(hours=self._max_age_hours)
        
        for node in graph.get_all_nodes():
            staleness_score = 0.0
            reasons = []
            
            # Check age
            if node.last_modified and node.last_modified < threshold_time:
                age_hours = (now_utc() - node.last_modified).total_seconds() / 3600
                age_factor = min(1.0, age_hours / (self._max_age_hours * 2))
                staleness_score += 0.3 * age_factor
                reasons.append(f"age:{age_hours:.1f}h")
            
            # Check trust score
            if node.trust_score < 0.5:
                staleness_score += 0.3 * (1.0 - node.trust_score)
                reasons.append(f"low_trust:{node.trust_score:.2f}")
            
            # Check version vector
            if node.version_vector:
                # Check if version vector indicates concurrent modifications
                vector_dict = node.version_vector.to_dict()
                for other_node in graph.get_all_nodes():
                    if other_node.id == node.id:
                        continue
                    if other_node.version_vector:
                        other_dict = other_node.version_vector.to_dict()
                        if self._are_vectors_concurrent(vector_dict, other_dict):
                            staleness_score += 0.2
                            reasons.append("concurrent_modification")
                            break
            
            # Check usage (unused nodes are more likely stale)
            if node.usage_count == 0:
                staleness_score += 0.1
                reasons.append("unused")
            
            # Check success rate
            if node.success_rate < 0.8:
                staleness_score += 0.1 * (1.0 - node.success_rate)
                reasons.append(f"low_success:{node.success_rate:.2f}")
            
            # Determine if stale
            if staleness_score >= self._staleness_threshold:
                suggested_action = self._determine_action(staleness_score, reasons)
                
                stale_node = StaleNode(
                    node_id=node.id,
                    stale_reason=", ".join(reasons) if reasons else "unknown",
                    last_modified=node.last_modified,
                    current_vector=node.version_vector.to_dict() if node.version_vector else None,
                    staleness_score=min(1.0, staleness_score),
                    suggested_action=suggested_action,
                )
                stale_nodes.append(stale_node)
        
        self._logger.info(f"Detected {len(stale_nodes)} stale nodes")
        return stale_nodes
    
    def check_vector_invalidation(
        self,
        node: ContextNode,
        current_vector: Dict[str, int]
    ) -> bool:
        """
        Check if a node's version vector indicates invalidation.
        
        Args:
            node: Context node to check
            current_vector: Current version vector from the system
            
        Returns:
            True if the node should be invalidated
        """
        if not node.version_vector:
            return False
        
        node_vector = node.version_vector.to_dict()
        
        # Check if current vector dominates node's vector
        # If so, the node is outdated
        if self._vector_dominates(current_vector, node_vector):
            return True
        
        # Check for concurrent modifications (potential conflict)
        if self._are_vectors_concurrent(current_vector, node_vector):
            # Node might need refresh due to concurrent changes
            return True
        
        return False
    
    def get_freshness_score(self, node: ContextNode) -> float:
        """
        Calculate freshness score for a node (0.0 to 1.0).
        
        Higher scores indicate fresher (more up-to-date) nodes.
        
        Args:
            node: Context node to evaluate
            
        Returns:
            Freshness score from 0.0 (very stale) to 1.0 (very fresh)
        """
        score = 1.0
        
        # Age factor
        if node.last_modified:
            age = now_utc() - node.last_modified
            age_hours = age.total_seconds() / 3600
            # Exponential decay: full freshness at 0h, ~37% at max_age, ~14% at 2*max_age
            age_factor = 0.5 + 0.5 * (1.0 / (1.0 + age_hours / self._max_age_hours))
            score *= age_factor
        
        # Trust factor
        score *= (0.5 + 0.5 * node.trust_score)
        
        # Usage factor (used nodes are "fresher" in context)
        if node.usage_count > 0:
            usage_factor = min(1.0, 0.8 + 0.2 * (node.usage_count / 10))
            score *= usage_factor
        
        # Success rate factor
        score *= (0.7 + 0.3 * node.success_rate)
        
        return max(0.0, min(1.0, score))
    
    def register_known_vector(
        self,
        node_id: str,
        vector: Dict[str, int]
    ) -> None:
        """
        Register a known-good version vector for comparison.
        
        Args:
            node_id: Node identifier
            vector: Known-good version vector
        """
        with self._lock:
            self._known_vectors[node_id] = vector
    
    def get_staleness_report(self) -> Dict[str, Any]:
        """
        Generate a staleness report for the context graph.
        
        Returns:
            Dict with staleness statistics and details
        """
        if not self._graph:
            return {"error": "No context graph set"}
        
        stale_nodes = self.detect_stale_context()
        all_nodes = self._graph.get_all_nodes()
        
        # Calculate statistics
        freshness_scores = [
            self.get_freshness_score(n) for n in all_nodes
        ]
        avg_freshness = (
            sum(freshness_scores) / len(freshness_scores)
            if freshness_scores else 0.0
        )
        
        return {
            "total_nodes": len(all_nodes),
            "stale_nodes_count": len(stale_nodes),
            "fresh_nodes_count": len(all_nodes) - len(stale_nodes),
            "average_freshness": round(avg_freshness, 3),
            "staleness_threshold": self._staleness_threshold,
            "max_age_hours": self._max_age_hours,
            "stale_nodes": [s.to_dict() for s in stale_nodes[:20]],  # Limit output
            "generated_at": now_utc_iso(),
        }
    
    def _are_vectors_concurrent(
        self,
        v1: Dict[str, int],
        v2: Dict[str, int]
    ) -> bool:
        """Check if two vectors are concurrent."""
        v1_dominates = False
        v2_dominates = False
        
        all_keys = set(v1.keys()) | set(v2.keys())
        
        for key in all_keys:
            v1_val = v1.get(key, 0)
            v2_val = v2.get(key, 0)
            
            if v1_val > v2_val:
                v1_dominates = True
            elif v2_val > v1_val:
                v2_dominates = True
        
        return v1_dominates and v2_dominates
    
    def _vector_dominates(
        self,
        v1: Dict[str, int],
        v2: Dict[str, int]
    ) -> bool:
        """Check if v1 dominates v2."""
        dominates = False
        all_keys = set(v1.keys()) | set(v2.keys())
        
        for key in all_keys:
            v1_val = v1.get(key, 0)
            v2_val = v2.get(key, 0)
            
            if v1_val < v2_val:
                return False
            if v1_val > v2_val:
                dominates = True
        
        return dominates
    
    def _determine_action(
        self,
        staleness_score: float,
        reasons: List[str]
    ) -> str:
        """Determine suggested action based on staleness."""
        if staleness_score >= 0.8:
            return "regenerate"
        elif staleness_score >= 0.6:
            return "refresh"
        elif "concurrent_modification" in str(reasons):
            return "resolve_conflict"
        elif "low_trust" in str(reasons):
            return "validate"
        else:
            return "refresh"


# =============================================================================
# Module-level convenience functions
# =============================================================================

_default_manager: Optional[VectorClockManager] = None
_default_detector: Optional[StaleDetector] = None


def get_vector_clock_manager(
    context_graph: Optional[ContextGraph] = None
) -> VectorClockManager:
    """
    Get or create the default VectorClockManager instance.
    
    Args:
        context_graph: Optional context graph
        
    Returns:
        VectorClockManager instance
    """
    global _default_manager
    
    if _default_manager is None:
        _default_manager = VectorClockManager(context_graph=context_graph)
    elif context_graph is not None:
        _default_manager.set_context_graph(context_graph)
    
    return _default_manager


def get_stale_detector(
    context_graph: Optional[ContextGraph] = None,
    max_age_hours: float = 24.0
) -> StaleDetector:
    """
    Get or create the default StaleDetector instance.
    
    Args:
        context_graph: Optional context graph
        max_age_hours: Maximum age before staleness
        
    Returns:
        StaleDetector instance
    """
    global _default_detector
    
    if _default_detector is None:
        _default_detector = StaleDetector(
            context_graph=context_graph,
            max_age_hours=max_age_hours
        )
    elif context_graph is not None:
        _default_detector.set_context_graph(context_graph)
    
    return _default_detector


def reset_version_vector_system() -> None:
    """Reset the default manager and detector instances."""
    global _default_manager, _default_detector
    _default_manager = None
    _default_detector = None
