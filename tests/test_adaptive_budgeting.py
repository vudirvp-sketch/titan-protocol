"""
Tests for ITEM-BUD-57: Clarity-Score Adaptive Budgeting.

Tests validate:
- Adaptive allocation based on clarity score
- Mode adjustments produce different allocations
- Budget tracking and allocation
- Thread safety
- Validation criteria

Author: TITAN FUSE Team
Version: 3.7.1
"""

import pytest
import threading
from concurrent.futures import ThreadPoolExecutor

from budget.adaptive_budgeting import (
    BudgetAllocation,
    AdaptiveBudgeter,
    ClarityTier,
    ModeType,
    DEFAULT_ALLOCATIONS,
    MODE_ADJUSTMENTS,
    init_budgeter,
    get_budgeter,
)


class TestBudgetAllocation:
    """Tests for BudgetAllocation dataclass."""

    def test_budget_allocation_creation(self):
        """Test basic BudgetAllocation creation."""
        allocation = BudgetAllocation(
            sev_1_2_ratio=0.6,
            sev_3_ratio=0.3,
            sev_4_ratio=0.1,
            clarity_score=0.75,
            mode="guided_autonomy"
        )

        assert allocation.sev_1_2_ratio == 0.6
        assert allocation.sev_3_ratio == 0.3
        assert allocation.sev_4_ratio == 0.1
        assert allocation.clarity_score == 0.75
        assert allocation.mode == "guided_autonomy"
        assert allocation.timestamp is not None

    def test_budget_allocation_validate_valid(self):
        """Test validation with valid allocation."""
        allocation = BudgetAllocation(
            sev_1_2_ratio=0.6,
            sev_3_ratio=0.3,
            sev_4_ratio=0.1,
            clarity_score=0.75,
            mode="guided_autonomy"
        )

        assert allocation.validate() is True

    def test_budget_allocation_validate_invalid(self):
        """Test validation with invalid allocation (not summing to 1.0)."""
        allocation = BudgetAllocation(
            sev_1_2_ratio=0.5,
            sev_3_ratio=0.3,
            sev_4_ratio=0.1,  # Total = 0.9
            clarity_score=0.75,
            mode="guided_autonomy"
        )

        assert allocation.validate() is False

    def test_budget_allocation_to_dict(self):
        """Test to_dict method."""
        allocation = BudgetAllocation(
            sev_1_2_ratio=0.6,
            sev_3_ratio=0.3,
            sev_4_ratio=0.1,
            clarity_score=0.75,
            mode="guided_autonomy"
        )

        d = allocation.to_dict()

        assert d["sev_1_2_ratio"] == 0.6
        assert d["sev_3_ratio"] == 0.3
        assert d["sev_4_ratio"] == 0.1
        assert d["clarity_score"] == 0.75
        assert d["mode"] == "guided_autonomy"
        assert "timestamp" in d

    def test_get_ratio_for_severity(self):
        """Test getting ratio for specific severity."""
        allocation = BudgetAllocation(
            sev_1_2_ratio=0.6,
            sev_3_ratio=0.3,
            sev_4_ratio=0.1,
            clarity_score=0.75,
            mode="guided_autonomy"
        )

        assert allocation.get_ratio_for_severity("SEV-1") == 0.6
        assert allocation.get_ratio_for_severity("SEV-2") == 0.6
        assert allocation.get_ratio_for_severity("SEV-3") == 0.3
        assert allocation.get_ratio_for_severity("SEV-4") == 0.1
        assert allocation.get_ratio_for_severity("SEV-5") == 0.0
        assert allocation.get_ratio_for_severity("sev-1") == 0.6  # Case insensitive


