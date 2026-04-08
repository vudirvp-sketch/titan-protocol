"""
Trust Score Engine for TITAN FUSE Protocol.

ITEM-SAE-004: Trust Score Engine Implementation

This module implements the TrustEngine for calculating and maintaining trust scores
for context nodes based on multiple factors.

Trust scoring enables intelligent context routing decisions:
- Higher trust nodes are preferred for context selection
- Low trust nodes trigger warnings or exclusion
- Trust decays over time without use
- Trust boosts on successful operations

Key Features:
- Multi-factor trust calculation
- Trust tier classification (TIER_1..4)
- Time-based decay
- Success/failure tracking
- Related node boosting

Author: TITAN FUSE Team
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any, Set
import logging
import threading
import math

from src.utils.timezone import now_utc, now_utc_iso
from src.context.context_graph import (
    ContextNode,
    ContextGraph,
    TrustTier,
    NodeType,
)


class TrustFactor(Enum):
    """Factors contributing to trust score."""
    AGE = "age"
    USAGE_COUNT = "usage_count"
    SUCCESS_RATE = "success_rate"
    SOURCE_QUALITY = "source_quality"
    VALIDATION_PASS = "validation_pass"


@dataclass
class TrustFactorWeights:
    """Weights for trust factor calculation."""
    age: float = 0.20
    usage_count: float = 0.25
    success_rate: float = 0.30
    source_quality: float = 0.15
    validation_pass: float = 0.10
    
    def __post_init__(self):
        """Validate weights sum to 1.0."""
        total = self.age + self.usage_count + self.success_rate + self.source_quality + self.validation_pass
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total}")


@dataclass
class TrustEngineConfig:
    """Configuration for TrustEngine."""
    # Minimum trust threshold for "trusted" status
    min_trust_threshold: float = 0.5
    
    # Trust decay rate per hour (applied to inactive nodes)
    decay_rate: float = 0.01  # 1% per hour
    
    # Trust boost on successful operation
    boost_on_hit: float = 0.05
    
    # Trust penalty on failed operation
    penalty_on_miss: float = 0.10
    
    # Maximum age in hours before significant decay
    max_age_hours: float = 24.0
    
    # Hours after which to apply decay
    decay_after_hours: float = 1.0
    
    # Weights for trust factors
    factor_weights: TrustFactorWeights = field(default_factory=TrustFactorWeights)
    
    # Source quality multipliers by node type
    source_quality_by_type: Dict[str, float] = field(default_factory=lambda: {
        "file": 0.8,
        "symbol": 0.7,
        "module": 0.9,
        "config": 1.0,
        "checkpoint": 0.6,
        "artifact": 0.5,
    })


@dataclass
class TrustScoreRecord:
    """Record of a trust score change."""
    node_id: str
    old_score: float
    new_score: float
    reason: str
    timestamp: str = field(default_factory=now_utc_iso)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "old_score": self.old_score,
            "new_score": self.new_score,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


@dataclass
class TrustEngineStats:
    """Statistics for TrustEngine operations."""
    total_updates: int = 0
    total_boosts: int = 0
    total_penalties: int = 0
    total_decays: int = 0
    avg_trust_score: float = 0.0
    low_trust_count: int = 0


class TrustEngine:
    """
    Trust Score Engine for TITAN FUSE Protocol.
    
    Calculates and maintains trust scores for context nodes based on:
    - Age: How recently the node was created/modified
    - Usage count: How frequently the node is accessed
    - Success rate: Historical success of operations involving the node
    - Source quality: Base quality of the source (by node type)
    - Validation pass: Whether validation passed for this node
    
    Trust tiers:
    - TIER_1_TRUSTED (>=0.8): High confidence, always use
    - TIER_2_RELIABLE (0.6-0.8): Good confidence, prefer use
    - TIER_3_UNCERTAIN (0.4-0.6): Low confidence, verify before use
    - TIER_4_UNTRUSTED (<0.4): Very low confidence, avoid
    
    Usage:
        engine = TrustEngine()
        
        # Calculate initial trust for a node
        trust = engine.calculate_initial_score(node)
        
        # Update trust on success
        engine.update_on_hit(node_id)
        
        # Update trust on failure
        engine.update_on_miss(node_id)
        
        # Apply time decay
        engine.apply_time_decay(node_id, hours_elapsed)
        
        # Get nodes below threshold
        low_trust = engine.get_low_trust_nodes(threshold=0.5)
    """
    
    def __init__(
        self,
        config: Optional[TrustEngineConfig] = None,
        context_graph: Optional[ContextGraph] = None,
    ):
        """
        Initialize the TrustEngine.
        
        Args:
            config: Configuration options
            context_graph: Optional ContextGraph to operate on
        """
        self._config = config or TrustEngineConfig()
        self._graph = context_graph
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)
        self._stats = TrustEngineStats()
        self._score_history: List[TrustScoreRecord] = []
    
    @property
    def config(self) -> TrustEngineConfig:
        """Get the configuration."""
        return self._config
    
    @property
    def stats(self) -> TrustEngineStats:
        """Get the statistics."""
        return self._stats
    
    def set_context_graph(self, graph: ContextGraph) -> None:
        """Set the context graph to operate on."""
        self._graph = graph
    
    # =========================================================================
    # Trust Score Calculation
    # =========================================================================
    
    def calculate_initial_score(self, node: ContextNode) -> float:
        """
        Calculate initial trust score for a node.
        
        Args:
            node: ContextNode to calculate score for
            
        Returns:
            Initial trust score (0.0 to 1.0)
        """
        weights = self._config.factor_weights
        
        # Age factor (newer = higher)
        age_score = self._calculate_age_factor(node)
        
        # Usage factor (more usage = higher)
        usage_score = self._calculate_usage_factor(node)
        
        # Success rate (already normalized)
        success_score = node.success_rate
        
        # Source quality (by node type)
        source_score = self._calculate_source_quality(node)
        
        # Validation (starts at 0.5, increases with validation)
        validation_score = 0.5
        if node.metadata.get("validated", False):
            validation_score = 1.0
        
        # Weighted average
        trust = (
            weights.age * age_score +
            weights.usage_count * usage_score +
            weights.success_rate * success_score +
            weights.source_quality * source_score +
            weights.validation_pass * validation_score
        )
        
        return max(0.0, min(1.0, trust))
    
    def _calculate_age_factor(self, node: ContextNode) -> float:
        """Calculate age-based trust factor."""
        if not node.last_modified:
            return 0.5  # Neutral if no timestamp
        
        age = now_utc() - node.last_modified
        age_hours = age.total_seconds() / 3600
        
        # Exponential decay based on age
        # Fresh (<1h) = 1.0, Old (>24h) approaches 0.3
        decay_factor = math.exp(-age_hours / self._config.max_age_hours)
        return 0.3 + 0.7 * decay_factor
    
    def _calculate_usage_factor(self, node: ContextNode) -> float:
        """Calculate usage-based trust factor."""
        # Logarithmic scaling: log(usage + 1) / log(100) caps at ~1.0
        usage = node.usage_count
        return min(1.0, math.log(usage + 1) / math.log(100))
    
    def _calculate_source_quality(self, node: ContextNode) -> float:
        """Calculate source quality factor based on node type."""
        type_key = node.type.value if isinstance(node.type, NodeType) else str(node.type)
        return self._config.source_quality_by_type.get(type_key, 0.5)
    
    def get_trust_tier(self, score: float) -> TrustTier:
        """
        Get the trust tier for a score.
        
        Args:
            score: Trust score (0.0 to 1.0)
            
        Returns:
            TrustTier classification
        """
        return TrustTier.from_score(score)
    
    # =========================================================================
    # Trust Score Updates
    # =========================================================================
    
    def update_on_hit(self, node_id: str) -> float:
        """
        Update trust score after successful operation.
        
        Args:
            node_id: Node identifier
            
        Returns:
            New trust score, or 0.0 if node not found
        """
        with self._lock:
            if not self._graph:
                self._logger.warning("No context graph set")
                return 0.0
            
            node = self._graph.get_node(node_id)
            if not node:
                return 0.0
            
            old_score = node.trust_score
            node.update_trust(self._config.boost_on_hit)
            node.record_access(success=True)
            
            self._record_change(node_id, old_score, node.trust_score, "hit")
            self._stats.total_updates += 1
            self._stats.total_boosts += 1
            
            self._logger.debug(
                f"Trust boost for {node_id}: {old_score:.3f} -> {node.trust_score:.3f}"
            )
            
            return node.trust_score
    
    def update_on_miss(self, node_id: str) -> float:
        """
        Update trust score after failed operation.
        
        Args:
            node_id: Node identifier
            
        Returns:
            New trust score, or 0.0 if node not found
        """
        with self._lock:
            if not self._graph:
                self._logger.warning("No context graph set")
                return 0.0
            
            node = self._graph.get_node(node_id)
            if not node:
                return 0.0
            
            old_score = node.trust_score
            node.update_trust(-self._config.penalty_on_miss)
            node.record_access(success=False)
            
            self._record_change(node_id, old_score, node.trust_score, "miss")
            self._stats.total_updates += 1
            self._stats.total_penalties += 1
            
            self._logger.debug(
                f"Trust penalty for {node_id}: {old_score:.3f} -> {node.trust_score:.3f}"
            )
            
            return node.trust_score
    
    def apply_time_decay(self, node_id: str, hours: float) -> float:
        """
        Apply time-based trust decay.
        
        Args:
            node_id: Node identifier
            hours: Hours since last access
            
        Returns:
            New trust score, or 0.0 if node not found
        """
        with self._lock:
            if not self._graph:
                return 0.0
            
            node = self._graph.get_node(node_id)
            if not node:
                return 0.0
            
            # Only decay if past threshold
            if hours < self._config.decay_after_hours:
                return node.trust_score
            
            old_score = node.trust_score
            
            # Calculate decay: exponential decay per hour
            decay_hours = hours - self._config.decay_after_hours
            decay_amount = self._config.decay_rate * decay_hours
            decay_amount = min(decay_amount, 0.3)  # Cap at 30% decay per call
            
            node.update_trust(-decay_amount)
            
            self._record_change(node_id, old_score, node.trust_score, f"decay:{hours:.1f}h")
            self._stats.total_updates += 1
            self._stats.total_decays += 1
            
            return node.trust_score
    
    def boost_related_nodes(self, node_id: str, boost: float = 0.03) -> None:
        """
        Boost trust score of related nodes.
        
        Args:
            node_id: Node identifier
            boost: Amount to boost (default: smaller than primary boost)
        """
        if not self._graph:
            return
        
        neighbors = self._graph.get_neighbors(node_id)
        for neighbor_id in neighbors:
            self._graph.update_trust_score(neighbor_id, boost)
    
    # =========================================================================
    # Query Operations
    # =========================================================================
    
    def get_low_trust_nodes(
        self,
        threshold: Optional[float] = None
    ) -> List[ContextNode]:
        """
        Get all nodes below trust threshold.
        
        Args:
            threshold: Trust threshold (defaults to config value)
            
        Returns:
            List of nodes below threshold
        """
        if not self._graph:
            return []
        
        threshold = threshold or self._config.min_trust_threshold
        return self._graph.get_low_trust_nodes(threshold)
    
    def get_nodes_by_tier(self, tier: TrustTier) -> List[ContextNode]:
        """
        Get all nodes in a specific trust tier.
        
        Args:
            tier: Trust tier to filter by
            
        Returns:
            List of nodes in the tier
        """
        if not self._graph:
            return []
        
        return self._graph.get_nodes_by_tier(tier)
    
    def get_trust_score(self, node_id: str) -> float:
        """
        Get trust score for a node.
        
        Args:
            node_id: Node identifier
            
        Returns:
            Trust score, or 0.0 if not found
        """
        if not self._graph:
            return 0.0
        
        return self._graph.get_trust_score(node_id)
    
    def should_use_node(
        self,
        node_id: str,
        min_tier: TrustTier = TrustTier.TIER_3_UNCERTAIN
    ) -> bool:
        """
        Check if a node should be used based on trust tier.
        
        Args:
            node_id: Node identifier
            min_tier: Minimum acceptable tier
            
        Returns:
            True if node's tier >= min_tier
        """
        if not self._graph:
            return False
        
        node = self._graph.get_node(node_id)
        if not node:
            return False
        
        tier_order = [
            TrustTier.TIER_4_UNTRUSTED,
            TrustTier.TIER_3_UNCERTAIN,
            TrustTier.TIER_2_RELIABLE,
            TrustTier.TIER_1_TRUSTED,
        ]
        
        return tier_order.index(node.trust_tier) >= tier_order.index(min_tier)
    
    # =========================================================================
    # Bulk Operations
    # =========================================================================
    
    def recalculate_all_scores(self) -> Dict[str, float]:
        """
        Recalculate trust scores for all nodes.
        
        Returns:
            Dict of node_id -> new_trust_score
        """
        if not self._graph:
            return {}
        
        results = {}
        for node in self._graph.get_all_nodes():
            new_score = self.calculate_initial_score(node)
            old_score = node.trust_score
            node.trust_score = new_score
            results[node.id] = new_score
            
            self._record_change(node.id, old_score, new_score, "recalculate")
        
        return results
    
    def apply_decay_to_all(self) -> int:
        """
        Apply time decay to all nodes.
        
        Returns:
            Number of nodes updated
        """
        if not self._graph:
            return 0
        
        count = 0
        now = now_utc()
        
        for node in self._graph.get_all_nodes():
            if node.last_accessed:
                hours = (now - node.last_accessed).total_seconds() / 3600
            else:
                hours = 24.0  # Default to max decay if never accessed
            
            self.apply_time_decay(node.id, hours)
            count += 1
        
        return count
    
    # =========================================================================
    # Internal Methods
    # =========================================================================
    
    def _record_change(
        self,
        node_id: str,
        old_score: float,
        new_score: float,
        reason: str
    ) -> None:
        """Record a trust score change."""
        record = TrustScoreRecord(
            node_id=node_id,
            old_score=old_score,
            new_score=new_score,
            reason=reason,
        )
        self._score_history.append(record)
        
        # Keep only last 1000 records
        if len(self._score_history) > 1000:
            self._score_history = self._score_history[-1000:]
    
    def get_score_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get recent trust score change history.
        
        Args:
            limit: Maximum number of records to return
            
        Returns:
            List of trust score change records
        """
        return [r.to_dict() for r in self._score_history[-limit:]]
    
    def get_stats_summary(self) -> Dict[str, Any]:
        """Get a summary of trust engine statistics."""
        low_trust = self.get_low_trust_nodes() if self._graph else []
        
        return {
            "total_updates": self._stats.total_updates,
            "total_boosts": self._stats.total_boosts,
            "total_penalties": self._stats.total_penalties,
            "total_decays": self._stats.total_decays,
            "low_trust_nodes": len(low_trust),
            "history_size": len(self._score_history),
            "config": {
                "min_trust_threshold": self._config.min_trust_threshold,
                "decay_rate": self._config.decay_rate,
                "boost_on_hit": self._config.boost_on_hit,
                "penalty_on_miss": self._config.penalty_on_miss,
            }
        }


# =============================================================================
# Module-level convenience functions
# =============================================================================

_default_engine: Optional[TrustEngine] = None


def get_trust_engine(
    config: Optional[TrustEngineConfig] = None,
    context_graph: Optional[ContextGraph] = None,
) -> TrustEngine:
    """
    Get or create the default TrustEngine instance.
    
    Args:
        config: Optional configuration
        context_graph: Optional context graph
        
    Returns:
        TrustEngine instance
    """
    global _default_engine
    
    if _default_engine is None:
        _default_engine = TrustEngine(config=config, context_graph=context_graph)
    elif context_graph is not None:
        _default_engine.set_context_graph(context_graph)
    
    return _default_engine


def reset_trust_engine() -> None:
    """Reset the default TrustEngine instance."""
    global _default_engine
    _default_engine = None
