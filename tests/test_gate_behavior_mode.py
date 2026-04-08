"""
Tests for ITEM-GATE-001: GATE_BEHAVIOR_MODE_SENSITIVITY

Unit tests for mode-aware gate behavior with sensitivity multiplier.

Tests:
- test_modes_differ: Different modes produce different gate behaviors
- test_ci_cd_strict: CI/CD mode fails fast on any violation
- test_sensitivity_multiplier_applied: Sensitivity multiplier adjusts thresholds
- test_mode_profile_selection: Correct profile selected for each mode
- test_consensus_requirement: Multi-agent mode requires consensus
"""

import pytest
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.policy.gate_behavior import (
    ExecutionMode,
    ModeProfile,
    MODE_PROFILES,
    GateBehaviorModifier,
    GateResult,
    ModifiedGateResult,
    GateSensitivityConfig,
    MODE_SENSITIVITY_DEFAULTS,
)


class TestExecutionMode:
    """Tests for ExecutionMode enum."""

    def test_new_modes_exist(self):
        """Test that new ITEM-GATE-001 modes exist."""
        assert ExecutionMode.CI_CD_PIPELINE is not None
        assert ExecutionMode.SINGLE_LLM_EXECUTOR is not None
        assert ExecutionMode.MULTI_AGENT_SWARM is not None

    def test_mode_values(self):
        """Test mode enum values match expected strings."""
        assert ExecutionMode.CI_CD_PIPELINE.value == "ci_cd_pipeline"
        assert ExecutionMode.SINGLE_LLM_EXECUTOR.value == "single_llm_executor"
        assert ExecutionMode.MULTI_AGENT_SWARM.value == "multi_agent_swarm"

    def test_existing_modes_preserved(self):
        """Test that existing modes are preserved for backward compatibility."""
        assert ExecutionMode.DETERMINISTIC.value == "deterministic"
        assert ExecutionMode.GUIDED_AUTONOMY.value == "guided_autonomy"
        assert ExecutionMode.FAST_PROTOTYPE.value == "fast_prototype"
        assert ExecutionMode.DIRECT.value == "direct"


class TestModeProfile:
    """Tests for ModeProfile dataclass."""

    def test_ci_cd_profile(self):
        """Test CI/CD pipeline profile configuration."""
        profile = MODE_PROFILES[ExecutionMode.CI_CD_PIPELINE]
        
        assert profile.mode == ExecutionMode.CI_CD_PIPELINE
        assert profile.strict_mode is True
        assert profile.fail_fast is True
        assert profile.sensitivity_multiplier == 0.8
        assert profile.retry_generous is False
        assert profile.consensus_required is False
        assert profile.max_retries == 1

    def test_single_llm_profile(self):
        """Test single LLM executor profile configuration."""
        profile = MODE_PROFILES[ExecutionMode.SINGLE_LLM_EXECUTOR]
        
        assert profile.mode == ExecutionMode.SINGLE_LLM_EXECUTOR
        assert profile.strict_mode is False
        assert profile.fail_fast is False
        assert profile.sensitivity_multiplier == 1.0
        assert profile.retry_generous is True
        assert profile.consensus_required is False
        assert profile.max_retries == 5

    def test_multi_agent_profile(self):
        """Test multi-agent swarm profile configuration."""
        profile = MODE_PROFILES[ExecutionMode.MULTI_AGENT_SWARM]
        
        assert profile.mode == ExecutionMode.MULTI_AGENT_SWARM
        assert profile.strict_mode is True
        assert profile.fail_fast is False
        assert profile.sensitivity_multiplier == 0.9
        assert profile.retry_generous is False
        assert profile.consensus_required is True
        assert profile.max_retries == 3

    def test_profile_to_dict(self):
        """Test ModeProfile serialization to dict."""
        profile = MODE_PROFILES[ExecutionMode.CI_CD_PIPELINE]
        data = profile.to_dict()
        
        assert "mode" in data
        assert "strict_mode" in data
        assert "fail_fast" in data
        assert "sensitivity_multiplier" in data
        assert data["mode"] == "ci_cd_pipeline"


