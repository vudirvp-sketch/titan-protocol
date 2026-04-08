"""
Tests for ITEM-RES-143: DeterministicSeed Injection Enforcement.

Comprehensive test suite for seed injection functionality including:
- Seed generation
- Parameter injection
- Temperature enforcement
- Checkpoint integration
- Validation
- Statistics tracking
"""

import pytest
import hashlib
from unittest.mock import patch, MagicMock

from src.llm.seed_injection import (
    SeedInjector,
    SeedInjectionConfig,
    SeedInjectionStats,
    CheckpointSeedData,
    SeedInjectionError,
    TemperatureViolationError,
    MissingSeedError,
    create_seed_injector,
    inject_deterministic_seed
)


class TestSeedInjectorInit:
    """Tests for SeedInjector initialization."""
    
    def test_init_with_default_config(self):
        """Test initialization with no config."""
        injector = SeedInjector()
        
        assert injector.config.enforce is True
        assert injector.config.require_temperature_zero is True
        assert injector.config.inject_on_all_calls is True
        assert injector._current_seed is None
        assert injector._current_session_id is None
    
    def test_init_with_config(self):
        """Test initialization with config."""
        config = {
            "deterministic_seed": {
                "enforce": False,
                "require_temperature_zero": False,
                "inject_on_all_calls": False
            }
        }
        injector = SeedInjector(config)
        
        assert injector.config.enforce is False
        assert injector.config.require_temperature_zero is False
        assert injector.config.inject_on_all_calls is False
    
    def test_init_with_partial_config(self):
        """Test initialization with partial config."""
        config = {
            "deterministic_seed": {
                "enforce": False
            }
        }
        injector = SeedInjector(config)
        
        assert injector.config.enforce is False
        assert injector.config.require_temperature_zero is True  # Default
        assert injector.config.inject_on_all_calls is True  # Default


class TestGenerateSeed:
    """Tests for seed generation."""
    
    def test_generate_seed_deterministic(self):
        """Test that seed generation is deterministic."""
        injector = SeedInjector()
        
        seed1 = injector.generate_seed("session-123")
        seed2 = injector.generate_seed("session-123")
        
        assert seed1 == seed2
        assert isinstance(seed1, int)
    
    def test_generate_seed_different_sessions(self):
        """Test that different sessions produce different seeds."""
        injector = SeedInjector()
        
        seed1 = injector.generate_seed("session-123")
        seed2 = injector.generate_seed("session-456")
        
        assert seed1 != seed2
    
    def test_generate_seed_updates_state(self):
        """Test that generate_seed updates internal state."""
        injector = SeedInjector()
        
        seed = injector.generate_seed("test-session")
        
        assert injector._current_seed == seed
        assert injector._current_session_id == "test-session"
        assert injector.get_current_seed() == seed
        assert injector.get_current_session_id() == "test-session"
    
    def test_generate_seed_matches_timezone_manager(self):
        """Test that seed generation matches TimezoneManager."""
        from src.utils.timezone import TimezoneManager
        
        injector = SeedInjector()
        seed = injector.generate_seed("test-session")
        expected = TimezoneManager.generate_seed("test-session")
        
        assert seed == expected
    
    def test_generate_seed_stats_tracking(self):
        """Test that stats are updated."""
        injector = SeedInjector()
        
        injector.generate_seed("session-1")
        
        assert injector._stats.last_seed == injector._current_seed
        assert injector._stats.last_session_id == "session-1"


