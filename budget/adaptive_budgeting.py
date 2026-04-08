"""
ITEM-BUD-57: Clarity-Score Adaptive Budgeting.

This module implements adaptive budget management where the clarity score
influences budget allocation per severity level.

PROBLEM: Fixed SEV percentage budgeting. No adaptation to clarity score.
         High clarity wastes budget.

SOLUTION: Implement adaptive budgeting where clarity score influences
          budget allocation per severity.

Allocation Logic:
    clarity >= 0.9:  SEV-1/2: 80%, SEV-3: 15%, SEV-4: 5%
    clarity >= 0.7:  SEV-1/2: 60%, SEV-3: 30%, SEV-4: 10%
    clarity < 0.7:   SEV-1/2: 40%, SEV-3: 40%, SEV-4: 20%

Mode Adjustments:
    - deterministic: +10% to SEV-1/2 (more thorough)
    - fast_prototype: +20% to SEV-4 (quick checks)
    - guided_autonomy: baseline

Author: TITAN FUSE Team
Version: 3.7.1
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, Tuple
import threading
import logging

from src.utils.timezone import now_utc_iso


class ClarityTier(Enum):
    """Clarity score tier for budget allocation."""
    HIGH = "high"        # clarity >= 0.9
    MEDIUM = "medium"    # 0.7 <= clarity < 0.9
    LOW = "low"          # clarity < 0.7


class ModeType(Enum):
    """Operation mode for budget adjustment."""
    DETERMINISTIC = "deterministic"
    FAST_PROTOTYPE = "fast_prototype"
    GUIDED_AUTONOMY = "guided_autonomy"


# Default allocation ratios per clarity tier
DEFAULT_ALLOCATIONS: Dict[ClarityTier, Tuple[float, float, float]] = {
    # (SEV-1/2 ratio, SEV-3 ratio, SEV-4 ratio)
    ClarityTier.HIGH: (0.80, 0.15, 0.05),
    ClarityTier.MEDIUM: (0.60, 0.30, 0.10),
    ClarityTier.LOW: (0.40, 0.40, 0.20),
}

# Mode adjustments (added to base allocation)
MODE_ADJUSTMENTS: Dict[ModeType, Tuple[float, float, float]] = {
    # (SEV-1/2 adjustment, SEV-3 adjustment, SEV-4 adjustment)
    ModeType.DETERMINISTIC: (0.10, -0.05, -0.05),  # +10% to SEV-1/2
    ModeType.FAST_PROTOTYPE: (-0.10, -0.10, 0.20),  # +20% to SEV-4
    ModeType.GUIDED_AUTONOMY: (0.0, 0.0, 0.0),  # No adjustment
}


@dataclass
class BudgetAllocation:
    """
    Budget allocation configuration based on clarity score.

    Represents the allocation ratios for different severity levels
    derived from the clarity score and operation mode.

    Attributes:
        sev_1_2_ratio: Budget ratio for SEV-1 and SEV-2 issues (combined)
        sev_3_ratio: Budget ratio for SEV-3 issues
        sev_4_ratio: Budget ratio for SEV-4 issues
        clarity_score: The clarity score that determined this allocation
        mode: The operation mode for this allocation
        timestamp: When this allocation was created
    """
    sev_1_2_ratio: float
    sev_3_ratio: float
    sev_4_ratio: float
    clarity_score: float
    mode: str
    timestamp: str = field(default_factory=now_utc_iso)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert allocation to dictionary representation.

        Returns:
            Dict containing all allocation fields
        """
        return {
            "sev_1_2_ratio": self.sev_1_2_ratio,
            "sev_3_ratio": self.sev_3_ratio,
            "sev_4_ratio": self.sev_4_ratio,
            "clarity_score": self.clarity_score,
            "mode": self.mode,
            "timestamp": self.timestamp,
        }

    def validate(self) -> bool:
        """
        Validate that allocation ratios sum to 1.0 (with tolerance).

        Returns:
            True if allocation is valid (ratios sum to ~1.0)
        """
        total = self.sev_1_2_ratio + self.sev_3_ratio + self.sev_4_ratio
        return abs(total - 1.0) < 0.001  # Allow small floating point errors

    def get_ratio_for_severity(self, severity: str) -> float:
        """
        Get the budget ratio for a specific severity level.

        Args:
            severity: Severity level (SEV-1, SEV-2, SEV-3, SEV-4)

        Returns:
            Budget ratio for the severity
        """
        severity = severity.upper()
        if severity in ("SEV-1", "SEV-2"):
            return self.sev_1_2_ratio
        elif severity == "SEV-3":
            return self.sev_3_ratio
        elif severity == "SEV-4":
            return self.sev_4_ratio
        else:
            return 0.0