class TestModesDiffer:
    """Tests that different modes produce different gate behaviors."""

    def test_sensitivity_differs_between_modes(self):
        """Test that sensitivity multipliers differ between modes."""
        ci_cd = MODE_PROFILES[ExecutionMode.CI_CD_PIPELINE]
        single_llm = MODE_PROFILES[ExecutionMode.SINGLE_LLM_EXECUTOR]
        multi_agent = MODE_PROFILES[ExecutionMode.MULTI_AGENT_SWARM]
        
        # CI/CD should be stricter (lower multiplier)
        assert ci_cd.sensitivity_multiplier < single_llm.sensitivity_multiplier
        assert ci_cd.sensitivity_multiplier < multi_agent.sensitivity_multiplier
        
        # Multi-agent should be stricter than single LLM
        assert multi_agent.sensitivity_multiplier < single_llm.sensitivity_multiplier

    def test_fail_fast_differs_between_modes(self):
        """Test that fail_fast setting differs between modes."""
        ci_cd = MODE_PROFILES[ExecutionMode.CI_CD_PIPELINE]
        single_llm = MODE_PROFILES[ExecutionMode.SINGLE_LLM_EXECUTOR]
        
        # CI/CD should fail fast, single LLM should not
        assert ci_cd.fail_fast is True
        assert single_llm.fail_fast is False

    def test_retry_count_differs_between_modes(self):
        """Test that retry counts differ between modes."""
        ci_cd = MODE_PROFILES[ExecutionMode.CI_CD_PIPELINE]
        fast_prototype = MODE_PROFILES[ExecutionMode.FAST_PROTOTYPE]
        
        # Fast prototype should allow more retries
        assert fast_prototype.max_retries > ci_cd.max_retries


class TestCICDStrict:
    """Tests for CI/CD mode strict behavior."""

    def test_ci_cd_fails_fast_on_sev1(self):
        """Test CI/CD mode fails fast on SEV-1."""
        modifier = GateBehaviorModifier(ExecutionMode.CI_CD_PIPELINE)
        
        assert modifier.should_fail_fast("SEV-1") is True

    def test_ci_cd_fails_fast_on_sev2(self):
        """Test CI/CD mode fails fast on SEV-2."""
        modifier = GateBehaviorModifier(ExecutionMode.CI_CD_PIPELINE)
        
        # CI/CD has fail_fast=True, so should fail on any severity
        assert modifier.should_fail_fast("SEV-2") is True

    def test_ci_cd_fails_fast_on_sev3(self):
        """Test CI/CD mode fails fast on SEV-3."""
        modifier = GateBehaviorModifier(ExecutionMode.CI_CD_PIPELINE)
        
        assert modifier.should_fail_fast("SEV-3") is True

    def test_ci_cd_is_strict_mode(self):
        """Test CI/CD mode is marked as strict."""
        modifier = GateBehaviorModifier(ExecutionMode.CI_CD_PIPELINE)
        
        assert modifier.is_strict_mode() is True

    def test_ci_cd_has_minimal_retries(self):
        """Test CI/CD mode has minimal retries."""
        modifier = GateBehaviorModifier(ExecutionMode.CI_CD_PIPELINE)
        
        assert modifier.get_retry_count() == 1


class TestSensitivityMultiplierApplied:
    """Tests for sensitivity multiplier application."""

    def test_sensitivity_reduces_thresholds(self):
        """Test that sensitivity multiplier < 1.0 reduces thresholds."""
        modifier = GateBehaviorModifier(ExecutionMode.CI_CD_PIPELINE)
        
        thresholds = {"max_sev2": 10, "max_sev3": 20}
        adjusted = modifier.apply_sensitivity(thresholds)
        
        # CI/CD has 0.8 multiplier
        assert adjusted["max_sev2"] == 8.0  # 10 * 0.8
        assert adjusted["max_sev3"] == 16.0  # 20 * 0.8

    def test_sensitivity_increases_thresholds(self):
        """Test that sensitivity multiplier > 1.0 increases thresholds."""
        modifier = GateBehaviorModifier(ExecutionMode.FAST_PROTOTYPE)
        
        thresholds = {"max_sev2": 10, "max_sev3": 20}
        adjusted = modifier.apply_sensitivity(thresholds)
        
        # Fast prototype has 1.2 multiplier
        assert adjusted["max_sev2"] == 12.0  # 10 * 1.2
        assert adjusted["max_sev3"] == 24.0  # 20 * 1.2

    def test_sensitivity_preserves_non_numeric(self):
        """Test that non-numeric values are preserved."""
        modifier = GateBehaviorModifier(ExecutionMode.CI_CD_PIPELINE)
        
        thresholds = {"name": "test", "max_sev2": 10}
        adjusted = modifier.apply_sensitivity(thresholds)
        
        assert adjusted["name"] == "test"  # Preserved
        assert adjusted["max_sev2"] == 8.0  # Adjusted

    def test_sensitivity_default_is_identity(self):
        """Test that DIRECT mode (1.0 multiplier) doesn't change thresholds."""
        modifier = GateBehaviorModifier(ExecutionMode.DIRECT)
        
        thresholds = {"max_sev2": 10}
        adjusted = modifier.apply_sensitivity(thresholds)
        
        assert adjusted["max_sev2"] == 10.0  # Unchanged