class TestInjectSeed:
    """Tests for seed injection into parameters."""
    
    def test_inject_seed_deterministic_mode(self):
        """Test seed injection in deterministic mode."""
        injector = SeedInjector()
        injector.generate_seed("test-session")
        
        params = {"model": "gpt-4", "messages": []}
        result = injector.inject_seed(params, mode="deterministic")
        
        assert "seed" in result
        assert result["seed"] == injector._current_seed
        assert result["temperature"] == 0
        assert result["metadata"]["seed_injected"] is True
    
    def test_inject_seed_sets_temperature_zero(self):
        """Test that temperature is set to 0 in deterministic mode."""
        injector = SeedInjector()
        injector.generate_seed("test-session")
        
        params = {"model": "gpt-4", "temperature": 0.7}
        result = injector.inject_seed(params, mode="deterministic")
        
        assert result["temperature"] == 0
    
    def test_inject_seed_preserves_other_params(self):
        """Test that other parameters are preserved."""
        injector = SeedInjector()
        injector.generate_seed("test-session")
        
        params = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 1000,
            "top_p": 0.9
        }
        result = injector.inject_seed(params, mode="deterministic")
        
        assert result["model"] == "gpt-4"
        assert result["max_tokens"] == 1000
        assert result["top_p"] == 0.9
        assert len(result["messages"]) == 1
    
    def test_inject_seed_non_deterministic_mode(self):
        """Test that seed is not injected in non-deterministic mode when inject_on_all_calls is False."""
        config = {
            "deterministic_seed": {
                "inject_on_all_calls": False
            }
        }
        injector = SeedInjector(config)
        injector.generate_seed("test-session")
        
        params = {"model": "gpt-4"}
        result = injector.inject_seed(params, mode="guided_autonomy")
        
        assert "seed" not in result
    
    def test_inject_seed_on_all_calls_enabled(self):
        """Test that seed is injected on all calls when enabled."""
        injector = SeedInjector()  # Default has inject_on_all_calls=True
        injector.generate_seed("test-session")
        
        params = {"model": "gpt-4"}
        result = injector.inject_seed(params, mode="guided_autonomy")
        
        # Seed should be injected even in non-deterministic mode
        assert "seed" in result
    
    def test_inject_seed_generates_from_session_id(self):
        """Test that passing session_id generates new seed."""
        injector = SeedInjector()
        
        params = {"model": "gpt-4"}
        result = injector.inject_seed(params, mode="deterministic", session_id="new-session")
        
        assert "seed" in result
        assert injector._current_session_id == "new-session"
    
    def test_inject_seed_no_mutation(self):
        """Test that original params are not mutated."""
        injector = SeedInjector()
        injector.generate_seed("test-session")
        
        params = {"model": "gpt-4"}
        result = injector.inject_seed(params, mode="deterministic")
        
        assert "seed" not in params  # Original unchanged
        assert "seed" in result  # Result has seed
    
    def test_inject_seed_updates_stats(self):
        """Test that stats are updated."""
        injector = SeedInjector()
        injector.generate_seed("test-session")
        
        initial = injector._stats.total_injections
        params = {"model": "gpt-4"}
        injector.inject_seed(params, mode="deterministic")
        
        assert injector._stats.total_injections == initial + 1
        assert injector._stats.successful_injections > 0


class TestVerifyDeterministic:
    """Tests for deterministic parameter verification."""
    
    def test_verify_valid_params(self):
        """Test verification of valid parameters."""
        injector = SeedInjector()
        
        params = {"seed": 12345, "temperature": 0}
        
        assert injector.verify_deterministic(params) is True
    
    def test_verify_missing_seed_raises(self):
        """Test that missing seed raises error when enforce is True."""
        injector = SeedInjector()
        
        params = {"temperature": 0}
        
        with pytest.raises(MissingSeedError):
            injector.verify_deterministic(params)
    
    def test_verify_missing_seed_no_raise_when_not_enforced(self):
        """Test that missing seed doesn't raise when enforce is False."""
        config = {"deterministic_seed": {"enforce": False}}
        injector = SeedInjector(config)
        
        params = {"temperature": 0}
        
        assert injector.verify_deterministic(params) is False
    
    def test_verify_nonzero_temperature_raises(self):
        """Test that non-zero temperature raises error when enforce is True."""
        injector = SeedInjector()
        
        params = {"seed": 12345, "temperature": 0.5}
        
        with pytest.raises(TemperatureViolationError):
            injector.verify_deterministic(params)
    
    def test_verify_nonzero_temperature_no_raise_when_not_required(self):
        """Test that non-zero temperature doesn't raise when not required."""
        config = {"deterministic_seed": {"require_temperature_zero": False}}
        injector = SeedInjector(config)
        
        params = {"seed": 12345, "temperature": 0.5}
        
        assert injector.verify_deterministic(params) is True
    
    def test_verify_updates_stats(self):
        """Test that stats are updated."""
        injector = SeedInjector()
        
        params = {"seed": 12345, "temperature": 0}
        injector.verify_deterministic(params)
        
        assert injector._stats.validation_checks > 0


