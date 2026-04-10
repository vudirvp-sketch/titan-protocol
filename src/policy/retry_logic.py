"""
TITAN FUSE Protocol - Retry Logic

Configurable retry strategies for transient failures.
Implements exponential backoff, jitter, and circuit breaker patterns.

TASK-003: Policy Engine & Autonomous Recovery Loops
FIX 09: Chain control integration for retry policies
"""

import random
import time
from datetime import datetime
from typing import Dict, Any, Optional, Callable, TypeVar, Union
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps

# FIX 09: Import chain control from policy_engine
from .policy_engine import PolicyResult, chain_next, chain_break_on


class RetryStrategy(Enum):
    """Retry strategies."""
    NONE = "none"
    FIXED = "fixed"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    EXPONENTIAL_JITTER = "exponential_jitter"


class RetryState(Enum):
    """State of retry process."""
    READY = "ready"
    RETRYING = "retrying"
    EXHAUSTED = "exhausted"
    SUCCESS = "success"
    CIRCUIT_OPEN = "circuit_open"


@dataclass
class RetryPolicy:
    """
    Retry policy configuration.

    Attributes:
        strategy: Retry strategy
        max_retries: Maximum number of retries
        base_delay_ms: Base delay in milliseconds
        max_delay_ms: Maximum delay in milliseconds
        multiplier: Multiplier for exponential backoff
        jitter: Jitter factor (0-1)
        retryable_errors: Error types that are retryable
        circuit_breaker_threshold: Failures before circuit opens
        circuit_breaker_reset_ms: Time before circuit resets
    """
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_JITTER
    max_retries: int = 3
    base_delay_ms: int = 100
    max_delay_ms: int = 30000
    multiplier: float = 2.0
    jitter: float = 0.1
    retryable_errors: list = field(default_factory=list)
    circuit_breaker_threshold: int = 5
    circuit_breaker_reset_ms: int = 60000

    def get_delay(self, attempt: int) -> int:
        """
        Calculate delay for a given attempt.

        Args:
            attempt: Attempt number (0-indexed)

        Returns:
            Delay in milliseconds
        """
        if self.strategy == RetryStrategy.NONE:
            return 0

        if self.strategy == RetryStrategy.FIXED:
            delay = self.base_delay_ms

        elif self.strategy == RetryStrategy.LINEAR:
            delay = self.base_delay_ms * (attempt + 1)

        elif self.strategy == RetryStrategy.EXPONENTIAL:
            delay = self.base_delay_ms * (self.multiplier ** attempt)

        elif self.strategy == RetryStrategy.EXPONENTIAL_JITTER:
            delay = self.base_delay_ms * (self.multiplier ** attempt)
            # Add jitter
            jitter_range = delay * self.jitter
            delay += random.uniform(-jitter_range, jitter_range)

        else:
            delay = self.base_delay_ms

        # Cap at max delay
        return min(int(delay), self.max_delay_ms)

    def is_retryable(self, error: Exception) -> bool:
        """Check if an error is retryable."""
        if not self.retryable_errors:
            return True  # Default: all errors are retryable

        error_type = type(error).__name__
        return error_type in self.retryable_errors

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "strategy": self.strategy.value,
            "max_retries": self.max_retries,
            "base_delay_ms": self.base_delay_ms,
            "max_delay_ms": self.max_delay_ms,
            "multiplier": self.multiplier,
            "jitter": self.jitter,
            "retryable_errors": self.retryable_errors,
            "circuit_breaker_threshold": self.circuit_breaker_threshold,
            "circuit_breaker_reset_ms": self.circuit_breaker_reset_ms
        }


@dataclass
class RetryResult:
    """
    Result of retry operation.

    Attributes:
        success: Whether operation succeeded
        attempts: Number of attempts made
        total_delay_ms: Total delay in milliseconds
        last_error: Last error encountered
        result: Result of successful operation
        state: Final retry state
    """
    success: bool = False
    attempts: int = 0
    total_delay_ms: int = 0
    last_error: Optional[str] = None
    result: Any = None
    state: RetryState = RetryState.READY
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "attempts": self.attempts,
            "total_delay_ms": self.total_delay_ms,
            "last_error": self.last_error,
            "state": self.state.value,
            "timestamp": self.timestamp
        }


