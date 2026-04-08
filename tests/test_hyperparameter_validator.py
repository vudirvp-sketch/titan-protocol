"""
TITAN FUSE Protocol - Hyperparameter Validator Tests

ITEM-PROT-001: Tests for Hyperparameter Enforcement Gate.

Tests cover:
- Gate blocks on violation
- Auto-fix mode corrects parameters
- Strict mode enforcement
- Relaxed mode allows flexibility
"""

import pytest
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.validation.guardian import (
    HyperparameterValidator,
    HyperparameterConfig,
    HyperparameterViolation,
    HyperparameterValidationResult,
    EnforcementMode,
    ViolationAction,
    create_hyperparameter_validator,
)
from src.policy.gate_manager import (
    GateManager,
    GateResult,
    GateType,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def strict_validator():
    """Create a strict mode validator."""
    config = HyperparameterConfig(
        enforcement=EnforcementMode.STRICT,
        on_violation=ViolationAction.REJECT,
    )
    return HyperparameterValidator(config)


@pytest.fixture
def relaxed_validator():
    """Create a relaxed mode validator."""
    config = HyperparameterConfig(
        enforcement=EnforcementMode.RELAXED,
        on_violation=ViolationAction.WARN,
    )
    return HyperparameterValidator(config)


@pytest.fixture
def auto_fix_validator():
    """Create an auto-fix mode validator."""
    config = HyperparameterConfig(
        enforcement=EnforcementMode.STRICT,
        on_violation=ViolationAction.AUTO_FIX,
    )
    return HyperparameterValidator(config)


@pytest.fixture
def valid_params():
    """Valid deterministic parameters."""
    return {
        "temperature": 0.0,
        "top_p": 0.1,
        "seed": 42,
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "test"}],
    }


# =============================================================================
# Test HyperparameterValidator - Basic Functionality
# =============================================================================

class TestHyperparameterValidatorBasics:
    """Tests for basic HyperparameterValidator functionality."""

    def test_create_validator_default_config(self):
        """Test creating validator with default config."""
        validator = HyperparameterValidator()
        
        assert validator.config.enforcement == EnforcementMode.STRICT
        assert validator.config.on_violation == ViolationAction.REJECT
        assert validator.config.allowed_temperature == 0.0
        assert validator.config.max_top_p == 0.1
        assert validator.config.require_seed is True

    def test_create_validator_custom_config(self):
        """Test creating validator with custom config."""
        config = HyperparameterConfig(
            enforcement=EnforcementMode.RELAXED,
            on_violation=ViolationAction.WARN,
            allowed_temperature=0.2,
            max_top_p=0.5,
            require_seed=False,
        )
        validator = HyperparameterValidator(config)
        
        assert validator.config.enforcement == EnforcementMode.RELAXED
        assert validator.config.on_violation == ViolationAction.WARN
        assert validator.config.allowed_temperature == 0.2
        assert validator.config.max_top_p == 0.5
        assert validator.config.require_seed is False

    def test_factory_function(self):
        """Test factory function creates correct validator."""
        validator = create_hyperparameter_validator(
            enforcement="relaxed",
            on_violation="warn"
        )
        
        assert validator.config.enforcement == EnforcementMode.RELAXED
        assert validator.config.on_violation == ViolationAction.WARN


# =============================================================================
# Test Strict Mode Enforcement
# =============================================================================

