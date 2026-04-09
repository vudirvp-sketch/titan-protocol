"""
TITAN FUSE Protocol - Resilience Module

Provides resilience patterns for TITAN Protocol v1.2.0:
- RetryExecutorFacade: Unified retry and circuit breaker operations

Author: TITAN FUSE Team
Version: 1.2.0
"""

from .retry_executor_facade import (
    # Main class
    RetryExecutorFacade,
    # Data classes
    CircuitState,
    CircuitData,
    RetryFacadeConfig,
    FacadeResult,
    # Factory functions
    create_retry_facade,
    get_retry_facade,
    reset_retry_facade,
)

__all__ = [
    "RetryExecutorFacade",
    "CircuitState",
    "CircuitData",
    "RetryFacadeConfig",
    "FacadeResult",
    "create_retry_facade",
    "get_retry_facade",
    "reset_retry_facade",
]
