"""
TITAN FUSE Protocol - Resilience Module

Provides resilience patterns for TITAN Protocol v1.2.0:
- RetryExecutorFacade: Unified retry and circuit breaker operations
- CircuitBreaker: Standalone circuit breaker implementation
- DegradationManager: Graceful degradation with recovery detection

PHASE_3 Components (ITEM_013, ITEM_014):
- CircuitBreaker: Prevents cascade failures with circuit breaker pattern
- CircuitBreakerRegistry: Manages multiple circuit breakers
- DegradationManager: Handles graceful degradation with automatic recovery

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

from .circuit_breaker import (
    # Main class
    CircuitBreaker,
    # Data classes
    CircuitBreakerConfig,
    CircuitBreakerStats,
    CircuitBreakerError,
    # Registry
    CircuitBreakerRegistry,
    get_circuit_breaker_registry,
)

from .degradation import (
    # Main class
    DegradationManager,
    # Enums
    DegradationLevel,
    # Data classes
    DegradationConfig,
    DegradationStats,
    FeatureState,
    # Factory functions
    get_degradation_manager,
    reset_degradation_manager,
    # Constants
    DEFAULT_FEATURE_SETS,
    PROFILE_DETECTION_WEIGHTS,
)

__all__ = [
    # RetryExecutorFacade
    "RetryExecutorFacade",
    "CircuitState",
    "CircuitData",
    "RetryFacadeConfig",
    "FacadeResult",
    "create_retry_facade",
    "get_retry_facade",
    "reset_retry_facade",
    
    # CircuitBreaker
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerStats",
    "CircuitBreakerError",
    "CircuitBreakerRegistry",
    "get_circuit_breaker_registry",
    
    # DegradationManager
    "DegradationManager",
    "DegradationLevel",
    "DegradationConfig",
    "DegradationStats",
    "FeatureState",
    "get_degradation_manager",
    "reset_degradation_manager",
    "DEFAULT_FEATURE_SETS",
    "PROFILE_DETECTION_WEIGHTS",
]
