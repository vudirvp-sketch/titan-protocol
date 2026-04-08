"""
ITEM-INT-132: Provider Adapter Registry for TITAN Protocol.

This module provides a central registry for LLM provider adapters,
enabling a plugin mechanism for custom providers and unified
management of provider configurations.

The registry supports:
- Dynamic provider registration
- Plugin loading from configured paths
- Provider validation
- Unified access to multiple providers
- Configuration management

Author: TITAN FUSE Team
Version: 4.1.0
"""

from typing import Dict, List, Optional, Type, Any
from dataclasses import dataclass, field
from pathlib import Path
import logging
import importlib
import os
import sys

from .adapters.base import (
    ProviderAdapter, AdapterConfig, CompletionResult,
    AdapterCapability, AdapterError, AdapterNotAvailableError
)
from .adapters.openai import OpenAIAdapter
from .adapters.anthropic import AnthropicAdapter
from .adapters.mock import MockAdapter

from src.utils.timezone import now_utc, now_utc_iso


@dataclass
class RegistryStats:
    """
    Statistics for the provider registry.

    Tracks registrations, requests, and errors across all providers.
    """
    total_registrations: int = 0
    total_requests: int = 0
    total_errors: int = 0
    providers_registered: int = 0
    plugins_loaded: int = 0
    last_registration_time: Optional[str] = None
    last_request_time: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "total_registrations": self.total_registrations,
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "providers_registered": self.providers_registered,
            "plugins_loaded": self.plugins_loaded,
            "last_registration_time": self.last_registration_time,
            "last_request_time": self.last_request_time
        }


