"""
Pruning Policy for TITAN FUSE Protocol.

ITEM-SAE-008: EXEC Stage Pruning - Pruning Policy

Defines policies for when and how to prune execution stages.
Provides configurable rules for stage retention and removal.

Key Features:
- Configurable retention policies
- Priority-based pruning decisions
- Session-aware pruning
- Integration with SessionManager

Author: TITAN FUSE Team
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any, Set, Callable
import logging
import threading

from src.utils.timezone import now_utc
from src.context.summarization import (
    ExecutionStage,
    StageSummary,
    StageStatus,
    StageType,
)


class PruningStrategy(Enum):
    """Strategy for pruning stages."""
    AGE_BASED = "age_based"          # Prune oldest first
    SIZE_BASED = "size_based"        # Prune largest first
    PRIORITY_BASED = "priority_based"  # Prune lowest priority first
    HYBRID = "hybrid"                # Combination of strategies


class RetentionReason(Enum):
    """Reason for retaining a stage."""
    ACTIVE = "active"
    RECENT = "recent"
    ROLLBACK_POINT = "rollback_point"
    HIGH_PRIORITY = "high_priority"
    HAS_ERRORS = "has_errors"
    CONFIGURED_MINIMUM = "configured_minimum"


@dataclass
class PruningCandidate:
    """
    A candidate for pruning.
    
    Attributes:
        stage: The stage being evaluated
        priority: Retention priority (higher = keep longer)
        reasons: Reasons for retaining
        can_prune: Whether the stage can be pruned
        estimated_savings: Estimated memory savings from pruning
    """
    stage: ExecutionStage
    priority: float
    reasons: List[RetentionReason] = field(default_factory=list)
    can_prune: bool = True
    estimated_savings: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "stage_id": self.stage.stage_id,
            "priority": round(self.priority, 3),
            "reasons": [r.value for r in self.reasons],
            "can_prune": self.can_prune,
            "estimated_savings": self.estimated_savings,
        }


@dataclass
class PruningResult:
    """
    Result of applying a pruning policy.
    
    Attributes:
        stages_pruned: Number of stages pruned
        stages_retained: Number of stages retained
        bytes_saved: Estimated bytes saved
        pruned_ids: IDs of pruned stages
        retained_ids: IDs of retained stages
        policy_name: Name of applied policy
        applied_at: When the policy was applied
    """
    stages_pruned: int
    stages_retained: int
    bytes_saved: int
    pruned_ids: List[str] = field(default_factory=list)
    retained_ids: List[str] = field(default_factory=list)
    policy_name: str = ""
    applied_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "stages_pruned": self.stages_pruned,
            "stages_retained": self.stages_retained,
            "bytes_saved": self.bytes_saved,
            "pruned_ids": self.pruned_ids,
            "retained_ids": self.retained_ids,
            "policy_name": self.policy_name,
            "applied_at": self.applied_at,
        }


@dataclass
class PruningPolicyConfig:
    """
    Configuration for pruning policy.
    
    Attributes:
        max_full_stages: Maximum full stages to retain
        max_age_hours: Maximum age before pruning
        min_stages_per_type: Minimum stages to keep per type
        preserve_rollback_stages: Always keep stages with rollback points
        preserve_error_stages: Keep stages with errors for debugging
        target_memory_mb: Target memory usage in MB
    """
    max_full_stages: int = 3
    max_age_hours: float = 24.0
    min_stages_per_type: int = 1
    preserve_rollback_stages: bool = True
    preserve_error_stages: bool = True
    target_memory_mb: int = 100
    strategy: PruningStrategy = PruningStrategy.HYBRID


class PruningPolicy:
    """
    Policy for pruning execution stages.
    
    Determines which stages should be pruned based on configurable rules.
    Supports multiple strategies and can be customized per session type.
    
    Usage:
        policy = PruningPolicy(config)
        
        # Check if a stage should be pruned
        should_prune = policy.should_prune(stage, session)
        
        # Get candidates for pruning
        candidates = policy.get_pruning_candidates(session)
        
        # Apply policy to a session
        result = policy.apply_policy(session)
    """
    
    def __init__(self, config: Optional[PruningPolicyConfig] = None):
        """
        Initialize the PruningPolicy.
        
        Args:
            config: Policy configuration
        """
        self._config = config or PruningPolicyConfig()
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)
        
        # Custom retention rules
        self._custom_rules: List[Callable[[ExecutionStage, Any], bool]] = []
    
    # =========================================================================
    # Policy Application
    # =========================================================================
    
    def should_prune(
        self,
        stage: ExecutionStage,
        session: Optional[Any] = None
    ) -> bool:
        """
        Determine if a stage should be pruned.
        
        Args:
            stage: ExecutionStage to evaluate
            session: Optional session context
            
        Returns:
            True if the stage should be pruned
        """
        # Cannot prune active stages
        if not stage.can_prune:
            return False
        
        # Check retention rules
        priority, reasons = self._calculate_priority(stage, session)
        
        # If there are strong retention reasons, don't prune
        strong_reasons = {
            RetentionReason.ACTIVE,
            RetentionReason.ROLLBACK_POINT,
        }
        
        if any(r in strong_reasons for r in reasons):
            if self._config.preserve_rollback_stages and RetentionReason.ROLLBACK_POINT in reasons:
                return False
        
        # Check age
        if stage.end_time:
            try:
                end_dt = datetime.fromisoformat(stage.end_time)
                age_hours = (now_utc() - end_dt).total_seconds() / 3600
                if age_hours > self._config.max_age_hours:
                    return True
            except (ValueError, TypeError):
                pass
        
        # Check priority threshold
        return priority < 0.3
    
    def get_retention_priority(
        self,
        stage: ExecutionStage,
        session: Optional[Any] = None
    ) -> float:
        """
        Calculate retention priority for a stage.
        
        Higher values indicate higher priority (keep longer).
        
        Args:
            stage: ExecutionStage to evaluate
            session: Optional session context
            
        Returns:
            Priority score (0.0 to 1.0)
        """
        priority, _ = self._calculate_priority(stage, session)
        return priority
    
    def get_pruning_candidates(
        self,
        stages: List[ExecutionStage],
        session: Optional[Any] = None
    ) -> List[PruningCandidate]:
        """
        Get all stages that are candidates for pruning.
        
        Args:
            stages: List of execution stages
            session: Optional session context
            
        Returns:
            List of PruningCandidate objects
        """
        candidates = []
        
        for stage in stages:
            priority, reasons = self._calculate_priority(stage, session)
            
            candidate = PruningCandidate(
                stage=stage,
                priority=priority,
                reasons=reasons,
                can_prune=stage.can_prune,
                estimated_savings=self._estimate_savings(stage),
            )
            candidates.append(candidate)
        
        # Sort by priority (lowest first for pruning)
        candidates.sort(key=lambda c: c.priority)
        
        return candidates
    
    def apply_policy(
        self,
        stages: List[ExecutionStage],
        session: Optional[Any] = None
    ) -> PruningResult:
        """
        Apply pruning policy to a list of stages.
        
        Args:
            stages: List of execution stages
            session: Optional session context
            
        Returns:
            PruningResult with details
        """
        candidates = self.get_pruning_candidates(stages, session)
        
        pruned_ids = []
        retained_ids = []
        bytes_saved = 0
        
        # Count stages by type for minimum retention
        type_counts: Dict[StageType, int] = {}
        
        # Determine how many to prune
        max_prune = len(stages) - self._config.max_full_stages
        
        for candidate in candidates:
            stage_type = candidate.stage.stage_type
            current_count = type_counts.get(stage_type, 0)
            
            # Check minimum per type
            if current_count < self._config.min_stages_per_type:
                retained_ids.append(candidate.stage.stage_id)
                type_counts[stage_type] = current_count + 1
                continue
            
            # Check if we should prune
            if (candidate.can_prune and
                len(pruned_ids) < max_prune and
                self._should_prune_candidate(candidate)):
                
                pruned_ids.append(candidate.stage.stage_id)
                bytes_saved += candidate.estimated_savings
            else:
                retained_ids.append(candidate.stage.stage_id)
                type_counts[stage_type] = type_counts.get(stage_type, 0) + 1
        
        return PruningResult(
            stages_pruned=len(pruned_ids),
            stages_retained=len(retained_ids),
            bytes_saved=bytes_saved,
            pruned_ids=pruned_ids,
            retained_ids=retained_ids,
            policy_name=f"{self._config.strategy.value}_policy",
        )
    
    # =========================================================================
    # Custom Rules
    # =========================================================================
    
    def add_retention_rule(
        self,
        rule: Callable[[ExecutionStage, Any], bool]
    ) -> None:
        """
        Add a custom retention rule.
        
        Args:
            rule: Function that returns True if stage should be retained
        """
        self._custom_rules.append(rule)
    
    def clear_custom_rules(self) -> None:
        """Clear all custom retention rules."""
        self._custom_rules.clear()
    
    # =========================================================================
    # Internal Methods
    # =========================================================================
    
    def _calculate_priority(
        self,
        stage: ExecutionStage,
        session: Optional[Any]
    ) -> tuple[float, List[RetentionReason]]:
        """Calculate priority and retention reasons."""
        priority = 0.5
        reasons: List[RetentionReason] = []
        
        # Active stages have highest priority
        if not stage.can_prune:
            return 1.0, [RetentionReason.ACTIVE]
        
        # Check age
        if stage.end_time:
            try:
                end_dt = datetime.fromisoformat(stage.end_time)
                age_hours = (now_utc() - end_dt).total_seconds() / 3600
                
                if age_hours < 1:
                    priority += 0.3
                    reasons.append(RetentionReason.RECENT)
                elif age_hours < 6:
                    priority += 0.15
                elif age_hours > self._config.max_age_hours:
                    priority -= 0.2
            except (ValueError, TypeError):
                pass
        
        # Check for rollback point
        if stage.rollback_point and self._config.preserve_rollback_stages:
            priority += 0.25
            reasons.append(RetentionReason.ROLLBACK_POINT)
        
        # Check for errors
        if stage.errors_encountered and self._config.preserve_error_stages:
            priority += 0.15
            reasons.append(RetentionReason.HAS_ERRORS)
        
        # Token usage
        if stage.tokens_used > 10000:
            priority += 0.1
        elif stage.tokens_used > 5000:
            priority += 0.05
        
        # Apply custom rules
        for rule in self._custom_rules:
            try:
                if rule(stage, session):
                    priority += 0.1
            except Exception as e:
                self._logger.warning(f"Custom rule error: {e}")
        
        # Apply strategy-specific adjustments
        if self._config.strategy == PruningStrategy.SIZE_BASED:
            # Higher token usage = higher priority
            priority += min(0.2, stage.tokens_used / 100000)
        elif self._config.strategy == PruningStrategy.AGE_BASED:
            # Already handled above
            pass
        
        return min(1.0, max(0.0, priority)), reasons
    
    def _estimate_savings(self, stage: ExecutionStage) -> int:
        """Estimate memory savings from pruning a stage."""
        # Rough estimate based on stage content
        base_size = 1024  # Base overhead
        
        # Add sizes for lists
        base_size += len(stage.files_processed) * 100
        base_size += len(stage.patches_applied) * 200
        base_size += len(stage.gates_passed) * 50
        base_size += len(stage.errors_encountered) * 100
        
        # Token data
        base_size += stage.tokens_used // 10
        
        return base_size
    
    def _should_prune_candidate(self, candidate: PruningCandidate) -> bool:
        """Determine if a candidate should be pruned."""
        # Don't prune if there are strong retention reasons
        if RetentionReason.ROLLBACK_POINT in candidate.reasons:
            if self._config.preserve_rollback_stages:
                return False
        
        # Prune based on priority
        return candidate.priority < 0.5
    
    # =========================================================================
    # Configuration
    # =========================================================================
    
    def update_config(self, **kwargs) -> None:
        """Update policy configuration."""
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
    
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration."""
        return {
            "max_full_stages": self._config.max_full_stages,
            "max_age_hours": self._config.max_age_hours,
            "min_stages_per_type": self._config.min_stages_per_type,
            "preserve_rollback_stages": self._config.preserve_rollback_stages,
            "preserve_error_stages": self._config.preserve_error_stages,
            "target_memory_mb": self._config.target_memory_mb,
            "strategy": self._config.strategy.value,
        }


# =============================================================================
# Module-level convenience
# =============================================================================

_default_policy: Optional[PruningPolicy] = None


def get_pruning_policy(config: Optional[PruningPolicyConfig] = None) -> PruningPolicy:
    """Get or create default PruningPolicy instance."""
    global _default_policy
    
    if _default_policy is None:
        _default_policy = PruningPolicy(config=config)
    elif config is not None:
        _default_policy = PruningPolicy(config=config)
    
    return _default_policy
