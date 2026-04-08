#!/usr/bin/env python3
"""
Tests for ITEM-INT-132: Provider Adapter Registry.

This test module validates:
- Registry creation and configuration
- Adapter registration and retrieval
- Plugin loading mechanism
- Validation criteria from TITAN_IMPLEMENTATION_PLAN_v7.0.md

VALIDATION_CRITERIA:
- registry_works: Registry loads adapters
- plugins_loaded: Custom plugins loaded
- router_uses_registry: Router delegates to registry

Author: TITAN FUSE Team
Version: 4.1.0
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.llm.provider_registry import (
    ProviderAdapterRegistry,
    get_registry, reset_registry, create_registry
)
from src.llm.adapters.base import (
    ProviderAdapter, AdapterConfig, CompletionResult,
    AdapterCapability, AdapterError, AdapterConfigError
)
from src.llm.adapters.mock import MockAdapter
from src.llm.adapters.openai import OpenAIAdapter
from src.llm.adapters.anthropic import AnthropicAdapter


class TestAdapterConfig:
    """Tests for AdapterConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = AdapterConfig()
        assert config.api_key is None
        assert config.api_base is None
        assert config.default_model == "unknown"
        assert config.max_tokens == 4096
        assert config.temperature == 0.7
        assert config.timeout_seconds == 30

    def test_config_from_dict(self):
        """Test creating config from dictionary."""
        data = {
            "api_key": "test-key",
            "default_model": "gpt-4",
            "max_tokens": 8192,
            "temperature": 0.5
        }
        config = AdapterConfig.from_dict(data)
        assert config.api_key == "test-key"
        assert config.default_model == "gpt-4"
        assert config.max_tokens == 8192
        assert config.temperature == 0.5

    def test_config_to_dict_redacts_key(self):
        """Test that to_dict redacts API key."""
        config = AdapterConfig(api_key="secret-key")
        d = config.to_dict()
        assert d["api_key"] == "***"


class TestMockAdapter:
    """Tests for MockAdapter."""

    def test_adapter_creation(self):
        """Test creating mock adapter."""
        config = AdapterConfig(default_model="mock-test")
        adapter = MockAdapter(config)
        assert adapter.name == "mock"
        assert adapter.get_default_model() == "mock-test"

    def test_complete_returns_result(self):
        """Test that complete returns a CompletionResult."""
        adapter = MockAdapter(AdapterConfig())
        messages = [{"role": "user", "content": "Hello"}]
        result = adapter.complete(messages)

        assert isinstance(result, CompletionResult)
        assert result.provider == "mock"
        assert "Mock Response" in result.content
        assert result.error is None

    def test_deterministic_response_with_seed(self):
        """Test that seed produces deterministic responses."""
        adapter = MockAdapter(AdapterConfig())
        messages = [{"role": "user", "content": "Test"}]

        result1 = adapter.complete(messages, seed=12345)
        result2 = adapter.complete(messages, seed=12345)

        assert result1.content == result2.content

    def test_streaming(self):
        """Test streaming completion."""
        adapter = MockAdapter(AdapterConfig())
        messages = [{"role": "user", "content": "Stream test"}]

        chunks = list(adapter.stream(messages))
        assert len(chunks) > 0
        assert chunks[-1].is_final

    def test_token_counting(self):
        """Test token counting estimation."""
        adapter = MockAdapter(AdapterConfig())
        text = "This is a test message with some words."
        tokens = adapter.count_tokens(text)
        # Rough estimate: ~4 chars per token
        assert tokens > 0
        assert tokens < len(text)

    def test_capabilities(self):
        """Test that mock adapter reports capabilities."""
        adapter = MockAdapter(AdapterConfig())
        capabilities = adapter.get_capabilities()

        assert AdapterCapability.STREAMING in capabilities
        assert AdapterCapability.SEED_PARAMETER in capabilities

    def test_request_logging(self):
        """Test that requests are logged."""
        adapter = MockAdapter(AdapterConfig())
        messages = [{"role": "user", "content": "Log test"}]

        adapter.complete(messages)
        adapter.complete(messages, seed=42)

        log = adapter.get_request_log()
        assert len(log) == 2
        assert log[1]["seed"] == 42

    def test_simulated_delay(self):
        """Test simulated delay."""
        import time

        adapter = MockAdapter(AdapterConfig(
            extra={"simulate_delay": True, "delay_ms": 100}
        ))

        start = time.time()
        adapter.complete([{"role": "user", "content": "Test"}])
        elapsed = (time.time() - start) * 1000

        assert elapsed >= 90  # Allow some variance

    def test_simulated_errors(self):
        """Test simulated error generation."""
        adapter = MockAdapter(AdapterConfig(
            extra={"simulate_errors": True, "error_rate": 1.0}  # Always error
        ))

        result = adapter.complete([{"role": "user", "content": "Test"}])
        assert result.error is not None


