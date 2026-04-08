"""
Conflict Resolution Formula Engine for TITAN FUSE Protocol.

ITEM-CAT-04: Mathematical formula for idea-level conflicts.
ITEM-ART-002: Integration with DecisionRecordManager for artifact compliance.
ITEM-AGENT-001: Integration with ScoutMatrix for scout-based conflict resolution.

Implements a deterministic weighted scoring system for resolving conflicts
between competing options or ideas. The formula follows Catalog §16 weights:

    score = accuracy×0.40 + utility×0.35 + efficiency×0.15 + consensus×0.10

Threshold-based decision logic provides graduated confidence levels based
on the gap between competing scores.

Scout Integration (ITEM-AGENT-001):
    The resolve_with_scouts method integrates ScoutMatrix findings with
    RoleWeightedConsensus for unified decision making.

Example:
    >>> resolver = ConflictResolver()
    >>> option_a = ConflictMetrics(accuracy=0.9, utility=0.8, efficiency=0.7, consensus=0.6)
    >>> option_b = ConflictMetrics(accuracy=0.5, utility=0.5, efficiency=0.5, consensus=0.5)
    >>> decision = resolver.resolve(option_a, option_b, label_a="Fast Approach", label_b="Safe Approach")
    >>> print(decision.winner)
    'Fast Approach'
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from src.decision.decision_record import DecisionRecordManager
    from src.agents.scout_matrix import ScoutMatrix, ScoutFinding, AggregatedFindings, ConsensusResult

# Configure module logger
logger = logging.getLogger(__name__)


# Default weights per Catalog §16
DEFAULT_CONFLICT_WEIGHTS: dict[str, float] = {
    "accuracy": 0.40,
    "utility": 0.35,
    "efficiency": 0.15,
    "consensus": 0.10,
}


class DecisionConfidence(Enum):
    """
    Confidence levels for conflict resolution decisions.
    
    Attributes:
        HIGH: Strong confidence - score gap >= 2.0
        MEDIUM: Moderate confidence - score gap >= 1.0 but < 2.0
        LOW: Weak confidence - score gap < 1.0
    """
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ResolutionStatus(Enum):
    """
    ITEM-AGENT-001: Status of a conflict resolution.
    
    Attributes:
        RESOLVED: Conflict has been resolved
        BLOCKED: Resolution blocked by veto
        ESCALATED: Conflict escalated for human review
        PENDING: Resolution pending additional information
    """
    RESOLVED = "resolved"
    BLOCKED = "blocked"
    ESCALATED = "escalated"
    PENDING = "pending"


@dataclass
class Conflict:
    """
    ITEM-AGENT-001: Represents a conflict to be resolved.
    
    Attributes:
        conflict_id: Unique identifier for this conflict
        title: Brief title of the conflict
        description: Detailed description
        options: List of options being considered
        context: Additional context data
        severity: Severity level (SEV-1 to SEV-4)
    """
    conflict_id: str
    title: str
    description: str
    options: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    severity: str = "SEV-3"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "conflict_id": self.conflict_id,
            "title": self.title,
            "description": self.description,
            "options": self.options,
            "context": self.context,
            "severity": self.severity,
        }


@dataclass
class Resolution:
    """
    ITEM-AGENT-001: Result of resolving a conflict with scout findings.
    
    Attributes:
        conflict: The original conflict
        status: Resolution status
        action_taken: Action that was taken
        rationale: Explanation for the resolution
        confidence: Confidence in the resolution (0.0 - 1.0)
        consensus_result: Optional ConsensusResult from scout matrix
        selected_option: The selected option if resolved
        veto_triggered: Whether a veto was triggered
    """
    conflict: Conflict
    status: ResolutionStatus
    action_taken: str
    rationale: str
    confidence: float
    consensus_result: Optional["ConsensusResult"] = None
    selected_option: Optional[str] = None
    veto_triggered: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "conflict_id": self.conflict.conflict_id,
            "status": self.status.value,
            "action_taken": self.action_taken,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "selected_option": self.selected_option,
            "veto_triggered": self.veto_triggered,
        }


@dataclass
class ConflictMetrics:
    """
    Metrics for evaluating a single option in conflict resolution.
    
    All metric values are normalized to the range [0.0, 1.0] where higher
    values indicate better performance in that dimension.
    
    Attributes:
        accuracy: Factual correctness of the option (0.0-1.0).
            Measures how well the option aligns with verified facts and truth.
        utility: Practical applicability of the option (0.0-1.0).
            Measures how useful and applicable the option is in practice.
        efficiency: Resource/complexity tradeoff (0.0-1.0).
            Measures how efficiently the option uses resources relative to outcomes.
        consensus: Source agreement level (0.0-1.0).
            Measures the degree of agreement among relevant sources or stakeholders.
        optimal_context: Optional context string describing when this option
            is optimal. Used for conditional recommendations.
    
    Example:
        >>> metrics = ConflictMetrics(
        ...     accuracy=0.95,
        ...     utility=0.80,
        ...     efficiency=0.70,
        ...     consensus=0.85,
        ...     optimal_context="Best for production environments"
        ... )
    """
    accuracy: float
    utility: float
    efficiency: float
    consensus: float
    optimal_context: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validate that all metrics are within valid range [0.0, 1.0]."""
        for field_name in ["accuracy", "utility", "efficiency", "consensus"]:
            value = getattr(self, field_name)
            if not isinstance(value, (int, float)):
                raise TypeError(
                    f"{field_name} must be a number, got {type(value).__name__}"
                )
            if not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"{field_name} must be in range [0.0, 1.0], got {value}"
                )
        logger.debug(
            f"ConflictMetrics created: accuracy={self.accuracy:.3f}, "
            f"utility={self.utility:.3f}, efficiency={self.efficiency:.3f}, "
            f"consensus={self.consensus:.3f}"
        )


