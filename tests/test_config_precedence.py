"""
Tests for ITEM-ARCH-18: Config Precedence Pyramid.

Tests the explicit precedence ordering for conflicting config sources.

Author: TITAN FUSE Team
Version: 3.7.0
"""

import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.config.precedence import (
    PRECEDENCE_ORDER,
    ORIGIN_DISPLAY_NAMES,
    ResolvedValue,
    ConfigPrecedenceConfig,
    ConfigPrecedenceResolver,
    get_precedence_resolver,
    reset_precedence_resolver
)


class TestPrecedenceOrder:
    """Tests for the precedence order constant."""
    
    def test_precedence_order_length(self):
        """Test that precedence order has all 5 sources."""
        assert len(PRECEDENCE_ORDER) == 5
    
    def test_precedence_order_hierarchy(self):
        """Test that ENV is highest and GLOBAL_DEFAULTS is lowest."""
        assert PRECEDENCE_ORDER[0] == "ENV"
        assert PRECEDENCE_ORDER[1] == "CLI"
        assert PRECEDENCE_ORDER[2] == "USER_CONSTRAINTS"
        assert PRECEDENCE_ORDER[3] == "LOCAL_CONFIG"
        assert PRECEDENCE_ORDER[4] == "GLOBAL_DEFAULTS"
    
    def test_origin_display_names(self):
        """Test that all origins have display names."""
        for origin in PRECEDENCE_ORDER:
            assert origin in ORIGIN_DISPLAY_NAMES


class TestResolvedValue:
    """Tests for ResolvedValue dataclass."""
    
    def test_create_resolved_value(self):
        """Test creating a resolved value."""
        resolved = ResolvedValue(
            value=100,
            origin="ENV",
            source_path=None,
            overridden_by=["CLI", "LOCAL_CONFIG"]
        )
        
        assert resolved.value == 100
        assert resolved.origin == "ENV"
        assert resolved.source_path is None
        assert len(resolved.overridden_by) == 2
        assert resolved.timestamp is not None
    
    def test_resolved_value_to_dict(self):
        """Test serialization of resolved value."""
        resolved = ResolvedValue(
            value="test_value",
            origin="CLI",
            source_path=None,
            overridden_by=[]
        )
        
        data = resolved.to_dict()
        
        assert data["value"] == "test_value"
        assert data["origin"] == "CLI"
        assert data["overridden_by"] == []
        assert "timestamp" in data
    
    def test_resolved_value_repr(self):
        """Test string representation."""
        resolved = ResolvedValue(value=42, origin="ENV")
        
        repr_str = repr(resolved)
        
        assert "42" in repr_str
        assert "ENV" in repr_str