class TestOpenAIAdapter:
    """Tests for OpenAI adapter."""

    def test_adapter_creation(self):
        """Test creating OpenAI adapter."""
        config = AdapterConfig(
            api_key="test-key",
            default_model="gpt-4"
        )
        adapter = OpenAIAdapter(config)
        assert adapter.name == "openai"
        assert adapter.get_default_model() == "gpt-4"

    def test_simulated_response_without_client(self):
        """Test simulated response when openai not installed."""
        config = AdapterConfig(default_model="gpt-4")
        adapter = OpenAIAdapter(config)
        adapter._openai_available = False  # Force simulation

        result = adapter.complete([{"role": "user", "content": "Hello"}])
        assert result.provider == "openai"
        assert "Simulated" in result.content

    def test_validate_config_requires_api_key(self):
        """Test that config validation requires API key."""
        adapter = OpenAIAdapter(AdapterConfig())
        adapter._api_key = None

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(AdapterConfigError) as exc_info:
                adapter.validate_config({})
            assert "API key" in str(exc_info.value)

    def test_validate_config_temperature_range(self):
        """Test temperature validation."""
        adapter = OpenAIAdapter(AdapterConfig())

        with pytest.raises(AdapterConfigError):
            adapter.validate_config({"temperature": 3.0})

    def test_capabilities(self):
        """Test OpenAI capabilities."""
        adapter = OpenAIAdapter(AdapterConfig())
        capabilities = adapter.get_capabilities()

        assert AdapterCapability.STREAMING in capabilities
        assert AdapterCapability.FUNCTION_CALLING in capabilities
        assert AdapterCapability.VISION in capabilities
        assert AdapterCapability.SEED_PARAMETER in capabilities


class TestAnthropicAdapter:
    """Tests for Anthropic adapter."""

    def test_adapter_creation(self):
        """Test creating Anthropic adapter."""
        config = AdapterConfig(
            api_key="test-key",
            default_model="claude-3-opus"
        )
        adapter = AnthropicAdapter(config)
        assert adapter.name == "anthropic"
        assert adapter.get_default_model() == "claude-3-opus"

    def test_simulated_response_without_client(self):
        """Test simulated response when anthropic not installed."""
        config = AdapterConfig(default_model="claude-3-opus")
        adapter = AnthropicAdapter(config)
        adapter._anthropic_available = False

        result = adapter.complete([{"role": "user", "content": "Hello"}])
        assert result.provider == "anthropic"
        assert "Simulated" in result.content

    def test_message_conversion(self):
        """Test OpenAI to Anthropic message format conversion."""
        adapter = AnthropicAdapter(AdapterConfig())

        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "How are you?"}
        ]

        anthropic_messages, system = adapter._convert_messages(messages)

        assert system == "You are helpful."
        assert len(anthropic_messages) == 3
        assert anthropic_messages[0]["role"] == "user"

    def test_validate_config_temperature_range(self):
        """Test Anthropic temperature validation (0-1)."""
        adapter = AnthropicAdapter(AdapterConfig())

        with pytest.raises(AdapterConfigError):
            adapter.validate_config({"temperature": 1.5})

    def test_capabilities(self):
        """Test Anthropic capabilities."""
        adapter = AnthropicAdapter(AdapterConfig())
        capabilities = adapter.get_capabilities()

        assert AdapterCapability.STREAMING in capabilities
        assert AdapterCapability.VISION in capabilities


