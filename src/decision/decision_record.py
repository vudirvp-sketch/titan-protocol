"""
ITEM-ART-002: Decision Record Enforcement for TITAN FUSE Protocol.

This module provides the DecisionRecordManager for ARTIFACT_CONTRACT compliance.
DECISION_RECORD is marked as REQUIRED in ARTIFACT_CONTRACT but was not enforced
in DELIVERY phase. This module bridges that gap.

The DecisionRecordManager collects all decisions made during execution
and generates the decision_record.json artifact in the DELIVERY phase.

Decision Types:
    - CONFLICT_RESOLUTION: Decisions from ConflictResolver
    - GATE_DECISION: Gate pass/fail decisions
    - ROUTING_DECISION: Model/content routing decisions
    - POLICY_DECISION: Policy application decisions
    - MERGE_DECISION: Content merge decisions
    - SCALING_DECISION: Scaling/adjustment decisions
    - ABORT_DECISION: Abort decisions
    - ROLLBACK_DECISION: Rollback decisions

Integration Points:
    - ConflictResolver: Records conflict resolution decisions
    - Orchestrator: Enforces decision record in DELIVERY phase
    - GateManager: Records gate decisions

Example:
    >>> from src.decision.decision_record import DecisionRecordManager, DecisionType
    >>> manager = DecisionRecordManager(session_id="sess-123")
    >>> manager.record_decision(
    ...     decision_type=DecisionType.CONFLICT_RESOLUTION,
    ...     context={"conflict": "merge conflict in file.py"},
    ...     options_considered=[{"label": "keep_ours"}, {"label": "keep_theirs"}],
    ...     selected_option="keep_ours",
    ...     rationale="Higher accuracy score",
    ...     confidence=0.85
    ... )
    >>> artifact = manager.generate_artifact()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional
import json
import logging

from src.utils.timezone import now_utc_iso


class DecisionType(Enum):
    """
    Types of decisions that can be recorded during execution.
    
    Each decision type corresponds to a specific decision point
    in the TITAN Protocol execution flow.
    
    Attributes:
        CONFLICT_RESOLUTION: Resolution of conflicting options
        GATE_DECISION: Gate pass/fail decisions
        ROUTING_DECISION: Model or content routing decisions
        POLICY_DECISION: Policy application decisions
        MERGE_DECISION: Content merge decisions
        SCALING_DECISION: Scaling or adjustment decisions
        ABORT_DECISION: Abort decisions
        ROLLBACK_DECISION: Rollback decisions
    """
    CONFLICT_RESOLUTION = "conflict_resolution"
    GATE_DECISION = "gate_decision"
    ROUTING_DECISION = "routing_decision"
    POLICY_DECISION = "policy_decision"
    MERGE_DECISION = "merge_decision"
    SCALING_DECISION = "scaling_decision"
    ABORT_DECISION = "abort_decision"
    ROLLBACK_DECISION = "rollback_decision"


@dataclass
class Decision:
    """
    A single decision made during execution.
    
    Encapsulates all information about a decision including context,
    options considered, and the rationale for the selection.
    
    Attributes:
        decision_id: Unique identifier for this decision
        decision_type: Type of decision (from DecisionType enum)
        timestamp: ISO8601 timestamp when decision was made
        context: Contextual information leading to the decision
        options_considered: List of options that were evaluated
        selected_option: The option that was selected
        rationale: Explanation for why this option was selected
        confidence: Confidence level in the decision (0.0-1.0)
        session_id: Session identifier for correlation
        gate_id: Optional gate ID if this is a gate decision
        conflict_id: Optional conflict ID if this is a conflict resolution
        metadata: Additional metadata for extensibility
    
    Example:
        >>> decision = Decision(
        ...     decision_id="DEC-sess1234-0001",
        ...     decision_type=DecisionType.CONFLICT_RESOLUTION,
        ...     timestamp="2024-01-15T10:30:00Z",
        ...     context={"file": "module.py", "conflict_type": "merge"},
        ...     options_considered=[{"label": "A"}, {"label": "B"}],
        ...     selected_option="A",
        ...     rationale="Higher accuracy score",
        ...     confidence=0.85,
        ...     session_id="sess-123"
        ... )
    """
    decision_id: str
    decision_type: DecisionType
    timestamp: str
    context: Dict[str, Any]
    options_considered: List[Dict[str, Any]]
    selected_option: str
    rationale: str
    confidence: float
    session_id: str
    gate_id: Optional[str] = None
    conflict_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        """Validate decision attributes."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in range [0.0, 1.0], got {self.confidence}"
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert decision to dictionary for serialization."""
        return {
            "decision_id": self.decision_id,
            "decision_type": self.decision_type.value,
            "timestamp": self.timestamp,
            "context": self.context,
            "options_considered": self.options_considered,
            "selected_option": self.selected_option,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "session_id": self.session_id,
            "gate_id": self.gate_id,
            "conflict_id": self.conflict_id,
            "metadata": self.metadata
        }


@dataclass
class DecisionRecordArtifact:
    """
    The decision record artifact for delivery.
    
    This is the final artifact generated for the DELIVERY phase,
    containing all decisions made during the session execution.
    
    Attributes:
        session_id: Session identifier
        created_at: ISO8601 timestamp when artifact was created
        decisions: List of all decisions made during execution
        summary: Summary counts by decision type
    
    Example:
        >>> artifact = DecisionRecordArtifact(
        ...     session_id="sess-123",
        ...     created_at="2024-01-15T10:35:00Z",
        ...     decisions=[decision1, decision2],
        ...     summary={"conflict_resolution": 2}
        ... )
    """
    session_id: str
    created_at: str
    decisions: List[Decision]
    summary: Dict[str, int]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert artifact to dictionary for serialization."""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "decisions": [d.to_dict() for d in self.decisions],
            "summary": self.summary
        }