class TestModeProfileSelection:
    """Tests for mode profile selection."""

    def test_get_mode_profile_returns_correct_profile(self):
        """Test that get_mode_profile returns correct profile."""
        modifier = GateBehaviorModifier(ExecutionMode.CI_CD_PIPELINE)
        
        profile = modifier.get_mode_profile()
        
        assert profile.mode == ExecutionMode.CI_CD_PIPELINE

    def test_get_current_mode(self):
        """Test that get_current_mode returns correct mode."""
        modifier = GateBehaviorModifier(ExecutionMode.SINGLE_LLM_EXECUTOR)
        
        assert modifier.get_current_mode() == ExecutionMode.SINGLE_LLM_EXECUTOR

    def test_default_mode_is_direct(self):
        """Test that default mode is DIRECT when not specified."""
        modifier = GateBehaviorModifier()
        
        assert modifier.get_current_mode() == ExecutionMode.DIRECT

    def test_mode_selection_from_config(self):
        """Test mode selection from config."""
        config = {"mode": {"current": "ci_cd_pipeline"}}
        # Note: Config-based mode selection is handled at GateManager level
        
        modifier = GateBehaviorModifier(ExecutionMode.CI_CD_PIPELINE, config)
        
        assert modifier.get_current_mode() == ExecutionMode.CI_CD_PIPELINE


class TestConsensusRequirement:
    """Tests for consensus requirement."""

    def test_multi_agent_requires_consensus(self):
        """Test multi-agent swarm mode requires consensus."""
        modifier = GateBehaviorModifier(ExecutionMode.MULTI_AGENT_SWARM)
        
        assert modifier.requires_consensus() is True

    def test_single_llm_does_not_require_consensus(self):
        """Test single LLM mode does not require consensus."""
        modifier = GateBehaviorModifier(ExecutionMode.SINGLE_LLM_EXECUTOR)
        
        assert modifier.requires_consensus() is False

    def test_ci_cd_does_not_require_consensus(self):
        """Test CI/CD mode does not require consensus."""
        modifier = GateBehaviorModifier(ExecutionMode.CI_CD_PIPELINE)
        
        assert modifier.requires_consensus() is False

    def test_deterministic_does_not_require_consensus(self):
        """Test deterministic mode does not require consensus."""
        modifier = GateBehaviorModifier(ExecutionMode.DETERMINISTIC)
        
        assert modifier.requires_consensus() is False


class TestRetryCount:
    """Tests for retry count behavior."""

    def test_ci_cd_minimal_retries(self):
        """Test CI/CD mode has minimal retries (1)."""
        modifier = GateBehaviorModifier(ExecutionMode.CI_CD_PIPELINE)
        
        assert modifier.get_retry_count() == 1

    def test_single_llm_generous_retries(self):
        """Test single LLM mode has generous retries (5)."""
        modifier = GateBehaviorModifier(ExecutionMode.SINGLE_LLM_EXECUTOR)
        
        assert modifier.get_retry_count() == 5

    def test_fast_prototype_max_retries(self):
        """Test fast prototype mode has max retries (10)."""
        modifier = GateBehaviorModifier(ExecutionMode.FAST_PROTOTYPE)
        
        assert modifier.get_retry_count() == 10

    def test_retry_generous_enforces_minimum(self):
        """Test retry_generous flag enforces minimum of 3 retries."""
        # Create a profile with low max_retries but retry_generous=True
        # This tests the internal logic that enforces minimum when retry_generous
        
        # Single LLM has retry_generous=True
        modifier = GateBehaviorModifier(ExecutionMode.SINGLE_LLM_EXECUTOR)
        
        # Should return at least 3 due to retry_generous logic
        assert modifier.get_retry_count() >= 3