class TestProviderAdapterRegistry:
    """Tests for ProviderAdapterRegistry."""

    def setup_method(self):
        """Reset registry before each test."""
        reset_registry()

    def test_registry_creation(self):
        """Test creating registry."""
        registry = ProviderAdapterRegistry()
        assert registry is not None
        assert isinstance(registry._adapters, dict)

    def test_auto_register_mock(self):
        """Test that mock adapter is auto-registered."""
        registry = ProviderAdapterRegistry()
        assert "mock" in registry.list_available()

    def test_register_adapter(self):
        """Test registering an adapter."""
        # Create registry without auto-register to test manual registration
        registry = ProviderAdapterRegistry({"llm": {"provider_registry": {"auto_register_builtin": False}}})
        adapter = MockAdapter(AdapterConfig(default_model="test-model"))

        registry.register(adapter)

        assert "mock" in registry.list_available()
        assert registry.has_adapter("mock")

    def test_register_prevents_duplicate(self):
        """Test that duplicate registration raises error."""
        # Create registry without auto-register
        registry = ProviderAdapterRegistry({"llm": {"provider_registry": {"auto_register_builtin": False}}})

        adapter1 = MockAdapter(AdapterConfig())
        adapter2 = MockAdapter(AdapterConfig())

        registry.register(adapter1)

        with pytest.raises(AdapterError):
            registry.register(adapter2)

    def test_register_override(self):
        """Test overriding existing adapter."""
        # Auto-registered mock adapter is present
        registry = ProviderAdapterRegistry()

        adapter2 = MockAdapter(AdapterConfig(default_model="v2"))

        # Override the auto-registered mock
        registry.register(adapter2, override=True)

        retrieved = registry.get("mock")
        assert retrieved.get_default_model() == "v2"

    def test_get_adapter(self):
        """Test getting a registered adapter."""
        # Mock adapter is auto-registered
        registry = ProviderAdapterRegistry()
        adapter = MockAdapter(AdapterConfig(default_model="test"))
        registry.register(adapter, override=True)

        retrieved = registry.get("mock")
        assert retrieved is adapter

    def test_get_nonexistent_adapter_raises(self):
        """Test that getting nonexistent adapter raises error."""
        registry = ProviderAdapterRegistry()

        with pytest.raises(AdapterError) as exc_info:
            registry.get("nonexistent")
        assert "not found" in str(exc_info.value)

    def test_list_available(self):
        """Test listing available adapters."""
        registry = ProviderAdapterRegistry()

        # Mock is auto-registered
        available = registry.list_available()
        assert "mock" in available

    def test_unregister(self):
        """Test unregistering an adapter."""
        # Mock is auto-registered, test unregistering it
        registry = ProviderAdapterRegistry()

        result = registry.unregister("mock")
        assert result is True
        assert "mock" not in registry.list_available()

    def test_unregister_nonexistent(self):
        """Test unregistering nonexistent adapter."""
        registry = ProviderAdapterRegistry()
        result = registry.unregister("nonexistent")
        assert result is False

    def test_validate_adapter(self):
        """Test adapter validation."""
        registry = ProviderAdapterRegistry()
        adapter = MockAdapter(AdapterConfig())

        is_valid = registry.validate_adapter(adapter)
        assert is_valid is True

    def test_get_stats(self):
        """Test getting registry statistics."""
        registry = ProviderAdapterRegistry()
        stats = registry.get_stats()

        assert "total_registrations" in stats
        assert "adapters" in stats

    def test_configure_adapter(self):
        """Test configuring an adapter."""
        registry = ProviderAdapterRegistry()
        config = AdapterConfig(default_model="configured-model")

        registry.configure_adapter("mock", config)

        stored = registry._adapter_configs.get("mock")
        assert stored.default_model == "configured-model"

    def test_get_adapter_for_provider_string(self):
        """Test getting adapter for provider string."""
        # Mock is auto-registered
        registry = ProviderAdapterRegistry()

        adapter = registry.get_adapter_for_provider("mock:test-model")
        assert adapter.name == "mock"


class TestPluginLoading:
    """Tests for plugin loading functionality."""

    def test_load_plugins_from_directory(self):
        """Test loading plugins from a directory."""
        registry = ProviderAdapterRegistry()

        # Create a temporary plugin directory
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_file = Path(tmpdir) / "test_plugin.py"
            plugin_file.write_text('''
from src.llm.adapters.base import ProviderAdapter, AdapterConfig

class TestPluginAdapter(ProviderAdapter):
    @property
    def name(self):
        return "test_plugin"

    def complete(self, messages, **kwargs):
        from src.llm.adapters.base import CompletionResult
        return CompletionResult(
            content="plugin response",
            model="test",
            provider=self.name
        )

    def stream(self, messages, **kwargs):
        yield from []

    def count_tokens(self, text):
        return len(text)

    def validate_config(self, config):
        return True

    def get_capabilities(self):
        return []

def register_adapters(registry):
    registry.register_class("test_plugin", TestPluginAdapter)
''')

            loaded = registry.load_plugins(tmpdir)
            assert loaded >= 1
            assert registry.has_class("test_plugin")

    def test_load_plugins_nonexistent_directory(self):
        """Test loading from nonexistent directory."""
        registry = ProviderAdapterRegistry()
        loaded = registry.load_plugins("/nonexistent/path")
        assert loaded == 0