class TestCheckpointIntegration:
    """Tests for checkpoint integration."""
    
    def test_get_checkpoint_seed_data(self):
        """Test getting checkpoint seed data."""
        injector = SeedInjector()
        injector.generate_seed("test-session")
        
        data = injector.get_checkpoint_seed_data(mode="deterministic")
        
        assert data is not None
        assert data.seed == injector._current_seed
        assert data.session_id == "test-session"
        assert data.mode == "deterministic"
        assert data.temperature == 0.0
        assert data.timestamp is not None
    
    def test_get_checkpoint_seed_data_no_seed(self):
        """Test getting checkpoint data when no seed generated."""
        injector = SeedInjector()
        
        data = injector.get_checkpoint_seed_data()
        
        assert data is None
    
    def test_get_checkpoint_seed_data_with_metadata(self):
        """Test checkpoint data includes metadata."""
        injector = SeedInjector()
        injector.generate_seed("test-session")
        
        metadata = {"phase": 4, "model": "gpt-4"}
        data = injector.get_checkpoint_seed_data(metadata=metadata)
        
        assert data.metadata == metadata
    
    def test_checkpoint_seed_data_to_dict(self):
        """Test checkpoint data serialization."""
        data = CheckpointSeedData(
            seed=12345,
            session_id="test-session",
            mode="deterministic",
            timestamp="2024-01-01T00:00:00Z",
            temperature=0.0,
            metadata={"key": "value"}
        )
        
        result = data.to_dict()
        
        assert result["seed"] == 12345
        assert result["session_id"] == "test-session"
        assert result["mode"] == "deterministic"
        assert result["timestamp"] == "2024-01-01T00:00:00Z"
        assert result["temperature"] == 0.0
        assert result["metadata"]["key"] == "value"
    
    def test_checkpoint_seed_data_from_dict(self):
        """Test checkpoint data deserialization."""
        data_dict = {
            "seed": 12345,
            "session_id": "test-session",
            "mode": "deterministic",
            "timestamp": "2024-01-01T00:00:00Z",
            "temperature": 0.0,
            "metadata": {"key": "value"}
        }
        
        data = CheckpointSeedData.from_dict(data_dict)
        
        assert data.seed == 12345
        assert data.session_id == "test-session"
        assert data.mode == "deterministic"
        assert data.timestamp == "2024-01-01T00:00:00Z"
        assert data.temperature == 0.0
        assert data.metadata["key"] == "value"
    
    def test_set_seed_from_checkpoint(self):
        """Test restoring seed from checkpoint."""
        injector = SeedInjector()
        
        checkpoint_data = {
            "seed": 12345,
            "session_id": "restored-session",
            "mode": "deterministic",
            "timestamp": "2024-01-01T00:00:00Z"
        }
        
        injector.set_seed_from_checkpoint(checkpoint_data)
        
        assert injector._current_seed == 12345
        assert injector._current_session_id == "restored-session"
    
    def test_roundtrip_checkpoint(self):
        """Test full roundtrip: generate -> checkpoint -> restore."""
        injector1 = SeedInjector()
        injector1.generate_seed("test-session")
        
        # Get checkpoint data
        checkpoint = injector1.get_checkpoint_seed_data()
        checkpoint_dict = checkpoint.to_dict()
        
        # Create new injector and restore
        injector2 = SeedInjector()
        injector2.set_seed_from_checkpoint(checkpoint_dict)
        
        assert injector2._current_seed == injector1._current_seed
        assert injector2._current_session_id == injector1._current_session_id


class TestStatistics:
    """Tests for statistics tracking."""
    
    def test_stats_initial_state(self):
        """Test initial stats state."""
        injector = SeedInjector()
        stats = injector.get_stats()
        
        assert stats["total_injections"] == 0
        assert stats["successful_injections"] == 0
        assert stats["validation_checks"] == 0
        assert stats["validation_failures"] == 0
        assert stats["temperature_violations"] == 0
        assert stats["missing_seed_violations"] == 0
    
    def test_stats_track_injections(self):
        """Test tracking of injections."""
        injector = SeedInjector()
        injector.generate_seed("test-session")
        
        params = {"model": "gpt-4"}
        injector.inject_seed(params, mode="deterministic")
        injector.inject_seed(params, mode="deterministic")
        
        stats = injector.get_stats()
        assert stats["total_injections"] == 2
        assert stats["successful_injections"] == 2
    
    def test_stats_track_validations(self):
        """Test tracking of validations."""
        config = {"deterministic_seed": {"enforce": False}}
        injector = SeedInjector(config)
        
        injector.verify_deterministic({"seed": 123, "temperature": 0})
        injector.verify_deterministic({"temperature": 0})  # Missing seed
        
        stats = injector.get_stats()
        assert stats["validation_checks"] == 2
        assert stats["validation_failures"] == 1
        assert stats["missing_seed_violations"] == 1
    
    def test_stats_track_temperature_violations(self):
        """Test tracking of temperature violations."""
        config = {"deterministic_seed": {"enforce": False}}
        injector = SeedInjector(config)
        
        injector.verify_deterministic({"seed": 123, "temperature": 0.5})
        
        stats = injector.get_stats()
        assert stats["temperature_violations"] == 1