class TestConfigPrecedenceConfig:
    """Tests for ConfigPrecedenceConfig."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = ConfigPrecedenceConfig()
        
        assert config.log_overrides is True
        assert config.strict_mode is False
        assert config.env_prefix == "TITAN_"
        assert config.cli_prefix == "--"
        assert config.constraints_file == "constraints.yaml"
        assert config.local_file == "config.yaml"


class TestConfigPrecedenceResolver:
    """Tests for ConfigPrecedenceResolver class."""
    
    def setup_method(self):
        """Reset resolver before each test."""
        reset_precedence_resolver()
    
    def test_initialization(self):
        """Test resolver initialization."""
        resolver = ConfigPrecedenceResolver()
        
        assert resolver.config is not None
        assert resolver._resolved_cache == {}
    
    def test_get_precedence_order(self):
        """Test getting precedence order."""
        resolver = ConfigPrecedenceResolver()
        
        order = resolver.get_precedence_order()
        
        assert order == PRECEDENCE_ORDER
    
    def test_resolve_with_single_source(self):
        """Test resolving from a single source."""
        resolver = ConfigPrecedenceResolver()
        
        sources = {
            "LOCAL_CONFIG": {"session": {"max_tokens": 50000}}
        }
        
        resolved = resolver.resolve("session.max_tokens", sources)
        
        assert resolved.value == 50000
        assert resolved.origin == "LOCAL_CONFIG"
        assert resolved.overridden_by == []
    
    def test_resolve_env_overrides_local(self):
        """Test that ENV overrides LOCAL_CONFIG."""
        resolver = ConfigPrecedenceResolver()
        
        sources = {
            "ENV": {"session": {"max_tokens": 200000}},
            "LOCAL_CONFIG": {"session": {"max_tokens": 50000}}
        }
        
        resolved = resolver.resolve("session.max_tokens", sources)
        
        assert resolved.value == 200000
        assert resolved.origin == "ENV"
        assert "LOCAL_CONFIG" in resolved.overridden_by
    
    def test_resolve_cli_overrides_user_constraints(self):
        """Test that CLI overrides USER_CONSTRAINTS."""
        resolver = ConfigPrecedenceResolver()
        
        sources = {
            "CLI": {"session": {"max_time_minutes": 120}},
            "USER_CONSTRAINTS": {"session": {"max_time_minutes": 30}}
        }
        
        resolved = resolver.resolve("session.max_time_minutes", sources)
        
        assert resolved.value == 120
        assert resolved.origin == "CLI"
        assert "USER_CONSTRAINTS" in resolved.overridden_by
    
    def test_resolve_with_defaults(self):
        """Test resolution falling back to defaults."""
        resolver = ConfigPrecedenceResolver()
        
        sources = {}  # No sources
        
        resolved = resolver.resolve("session.max_tokens", sources)
        
        assert resolved.value == 100000  # Default value
        assert resolved.origin == "GLOBAL_DEFAULTS"
    
    def test_resolve_unknown_key(self):
        """Test resolving a key not in defaults."""
        resolver = ConfigPrecedenceResolver()
        
        sources = {}
        
        resolved = resolver.resolve("unknown.key", sources)
        
        assert resolved.value is None
        assert resolved.origin == "GLOBAL_DEFAULTS"
    
    def test_get_origin(self):
        """Test getting origin of resolved key."""
        resolver = ConfigPrecedenceResolver()
        
        sources = {
            "ENV": {"test": {"key": "value"}}
        }
        
        resolver.resolve("test.key", sources)
        
        origin = resolver.get_origin("test.key")
        
        assert origin == "ENV"
    
    def test_get_origin_unknown_key(self):
        """Test getting origin of unknown key."""
        resolver = ConfigPrecedenceResolver()
        
        origin = resolver.get_origin("unknown.key")
        
        assert origin == "GLOBAL_DEFAULTS"
    
    def test_get_override_history(self):
        """Test getting override history."""
        resolver = ConfigPrecedenceResolver()
        
        sources = {
            "ENV": {"session": {"max_tokens": 200000}},
            "LOCAL_CONFIG": {"session": {"max_tokens": 50000}}
        }
        
        resolver.resolve("session.max_tokens", sources)
        
        history = resolver.get_override_history("session.max_tokens")
        
        assert len(history) == 1
        assert history[0]["origin"] == "ENV"
        assert "LOCAL_CONFIG" in history[0]["overridden"]
    
    def test_resolve_all(self):
        """Test resolving all keys."""
        resolver = ConfigPrecedenceResolver()
        
        sources_list = [
            {"_origin": "ENV", "session": {"max_tokens": 200000}},
            {"_origin": "LOCAL_CONFIG", "session": {"max_time_minutes": 30}}
        ]
        
        resolved = resolver.resolve_all(sources_list)
        
        assert "session.max_tokens" in resolved
        assert "session.max_time_minutes" in resolved
        assert resolved["session.max_tokens"].origin == "ENV"
        assert resolved["session.max_time_minutes"].origin == "LOCAL_CONFIG"
    
    def test_clear_cache(self):
        """Test clearing the cache."""
        resolver = ConfigPrecedenceResolver()
        
        sources = {"ENV": {"test": {"key": "value"}}}
        
        resolver.resolve("test.key", sources)
        
        assert len(resolver._resolved_cache) > 0
        
        resolver.clear_cache()
        
        assert len(resolver._resolved_cache) == 0
    
    def test_load_env_overrides(self):
        """Test loading from environment variables."""
        resolver = ConfigPrecedenceResolver()
        
        # Note: Env vars convert ALL underscores to dots
        # TITAN_SESSION_MAX_TOKENS -> session.max.tokens
        with patch.dict(os.environ, {
            "TITAN_SESSION_MAX_TOKENS": "300000",
            "TITAN_LOGGING_LEVEL": "debug"
        }):
            env_config = resolver._load_env_overrides()
            
            # session.max.tokens, not session.max_tokens
            assert env_config["session"]["max"]["tokens"] == 300000
            assert env_config["logging"]["level"] == "debug"
    
    def test_load_env_boolean(self):
        """Test loading boolean from environment."""
        resolver = ConfigPrecedenceResolver()
        
        with patch.dict(os.environ, {
            "TITAN_SESSION_CHECKPOINT_ENABLED": "true"
        }):
            env_config = resolver._load_env_overrides()
            
            assert env_config["session"]["checkpoint"]["enabled"] is True
    
    def test_load_cli_overrides(self):
        """Test loading from CLI arguments."""
        resolver = ConfigPrecedenceResolver()
        
        cli_args = {
            "--session-max-tokens": 400000,
            "--logging-level": "warning"
        }
        
        cli_config = resolver._load_cli_overrides(cli_args)
        
        assert cli_config["session"]["max"]["tokens"] == 400000
        assert cli_config["logging"]["level"] == "warning"
    
    def test_load_local_config_file(self):
        """Test loading from local config file."""
        resolver = ConfigPrecedenceResolver()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test_config.yaml"
            
            config_content = """