class DecisionRecordManager:
    """
    ITEM-ART-002: Manage decision records for ARTIFACT_CONTRACT compliance.
    
    The DecisionRecordManager collects all decisions made during execution
    and generates the decision_record.json artifact in the DELIVERY phase.
    
    This ensures that DECISION_RECORD (marked as REQUIRED in ARTIFACT_CONTRACT)
    is properly enforced in the DELIVERY phase.
    
    Attributes:
        session_id: The session identifier for this manager
    
    Example:
        >>> manager = DecisionRecordManager(session_id="sess-123")
        >>> # Record a conflict resolution decision
        >>> decision = manager.record_decision(
        ...     decision_type=DecisionType.CONFLICT_RESOLUTION,
        ...     context={"file": "test.py"},
        ...     options_considered=[{"label": "A"}, {"label": "B"}],
        ...     selected_option="A",
        ...     rationale="Better coverage",
        ...     confidence=0.9,
        ...     conflict_id="conf-001"
        ... )
        >>> # Generate artifact for delivery
        >>> artifact = manager.generate_artifact()
        >>> artifact.to_dict()
    """
    
    def __init__(self, session_id: str):
        """
        Initialize the DecisionRecordManager.
        
        Args:
            session_id: The session identifier for correlation.
        """
        self._session_id = session_id
        self._decisions: List[Decision] = []
        self._decision_counter = 0
        self._logger = logging.getLogger(__name__)
        
        self._logger.info(
            f"[ITEM-ART-002] DecisionRecordManager initialized for session: {session_id}"
        )
    
    def record_decision(
        self,
        decision_type: DecisionType,
        context: Dict[str, Any],
        options_considered: List[Dict[str, Any]],
        selected_option: str,
        rationale: str,
        confidence: float,
        gate_id: Optional[str] = None,
        conflict_id: Optional[str] = None,
        metadata: Dict[str, Any] = None
    ) -> Decision:
        """
        Record a decision made during execution.
        
        Args:
            decision_type: Type of decision being recorded
            context: Contextual information about the decision
            options_considered: List of options that were evaluated
            selected_option: The option that was selected
            rationale: Explanation for the selection
            confidence: Confidence level (0.0-1.0)
            gate_id: Optional gate ID for gate decisions
            conflict_id: Optional conflict ID for conflict resolutions
            metadata: Additional metadata
        
        Returns:
            The created Decision instance.
        
        Raises:
            ValueError: If confidence is not in range [0.0, 1.0]
        
        Example:
            >>> decision = manager.record_decision(
            ...     decision_type=DecisionType.GATE_DECISION,
            ...     context={"gate": "GATE-03"},
            ...     options_considered=[{"pass": True}, {"pass": False}],
            ...     selected_option="pass",
            ...     rationale="All checks passed",
            ...     confidence=1.0,
            ...     gate_id="GATE-03"
            ... )
        """
        self._decision_counter += 1
        decision_id = f"DEC-{self._session_id[:8]}-{self._decision_counter:04d}"
        
        decision = Decision(
            decision_id=decision_id,
            decision_type=decision_type,
            timestamp=now_utc_iso(),
            context=context,
            options_considered=options_considered,
            selected_option=selected_option,
            rationale=rationale,
            confidence=confidence,
            session_id=self._session_id,
            gate_id=gate_id,
            conflict_id=conflict_id,
            metadata=metadata or {}
        )
        
        self._decisions.append(decision)
        
        self._logger.info(
            f"[ITEM-ART-002] Recorded decision {decision_id}: "
            f"{decision_type.value} -> {selected_option} (confidence: {confidence:.2f})"
        )
        
        return decision
    
    def get_decisions(self) -> List[Decision]:
        """
        Get all recorded decisions.
        
        Returns:
            List of all Decision instances recorded.
        """
        return list(self._decisions)
    
    def get_decisions_by_type(self, decision_type: DecisionType) -> List[Decision]:
        """
        Get decisions filtered by type.
        
        Args:
            decision_type: The type to filter by.
        
        Returns:
            List of Decision instances matching the type.
        """
        return [d for d in self._decisions if d.decision_type == decision_type]
    
    def get_decisions_by_gate(self, gate_id: str) -> List[Decision]:
        """
        Get decisions for a specific gate.
        
        Args:
            gate_id: The gate identifier.
        
        Returns:
            List of Decision instances for the gate.
        """
        return [d for d in self._decisions if d.gate_id == gate_id]
    
    def get_decision_count(self) -> int:
        """
        Get the total number of decisions recorded.
        
        Returns:
            Count of decisions.
        """
        return len(self._decisions)
    
    def empty(self) -> bool:
        """
        Check if no decisions have been recorded.
        
        Returns:
            True if no decisions recorded, False otherwise.
        """
        return len(self._decisions) == 0
    
    def generate_artifact(self) -> DecisionRecordArtifact:
        """
        Generate decision record artifact for delivery.
        
        Creates a DecisionRecordArtifact containing all decisions
        and a summary of decision counts by type.
        
        Returns:
            DecisionRecordArtifact ready for serialization.
        """
        # Build summary by decision type
        summary: Dict[str, int] = {}
        for decision in self._decisions:
            type_name = decision.decision_type.value
            summary[type_name] = summary.get(type_name, 0) + 1
        
        artifact = DecisionRecordArtifact(
            session_id=self._session_id,
            created_at=now_utc_iso(),
            decisions=self._decisions,
            summary=summary
        )
        
        self._logger.info(
            f"[ITEM-ART-002] Generated decision record artifact: "
            f"{len(self._decisions)} decisions across {len(summary)} types"
        )
        
        return artifact
    
    def to_json(self) -> str:
        """
        Export as JSON string.
        
        Generates the artifact and serializes to JSON format.
        
        Returns:
            JSON string representation of the artifact.
        """
        artifact = self.generate_artifact()
        return json.dumps(artifact.to_dict(), indent=2)
    
    def clear(self) -> None:
        """
        Clear all recorded decisions.
        
        Useful for testing or resetting state.
        """
        self._decisions.clear()
        self._decision_counter = 0
        self._logger.info(
            f"[ITEM-ART-002] Cleared all decisions for session: {self._session_id}"
        )


def create_decision_record_manager(session_id: str) -> DecisionRecordManager:
    """
    Factory function to create DecisionRecordManager.
    
    Provides a convenient way to create a DecisionRecordManager
    with the given session ID.
    
    Args:
        session_id: The session identifier.
    
    Returns:
        Configured DecisionRecordManager instance.
    
    Example:
        >>> manager = create_decision_record_manager("sess-123")
    """
    return DecisionRecordManager(session_id)


def write_decision_record(
    manager: DecisionRecordManager,
    output_path: str
) -> Dict[str, Any]:
    """
    Write decision record artifact to file.
    
    Args:
        manager: The DecisionRecordManager to export.
        output_path: Path to write the JSON file.
    
    Returns:
        Dictionary with write result including path and count.
    """
    import pathlib
    
    artifact = manager.generate_artifact()
    path = pathlib.Path(output_path)
    
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write artifact
    with open(path, 'w') as f:
        json.dump(artifact.to_dict(), f, indent=2)
    
    return {
        "success": True,
        "path": str(path),
        "decision_count": len(artifact.decisions),
        "summary": artifact.summary
    }
