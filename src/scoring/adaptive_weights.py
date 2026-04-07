"""
Adaptive Weight Profiles Engine for TITAN FUSE Protocol.

ITEM-CAT-01: Four-axis scoring with domain-specific weight profiles.

This module implements the Adaptive Weight Profiles Engine that provides
deterministic scoring across four axes:
- TF (Technical Fidelity): Accuracy of technical content
- RS (Reliability Score): Trustworthiness of sources
- DS (Domain Specificity): Relevance to specific domain
- AC (Actionability Coefficient): Practical applicability

Author: TITAN FUSE Team
Version: 3.2.3
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple, Any, Callable
import logging
import math


class WeightProfile(Enum):
    """
    Domain-specific weight profiles for four-axis scoring.

    Each profile defines weights for:
    - TF: Technical Fidelity (0.0 - 1.0 weight)
    - RS: Reliability Score (0.0 - 1.0 weight)
    - DS: Domain Specificity (0.0 - 1.0 weight)
    - AC: Actionability Coefficient (0.0 - 1.0 weight)

    Weights must sum to 1.0 for each profile.

    Profiles:
        TECHNICAL: Optimized for code, engineering, and technical content.
            Heavy emphasis on reliability (RS) and technical accuracy (TF).

        MEDICAL_LEGAL: Optimized for medical and legal domains.
            Highest emphasis on reliability (RS) due to critical accuracy requirements.

        NARRATIVE: Optimized for creative and narrative content.
            Emphasis on domain specificity (DS) and actionability (AC).

        MIXED: Balanced profile for general-purpose use.
            Moderate weights across all axes.
    """

    TECHNICAL = {
        "TF": 0.30,
        "RS": 0.35,
        "DS": 0.25,
        "AC": 0.10,
    }

    MEDICAL_LEGAL = {
        "TF": 0.35,
        "RS": 0.40,
        "DS": 0.15,
        "AC": 0.10,
    }

    NARRATIVE = {
        "TF": 0.25,
        "RS": 0.10,
        "DS": 0.35,
        "AC": 0.30,
    }

    MIXED = {
        "TF": 0.35,
        "RS": 0.25,
        "DS": 0.25,
        "AC": 0.15,
    }

    @property
    def weights(self) -> Dict[str, float]:
        """Return the weight dictionary for this profile."""
        return self.value

    def validate(self) -> bool:
        """
        Validate that weights sum to 1.0.

        Returns:
            True if weights are valid (sum to 1.0 within tolerance)
        """
        total = sum(self.weights.values())
        return math.isclose(total, 1.0, rel_tol=1e-9)


class Decision(Enum):
    """
    Decision outcome for conflict resolution.

    Attributes:
        AUTO_SELECT: Clear winner, no rationale needed (gap >= 2.0)
        RECOMMENDED: Winner with rationale (gap >= 1.0)
        CONDITIONAL: Close call, conditional recommendation (gap < 1.0)
    """

    AUTO_SELECT = "AUTO_SELECT"
    RECOMMENDED = "RECOMMENDED"
    CONDITIONAL = "CONDITIONAL"


@dataclass
class WeightedScore:
    """
    Container for a weighted score with detailed breakdown.

    Attributes:
        score: The final weighted score (0.0 - 10.0)
        profile: The weight profile used
        components: Raw component scores (TF, RS, DS, AC)
        weighted_components: Component scores after weighting
    """

    score: float
    profile: WeightProfile
    components: Dict[str, float]
    weighted_components: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Calculate weighted components if not provided."""
        if not self.weighted_components:
            weights = self.profile.weights
            self.weighted_components = {
                axis: self.components.get(axis, 0.0) * weights.get(axis, 0.0)
                for axis in ["TF", "RS", "DS", "AC"]
            }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "score": self.score,
            "profile": self.profile.name,
            "components": self.components,
            "weighted_components": self.weighted_components,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WeightedScore":
        """Create from dictionary."""
        return cls(
            score=data["score"],
            profile=WeightProfile[data["profile"]],
            components=data["components"],
            weighted_components=data.get("weighted_components", {}),
        )

    def __str__(self) -> str:
        """Human-readable representation."""
        return (
            f"WeightedScore({self.score:.3f}, profile={self.profile.name}, "
            f"TF={self.components.get('TF', 0):.1f}, "
            f"RS={self.components.get('RS', 0):.1f}, "
            f"DS={self.components.get('DS', 0):.1f}, "
            f"AC={self.components.get('AC', 0):.1f})"
        )