class TestStrictModeEnforcement:
    """Tests for strict mode enforcement."""

    def test_valid_params_pass(self, strict_validator, valid_params):
        """Test that valid parameters pass validation."""
        result = strict_validator.validate_deterministic(valid_params)
        
        assert result.valid is True
        assert len(result.violations) == 0
        assert result.was_auto_fixed is False

    def test_temperature_violation_rejected(self, strict_validator):
        """Test that non-zero temperature is rejected in strict mode."""
        params = {
            "temperature": 0.7,
            "top_p": 0.1,
            "seed": 42,
        }
        
        result = strict_validator.validate_deterministic(params)
        
        assert result.valid is False
        assert len(result.violations) == 1
        assert result.violations[0].param_name == "temperature"
        assert result.violations[0].actual == 0.7

    def test_top_p_violation_rejected(self, strict_validator):
        """Test that top_p > 0.1 is rejected in strict mode."""
        params = {
            "temperature": 0.0,
            "top_p": 0.9,
            "seed": 42,
        }
        
        result = strict_validator.validate_deterministic(params)
        
        assert result.valid is False
        assert len(result.violations) == 1
        assert result.violations[0].param_name == "top_p"
        assert result.violations[0].actual == 0.9

    def test_missing_seed_rejected(self, strict_validator):
        """Test that missing seed is rejected in strict mode."""
        params = {
            "temperature": 0.0,
            "top_p": 0.1,
        }
        
        result = strict_validator.validate_deterministic(params)
        
        assert result.valid is False
        assert any(v.param_name == "seed" for v in result.violations)

    def test_invalid_seed_type_rejected(self, strict_validator):
        """Test that non-integer seed is rejected."""
        params = {
            "temperature": 0.0,
            "top_p": 0.1,
            "seed": "not_an_int",
        }
        
        result = strict_validator.validate_deterministic(params)
        
        assert result.valid is False
        assert any(v.param_name == "seed" for v in result.violations)

    def test_boolean_seed_rejected(self, strict_validator):
        """Test that boolean seed is rejected (bool is subclass of int)."""
        params = {
            "temperature": 0.0,
            "top_p": 0.1,
            "seed": True,
        }
        
        result = strict_validator.validate_deterministic(params)
        
        assert result.valid is False
        assert any(v.param_name == "seed" for v in result.violations)

    def test_multiple_violations_detected(self, strict_validator):
        """Test that multiple violations are all detected."""
        params = {
            "temperature": 0.7,
            "top_p": 0.9,
            "seed": "invalid",
        }
        
        result = strict_validator.validate_deterministic(params)
        
        assert result.valid is False
        assert len(result.violations) == 3

    def test_check_temperature_method(self, strict_validator):
        """Test check_temperature method."""
        assert strict_validator.check_temperature(0.0) is True
        assert strict_validator.check_temperature(0.7) is False

    def test_check_top_p_method(self, strict_validator):
        """Test check_top_p method."""
        assert strict_validator.check_top_p(0.1) is True
        assert strict_validator.check_top_p(0.05) is True
        assert strict_validator.check_top_p(0.9) is False

    def test_check_seed_method(self, strict_validator):
        """Test check_seed method."""
        assert strict_validator.check_seed(42) is True
        assert strict_validator.check_seed(0) is True
        assert strict_validator.check_seed(-1) is True
        assert strict_validator.check_seed(3.14) is False
        assert strict_validator.check_seed("42") is False
        assert strict_validator.check_seed(True) is False
        assert strict_validator.check_seed(False) is False


# =============================================================================
# Test Relaxed Mode
# =============================================================================

class TestRelaxedModeAllowsFlexibility:
    """Tests for relaxed mode allowing flexibility."""

    def test_invalid_temperature_passes(self, relaxed_validator):
        """Test that non-zero temperature passes in relaxed mode."""
        params = {
            "temperature": 0.7,
            "top_p": 0.9,
            "seed": 42,
        }
        
        result = relaxed_validator.validate_deterministic(params)
        
        assert result.valid is True

    def test_missing_seed_passes_if_not_required(self):
        """Test that missing seed passes if not required."""
        config = HyperparameterConfig(
            enforcement=EnforcementMode.RELAXED,
            on_violation=ViolationAction.WARN,
            require_seed=False,
        )
        validator = HyperparameterValidator(config)
        
        params = {
            "temperature": 0.7,
            "top_p": 0.9,
        }
        
        result = validator.validate_deterministic(params)
        
        assert result.valid is True


