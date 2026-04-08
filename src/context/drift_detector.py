"""
Semantic Drift Detector for TITAN FUSE Protocol.

ITEM-SAE-007: Semantic Drift Detector Implementation

Detects when context has drifted from actual file state and requires refresh.
Monitors semantic changes and alerts when context is sufficiently outdated.

Key Features:
- Drift score calculation (0.0 to 1.0)
- Drift level classification (NONE, MINOR, MODERATE, SEVERE)
- Change impact analysis
- Integration with improvement loop
- Trust score adjustment based on drift

Drift Levels:
- NONE (0.0-0.1): No action needed
- MINOR (0.1-0.3): Log the drift
- MODERATE (0.3-0.6): Warn and suggest refresh
- SEVERE (0.6-1.0): Context refresh required

Author: TITAN FUSE Team
Version: 1.0.0
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple
import logging
import threading

from src.utils.timezone import now_utc, now_utc_iso
from src.context.context_graph import ContextGraph, ContextNode, TrustTier
from src.context.semantic_checksum import (
    SemanticChecksum,
    SemanticChecksumResult,
    Language,
    ChecksumDiff,
)


class DriftLevel(Enum):
    """
    Severity level of semantic drift.
    
    NONE: No significant drift, context is fresh
    MINOR: Small drift, logging recommended
    MODERATE: Significant drift, warning and refresh suggested
    SEVERE: Critical drift, context refresh required
    """
    NONE = "NONE"
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    
    @classmethod
    def from_score(cls, score: float) -> "DriftLevel":
        """Determine drift level from score."""
        if score < 0.1:
            return cls.NONE
        elif score < 0.3:
            return cls.MINOR
        elif score < 0.6:
            return cls.MODERATE
        else:
            return cls.SEVERE


@dataclass
class Change:
    """
    Represents a detected change in a file.
    
    Attributes:
        file_path: Path to the changed file
        change_type: Type of change (added, removed, modified)
        old_hash: Previous semantic hash
        new_hash: Current semantic hash
        impact_score: Impact score (0.0 to 1.0)
        detected_at: When the change was detected
    """
    file_path: str
    change_type: str
    old_hash: str
    new_hash: str
    impact_score: float = 0.0
    detected_at: str = field(default_factory=now_utc_iso)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "file_path": self.file_path,
            "change_type": self.change_type,
            "old_hash": self.old_hash,
            "new_hash": self.new_hash,
            "impact_score": self.impact_score,
            "detected_at": self.detected_at,
        }


@dataclass
class DriftResult:
    """
    Result of drift detection for a single node.
    
    Attributes:
        node_id: ID of the context node
        drift_score: Drift score (0.0 to 1.0)
        drift_level: Classification of drift
        changes: List of detected changes
        recommended_action: Suggested action
        details: Additional details
    """
    node_id: str
    drift_score: float
    drift_level: DriftLevel
    changes: List[Change] = field(default_factory=list)
    recommended_action: str = "continue"
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "node_id": self.node_id,
            "drift_score": round(self.drift_score, 3),
            "drift_level": self.drift_level.value,
            "changes": [c.to_dict() for c in self.changes],
            "recommended_action": self.recommended_action,
            "details": self.details,
        }


@dataclass
class DriftReport:
    """
    Complete drift report for the context graph.
    
    Attributes:
        total_nodes: Total nodes checked
        drifted_nodes: Nodes with detected drift
        severe_drift_count: Number of severely drifted nodes
        average_drift_score: Average drift score
        recommendations: List of recommended actions
        generated_at: When the report was generated
    """
    total_nodes: int
    drifted_nodes: List[DriftResult] = field(default_factory=list)
    severe_drift_count: int = 0
    average_drift_score: float = 0.0
    recommendations: List[str] = field(default_factory=list)
    generated_at: str = field(default_factory=now_utc_iso)
    
    @property
    def has_severe_drift(self) -> bool:
        """Check if any node has severe drift."""
        return self.severe_drift_count > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_nodes": self.total_nodes,
            "drifted_nodes_count": len(self.drifted_nodes),
            "severe_drift_count": self.severe_drift_count,
            "average_drift_score": round(self.average_drift_score, 3),
            "has_severe_drift": self.has_severe_drift,
            "recommendations": self.recommendations,
            "generated_at": self.generated_at,
            "drifted_nodes": [d.to_dict() for d in self.drifted_nodes],
        }


class DriftDetector:
    """
    Detects semantic drift in context nodes.
    
    Monitors the relationship between cached context and actual file state,
    alerting when context has drifted sufficiently to require refresh.
    
    Usage:
        detector = DriftDetector(context_graph)
        
        # Detect drift for all nodes
        report = detector.detect_all_drift()
        
        # Detect drift for specific node
        result = detector.detect_drift(node, current_file_content)
        
        # Get drift score
        score = detector.compute_drift_score(changes)
    """
    
    def __init__(
        self,
        context_graph: Optional[ContextGraph] = None,
        drift_threshold: float = 0.3,
        critical_threshold: float = 0.6,
        impact_weights: Optional[Dict[str, float]] = None,
    ):
        """
        Initialize the DriftDetector.
        
        Args:
            context_graph: Context graph to monitor
            drift_threshold: Threshold for MODERATE drift
            critical_threshold: Threshold for SEVERE drift
            impact_weights: Weights for different change types
        """
        self._graph = context_graph
        self._drift_threshold = drift_threshold
        self._critical_threshold = critical_threshold
        
        self._impact_weights = impact_weights or {
            "added": 0.2,
            "removed": 0.4,
            "modified": 0.3,
            "structural": 0.5,
            "signature_change": 0.6,
        }
        
        self._checksummer = SemanticChecksum()
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)
        
        # History tracking
        self._drift_history: List[DriftResult] = []
    
    def set_context_graph(self, graph: ContextGraph) -> None:
        """Set the context graph to monitor."""
        self._graph = graph
    
    # =========================================================================
    # Drift Detection
    # =========================================================================
    
    def detect_drift(
        self,
        node: ContextNode,
        current_content: Optional[str] = None
    ) -> DriftResult:
        """
        Detect drift for a specific context node.
        
        Args:
            node: Context node to check
            current_content: Optional current file content (read from file if not provided)
            
        Returns:
            DriftResult with drift details
        """
        changes: List[Change] = []
        drift_score = 0.0
        
        # Get current file content if not provided
        if current_content is None:
            try:
                with open(node.location, "r", encoding="utf-8") as f:
                    current_content = f.read()
            except (FileNotFoundError, OSError) as e:
                return DriftResult(
                    node_id=node.id,
                    drift_score=1.0,
                    drift_level=DriftLevel.SEVERE,
                    changes=[],
                    recommended_action="file_missing",
                    details={"error": str(e)},
                )
        
        # Compute current semantic hash
        language = self._checksummer.detect_language(node.location)
        current_result = self._checksummer.compute_ast_hash(
            current_content, language, node.location
        )
        
        # Compare with stored hash
        if node.semantic_hash:
            if node.semantic_hash != current_result.semantic_hash:
                # Semantic change detected
                change = Change(
                    file_path=node.location,
                    change_type="semantic",
                    old_hash=node.semantic_hash,
                    new_hash=current_result.semantic_hash,
                    impact_score=self._impact_weights.get("signature_change", 0.6),
                )
                changes.append(change)
        
        # Check content hash as fallback
        if node.content_hash:
            current_content_hash = hashlib.sha256(current_content.encode()).hexdigest()[:32]
            if node.content_hash != current_content_hash:
                if not changes:  # Only add if no semantic change detected
                    change = Change(
                        file_path=node.location,
                        change_type="content",
                        old_hash=node.content_hash,
                        new_hash=current_content_hash,
                        impact_score=0.2,
                    )
                    changes.append(change)
        
        # Check age-based drift
        if node.last_modified:
            age = now_utc() - node.last_modified
            age_hours = age.total_seconds() / 3600
            if age_hours > 24:
                age_drift = min(0.3, age_hours / 240)  # Max 0.3 for age
                drift_score += age_drift
        
        # Compute total drift score from changes
        drift_score += sum(c.impact_score for c in changes)
        drift_score = min(1.0, drift_score)
        
        # Determine drift level
        drift_level = DriftLevel.from_score(drift_score)
        
        # Determine recommended action
        recommended_action = self._determine_action(drift_level, changes)
        
        result = DriftResult(
            node_id=node.id,
            drift_score=drift_score,
            drift_level=drift_level,
            changes=changes,
            recommended_action=recommended_action,
            details={
                "current_hash": current_result.semantic_hash,
                "stored_hash": node.semantic_hash,
                "element_count": current_result.element_count,
            },
        )
        
        # Store in history
        self._drift_history.append(result)
        if len(self._drift_history) > 1000:
            self._drift_history = self._drift_history[-1000:]
        
        return result
    
    def detect_all_drift(self) -> DriftReport:
        """
        Detect drift for all nodes in the context graph.
        
        Returns:
            DriftReport with complete drift analysis
        """
        if not self._graph:
            return DriftReport(total_nodes=0)
        
        drifted_nodes: List[DriftResult] = []
        total_score = 0.0
        severe_count = 0
        recommendations = set()
        
        for node in self._graph.get_all_nodes():
            result = self.detect_drift(node)
            
            total_score += result.drift_score
            
            if result.drift_level != DriftLevel.NONE:
                drifted_nodes.append(result)
                
                if result.drift_level == DriftLevel.SEVERE:
                    severe_count += 1
                
                recommendations.add(result.recommended_action)
        
        avg_score = total_score / len(self._graph.get_all_nodes()) if self._graph.get_all_nodes() else 0.0
        
        return DriftReport(
            total_nodes=len(self._graph.get_all_nodes()),
            drifted_nodes=drifted_nodes,
            severe_drift_count=severe_count,
            average_drift_score=avg_score,
            recommendations=sorted(list(recommendations)),
        )
    
    # =========================================================================
    # Drift Score Calculation
    # =========================================================================
    
    def compute_drift_score(self, changes: List[Change]) -> float:
        """
        Compute drift score from a list of changes.
        
        Args:
            changes: List of detected changes
            
        Returns:
            Drift score (0.0 to 1.0)
        """
        if not changes:
            return 0.0
        
        score = 0.0
        
        for change in changes:
            weight = self._impact_weights.get(change.change_type, 0.3)
            score += weight * change.impact_score
        
        return min(1.0, score)
    
    def classify_drift(self, score: float) -> DriftLevel:
        """
        Classify drift score into a level.
        
        Args:
            score: Drift score (0.0 to 1.0)
            
        Returns:
            DriftLevel classification
        """
        return DriftLevel.from_score(score)
    
    # =========================================================================
    # Integration Methods
    # =========================================================================
    
    def adjust_trust_scores(self, report: DriftReport) -> Dict[str, float]:
        """
        Adjust trust scores based on drift report.
        
        Nodes with drift have their trust scores reduced.
        
        Args:
            report: DriftReport to process
            
        Returns:
            Dict of node_id -> new_trust_score
        """
        if not self._graph:
            return {}
        
        adjustments = {}
        
        for drift_result in report.drifted_nodes:
            node = self._graph.get_node(drift_result.node_id)
            if node:
                # Reduce trust based on drift level
                if drift_result.drift_level == DriftLevel.SEVERE:
                    penalty = 0.3
                elif drift_result.drift_level == DriftLevel.MODERATE:
                    penalty = 0.15
                elif drift_result.drift_level == DriftLevel.MINOR:
                    penalty = 0.05
                else:
                    penalty = 0.0
                
                node.update_trust(-penalty)
                adjustments[node.id] = node.trust_score
        
        return adjustments
    
    def get_drift_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent drift detection history."""
        return [r.to_dict() for r in self._drift_history[-limit:]]
    
    # =========================================================================
    # Internal Methods
    # =========================================================================
    
    def _determine_action(
        self,
        drift_level: DriftLevel,
        changes: List[Change]
    ) -> str:
        """Determine recommended action based on drift level."""
        if drift_level == DriftLevel.SEVERE:
            return "refresh_required"
        elif drift_level == DriftLevel.MODERATE:
            return "refresh_suggested"
        elif drift_level == DriftLevel.MINOR:
            return "log"
        else:
            return "continue"


# =============================================================================
# Module-level convenience
# =============================================================================

_default_detector: Optional[DriftDetector] = None


def get_drift_detector(context_graph: Optional[ContextGraph] = None) -> DriftDetector:
    """Get or create default DriftDetector instance."""
    global _default_detector
    
    if _default_detector is None:
        _default_detector = DriftDetector(context_graph=context_graph)
    elif context_graph is not None:
        _default_detector.set_context_graph(context_graph)
    
    return _default_detector