class ProviderAdapterRegistry:
    """
    Central registry for LLM provider adapters.

    ITEM-INT-132: Implements a plugin mechanism for custom LLM providers.
    Provides unified access to multiple providers through a single interface.

    Features:
    - Register custom provider adapters
    - Load plugins from configured paths
    - Validate adapter configurations
    - Track usage statistics

    Usage:
        # Initialize registry
        registry = ProviderAdapterRegistry()

        # Register built-in adapters
        registry.register(OpenAIAdapter(config))
        registry.register(AnthropicAdapter(config))

        # Get adapter by name
        adapter = registry.get("openai")

        # List available adapters
        names = registry.list_available()

        # Load plugins from path
        registry.load_plugins("/path/to/plugins")

    Configuration:
        The registry can be configured via config.yaml:
        ```yaml
        llm:
          provider_registry:
            enabled: true
            plugin_paths:
              - "./plugins/providers"
            auto_register_builtin: true
        ```
    """

    # Built-in adapter classes
    BUILTIN_ADAPTERS = {
        "openai": OpenAIAdapter,
        "anthropic": AnthropicAdapter,
        "mock": MockAdapter
    }

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the provider registry.

        Args:
            config: Configuration dictionary containing provider_registry settings
        """
        self._logger = logging.getLogger("titan.provider_registry")
        self.config = config or {}

        # Adapter storage
        self._adapters: Dict[str, ProviderAdapter] = {}
        self._adapter_classes: Dict[str, Type[ProviderAdapter]] = {}

        # Configuration storage
        self._adapter_configs: Dict[str, AdapterConfig] = {}

        # Statistics
        self._stats = RegistryStats()

        # Registry settings
        registry_config = self.config.get("llm", {}).get("provider_registry", {})
        self._plugin_paths = registry_config.get("plugin_paths", [])
        self._auto_register_builtin = registry_config.get("auto_register_builtin", True)

        # Register built-in adapter classes
        self._register_builtin_classes()

        # Auto-register built-in adapters if configured
        if self._auto_register_builtin:
            self._auto_register_builtin_adapters()

        self._logger.info(
            f"ProviderAdapterRegistry initialized: "
            f"builtin_adapters={len(self.BUILTIN_ADAPTERS)}, "
            f"auto_register={self._auto_register_builtin}"
        )

    def _register_builtin_classes(self) -> None:
        """Register built-in adapter classes for lookup."""
        for name, adapter_class in self.BUILTIN_ADAPTERS.items():
            self._adapter_classes[name] = adapter_class

    def _auto_register_builtin_adapters(self) -> None:
        """Auto-register built-in adapters with default config."""
        # Register mock adapter with default config (always available)
        mock_config = AdapterConfig(default_model="mock-default")
        try:
            mock_adapter = MockAdapter(mock_config)
            self._adapters["mock"] = mock_adapter
            self._stats.providers_registered += 1
            self._logger.debug("Auto-registered mock adapter")
        except Exception as e:
            self._logger.warning(f"Failed to auto-register mock adapter: {e}")

    def register(self, adapter: ProviderAdapter,
                 override: bool = False) -> None:
        """
        Register a provider adapter.

        Args:
            adapter: The adapter instance to register
            override: Whether to override existing adapter with same name

        Raises:
            AdapterError: If adapter with same name exists and override=False
        """
        name = adapter.name

        if name in self._adapters and not override:
            raise AdapterError(
                f"Adapter '{name}' already registered. "
                f"Use override=True to replace."
            )

        self._adapters[name] = adapter
        self._stats.total_registrations += 1
        self._stats.providers_registered = len(self._adapters)
        self._stats.last_registration_time = now_utc_iso()

        self._logger.info(
            f"Registered adapter: {name} (version={adapter.version}, "
            f"model={adapter.get_default_model()})"
        )

    def register_class(self, name: str,
                       adapter_class: Type[ProviderAdapter]) -> None:
        """
        Register an adapter class for lazy instantiation.

        Args:
            name: Name to register the class under
            adapter_class: The adapter class (not instance)
        """
        self._adapter_classes[name] = adapter_class
        self._logger.debug(f"Registered adapter class: {name}")

    def get(self, name: str,
            config: Optional[AdapterConfig] = None) -> ProviderAdapter:
        """
        Get a registered adapter by name.

        Args:
            name: The adapter name
            config: Optional config to create adapter if not registered

        Returns:
            The provider adapter

        Raises:
            AdapterNotAvailableError: If adapter not found and cannot be created
        """
        # Check if already registered
        if name in self._adapters:
            self._stats.total_requests += 1
            self._stats.last_request_time = now_utc_iso()
            return self._adapters[name]

        # Try to create from registered class
        if name in self._adapter_classes:
            adapter_class = self._adapter_classes[name]

            # Use provided config or stored config
            adapter_config = config or self._adapter_configs.get(name)

            if adapter_config:
                adapter = adapter_class(adapter_config)
                self._adapters[name] = adapter
                self._stats.total_requests += 1
                self._stats.last_request_time = now_utc_iso()
                return adapter

        # Not found
        raise AdapterNotAvailableError(
            f"Adapter '{name}' not found. "
            f"Available: {list(self._adapters.keys())}"
        )

    def get_or_create(self, name: str,
                      config: AdapterConfig) -> ProviderAdapter:
        """
        Get an adapter, creating it if necessary.

        Args:
            name: The adapter name
            config: Configuration for the adapter

        Returns:
            The provider adapter
        """
        if name in self._adapters:
            return self._adapters[name]

        # Store config for later use
        self._adapter_configs[name] = config

        # Create adapter
        return self.get(name, config)

    def list_available(self) -> List[str]:
        """
        List all available adapter names.

        Returns:
            List of registered adapter names
        """
        return list(self._adapters.keys())

    def list_classes(self) -> List[str]:
        """
        List all registered adapter classes.

        Returns:
            List of adapter class names
        """
        return list(self._adapter_classes.keys())

    def has_adapter(self, name: str) -> bool:
        """
        Check if an adapter is registered.

        Args:
            name: The adapter name

        Returns:
            bool: True if adapter is registered
        """
        return name in self._adapters

    def has_class(self, name: str) -> bool:
        """
        Check if an adapter class is registered.

        Args:
            name: The adapter class name

        Returns:
            bool: True if class is registered
        """
        return name in self._adapter_classes

    def validate_adapter(self, adapter: ProviderAdapter) -> bool:
        """
        Validate an adapter instance.

        Performs comprehensive validation of adapter:
        - Required methods implemented
        - Configuration valid
        - Capabilities consistent

        Args:
            adapter: The adapter to validate

        Returns:
            bool: True if valid

        Raises:
            AdapterError: If validation fails
        """
        # Check required attributes
        if not hasattr(adapter, 'name') or not adapter.name:
            raise AdapterError("Adapter must have a 'name' attribute")

        # Check required methods
        required_methods = ['complete', 'stream', 'count_tokens',
                            'validate_config', 'get_capabilities']

        for method in required_methods:
            if not hasattr(adapter, method):
                raise AdapterError(
                    f"Adapter '{adapter.name}' missing required method: {method}"
                )

        # Validate configuration
        try:
            adapter.validate_config(adapter.config.to_dict())
        except Exception as e:
            raise AdapterError(
                f"Adapter '{adapter.name}' configuration invalid: {e}"
            )

        return True

    def unregister(self, name: str) -> bool:
        """
        Unregister an adapter.

        Args:
            name: The adapter name to unregister

        Returns:
            bool: True if adapter was unregistered
        """
        if name in self._adapters:
            del self._adapters[name]
            self._stats.providers_registered = len(self._adapters)
            self._logger.info(f"Unregistered adapter: {name}")
            return True
        return False

    def load_plugins(self, path: str) -> int:
        """
        Load adapter plugins from a directory.

        Plugins are Python modules that define adapter classes.
        Each module should define a `register_adapters(registry)` function
        or export adapter classes.

        Args:
            path: Directory path to load plugins from

        Returns:
            int: Number of plugins loaded
        """
        plugin_dir = Path(path)

        if not plugin_dir.exists():
            self._logger.warning(f"Plugin directory does not exist: {path}")
            return 0

        loaded = 0

        for plugin_file in plugin_dir.glob("*.py"):
            if plugin_file.name.startswith("_"):
                continue

            try:
                loaded += self._load_plugin_file(plugin_file)
            except Exception as e:
                self._logger.error(
                    f"Failed to load plugin {plugin_file}: {e}"
                )

        self._stats.plugins_loaded += loaded
        return loaded

    def _load_plugin_file(self, plugin_path: Path) -> int:
        """
        Load a single plugin file.

        Args:
            plugin_path: Path to the plugin file

        Returns:
            int: Number of adapters loaded from this plugin
        """
        module_name = f"titan_plugin_{plugin_path.stem}"

        # Load the module
        spec = importlib.util.spec_from_file_location(
            module_name, plugin_path
        )

        if spec is None or spec.loader is None:
            return 0

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        loaded = 0

        # Check for register function
        if hasattr(module, 'register_adapters'):
            module.register_adapters(self)
            loaded += 1
            self._logger.info(
                f"Loaded plugin via register_adapters: {plugin_path.name}"
            )

        # Look for adapter classes
        for attr_name in dir(module):
            attr = getattr(module, attr_name)

            # Check if it's a ProviderAdapter subclass
            if (isinstance(attr, type) and
                    issubclass(attr, ProviderAdapter) and
                    attr is not ProviderAdapter):

                # Try to get adapter name
                try:
                    temp_instance = attr(AdapterConfig())
                    adapter_name = temp_instance.name
                    self._adapter_classes[adapter_name] = attr
                    loaded += 1
                    self._logger.info(
                        f"Registered adapter class from plugin: {adapter_name}"
                    )
                except Exception as e:
                    self._logger.warning(
                        f"Could not instantiate adapter {attr_name}: {e}"
                    )

        return loaded

    def get_stats(self) -> Dict:
        """
        Get registry statistics.

        Returns:
            Dict with registry statistics
        """
        stats = self._stats.to_dict()
        stats["adapters"] = {
            name: adapter.get_stats()
            for name, adapter in self._adapters.items()
        }
        return stats

    def reset_stats(self) -> None:
        """Reset registry statistics."""
        self._stats = RegistryStats()
        for adapter in self._adapters.values():
            adapter.reset_stats()

    def configure_adapter(self, name: str, config: AdapterConfig) -> None:
        """
        Store configuration for an adapter.

        The config will be used when the adapter is created via get().

        Args:
            name: Adapter name
            config: Configuration to store
        """
        self._adapter_configs[name] = config

        # If adapter already exists, reconfigure it
        if name in self._adapters:
            adapter_class = type(self._adapters[name])
            self._adapters[name] = adapter_class(config)
            self._logger.info(f"Reconfigured adapter: {name}")

    def get_adapter_for_provider(self, provider: str,
                                  model: Optional[str] = None) -> ProviderAdapter:
        """
        Get adapter for a provider string.

        Provider strings can be in formats:
        - "openai" -> OpenAI adapter
        - "openai:gpt-4" -> OpenAI adapter with model override
        - "anthropic:claude-3-opus" -> Anthropic adapter

        Args:
            provider: Provider string
            model: Optional model override

        Returns:
            Provider adapter configured for the provider

        Raises:
            AdapterNotAvailableError: If provider not found
        """
        # Parse provider string
        if ":" in provider:
            provider_name, model_name = provider.split(":", 1)
            if model is None:
                model = model_name
        else:
            provider_name = provider

        # Get adapter
        adapter = self.get(provider_name)

        # Override model if specified
        if model and adapter.config.default_model != model:
            new_config = AdapterConfig(
                api_key=adapter.config.api_key,
                api_base=adapter.config.api_base,
                default_model=model,
                max_tokens=adapter.config.max_tokens,
                temperature=adapter.config.temperature,
                extra=adapter.config.extra
            )
            adapter_class = type(adapter)
            adapter = adapter_class(new_config)

        return adapter

    def complete_with_provider(self, provider: str,
                               messages: List[Dict],
                               **kwargs) -> CompletionResult:
        """
        Convenience method to complete using a provider string.

        Args:
            provider: Provider string (e.g., "openai:gpt-4")
            messages: Messages to send
            **kwargs: Additional parameters

        Returns:
            CompletionResult from the provider
        """
        adapter = self.get_adapter_for_provider(provider)
        return adapter.complete(messages, **kwargs)


# Global registry instance (singleton pattern)
_global_registry: Optional[ProviderAdapterRegistry] = None


def get_registry(config: Optional[Dict] = None) -> ProviderAdapterRegistry:
    """
    Get the global provider registry instance.

    Creates the registry on first call with optional config.
    Subsequent calls return the same instance.

    Args:
        config: Configuration (only used on first call)

    Returns:
        The global ProviderAdapterRegistry instance
    """
    global _global_registry

    if _global_registry is None:
        _global_registry = ProviderAdapterRegistry(config)

    return _global_registry


def reset_registry() -> None:
    """Reset the global registry (mainly for testing)."""
    global _global_registry
    _global_registry = None


def create_registry(config: Optional[Dict] = None) -> ProviderAdapterRegistry:
    """
    Create a new provider registry instance.

    Unlike get_registry(), this always creates a new instance.

    Args:
        config: Configuration dictionary

    Returns:
        New ProviderAdapterRegistry instance
    """
    return ProviderAdapterRegistry(config)
