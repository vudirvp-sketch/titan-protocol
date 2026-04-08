# TITAN FUSE Protocol - LLM Module
"""
LLM routing and model management.

ITEM-GATE-05: Model Downgrade Determinism
ITEM-PERF-01: Streaming Response Support
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
]