class TestAdaptiveBudgeter:
    """Tests for AdaptiveBudgeter class."""

    def test_init(self):
        """Test AdaptiveBudgeter initialization."""
        budgeter = AdaptiveBudgeter(total_budget=100000)

        assert budgeter.total_budget == 100000
        assert budgeter._current_allocation is None
        assert budgeter._total_used == 0

    def test_init_with_config(self):
        """Test initialization with custom config."""
        config = {
            "allocations": {
                "high": (0.85, 0.10, 0.05),
            },
            "min_allocation": 0.03
        }
        budgeter = AdaptiveBudgeter(total_budget=100000, config=config)

        assert budgeter._min_allocation == 0.03
        assert budgeter._allocations[ClarityTier.HIGH] == (0.85, 0.10, 0.05)

    def test_calculate_budget_high_clarity(self):
        """Test budget calculation with high clarity (>= 0.9)."""
        budgeter = AdaptiveBudgeter(total_budget=100000)
        allocation = budgeter.calculate_budget(clarity_score=0.95)

        assert allocation.clarity_score == 0.95
        # High clarity: SEV-1/2: 80%, SEV-3: 15%, SEV-4: 5%
        assert allocation.sev_1_2_ratio == pytest.approx(0.80, rel=0.01)
        assert allocation.sev_3_ratio == pytest.approx(0.15, rel=0.01)
        assert allocation.sev_4_ratio == pytest.approx(0.05, rel=0.01)
        assert allocation.validate() is True

    def test_calculate_budget_medium_clarity(self):
        """Test budget calculation with medium clarity (0.7-0.9)."""
        budgeter = AdaptiveBudgeter(total_budget=100000)
        allocation = budgeter.calculate_budget(clarity_score=0.75)

        assert allocation.clarity_score == 0.75
        # Medium clarity: SEV-1/2: 60%, SEV-3: 30%, SEV-4: 10%
        assert allocation.sev_1_2_ratio == pytest.approx(0.60, rel=0.01)
        assert allocation.sev_3_ratio == pytest.approx(0.30, rel=0.01)
        assert allocation.sev_4_ratio == pytest.approx(0.10, rel=0.01)
        assert allocation.validate() is True

    def test_calculate_budget_low_clarity(self):
        """Test budget calculation with low clarity (< 0.7)."""
        budgeter = AdaptiveBudgeter(total_budget=100000)
        allocation = budgeter.calculate_budget(clarity_score=0.5)

        assert allocation.clarity_score == 0.5
        # Low clarity: SEV-1/2: 40%, SEV-3: 40%, SEV-4: 20%
        assert allocation.sev_1_2_ratio == pytest.approx(0.40, rel=0.01)
        assert allocation.sev_3_ratio == pytest.approx(0.40, rel=0.01)
        assert allocation.sev_4_ratio == pytest.approx(0.20, rel=0.01)
        assert allocation.validate() is True

    def test_calculate_budget_boundary_values(self):
        """Test budget calculation at boundary values."""
        budgeter = AdaptiveBudgeter(total_budget=100000)

        # Test at exactly 0.9 (should be HIGH tier)
        allocation = budgeter.calculate_budget(clarity_score=0.9)
        assert allocation.sev_1_2_ratio == pytest.approx(0.80, rel=0.01)

        # Test at exactly 0.7 (should be MEDIUM tier)
        allocation = budgeter.calculate_budget(clarity_score=0.7)
        assert allocation.sev_1_2_ratio == pytest.approx(0.60, rel=0.01)

        # Test at just below 0.7 (should be LOW tier)
        allocation = budgeter.calculate_budget(clarity_score=0.699)
        assert allocation.sev_1_2_ratio == pytest.approx(0.40, rel=0.01)

    def test_calculate_budget_clamps_score(self):
        """Test that clarity score is clamped to valid range."""
        budgeter = AdaptiveBudgeter(total_budget=100000)

        # Test over 1.0
        allocation = budgeter.calculate_budget(clarity_score=1.5)
        assert allocation.clarity_score == 1.0

        # Test under 0.0
        allocation = budgeter.calculate_budget(clarity_score=-0.5)
        assert allocation.clarity_score == 0.0

    def test_calculate_budget_with_mode_deterministic(self):
        """Test budget calculation with deterministic mode."""
        budgeter = AdaptiveBudgeter(total_budget=100000)
        allocation = budgeter.calculate_budget(
            clarity_score=0.75,
            mode="deterministic"
        )

        # Deterministic adds 10% to SEV-1/2
        # Base: 60%, 30%, 10% -> Adjusted: 70%, 25%, 5%
        assert allocation.sev_1_2_ratio == pytest.approx(0.70, rel=0.01)
        assert allocation.mode == "deterministic"

    def test_calculate_budget_with_mode_fast_prototype(self):
        """Test budget calculation with fast_prototype mode."""
        budgeter = AdaptiveBudgeter(total_budget=100000)
        allocation = budgeter.calculate_budget(
            clarity_score=0.75,
            mode="fast_prototype"
        )

        # Fast prototype adds 20% to SEV-4
        # Base: 60%, 30%, 10% -> Adjusted: 50%, 20%, 30%
        assert allocation.sev_4_ratio == pytest.approx(0.30, rel=0.01)
        assert allocation.mode == "fast_prototype"

    def test_adjust_for_mode(self):
        """Test mode adjustment on existing allocation."""
        budgeter = AdaptiveBudgeter(total_budget=100000)

        # First calculate base allocation
        budgeter.calculate_budget(clarity_score=0.75)

        # Then adjust for mode
        allocation = budgeter.adjust_for_mode("deterministic")

        # Should have deterministic adjustment
        assert allocation.sev_1_2_ratio == pytest.approx(0.70, rel=0.01)
        assert allocation.mode == "deterministic"

    def test_adjust_for_mode_without_allocation_raises(self):
        """Test that adjust_for_mode raises without current allocation."""
        budgeter = AdaptiveBudgeter(total_budget=100000)

        with pytest.raises(ValueError, match="No current allocation"):
            budgeter.adjust_for_mode("deterministic")

    def test_allocate_success(self):
        """Test successful token allocation."""
        budgeter = AdaptiveBudgeter(total_budget=100000)
        budgeter.calculate_budget(clarity_score=0.75)

        success = budgeter.allocate("SEV-1", 1000)
        assert success is True

        remaining = budgeter.get_remaining_budget()
        assert remaining["total"] == 99000

    def test_allocate_insufficient_budget(self):
        """Test allocation with insufficient budget."""
        budgeter = AdaptiveBudgeter(total_budget=100)
        budgeter.calculate_budget(clarity_score=0.75)

        # Try to allocate more than available
        success = budgeter.allocate("SEV-1", 200)
        assert success is False

    def test_allocate_unknown_severity(self):
        """Test allocation with unknown severity."""
        budgeter = AdaptiveBudgeter(total_budget=100000)
        budgeter.calculate_budget(clarity_score=0.75)

        success = budgeter.allocate("SEV-5", 100)
        assert success is False

    def test_get_remaining_budget(self):
        """Test remaining budget calculation."""
        budgeter = AdaptiveBudgeter(total_budget=100000)
        budgeter.calculate_budget(clarity_score=0.75)  # 60%, 30%, 10%

        remaining = budgeter.get_remaining_budget()

        assert remaining["total"] == 100000
        # SEV-1/2 get half each of 60% = 30% each
        assert remaining["SEV-1"] == 30000
        assert remaining["SEV-2"] == 30000
        assert remaining["SEV-3"] == 30000
        assert remaining["SEV-4"] == 10000

    def test_get_remaining_budget_after_allocation(self):
        """Test remaining budget after allocations."""
        budgeter = AdaptiveBudgeter(total_budget=100000)
        budgeter.calculate_budget(clarity_score=0.75)

        budgeter.allocate("SEV-1", 10000)
        budgeter.allocate("SEV-3", 5000)

        remaining = budgeter.get_remaining_budget()

        assert remaining["total"] == 85000
        assert remaining["SEV-1"] == 20000  # 30000 - 10000
        assert remaining["SEV-3"] == 25000  # 30000 - 5000

    def test_get_stats(self):
        """Test statistics retrieval."""
        budgeter = AdaptiveBudgeter(total_budget=100000)
        budgeter.calculate_budget(clarity_score=0.75)
        budgeter.allocate("SEV-1", 1000)

        stats = budgeter.get_stats()

        assert stats["total_budget"] == 100000
        assert stats["total_used"] == 1000
        assert stats["remaining"] == 99000
        assert stats["usage_by_severity"]["SEV-1"] == 1000
        assert stats["current_allocation"] is not None

    def test_reset(self):
        """Test reset functionality."""
        budgeter = AdaptiveBudgeter(total_budget=100000)
        budgeter.calculate_budget(clarity_score=0.75)
        budgeter.allocate("SEV-1", 1000)

        budgeter.reset()

        assert budgeter._current_allocation is None
        assert budgeter._total_used == 0
        assert budgeter._used_budget["SEV-1"] == 0

    def test_set_total_budget(self):
        """Test updating total budget."""
        budgeter = AdaptiveBudgeter(total_budget=100000)

        budgeter.set_total_budget(200000)

        assert budgeter.total_budget == 200000

    def test_get_allocation_for_clarity(self):
        """Test preview allocation without setting current."""
        budgeter = AdaptiveBudgeter(total_budget=100000)

        allocation = budgeter.get_allocation_for_clarity(0.95)

        assert allocation.sev_1_2_ratio == pytest.approx(0.80, rel=0.01)
        # Current allocation should still be None
        assert budgeter._current_allocation is None


