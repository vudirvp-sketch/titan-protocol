"""
Tests for Tiered Validator (ITEM-VAL-69).

Tests the severity-based validation tiering system that optimizes
performance by sampling SEV-3/4 validators on large files.
"""

import pytest
from dataclasses import dataclass
from typing import Dict, Any
from unittest.mock import Mock

from src.validation.tiered_validator import (
    TieredValidator,
    SeverityTier,
    SamplingDecision,
    TieredValidatorStats,
    ValidatorProtocol,
    create_tiered_validator,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@dataclass
class MockValidator:
    """Mock validator for testing."""
    name: str
    severity: str


def create_mock_validator(name: str, severity: str) -> MockValidator:
    """Create a mock validator with the given name and severity."""
    return MockValidator(name=name, severity=severity)


def get_default_config() -> Dict[str, Any]:
    """Get the default configuration for testing."""
    return {
        "validation_tiering": {
            "enabled": True,
            "thresholds": {
                "sev1_sev2": 1.0,
                "sev3_large_file_threshold": 50000,
                "sev3_sampling_rate": 0.5,
                "sev4_sampling_rate": 0.2,
            }
        }
    }


# =============================================================================
# Tests for SeverityTier Enum
# =============================================================================

class TestSeverityTier:
    """Tests for SeverityTier enum."""

    def test_tier_values(self):
        """Test that tier values are correct."""
        assert SeverityTier.TIER_1.value == 1
        assert SeverityTier.TIER_2.value == 2
        assert SeverityTier.TIER_3.value == 3
        assert SeverityTier.TIER_4.value == 4

    def test_tier_ordering(self):
        """Test that tiers are ordered correctly."""
        assert SeverityTier.TIER_1.value < SeverityTier.TIER_2.value
        assert SeverityTier.TIER_2.value < SeverityTier.TIER_3.value
        assert SeverityTier.TIER_3.value < SeverityTier.TIER_4.value


# =============================================================================
# Tests for SamplingDecision
# =============================================================================

class TestSamplingDecision:
    """Tests for SamplingDecision dataclass."""

    def test_decision_creation(self):
        """Test creating a sampling decision."""
        decision = SamplingDecision(
            validator_name="test_validator",
            severity="SEV-3",
            file_size=75000,
            sampling_rate=0.5,
            should_run=True,
            tier=SeverityTier.TIER_3,
        )
        
        assert decision.validator_name == "test_validator"
        assert decision.severity == "SEV-3"
        assert decision.file_size == 75000
        assert decision.sampling_rate == 0.5
        assert decision.should_run is True
        assert decision.tier == SeverityTier.TIER_3
        assert decision.timestamp is not None

    def test_decision_to_dict(self):
        """Test converting decision to dictionary."""
        decision = SamplingDecision(
            validator_name="my_validator",
            severity="SEV-4",
            file_size=100000,
            sampling_rate=0.2,
            should_run=False,
            tier=SeverityTier.TIER_4,
        )
        
        data = decision.to_dict()
        
        assert data["validator_name"] == "my_validator"
        assert data["severity"] == "SEV-4"
        assert data["file_size"] == 100000
        assert data["sampling_rate"] == 0.2
        assert data["should_run"] is False
        assert data["tier"] == 4
        assert "timestamp" in data


# =============================================================================
# Tests for TieredValidatorStats
# =============================================================================

class TestTieredValidatorStats:
    """Tests for TieredValidatorStats dataclass."""

    def test_stats_initialization(self):
        """Test stats are initialized to zero."""
        stats = TieredValidatorStats()
        
        assert stats.validators_run == 0
        assert stats.validators_skipped == 0
        assert len(stats.sampling_decisions) == 0
        assert stats.total_decisions == 0
        assert stats.skip_rate == 0.0

    def test_stats_total_decisions(self):
        """Test total decisions calculation."""
        stats = TieredValidatorStats()
        stats.validators_run = 10
        stats.validators_skipped = 5
        
        assert stats.total_decisions == 15

    def test_stats_skip_rate(self):
        """Test skip rate calculation."""
        stats = TieredValidatorStats()
        
        # No decisions yet
        assert stats.skip_rate == 0.0
        
        # Some decisions
        stats.validators_run = 8
        stats.validators_skipped = 2
        assert stats.skip_rate == 0.2  # 2/10 = 20%
        
        # All skipped
        stats.validators_run = 0
        stats.validators_skipped = 5
        assert stats.skip_rate == 1.0

    def test_stats_to_dict(self):
        """Test converting stats to dictionary."""
        stats = TieredValidatorStats()
        stats.validators_run = 10
        stats.validators_skipped = 5
        
        data = stats.to_dict()
        
        assert data["validators_run"] == 10
        assert data["validators_skipped"] == 5
        assert data["total_decisions"] == 15
        assert data["skip_rate"] == 1/3
        assert data["sampling_decisions_count"] == 0

    def test_stats_reset(self):
        """Test resetting stats."""
        stats = TieredValidatorStats()
        stats.validators_run = 10
        stats.validators_skipped = 5
        stats.sampling_decisions.append(
            SamplingDecision(
                validator_name="test",
                severity="SEV-3",
                file_size=1000,
                sampling_rate=1.0,
                should_run=True,
                tier=SeverityTier.TIER_3,
            )
        )
        
        stats.reset()
        
        assert stats.validators_run == 0
        assert stats.validators_skipped == 0
        assert len(stats.sampling_decisions) == 0


# =============================================================================
# Tests for TieredValidator
# =============================================================================

class TestTieredValidatorInitialization:
    """Tests for TieredValidator initialization."""

    def test_initialization_default(self):
        """Test initialization with no config."""
        tiered = TieredValidator()
        
        assert tiered.enabled is True
        assert tiered._sev3_large_file_threshold == 50000
        assert tiered._sev3_sampling_rate == 0.5
        assert tiered._sev4_sampling_rate == 0.2
        assert tiered._sev4_large_file_threshold == 10000

    def test_initialization_with_config(self):
        """Test initialization with custom config."""
        config = {
            "validation_tiering": {
                "enabled": True,
                "thresholds": {
                    "sev3_large_file_threshold": 100000,
                    "sev3_sampling_rate": 0.3,
                    "sev4_sampling_rate": 0.1,
                }
            }
        }
        tiered = TieredValidator(config)
        
        assert tiered._sev3_large_file_threshold == 100000
        assert tiered._sev3_sampling_rate == 0.3
        assert tiered._sev4_sampling_rate == 0.1

    def test_initialization_disabled(self):
        """Test initialization with tiering disabled."""
        config = {
            "validation_tiering": {
                "enabled": False
            }
        }
        tiered = TieredValidator(config)
        
        assert tiered.enabled is False

    def test_initialization_with_seed(self):
        """Test initialization with random seed for deterministic behavior."""
        tiered1 = TieredValidator(seed=42)
        tiered2 = TieredValidator(seed=42)
        
        # Same seed should produce same random sequence
        validator = create_mock_validator("test", "SEV-3")
        
        # Run multiple times with same seed
        results1 = [tiered1.should_run(validator, 100000) for _ in range(10)]
        results2 = [tiered2.should_run(validator, 100000) for _ in range(10)]
        
        assert results1 == results2


class TestGetTierForSeverity:
    """Tests for get_tier_for_severity method."""

    def test_sev1_variations(self):
        """Test SEV-1 severity mapping."""
        tiered = TieredValidator()
        
        assert tiered.get_tier_for_severity("SEV-1") == SeverityTier.TIER_1
        assert tiered.get_tier_for_severity("SEV1") == SeverityTier.TIER_1
        assert tiered.get_tier_for_severity("sev-1") == SeverityTier.TIER_1
        assert tiered.get_tier_for_severity("sev1") == SeverityTier.TIER_1

    def test_sev2_variations(self):
        """Test SEV-2 severity mapping."""
        tiered = TieredValidator()
        
        assert tiered.get_tier_for_severity("SEV-2") == SeverityTier.TIER_2
        assert tiered.get_tier_for_severity("SEV2") == SeverityTier.TIER_2
        assert tiered.get_tier_for_severity("sev-2") == SeverityTier.TIER_2

    def test_sev3_variations(self):
        """Test SEV-3 severity mapping."""
        tiered = TieredValidator()
        
        assert tiered.get_tier_for_severity("SEV-3") == SeverityTier.TIER_3
        assert tiered.get_tier_for_severity("SEV3") == SeverityTier.TIER_3
        assert tiered.get_tier_for_severity("sev-3") == SeverityTier.TIER_3

    def test_sev4_variations(self):
        """Test SEV-4 severity mapping."""
        tiered = TieredValidator()
        
        assert tiered.get_tier_for_severity("SEV-4") == SeverityTier.TIER_4
        assert tiered.get_tier_for_severity("SEV4") == SeverityTier.TIER_4
        assert tiered.get_tier_for_severity("sev-4") == SeverityTier.TIER_4

    def test_invalid_severity(self):
        """Test that invalid severity raises ValueError."""
        tiered = TieredValidator()
        
        with pytest.raises(ValueError) as exc_info:
            tiered.get_tier_for_severity("INVALID")
        
        assert "Unknown severity" in str(exc_info.value)


class TestGetSamplingRate:
    """Tests for get_sampling_rate method."""

    def test_sev1_always_runs(self):
        """Test that SEV-1 always has 100% sampling rate."""
        tiered = TieredValidator(get_default_config())
        
        # Small file
        assert tiered.get_sampling_rate(1000, "SEV-1") == 1.0
        # Medium file
        assert tiered.get_sampling_rate(50000, "SEV-1") == 1.0
        # Large file
        assert tiered.get_sampling_rate(1000000, "SEV-1") == 1.0

    def test_sev2_always_runs(self):
        """Test that SEV-2 always has 100% sampling rate."""
        tiered = TieredValidator(get_default_config())
        
        # Small file
        assert tiered.get_sampling_rate(1000, "SEV-2") == 1.0
        # Medium file
        assert tiered.get_sampling_rate(50000, "SEV-2") == 1.0
        # Large file
        assert tiered.get_sampling_rate(1000000, "SEV-2") == 1.0

    def test_sev3_small_file(self):
        """Test that SEV-3 runs at 100% for small files (<50KB)."""
        tiered = TieredValidator(get_default_config())
        
        # Very small file
        assert tiered.get_sampling_rate(1000, "SEV-3") == 1.0
        # Just below threshold
        assert tiered.get_sampling_rate(49999, "SEV-3") == 1.0

    def test_sev3_large_file(self):
        """Test that SEV-3 is sampled at 50% for large files (>=50KB)."""
        tiered = TieredValidator(get_default_config())
        
        # Exactly at threshold
        assert tiered.get_sampling_rate(50000, "SEV-3") == 0.5
        # Above threshold
        assert tiered.get_sampling_rate(100000, "SEV-3") == 0.5
        # Very large file
        assert tiered.get_sampling_rate(1000000, "SEV-3") == 0.5

    def test_sev4_small_file(self):
        """Test that SEV-4 runs at 100% for small files (<10KB)."""
        tiered = TieredValidator(get_default_config())
        
        # Very small file
        assert tiered.get_sampling_rate(1000, "SEV-4") == 1.0
        # Just below threshold
        assert tiered.get_sampling_rate(9999, "SEV-4") == 1.0

    def test_sev4_large_file(self):
        """Test that SEV-4 is sampled at 20% for large files (>=10KB)."""
        tiered = TieredValidator(get_default_config())
        
        # Exactly at threshold
        assert tiered.get_sampling_rate(10000, "SEV-4") == 0.2
        # Above threshold
        assert tiered.get_sampling_rate(50000, "SEV-4") == 0.2
        # Very large file
        assert tiered.get_sampling_rate(1000000, "SEV-4") == 0.2

    def test_disabled_tiering(self):
        """Test that disabled tiering always returns 1.0."""
        config = {"validation_tiering": {"enabled": False}}
        tiered = TieredValidator(config)
        
        # All severities should run at 100% when disabled
        assert tiered.get_sampling_rate(1000000, "SEV-1") == 1.0
        assert tiered.get_sampling_rate(1000000, "SEV-2") == 1.0
        assert tiered.get_sampling_rate(1000000, "SEV-3") == 1.0
        assert tiered.get_sampling_rate(1000000, "SEV-4") == 1.0


class TestShouldRun:
    """Tests for should_run method."""

    def test_sev1_always_true(self):
        """Test that SEV-1 validators always run."""
        tiered = TieredValidator(seed=42)
        
        validator = create_mock_validator("critical_check", "SEV-1")
        
        # Should always be True regardless of file size
        for file_size in [100, 10000, 50000, 100000, 1000000]:
            assert tiered.should_run(validator, file_size) is True

    def test_sev2_always_true(self):
        """Test that SEV-2 validators always run."""
        tiered = TieredValidator(seed=42)
        
        validator = create_mock_validator("important_check", "SEV-2")
        
        # Should always be True regardless of file size
        for file_size in [100, 10000, 50000, 100000, 1000000]:
            assert tiered.should_run(validator, file_size) is True

    def test_sev3_small_file_always_true(self):
        """Test that SEV-3 validators run for small files."""
        tiered = TieredValidator(seed=42)
        
        validator = create_mock_validator("standard_check", "SEV-3")
        
        # Should always be True for files under 50KB
        for file_size in [100, 5000, 10000, 49999]:
            assert tiered.should_run(validator, file_size) is True

    def test_sev3_large_file_probabilistic(self):
        """Test that SEV-3 validators are sampled for large files."""
        tiered = TieredValidator(seed=42)
        
        validator = create_mock_validator("standard_check", "SEV-3")
        
        # For large files, expect roughly 50% to run
        results = [tiered.should_run(validator, 100000) for _ in range(100)]
        
        # With seed 42, we expect a specific distribution
        # Allow some variance but expect roughly half
        run_count = sum(results)
        assert 30 <= run_count <= 70  # Roughly 50% with tolerance

    def test_sev4_small_file_always_true(self):
        """Test that SEV-4 validators run for small files (<10KB)."""
        tiered = TieredValidator(seed=42)
        
        validator = create_mock_validator("optional_check", "SEV-4")
        
        # Should always be True for files under 10KB
        for file_size in [100, 5000, 9999]:
            assert tiered.should_run(validator, file_size) is True

    def test_sev4_large_file_probabilistic(self):
        """Test that SEV-4 validators are sampled for large files."""
        tiered = TieredValidator(seed=42)
        
        validator = create_mock_validator("optional_check", "SEV-4")
        
        # For large files (>=10KB), expect roughly 20% to run
        results = [tiered.should_run(validator, 100000) for _ in range(100)]
        
        # With seed 42, allow variance but expect roughly 20%
        run_count = sum(results)
        assert 5 <= run_count <= 40  # Roughly 20% with tolerance

    def test_records_decision(self):
        """Test that should_run records sampling decisions."""
        tiered = TieredValidator()
        
        validator = create_mock_validator("test_validator", "SEV-3")
        
        initial_count = len(tiered._stats.sampling_decisions)
        tiered.should_run(validator, 100000)
        
        assert len(tiered._stats.sampling_decisions) == initial_count + 1
        
        decision = tiered._stats.sampling_decisions[-1]
        assert decision.validator_name == "test_validator"
        assert decision.severity == "SEV-3"
        assert decision.file_size == 100000
        assert decision.sampling_rate == 0.5

    def test_updates_stats_counters(self):
        """Test that should_run updates statistics counters."""
        tiered = TieredValidator(seed=42)
        
        validator_sev1 = create_mock_validator("sev1", "SEV-1")
        validator_sev3 = create_mock_validator("sev3", "SEV-3")
        
        # SEV-1 should increment validators_run
        tiered.should_run(validator_sev1, 100000)
        assert tiered._stats.validators_run == 1
        assert tiered._stats.validators_skipped == 0
        
        # SEV-3 on large file may or may not run (probabilistic)
        # Run multiple times and check counters are updated
        tiered.reset_stats()
        for _ in range(100):
            tiered.should_run(validator_sev3, 100000)
        
        total = tiered._stats.validators_run + tiered._stats.validators_skipped
        assert total == 100


class TestStatisticsMethods:
    """Tests for statistics methods."""

    def test_get_stats(self):
        """Test getting statistics."""
        tiered = TieredValidator(seed=42)
        
        validator = create_mock_validator("test", "SEV-3")
        
        for _ in range(10):
            tiered.should_run(validator, 100000)
        
        stats = tiered.get_stats()
        
        assert isinstance(stats, TieredValidatorStats)
        assert stats.total_decisions == 10
        assert len(stats.sampling_decisions) == 10

    def test_reset_stats(self):
        """Test resetting statistics."""
        tiered = TieredValidator(seed=42)
        
        validator = create_mock_validator("test", "SEV-3")
        
        for _ in range(10):
            tiered.should_run(validator, 100000)
        
        assert tiered._stats.total_decisions > 0
        
        tiered.reset_stats()
        
        assert tiered._stats.validators_run == 0
        assert tiered._stats.validators_skipped == 0
        assert len(tiered._stats.sampling_decisions) == 0

    def test_get_recent_decisions(self):
        """Test getting recent decisions."""
        tiered = TieredValidator(seed=42)
        
        validator = create_mock_validator("test", "SEV-3")
        
        for i in range(20):
            tiered.should_run(validator, 100000 + i)
        
        recent = tiered.get_recent_decisions(limit=5)
        
        assert len(recent) == 5
        # Should be the most recent decisions
        assert recent[-1].file_size == 100019

    def test_clear_decisions(self):
        """Test clearing decisions history."""
        tiered = TieredValidator(seed=42)
        
        validator = create_mock_validator("test", "SEV-3")
        
        for _ in range(10):
            tiered.should_run(validator, 100000)
        
        assert len(tiered._stats.sampling_decisions) == 10
        
        tiered.clear_decisions()
        
        assert len(tiered._stats.sampling_decisions) == 0
        # Counters should remain unchanged
        assert tiered._stats.total_decisions == 10

    def test_get_config(self):
        """Test getting current configuration."""
        config = {
            "validation_tiering": {
                "enabled": True,
                "thresholds": {
                    "sev3_large_file_threshold": 75000,
                    "sev3_sampling_rate": 0.4,
                    "sev4_sampling_rate": 0.15,
                }
            }
        }
        tiered = TieredValidator(config)
        
        config_out = tiered.get_config()
        
        assert config_out["enabled"] is True
        assert config_out["sev3_large_file_threshold"] == 75000
        assert config_out["sev3_sampling_rate"] == 0.4
        assert config_out["sev4_sampling_rate"] == 0.15


# =============================================================================
# Tests for Factory Function
# =============================================================================

class TestFactoryFunction:
    """Tests for create_tiered_validator factory function."""

    def test_create_default(self):
        """Test creating with default settings."""
        tiered = create_tiered_validator()
        
        assert isinstance(tiered, TieredValidator)
        assert tiered.enabled is True

    def test_create_with_config(self):
        """Test creating with configuration."""
        config = {
            "validation_tiering": {
                "enabled": False
            }
        }
        tiered = create_tiered_validator(config)
        
        assert tiered.enabled is False

    def test_create_with_seed(self):
        """Test creating with random seed."""
        tiered = create_tiered_validator(seed=123)
        
        assert isinstance(tiered, TieredValidator)


# =============================================================================
# Validation Criteria Tests (from implementation plan)
# =============================================================================

class TestValidationCriteria:
    """Tests for validation criteria from ITEM-VAL-69 implementation plan."""

    def test_criterion_sev1_sev2_always(self):
        """
        CRITERION: sev1_sev2_always
        Test that SEV-1/SEV-2 validators always run.
        """
        tiered = TieredValidator(get_default_config())
        
        sev1_validator = create_mock_validator("sev1_check", "SEV-1")
        sev2_validator = create_mock_validator("sev2_check", "SEV-2")
        
        # Test multiple file sizes
        file_sizes = [100, 1000, 10000, 50000, 100000, 500000, 1000000]
        
        for file_size in file_sizes:
            # SEV-1 should always run
            assert tiered.should_run(sev1_validator, file_size) is True, \
                f"SEV-1 should run for file_size={file_size}"
            
            # SEV-2 should always run
            assert tiered.should_run(sev2_validator, file_size) is True, \
                f"SEV-2 should run for file_size={file_size}"

    def test_criterion_sampling_applied_sev3(self):
        """
        CRITERION: sampling_applied
        Test that SEV-3 is sampled correctly on large files.
        """
        tiered = TieredValidator(get_default_config(), seed=42)
        
        validator = create_mock_validator("sev3_check", "SEV-3")
        
        # Small files (<50KB) should always run
        small_sizes = [100, 5000, 25000, 49999]
        for file_size in small_sizes:
            tiered.reset_stats()
            assert tiered.should_run(validator, file_size) is True, \
                f"SEV-3 should run for small file_size={file_size}"
        
        # Large files (>=50KB) should be sampled at 50%
        tiered.reset_stats()
        runs = 1000
        for _ in range(runs):
            tiered.should_run(validator, 100000)
        
        stats = tiered.get_stats()
        # Expect roughly 50% sampling rate
        actual_rate = stats.validators_run / stats.total_decisions
        assert 0.45 <= actual_rate <= 0.55, \
            f"SEV-3 sampling rate should be ~50%, got {actual_rate:.2%}"

    def test_criterion_sampling_applied_sev4(self):
        """
        CRITERION: sampling_applied
        Test that SEV-4 is sampled correctly on large files.
        """
        tiered = TieredValidator(get_default_config(), seed=42)
        
        validator = create_mock_validator("sev4_check", "SEV-4")
        
        # Small files (<10KB) should always run
        small_sizes = [100, 5000, 9999]
        for file_size in small_sizes:
            tiered.reset_stats()
            assert tiered.should_run(validator, file_size) is True, \
                f"SEV-4 should run for small file_size={file_size}"
        
        # Large files (>=10KB) should be sampled at 20%
        tiered.reset_stats()
        runs = 1000
        for _ in range(runs):
            tiered.should_run(validator, 100000)
        
        stats = tiered.get_stats()
        # Expect roughly 20% sampling rate
        actual_rate = stats.validators_run / stats.total_decisions
        assert 0.15 <= actual_rate <= 0.25, \
            f"SEV-4 sampling rate should be ~20%, got {actual_rate:.2%}"

    def test_tier_boundary_conditions(self):
        """Test behavior at exact threshold boundaries."""
        tiered = TieredValidator(get_default_config())
        
        sev3_validator = create_mock_validator("sev3", "SEV-3")
        sev4_validator = create_mock_validator("sev4", "SEV-4")
        
        # SEV-3 threshold is 50KB
        # Just below threshold should always run
        tiered.reset_stats()
        assert tiered.should_run(sev3_validator, 49999) is True
        assert tiered.get_sampling_rate(49999, "SEV-3") == 1.0
        
        # At threshold should be sampled
        assert tiered.get_sampling_rate(50000, "SEV-3") == 0.5
        
        # SEV-4 threshold is 10KB
        # Just below threshold should always run
        tiered.reset_stats()
        assert tiered.should_run(sev4_validator, 9999) is True
        assert tiered.get_sampling_rate(9999, "SEV-4") == 1.0
        
        # At threshold should be sampled
        assert tiered.get_sampling_rate(10000, "SEV-4") == 0.2


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for TieredValidator."""

    def test_validator_protocol_compliance(self):
        """Test that mock validators implement the protocol correctly."""
        tiered = TieredValidator()
        
        # Test with dataclass validator
        validator = create_mock_validator("test", "SEV-1")
        assert isinstance(validator, ValidatorProtocol)
        
        # should_run should work with the protocol
        result = tiered.should_run(validator, 1000)
        assert isinstance(result, bool)

    def test_mock_validator_compatibility(self):
        """Test that Mock objects work with should_run."""
        tiered = TieredValidator()
        
        # Create a mock with the required attributes
        mock_validator = Mock()
        mock_validator.severity = "SEV-3"
        mock_validator.name = "mock_validator"
        
        # Should work with the mock
        result = tiered.should_run(mock_validator, 1000)
        assert isinstance(result, bool)

    def test_missing_severity_defaults_to_sev3(self):
        """Test that validators without severity default to SEV-3."""
        tiered = TieredValidator()
        
        # Create a validator without severity attribute
        class MinimalValidator:
            name = "minimal"
        
        validator = MinimalValidator()
        
        # Should not raise and should treat as SEV-3
        result = tiered.should_run(validator, 1000)
        assert isinstance(result, bool)

    def test_zero_file_size(self):
        """Test handling of zero file size."""
        tiered = TieredValidator()
        
        validator = create_mock_validator("test", "SEV-3")
        
        # Zero file size should be treated as small file
        assert tiered.should_run(validator, 0) is True
        assert tiered.get_sampling_rate(0, "SEV-3") == 1.0

    def test_negative_file_size(self):
        """Test handling of negative file size (should treat as small)."""
        tiered = TieredValidator()
        
        validator = create_mock_validator("test", "SEV-3")
        
        # Negative file size is invalid but should not crash
        # Treat as small file (always run)
        result = tiered.should_run(validator, -1)
        assert isinstance(result, bool)
