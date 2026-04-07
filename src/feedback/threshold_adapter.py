"""
Threshold Adapter Module for TITAN Protocol.

ITEM-FEEDBACK-01: ThresholdAdapter Implementation

This module provides adaptive threshold adjustment based on feedback
statistics. It implements a learning algorithm that adjusts skill
confidence thresholds based on user feedback.

Features:
- Adaptive threshold calculation using feedback statistics
- Confidence factor based on sample size
- Threshold validation with constraints
- Dry-run simulation for safe testing

Key Formula:
    new_threshold = current_threshold + alpha * (positive_rate - target_rate) * confidence_factor
    
    Where:
    - alpha: learning rate (default 0.1)
    - positive_rate: thumbs_up / (thumbs_up + thumbs_down)
    - target_rate: target success rate (default 0.8)
    - confidence_factor: sqrt(sample_size / min_samples)

Components:
- DryRunResult: Result of a dry-run adjustment simulation
- ThresholdAdapter: Main threshold calculation and validation class

Author: TITAN Protocol Team
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, TYPE_CHECKING
import math
import logging

if TYPE_CHECKING:
    from src.feedback.feedback_loop import AggregatedFeedback, FeedbackLoop


class ValidationResult(Enum):
    """
    Result of threshold validation.
    
    Attributes:
        VALID: Threshold is within acceptable bounds
        TOO_LOW: Threshold is below minimum allowed
        TOO_HIGH: Threshold is above maximum allowed
        INVALID: Threshold is not a valid number
    """
    VALID = "valid"
    TOO_LOW = "too_low"
    TOO_HIGH = "too_high"
    INVALID = "invalid"


@dataclass
class DryRunResult:
    """
    Result of a dry-run threshold adjustment simulation.
    
    Provides detailed information about what would happen if a
    threshold adjustment were applied, including safety checks
    and predicted impact.
    
    Attributes:
        skill_id: Skill that would be adjusted
        current_threshold: Current threshold value
        proposed_threshold: Proposed new threshold
        current_success_rate: Current positive feedback rate
        simulated_success_rate: Predicted success rate after adjustment
        degradation: Performance degradation risk (0.0-1.0)
        safe: Whether the adjustment is safe to apply
        warnings: List of warning messages
    """
    skill_id: str
    current_threshold: float
    proposed_threshold: float
    current_success_rate: float
    simulated_success_rate: float
    degradation: float = 0.0
    safe: bool = True
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation
        """
        return {
            "skill_id": self.skill_id,
            "current_threshold": self.current_threshold,
            "proposed_threshold": self.proposed_threshold,
            "current_success_rate": self.current_success_rate,
            "simulated_success_rate": self.simulated_success_rate,
            "degradation": self.degradation,
            "safe": self.safe,
            "warnings": self.warnings
        }