class TestModeAdjustments:
    """Tests for mode-specific adjustments."""

    def test_deterministic_mode_increases_sev_1_2(self):
        """Test that deterministic mode increases SEV-1/2 allocation."""
        budgeter = AdaptiveBudgeter(total_budget=100000)

        base = budgeter.calculate_budget(clarity_score=0.75)
        adjusted = budgeter.adjust_for_mode("deterministic")

        # Deterministic should increase SEV-1/2
        assert adjusted.sev_1_2_ratio > base.sev_1_2_ratio

    def test_fast_prototype_increases_sev_4(self):
        """Test that fast_prototype mode increases SEV-4 allocation."""
        budgeter = AdaptiveBudgeter(total_budget=100000)

        base = budgeter.calculate_budget(clarity_score=0.75)
        adjusted = budgeter.adjust_for_mode("fast_prototype")

        # Fast prototype should increase SEV-4
        assert adjusted.sev_4_ratio > base.sev_4_ratio

    def test_modes_differ(self):
        """VALIDATION CRITERION: Different modes have different allocations."""
        budgeter = AdaptiveBudgeter(total_budget=100000)

        alloc_det = budgeter.calculate_budget(clarity_score=0.75, mode="deterministic")
        alloc_fast = budgeter.calculate_budget(clarity_score=0.75, mode="fast_prototype")
        alloc_guided = budgeter.calculate_budget(clarity_score=0.75, mode="guided_autonomy")

        # All three should be different
        assert alloc_det.to_dict() != alloc_fast.to_dict()
        assert alloc_det.to_dict() != alloc_guided.to_dict()
        assert alloc_fast.to_dict() != alloc_guided.to_dict()

        # Specifically check SEV-1/2 ratios differ
        assert alloc_det.sev_1_2_ratio != alloc_fast.sev_1_2_ratio
        assert alloc_det.sev_1_2_ratio != alloc_guided.sev_1_2_ratio


