# TITAN FUSE Protocol - LLM Module
"""
LLM routing and model management.

ITEM-GATE-05: Model Downgrade Determinism
ITEM-PERF-01: Streaming Response Support
ITEM-INT-132: Provider Adapter Registry
"""

from .router import (
    ModelRouter, ModelConfig, FallbackState, BudgetStatus,
    ExecutionStrictness, BudgetExhaustedError, DowngradeViolationError,
    create_model_router, get_model_for_operation
)

from .streaming import (
    StreamingHandler, StreamConfig, StreamState,
    StreamMetrics, StreamChunk,
    create_streaming_handler
)

# ITEM-INT-132: Provider Adapter Registry
from .provider_registry import (
    ProviderAdapterRegistry,
    get_registry, reset_registry, create_registry
)

from .adapters import (
    ProviderAdapter,
    CompletionResult,
    AdapterConfig,
    AdapterCapability,
    OpenAIAdapter,
    AnthropicAdapter,
    MockAdapter
)

__all__ = [
    # Router exports
    'ModelRouter',
    'ModelConfig',
    'FallbackState',
    'BudgetStatus',
    'ExecutionStrictness',
    'BudgetExhaustedError',
    'DowngradeViolationError',
    'create_model_router',
    'get_model_for_operation',
    # Streaming exports (ITEM-PERF-01)
    'StreamingHandler',
    'StreamConfig',
    'StreamState',
    'StreamMetrics',
    'StreamChunk',
    'create_streaming_handler',
    # Provider Registry exports (ITEM-INT-132)
    'ProviderAdapterRegistry',
    'get_registry',
    'reset_registry',
    'create_registry',
    # Adapter exports (ITEM-INT-132)
    'ProviderAdapter',
    'CompletionResult',
    'AdapterConfig',
    'AdapterCapability',
    'OpenAIAdapter',
    'AnthropicAdapter',
    'MockAdapter',
]
