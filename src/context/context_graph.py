"""
Context Graph Module for TITAN FUSE Protocol.

ITEM-SAE-003: Context Graph Schema Definition

This module implements the Context Graph - a structure for managing context nodes
with trust scores, version vectors, and relationships for intelligent context routing.

Key Features:
- Trust scoring with tier classification
- Version vectors for causal ordering and stale detection
- Node relationships (imports, calls, depends_on, etc.)
- JSON serialization compatible with context_graph.schema.json

Author: TITAN FUSE Team
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Set, Tuple
import json
import hashlib
import threading
import logging

from src.utils.timezone import now_utc, now_utc_iso


class NodeType(Enum):
    """Type of context node."""
    FILE = "file"
    SYMBOL = "symbol"
    MODULE = "module"
    CONFIG = "config"
    CHECKPOINT = "checkpoint"
    ARTIFACT = "artifact"


class EdgeRelation(Enum):
    """Type of relationship between nodes."""
    IMPORTS = "imports"
    CALLS = "calls"
    DEPENDS_ON = "depends_on"
    EXTENDS = "extends"
    IMPLEMENTS = "implements"
    REFERENCES = "references"
    CONTAINS = "contains"
    PRODUCES = "produces"


class TrustTier(Enum):
    """
    Trust tier classification for context nodes.
    
    TIER_1_TRUSTED:    High confidence, always use (trust >= 0.8)
    TIER_2_RELIABLE:   Good confidence, prefer use (0.6 <= trust < 0.8)
    TIER_3_UNCERTAIN:  Low confidence, verify before use (0.4 <= trust < 0.6)
    TIER_4_UNTRUSTED:  Very low confidence, avoid (trust < 0.4)
    """
    TIER_1_TRUSTED = "TIER_1_TRUSTED"
    TIER_2_RELIABLE = "TIER_2_RELIABLE"
    TIER_3_UNCERTAIN = "TIER_3_UNCERTAIN"
    TIER_4_UNTRUSTED = "TIER_4_UNTRUSTED"
    
    @classmethod
    def from_score(cls, score: float) -> "TrustTier":
        """Determine trust tier from score."""
        if score >= 0.8:
            return cls.TIER_1_TRUSTED
        elif score >= 0.6:
            return cls.TIER_2_RELIABLE
        elif score >= 0.4:
            return cls.TIER_3_UNCERTAIN
        else:
            return cls.TIER_4_UNTRUSTED


@dataclass
class VersionVector:
    """
    Version vector for causal ordering and conflict detection.
    
    A version vector maps node IDs to counters, allowing detection of:
    - Concurrent modifications
    - Causal dependencies
    - Stale context
    """
    vector: Dict[str, int] = field(default_factory=dict)
    
    def increment(self, node_id: str) -> "VersionVector":
        """Increment counter for a node and return self."""
        self.vector[node_id] = self.vector.get(node_id, 0) + 1
        return self
    
    def merge(self, other: "VersionVector") -> "VersionVector":
        """
        Merge with another version vector (takes max of each counter).
        
        Returns a new VersionVector with merged values.
        """
        result = VersionVector(vector=self.vector.copy())
        for node_id, counter in other.vector.items():
            result.vector[node_id] = max(result.vector.get(node_id, 0), counter)
        return result
    
    def compare(self, other: "VersionVector") -> int:
        """
        Compare two version vectors.
        
        Returns:
            -1 if self < other (self is older)
             0 if concurrent (no ordering)
             1 if self > other (self is newer)
        """
        self_dominates = False
        other_dominates = False
        
        all_keys = set(self.vector.keys()) | set(other.vector.keys())
        
        for key in all_keys:
            self_val = self.vector.get(key, 0)
            other_val = other.vector.get(key, 0)
            
            if self_val > other_val:
                self_dominates = True
            elif other_val > self_val:
                other_dominates = True
        
        if self_dominates and not other_dominates:
            return 1
        elif other_dominates and not self_dominates:
            return -1
        else:
            return 0
    
    def is_concurrent(self, other: "VersionVector") -> bool:
        """Check if two vectors are concurrent (neither dominates)."""
        return self.compare(other) == 0
    
    def dominates(self, other: "VersionVector") -> bool:
        """Check if this vector dominates the other."""
        return self.compare(other) == 1
    
    def to_dict(self) -> Dict[str, int]:
        """Convert to dictionary for JSON serialization."""
        return self.vector.copy()
    
    @classmethod
    def from_dict(cls, data: Dict[str, int]) -> "VersionVector":
        """Create from dictionary."""
        return cls(vector=data.copy())


@dataclass
class ContextNode:
    """
    A node in the context graph representing a file, symbol, module, or config.
    
    Attributes:
        id: Unique identifier (typically file path or symbol name)
        type: Node type (file, symbol, module, config, etc.)
        location: File path or location reference
        trust_score: Trust score from 0.0 to 1.0
        content_hash: SHA-256 hash of content
        semantic_hash: AST-based hash for semantic changes
        version_vector: Version vector for change tracking
        usage_count: Number of accesses
        success_rate: Success rate of operations (0.0 to 1.0)
        metadata: Additional metadata dict
    """
    id: str
    type: NodeType
    location: str
    trust_score: float = 0.5
    content_hash: Optional[str] = None
    semantic_hash: Optional[str] = None
    version_vector: Optional[VersionVector] = None
    last_modified: Optional[datetime] = None
    last_accessed: Optional[datetime] = None
    usage_count: int = 0
    success_rate: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate trust score and initialize version vector."""
        self.trust_score = max(0.0, min(1.0, self.trust_score))
        if self.version_vector is None:
            self.version_vector = VersionVector()
    
    @property
    def trust_tier(self) -> TrustTier:
        """Get the trust tier for this node."""
        return TrustTier.from_score(self.trust_score)
    
    def update_trust(self, delta: float) -> None:
        """Update trust score by delta, clamping to [0.0, 1.0]."""
        self.trust_score = max(0.0, min(1.0, self.trust_score + delta))
    
    def record_access(self, success: bool = True) -> None:
        """Record an access to this node."""
        self.last_accessed = now_utc()
        self.usage_count += 1
        
        # Update success rate with exponential moving average
        alpha = 0.1  # Learning rate
        if success:
            self.success_rate = alpha * 1.0 + (1 - alpha) * self.success_rate
        else:
            self.success_rate = alpha * 0.0 + (1 - alpha) * self.success_rate
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "id": self.id,
            "type": self.type.value,
            "location": self.location,
            "trust_score": self.trust_score,
            "trust_tier": self.trust_tier.value,
            "usage_count": self.usage_count,
            "success_rate": self.success_rate,
        }
        
        if self.content_hash:
            result["content_hash"] = self.content_hash
        if self.semantic_hash:
            result["semantic_hash"] = self.semantic_hash
        if self.version_vector:
            result["version_vector"] = self.version_vector.to_dict()
        if self.last_modified:
            result["last_modified"] = self.last_modified.isoformat()
        if self.last_accessed:
            result["last_accessed"] = self.last_accessed.isoformat()
        if self.metadata:
            result["metadata"] = self.metadata
            
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextNode":
        """Create from dictionary."""
        version_vector = None
        if "version_vector" in data:
            version_vector = VersionVector.from_dict(data["version_vector"])
        
        last_modified = None
        if "last_modified" in data:
            last_modified = datetime.fromisoformat(data["last_modified"])
        
        last_accessed = None
        if "last_accessed" in data:
            last_accessed = datetime.fromisoformat(data["last_accessed"])
        
        return cls(
            id=data["id"],
            type=NodeType(data["type"]),
            location=data["location"],
            trust_score=data.get("trust_score", 0.5),
            content_hash=data.get("content_hash"),
            semantic_hash=data.get("semantic_hash"),
            version_vector=version_vector,
            last_modified=last_modified,
            last_accessed=last_accessed,
            usage_count=data.get("usage_count", 0),
            success_rate=data.get("success_rate", 1.0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ContextEdge:
    """
    An edge in the context graph representing a relationship between nodes.
    
    Attributes:
        from_id: Source node ID
        to_id: Target node ID
        relation: Type of relationship
        weight: Edge weight for routing (0.0 to 1.0)
        metadata: Additional metadata
    """
    from_id: str
    to_id: str
    relation: EdgeRelation
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "from": self.from_id,
            "to": self.to_id,
            "relation": self.relation.value,
            "weight": self.weight,
        }
        if self.metadata:
            result["metadata"] = self.metadata
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextEdge":
        """Create from dictionary."""
        return cls(
            from_id=data["from"],
            to_id=data["to"],
            relation=EdgeRelation(data["relation"]),
            weight=data.get("weight", 1.0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ContextGraphMetadata:
    """Metadata for the context graph."""
    generated_at: datetime
    total_nodes: int
    total_edges: int
    avg_trust_score: float = 0.0
    stale_nodes: List[str] = field(default_factory=list)
    trust_distribution: Dict[str, int] = field(default_factory=dict)
    protocol_version: str = "5.0.0"
    session_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "generated_at": self.generated_at.isoformat(),
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "avg_trust_score": self.avg_trust_score,
            "stale_nodes": self.stale_nodes,
            "trust_distribution": self.trust_distribution,
            "protocol_version": self.protocol_version,
            "session_id": self.session_id,
        }


class ContextGraph:
    """
    Context Graph for TITAN FUSE Protocol.
    
    Manages context nodes with trust scores, version vectors, and relationships
    for intelligent context routing and stale detection.
    
    Thread-safe implementation for concurrent access.
    
    Usage:
        graph = ContextGraph()
        
        # Add nodes
        node = ContextNode(id="src/main.py", type=NodeType.FILE, location="src/main.py")
        graph.add_node(node)
        
        # Add edges
        edge = ContextEdge("src/main.py", "src/utils.py", EdgeRelation.IMPORTS)
        graph.add_edge(edge)
        
        # Query trust scores
        trust = graph.get_trust_score("src/main.py")
        low_trust = graph.get_low_trust_nodes(threshold=0.5)
        
        # Detect stale
        stale = graph.detect_stale_nodes()
        
        # Serialize
        json_data = graph.to_json()
    """
    
    def __init__(self, session_id: Optional[str] = None):
        """
        Initialize the context graph.
        
        Args:
            session_id: Optional session ID for this graph
        """
        self._nodes: Dict[str, ContextNode] = {}
        self._edges: List[ContextEdge] = []
        self._outgoing: Dict[str, List[str]] = {}  # node_id -> edge indices
        self._incoming: Dict[str, List[str]] = {}  # node_id -> edge indices
        self._session_id = session_id
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)
    
    @property
    def session_id(self) -> Optional[str]:
        """Get the session ID."""
        return self._session_id
    
    @session_id.setter
    def session_id(self, value: str) -> None:
        """Set the session ID."""
        self._session_id = value
    
    # =========================================================================
    # Node Operations
    # =========================================================================
    
    def add_node(self, node: ContextNode) -> None:
        """
        Add a node to the graph.
        
        Args:
            node: ContextNode to add
        """
        with self._lock:
            self._nodes[node.id] = node
            self._logger.debug(f"Added node: {node.id} (trust={node.trust_score:.2f})")
    
    def get_node(self, node_id: str) -> Optional[ContextNode]:
        """
        Get a node by ID.
        
        Args:
            node_id: Node identifier
            
        Returns:
            ContextNode if found, None otherwise
        """
        return self._nodes.get(node_id)
    
    def remove_node(self, node_id: str) -> bool:
        """
        Remove a node and all its edges.
        
        Args:
            node_id: Node identifier
            
        Returns:
            True if node was removed
        """
        with self._lock:
            if node_id not in self._nodes:
                return False
            
            # Remove edges
            self._edges = [
                e for e in self._edges
                if e.from_id != node_id and e.to_id != node_id
            ]
            
            # Remove from indices
            self._outgoing.pop(node_id, None)
            self._incoming.pop(node_id, None)
            
            # Remove node
            del self._nodes[node_id]
            return True
    
    def has_node(self, node_id: str) -> bool:
        """Check if a node exists."""
        return node_id in self._nodes
    
    def get_all_nodes(self) -> List[ContextNode]:
        """Get all nodes in the graph."""
        return list(self._nodes.values())
    
    # =========================================================================
    # Edge Operations
    # =========================================================================
    
    def add_edge(self, edge: ContextEdge) -> None:
        """
        Add an edge to the graph.
        
        Args:
            edge: ContextEdge to add
        """
        with self._lock:
            self._edges.append(edge)
            
            # Update indices
            if edge.from_id not in self._outgoing:
                self._outgoing[edge.from_id] = []
            self._outgoing[edge.from_id].append(edge.to_id)
            
            if edge.to_id not in self._incoming:
                self._incoming[edge.to_id] = []
            self._incoming[edge.to_id].append(edge.from_id)
            
            self._logger.debug(
                f"Added edge: {edge.from_id} --[{edge.relation.value}]--> {edge.to_id}"
            )
    
    def get_edges_from(self, node_id: str) -> List[ContextEdge]:
        """Get all outgoing edges from a node."""
        return [e for e in self._edges if e.from_id == node_id]
    
    def get_edges_to(self, node_id: str) -> List[ContextEdge]:
        """Get all incoming edges to a node."""
        return [e for e in self._edges if e.to_id == node_id]
    
    def get_neighbors(self, node_id: str) -> List[str]:
        """Get all neighboring node IDs (both incoming and outgoing)."""
        outgoing = self._outgoing.get(node_id, [])
        incoming = self._incoming.get(node_id, [])
        return list(set(outgoing + incoming))
    
    # =========================================================================
    # Trust Score Operations
    # =========================================================================
    
    def get_trust_score(self, node_id: str) -> float:
        """
        Get the trust score for a node.
        
        Args:
            node_id: Node identifier
            
        Returns:
            Trust score (0.0 to 1.0), or 0.0 if node not found
        """
        node = self.get_node(node_id)
        return node.trust_score if node else 0.0
    
    def update_trust_score(self, node_id: str, delta: float) -> bool:
        """
        Update trust score for a node.
        
        Args:
            node_id: Node identifier
            delta: Change to apply to trust score
            
        Returns:
            True if node was found and updated
        """
        node = self.get_node(node_id)
        if node:
            node.update_trust(delta)
            self._logger.debug(
                f"Updated trust for {node_id}: {node.trust_score:.2f} (delta={delta:+.2f})"
            )
            return True
        return False
    
    def get_low_trust_nodes(self, threshold: float = 0.5) -> List[ContextNode]:
        """
        Get all nodes with trust score below threshold.
        
        Args:
            threshold: Trust score threshold
            
        Returns:
            List of nodes with trust score < threshold
        """
        return [n for n in self._nodes.values() if n.trust_score < threshold]
    
    def get_nodes_by_tier(self, tier: TrustTier) -> List[ContextNode]:
        """
        Get all nodes in a specific trust tier.
        
        Args:
            tier: Trust tier to filter by
            
        Returns:
            List of nodes in the specified tier
        """
        return [n for n in self._nodes.values() if n.trust_tier == tier]
    
    def boost_related_nodes(self, node_id: str, boost: float = 0.05) -> None:
        """
        Boost trust score of related nodes.
        
        Args:
            node_id: Node identifier
            boost: Amount to boost trust scores
        """
        neighbors = self.get_neighbors(node_id)
        for neighbor_id in neighbors:
            self.update_trust_score(neighbor_id, boost)
    
    # =========================================================================
    # Version Vector Operations
    # =========================================================================
    
    def get_version_vector(self, node_id: str) -> Optional[VersionVector]:
        """Get the version vector for a node."""
        node = self.get_node(node_id)
        return node.version_vector if node else None
    
    def increment_version(self, node_id: str) -> bool:
        """
        Increment version counter for a node.
        
        Args:
            node_id: Node identifier
            
        Returns:
            True if node was found and updated
        """
        node = self.get_node(node_id)
        if node and node.version_vector:
            node.version_vector.increment(node_id)
            node.last_modified = now_utc()
            return True
        return False
    
    def merge_version_vectors(
        self,
        v1: VersionVector,
        v2: VersionVector
    ) -> VersionVector:
        """Merge two version vectors."""
        return v1.merge(v2)
    
    def detect_concurrent_modifications(self) -> List[Tuple[str, str]]:
        """
        Detect pairs of nodes with concurrent modifications.
        
        Returns:
            List of (node_id1, node_id2) tuples with concurrent modifications
        """
        concurrent_pairs = []
        nodes = list(self._nodes.values())
        
        for i, n1 in enumerate(nodes):
            for n2 in nodes[i+1:]:
                if (n1.version_vector and n2.version_vector and
                    n1.version_vector.is_concurrent(n2.version_vector)):
                    concurrent_pairs.append((n1.id, n2.id))
        
        return concurrent_pairs
    
    # =========================================================================
    # Stale Detection
    # =========================================================================
    
    def detect_stale_nodes(
        self,
        max_age_hours: float = 24.0,
        min_trust: float = 0.3
    ) -> List[ContextNode]:
        """
        Detect stale nodes based on age and trust score.
        
        Args:
            max_age_hours: Maximum age in hours before considering stale
            min_trust: Minimum trust score to not be considered stale
            
        Returns:
            List of stale nodes
        """
        from datetime import timedelta
        
        stale = []
        threshold = now_utc() - timedelta(hours=max_age_hours)
        
        for node in self._nodes.values():
            is_old = node.last_modified and node.last_modified < threshold
            is_low_trust = node.trust_score < min_trust
            
            if is_old or is_low_trust:
                stale.append(node)
        
        return stale
    
    def get_freshness_score(self, node_id: str) -> float:
        """
        Calculate freshness score for a node (0.0 to 1.0).
        
        Based on age, usage, and trust.
        """
        node = self.get_node(node_id)
        if not node:
            return 0.0
        
        from datetime import timedelta
        
        # Age factor (1.0 for just modified, decaying to 0.0 over 7 days)
        age_factor = 1.0
        if node.last_modified:
            age = now_utc() - node.last_modified
            max_age = timedelta(days=7)
            age_hours = age.total_seconds() / 3600
            max_hours = max_age.total_seconds() / 3600
            age_factor = max(0.0, 1.0 - (age_hours / max_hours))
        
        # Usage factor (logarithmic scaling)
        import math
        usage_factor = min(1.0, math.log(node.usage_count + 1) / 5)
        
        # Combined score
        return 0.4 * node.trust_score + 0.4 * age_factor + 0.2 * usage_factor
    
    # =========================================================================
    # Serialization
    # =========================================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert graph to dictionary for JSON serialization."""
        # Calculate metadata
        trust_scores = [n.trust_score for n in self._nodes.values()]
        avg_trust = sum(trust_scores) / len(trust_scores) if trust_scores else 0.0
        
        trust_distribution = {
            "TIER_1_TRUSTED": 0,
            "TIER_2_RELIABLE": 0,
            "TIER_3_UNCERTAIN": 0,
            "TIER_4_UNTRUSTED": 0,
        }
        for node in self._nodes.values():
            trust_distribution[node.trust_tier.value] += 1
        
        stale = self.detect_stale_nodes()
        
        return {
            "version": "1.0.0",
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges],
            "metadata": {
                "generated_at": now_utc_iso(),
                "total_nodes": len(self._nodes),
                "total_edges": len(self._edges),
                "avg_trust_score": round(avg_trust, 3),
                "stale_nodes": [n.id for n in stale],
                "trust_distribution": trust_distribution,
                "protocol_version": "5.0.0",
                "session_id": self._session_id,
            }
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert graph to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextGraph":
        """Create graph from dictionary."""
        graph = cls()
        
        # Add nodes
        for node_data in data.get("nodes", []):
            node = ContextNode.from_dict(node_data)
            graph.add_node(node)
        
        # Add edges
        for edge_data in data.get("edges", []):
            edge = ContextEdge.from_dict(edge_data)
            graph.add_edge(edge)
        
        # Set session ID from metadata
        metadata = data.get("metadata", {})
        graph._session_id = metadata.get("session_id")
        
        return graph
    
    @classmethod
    def from_json(cls, json_str: str) -> "ContextGraph":
        """Create graph from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    def save(self, path: str) -> None:
        """Save graph to file."""
        with open(path, "w") as f:
            f.write(self.to_json())
    
    @classmethod
    def load(cls, path: str) -> "ContextGraph":
        """Load graph from file."""
        with open(path, "r") as f:
            return cls.from_json(f.read())
    
    # =========================================================================
    # Statistics
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics."""
        trust_scores = [n.trust_score for n in self._nodes.values()]
        
        return {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "avg_trust_score": sum(trust_scores) / len(trust_scores) if trust_scores else 0.0,
            "min_trust_score": min(trust_scores) if trust_scores else 0.0,
            "max_trust_score": max(trust_scores) if trust_scores else 0.0,
            "stale_nodes_count": len(self.detect_stale_nodes()),
            "low_trust_nodes_count": len(self.get_low_trust_nodes(0.5)),
        }