@dataclass
class ConflictResolution:
    """
    Result of conflict resolution between two scores.

    Attributes:
        decision: The decision type (AUTO_SELECT, RECOMMENDED, CONDITIONAL)
        winner_score: The winning score (or higher score for CONDITIONAL)
        loser_score: The losing score (or lower score for CONDITIONAL)
        gap: The absolute difference between scores
        rationale: Explanation for the decision (None for AUTO_SELECT)
        recommended_action: Suggested next step for CONDITIONAL decisions
    """

    decision: Decision
    winner_score: WeightedScore
    loser_score: WeightedScore
    gap: float
    rationale: Optional[str] = None
    recommended_action: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "decision": self.decision.value,
            "winner_score": self.winner_score.to_dict(),
            "loser_score": self.loser_score.to_dict(),
            "gap": round(self.gap, 3),
            "rationale": self.rationale,
            "recommended_action": self.recommended_action,
        }

    def is_auto_select(self) -> bool:
        """Check if decision is an automatic selection."""
        return self.decision == Decision.AUTO_SELECT

    def requires_review(self) -> bool:
        """Check if human review is recommended."""
        return self.decision == Decision.CONDITIONAL


# Default weight profiles dictionary for easy lookup
DEFAULT_WEIGHT_PROFILES: Dict[str, WeightProfile] = {
    "TECHNICAL": WeightProfile.TECHNICAL,
    "MEDICAL_LEGAL": WeightProfile.MEDICAL_LEGAL,
    "NARRATIVE": WeightProfile.NARRATIVE,
    "MIXED": WeightProfile.MIXED,
}


