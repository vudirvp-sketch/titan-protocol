# TITAN FUSE Protocol - LLM Provider Adapters
"""
ITEM-INT-132: Provider Adapter Registry

This module provides a plugin mechanism for custom LLM providers.
Each adapter implements a common interface for consistent behavior
across different LLM backends.

Available Adapters:
- OpenAIAdapter: OpenAI GPT models
- AnthropicAdapter: Anthropic Claude models
- MockAdapter: Testing mock adapter
"""

from .base import (
    ProviderAdapter,
    CompletionResult,
    StreamChunk,
    AdapterConfig,
    AdapterCapability
)

from .openai import OpenAIAdapter
from .anthropic import AnthropicAdapter
from .mock import MockAdapter

__all__ = [
    # Base classes
    'ProviderAdapter',
    'CompletionResult',
    'StreamChunk',
    'AdapterConfig',
    'AdapterCapability',
    # Built-in adapters
    'OpenAIAdapter',
    'AnthropicAdapter',
    'MockAdapter',
]