# =============================================================================
# Test Auto-Fix Mode
# =============================================================================

class TestAutoFixWorks:
    """Tests for auto-fix mode correcting parameters."""

    def test_temperature_auto_fixed(self, auto_fix_validator):
        """Test that temperature is auto-fixed to 0.0."""
        params = {
            "temperature": 0.7,
            "top_p": 0.1,
            "seed": 42,
        }
        
        result = auto_fix_validator.validate_deterministic(params)
        
        assert result.valid is True
        assert result.was_auto_fixed is True
        assert result.fixed_params["temperature"] == 0.0

    def test_top_p_auto_fixed(self, auto_fix_validator):
        """Test that top_p is auto-fixed to 0.1."""
        params = {
            "temperature": 0.0,
            "top_p": 0.9,
            "seed": 42,
        }
        
        result = auto_fix_validator.validate_deterministic(params)
        
        assert result.valid is True
        assert result.was_auto_fixed is True
        assert result.fixed_params["top_p"] == 0.1

    def test_seed_auto_fixed_from_string(self, auto_fix_validator):
        """Test that string seed is converted to int."""
        params = {
            "temperature": 0.0,
            "top_p": 0.1,
            "seed": "42",
        }
        
        result = auto_fix_validator.validate_deterministic(params)
        
        assert result.valid is True
        assert result.was_auto_fixed is True
        assert result.fixed_params["seed"] == 42
        assert isinstance(result.fixed_params["seed"], int)

    def test_seed_auto_fixed_from_bool(self, auto_fix_validator):
        """Test that boolean seed is converted to int."""
        params = {
            "temperature": 0.0,
            "top_p": 0.1,
            "seed": True,
        }
        
        result = auto_fix_validator.validate_deterministic(params)
        
        assert result.valid is True
        assert result.was_auto_fixed is True
        assert result.fixed_params["seed"] == 1

    def test_all_params_auto_fixed(self, auto_fix_validator):
        """Test that all parameters are auto-fixed together."""
        params = {
            "temperature": 0.7,
            "top_p": 0.9,
            "seed": "42",
        }
        
        result = auto_fix_validator.validate_deterministic(params)
        
        assert result.valid is True
        assert result.was_auto_fixed is True
        assert result.fixed_params["temperature"] == 0.0
        assert result.fixed_params["top_p"] == 0.1
        assert result.fixed_params["seed"] == 42

    def test_auto_fix_preserves_other_params(self, auto_fix_validator):
        """Test that auto-fix preserves non-violating params."""
        params = {
            "temperature": 0.7,
            "top_p": 0.9,
            "seed": 42,
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "test"}],
        }
        
        result = auto_fix_validator.validate_deterministic(params)
        
        assert result.fixed_params["model"] == "gpt-4"
        assert result.fixed_params["messages"] == [{"role": "user", "content": "test"}]

    def test_cannot_auto_fix_invalid_seed(self, auto_fix_validator):
        """Test that invalid seed values cannot be auto-fixed."""
        params = {
            "temperature": 0.0,
            "top_p": 0.1,
            "seed": "not_a_number",
        }
        
        result = auto_fix_validator.validate_deterministic(params)
        
        # Should still fail because seed can't be converted
        assert result.valid is False

    def test_cannot_auto_fix_missing_seed(self, auto_fix_validator):
        """Test that missing seed cannot be auto-fixed."""
        params = {
            "temperature": 0.0,
            "top_p": 0.1,
        }
        
        result = auto_fix_validator.validate_deterministic(params)
        
        assert result.valid is False


# =============================================================================
# Test Gate Integration
# =============================================================================

