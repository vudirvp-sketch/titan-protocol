"""
Tests for TieredValidator Sampling Enhancement (ITEM-VAL-001).

Tests the enhanced sampling logic for SEV-3/SEV-4 validators based on
file size and content characteristics, including critical content type
heuristics and stratified content sampling.
"""

import pytest
from dataclasses import dataclass
from typing import Dict, Any, Optional

from src.validation.tiered_validator import (
    TieredValidator,
    SeverityTier,
    SamplingConfig,
    SamplingDecision,
    TieredValidatorStats,
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
            "sampling": {
                "sev3_large_file_threshold": 50000,
                "sev3_large_file_rate": 0.5,
                "sev4_small_file_threshold": 10000,
                "sev4_small_file_rate": 1.0,
                "sev4_large_file_rate": 0.2,
                "critical_content_types": ["config", "schema", "manifest"],
                "critical_content_multiplier": 1.5,
            }
        }
    }


def get_legacy_config() -> Dict[str, Any]:
    """Get legacy configuration format for backward compatibility testing."""
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
# Tests for SamplingConfig
# =============================================================================

class TestSamplingConfig:
    """Tests for SamplingConfig dataclass."""

    def test_default_values(self):
        """Test that default values are correct."""
        config = SamplingConfig()
        
        assert config.sev1_rate == 1.0
        assert config.sev2_rate == 1.0
        assert config.sev3_small_file_rate == 1.0
        assert config.sev3_large_file_rate == 0.5
        assert config.sev3_size_threshold == 50000
        assert config.sev4_small_file_rate == 1.0
        assert config.sev4_large_file_rate == 0.2
        assert config.sev4_size_threshold == 10000
        assert config.critical_content_multiplier == 1.5
        assert "config" in config.critical_content_types
        assert "schema" in config.critical_content_types
        assert "manifest" in config.critical_content_types

    def test_custom_values(self):
        """Test that custom values can be set."""
        config = SamplingConfig(
            sev3_large_file_rate=0.3,
            sev4_large_file_rate=0.1,
            critical_content_multiplier=2.0,
            critical_content_types=["config", "yaml"],
        )
        
        assert config.sev3_large_file_rate == 0.3
        assert config.sev4_large_file_rate == 0.1
        assert config.critical_content_multiplier == 2.0
        assert config.critical_content_types == ["config", "yaml"]

    def test_to_dict(self):
        """Test converting to dictionary."""
        config = SamplingConfig()
        data = config.to_dict()
        
        assert isinstance(data, dict)
        assert data["sev1_rate"] == 1.0
        assert data["sev3_size_threshold"] == 50000
        assert data["sev4_size_threshold"] == 10000
        assert data["critical_content_multiplier"] == 1.5
        assert len(data["critical_content_types"]) == 3


# =============================================================================
# Tests for SEV-1/SEV-2 Always Run
# =============================================================================

class TestSev1Sev2AlwaysRun:
    """
    CRITERION: test_sev1_sev2_always
    Test that SEV-1/SEV-2 validators always run at 100%.
    """

    def test_sev1_always_runs(self):
        """Test that SEV-1 validators always run regardless of file size."""
        tiered = TieredValidator(get_default_config(), seed=42)
        validator = create_mock_validator("critical_check", "SEV-1")
        
        # Test various file sizes
        file_sizes = [100, 1000, 10000, 50000, 100000, 500000, 1000000]
        
        for file_size in file_sizes:
            assert tiered.should_run(validator, file_size) is True, \
                f"SEV-1 should run for file_size={file_size}"
            
            assert tiered.get_sampling_rate(file_size, "SEV-1") == 1.0, \
                f"SEV-1 rate should be 1.0 for file_size={file_size}"

    def test_sev2_always_runs(self):
        """Test that SEV-2 validators always run regardless of file size."""
        tiered = TieredValidator(get_default_config(), seed=42)
        validator = create_mock_validator("important_check", "SEV-2")
        
        # Test various file sizes
        file_sizes = [100, 1000, 10000, 50000, 100000, 500000, 1000000]
        
        for file_size in file_sizes:
            assert tiered.should_run(validator, file_size) is True, \
                f"SEV-2 should run for file_size={file_size}"
            
            assert tiered.get_sampling_rate(file_size, "SEV-2") == 1.0, \
                f"SEV-2 rate should be 1.0 for file_size={file_size}"

    def test_sev1_with_critical_content_type(self):
        """Test that SEV-1 still runs at 100% even with critical content type."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        # SEV-1 should always be 100% regardless of content type
        rate = tiered.get_sampling_rate(100000, "SEV-1", "config")
        assert rate == 1.0

    def test_sev2_with_critical_content_type(self):
        """Test that SEV-2 still runs at 100% even with critical content type."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        # SEV-2 should always be 100% regardless of content type
        rate = tiered.get_sampling_rate(100000, "SEV-2", "schema")
        assert rate == 1.0