class TestFailFastBehavior:
    """Tests for fail-fast behavior."""

    def test_sev1_always_causes_fail_fast(self):
        """Test SEV-1 always causes fail-fast regardless of mode."""
        # Test with single_llm_executor which has fail_fast=False
        modifier = GateBehaviorModifier(ExecutionMode.SINGLE_LLM_EXECUTOR)
        
        # SEV-1 should still cause fail-fast
        assert modifier.should_fail_fast("SEV-1") is True

    def test_non_sev1_respects_fail_fast_setting(self):
        """Test non-SEV-1 respects mode's fail_fast setting."""
        # CI/CD has fail_fast=True
        cicd = GateBehaviorModifier(ExecutionMode.CI_CD_PIPELINE)
        assert cicd.should_fail_fast("SEV-2") is True
        
        # Single LLM has fail_fast=False
        single = GateBehaviorModifier(ExecutionMode.SINGLE_LLM_EXECUTOR)
        assert single.should_fail_fast("SEV-2") is False

    def test_deterministic_fails_fast(self):
        """Test deterministic mode fails fast on any severity."""
        modifier = GateBehaviorModifier(ExecutionMode.DETERMINISTIC)
        
        assert modifier.should_fail_fast("SEV-1") is True
        assert modifier.should_fail_fast("SEV-2") is True
        assert modifier.should_fail_fast("SEV-3") is True
        assert modifier.should_fail_fast("SEV-4") is True


class TestSensitivityConfigs:
    """Tests for mode sensitivity configurations."""

    def test_ci_cd_sensitivity_config_exists(self):
        """Test CI/CD sensitivity config exists."""
        assert "ci_cd_pipeline" in MODE_SENSITIVITY_DEFAULTS
        
        config = MODE_SENSITIVITY_DEFAULTS["ci_cd_pipeline"]
        assert config.fail_on_any_gap is True
        assert config.max_sev1_gaps == 0

    def test_single_llm_sensitivity_config_exists(self):
        """Test single LLM sensitivity config exists."""
        assert "single_llm_executor" in MODE_SENSITIVITY_DEFAULTS
        
        config = MODE_SENSITIVITY_DEFAULTS["single_llm_executor"]
        assert config.fail_on_any_gap is False
        assert config.allow_advisory_pass is True

    def test_multi_agent_sensitivity_config_exists(self):
        """Test multi-agent sensitivity config exists."""
        assert "multi_agent_swarm" in MODE_SENSITIVITY_DEFAULTS
        
        config = MODE_SENSITIVITY_DEFAULTS["multi_agent_swarm"]
        assert config.fail_on_any_gap is False
        assert config.max_sev2_gaps == 1  # More restrictive


class TestBackwardCompatibility:
    """Tests for backward compatibility."""

    def test_existing_modes_still_work(self):
        """Test that existing modes still work with new API."""
        # Test deterministic
        det = GateBehaviorModifier(ExecutionMode.DETERMINISTIC)
        assert det.is_strict_mode() is True
        
        # Test guided_autonomy
        guided = GateBehaviorModifier(ExecutionMode.GUIDED_AUTONOMY)
        assert guided.is_strict_mode() is False
        
        # Test fast_prototype
        fast = GateBehaviorModifier(ExecutionMode.FAST_PROTOTYPE)
        assert fast.is_strict_mode() is False

    def test_get_sensitivity_still_works(self):
        """Test that get_sensitivity still works for string modes."""
        modifier = GateBehaviorModifier()
        
        # Should work with string mode names
        sens = modifier.get_sensitivity("deterministic")
        assert sens.fail_on_any_gap is True

    def test_mode_aliases_work(self):
        """Test that mode aliases still work."""
        modifier = GateBehaviorModifier()
        
        # Test various aliases
        assert modifier.get_sensitivity("ci-cd").fail_on_any_gap is True
        assert modifier.get_sensitivity("cicd").fail_on_any_gap is True
        assert modifier.get_sensitivity("single_llm").allow_advisory_pass is True
        assert modifier.get_sensitivity("swarm").max_sev2_gaps == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