class TestReset:
    """Tests for reset functionality."""
    
    def test_reset_clears_state(self):
        """Test that reset clears current state."""
        injector = SeedInjector()
        injector.generate_seed("test-session")
        
        injector.reset()
        
        assert injector._current_seed is None
        assert injector._current_session_id is None
    
    def test_reset_preserves_stats(self):
        """Test that reset preserves statistics."""
        injector = SeedInjector()
        injector.generate_seed("test-session")
        injector.inject_seed({"model": "gpt-4"}, mode="deterministic")
        
        stats_before = injector.get_stats()
        injector.reset()
        stats_after = injector.get_stats()
        
        assert stats_after["total_injections"] == stats_before["total_injections"]


class TestHelperFunctions:
    """Tests for helper functions."""
    
    def test_create_seed_injector(self):
        """Test factory function."""
        config = {
            "deterministic_seed": {
                "enforce": False
            }
        }
        
        injector = create_seed_injector(config)
        
        assert isinstance(injector, SeedInjector)
        assert injector.config.enforce is False
    
    def test_inject_deterministic_seed(self):
        """Test convenience function."""
        params = {"model": "gpt-4", "temperature": 0.7}
        
        result = inject_deterministic_seed(
            params, 
            mode="deterministic", 
            session_id="test-session"
        )
        
        assert "seed" in result
        assert result["temperature"] == 0


class TestIsDeterministicMode:
    """Tests for mode checking."""
    
    def test_is_deterministic_mode_exact(self):
        """Test exact mode match."""
        injector = SeedInjector()
        
        assert injector.is_deterministic_mode("deterministic") is True
        assert injector.is_deterministic_mode("DETERMINISTIC") is True
        assert injector.is_deterministic_mode("Deterministic") is True
    
    def test_is_deterministic_mode_variant(self):
        """Test mode variant."""
        injector = SeedInjector()
        
        assert injector.is_deterministic_mode("deterministic_mode") is True
    
    def test_is_not_deterministic_mode(self):
        """Test non-deterministic modes."""
        injector = SeedInjector()
        
        assert injector.is_deterministic_mode("guided_autonomy") is False
        assert injector.is_deterministic_mode("fast_prototype") is False
        assert injector.is_deterministic_mode("fast") is False