# =============================================================================
# Tests for SEV-3 Sampling
# =============================================================================

class TestSev3Sampling:
    """
    CRITERION: test_sev3_sampling_large_files
    Test that SEV-3 validators are sampled correctly on large files.
    """

    def test_sev3_small_file_always_runs(self):
        """Test that SEV-3 runs at 100% for small files (<50KB)."""
        tiered = TieredValidator(get_default_config(), seed=42)
        validator = create_mock_validator("standard_check", "SEV-3")
        
        # Test small file sizes
        small_sizes = [100, 5000, 25000, 49999]
        
        for file_size in small_sizes:
            tiered.reset_stats()
            assert tiered.should_run(validator, file_size) is True, \
                f"SEV-3 should run for small file_size={file_size}"
            assert tiered.get_sampling_rate(file_size, "SEV-3") == 1.0

    def test_sev3_large_file_sampled_at_50_percent(self):
        """Test that SEV-3 is sampled at 50% for large files (>=50KB)."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        # Verify the sampling rate
        assert tiered.get_sampling_rate(50000, "SEV-3") == 0.5
        assert tiered.get_sampling_rate(100000, "SEV-3") == 0.5
        assert tiered.get_sampling_rate(1000000, "SEV-3") == 0.5

    def test_sev3_large_file_probabilistic_distribution(self):
        """Test that SEV-3 sampling produces expected distribution over many runs."""
        tiered = TieredValidator(get_default_config(), seed=42)
        validator = create_mock_validator("standard_check", "SEV-3")
        
        # Run many times to check distribution
        tiered.reset_stats()
        runs = 1000
        for _ in range(runs):
            tiered.should_run(validator, 100000)
        
        stats = tiered.get_stats()
        actual_rate = stats.validators_run / stats.total_decisions
        
        # Expect roughly 50% sampling rate (within 5%)
        assert 0.45 <= actual_rate <= 0.55, \
            f"SEV-3 sampling rate should be ~50%, got {actual_rate:.2%}"

    def test_sev3_boundary_condition(self):
        """Test SEV-3 behavior at exact threshold."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        # Just below threshold
        assert tiered.get_sampling_rate(49999, "SEV-3") == 1.0
        
        # At threshold
        assert tiered.get_sampling_rate(50000, "SEV-3") == 0.5
        
        # Just above threshold
        assert tiered.get_sampling_rate(50001, "SEV-3") == 0.5


# =============================================================================
# Tests for SEV-4 Sampling
# =============================================================================