class TestAdaptiveAllocation:
    """Tests for adaptive allocation based on clarity."""

    def test_budget_adapts_to_clarity(self):
        """VALIDATION CRITERION: Budget adapts to clarity."""
        budgeter = AdaptiveBudgeter(total_budget=100000)

        high_clarity = budgeter.calculate_budget(clarity_score=0.95)
        medium_clarity = budgeter.calculate_budget(clarity_score=0.75)
        low_clarity = budgeter.calculate_budget(clarity_score=0.5)

        # SEV-1/2 should decrease as clarity decreases
        assert high_clarity.sev_1_2_ratio > medium_clarity.sev_1_2_ratio
        assert medium_clarity.sev_1_2_ratio > low_clarity.sev_1_2_ratio

        # SEV-4 should increase as clarity decreases
        assert low_clarity.sev_4_ratio > medium_clarity.sev_4_ratio
        assert medium_clarity.sev_4_ratio > high_clarity.sev_4_ratio

    def test_high_clarity_efficiency(self):
        """Test that high clarity allocates more to critical issues."""
        budgeter = AdaptiveBudgeter(total_budget=100000)

        allocation = budgeter.calculate_budget(clarity_score=0.95)

        # High clarity should focus on SEV-1/2
        assert allocation.sev_1_2_ratio >= 0.75

    def test_low_clarity_conservative(self):
        """Test that low clarity uses more conservative allocation."""
        budgeter = AdaptiveBudgeter(total_budget=100000)

        allocation = budgeter.calculate_budget(clarity_score=0.5)

        # Low clarity should spread budget more evenly
        assert allocation.sev_4_ratio >= 0.15
        assert allocation.sev_3_ratio >= 0.35


class TestThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_allocate(self):
        """Test concurrent allocation is thread-safe."""
        budgeter = AdaptiveBudgeter(total_budget=100000)
        budgeter.calculate_budget(clarity_score=0.75)

        def allocate_task(severity, tokens):
            return budgeter.allocate(severity, tokens)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(allocate_task, "SEV-1", 100)
                for _ in range(100)
            ]
            results = [f.result() for f in futures]

        # Should have exactly 100 successful allocations of 100 tokens each
        # = 10000 tokens total from SEV-1 budget of 30000
        assert sum(results) == 100

        remaining = budgeter.get_remaining_budget()
        assert remaining["SEV-1"] == 20000  # 30000 - 10000

    def test_concurrent_calculate_budget(self):
        """Test concurrent budget calculation is thread-safe."""
        budgeter = AdaptiveBudgeter(total_budget=100000)

        def calculate_task(clarity):
            return budgeter.calculate_budget(clarity_score=clarity)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(calculate_task, 0.5 + (i * 0.05))
                for i in range(20)
            ]
            allocations = [f.result() for f in futures]

        # All allocations should be valid
        for alloc in allocations:
            assert alloc.validate() is True


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_init_budgeter(self):
        """Test init_budgeter function."""
        budgeter = init_budgeter(total_budget=50000)

        assert budgeter.total_budget == 50000
        assert get_budgeter() is budgeter

    def test_get_budgeter_none_initially(self):
        """Test get_budgeter returns None before initialization."""
        # Reset global budgeter
        import budget.adaptive_budgeting as mod
        mod._global_budgeter = None

        assert get_budgeter() is None


class TestDefaultValues:
    """Tests for default configuration values."""

    def test_default_allocations_sum_to_one(self):
        """Test that all default allocations sum to 1.0."""
        for tier, ratios in DEFAULT_ALLOCATIONS.items():
            total = sum(ratios)
            assert total == pytest.approx(1.0, rel=0.001), \
                f"Allocations for {tier} sum to {total}"

    def test_mode_adjustments_sum_to_zero(self):
        """Test that all mode adjustments sum to 0."""
        for mode, adjustments in MODE_ADJUSTMENTS.items():
            total = sum(adjustments)
            assert total == pytest.approx(0.0, rel=0.001), \
                f"Adjustments for {mode} sum to {total}"


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_zero_budget(self):
        """Test behavior with zero budget."""
        budgeter = AdaptiveBudgeter(total_budget=0)
        budgeter.calculate_budget(clarity_score=0.75)

        remaining = budgeter.get_remaining_budget()
        assert remaining["total"] == 0

        success = budgeter.allocate("SEV-1", 1)
        assert success is False

    def test_allocate_exact_budget(self):
        """Test allocating exactly the remaining budget."""
        budgeter = AdaptiveBudgeter(total_budget=100)
        budgeter.calculate_budget(clarity_score=0.75)

        # SEV-1 should have 30 tokens (30% of 100)
        success = budgeter.allocate("SEV-1", 30)
        assert success is True

        remaining = budgeter.get_remaining_budget()
        assert remaining["SEV-1"] == 0

    def test_case_insensitive_severity(self):
        """Test that severity matching is case insensitive."""
        budgeter = AdaptiveBudgeter(total_budget=100000)
        budgeter.calculate_budget(clarity_score=0.75)

        # Test various case combinations
        assert budgeter.allocate("sev-1", 100) is True
        assert budgeter.allocate("SeV-2", 100) is True
        assert budgeter.allocate("SEV-3", 100) is True

    def test_unknown_mode_uses_default(self):
        """Test that unknown mode falls back to guided_autonomy."""
        budgeter = AdaptiveBudgeter(total_budget=100000)

        allocation = budgeter.calculate_budget(
            clarity_score=0.75,
            mode="unknown_mode"
        )

        # Should use guided_autonomy (no adjustment)
        assert allocation.mode == "guided_autonomy"
        assert allocation.sev_1_2_ratio == pytest.approx(0.60, rel=0.01)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