class ThresholdAdapter:
    """
    Adaptive threshold calculator and validator.
    
    Calculates new thresholds for skills based on feedback statistics
    using a learning algorithm with confidence weighting.
    
    Algorithm:
        The threshold adjustment uses a gradient-based approach:
        
        new_threshold = current_threshold + alpha * (positive_rate - target_rate) * confidence_factor
        
        - If positive_rate > target_rate: threshold increases (skill is performing well)
        - If positive_rate < target_rate: threshold decreases (skill needs improvement)
        - Confidence factor increases with more samples
    
    Configuration:
        - alpha: Learning rate (default 0.1)
        - target_rate: Target positive feedback rate (default 0.8)
        - min_samples: Minimum samples for adjustment (default 10)
        - max_adjustment: Maximum single adjustment magnitude (default 0.1)
        - min_threshold: Minimum allowed threshold (default 0.3)
        - max_threshold: Maximum allowed threshold (default 0.95)
        - degradation_threshold: Max allowed degradation (default 0.1)
    
    Example:
        >>> adapter = ThresholdAdapter(config, catalog, feedback_store)
        >>> new_threshold = adapter.calculate_new_threshold(skill_id, aggregated)
        >>> result = adapter.dry_run_adjustment(skill_id, new_threshold)
        >>> if result.safe:
        ...     # Apply the adjustment
        ...     pass
    """
    
    # Default configuration values
    DEFAULT_ALPHA = 0.1
    DEFAULT_TARGET_RATE = 0.8
    DEFAULT_MIN_SAMPLES = 10
    DEFAULT_MAX_ADJUSTMENT = 0.1
    DEFAULT_MIN_THRESHOLD = 0.3
    DEFAULT_MAX_THRESHOLD = 0.95
    DEFAULT_DEGRADATION_THRESHOLD = 0.1
    
    def __init__(self, config: Dict[str, Any], catalog: Dict[str, Any],
                 feedback_store: 'FeedbackLoop'):
        """
        Initialize the threshold adapter.
        
        Args:
            config: Configuration dictionary with adapter settings
            catalog: Current skill catalog dictionary
            feedback_store: FeedbackLoop instance for accessing feedback data
        """
        self.config = config
        self.catalog = catalog
        self.feedback_store = feedback_store
        
        # Extract configuration values
        adapter_config = config.get("threshold_adapter", {})
        
        self._alpha = adapter_config.get("alpha", self.DEFAULT_ALPHA)
        self._target_rate = adapter_config.get("target_rate", self.DEFAULT_TARGET_RATE)
        self._min_samples = adapter_config.get("min_samples", self.DEFAULT_MIN_SAMPLES)
        self._max_adjustment = adapter_config.get("max_adjustment", self.DEFAULT_MAX_ADJUSTMENT)
        self._min_threshold = adapter_config.get("min_threshold", self.DEFAULT_MIN_THRESHOLD)
        self._max_threshold = adapter_config.get("max_threshold", self.DEFAULT_MAX_THRESHOLD)
        self._degradation_threshold = adapter_config.get(
            "degradation_threshold", 
            self.DEFAULT_DEGRADATION_THRESHOLD
        )
        
        self._logger = logging.getLogger(__name__)
    
    def calculate_new_threshold(self, skill_id: str, 
                                feedback_stats: 'AggregatedFeedback') -> float:
        """
        Calculate a new threshold for a skill based on feedback.
        
        Uses the learning algorithm to compute an adjusted threshold:
        
        new_threshold = current_threshold + alpha * (positive_rate - target_rate) * confidence_factor
        
        Args:
            skill_id: Skill to calculate threshold for
            feedback_stats: Aggregated feedback statistics
            
        Returns:
            Calculated new threshold value
        """
        # Get current threshold
        current_threshold = self._get_current_threshold(skill_id)
        
        # Calculate sample size for confidence
        sample_size = feedback_stats.thumbs_up_count + feedback_stats.thumbs_down_count
        
        # Calculate confidence factor
        confidence_factor = self._calculate_confidence_factor(sample_size)
        
        # Calculate positive rate
        positive_rate = feedback_stats.positive_rate
        
        # Calculate adjustment
        adjustment = self._alpha * (positive_rate - self._target_rate) * confidence_factor
        
        # Clamp adjustment to maximum
        adjustment = max(-self._max_adjustment, min(self._max_adjustment, adjustment))
        
        # Calculate new threshold
        new_threshold = current_threshold + adjustment
        
        # Clamp to valid range
        new_threshold = max(self._min_threshold, min(self._max_threshold, new_threshold))
        
        self._logger.debug(
            f"Calculated new threshold for {skill_id}: "
            f"current={current_threshold:.3f}, positive_rate={positive_rate:.3f}, "
            f"confidence={confidence_factor:.3f}, adjustment={adjustment:.3f}, "
            f"new={new_threshold:.3f}"
        )
        
        return round(new_threshold, 4)
    
    def _get_current_threshold(self, skill_id: str) -> float:
        """
        Get the current threshold for a skill from the catalog.
        
        Args:
            skill_id: Skill to get threshold for
            
        Returns:
            Current threshold or default value
        """
        skills = self.catalog.get("skills", {})
        skill = skills.get(skill_id, {})
        return skill.get("threshold", 0.7)
    
    def _calculate_confidence_factor(self, sample_size: int) -> float:
        """
        Calculate confidence factor based on sample size.
        
        Formula: sqrt(sample_size / min_samples)
        
        The confidence factor scales the adjustment based on how much
        data we have. More samples = higher confidence = larger adjustments.
        
        Args:
            sample_size: Number of feedback samples
            
        Returns:
            Confidence factor (0.0-1.0)
        """
        if sample_size < self._min_samples:
            # Below minimum samples, scale down confidence
            return math.sqrt(sample_size / self._min_samples)
        
        # At or above minimum samples, cap confidence at 1.0
        # (or allow higher for more confidence if desired)
        return min(1.0, math.sqrt(sample_size / self._min_samples))
    
    def validate_threshold(self, threshold: float, skill_id: str) -> ValidationResult:
        """
        Validate that a threshold is within acceptable bounds.
        
        Checks that the threshold is:
        - A valid number
        - Within the configured min/max range
        - Compatible with the skill's requirements
        
        Args:
            threshold: Threshold value to validate
            skill_id: Skill the threshold is for
            
        Returns:
            ValidationResult indicating if threshold is valid
        """
        # Check if it's a valid number
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            return ValidationResult.INVALID
        
        # Check for NaN or infinity
        if math.isnan(threshold) or math.isinf(threshold):
            return ValidationResult.INVALID
        
        # Check min bound
        if threshold < self._min_threshold:
            return ValidationResult.TOO_LOW
        
        # Check max bound
        if threshold > self._max_threshold:
            return ValidationResult.TOO_HIGH
        
        return ValidationResult.VALID
    
    def dry_run_adjustment(self, skill_id: str, new_threshold: float) -> DryRunResult:
        """
        Simulate a threshold adjustment without applying it.
        
        Provides detailed analysis of what would happen if the
        adjustment were applied, including:
        - Predicted impact on success rate
        - Risk of performance degradation
        - Safety assessment
        - Warning messages
        
        Args:
            skill_id: Skill to simulate adjustment for
            new_threshold: Proposed new threshold
            
        Returns:
            DryRunResult with simulation details
        """
        # Get current threshold
        current_threshold = self._get_current_threshold(skill_id)
        
        # Validate the new threshold
        validation = self.validate_threshold(new_threshold, skill_id)
        
        warnings = []
        safe = True
        
        # Check validation result
        if validation != ValidationResult.VALID:
            safe = False
            warnings.append(f"Threshold validation failed: {validation.value}")
        
        # Calculate current success rate
        current_success_rate = self._estimate_success_rate(skill_id, current_threshold)
        
        # Estimate simulated success rate
        # Higher threshold = stricter filtering = potentially lower success rate
        # Lower threshold = more permissive = potentially higher success rate
        simulated_success_rate = self._simulate_success_rate(
            skill_id, current_threshold, new_threshold
        )
        
        # Calculate degradation risk
        degradation = self._calculate_degradation(
            current_success_rate, simulated_success_rate
        )
        
        # Check for significant degradation
        if degradation > self._degradation_threshold:
            safe = False
            warnings.append(
                f"High degradation risk: {degradation:.1%} "
                f"(threshold: {self._degradation_threshold:.1%})"
            )
        
        # Check for large threshold changes
        threshold_change = abs(new_threshold - current_threshold)
        if threshold_change > self._max_adjustment:
            warnings.append(
                f"Large threshold change: {threshold_change:.3f} "
                f"(max: {self._max_adjustment:.3f})"
            )
        
        # Check for threshold at bounds
        if new_threshold <= self._min_threshold:
            warnings.append(f"Threshold at minimum bound: {self._min_threshold}")
        elif new_threshold >= self._max_threshold:
            warnings.append(f"Threshold at maximum bound: {self._max_threshold}")
        
        return DryRunResult(
            skill_id=skill_id,
            current_threshold=current_threshold,
            proposed_threshold=new_threshold,
            current_success_rate=current_success_rate,
            simulated_success_rate=simulated_success_rate,
            degradation=degradation,
            safe=safe,
            warnings=warnings
        )
    
    def _estimate_success_rate(self, skill_id: str, threshold: float) -> float:
        """
        Estimate the current success rate for a skill.
        
        This is based on the positive feedback rate from users.
        
        Args:
            skill_id: Skill to estimate for
            threshold: Current threshold
            
        Returns:
            Estimated success rate (0.0-1.0)
        """
        # Get feedback stats from the feedback store
        if hasattr(self.feedback_store, 'get_feedback_stats'):
            stats = self.feedback_store.get_feedback_stats(skill_id)
            return stats.get("positive_rate", 0.5)
        
        # Default to 50% if no data available
        return 0.5
    
    def _simulate_success_rate(self, skill_id: str, 
                               current_threshold: float,
                               new_threshold: float) -> float:
        """
        Simulate the success rate after a threshold adjustment.
        
        Uses a simple model where:
        - Higher threshold = stricter filtering = lower false positives but may miss some
        - Lower threshold = more permissive = higher recall but more false positives
        
        Args:
            skill_id: Skill to simulate for
            current_threshold: Current threshold
            new_threshold: Proposed new threshold
            
        Returns:
            Simulated success rate (0.0-1.0)
        """
        # Get current success rate
        current_success_rate = self._estimate_success_rate(skill_id, current_threshold)
        
        # Calculate threshold change
        threshold_delta = new_threshold - current_threshold
        
        # Simple linear model:
        # - Increasing threshold by 0.1 reduces success rate by ~0.05
        # - Decreasing threshold by 0.1 increases success rate by ~0.05
        # This is a simplified model; real behavior depends on skill characteristics
        
        sensitivity = 0.5  # How much threshold changes affect success rate
        
        simulated_rate = current_success_rate - (threshold_delta * sensitivity)
        
        # Clamp to valid range
        return max(0.0, min(1.0, simulated_rate))
    
    def _calculate_degradation(self, current_rate: float, simulated_rate: float) -> float:
        """
        Calculate the degradation risk from a threshold change.
        
        Args:
            current_rate: Current success rate
            simulated_rate: Simulated success rate after change
            
        Returns:
            Degradation value (0.0-1.0)
        """
        if current_rate <= 0:
            return 0.0
        
        # Degradation is the relative decrease in success rate
        if simulated_rate < current_rate:
            return (current_rate - simulated_rate) / current_rate
        
        # No degradation if simulated rate is higher
        return 0.0
    
    def get_adjustment_recommendation(self, skill_id: str) -> Dict[str, Any]:
        """
        Get a recommendation for threshold adjustment.
        
        Provides detailed analysis including:
        - Whether adjustment is recommended
        - Current vs proposed threshold
        - Confidence level
        - Risk assessment
        
        Args:
            skill_id: Skill to get recommendation for
            
        Returns:
            Dictionary with recommendation details
        """
        from datetime import timedelta
        from src.feedback.feedback_loop import AggregatedFeedback
        
        # Get feedback stats
        window = timedelta(days=30)
        if hasattr(self.feedback_store, 'aggregate_feedback'):
            feedback_stats = self.feedback_store.aggregate_feedback(skill_id, window)
        else:
            feedback_stats = AggregatedFeedback(skill_id=skill_id)
        
        # Calculate new threshold
        new_threshold = self.calculate_new_threshold(skill_id, feedback_stats)
        
        # Run dry-run simulation
        dry_run = self.dry_run_adjustment(skill_id, new_threshold)
        
        # Determine sample size confidence
        sample_size = feedback_stats.thumbs_up_count + feedback_stats.thumbs_down_count
        
        if sample_size < self._min_samples:
            confidence = "low"
            recommended = False
        elif sample_size < self._min_samples * 2:
            confidence = "medium"
            recommended = dry_run.safe
        else:
            confidence = "high"
            recommended = dry_run.safe
        
        return {
            "skill_id": skill_id,
            "recommended": recommended,
            "confidence": confidence,
            "sample_size": sample_size,
            "min_samples": self._min_samples,
            "current_threshold": dry_run.current_threshold,
            "proposed_threshold": new_threshold,
            "adjustment_magnitude": abs(new_threshold - dry_run.current_threshold),
            "positive_rate": feedback_stats.positive_rate,
            "target_rate": self._target_rate,
            "dry_run_result": dry_run.to_dict(),
            "warnings": dry_run.warnings
        }
    
    def batch_calculate_thresholds(self, skill_ids: List[str]) -> Dict[str, float]:
        """
        Calculate new thresholds for multiple skills.
        
        Args:
            skill_ids: List of skill IDs to calculate for
            
        Returns:
            Dictionary mapping skill_id to new threshold
        """
        from datetime import timedelta
        from src.feedback.feedback_loop import AggregatedFeedback
        
        results = {}
        window = timedelta(days=30)
        
        for skill_id in skill_ids:
            try:
                # Get feedback stats
                if hasattr(self.feedback_store, 'aggregate_feedback'):
                    feedback_stats = self.feedback_store.aggregate_feedback(skill_id, window)
                else:
                    feedback_stats = AggregatedFeedback(skill_id=skill_id)
                
                # Calculate new threshold
                new_threshold = self.calculate_new_threshold(skill_id, feedback_stats)
                results[skill_id] = new_threshold
                
            except Exception as e:
                self._logger.warning(f"Failed to calculate threshold for {skill_id}: {e}")
                results[skill_id] = self._get_current_threshold(skill_id)
        
        return results
    
    def get_adapter_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the adapter configuration.
        
        Returns:
            Dictionary with adapter statistics
        """
        return {
            "alpha": self._alpha,
            "target_rate": self._target_rate,
            "min_samples": self._min_samples,
            "max_adjustment": self._max_adjustment,
            "min_threshold": self._min_threshold,
            "max_threshold": self._max_threshold,
            "degradation_threshold": self._degradation_threshold,
            "catalog_skills": len(self.catalog.get("skills", {}))
        }