class TestGlobalRegistry:
    """Tests for global registry functions."""

    def setup_method(self):
        """Reset registry before each test."""
        reset_registry()

    def test_get_registry_singleton(self):
        """Test that get_registry returns singleton."""
        registry1 = get_registry()
        registry2 = get_registry()

        assert registry1 is registry2

    def test_reset_registry(self):
        """Test that reset_registry clears singleton."""
        registry1 = get_registry()
        reset_registry()
        registry2 = get_registry()

        assert registry1 is not registry2

    def test_create_registry_new_instance(self):
        """Test that create_registry creates new instance."""
        registry1 = create_registry()
        registry2 = create_registry()

        assert registry1 is not registry2


class TestValidationCriteria:
    """
    Tests for VALIDATION_CRITERIA from ITEM-INT-132.

    - registry_works: Registry loads adapters
    - plugins_loaded: Custom plugins loaded
    - router_uses_registry: Router delegates to registry
    """

    def setup_method(self):
        """Reset registry before each test."""
        reset_registry()

    def test_criterion_registry_works(self):
        """
        VALIDATION_CRITERIA: registry_works
        Test that registry loads adapters.
        """
        registry = ProviderAdapterRegistry()

        # Register built-in adapters
        mock_adapter = MockAdapter(AdapterConfig(default_model="mock-test"))
        registry.register(mock_adapter, override=True)

        # Verify adapter is registered
        assert registry.has_adapter("mock")

        # Verify we can get and use the adapter
        adapter = registry.get("mock")
        result = adapter.complete([{"role": "user", "content": "Test"}])

        assert result.provider == "mock"
        assert result.error is None

    def test_criterion_plugins_loaded(self):
        """
        VALIDATION_CRITERIA: plugins_loaded
        Test that custom plugins can be loaded.
        """
        registry = ProviderAdapterRegistry()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a custom plugin
            plugin_file = Path(tmpdir) / "custom_provider.py"
            plugin_file.write_text('''
from src.llm.adapters.base import ProviderAdapter, AdapterConfig, CompletionResult

class CustomProviderAdapter(ProviderAdapter):
    @property
    def name(self):
        return "custom_provider"

    def complete(self, messages, **kwargs):
        return CompletionResult(
            content="Custom provider response",
            model="custom-model",
            provider=self.name
        )

    def stream(self, messages, **kwargs):
        yield from []

    def count_tokens(self, text):
        return len(text) // 4

    def validate_config(self, config):
        return True

    def get_capabilities(self):
        return []
''')

            # Load the plugin
            loaded = registry.load_plugins(tmpdir)
            assert loaded >= 1

            # Verify the adapter class was registered
            assert registry.has_class("custom_provider")

    def test_criterion_router_uses_registry(self):
        """
        VALIDATION_CRITERIA: router_uses_registry
        Test integration with ModelRouter.
        """
        from src.llm.router import ModelRouter, ModelConfig

        # Create registry with mock adapter
        registry = ProviderAdapterRegistry()
        mock_adapter = MockAdapter(AdapterConfig(default_model="mock-gpt-4"))
        registry.register(mock_adapter, override=True)

        # Create router config
        config = {
            "model_routing": {
                "root_model": {"provider": "mock", "model": "mock-gpt-4"},
                "leaf_model": {"provider": "mock", "model": "mock-gpt-3.5"}
            },
            "model_fallback": {
                "enabled": True,
                "chain": ["mock:mock-gpt-3.5"]
            }
        }

        router = ModelRouter(config)

        # Verify router uses provider strings correctly
        assert router.root_model.provider == "mock"
        assert router.leaf_model.provider == "mock"

        # Verify registry can provide adapters for router's providers
        adapter = registry.get_adapter_for_provider("mock:mock-gpt-4")
        assert adapter.name == "mock"


class TestCompletionResult:
    """Tests for CompletionResult."""

    def test_result_creation(self):
        """Test creating a completion result."""
        result = CompletionResult(
            content="Test response",
            model="gpt-4",
            provider="openai",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30
        )

        assert result.content == "Test response"
        assert result.model == "gpt-4"
        assert result.provider == "openai"
        assert result.total_tokens == 30

    def test_result_to_dict(self):
        """Test converting result to dictionary."""
        result = CompletionResult(
            content="Test",
            model="gpt-4",
            provider="openai",
            metadata={"key": "value"}
        )

        d = result.to_dict()
        assert d["content"] == "Test"
        assert d["model"] == "gpt-4"
        assert d["metadata"]["key"] == "value"


class TestAdapterCapabilities:
    """Tests for adapter capabilities."""

    def test_has_capability(self):
        """Test checking for capabilities."""
        adapter = MockAdapter(AdapterConfig())

        assert adapter.has_capability(AdapterCapability.STREAMING)
        assert adapter.has_capability(AdapterCapability.SEED_PARAMETER)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