@dataclass
class Decision:
    """
    Result of a conflict resolution between two options.
    
    Encapsulates the outcome of comparing two ConflictMetrics instances,
    including the winner (if any), confidence level, and reasoning.
    
    Attributes:
        winner: The label of the winning option, or None if the decision
            is conditional (gap < 1.0 and no clear winner).
        conditional: True if the decision is conditional and requires
            additional context or judgment. False if there's a clear winner.
        rationale: Explanation for the decision. Present when confidence
            is MEDIUM or LOW, absent for HIGH confidence decisions.
        confidence: The confidence level of this decision based on the
            score gap between options.
        score_a: The calculated conflict score for option A.
        score_b: The calculated conflict score for option B.
        gap: The absolute difference between scores.
    
    Example:
        >>> decision = Decision(
        ...     winner="Option A",
        ...     conditional=False,
        ...     rationale="Higher accuracy and utility scores",
        ...     confidence=DecisionConfidence.MEDIUM,
        ...     score_a=0.850,
        ...     score_b=0.500,
        ...     gap=0.350
        ... )
    """
    winner: Optional[str]
    conditional: bool
    rationale: Optional[str]
    confidence: DecisionConfidence
    score_a: float = 0.0
    score_b: float = 0.0
    gap: float = 0.0


class ConflictResolver:
    """
    Resolves conflicts between competing options using weighted metrics.
    
    Implements the TITAN Protocol conflict resolution formula with
    deterministic scoring and threshold-based decision logic.
    
    The default weights follow Catalog §16:
        - accuracy: 0.40 (highest priority)
        - utility: 0.35
        - efficiency: 0.15
        - consensus: 0.10 (lowest priority)
    
    Decision thresholds:
        - gap >= 2.0: HIGH confidence, clear winner, no rationale needed
        - gap >= 1.0: MEDIUM confidence, winner with rationale
        - gap < 1.0: LOW confidence, conditional recommendation
    
    Attributes:
        weights: Dictionary of metric weights. Defaults to DEFAULT_CONFLICT_WEIGHTS.
    
    Example:
        >>> resolver = ConflictResolver()
        >>> option_a = ConflictMetrics(0.9, 0.8, 0.7, 0.6)
        >>> option_b = ConflictMetrics(0.5, 0.5, 0.5, 0.5)
        >>> decision = resolver.resolve(option_a, option_b, "A", "B")
    """
    
    # Threshold constants for decision logic
    HIGH_CONFIDENCE_THRESHOLD: float = 2.0
    MEDIUM_CONFIDENCE_THRESHOLD: float = 1.0
    
    def __init__(self, weights: Optional[dict[str, float]] = None) -> None:
        """
        Initialize the ConflictResolver with optional custom weights.
        
        Args:
            weights: Optional dictionary of metric weights. Must contain
                keys 'accuracy', 'utility', 'efficiency', and 'consensus'.
                If not provided, uses DEFAULT_CONFLICT_WEIGHTS.
        
        Raises:
            ValueError: If weights don't sum to approximately 1.0 or are missing keys.
        """
        self.weights = weights if weights is not None else DEFAULT_CONFLICT_WEIGHTS.copy()
        self._validate_weights()
        logger.info(
            f"ConflictResolver initialized with weights: "
            f"accuracy={self.weights['accuracy']:.2f}, "
            f"utility={self.weights['utility']:.2f}, "
            f"efficiency={self.weights['efficiency']:.2f}, "
            f"consensus={self.weights['consensus']:.2f}"
        )
    
    def _validate_weights(self) -> None:
        """Validate that weights are properly configured."""
        required_keys = {"accuracy", "utility", "efficiency", "consensus"}
        provided_keys = set(self.weights.keys())
        
        if not required_keys.issubset(provided_keys):
            missing = required_keys - provided_keys
            raise ValueError(f"Missing required weight keys: {missing}")
        
        total = sum(self.weights.values())
        if not 0.99 <= total <= 1.01:  # Allow small floating-point tolerance
            raise ValueError(
                f"Weights must sum to 1.0, got {total:.4f}"
            )
        
        for key, value in self.weights.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"Weight for '{key}' must be in [0.0, 1.0], got {value}"
                )
    
    def calculate_conflict_score(
        self,
        metrics: ConflictMetrics,
        weights: Optional[dict[str, float]] = None
    ) -> float:
        """
        Calculate the weighted conflict score for given metrics.
        
        The score is computed as:
            score = accuracy×w_accuracy + utility×w_utility +
                    efficiency×w_efficiency + consensus×w_consensus
        
        Result is deterministically rounded to 3 decimal places.
        
        Args:
            metrics: ConflictMetrics instance to score.
            weights: Optional custom weights. Uses instance weights if not provided.
        
        Returns:
            Float score rounded to 3 decimal places (0.000 to 1.000).
        
        Example:
            >>> resolver = ConflictResolver()
            >>> metrics = ConflictMetrics(accuracy=1.0, utility=1.0, 
            ...                          efficiency=1.0, consensus=1.0)
            >>> resolver.calculate_conflict_score(metrics)
            1.0
        """
        w = weights if weights is not None else self.weights
        
        raw_score = (
            metrics.accuracy * w["accuracy"] +
            metrics.utility * w["utility"] +
            metrics.efficiency * w["efficiency"] +
            metrics.consensus * w["consensus"]
        )
        
        # Deterministic rounding to 3 decimal places
        score = round(raw_score, 3)
        
        logger.debug(
            f"Calculated conflict score: {score:.3f} "
            f"(accuracy={metrics.accuracy:.2f}×{w['accuracy']:.2f} + "
            f"utility={metrics.utility:.2f}×{w['utility']:.2f} + "
            f"efficiency={metrics.efficiency:.2f}×{w['efficiency']:.2f} + "
            f"consensus={metrics.consensus:.2f}×{w['consensus']:.2f})"
        )
        
        return score
    
    def resolve(
        self,
        option_a: ConflictMetrics,
        option_b: ConflictMetrics,
        label_a: str = "Option A",
        label_b: str = "Option B",
        decision_record_manager: Optional["DecisionRecordManager"] = None,
        conflict_id: Optional[str] = None,
        context: Optional[dict] = None
    ) -> Decision:
        """
        Resolve conflict between two options based on their metrics.
        
        Compares the weighted scores of both options and produces a
        Decision based on the gap between scores:
        
        - gap >= 2.0: Clear winner with HIGH confidence, no rationale
        - gap >= 1.0: Winner with MEDIUM confidence and rationale
        - gap < 1.0: Conditional recommendation with LOW confidence
        
        Note: Gap is calculated as the absolute difference between scaled
        scores (multiplied by 10 for threshold comparison).
        
        Args:
            option_a: Metrics for the first option.
            option_b: Metrics for the second option.
            label_a: Label for the first option (default: "Option A").
            label_b: Label for the second option (default: "Option B").
            decision_record_manager: Optional DecisionRecordManager to record
                the decision (ITEM-ART-002).
            conflict_id: Optional conflict identifier for the decision record.
            context: Optional additional context for the decision record.
        
        Returns:
            Decision instance with winner, confidence, and optional rationale.
        
        Example:
            >>> resolver = ConflictResolver()
            >>> a = ConflictMetrics(0.9, 0.9, 0.9, 0.9)
            >>> b = ConflictMetrics(0.4, 0.4, 0.4, 0.4)
            >>> decision = resolver.resolve(a, b, "Fast", "Slow")
            >>> decision.winner
            'Fast'
            >>> decision.confidence
            <DecisionConfidence.HIGH: 'high'>
        """
        logger.info(
            f"Resolving conflict between '{label_a}' and '{label_b}'"
        )
        
        # Calculate scores for both options
        score_a = self.calculate_conflict_score(option_a)
        score_b = self.calculate_conflict_score(option_b)
        
        # Calculate gap (scale by 10 for threshold comparison)
        # This allows for meaningful thresholds with normalized scores
        gap = abs(score_a - score_b) * 10
        
        logger.debug(
            f"Scores: {label_a}={score_a:.3f}, {label_b}={score_b:.3f}, gap={gap:.3f}"
        )
        
        # Determine winner based on scores
        if score_a >= score_b:
            winner_label = label_a
            winner_metrics = option_a
        else:
            winner_label = label_b
            winner_metrics = option_b
        
        # Apply threshold logic
        if gap >= self.HIGH_CONFIDENCE_THRESHOLD:
            decision = self._make_high_confidence_decision(
                winner_label, score_a, score_b, gap
            )
        elif gap >= self.MEDIUM_CONFIDENCE_THRESHOLD:
            decision = self._make_medium_confidence_decision(
                winner_label, winner_metrics, score_a, score_b, gap,
                label_a, label_b
            )
        else:
            decision = self._make_low_confidence_decision(
                option_a, option_b, score_a, score_b, gap,
                label_a, label_b
            )
        
        logger.info(
            f"Decision: winner='{decision.winner}', "
            f"confidence={decision.confidence.value}, "
            f"conditional={decision.conditional}"
        )
        
        # ITEM-ART-002: Record decision if manager provided
        if decision_record_manager is not None:
            from src.decision.decision_record import DecisionType
            
            # Build options_considered for the record
            options_considered = [
                {
                    "label": label_a,
                    "score": score_a,
                    "metrics": {
                        "accuracy": option_a.accuracy,
                        "utility": option_a.utility,
                        "efficiency": option_a.efficiency,
                        "consensus": option_a.consensus
                    }
                },
                {
                    "label": label_b,
                    "score": score_b,
                    "metrics": {
                        "accuracy": option_b.accuracy,
                        "utility": option_b.utility,
                        "efficiency": option_b.efficiency,
                        "consensus": option_b.consensus
                    }
                }
            ]
            
            # Determine confidence value
            confidence_map = {
                DecisionConfidence.HIGH: 1.0,
                DecisionConfidence.MEDIUM: 0.7,
                DecisionConfidence.LOW: 0.4
            }
            
            decision_record_manager.record_decision(
                decision_type=DecisionType.CONFLICT_RESOLUTION,
                context=context or {
                    "gap": gap,
                    "score_a": score_a,
                    "score_b": score_b
                },
                options_considered=options_considered,
                selected_option=winner_label if winner_label else "conditional",
                rationale=decision.rationale or f"Score gap: {gap:.3f}",
                confidence=confidence_map.get(decision.confidence, 0.5),
                conflict_id=conflict_id
            )
        
        return decision
    
    def _make_high_confidence_decision(
        self,
        winner: str,
        score_a: float,
        score_b: float,
        gap: float
    ) -> Decision:
        """
        Create a HIGH confidence decision (gap >= 2.0).
        
        High confidence decisions have a clear winner with no rationale
        needed - the gap is large enough that the choice is obvious.
        """
        logger.debug(f"Creating HIGH confidence decision for winner '{winner}'")
        return Decision(
            winner=winner,
            conditional=False,
            rationale=None,  # No rationale for high confidence
            confidence=DecisionConfidence.HIGH,
            score_a=score_a,
            score_b=score_b,
            gap=gap
        )
    
    def _make_medium_confidence_decision(
        self,
        winner: str,
        winner_metrics: ConflictMetrics,
        score_a: float,
        score_b: float,
        gap: float,
        label_a: str,
        label_b: str
    ) -> Decision:
        """
        Create a MEDIUM confidence decision (1.0 <= gap < 2.0).
        
        Medium confidence decisions include a one-sentence rationale
        explaining the key differentiating factor.
        """
        logger.debug(f"Creating MEDIUM confidence decision for winner '{winner}'")
        
        # Generate one-sentence rationale based on strongest metric
        rationale = self._generate_rationale(
            winner_metrics, score_a, score_b, label_a, label_b
        )
        
        return Decision(
            winner=winner,
            conditional=False,
            rationale=rationale,
            confidence=DecisionConfidence.MEDIUM,
            score_a=score_a,
            score_b=score_b,
            gap=gap
        )
    
    def _make_low_confidence_decision(
        self,
        option_a: ConflictMetrics,
        option_b: ConflictMetrics,
        score_a: float,
        score_b: float,
        gap: float,
        label_a: str,
        label_b: str
    ) -> Decision:
        """
        Create a LOW confidence decision (gap < 1.0).
        
        Low confidence decisions are conditional - they provide context-
        specific recommendations rather than a clear winner.
        """
        logger.debug("Creating LOW confidence conditional decision")
        
        # Determine conditional recommendation based on optimal_context
        if score_a >= score_b:
            preferred = label_a
            preferred_metrics = option_a
            other = label_b
        else:
            preferred = label_b
            preferred_metrics = option_b
            other = label_a
        
        # Build conditional rationale
        if preferred_metrics.optimal_context:
            rationale = (
                f"Consider '{preferred}' for {preferred_metrics.optimal_context.lower()}; "
                f"otherwise '{other}' may be suitable."
            )
        else:
            rationale = (
                f"Scores are too close to declare a clear winner; "
                f"'{preferred}' has a slight edge but context should guide the choice."
            )
        
        return Decision(
            winner=None,  # No clear winner for conditional decisions
            conditional=True,
            rationale=rationale,
            confidence=DecisionConfidence.LOW,
            score_a=score_a,
            score_b=score_b,
            gap=gap
        )
    
    def _generate_rationale(
        self,
        winner_metrics: ConflictMetrics,
        score_a: float,
        score_b: float,
        label_a: str,
        label_b: str
    ) -> str:
        """
        Generate a one-sentence rationale for the decision.
        
        Identifies the strongest metric difference and creates
        a concise explanation.
        """
        # Find the metric with highest weighted contribution
        contributions = {
            "accuracy": winner_metrics.accuracy * self.weights["accuracy"],
            "utility": winner_metrics.utility * self.weights["utility"],
            "efficiency": winner_metrics.efficiency * self.weights["efficiency"],
            "consensus": winner_metrics.consensus * self.weights["consensus"],
        }
        
        strongest = max(contributions, key=contributions.get)
        strongest_value = getattr(winner_metrics, strongest)
        
        return (
            f"Selected based on superior {strongest} "
            f"({strongest_value:.0%}) with overall score advantage."
        )


    def resolve_with_scouts(
        self,
        conflict: Conflict,
        scout_findings: "AggregatedFindings",
        scout_matrix: Optional["ScoutMatrix"] = None
    ) -> Resolution:
        """
        ITEM-AGENT-001: Resolve conflict using scout findings with weighted consensus.
        
        Integrates ScoutMatrix findings with RoleWeightedConsensus to make
        decisions that respect veto rules and role weights.
        
        Args:
            conflict: The conflict to resolve
            scout_findings: Aggregated findings from all scout agents
            scout_matrix: Optional ScoutMatrix instance (creates new if None)
            
        Returns:
            Resolution with decision status and rationale
            
        Example:
            >>> resolver = ConflictResolver()
            >>> conflict = Conflict(
            ...     conflict_id="c1",
            ...     title="Framework Selection",
            ...     description="Choose between React and Vue"
            ... )
            >>> resolution = resolver.resolve_with_scouts(conflict, aggregated_findings)
            >>> print(resolution.status)
            ResolutionStatus.RESOLVED
        """
        logger.info(
            f"[ITEM-AGENT-001] Resolving conflict '{conflict.conflict_id}' "
            f"with scout findings"
        )
        
        # Import here to avoid circular imports
        from src.agents.scout_matrix import ScoutMatrix as ScoutMatrixClass
        
        # Use provided matrix or create new one
        matrix = scout_matrix or ScoutMatrixClass()
        
        # Get role weights from ScoutMatrix
        weights = matrix.get_role_weights()
        
        # Check for veto first
        if scout_findings.veto_active:
            logger.warning(
                f"[ITEM-AGENT-001] Veto active for conflict '{conflict.conflict_id}': "
                f"{scout_findings.veto_reason}"
            )
            return Resolution(
                conflict=conflict,
                status=ResolutionStatus.BLOCKED,
                action_taken="Veto triggered by scout findings",
                rationale=scout_findings.veto_reason or "Veto triggered",
                confidence=1.0,
                veto_triggered=True
            )
        
        # Submit to consensus
        consensus_result = matrix.submit_to_consensus(scout_findings)
        
        # Determine resolution status based on consensus
        if consensus_result.veto_triggered:
            status = ResolutionStatus.BLOCKED
            action_taken = "Consensus blocked by veto"
            confidence = 1.0
            selected_option = None
        elif consensus_result.approved:
            status = ResolutionStatus.RESOLVED
            action_taken = f"Consensus approved (score: {consensus_result.score:.2f})"
            confidence = consensus_result.confidence
            # Select the best option if options were provided
            selected_option = self._select_best_option(
                conflict.options, consensus_result
            )
        elif consensus_result.score >= 0.4:
            status = ResolutionStatus.ESCALATED
            action_taken = f"Low consensus (score: {consensus_result.score:.2f}), escalated"
            confidence = consensus_result.confidence
            selected_option = None
        else:
            status = ResolutionStatus.ESCALATED
            action_taken = f"Insufficient consensus (score: {consensus_result.score:.2f})"
            confidence = consensus_result.confidence
            selected_option = None
        
        resolution = Resolution(
            conflict=conflict,
            status=status,
            action_taken=action_taken,
            rationale=consensus_result.rationale,
            confidence=confidence,
            consensus_result=consensus_result,
            selected_option=selected_option,
            veto_triggered=consensus_result.veto_triggered
        )
        
        logger.info(
            f"[ITEM-AGENT-001] Conflict '{conflict.conflict_id}' resolved: "
            f"status={status.value}, confidence={confidence:.0%}"
        )
        
        return resolution
    
    def _select_best_option(
        self,
        options: Dict[str, Any],
        consensus_result: "ConsensusResult"
    ) -> Optional[str]:
        """Select the best option from available options based on consensus."""
        if not options:
            return None
        
        # If options have scores, pick the highest
        scored_options = []
        for key, value in options.items():
            if isinstance(value, dict) and "score" in value:
                scored_options.append((key, value["score"]))
            elif isinstance(value, (int, float)):
                scored_options.append((key, float(value)))
        
        if scored_options:
            # Sort by score descending
            scored_options.sort(key=lambda x: x[1], reverse=True)
            return scored_options[0][0]
        
        # If no scores, return first option if consensus approved
        if consensus_result.approved and options:
            return next(iter(options.keys()))
        
        return None


def create_conflict_resolver(
    weights: Optional[dict[str, float]] = None
) -> ConflictResolver:
    """
    Factory function to create a ConflictResolver instance.
    
    Provides a convenient way to create a ConflictResolver with
    optional custom weights.
    
    Args:
        weights: Optional dictionary of metric weights. If not provided,
            uses the default weights from Catalog §16.
    
    Returns:
        Configured ConflictResolver instance.
    
    Example:
        >>> resolver = create_conflict_resolver()
        >>> # Or with custom weights
        >>> custom = {"accuracy": 0.5, "utility": 0.3, 
        ...           "efficiency": 0.1, "consensus": 0.1}
        >>> resolver = create_conflict_resolver(custom)
    """
    return ConflictResolver(weights=weights)