class TestSeedInjectionConfig:
    """Tests for SeedInjectionConfig dataclass."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = SeedInjectionConfig()
        
        assert config.enforce is True
        assert config.require_temperature_zero is True
        assert config.inject_on_all_calls is True


class TestSeedInjectionStats:
    """Tests for SeedInjectionStats dataclass."""
    
    def test_default_values(self):
        """Test default stats values."""
        stats = SeedInjectionStats()
        
        assert stats.total_injections == 0
        assert stats.successful_injections == 0
        assert stats.validation_checks == 0
        assert stats.validation_failures == 0
        assert stats.temperature_violations == 0
        assert stats.missing_seed_violations == 0
        assert stats.last_seed is None
        assert stats.last_session_id is None
    
    def test_to_dict(self):
        """Test stats serialization."""
        stats = SeedInjectionStats(
            total_injections=10,
            successful_injections=9,
            validation_checks=5,
            validation_failures=1,
            temperature_violations=2,
            missing_seed_violations=3,
            last_seed=12345,
            last_session_id="test"
        )
        
        result = stats.to_dict()
        
        assert result["total_injections"] == 10
        assert result["successful_injections"] == 9
        assert result["validation_checks"] == 5
        assert result["validation_failures"] == 1
        assert result["temperature_violations"] == 2
        assert result["missing_seed_violations"] == 3
        assert result["last_seed"] == 12345
        assert result["last_session_id"] == "test"


class TestReproducibility:
    """Tests for reproducibility guarantees."""
    
    def test_same_seed_same_output_params(self):
        """Test that same seed produces same parameters."""
        injector1 = SeedInjector()
        injector2 = SeedInjector()
        
        injector1.generate_seed("shared-session")
        injector2.generate_seed("shared-session")
        
        params = {"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}]}
        
        result1 = injector1.inject_seed(params.copy(), mode="deterministic")
        result2 = injector2.inject_seed(params.copy(), mode="deterministic")
        
        assert result1["seed"] == result2["seed"]
        assert result1["temperature"] == result2["temperature"]
    
    def test_checkpoint_reproducibility(self):
        """Test that checkpoint enables exact reproduction."""
        # Session 1: Generate and save to checkpoint
        injector1 = SeedInjector()
        injector1.generate_seed("original-session")
        checkpoint = injector1.get_checkpoint_seed_data().to_dict()
        
        # Simulate session 2: Restore from checkpoint
        injector2 = SeedInjector()
        injector2.set_seed_from_checkpoint(checkpoint)
        
        # Both should produce same params
        params = {"model": "gpt-4"}
        result1 = injector1.inject_seed(params.copy(), mode="deterministic")
        result2 = injector2.inject_seed(params.copy(), mode="deterministic")
        
        assert result1["seed"] == result2["seed"]


class TestEdgeCases:
    """Tests for edge cases."""
    
    def test_inject_with_existing_metadata(self):
        """Test injection when params already have metadata."""
        injector = SeedInjector()
        injector.generate_seed("test-session")
        
        params = {"model": "gpt-4", "metadata": {"existing": "value"}}
        result = injector.inject_seed(params, mode="deterministic")
        
        assert result["metadata"]["existing"] == "value"
        assert result["metadata"]["seed_injected"] is True
    
    def test_empty_params(self):
        """Test injection with empty params."""
        injector = SeedInjector()
        injector.generate_seed("test-session")
        
        result = injector.inject_seed({}, mode="deterministic")
        
        assert "seed" in result
        assert "temperature" in result
    
    def test_none_session_id(self):
        """Test behavior with None session_id in deterministic mode."""
        config = {"deterministic_seed": {"enforce": False}}
        injector = SeedInjector(config)
        
        # With enforce=False, should not crash and should not inject seed
        result = injector.inject_seed({"model": "gpt-4"}, mode="deterministic")
        
        # Without a seed generated, seed should not be present
        assert "seed" not in result
    
    def test_none_session_id_enforced_raises(self):
        """Test that deterministic mode with enforce raises error without session_id."""
        injector = SeedInjector()  # enforce=True by default
        
        # Should raise SeedInjectionError when enforce=True and no seed
        with pytest.raises(SeedInjectionError):
            injector.inject_seed({"model": "gpt-4"}, mode="deterministic")


class TestIntegrationWithRouter:
    """Tests for integration with ModelRouter modes."""
    
    def test_deterministic_mode_string_variants(self):
        """Test various deterministic mode string representations."""
        injector = SeedInjector()
        injector.generate_seed("test-session")
        
        for mode in ["deterministic", "DETERMINISTIC", "Deterministic", "deterministic_mode"]:
            result = injector.inject_seed({"model": "gpt-4"}, mode=mode)
            assert "seed" in result, f"Failed for mode: {mode}"
            assert result["temperature"] == 0, f"Failed for mode: {mode}"
    
    def test_guided_autonomy_injects_when_configured(self):
        """Test that guided_autonomy mode injects when inject_on_all_calls=True."""
        injector = SeedInjector()  # Default has inject_on_all_calls=True
        injector.generate_seed("test-session")
        
        result = injector.inject_seed({"model": "gpt-4"}, mode="guided_autonomy")
        
        # Seed injected but temperature not forced to 0
        assert "seed" in result
    
    def test_fast_prototype_injects_when_configured(self):
        """Test that fast_prototype mode injects when inject_on_all_calls=True."""
        injector = SeedInjector()  # Default has inject_on_all_calls=True
        injector.generate_seed("test-session")
        
        result = injector.inject_seed({"model": "gpt-4"}, mode="fast_prototype")
        
        assert "seed" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