class TestSev4Sampling:
    """
    CRITERION: test_sev4_sampling
    Test that SEV-4 validators are sampled correctly.
    """

    def test_sev4_small_file_always_runs(self):
        """Test that SEV-4 runs at 100% for small files (<10KB)."""
        tiered = TieredValidator(get_default_config(), seed=42)
        validator = create_mock_validator("optional_check", "SEV-4")
        
        # Test small file sizes
        small_sizes = [100, 5000, 9999]
        
        for file_size in small_sizes:
            tiered.reset_stats()
            assert tiered.should_run(validator, file_size) is True, \
                f"SEV-4 should run for small file_size={file_size}"
            assert tiered.get_sampling_rate(file_size, "SEV-4") == 1.0

    def test_sev4_large_file_sampled_at_20_percent(self):
        """Test that SEV-4 is sampled at 20% for large files (>=10KB)."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        # Verify the sampling rate
        assert tiered.get_sampling_rate(10000, "SEV-4") == 0.2
        assert tiered.get_sampling_rate(50000, "SEV-4") == 0.2
        assert tiered.get_sampling_rate(1000000, "SEV-4") == 0.2

    def test_sev4_large_file_probabilistic_distribution(self):
        """Test that SEV-4 sampling produces expected distribution over many runs."""
        tiered = TieredValidator(get_default_config(), seed=42)
        validator = create_mock_validator("optional_check", "SEV-4")
        
        # Run many times to check distribution
        tiered.reset_stats()
        runs = 1000
        for _ in range(runs):
            tiered.should_run(validator, 100000)
        
        stats = tiered.get_stats()
        actual_rate = stats.validators_run / stats.total_decisions
        
        # Expect roughly 20% sampling rate (within 5%)
        assert 0.15 <= actual_rate <= 0.25, \
            f"SEV-4 sampling rate should be ~20%, got {actual_rate:.2%}"

    def test_sev4_boundary_condition(self):
        """Test SEV-4 behavior at exact threshold."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        # Just below threshold
        assert tiered.get_sampling_rate(9999, "SEV-4") == 1.0
        
        # At threshold
        assert tiered.get_sampling_rate(10000, "SEV-4") == 0.2
        
        # Just above threshold
        assert tiered.get_sampling_rate(10001, "SEV-4") == 0.2


# =============================================================================
# Tests for Critical Content Type Heuristics
# =============================================================================