class AdaptiveBudgeter:
    """
    ITEM-BUD-57: Adaptive budget manager based on clarity score.

    Manages budget allocation dynamically based on clarity scores,
    allowing for more efficient resource utilization when clarity
    is high and more conservative allocation when clarity is low.

    Thread-safe implementation for concurrent access.

    Usage:
        budgeter = AdaptiveBudgeter(total_budget=100000)

        # Calculate allocation based on clarity
        allocation = budgeter.calculate_budget(clarity_score=0.85)
        print(f"SEV-1/2: {allocation.sev_1_2_ratio * 100}%")

        # Adjust for mode
        allocation = budgeter.adjust_for_mode("deterministic")

        # Allocate tokens for a specific severity
        success = budgeter.allocate("SEV-1", 1000)

        # Get remaining budget
        remaining = budgeter.get_remaining_budget()
    """

    def __init__(
        self,
        total_budget: int,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the AdaptiveBudgeter.

        Args:
            total_budget: Total token budget available
            config: Optional configuration dictionary with keys:
                - allocations: Custom allocation ratios per clarity tier
                - mode_adjustments: Custom mode adjustments
                - min_allocation: Minimum allocation per severity (default: 0.05)
        """
        self.total_budget = total_budget
        self.config = config or {}
        self._logger = logging.getLogger(__name__)

        # Load custom allocations or use defaults
        self._allocations = self._load_allocations()
        self._mode_adjustments = self._load_mode_adjustments()

        # State
        self._current_allocation: Optional[BudgetAllocation] = None
        self._used_budget: Dict[str, int] = {
            "SEV-1": 0,
            "SEV-2": 0,
            "SEV-3": 0,
            "SEV-4": 0,
        }
        self._total_used = 0
        self._lock = threading.Lock()

        # Minimum allocation threshold
        self._min_allocation = self.config.get("min_allocation", 0.05)

        # Stats tracking
        self._allocation_history: list = []
        self._max_history = 100

    def _load_allocations(self) -> Dict[ClarityTier, Tuple[float, float, float]]:
        """Load allocation ratios from config or use defaults."""
        custom = self.config.get("allocations", {})
        allocations = DEFAULT_ALLOCATIONS.copy()

        for tier_name, ratios in custom.items():
            try:
                tier = ClarityTier(tier_name.lower())
                if len(ratios) == 3:
                    allocations[tier] = tuple(ratios)
            except ValueError:
                self._logger.warning(f"Unknown clarity tier in config: {tier_name}")

        return allocations

    def _load_mode_adjustments(self) -> Dict[ModeType, Tuple[float, float, float]]:
        """Load mode adjustments from config or use defaults."""
        custom = self.config.get("mode_adjustments", {})
        adjustments = MODE_ADJUSTMENTS.copy()

        for mode_name, adj in custom.items():
            try:
                mode = ModeType(mode_name.lower())
                if len(adj) == 3:
                    adjustments[mode] = tuple(adj)
            except ValueError:
                self._logger.warning(f"Unknown mode in config: {mode_name}")

        return adjustments

    def _get_clarity_tier(self, clarity_score: float) -> ClarityTier:
        """
        Determine the clarity tier for a given score.

        Args:
            clarity_score: Clarity score (0.0 to 1.0)

        Returns:
            ClarityTier enum value
        """
        if clarity_score >= 0.9:
            return ClarityTier.HIGH
        elif clarity_score >= 0.7:
            return ClarityTier.MEDIUM
        else:
            return ClarityTier.LOW

    def _clamp_ratios(
        self,
        sev_1_2: float,
        sev_3: float,
        sev_4: float
    ) -> Tuple[float, float, float]:
        """
        Clamp ratios to valid range and ensure they sum to 1.0.

        Args:
            sev_1_2: SEV-1/2 ratio
            sev_3: SEV-3 ratio
            sev_4: SEV-4 ratio

        Returns:
            Normalized tuple of (sev_1_2, sev_3, sev_4)
        """
        # Apply minimum thresholds
        sev_1_2 = max(self._min_allocation, sev_1_2)
        sev_3 = max(self._min_allocation, sev_3)
        sev_4 = max(self._min_allocation, sev_4)

        # Normalize to sum to 1.0
        total = sev_1_2 + sev_3 + sev_4
        if total > 0:
            sev_1_2 = sev_1_2 / total
            sev_3 = sev_3 / total
            sev_4 = sev_4 / total

        return (sev_1_2, sev_3, sev_4)

    def calculate_budget(
        self,
        clarity_score: float,
        mode: Optional[str] = None
    ) -> BudgetAllocation:
        """
        Calculate budget allocation based on clarity score.

        This is the primary method for determining budget allocation.
        It considers both the clarity score and optionally the operation mode.

        Args:
            clarity_score: Clarity score (0.0 to 1.0)
            mode: Optional operation mode for adjustment

        Returns:
            BudgetAllocation with calculated ratios
        """
        # Validate clarity score
        clarity_score = max(0.0, min(1.0, clarity_score))

        # Get base allocation from clarity tier
        tier = self._get_clarity_tier(clarity_score)
        base_sev_1_2, base_sev_3, base_sev_4 = self._allocations[tier]

        # Apply mode adjustment if specified
        if mode:
            try:
                mode_type = ModeType(mode.lower())
                adj_1_2, adj_3, adj_4 = self._mode_adjustments[mode_type]
                sev_1_2 = base_sev_1_2 + adj_1_2
                sev_3 = base_sev_3 + adj_3
                sev_4 = base_sev_4 + adj_4
            except ValueError:
                # Unknown mode, use base allocation
                sev_1_2, sev_3, sev_4 = base_sev_1_2, base_sev_3, base_sev_4
                mode = "guided_autonomy"  # Default mode
        else:
            sev_1_2, sev_3, sev_4 = base_sev_1_2, base_sev_3, base_sev_4
            mode = "guided_autonomy"  # Default mode

        # Clamp and normalize ratios
        sev_1_2, sev_3, sev_4 = self._clamp_ratios(sev_1_2, sev_3, sev_4)

        # Create allocation
        allocation = BudgetAllocation(
            sev_1_2_ratio=sev_1_2,
            sev_3_ratio=sev_3,
            sev_4_ratio=sev_4,
            clarity_score=clarity_score,
            mode=mode
        )

        with self._lock:
            self._current_allocation = allocation
            # Track allocation history
            self._allocation_history.append(allocation.to_dict())
            if len(self._allocation_history) > self._max_history:
                self._allocation_history.pop(0)

        self._logger.debug(
            f"Calculated allocation for clarity={clarity_score:.2f}, "
            f"mode={mode}: SEV-1/2={sev_1_2:.1%}, "
            f"SEV-3={sev_3:.1%}, SEV-4={sev_4:.1%}"
        )

        return allocation

    def adjust_for_mode(self, mode: str) -> BudgetAllocation:
        """
        Adjust current allocation for a specific mode.

        Modifies the base allocation based on the operation mode.
        Requires a current allocation to exist (call calculate_budget first).

        Args:
            mode: Operation mode (deterministic, fast_prototype, guided_autonomy)

        Returns:
            Adjusted BudgetAllocation

        Raises:
            ValueError: If no current allocation exists
        """
        with self._lock:
            if self._current_allocation is None:
                raise ValueError(
                    "No current allocation. Call calculate_budget() first."
                )

            # Get current values
            sev_1_2 = self._current_allocation.sev_1_2_ratio
            sev_3 = self._current_allocation.sev_3_ratio
            sev_4 = self._current_allocation.sev_4_ratio
            clarity_score = self._current_allocation.clarity_score

        try:
            mode_type = ModeType(mode.lower())
            adj_1_2, adj_3, adj_4 = self._mode_adjustments[mode_type]
            sev_1_2 = sev_1_2 + adj_1_2
            sev_3 = sev_3 + adj_3
            sev_4 = sev_4 + adj_4
        except ValueError:
            self._logger.warning(f"Unknown mode: {mode}, using current allocation")
            mode = "guided_autonomy"

        # Clamp and normalize ratios
        sev_1_2, sev_3, sev_4 = self._clamp_ratios(sev_1_2, sev_3, sev_4)

        # Create new allocation
        allocation = BudgetAllocation(
            sev_1_2_ratio=sev_1_2,
            sev_3_ratio=sev_3,
            sev_4_ratio=sev_4,
            clarity_score=clarity_score,
            mode=mode
        )

        with self._lock:
            self._current_allocation = allocation

        return allocation

    def get_remaining_budget(self) -> Dict[str, int]:
        """
        Get remaining budget per severity level.

        Returns:
            Dict with remaining tokens for each severity and total
        """
        with self._lock:
            allocation = self._current_allocation
            used = self._used_budget.copy()
            total_used = self._total_used

        remaining = {
            "SEV-1": 0,
            "SEV-2": 0,
            "SEV-3": 0,
            "SEV-4": 0,
            "total": max(0, self.total_budget - total_used),
        }

        if allocation:
            # Calculate remaining based on allocation ratios
            total_remaining = remaining["total"]

            # SEV-1 and SEV-2 share the same allocation
            sev_1_2_budget = int(self.total_budget * allocation.sev_1_2_ratio)
            sev_3_budget = int(self.total_budget * allocation.sev_3_ratio)
            sev_4_budget = int(self.total_budget * allocation.sev_4_ratio)

            # Split SEV-1/2 budget between them
            remaining["SEV-1"] = max(0, sev_1_2_budget // 2 - used["SEV-1"])
            remaining["SEV-2"] = max(0, sev_1_2_budget // 2 - used["SEV-2"])
            remaining["SEV-3"] = max(0, sev_3_budget - used["SEV-3"])
            remaining["SEV-4"] = max(0, sev_4_budget - used["SEV-4"])

        return remaining

    def allocate(self, severity: str, tokens: int) -> bool:
        """
        Attempt to allocate tokens for a specific severity.

        Checks if the requested tokens are available for the severity
        and deducts them if so.

        Args:
            severity: Severity level (SEV-1, SEV-2, SEV-3, SEV-4)
            tokens: Number of tokens to allocate

        Returns:
            True if allocation succeeded, False if insufficient budget
        """
        severity = severity.upper()
        if severity not in self._used_budget:
            self._logger.warning(f"Unknown severity: {severity}")
            return False

        remaining = self.get_remaining_budget()

        # Check if we have enough remaining budget
        # For SEV-1/SEV-2, check combined remaining
        if severity in ("SEV-1", "SEV-2"):
            available = remaining["SEV-1"] + remaining["SEV-2"]
        else:
            available = remaining[severity]

        if tokens > available:
            self._logger.debug(
                f"Insufficient budget for {severity}: "
                f"requested={tokens}, available={available}"
            )
            return False

        with self._lock:
            self._used_budget[severity] += tokens
            self._total_used += tokens

        return True

    def get_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive budget statistics.

        Returns:
            Dict containing:
            - total_budget: Total budget
            - total_used: Total tokens used
            - remaining: Total remaining
            - usage_by_severity: Tokens used per severity
            - current_allocation: Current allocation details
            - allocation_history: Recent allocation history
        """
        with self._lock:
            allocation = self._current_allocation
            used = self._used_budget.copy()
            total_used = self._total_used
            history = self._allocation_history.copy()

        return {
            "total_budget": self.total_budget,
            "total_used": total_used,
            "remaining": max(0, self.total_budget - total_used),
            "usage_percentage": (total_used / self.total_budget * 100)
                               if self.total_budget > 0 else 0,
            "usage_by_severity": used,
            "current_allocation": allocation.to_dict() if allocation else None,
            "allocation_history_count": len(history),
            "recent_allocations": history[-5:] if history else [],
        }

    def reset(self) -> None:
        """
        Reset budget state.

        Clears all usage tracking and allocation history.
        Total budget is preserved.
        """
        with self._lock:
            self._current_allocation = None
            self._used_budget = {
                "SEV-1": 0,
                "SEV-2": 0,
                "SEV-3": 0,
                "SEV-4": 0,
            }
            self._total_used = 0
            self._allocation_history.clear()

        self._logger.info("AdaptiveBudgeter reset")

    def set_total_budget(self, budget: int) -> None:
        """
        Update total budget.

        Args:
            budget: New total budget
        """
        with self._lock:
            self.total_budget = budget
        self._logger.info(f"Total budget updated to {budget}")

    def get_allocation_for_clarity(self, clarity_score: float) -> BudgetAllocation:
        """
        Get allocation for a clarity score without setting it as current.

        This is a convenience method for previewing allocations.

        Args:
            clarity_score: Clarity score (0.0 to 1.0)

        Returns:
            BudgetAllocation for the given clarity score
        """
        clarity_score = max(0.0, min(1.0, clarity_score))
        tier = self._get_clarity_tier(clarity_score)
        sev_1_2, sev_3, sev_4 = self._allocations[tier]

        return BudgetAllocation(
            sev_1_2_ratio=sev_1_2,
            sev_3_ratio=sev_3,
            sev_4_ratio=sev_4,
            clarity_score=clarity_score,
            mode="guided_autonomy"
        )


# Module-level convenience
_global_budgeter: Optional[AdaptiveBudgeter] = None


def get_budgeter() -> Optional[AdaptiveBudgeter]:
    """Get the global AdaptiveBudgeter instance."""
    return _global_budgeter


def init_budgeter(
    total_budget: int,
    config: Optional[Dict[str, Any]] = None
) -> AdaptiveBudgeter:
    """
    Initialize and set the global AdaptiveBudgeter.

    Args:
        total_budget: Total token budget
        config: Optional configuration dictionary

    Returns:
        The initialized AdaptiveBudgeter
    """
    global _global_budgeter
    _global_budgeter = AdaptiveBudgeter(total_budget=total_budget, config=config)
    return _global_budgeter
