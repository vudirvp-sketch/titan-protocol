"""
TITAN FUSE Protocol - Circuit Breaker

ITEM_013: CircuitBreaker for TITAN Protocol v1.2.0

Prevents cascade failures with circuit breaker pattern.
This module provides a standalone CircuitBreaker class that can be used
independently or integrated with the RetryExecutorFacade.

Key Features:
- Three states: CLOSED, OPEN, HALF_OPEN
- Configurable failure threshold and reset timeout
- Event emission on state transitions
- Thread-safe state management
- Metrics collection

Integration Points:
- RetryExecutorFacade: Uses CircuitBreaker internally
- EventBus: Emits CIRCUIT_OPENED, CIRCUIT_CLOSED, CIRCUIT_HALF_OPEN events
- UniversalRouter: Uses circuit breaker for external service calls

Author: TITAN FUSE Team
Version: 1.2.0
"""

import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, Callable, List
import logging
import traceback

from src.events.event_bus import Event, EventSeverity, EventBus
from src.utils.timezone import now_utc_iso


class CircuitState(Enum):
    """
    Circuit breaker state enumeration.
    
    States:
    - CLOSED: Normal operation, requests flow through
    - OPEN: Circuit tripped, requests fail fast
    - HALF_OPEN: Testing if service recovered, limited requests allowed
    """
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """
    Configuration for CircuitBreaker.
    
    Attributes:
        failure_threshold: Number of consecutive failures before opening (default: 5)
        success_threshold: Successes needed in half-open to close (default: 2)
        timeout_ms: Time in ms before attempting half-open (default: 30000)
        half_open_max_calls: Max calls allowed in half-open state (default: 1)
        enable_metrics: Enable metrics collection (default: True)
        enable_events: Enable event emission (default: True)
    """
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout_ms: int = 30000
    half_open_max_calls: int = 1
    enable_metrics: bool = True
    enable_events: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "failure_threshold": self.failure_threshold,
            "success_threshold": self.success_threshold,
            "timeout_ms": self.timeout_ms,
            "half_open_max_calls": self.half_open_max_calls,
            "enable_metrics": self.enable_metrics,
            "enable_events": self.enable_events,
        }


@dataclass
class CircuitBreakerStats:
    """
    Statistics for circuit breaker operations.
    
    Attributes:
        total_calls: Total number of calls
        successful_calls: Number of successful calls
        failed_calls: Number of failed calls
        rejected_calls: Calls rejected while open
        state_transitions: Number of state transitions
        last_failure_time: Timestamp of last failure
        last_success_time: Timestamp of last success
        last_state_change: Timestamp of last state change
    """
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    state_transitions: int = 0
    last_failure_time: Optional[str] = None
    last_success_time: Optional[str] = None
    last_state_change: Optional[str] = None
    current_state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "rejected_calls": self.rejected_calls,
            "state_transitions": self.state_transitions,
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
            "last_state_change": self.last_state_change,
            "current_state": self.current_state.value,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
        }


class CircuitBreakerError(Exception):
    """Exception raised when circuit is open."""
    
    def __init__(self, circuit_id: str, state: CircuitState, message: str = ""):
        self.circuit_id = circuit_id
        self.state = state
        self.message = message or f"Circuit '{circuit_id}' is {state.value}"
        super().__init__(self.message)