class RetryExecutor:
    """
    Executor for retry operations with circuit breaker.

    Usage:
        executor = RetryExecutor(RetryPolicy(
            strategy=RetryStrategy.EXPONENTIAL_JITTER,
            max_retries=3
        ))

        result = executor.execute(
            lambda: risky_operation(),
            on_retry=lambda attempt, error: print(f"Retry {attempt}: {error}")
        )
    """

    def __init__(self, policy: Optional[RetryPolicy] = None):
        self.policy = policy or RetryPolicy()
        self._consecutive_failures = 0
        self._circuit_open_until: Optional[float] = None

    @property
    def circuit_open(self) -> bool:
        """Check if circuit breaker is open."""
        if self._circuit_open_until is None:
            return False

        if time.time() >= self._circuit_open_until:
            self._circuit_open_until = None
            self._consecutive_failures = 0
            return False

        return True

    # FIX 09: Chain control decorators for retry execution
    @chain_next(on_success="log_success", on_failure="handle_failure")
    @chain_break_on(lambda result: result.state == RetryState.CIRCUIT_OPEN)
    def execute(self,
                operation: Callable[[], Any],
                on_retry: Optional[Callable[[int, Exception], None]] = None) -> RetryResult:
        """
        Execute an operation with retry logic.

        Args:
            operation: Operation to execute
            on_retry: Callback for retry events

        Returns:
            Retry result
        """
        result = RetryResult(state=RetryState.READY)

        # Check circuit breaker
        if self.circuit_open:
            result.state = RetryState.CIRCUIT_OPEN
            result.last_error = "Circuit breaker is open"
            return result

        for attempt in range(self.policy.max_retries + 1):
            result.attempts = attempt + 1

            try:
                operation_result = operation()
                result.success = True
                result.result = operation_result
                result.state = RetryState.SUCCESS

                # Reset on success
                self._consecutive_failures = 0

                return result

            except Exception as e:
                result.last_error = str(e)

                # Check if error is retryable
                if not self.policy.is_retryable(e):
                    result.state = RetryState.EXHAUSTED
                    return result

                # Check if we have more retries
                if attempt >= self.policy.max_retries:
                    result.state = RetryState.EXHAUSTED
                    self._handle_failure()
                    return result

                # Calculate and apply delay
                delay_ms = self.policy.get_delay(attempt)
                result.total_delay_ms += delay_ms

                # Notify retry callback
                if on_retry:
                    try:
                        on_retry(attempt + 1, e)
                    except Exception:
                        pass

                # Apply delay
                result.state = RetryState.RETRYING
                time.sleep(delay_ms / 1000)

        result.state = RetryState.EXHAUSTED
        return result

    def _handle_failure(self) -> None:
        """Handle consecutive failure."""
        self._consecutive_failures += 1

        if self._consecutive_failures >= self.policy.circuit_breaker_threshold:
            self._circuit_open_until = (
                time.time() + self.policy.circuit_breaker_reset_ms / 1000
            )

    async def execute_async(self,
                            operation: Callable[[], Any],
                            on_retry: Optional[Callable[[int, Exception], None]] = None) -> RetryResult:
        """
        Execute an async operation with retry logic.

        Args:
            operation: Async operation to execute
            on_retry: Callback for retry events

        Returns:
            Retry result
        """
        import asyncio

        result = RetryResult(state=RetryState.READY)

        if self.circuit_open:
            result.state = RetryState.CIRCUIT_OPEN
            result.last_error = "Circuit breaker is open"
            return result

        for attempt in range(self.policy.max_retries + 1):
            result.attempts = attempt + 1

            try:
                if asyncio.iscoroutinefunction(operation):
                    operation_result = await operation()
                else:
                    operation_result = operation()

                result.success = True
                result.result = operation_result
                result.state = RetryState.SUCCESS
                self._consecutive_failures = 0
                return result

            except Exception as e:
                result.last_error = str(e)

                if not self.policy.is_retryable(e):
                    result.state = RetryState.EXHAUSTED
                    return result

                if attempt >= self.policy.max_retries:
                    result.state = RetryState.EXHAUSTED
                    self._handle_failure()
                    return result

                delay_ms = self.policy.get_delay(attempt)
                result.total_delay_ms += delay_ms

                if on_retry:
                    try:
                        on_retry(attempt + 1, e)
                    except Exception:
                        pass

                result.state = RetryState.RETRYING
                await asyncio.sleep(delay_ms / 1000)

        result.state = RetryState.EXHAUSTED
        return result


# Default retry policies
DEFAULT_POLICY = RetryPolicy()

AGGRESSIVE_POLICY = RetryPolicy(
    strategy=RetryStrategy.EXPONENTIAL_JITTER,
    max_retries=5,
    base_delay_ms=50,
    max_delay_ms=10000,
    multiplier=1.5,
    jitter=0.2
)

CONSERVATIVE_POLICY = RetryPolicy(
    strategy=RetryStrategy.EXPONENTIAL,
    max_retries=2,
    base_delay_ms=1000,
    max_delay_ms=30000,
    multiplier=3.0
)


# Convenience functions
_global_executor: Optional[RetryExecutor] = None


def get_executor(policy: Optional[RetryPolicy] = None) -> RetryExecutor:
    """Get a retry executor."""
    global _global_executor
    if _global_executor is None or policy:
        _global_executor = RetryExecutor(policy or DEFAULT_POLICY)
    return _global_executor


def should_retry(error: Exception, policy: Optional[RetryPolicy] = None) -> bool:
    """Check if an error should be retried."""
    p = policy or DEFAULT_POLICY
    return p.is_retryable(error)


def get_retry_delay(attempt: int, policy: Optional[RetryPolicy] = None) -> int:
    """Get retry delay for an attempt."""
    p = policy or DEFAULT_POLICY
    return p.get_delay(attempt)


def with_retry(policy: Optional[RetryPolicy] = None,
               on_retry: Optional[Callable[[int, Exception], None]] = None):
    """
    Decorator to add retry logic to a function.

    Usage:
        @with_retry(RetryPolicy(max_retries=3))
        def risky_operation():
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            executor = RetryExecutor(policy or DEFAULT_POLICY)
            result = executor.execute(
                lambda: func(*args, **kwargs),
                on_retry=on_retry
            )
            if result.success:
                return result.result
            raise Exception(result.last_error)
        return wrapper
    return decorator
