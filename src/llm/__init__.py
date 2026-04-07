# TITAN FUSE Protocol - LLM Module
"""
LLM routing and model management.

ITEM-GATE-05: Model Downgrade Determinism
"""

from .router import (
    ModelRouter, ModelConfig, FallbackState, BudgetStatus,
    ExecutionStrictness, BudgetExhaustedError, DowngradeViolationError,
    create_model_router, get_model_for_operation
)

__all__ = [
    'ModelRouter', 
    'ModelConfig', 
    'FallbackState',
    'BudgetStatus',
    'ExecutionStrictness',
    'BudgetExhaustedError',
    'DowngradeViolationError',
    'create_model_router',
    'get_model_for_operation'
]
