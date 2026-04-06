"""
Dual-Axis Scoring (SIGNAL × READINESS).

Provides unified assessment scoring combining domain volatility
with confidence scores for production readiness evaluation.

Author: TITAN FUSE Team
Version: 3.2.3
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


class SignalStrength(Enum):
    """Signal strength based on domain volatility."""
    WEAK = 1      # High volatility domain
    MODERATE = 2  # Medium volatility domain
    STRONG = 3    # Low volatility domain


class ReadinessTier(Enum):
    """Production readiness tier based on confidence."""
    PRODUCTION_READY = "PRODUCTION_READY"    # confidence >= 0.9
    EXPERIMENTAL = "EXPERIMENTAL"            # confidence >= 0.7
    REVIEW_REQUIRED = "REVIEW_REQUIRED"      # confidence < 0.7


@dataclass
class AssessmentScore:
    """
    Unified assessment score combining signal and readiness.

    The score provides a dual-axis evaluation:
    - Signal: Based on domain volatility (how stable/predictable the domain is)
    - Readiness: Based on confidence (how reliable the results are)

    Combined score = signal_weight * 0.4 + confidence * 0.6
    """
    signal: SignalStrength
    readiness: ReadinessTier
    combined_score: float  # 0.0 - 1.0

    @classmethod
    def calculate(cls, volatility: str, confidence: float) -> 'AssessmentScore':
        """
        Calculate assessment score from volatility and confidence.

        Args:
            volatility: Domain volatility level ('low', 'medium', 'high', 'V0'-'V3')
            confidence: Confidence score (0.0 - 1.0)

        Returns:
            AssessmentScore with signal, readiness, and combined score

        Examples:
            >>> score = AssessmentScore.calculate("low", 0.95)
            >>> score.signal
            <SignalStrength.STRONG: 3>
            >>> score.readiness
            <ReadinessTier.PRODUCTION_READY: 'PRODUCTION_READY'>
        """
        # Map volatility to signal
        signal_map = {
            "low": SignalStrength.STRONG,
            "medium": SignalStrength.MODERATE,
            "high": SignalStrength.WEAK,
            "v0": SignalStrength.STRONG,    # V0: Very stable
            "v1": SignalStrength.STRONG,    # V1: Stable
            "v2": SignalStrength.MODERATE,  # V2: Moderate
            "v3": SignalStrength.WEAK       # V3: Volatile
        }
        signal = signal_map.get(volatility.lower(), SignalStrength.MODERATE)

        # Map confidence to readiness
        if confidence >= 0.9:
            readiness = ReadinessTier.PRODUCTION_READY
        elif confidence >= 0.7:
            readiness = ReadinessTier.EXPERIMENTAL
        else:
            readiness = ReadinessTier.REVIEW_REQUIRED

        # Combined score: signal (40%) + confidence (60%)
        combined = (signal.value / 3.0) * 0.4 + min(confidence, 1.0) * 0.6

        return cls(signal=signal, readiness=readiness, combined_score=combined)

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "signal": self.signal.name,
            "readiness": self.readiness.value,
            "combined_score": round(self.combined_score, 3)
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'AssessmentScore':
        """Create from dictionary."""
        return cls(
            signal=SignalStrength[data["signal"]],
            readiness=ReadinessTier(data["readiness"]),
            combined_score=data["combined_score"]
        )

    def __str__(self) -> str:
        """Human-readable representation."""
        return f"AssessmentScore({self.signal.name}, {self.readiness.value}, {self.combined_score:.2f})"

    def is_production_ready(self) -> bool:
        """Check if score meets production readiness criteria."""
        return (
            self.readiness == ReadinessTier.PRODUCTION_READY and
            self.signal in (SignalStrength.STRONG, SignalStrength.MODERATE)
        )

    def requires_review(self) -> bool:
        """Check if human review is required."""
        return self.readiness == ReadinessTier.REVIEW_REQUIRED


# Convenience functions
def assess(volatility: str, confidence: float) -> AssessmentScore:
    """Quick assessment function."""
    return AssessmentScore.calculate(volatility, confidence)


def is_safe_to_proceed(volatility: str, confidence: float, threshold: float = 0.7) -> bool:
    """Check if it's safe to proceed based on assessment."""
    score = AssessmentScore.calculate(volatility, confidence)
    return score.combined_score >= threshold and not score.requires_review()
