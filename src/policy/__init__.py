"""
TITAN FUSE Protocol - Policy Module

Policy Engine & Autonomous Recovery Loops (TASK-003)

This module provides:
- Policy Engine: Configurable behavior rules
- Recovery Manager: Autonomous recovery loops
- Retry Logic: Configurable retry strategies
- Policy Manifest: Declarative policy configuration
"""

from .policy_engine import (
    PolicyEngine,
    Policy,
    PolicyAction,
    PolicyCondition,
    PolicyResult,
    load_policies,
    evaluate_policy
)

from .recovery_manager import (
    RecoveryManager,
    RecoveryAction,
    RecoveryContext,
    RecoveryResult,
    RecoveryState,
    start_recovery,
    execute_recovery
)

from .retry_logic import (
    RetryStrategy,
    RetryPolicy,
    RetryResult,
    RetryState,
    should_retry,
    get_retry_delay
)

__all__ = [
    # Policy Engine
    "PolicyEngine",
    "Policy",
    "PolicyAction",
    "PolicyCondition",
    "PolicyResult",
    "load_policies",
    "evaluate_policy",
    # Recovery Manager
    "RecoveryManager",
    "RecoveryAction",
    "RecoveryContext",
    "RecoveryResult",
    "RecoveryState",
    "start_recovery",
    "execute_recovery",
    # Retry Logic
    "RetryStrategy",
    "RetryPolicy",
    "RetryResult",
    "RetryState",
    "should_retry",
    "get_retry_delay"
]

__version__ = "1.0.0"