class AdaptiveWeightEngine:
    """
    Adaptive Weight Profiles Engine for four-axis scoring.

    This engine provides deterministic scoring using domain-specific
    weight profiles and conflict resolution with threshold-based decisions.

    Scoring Formula:
        score = (TF × w_TF) + (RS × w_RS) + (DS × w_DS) + (AC × w_AC)

    Where w_TF, w_RS, w_DS, w_AC are weights from the selected profile.

    Conflict Resolution Thresholds:
        - gap >= 2.0: AUTO_SELECT (clear winner, no rationale)
        - gap >= 1.0: RECOMMENDED (winner with one-sentence rationale)
        - gap < 1.0: CONDITIONAL (requires additional consideration)

    Usage:
        engine = AdaptiveWeightEngine()

        # Calculate score
        score = engine.calculate_score(
            tf=8.5, rs=7.2, ds=6.0, ac=9.0,
            profile=WeightProfile.TECHNICAL
        )

        # Resolve conflict
        resolution = engine.resolve_conflict(score_a, score_b)

    Integration with Guardian:
        The engine provides hooks for validation loop integration:
        - register_guardian_callback(): Set callback for validation
        - validate_score(): Trigger validation with guardian
    """

    # Threshold constants for conflict resolution
    THRESHOLD_AUTO_SELECT = 2.0
    THRESHOLD_RECOMMENDED = 1.0

    def __init__(self, default_profile: Optional[WeightProfile] = None) -> None:
        """
        Initialize the Adaptive Weight Engine.

        Args:
            default_profile: Default profile to use if not specified
                           in calculate_score. Defaults to MIXED.
        """
        self._default_profile = default_profile or WeightProfile.MIXED
        self._logger = logging.getLogger(__name__)
        self._guardian_callback: Optional[Callable[[WeightedScore], bool]] = None

        # Validate all profiles on initialization
        self._validate_profiles()

    def _validate_profiles(self) -> None:
        """Validate that all weight profiles are properly configured."""
        for profile in WeightProfile:
            if not profile.validate():
                raise ValueError(
                    f"Invalid weight profile {profile.name}: "
                    f"weights do not sum to 1.0"
                )
        self._logger.debug("All weight profiles validated successfully")

    @property
    def default_profile(self) -> WeightProfile:
        """Get the default weight profile."""
        return self._default_profile

    @default_profile.setter
    def default_profile(self, profile: WeightProfile) -> None:
        """Set the default weight profile."""
        self._default_profile = profile
        self._logger.debug(f"Default profile set to: {profile.name}")

    def calculate_score(
        self,
        tf: float,
        rs: float,
        ds: float,
        ac: float,
        profile: Optional[WeightProfile] = None,
    ) -> float:
        """
        Calculate weighted score from four-axis components.

        The scoring formula is:
            score = (TF × w_TF) + (RS × w_RS) + (DS × w_DS) + (AC × w_AC)

        Scores are deterministically rounded to 3 decimal places.

        Args:
            tf: Technical Fidelity score (0.0 - 10.0)
            rs: Reliability Score (0.0 - 10.0)
            ds: Domain Specificity score (0.0 - 10.0)
            ac: Actionability Coefficient (0.0 - 10.0)
            profile: Weight profile to use. Defaults to engine's default profile.

        Returns:
            Weighted score rounded to 3 decimal places (0.0 - 10.0)

        Raises:
            ValueError: If any score is outside the valid range

        Example:
            >>> engine = AdaptiveWeightEngine()
            >>> engine.calculate_score(8.5, 7.2, 6.0, 9.0, WeightProfile.TECHNICAL)
            7.505
        """
        # Use default profile if not specified
        active_profile = profile or self._default_profile

        # Validate inputs
        self._validate_score_range(tf, "TF")
        self._validate_score_range(rs, "RS")
        self._validate_score_range(ds, "DS")
        self._validate_score_range(ac, "AC")

        weights = active_profile.weights

        # Apply formula: (TF × w_TF) + (RS × w_RS) + (DS × w_DS) + (AC × w_AC)
        weighted_score = (
            (tf * weights["TF"])
            + (rs * weights["RS"])
            + (ds * weights["DS"])
            + (ac * weights["AC"])
        )

        # Deterministic rounding to 3 decimal places
        rounded_score = round(weighted_score, 3)

        self._logger.debug(
            f"Calculated score: {rounded_score:.3f} "
            f"(TF={tf:.1f}×{weights['TF']:.2f}, "
            f"RS={rs:.1f}×{weights['RS']:.2f}, "
            f"DS={ds:.1f}×{weights['DS']:.2f}, "
            f"AC={ac:.1f}×{weights['AC']:.2f}) "
            f"profile={active_profile.name}"
        )

        return rounded_score

    def calculate_score_detailed(
        self,
        tf: float,
        rs: float,
        ds: float,
        ac: float,
        profile: Optional[WeightProfile] = None,
    ) -> WeightedScore:
        """
        Calculate weighted score with detailed breakdown.

        Same as calculate_score but returns a WeightedScore object
        with component breakdown for analysis.

        Args:
            tf: Technical Fidelity score (0.0 - 10.0)
            rs: Reliability Score (0.0 - 10.0)
            ds: Domain Specificity score (0.0 - 10.0)
            ac: Actionability Coefficient (0.0 - 10.0)
            profile: Weight profile to use

        Returns:
            WeightedScore object with full breakdown
        """
        active_profile = profile or self._default_profile

        score = self.calculate_score(tf, rs, ds, ac, active_profile)

        return WeightedScore(
            score=score,
            profile=active_profile,
            components={"TF": tf, "RS": rs, "DS": ds, "AC": ac},
        )

    def _validate_score_range(self, score: float, name: str) -> None:
        """
        Validate that a score is within valid range.

        Args:
            score: The score to validate
            name: Name of the score component for error messages

        Raises:
            ValueError: If score is outside valid range
        """
        if not 0.0 <= score <= 10.0:
            raise ValueError(
                f"Invalid {name} score: {score}. "
                f"Must be between 0.0 and 10.0"
            )

    def resolve_conflict(
        self,
        score_a: WeightedScore,
        score_b: WeightedScore,
    ) -> ConflictResolution:
        """
        Resolve conflict between two weighted scores.

        Uses threshold-based decision making:
        - gap >= 2.0: AUTO_SELECT - Clear winner, no rationale needed
        - gap >= 1.0: RECOMMENDED - Winner with one-sentence rationale
        - gap < 1.0: CONDITIONAL - Close call, requires additional consideration

        Args:
            score_a: First weighted score
            score_b: Second weighted score

        Returns:
            ConflictResolution with decision and rationale

        Example:
            >>> engine = AdaptiveWeightEngine()
            >>> score_a = WeightedScore(8.5, WeightProfile.TECHNICAL, {})
            >>> score_b = WeightedScore(6.0, WeightProfile.TECHNICAL, {})
            >>> resolution = engine.resolve_conflict(score_a, score_b)
            >>> resolution.decision
            <Decision.AUTO_SELECT: 'AUTO_SELECT'>
        """
        gap = abs(score_a.score - score_b.score)

        # Determine winner and loser
        if score_a.score >= score_b.score:
            winner, loser = score_a, score_b
        else:
            winner, loser = score_b, score_a

        self._logger.debug(
            f"Resolving conflict: score_a={score_a.score:.3f}, "
            f"score_b={score_b.score:.3f}, gap={gap:.3f}"
        )

        # Apply thresholds
        if gap >= self.THRESHOLD_AUTO_SELECT:
            # Clear winner - no rationale needed
            decision = Decision.AUTO_SELECT
            rationale = None
            recommended_action = None

            self._logger.info(
                f"[conflict_resolution] AUTO_SELECT: "
                f"winner={winner.score:.3f}, gap={gap:.3f} >= {self.THRESHOLD_AUTO_SELECT}"
            )

        elif gap >= self.THRESHOLD_RECOMMENDED:
            # Winner with rationale
            decision = Decision.RECOMMENDED
            rationale = self._generate_rationale(winner, loser, gap)
            recommended_action = None

            self._logger.info(
                f"[conflict_resolution] RECOMMENDED: "
                f"winner={winner.score:.3f}, gap={gap:.3f} >= {self.THRESHOLD_RECOMMENDED}"
            )

        else:
            # Close call - conditional recommendation
            decision = Decision.CONDITIONAL
            rationale = self._generate_rationale(winner, loser, gap)
            recommended_action = self._generate_conditional_action(winner, loser, gap)

            self._logger.warning(
                f"[conflict_resolution] CONDITIONAL: "
                f"winner={winner.score:.3f}, gap={gap:.3f} < {self.THRESHOLD_RECOMMENDED} "
                f"- human review recommended"
            )

        return ConflictResolution(
            decision=decision,
            winner_score=winner,
            loser_score=loser,
            gap=gap,
            rationale=rationale,
            recommended_action=recommended_action,
        )

    def _generate_rationale(
        self,
        winner: WeightedScore,
        loser: WeightedScore,
        gap: float,
    ) -> str:
        """
        Generate one-sentence rationale for the decision.

        Args:
            winner: The winning score
            loser: The losing score
            gap: The score difference

        Returns:
            One-sentence rationale string
        """
        # Identify the key differentiating axis
        winner_components = winner.components
        loser_components = loser.components

        differences = {
            axis: winner_components.get(axis, 0) - loser_components.get(axis, 0)
            for axis in ["TF", "RS", "DS", "AC"]
        }

        # Find the axis with largest positive difference
        key_axis = max(differences, key=lambda x: abs(differences[x]))
        axis_names = {
            "TF": "Technical Fidelity",
            "RS": "Reliability Score",
            "DS": "Domain Specificity",
            "AC": "Actionability Coefficient",
        }

        return (
            f"Option A leads by {gap:.2f} points, primarily due to higher "
            f"{axis_names[key_axis]} ({winner_components.get(key_axis, 0):.1f} vs "
            f"{loser_components.get(key_axis, 0):.1f})."
        )

    def _generate_conditional_action(
        self,
        winner: WeightedScore,
        loser: WeightedScore,
        gap: float,
    ) -> str:
        """
        Generate recommended action for conditional decisions.

        Args:
            winner: The higher score
            loser: The lower score
            gap: The score difference

        Returns:
            Recommended action string
        """
        return (
            f"Scores are within {self.THRESHOLD_RECOMMENDED:.1f} point threshold "
            f"(gap: {gap:.3f}). Consider human review or additional evaluation "
            f"before making final decision."
        )

    # =========================================================================
    # Guardian Integration Interface
    # =========================================================================

    def register_guardian_callback(
        self,
        callback: Callable[[WeightedScore], bool],
    ) -> None:
        """
        Register a guardian callback for validation integration.

        The guardian callback is invoked during score validation to
        enable the validation loop to check scores against guardian rules.

        Args:
            callback: Function that takes a WeightedScore and returns
                     True if validation passes, False otherwise.

        Example:
            >>> def my_guardian(score: WeightedScore) -> bool:
            ...     return score.score >= 7.0
            >>> engine.register_guardian_callback(my_guardian)
        """
        self._guardian_callback = callback
        self._logger.info("Guardian callback registered for validation integration")

    def validate_score(
        self,
        score: WeightedScore,
        strict: bool = False,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate a score using the registered guardian callback.

        This method provides integration with the validation loop,
        allowing guardian checks on calculated scores.

        Args:
            score: The weighted score to validate
            strict: If True, raise exception on missing callback

        Returns:
            Tuple of (is_valid, error_message)

        Raises:
            RuntimeError: If strict=True and no callback is registered
        """
        if self._guardian_callback is None:
            if strict:
                raise RuntimeError(
                    "No guardian callback registered. "
                    "Call register_guardian_callback() first."
                )
            self._logger.warning(
                "validate_score called without guardian callback - returning True"
            )
            return True, None

        try:
            is_valid = self._guardian_callback(score)
            if is_valid:
                self._logger.debug(
                    f"Score validation passed: {score.score:.3f}"
                )
                return True, None
            else:
                error_msg = f"Guardian validation failed for score {score.score:.3f}"
                self._logger.warning(error_msg)
                return False, error_msg

        except Exception as e:
            error_msg = f"Guardian callback raised exception: {e}"
            self._logger.error(error_msg)
            return False, error_msg

    def calculate_and_validate(
        self,
        tf: float,
        rs: float,
        ds: float,
        ac: float,
        profile: Optional[WeightProfile] = None,
    ) -> Tuple[WeightedScore, bool, Optional[str]]:
        """
        Calculate score and validate with guardian in one operation.

        Convenience method for the validation loop integration.

        Args:
            tf: Technical Fidelity score
            rs: Reliability Score
            ds: Domain Specificity score
            ac: Actionability Coefficient
            profile: Weight profile to use

        Returns:
            Tuple of (weighted_score, is_valid, error_message)
        """
        score = self.calculate_score_detailed(tf, rs, ds, ac, profile)
        is_valid, error = self.validate_score(score)
        return score, is_valid, error

    def get_profile_weights(
        self,
        profile: Optional[WeightProfile] = None,
    ) -> Dict[str, float]:
        """
        Get the weights for a specific profile.

        Args:
            profile: Weight profile. Defaults to engine's default.

        Returns:
            Dictionary of axis weights
        """
        active_profile = profile or self._default_profile
        return active_profile.weights.copy()

    def list_profiles(self) -> Dict[str, Dict[str, float]]:
        """
        List all available weight profiles.

        Returns:
            Dictionary mapping profile names to their weights
        """
        return {
            profile.name: profile.weights.copy()
            for profile in WeightProfile
        }


# =============================================================================
# Convenience Factory Function
# =============================================================================

def create_weight_engine(
    default_profile: str = "MIXED",
    guardian_callback: Optional[Callable[[WeightedScore], bool]] = None,
) -> AdaptiveWeightEngine:
    """
    Factory function to create an AdaptiveWeightEngine.

    Args:
        default_profile: Name of default profile ("TECHNICAL", "MEDICAL_LEGAL",
                        "NARRATIVE", or "MIXED"). Defaults to "MIXED".
        guardian_callback: Optional guardian callback for validation

    Returns:
        Configured AdaptiveWeightEngine instance

    Raises:
        ValueError: If default_profile name is invalid

    Example:
        >>> engine = create_weight_engine("TECHNICAL")
        >>> engine.calculate_score(8.0, 7.5, 6.0, 9.0)
        7.425
    """
    profile = DEFAULT_WEIGHT_PROFILES.get(default_profile.upper())
    if profile is None:
        valid_names = ", ".join(DEFAULT_WEIGHT_PROFILES.keys())
        raise ValueError(
            f"Invalid profile name '{default_profile}'. "
            f"Valid profiles: {valid_names}"
        )

    engine = AdaptiveWeightEngine(default_profile=profile)

    if guardian_callback is not None:
        engine.register_guardian_callback(guardian_callback)

    return engine