class CircuitBreaker:
    """
    Circuit breaker for preventing cascade failures.
    
    Implements the circuit breaker pattern with three states:
    - CLOSED: Normal operation, all requests pass through
    - OPEN: Circuit tripped, requests fail fast without calling the service
    - HALF_OPEN: Testing state, limited requests allowed to check recovery
    
    Thread-safe implementation with event emission support.
    
    Usage:
        breaker = CircuitBreaker(
            circuit_id="my_service",
            config=CircuitBreakerConfig(failure_threshold=3),
            event_bus=event_bus
        )
        
        # Execute with circuit breaker protection
        try:
            result = breaker.execute(lambda: risky_operation())
        except CircuitBreakerError as e:
            print(f"Circuit is open: {e}")
        
        # Check state
        if breaker.is_closed():
            # Safe to proceed
            pass
        
        # Manual control
        breaker.reset()
        breaker.force_open()
    
    Attributes:
        circuit_id: Unique identifier for this circuit
        config: CircuitBreakerConfig instance
        event_bus: Optional EventBus for state change events
    """
    
    def __init__(
        self,
        circuit_id: str,
        config: Optional[CircuitBreakerConfig] = None,
        event_bus: Optional[EventBus] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize CircuitBreaker.
        
        Args:
            circuit_id: Unique identifier for this circuit
            config: Configuration options
            event_bus: EventBus for emitting state change events
            logger: Optional logger instance
        """
        self.circuit_id = circuit_id
        self._config = config or CircuitBreakerConfig()
        self._event_bus = event_bus
        self._logger = logger or logging.getLogger(__name__)
        
        # State management
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._opened_at: Optional[float] = None
        self._half_open_calls = 0
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Statistics
        self._stats = CircuitBreakerStats()
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state (with automatic half-open transition)."""
        with self._lock:
            if self._state == CircuitState.OPEN and self._opened_at is not None:
                elapsed_ms = (time.time() - self._opened_at) * 1000
                if elapsed_ms >= self._config.timeout_ms:
                    self._transition_to(CircuitState.HALF_OPEN)
            return self._state
    
    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self.state == CircuitState.CLOSED
    
    @property
    def is_open(self) -> bool:
        """Check if circuit is open (failing fast)."""
        return self.state == CircuitState.OPEN
    
    @property
    def is_half_open(self) -> bool:
        """Check if circuit is in half-open state (testing recovery)."""
        return self.state == CircuitState.HALF_OPEN
    
    def _transition_to(self, new_state: CircuitState) -> None:
        """
        Transition to a new state.
        
        Args:
            new_state: The new state to transition to
        """
        old_state = self._state
        
        if old_state == new_state:
            return
        
        self._state = new_state
        self._stats.state_transitions += 1
        self._stats.last_state_change = now_utc_iso()
        self._stats.current_state = new_state
        
        # State-specific initialization
        if new_state == CircuitState.OPEN:
            self._opened_at = time.time()
            self._half_open_calls = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._consecutive_successes = 0
        elif new_state == CircuitState.CLOSED:
            self._opened_at = None
            self._consecutive_failures = 0
            self._consecutive_successes = 0
            self._half_open_calls = 0
        
        # Emit event
        self._emit_state_change(old_state, new_state)
        
        self._logger.info(
            f"Circuit '{self.circuit_id}' transitioned: {old_state.value} -> {new_state.value}"
        )
    
    def _emit_state_change(
        self,
        old_state: CircuitState,
        new_state: CircuitState,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit circuit state change event."""
        if not self._config.enable_events or not self._event_bus:
            return
        
        event_type_map = {
            CircuitState.OPEN: "CIRCUIT_OPENED",
            CircuitState.CLOSED: "CIRCUIT_CLOSED",
            CircuitState.HALF_OPEN: "CIRCUIT_HALF_OPEN",
        }
        
        event = Event(
            event_type=event_type_map.get(new_state, "CIRCUIT_STATE_CHANGE"),
            data={
                "circuit_id": self.circuit_id,
                "old_state": old_state.value,
                "new_state": new_state.value,
                "timestamp": now_utc_iso(),
                "consecutive_failures": self._consecutive_failures,
                "consecutive_successes": self._consecutive_successes,
                **(extra_data or {}),
            },
            severity=EventSeverity.WARN if new_state == CircuitState.OPEN else EventSeverity.INFO,
            source="CircuitBreaker",
        )
        self._event_bus.emit(event)
    
    def _record_success(self) -> None:
        """Record a successful operation."""
        with self._lock:
            self._stats.total_calls += 1
            self._stats.successful_calls += 1
            self._stats.last_success_time = now_utc_iso()
            self._consecutive_failures = 0
            self._consecutive_successes += 1
            
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1
                
                # Check if we should close the circuit
                if self._consecutive_successes >= self._config.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
    
    def _record_failure(self, error: Optional[Exception] = None) -> None:
        """Record a failed operation."""
        with self._lock:
            self._stats.total_calls += 1
            self._stats.failed_calls += 1
            self._stats.last_failure_time = now_utc_iso()
            self._consecutive_failures += 1
            self._consecutive_successes = 0
            
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1
                # Failure in half-open immediately reopens
                self._transition_to(CircuitState.OPEN)
            elif self._consecutive_failures >= self._config.failure_threshold:
                self._transition_to(CircuitState.OPEN)
    
    def _can_execute(self) -> bool:
        """Check if execution is allowed."""
        state = self.state  # This triggers half-open transition if timeout elapsed
        
        if state == CircuitState.CLOSED:
            return True
        
        if state == CircuitState.OPEN:
            return False
        
        if state == CircuitState.HALF_OPEN:
            # Allow limited calls in half-open
            return self._half_open_calls < self._config.half_open_max_calls
        
        return False
    
    def execute(
        self,
        operation: Callable[[], Any],
        on_failure: Optional[Callable[[Exception], None]] = None,
    ) -> Any:
        """
        Execute an operation with circuit breaker protection.
        
        Args:
            operation: The operation to execute
            on_failure: Optional callback when operation fails
            
        Returns:
            Result of the operation
            
        Raises:
            CircuitBreakerError: If circuit is open
            Exception: Re-raises the operation's exception after recording failure
        """
        with self._lock:
            if not self._can_execute():
                self._stats.rejected_calls += 1
                raise CircuitBreakerError(
                    self.circuit_id,
                    self._state,
                    f"Circuit '{self.circuit_id}' is {self._state.value}"
                )
        
        try:
            result = operation()
            self._record_success()
            return result
        except Exception as e:
            self._record_failure(e)
            
            if on_failure:
                try:
                    on_failure(e)
                except Exception:
                    pass
            
            raise
    
    def call(
        self,
        func: Callable[..., Any],
        *args,
        **kwargs,
    ) -> Any:
        """
        Call a function with circuit breaker protection.
        
        Convenience method that wraps execute() for function calls.
        
        Args:
            func: Function to call
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Result of the function call
        """
        return self.execute(lambda: func(*args, **kwargs))
    
    def reset(self) -> None:
        """
        Reset the circuit breaker to CLOSED state.
        
        Forces the circuit to closed state regardless of current state.
        """
        with self._lock:
            self._transition_to(CircuitState.CLOSED)
            self._logger.info(f"Circuit '{self.circuit_id}' manually reset to CLOSED")
    
    def force_open(self) -> None:
        """
        Force the circuit breaker to OPEN state.
        
        Forces the circuit to open state, useful for maintenance or
        when issues are detected externally.
        """
        with self._lock:
            self._transition_to(CircuitState.OPEN)
            self._logger.warning(f"Circuit '{self.circuit_id}' manually forced OPEN")
    
    def get_state(self) -> CircuitState:
        """Get current circuit state."""
        return self.state
    
    def get_stats(self) -> CircuitBreakerStats:
        """Get circuit breaker statistics."""
        with self._lock:
            # Update stats with current values
            self._stats.consecutive_failures = self._consecutive_failures
            self._stats.consecutive_successes = self._consecutive_successes
            self._stats.current_state = self._state
            return self._stats
    
    def reset_stats(self) -> None:
        """Reset statistics."""
        with self._lock:
            self._stats = CircuitBreakerStats(current_state=self._state)
    
    def set_event_bus(self, event_bus: EventBus) -> None:
        """Set EventBus for emitting events."""
        self._event_bus = event_bus
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "circuit_id": self.circuit_id,
            "state": self.state.value,
            "config": self._config.to_dict(),
            "stats": self.get_stats().to_dict(),
        }


class CircuitBreakerRegistry:
    """
    Registry for managing multiple circuit breakers.
    
    Provides centralized management of circuit breakers with
    bulk operations and monitoring capabilities.
    
    Usage:
        registry = CircuitBreakerRegistry()
        
        # Create or get circuit breaker
        breaker = registry.get_or_create("my_service", config=config)
        
        # Get all circuits
        all_circuits = registry.get_all()
        
        # Reset all
        registry.reset_all()
    """
    
    def __init__(self, event_bus: Optional[EventBus] = None):
        """
        Initialize registry.
        
        Args:
            event_bus: EventBus to use for all circuit breakers
        """
        self._event_bus = event_bus
        self._circuits: Dict[str, CircuitBreaker] = {}
        self._lock = threading.RLock()
    
    def get_or_create(
        self,
        circuit_id: str,
        config: Optional[CircuitBreakerConfig] = None,
    ) -> CircuitBreaker:
        """
        Get existing circuit breaker or create new one.
        
        Args:
            circuit_id: Unique identifier
            config: Configuration for new circuit breaker
            
        Returns:
            CircuitBreaker instance
        """
        with self._lock:
            if circuit_id not in self._circuits:
                self._circuits[circuit_id] = CircuitBreaker(
                    circuit_id=circuit_id,
                    config=config,
                    event_bus=self._event_bus,
                )
            return self._circuits[circuit_id]
    
    def get(self, circuit_id: str) -> Optional[CircuitBreaker]:
        """Get circuit breaker by ID."""
        with self._lock:
            return self._circuits.get(circuit_id)
    
    def get_all(self) -> Dict[str, CircuitBreaker]:
        """Get all circuit breakers."""
        with self._lock:
            return dict(self._circuits)
    
    def get_all_states(self) -> Dict[str, CircuitState]:
        """Get all circuit breaker states."""
        with self._lock:
            return {cid: cb.state for cid, cb in self._circuits.items()}
    
    def reset_all(self) -> None:
        """Reset all circuit breakers to CLOSED state."""
        with self._lock:
            for cb in self._circuits.values():
                cb.reset()
    
    def reset(self, circuit_id: str) -> bool:
        """
        Reset specific circuit breaker.
        
        Returns:
            True if circuit was found and reset, False otherwise
        """
        with self._lock:
            if circuit_id in self._circuits:
                self._circuits[circuit_id].reset()
                return True
            return False
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all circuit breakers."""
        with self._lock:
            return {cid: cb.get_stats().to_dict() for cid, cb in self._circuits.items()}
    
    def remove(self, circuit_id: str) -> bool:
        """Remove circuit breaker from registry."""
        with self._lock:
            if circuit_id in self._circuits:
                del self._circuits[circuit_id]
                return True
            return False
    
    def set_event_bus(self, event_bus: EventBus) -> None:
        """Set EventBus for all circuit breakers."""
        self._event_bus = event_bus
        with self._lock:
            for cb in self._circuits.values():
                cb.set_event_bus(event_bus)


# Global registry instance
_global_registry: Optional[CircuitBreakerRegistry] = None


def get_circuit_breaker_registry(event_bus: Optional[EventBus] = None) -> CircuitBreakerRegistry:
    """
    Get global circuit breaker registry.
    
    Creates registry on first call, returns existing on subsequent calls.
    
    Args:
        event_bus: EventBus to use (only on first call)
        
    Returns:
        Global CircuitBreakerRegistry instance
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = CircuitBreakerRegistry(event_bus=event_bus)
    return _global_registry