class TestCriticalContentTypeHeuristics:
    """
    CRITERION: test_critical_content_increased_rate
    Test that critical content types get increased sampling rates.
    """

    def test_config_file_increased_rate_sev3(self):
        """Test that 'config' content type increases SEV-3 sampling rate."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        # SEV-3 large file: 0.5 * 1.5 = 0.75
        rate = tiered.get_sampling_rate(100000, "SEV-3", "config")
        assert rate == 0.75, f"Expected 0.75, got {rate}"

    def test_schema_file_increased_rate_sev4(self):
        """Test that 'schema' content type increases SEV-4 sampling rate."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        # SEV-4 large file: 0.2 * 1.5 = 0.3
        rate = tiered.get_sampling_rate(100000, "SEV-4", "schema")
        assert abs(rate - 0.3) < 0.001, f"Expected 0.3, got {rate}"

    def test_manifest_file_increased_rate(self):
        """Test that 'manifest' content type increases sampling rate."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        # SEV-3 large file: 0.5 * 1.5 = 0.75
        rate = tiered.get_sampling_rate(100000, "SEV-3", "manifest")
        assert rate == 0.75

    def test_non_critical_content_unchanged(self):
        """Test that non-critical content types have normal sampling rates."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        # Non-critical content type
        rate = tiered.get_sampling_rate(100000, "SEV-3", "documentation")
        assert rate == 0.5  # Unchanged

    def test_critical_content_capped_at_100_percent(self):
        """Test that critical content multiplier is capped at 100%."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        # SEV-3 small file: 1.0 * 1.5 = 1.5, but capped at 1.0
        rate = tiered.get_sampling_rate(1000, "SEV-3", "config")
        assert rate == 1.0  # Capped at 100%

    def test_sev4_small_file_critical_content(self):
        """Test that SEV-4 small file with critical content is capped at 100%."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        # SEV-4 small file: 1.0 * 1.5 = 1.5, but capped at 1.0
        rate = tiered.get_sampling_rate(5000, "SEV-4", "schema")
        assert rate == 1.0

    def test_none_content_type_uses_default(self):
        """Test that None content type uses default sampling rate."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        rate = tiered.get_sampling_rate(100000, "SEV-3", None)
        assert rate == 0.5  # Default rate


# =============================================================================
# Tests for Sampling Rate Correctness
# =============================================================================

class TestSamplingRateCorrectness:
    """
    CRITERION: test_sampling_rate_correct
    Test that sampling rate matches rules within 5%.
    """

    def test_sev3_rate_within_tolerance(self):
        """Test SEV-3 sampling rate is within 5% of expected."""
        tiered = TieredValidator(get_default_config(), seed=42)
        validator = create_mock_validator("sev3", "SEV-3")
        
        # Run 1000 times
        tiered.reset_stats()
        for _ in range(1000):
            tiered.should_run(validator, 75000)  # Large file
        
        stats = tiered.get_stats()
        actual_rate = stats.validators_run / stats.total_decisions
        
        # Expected 50%, tolerance 5%
        assert abs(actual_rate - 0.5) <= 0.05, \
            f"SEV-3 rate {actual_rate:.2%} not within 5% of expected 50%"

    def test_sev4_rate_within_tolerance(self):
        """Test SEV-4 sampling rate is within 5% of expected."""
        tiered = TieredValidator(get_default_config(), seed=42)
        validator = create_mock_validator("sev4", "SEV-4")
        
        # Run 1000 times
        tiered.reset_stats()
        for _ in range(1000):
            tiered.should_run(validator, 75000)  # Large file
        
        stats = tiered.get_stats()
        actual_rate = stats.validators_run / stats.total_decisions
        
        # Expected 20%, tolerance 5%
        assert abs(actual_rate - 0.2) <= 0.05, \
            f"SEV-4 rate {actual_rate:.2%} not within 5% of expected 20%"

    def test_critical_content_rate_within_tolerance(self):
        """Test critical content sampling rate is within 5% of expected."""
        tiered = TieredValidator(get_default_config(), seed=42)
        validator = create_mock_validator("sev4", "SEV-4")
        
        # Run 1000 times with critical content type
        tiered.reset_stats()
        for _ in range(1000):
            tiered.should_run(validator, 75000, content_type="schema")
        
        stats = tiered.get_stats()
        actual_rate = stats.validators_run / stats.total_decisions
        
        # Expected 30% (0.2 * 1.5), tolerance 5%
        assert abs(actual_rate - 0.3) <= 0.05, \
            f"Critical content rate {actual_rate:.2%} not within 5% of expected 30%"


# =============================================================================
# Tests for Stratified Sampling
# =============================================================================

class TestStratifiedSampling:
    """
    CRITERION: test_stratified_sampling_preserves_structure
    Test that stratified sampling preserves content structure.
    """

    def test_full_rate_returns_original_content(self):
        """Test that rate 1.0 returns original content unchanged."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        content = "line1\nline2\nline3\nline4\nline5"
        result = tiered.sample_content(content, 1.0)
        
        assert result == content

    def test_zero_rate_returns_empty(self):
        """Test that rate 0.0 returns empty string."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        content = "line1\nline2\nline3\nline4\nline5"
        result = tiered.sample_content(content, 0.0)
        
        assert result == ""

    def test_preserves_beginning_section(self):
        """Test that stratified sampling includes beginning section."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        # Create content with identifiable sections
        lines = [f"line_{i}" for i in range(100)]
        content = "\n".join(lines)
        
        result = tiered.sample_content(content, 0.5)
        
        # Beginning lines should be present
        assert "line_0" in result

    def test_preserves_middle_section(self):
        """Test that stratified sampling includes middle section."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        # Create content with identifiable sections
        lines = [f"line_{i}" for i in range(100)]
        content = "\n".join(lines)
        
        result = tiered.sample_content(content, 0.5)
        
        # Middle lines should be present (around line 50)
        assert "MIDDLE SECTION SAMPLED" in result

    def test_preserves_end_section(self):
        """Test that stratified sampling includes end section."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        # Create content with identifiable sections
        lines = [f"line_{i}" for i in range(100)]
        content = "\n".join(lines)
        
        result = tiered.sample_content(content, 0.5)
        
        # End section should be marked
        assert "END SECTION" in result

    def test_empty_content_returns_empty(self):
        """Test that empty content returns empty."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        result = tiered.sample_content("", 0.5)
        assert result == ""

    def test_single_line_content(self):
        """Test handling of single-line content."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        content = "single_line"
        result = tiered.sample_content(content, 0.5)
        
        # Should return the single line
        assert "single_line" in result

    def test_small_content_gets_all_lines(self):
        """Test that small content gets most/all lines with reasonable rate."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        lines = [f"line_{i}" for i in range(6)]
        content = "\n".join(lines)
        
        result = tiered.sample_content(content, 0.5)
        
        # Should include some content
        assert len(result) > 0


# =============================================================================
# Tests for Deterministic Behavior
# =============================================================================

class TestDeterministicBehavior:
    """Test that sampling is reproducible with same seed."""

    def test_same_seed_produces_same_results(self):
        """Test that same seed produces identical sampling decisions."""
        validator = create_mock_validator("test", "SEV-3")
        
        tiered1 = TieredValidator(get_default_config(), seed=12345)
        tiered2 = TieredValidator(get_default_config(), seed=12345)
        
        results1 = [tiered1.should_run(validator, 100000) for _ in range(100)]
        results2 = [tiered2.should_run(validator, 100000) for _ in range(100)]
        
        assert results1 == results2

    def test_different_seeds_produce_different_results(self):
        """Test that different seeds produce different sampling decisions."""
        validator = create_mock_validator("test", "SEV-3")
        
        tiered1 = TieredValidator(get_default_config(), seed=111)
        tiered2 = TieredValidator(get_default_config(), seed=222)
        
        results1 = [tiered1.should_run(validator, 100000) for _ in range(100)]
        results2 = [tiered2.should_run(validator, 100000) for _ in range(100)]
        
        # Should be different (extremely unlikely to be identical with different seeds)
        assert results1 != results2

    def test_no_seed_allows_random_behavior(self):
        """Test that no seed allows non-deterministic behavior."""
        validator = create_mock_validator("test", "SEV-3")
        
        tiered = TieredValidator(get_default_config())
        
        # Should not raise and should produce results
        results = [tiered.should_run(validator, 100000) for _ in range(100)]
        
        # Should have some results
        assert len(results) == 100


# =============================================================================
# Tests for Backward Compatibility
# =============================================================================

class TestBackwardCompatibility:
    """Test backward compatibility with legacy configuration format."""

    def test_legacy_thresholds_format_still_works(self):
        """Test that old 'thresholds' format still works."""
        tiered = TieredValidator(get_legacy_config(), seed=42)
        
        # Should still work with legacy config
        assert tiered.get_sampling_rate(100000, "SEV-3") == 0.5
        assert tiered.get_sampling_rate(100000, "SEV-4") == 0.2

    def test_new_sampling_format_overrides_legacy(self):
        """Test that new 'sampling' format overrides legacy 'thresholds'."""
        config = {
            "validation_tiering": {
                "enabled": True,
                "thresholds": {
                    "sev3_sampling_rate": 0.3,  # Old value
                },
                "sampling": {
                    "sev3_large_file_rate": 0.7,  # New value should win
                }
            }
        }
        tiered = TieredValidator(config, seed=42)
        
        # New format should take precedence
        assert tiered.get_sampling_rate(100000, "SEV-3") == 0.7

    def test_critical_content_defaults_when_not_configured(self):
        """Test that critical content defaults work when not explicitly configured."""
        tiered = TieredValidator(get_legacy_config(), seed=42)
        
        # Default critical content types should be used
        assert "config" in tiered.sampling_config.critical_content_types
        assert tiered.sampling_config.critical_content_multiplier == 1.5


# =============================================================================
# Tests for Statistics Tracking
# =============================================================================

class TestStatisticsTracking:
    """Test that statistics are correctly tracked with new features."""

    def test_content_type_recorded_in_decision(self):
        """Test that content type is logged in decision."""
        tiered = TieredValidator(get_default_config(), seed=42)
        validator = create_mock_validator("test", "SEV-3")
        
        tiered.should_run(validator, 100000, content_type="config")
        
        # Check decision was recorded
        decision = tiered.get_stats().sampling_decisions[-1]
        assert decision.validator_name == "test"
        assert decision.severity == "SEV-3"
        assert decision.file_size == 100000
        # Sampling rate should be affected by critical content type
        assert decision.sampling_rate == 0.75  # 0.5 * 1.5

    def test_multiple_decisions_tracked(self):
        """Test that multiple decisions are tracked correctly."""
        tiered = TieredValidator(get_default_config(), seed=42)
        validator = create_mock_validator("test", "SEV-4")
        
        for _ in range(10):
            tiered.should_run(validator, 50000, content_type="schema")
        
        stats = tiered.get_stats()
        assert len(stats.sampling_decisions) == 10
        assert stats.total_decisions == 10

    def test_reset_clears_stats(self):
        """Test that reset clears all statistics."""
        tiered = TieredValidator(get_default_config(), seed=42)
        validator = create_mock_validator("test", "SEV-3")
        
        for _ in range(10):
            tiered.should_run(validator, 100000)
        
        assert tiered.get_stats().total_decisions == 10
        
        tiered.reset_stats()
        
        assert tiered.get_stats().validators_run == 0
        assert tiered.get_stats().validators_skipped == 0
        assert len(tiered.get_stats().sampling_decisions) == 0


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for the enhanced TieredValidator."""

    def test_full_workflow(self):
        """Test a complete workflow with all features."""
        config = get_default_config()
        tiered = TieredValidator(config, seed=42)
        
        # Create validators
        sev1 = create_mock_validator("critical", "SEV-1")
        sev2 = create_mock_validator("important", "SEV-2")
        sev3 = create_mock_validator("standard", "SEV-3")
        sev4 = create_mock_validator("optional", "SEV-4")
        
        # Test various scenarios
        assert tiered.should_run(sev1, 1000000, "config") is True
        assert tiered.should_run(sev2, 1000000, "schema") is True
        
        # SEV-3 on large config file (75% rate)
        tiered.reset_stats()
        for _ in range(100):
            tiered.should_run(sev3, 100000, "config")
        rate = tiered.get_stats().validators_run / 100
        assert 0.65 <= rate <= 0.85  # ~75% with tolerance
        
        # SEV-4 on large schema file (30% rate)
        tiered.reset_stats()
        for _ in range(100):
            tiered.should_run(sev4, 100000, "schema")
        rate = tiered.get_stats().validators_run / 100
        assert 0.20 <= rate <= 0.40  # ~30% with tolerance

    def test_get_config_returns_sampling_config(self):
        """Test that get_config returns the sampling configuration."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        config = tiered.get_config()
        
        assert "enabled" in config
        assert "sampling_config" in config
        assert config["enabled"] is True
        assert config["sampling_config"]["sev3_large_file_rate"] == 0.5

    def test_factory_function_with_new_config(self):
        """Test factory function with new configuration."""
        tiered = create_tiered_validator(get_default_config(), seed=42)
        
        assert tiered.enabled is True
        assert tiered.sampling_config.sev3_large_file_rate == 0.5
        assert "config" in tiered.sampling_config.critical_content_types


# =============================================================================
# Edge Case Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_negative_file_size(self):
        """Test handling of negative file size."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        # Negative size should be treated as small file
        rate = tiered.get_sampling_rate(-1, "SEV-3")
        assert rate == 1.0  # Small file rate

    def test_zero_file_size(self):
        """Test handling of zero file size."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        rate = tiered.get_sampling_rate(0, "SEV-3")
        assert rate == 1.0  # Small file rate

    def test_very_large_file_size(self):
        """Test handling of very large file size."""
        tiered = TieredValidator(get_default_config(), seed=42)
        
        rate = tiered.get_sampling_rate(10**15, "SEV-3")
        assert rate == 0.5  # Large file rate

    def test_empty_critical_content_types(self):
        """Test with empty critical content types list."""
        config = {
            "validation_tiering": {
                "enabled": True,
                "sampling": {
                    "critical_content_types": [],
                }
            }
        }
        tiered = TieredValidator(config, seed=42)
        
        # No content type should be critical
        rate = tiered.get_sampling_rate(100000, "SEV-3", "config")
        assert rate == 0.5  # No multiplier applied

    def test_custom_critical_content_multiplier(self):
        """Test with custom critical content multiplier."""
        config = {
            "validation_tiering": {
                "enabled": True,
                "sampling": {
                    "critical_content_multiplier": 2.0,
                    "critical_content_types": ["config"],
                }
            }
        }
        tiered = TieredValidator(config, seed=42)
        
        # SEV-4 large file: 0.2 * 2.0 = 0.4
        rate = tiered.get_sampling_rate(100000, "SEV-4", "config")
        assert rate == 0.4