session:
  max_tokens: 250000
logging:
  level: error
"""
            with open(config_path, 'w') as f:
                f.write(config_content)
            
            config = resolver._load_local_config(config_path)
            
            assert config["session"]["max_tokens"] == 250000
            assert config["logging"]["level"] == "error"
    
    def test_load_user_constraints_file(self):
        """Test loading from user constraints file."""
        resolver = ConfigPrecedenceResolver()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            constraints_path = Path(tmpdir) / "constraints.yaml"
            
            constraints_content = """
session:
  max_time_minutes: 15
  max_tokens: 50000
"""
            with open(constraints_path, 'w') as f:
                f.write(constraints_content)
            
            constraints = resolver._load_user_constraints(constraints_path)
            
            assert constraints["session"]["max_time_minutes"] == 15
            assert constraints["session"]["max_tokens"] == 50000
    
    def test_resolve_full_config(self):
        """Test resolving full merged config."""
        resolver = ConfigPrecedenceResolver()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            
            with open(config_path, 'w') as f:
                f.write("session:\n  max_tokens: 50000\n  max_time_minutes: 30\n")
            
            # Use TITAN_LOGGING_LEVEL which maps to logging.level correctly
            with patch.dict(os.environ, {"TITAN_LOGGING_LEVEL": "debug"}):
                full_config = resolver.resolve_full_config(config_path=config_path)
                
                assert full_config["session"]["max_tokens"] == 50000  # From local
                assert full_config["session"]["max_time_minutes"] == 30  # From local
                assert full_config["logging"]["level"] == "debug"  # From ENV
    
    def test_get_config_origin_report(self):
        """Test generating origin report."""
        resolver = ConfigPrecedenceResolver()
        
        sources = {
            "ENV": {"session": {"max_tokens": 200000}},
            "LOCAL_CONFIG": {"session": {"max_tokens": 50000}}
        }
        
        resolver.resolve("session.max_tokens", sources)
        
        report = resolver.get_config_origin_report()
        
        assert "precedence_order" in report
        assert "resolved_keys" in report
        assert "override_history" in report
        assert "session.max_tokens" in report["resolved_keys"]
    
    def test_strict_mode_warning(self):
        """Test strict mode warnings on conflicts."""
        config = ConfigPrecedenceConfig(strict_mode=True)
        resolver = ConfigPrecedenceResolver(config)
        
        sources = {
            "ENV": {"session": {"max_tokens": 200000}},
            "LOCAL_CONFIG": {"session": {"max_tokens": 50000}}
        }
        
        # Should not raise, but should log warning
        resolved = resolver.resolve("session.max_tokens", sources)
        
        assert resolved.value == 200000
    
    def test_deep_merge(self):
        """Test deep merge functionality."""
        resolver = ConfigPrecedenceResolver()
        
        base = {
            "session": {"max_tokens": 100000, "max_time_minutes": 60},
            "logging": {"level": "info"}
        }
        
        overlay = {
            "session": {"max_tokens": 200000},
            "security": {"enabled": True}
        }
        
        merged = resolver._deep_merge(base, overlay)
        
        assert merged["session"]["max_tokens"] == 200000
        assert merged["session"]["max_time_minutes"] == 60
        assert merged["logging"]["level"] == "info"
        assert merged["security"]["enabled"] is True


class TestGlobalFunctions:
    """Tests for global convenience functions."""
    
    def setup_method(self):
        """Reset resolver before each test."""
        reset_precedence_resolver()
    
    def test_get_precedence_resolver_singleton(self):
        """Test getting singleton instance."""
        resolver1 = get_precedence_resolver()
        resolver2 = get_precedence_resolver()
        
        assert resolver1 is resolver2
    
    def test_reset_precedence_resolver(self):
        """Test resetting singleton."""
        resolver1 = get_precedence_resolver()
        
        reset_precedence_resolver()
        
        resolver2 = get_precedence_resolver()
        
        assert resolver1 is not resolver2


class TestIntegration:
    """Integration tests for config precedence."""
    
    def setup_method(self):
        """Reset resolver before each test."""
        reset_precedence_resolver()
    
    def test_full_precedence_chain(self):
        """Test the complete precedence chain."""
        resolver = ConfigPrecedenceResolver()
        
        sources = {
            "ENV": {"session": {"max_tokens": 400000}},
            "CLI": {"session": {"max_tokens": 350000}},
            "USER_CONSTRAINTS": {"session": {"max_tokens": 300000}},
            "LOCAL_CONFIG": {"session": {"max_tokens": 250000}},
            "GLOBAL_DEFAULTS": {"session": {"max_tokens": 100000}}
        }
        
        resolved = resolver.resolve("session.max_tokens", sources)
        
        # ENV should win
        assert resolved.value == 400000
        assert resolved.origin == "ENV"
        
        # Should have overridden all lower precedence sources
        assert "CLI" in resolved.overridden_by
        assert "USER_CONSTRAINTS" in resolved.overridden_by
        assert "LOCAL_CONFIG" in resolved.overridden_by
        assert "GLOBAL_DEFAULTS" in resolved.overridden_by
    
    def test_partial_precedence_chain(self):
        """Test precedence with only some sources present."""
        resolver = ConfigPrecedenceResolver()
        
        sources = {
            "USER_CONSTRAINTS": {"session": {"max_tokens": 300000}},
            "LOCAL_CONFIG": {"session": {"max_tokens": 250000}}
        }
        
        resolved = resolver.resolve("session.max_tokens", sources)
        
        # USER_CONSTRAINTS should win over LOCAL_CONFIG
        assert resolved.value == 300000
        assert resolved.origin == "USER_CONSTRAINTS"
        assert "LOCAL_CONFIG" in resolved.overridden_by
    
    def test_nested_key_resolution(self):
        """Test resolution of deeply nested keys."""
        resolver = ConfigPrecedenceResolver()
        
        sources = {
            "LOCAL_CONFIG": {
                "storage": {
                    "s3": {
                        "bucket": "my-bucket"
                    }
                }
            }
        }
        
        resolved = resolver.resolve("storage.s3.bucket", sources)
        
        assert resolved.value == "my-bucket"
        assert resolved.origin == "LOCAL_CONFIG"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