class TestGateBlocksOnViolation:
    """Tests for gate blocking on hyperparameter violations."""

    def test_gate_passes_with_valid_params(self, valid_params):
        """Test that gate passes with valid parameters."""
        manager = GateManager()
        context = {
            "llm_params": valid_params,
            "determinism_mode": "strict",
        }
        
        result = manager.run_pre_exec_gates(context)
        
        # Find the hyperparameter check result
        hyperparam_result = next(
            (r for r in result.pre_exec_results if r.gate_name == "Hyperparameter Check"),
            None
        )
        
        assert hyperparam_result is not None
        assert hyperparam_result.result == GateResult.PASS

    def test_gate_blocks_on_violation(self):
        """Test that GATE_00 blocks when hyperparameters violated."""
        manager = GateManager()
        context = {
            "llm_params": {
                "temperature": 0.7,
                "top_p": 0.9,
            },
            "determinism_mode": "strict",
        }
        
        result = manager.run_pre_exec_gates(context)
        
        # Find the hyperparameter check result
        hyperparam_result = next(
            (r for r in result.pre_exec_results if r.gate_name == "Hyperparameter Check"),
            None
        )
        
        assert hyperparam_result is not None
        assert hyperparam_result.result == GateResult.FAIL
        assert "Hyperparameter Check" in result.failed_gates

    def test_gate_auto_fixes_when_configured(self):
        """Test that gate auto-fixes when configured."""
        manager = GateManager()
        context = {
            "llm_params": {
                "temperature": 0.7,
                "top_p": 0.9,
                "seed": 42,
            },
            "determinism_mode": "strict",
            "hyperparameters": {
                "on_violation": "auto_fix",
            },
        }
        
        result = manager.run_pre_exec_gates(context)
        
        # Find the hyperparameter check result
        hyperparam_result = next(
            (r for r in result.pre_exec_results if r.gate_name == "Hyperparameter Check"),
            None
        )
        
        assert hyperparam_result is not None
        assert hyperparam_result.result == GateResult.PASS
        # Check that params were auto-fixed in context
        assert context["llm_params"]["temperature"] == 0.0
        assert context["llm_params"]["top_p"] == 0.1

    def test_gate_warns_in_warn_mode(self):
        """Test that gate warns but passes in warn mode."""
        manager = GateManager()
        context = {
            "llm_params": {
                "temperature": 0.7,
                "top_p": 0.9,
                "seed": 42,
            },
            "determinism_mode": "strict",
            "hyperparameters": {
                "on_violation": "warn",
            },
        }
        
        result = manager.run_pre_exec_gates(context)
        
        # Find the hyperparameter check result
        hyperparam_result = next(
            (r for r in result.pre_exec_results if r.gate_name == "Hyperparameter Check"),
            None
        )
        
        assert hyperparam_result is not None
        assert hyperparam_result.result == GateResult.PASS

    def test_gate_skips_when_no_params(self):
        """Test that gate passes when no LLM params provided."""
        manager = GateManager()
        context = {
            "determinism_mode": "strict",
        }
        
        result = manager.run_pre_exec_gates(context)
        
        # Find the hyperparameter check result
        hyperparam_result = next(
            (r for r in result.pre_exec_results if r.gate_name == "Hyperparameter Check"),
            None
        )
        
        assert hyperparam_result is not None
        assert hyperparam_result.result == GateResult.PASS


# =============================================================================
# Test Statistics Tracking
# =============================================================================

class TestStatisticsTracking:
    """Tests for validation statistics tracking."""

    def test_stats_increment_on_validation(self, strict_validator, valid_params):
        """Test that stats are incremented on validation."""
        initial_stats = strict_validator.get_stats()
        assert initial_stats["total_validations"] == 0
        
        strict_validator.validate_deterministic(valid_params)
        
        stats = strict_validator.get_stats()
        assert stats["total_validations"] == 1
        assert stats["valid_count"] == 1

    def test_stats_increment_on_violation(self, strict_validator):
        """Test that stats are incremented on violation."""
        params = {"temperature": 0.7}
        
        strict_validator.validate_deterministic(params)
        
        stats = strict_validator.get_stats()
        assert stats["total_validations"] == 1
        assert stats["violation_count"] == 1
        assert stats["reject_count"] == 1

    def test_stats_increment_on_auto_fix(self, auto_fix_validator):
        """Test that stats are incremented on auto-fix."""
        params = {"temperature": 0.7, "seed": 42}
        
        auto_fix_validator.validate_deterministic(params)
        
        stats = auto_fix_validator.get_stats()
        assert stats["auto_fix_count"] == 1

    def test_reset_stats(self, strict_validator, valid_params):
        """Test that stats can be reset."""
        strict_validator.validate_deterministic(valid_params)
        
        strict_validator.reset_stats()
        
        stats = strict_validator.get_stats()
        assert stats["total_validations"] == 0


# =============================================================================
# Test Configuration Updates
# =============================================================================

class TestConfigurationUpdates:
    """Tests for configuration updates."""

    def test_update_config(self, strict_validator):
        """Test updating validator configuration."""
        new_config = HyperparameterConfig(
            enforcement=EnforcementMode.RELAXED,
            on_violation=ViolationAction.WARN,
        )
        
        strict_validator.update_config(new_config)
        
        assert strict_validator.config.enforcement == EnforcementMode.RELAXED
        assert strict_validator.config.on_violation == ViolationAction.WARN


# =============================================================================
# Test Serialization
# =============================================================================

class TestSerialization:
    """Tests for serialization methods."""

    def test_violation_to_dict(self):
        """Test violation serialization."""
        violation = HyperparameterViolation(
            param_name="temperature",
            expected="0.0",
            actual=0.7,
            severity=5,
            message="Temperature must be 0.0",
            auto_fix_value=0.0,
        )
        
        d = violation.to_dict()
        
        assert d["param_name"] == "temperature"
        assert d["expected"] == "0.0"
        assert d["actual"] == 0.7
        assert d["severity"] == 5
        assert d["auto_fix_value"] == 0.0

    def test_result_to_dict(self):
        """Test result serialization."""
        result = HyperparameterValidationResult(
            valid=True,
            violations=[],
            fixed_params={"temperature": 0.0},
            was_auto_fixed=True,
        )
        
        d = result.to_dict()
        
        assert d["valid"] is True
        assert d["violations"] == []
        assert d["fixed_params"]["temperature"] == 0.0
        assert d["was_auto_fixed"] is True

    def test_config_to_dict(self):
        """Test config serialization."""
        config = HyperparameterConfig(
            enforcement=EnforcementMode.STRICT,
            on_violation=ViolationAction.REJECT,
        )
        
        d = config.to_dict()
        
        assert d["enforcement"] == "strict"
        assert d["on_violation"] == "reject"
        assert d["allowed_temperature"] == 0.0
        assert d["max_top_p"] == 0.1


# =============================================================================
# Test Auto-Fix Method
# =============================================================================

class TestAutoFixMethod:
    """Tests for the auto_fix method."""

    def test_auto_fix_temperature(self, strict_validator):
        """Test auto_fix method for temperature."""
        params = {"temperature": 0.7, "seed": 42}
        
        fixed = strict_validator.auto_fix(params)
        
        assert fixed["temperature"] == 0.0

    def test_auto_fix_top_p(self, strict_validator):
        """Test auto_fix method for top_p."""
        params = {"top_p": 0.9, "seed": 42}
        
        fixed = strict_validator.auto_fix(params)
        
        assert fixed["top_p"] == 0.1

    def test_auto_fix_seed_from_string(self, strict_validator):
        """Test auto_fix method for seed conversion."""
        params = {"seed": "42"}
        
        fixed = strict_validator.auto_fix(params)
        
        assert fixed["seed"] == 42
        assert isinstance(fixed["seed"], int)

    def test_auto_fix_preserves_valid_params(self, strict_validator, valid_params):
        """Test that auto_fix preserves already valid params."""
        fixed = strict_validator.auto_fix(valid_params)
        
        assert fixed["temperature"] == 0.0
        assert fixed["top_p"] == 0.1
        assert fixed["seed"] == 42


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
