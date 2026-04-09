"""
TITAN FUSE Protocol - Retry Executor Facade

ITEM_013b: RetryExecutorFacade for TITAN Protocol v1.2.0

Unified facade for retry and circuit breaker operations.
Wraps existing RetryExecutor with standardized interface.

Key Features:
- Single point for all retry operations
- Support for multiple named circuits (not just single circuit)
- Emits CIRCUIT_OPENED, CIRCUIT_CLOSED, CIRCUIT_HALF_OPEN events
- Prevents exponential request multiplication from nested retries
- Metrics tracking (total_requests, total_retries, circuit_trips)

Author: TITAN FUSE Team
Version: 1.2.0
"""

import time
import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, Callable, TypeVar, List, Set
import logging
import functools

from src.policy.retry_logic import (
    RetryExecutor,
    RetryPolicy,
    RetryResult,
    RetryStrategy,
    RetryState,
    DEFAULT_POLICY,
)
from src.events.event_bus import Event, EventSeverity, EventBus

T = TypeVar('T')


# =============================================================================
# Circuit State Enum
# =============================================================================

class CircuitState(Enum):
    """
    Circuit breaker state for named circuits.
    
    States:
    - CLOSED: Normal operation, requests flow through
    - OPEN: Circuit tripped, requests fail fast
    - HALF_OPEN: Testing if service recovered, limited requests allowed
    """
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# =============================================================================
# Circuit Data Class
# =============================================================================

@dataclass
class CircuitData:
    """
    Data structure for tracking individual circuit state.
    
    Attributes:
        circuit_id: Unique identifier for the circuit
        state: Current circuit state (CLOSED, OPEN, HALF_OPEN)
        consecutive_failures: Number of consecutive failures
        total_failures: Total failures since last reset
        total_successes: Total successes since last reset
        last_failure_time: Timestamp of last failure
        last_success_time: Timestamp of last success
        opened_at: When circuit was opened (None if closed)
        half_open_at: When circuit entered half-open state
        half_open_successes: Successes during half-open state
        half_open_requests: Total requests during half-open state
    """
    circuit_id: str
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    total_failures: int = 0
    total_successes: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    opened_at: Optional[float] = None
    half_open_at: Optional[float] = None
    half_open_successes: int = 0
    half_open_requests: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "circuit_id": self.circuit_id,
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
            "opened_at": self.opened_at,
            "half_open_at": self.half_open_at,
            "half_open_successes": self.half_open_successes,
            "half_open_requests": self.half_open_requests,
        }


# =============================================================================
# Retry Facade Config
# =============================================================================

@dataclass
class RetryFacadeConfig:
    """
    Configuration for RetryExecutorFacade.
    
    Attributes:
        default_max_retries: Default maximum retries (default: 3)
        default_backoff_strategy: Default backoff strategy
        circuit_breaker_threshold: Failures before circuit opens (default: 5)
        circuit_breaker_reset_ms: Time before circuit tries half-open (default: 60000)
        half_open_max_requests: Max requests in half-open state (default: 3)
        half_open_success_threshold: Successes needed to close circuit (default: 2)
        max_nested_depth: Maximum nested retry depth to prevent multiplication (default: 2)
        enable_metrics: Enable metrics tracking (default: True)
    """
    default_max_retries: int = 3
    default_backoff_strategy: str = "exponential"
    circuit_breaker_threshold: int = 5
    circuit_breaker_reset_ms: int = 60000
    half_open_max_requests: int = 3
    half_open_success_threshold: int = 2
    max_nested_depth: int = 2
    enable_metrics: bool = True
    base_delay_ms: int = 100
    max_delay_ms: int = 30000
    multiplier: float = 2.0
    jitter: float = 0.1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "default_max_retries": self.default_max_retries,
            "default_backoff_strategy": self.default_backoff_strategy,
            "circuit_breaker_threshold": self.circuit_breaker_threshold,
            "circuit_breaker_reset_ms": self.circuit_breaker_reset_ms,
            "half_open_max_requests": self.half_open_max_requests,
            "half_open_success_threshold": self.half_open_success_threshold,
            "max_nested_depth": self.max_nested_depth,
            "enable_metrics": self.enable_metrics,
            "base_delay_ms": self.base_delay_ms,
            "max_delay_ms": self.max_delay_ms,
            "multiplier": self.multiplier,
            "jitter": self.jitter,
        }


# =============================================================================
# Retry Facade Result
# =============================================================================

@dataclass
class FacadeResult:
    """
    Result from RetryExecutorFacade execution.
    
    Attributes:
        success: Whether the operation succeeded
        result: Result from the operation if successful
        error: Error message if failed
        attempts: Number of attempts made
        circuit_id: Circuit ID used
        circuit_state: Final circuit state
        total_delay_ms: Total delay from retries
        was_retried: Whether any retries occurred
        nested_depth: Nested retry depth detected
    """
    success: bool
    result: Any = None
    error: Optional[str] = None
    attempts: int = 0
    circuit_id: Optional[str] = None
    circuit_state: CircuitState = CircuitState.CLOSED
    total_delay_ms: int = 0
    was_retried: bool = False
    nested_depth: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "attempts": self.attempts,
            "circuit_id": self.circuit_id,
            "circuit_state": self.circuit_state.value,
            "total_delay_ms": self.total_delay_ms,
            "was_retried": self.was_retried,
            "nested_depth": self.nested_depth,
        }


# =============================================================================
# Retry Executor Facade
# =============================================================================

class RetryExecutorFacade:
    """
    Unified facade for retry and circuit breaker operations.
    
    This is the SINGLE POINT for all retry operations in TITAN Protocol v1.2.0.
    Wraps existing RetryExecutor with standardized interface.
    
    Key Features:
    - Multiple named circuits (not just single circuit)
    - Emits CIRCUIT_OPENED, CIRCUIT_CLOSED, CIRCUIT_HALF_OPEN events
    - Prevents exponential request multiplication from nested retries
    - Metrics tracking (total_requests, total_retries, circuit_trips)
    
    Usage:
        facade = RetryExecutorFacade(event_bus=event_bus)
        
        # Execute with retry
        result = facade.execute_with_retry(
            my_function,
            arg1, arg2,
            max_retries=3,
            backoff_strategy="exponential",
            circuit_id="skill_graph",
            kwarg1=value1
        )
        
        # Get circuit state
        state = facade.get_circuit_state("skill_graph")
        
        # Reset circuit
        facade.reset_circuit("skill_graph")
        
        # Get all circuits
        circuits = facade.get_all_circuits()
    
    Usage Contract:
        # CORRECT: Use facade
        result = retry_facade.execute_with_retry(
            adapter.on_execute,
            plan,
            max_retries=3,
            circuit_id="skill_graph"
        )
        
        # INCORRECT: Local retry loop (forbidden)
        for attempt in range(3):  # DO NOT DO THIS
            try:
                result = adapter.on_execute(plan)
            except Exception:
                continue
    """
    
    # Thread-local storage for tracking nested depth
    _nesting_depth = threading.local()
    
    def __init__(
        self,
        config: Optional[RetryFacadeConfig] = None,
        event_bus: Optional[EventBus] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize RetryExecutorFacade.
        
        Args:
            config: Configuration options
            event_bus: EventBus for emitting circuit events
            logger: Optional logger instance
        """
        self._config = config or RetryFacadeConfig()
        self._event_bus = event_bus
        self._logger = logger or logging.getLogger(__name__)
        
        # Circuits storage: circuit_id -> CircuitData
        self._circuits: Dict[str, CircuitData] = {}
        self._circuits_lock = threading.RLock()
        
        # Per-circuit executors: circuit_id -> RetryExecutor
        self._executors: Dict[str, RetryExecutor] = {}
        
        # Metrics
        self._metrics = {
            "total_requests": 0,
            "total_retries": 0,
            "total_successes": 0,
            "total_failures": 0,
            "circuit_trips": 0,
            "circuit_recoveries": 0,
            "nested_depth_violations": 0,
        }
        self._metrics_lock = threading.Lock()
        
        # Default policy template
        self._default_policy = self._create_policy_from_config()
    
    def _create_policy_from_config(self, max_retries: Optional[int] = None) -> RetryPolicy:
        """Create RetryPolicy from config."""
        strategy_map = {
            "fixed": RetryStrategy.FIXED,
            "linear": RetryStrategy.LINEAR,
            "exponential": RetryStrategy.EXPONENTIAL,
            "exponential_jitter": RetryStrategy.EXPONENTIAL_JITTER,
            "none": RetryStrategy.NONE,
        }
        
        return RetryPolicy(
            strategy=strategy_map.get(
                self._config.default_backoff_strategy,
                RetryStrategy.EXPONENTIAL_JITTER
            ),
            max_retries=max_retries or self._config.default_max_retries,
            base_delay_ms=self._config.base_delay_ms,
            max_delay_ms=self._config.max_delay_ms,
            multiplier=self._config.multiplier,
            jitter=self._config.jitter,
            circuit_breaker_threshold=self._config.circuit_breaker_threshold,
            circuit_breaker_reset_ms=self._config.circuit_breaker_reset_ms,
        )
    
    def _get_or_create_circuit(self, circuit_id: str) -> CircuitData:
        """Get or create circuit data for given ID."""
        with self._circuits_lock:
            if circuit_id not in self._circuits:
                self._circuits[circuit_id] = CircuitData(circuit_id=circuit_id)
            return self._circuits[circuit_id]
    
    def _get_or_create_executor(self, circuit_id: str, policy: Optional[RetryPolicy] = None) -> RetryExecutor:
        """Get or create executor for circuit."""
        with self._circuits_lock:
            if circuit_id not in self._executors:
                self._executors[circuit_id] = RetryExecutor(
                    policy or self._default_policy
                )
            return self._executors[circuit_id]
    
    def _emit_circuit_event(
        self,
        event_type: str,
        circuit_id: str,
        old_state: CircuitState,
        new_state: CircuitState,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit circuit state change event."""
        if not self._event_bus:
            return
        
        event = Event(
            event_type=event_type,
            data={
                "circuit_id": circuit_id,
                "old_state": old_state.value,
                "new_state": new_state.value,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                **(data or {}),
            },
            severity=EventSeverity.WARN if new_state == CircuitState.OPEN else EventSeverity.INFO,
            source="RetryExecutorFacade",
        )
        self._event_bus.emit(event)
    
    def _check_nested_depth(self) -> int:
        """Check and return current nesting depth."""
        depth = getattr(self._nesting_depth, 'depth', 0)
        return depth
    
    def _enter_nested_context(self) -> int:
        """Enter nested retry context, return current depth."""
        depth = getattr(self._nesting_depth, 'depth', 0)
        self._nesting_depth.depth = depth + 1
        return depth
    
    def _exit_nested_context(self) -> None:
        """Exit nested retry context."""
        depth = getattr(self._nesting_depth, 'depth', 0)
        self._nesting_depth.depth = max(0, depth - 1)
    
    def _update_circuit_state(
        self,
        circuit: CircuitData,
        executor: RetryExecutor,
    ) -> None:
        """Update circuit state based on executor state."""
        old_state = circuit.state
        
        # Check if executor circuit is open
        if executor.circuit_open:
            if circuit.state != CircuitState.OPEN:
                circuit.state = CircuitState.OPEN
                circuit.opened_at = time.time()
                
                # Update metrics
                with self._metrics_lock:
                    self._metrics["circuit_trips"] += 1
                
                # Emit event
                self._emit_circuit_event(
                    "CIRCUIT_OPENED",
                    circuit.circuit_id,
                    old_state,
                    CircuitState.OPEN,
                    {"consecutive_failures": circuit.consecutive_failures},
                )
                self._logger.warning(
                    f"Circuit '{circuit.circuit_id}' OPENED after {circuit.consecutive_failures} failures"
                )
        else:
            # Circuit is closed, check if we need to transition from OPEN/HALF_OPEN
            if circuit.state in (CircuitState.OPEN, CircuitState.HALF_OPEN):
                if circuit.state == CircuitState.OPEN:
                    # Transition to half-open first
                    circuit.state = CircuitState.HALF_OPEN
                    circuit.half_open_at = time.time()
                    circuit.half_open_successes = 0
                    circuit.half_open_requests = 0
                    
                    self._emit_circuit_event(
                        "CIRCUIT_HALF_OPEN",
                        circuit.circuit_id,
                        CircuitState.OPEN,
                        CircuitState.HALF_OPEN,
                    )
                    self._logger.info(
                        f"Circuit '{circuit.circuit_id}' entered HALF_OPEN state"
                    )
    
    def _record_success(self, circuit: CircuitData) -> None:
        """Record successful operation."""
        circuit.total_successes += 1
        circuit.last_success_time = time.time()
        circuit.consecutive_failures = 0
        
        if circuit.state == CircuitState.HALF_OPEN:
            circuit.half_open_successes += 1
            circuit.half_open_requests += 1
            
            # Check if we can close the circuit
            if circuit.half_open_successes >= self._config.half_open_success_threshold:
                old_state = circuit.state
                circuit.state = CircuitState.CLOSED
                circuit.opened_at = None
                circuit.half_open_at = None
                circuit.consecutive_failures = 0
                
                # Update metrics
                with self._metrics_lock:
                    self._metrics["circuit_recoveries"] += 1
                
                # Emit event
                self._emit_circuit_event(
                    "CIRCUIT_CLOSED",
                    circuit.circuit_id,
                    old_state,
                    CircuitState.CLOSED,
                )
                self._logger.info(
                    f"Circuit '{circuit.circuit_id}' CLOSED after recovery"
                )
    
    def _record_failure(self, circuit: CircuitData) -> None:
        """Record failed operation."""
        circuit.total_failures += 1
        circuit.consecutive_failures += 1
        circuit.last_failure_time = time.time()
        
        if circuit.state == CircuitState.HALF_OPEN:
            circuit.half_open_requests += 1
            
            # Check if half-open requests exceeded
            if circuit.half_open_requests >= self._config.half_open_max_requests:
                # Re-open circuit
                old_state = circuit.state
                circuit.state = CircuitState.OPEN
                circuit.opened_at = time.time()
                circuit.half_open_at = None
                
                self._emit_circuit_event(
                    "CIRCUIT_OPENED",
                    circuit.circuit_id,
                    old_state,
                    CircuitState.OPEN,
                    {"reason": "half_open_failure"},
                )
                self._logger.warning(
                    f"Circuit '{circuit.circuit_id}' re-OPENED from HALF_OPEN"
                )
    
    def execute_with_retry(
        self,
        func: Callable[..., T],
        *args,
        max_retries: Optional[int] = None,
        backoff_strategy: Optional[str] = None,
        circuit_id: Optional[str] = None,
        **kwargs,
    ) -> FacadeResult:
        """
        Execute function with retry and optional circuit breaker.
        
        This is the main entry point for all retry operations.
        
        Args:
            func: Function to execute
            *args: Positional arguments for function
            max_retries: Maximum retries (default from config)
            backoff_strategy: Backoff strategy (fixed, linear, exponential, exponential_jitter, none)
            circuit_id: Optional circuit ID for circuit breaker
            **kwargs: Keyword arguments for function
            
        Returns:
            FacadeResult with execution outcome
            
        Raises:
            RuntimeError: If max nested depth exceeded
        """
        # Check nested depth
        current_depth = self._check_nested_depth()
        if current_depth >= self._config.max_nested_depth:
            with self._metrics_lock:
                self._metrics["nested_depth_violations"] += 1
            self._logger.warning(
                f"Nested retry depth {current_depth} exceeds max {self._config.max_nested_depth}"
            )
            return FacadeResult(
                success=False,
                error=f"Nested retry depth exceeded ({current_depth})",
                nested_depth=current_depth,
                circuit_id=circuit_id,
            )
        
        # Enter nested context
        self._enter_nested_context()
        
        try:
            # Update metrics
            with self._metrics_lock:
                self._metrics["total_requests"] += 1
            
            # Create policy with specified parameters
            policy = self._create_policy_from_config(max_retries)
            
            # Override strategy if specified
            if backoff_strategy:
                strategy_map = {
                    "fixed": RetryStrategy.FIXED,
                    "linear": RetryStrategy.LINEAR,
                    "exponential": RetryStrategy.EXPONENTIAL,
                    "exponential_jitter": RetryStrategy.EXPONENTIAL_JITTER,
                    "none": RetryStrategy.NONE,
                }
                policy.strategy = strategy_map.get(
                    backoff_strategy, RetryStrategy.EXPONENTIAL_JITTER
                )
            
            # Get or create circuit and executor
            circuit = None
            if circuit_id:
                circuit = self._get_or_create_circuit(circuit_id)
                
                # Check circuit state before executing
                if circuit.state == CircuitState.OPEN:
                    # Check if we should transition to half-open
                    if circuit.opened_at:
                        elapsed_ms = (time.time() - circuit.opened_at) * 1000
                        if elapsed_ms >= self._config.circuit_breaker_reset_ms:
                            # Transition to half-open
                            old_state = circuit.state
                            circuit.state = CircuitState.HALF_OPEN
                            circuit.half_open_at = time.time()
                            circuit.half_open_successes = 0
                            circuit.half_open_requests = 0
                            
                            self._emit_circuit_event(
                                "CIRCUIT_HALF_OPEN",
                                circuit.circuit_id,
                                old_state,
                                CircuitState.HALF_OPEN,
                            )
                            self._logger.info(
                                f"Circuit '{circuit.circuit_id}' entered HALF_OPEN state"
                            )
                        else:
                            # Circuit still open, fail fast
                            return FacadeResult(
                                success=False,
                                error=f"Circuit '{circuit_id}' is OPEN",
                                circuit_id=circuit_id,
                                circuit_state=CircuitState.OPEN,
                            )
                
                # Check half-open request limit
                if circuit.state == CircuitState.HALF_OPEN:
                    if circuit.half_open_requests >= self._config.half_open_max_requests:
                        return FacadeResult(
                            success=False,
                            error=f"Circuit '{circuit_id}' is HALF_OPEN and at max requests",
                            circuit_id=circuit_id,
                            circuit_state=CircuitState.HALF_OPEN,
                        )
            
            # Create wrapper function with args/kwargs
            def wrapper():
                return func(*args, **kwargs)
            
            # Create executor for this operation
            executor = RetryExecutor(policy)
            
            # Execute with retry
            retry_result = executor.execute(wrapper)
            
            # Record result
            if retry_result.success:
                if circuit:
                    self._record_success(circuit)
                with self._metrics_lock:
                    self._metrics["total_successes"] += 1
            else:
                if circuit:
                    self._record_failure(circuit)
                    # Check if executor circuit opened
                    self._update_circuit_state(circuit, executor)
                with self._metrics_lock:
                    self._metrics["total_failures"] += 1
            
            # Track retries
            if retry_result.attempts > 1:
                with self._metrics_lock:
                    self._metrics["total_retries"] += retry_result.attempts - 1
            
            return FacadeResult(
                success=retry_result.success,
                result=retry_result.result,
                error=retry_result.last_error,
                attempts=retry_result.attempts,
                circuit_id=circuit_id,
                circuit_state=circuit.state if circuit else CircuitState.CLOSED,
                total_delay_ms=retry_result.total_delay_ms,
                was_retried=retry_result.attempts > 1,
                nested_depth=current_depth,
            )
            
        finally:
            self._exit_nested_context()
    
    async def execute_with_retry_async(
        self,
        func: Callable[..., T],
        *args,
        max_retries: Optional[int] = None,
        backoff_strategy: Optional[str] = None,
        circuit_id: Optional[str] = None,
        **kwargs,
    ) -> FacadeResult:
        """
        Execute async function with retry and optional circuit breaker.
        
        Async version of execute_with_retry.
        
        Args:
            func: Async function to execute
            *args: Positional arguments for function
            max_retries: Maximum retries (default from config)
            backoff_strategy: Backoff strategy
            circuit_id: Optional circuit ID for circuit breaker
            **kwargs: Keyword arguments for function
            
        Returns:
            FacadeResult with execution outcome
        """
        # Check nested depth
        current_depth = self._check_nested_depth()
        if current_depth >= self._config.max_nested_depth:
            with self._metrics_lock:
                self._metrics["nested_depth_violations"] += 1
            self._logger.warning(
                f"Nested retry depth {current_depth} exceeds max {self._config.max_nested_depth}"
            )
            return FacadeResult(
                success=False,
                error=f"Nested retry depth exceeded ({current_depth})",
                nested_depth=current_depth,
                circuit_id=circuit_id,
            )
        
        # Enter nested context
        self._enter_nested_context()
        
        try:
            # Update metrics
            with self._metrics_lock:
                self._metrics["total_requests"] += 1
            
            # Create policy
            policy = self._create_policy_from_config(max_retries)
            
            # Override strategy if specified
            if backoff_strategy:
                strategy_map = {
                    "fixed": RetryStrategy.FIXED,
                    "linear": RetryStrategy.LINEAR,
                    "exponential": RetryStrategy.EXPONENTIAL,
                    "exponential_jitter": RetryStrategy.EXPONENTIAL_JITTER,
                    "none": RetryStrategy.NONE,
                }
                policy.strategy = strategy_map.get(
                    backoff_strategy, RetryStrategy.EXPONENTIAL_JITTER
                )
            
            # Get or create circuit
            circuit = None
            if circuit_id:
                circuit = self._get_or_create_circuit(circuit_id)
                
                if circuit.state == CircuitState.OPEN:
                    if circuit.opened_at:
                        elapsed_ms = (time.time() - circuit.opened_at) * 1000
                        if elapsed_ms >= self._config.circuit_breaker_reset_ms:
                            old_state = circuit.state
                            circuit.state = CircuitState.HALF_OPEN
                            circuit.half_open_at = time.time()
                            circuit.half_open_successes = 0
                            circuit.half_open_requests = 0
                            
                            self._emit_circuit_event(
                                "CIRCUIT_HALF_OPEN",
                                circuit.circuit_id,
                                old_state,
                                CircuitState.HALF_OPEN,
                            )
                        else:
                            return FacadeResult(
                                success=False,
                                error=f"Circuit '{circuit_id}' is OPEN",
                                circuit_id=circuit_id,
                                circuit_state=CircuitState.OPEN,
                            )
                
                if circuit.state == CircuitState.HALF_OPEN:
                    if circuit.half_open_requests >= self._config.half_open_max_requests:
                        return FacadeResult(
                            success=False,
                            error=f"Circuit '{circuit_id}' is HALF_OPEN and at max requests",
                            circuit_id=circuit_id,
                            circuit_state=CircuitState.HALF_OPEN,
                        )
            
            # Create async wrapper
            async def wrapper():
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                return func(*args, **kwargs)
            
            # Create executor
            executor = RetryExecutor(policy)
            
            # Execute with retry
            retry_result = await executor.execute_async(wrapper)
            
            # Record result
            if retry_result.success:
                if circuit:
                    self._record_success(circuit)
                with self._metrics_lock:
                    self._metrics["total_successes"] += 1
            else:
                if circuit:
                    self._record_failure(circuit)
                    self._update_circuit_state(circuit, executor)
                with self._metrics_lock:
                    self._metrics["total_failures"] += 1
            
            if retry_result.attempts > 1:
                with self._metrics_lock:
                    self._metrics["total_retries"] += retry_result.attempts - 1
            
            return FacadeResult(
                success=retry_result.success,
                result=retry_result.result,
                error=retry_result.last_error,
                attempts=retry_result.attempts,
                circuit_id=circuit_id,
                circuit_state=circuit.state if circuit else CircuitState.CLOSED,
                total_delay_ms=retry_result.total_delay_ms,
                was_retried=retry_result.attempts > 1,
                nested_depth=current_depth,
            )
            
        finally:
            self._exit_nested_context()
    
    def get_circuit_state(self, circuit_id: str) -> CircuitState:
        """
        Get state of named circuit.
        
        Args:
            circuit_id: Circuit identifier
            
        Returns:
            CircuitState (CLOSED if circuit doesn't exist)
        """
        with self._circuits_lock:
            if circuit_id in self._circuits:
                circuit = self._circuits[circuit_id]
                
                # Check if OPEN circuit should transition to HALF_OPEN
                if circuit.state == CircuitState.OPEN and circuit.opened_at:
                    elapsed_ms = (time.time() - circuit.opened_at) * 1000
                    if elapsed_ms >= self._config.circuit_breaker_reset_ms:
                        return CircuitState.HALF_OPEN
                
                return circuit.state
            return CircuitState.CLOSED
    
    def reset_circuit(self, circuit_id: str) -> bool:
        """
        Reset named circuit to CLOSED state.
        
        Args:
            circuit_id: Circuit identifier
            
        Returns:
            True if circuit was reset, False if circuit doesn't exist
        """
        with self._circuits_lock:
            if circuit_id in self._circuits:
                circuit = self._circuits[circuit_id]
                old_state = circuit.state
                
                # Reset circuit
                circuit.state = CircuitState.CLOSED
                circuit.consecutive_failures = 0
                circuit.opened_at = None
                circuit.half_open_at = None
                circuit.half_open_successes = 0
                circuit.half_open_requests = 0
                
                # Reset executor
                if circuit_id in self._executors:
                    self._executors[circuit_id]._consecutive_failures = 0
                    self._executors[circuit_id]._circuit_open_until = None
                
                # Emit event if state changed
                if old_state != CircuitState.CLOSED:
                    self._emit_circuit_event(
                        "CIRCUIT_CLOSED",
                        circuit_id,
                        old_state,
                        CircuitState.CLOSED,
                        {"reason": "manual_reset"},
                    )
                
                self._logger.info(f"Circuit '{circuit_id}' manually reset to CLOSED")
                return True
            return False
    
    def get_all_circuits(self) -> Dict[str, CircuitState]:
        """
        Get all circuit states.
        
        Returns:
            Dictionary mapping circuit_id to CircuitState
        """
        with self._circuits_lock:
            return {
                circuit_id: self.get_circuit_state(circuit_id)
                for circuit_id in self._circuits
            }
    
    def get_circuit_data(self, circuit_id: str) -> Optional[CircuitData]:
        """
        Get detailed circuit data.
        
        Args:
            circuit_id: Circuit identifier
            
        Returns:
            CircuitData if exists, None otherwise
        """
        with self._circuits_lock:
            if circuit_id in self._circuits:
                return self._circuits[circuit_id]
            return None
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get facade metrics.
        
        Returns:
            Dictionary with metrics:
            - total_requests: Total requests processed
            - total_retries: Total retries performed
            - total_successes: Total successful operations
            - total_failures: Total failed operations
            - circuit_trips: Total circuit trips (OPEN transitions)
            - circuit_recoveries: Total circuit recoveries (CLOSED transitions)
            - nested_depth_violations: Nested depth violations
            - circuits: Per-circuit metrics
        """
        with self._metrics_lock:
            metrics = dict(self._metrics)
        
        # Add circuit metrics
        with self._circuits_lock:
            metrics["circuits"] = {
                circuit_id: circuit.to_dict()
                for circuit_id, circuit in self._circuits.items()
            }
            metrics["circuit_count"] = len(self._circuits)
        
        # Add config
        metrics["config"] = self._config.to_dict()
        
        return metrics
    
    def reset_metrics(self) -> None:
        """Reset all metrics."""
        with self._metrics_lock:
            self._metrics = {
                "total_requests": 0,
                "total_retries": 0,
                "total_successes": 0,
                "total_failures": 0,
                "circuit_trips": 0,
                "circuit_recoveries": 0,
                "nested_depth_violations": 0,
            }
    
    def set_event_bus(self, event_bus: EventBus) -> None:
        """
        Set EventBus for emitting events.
        
        Args:
            event_bus: EventBus instance
        """
        self._event_bus = event_bus
    
    def is_circuit_open(self, circuit_id: str) -> bool:
        """
        Check if circuit is open.
        
        Args:
            circuit_id: Circuit identifier
            
        Returns:
            True if circuit is OPEN, False otherwise
        """
        return self.get_circuit_state(circuit_id) == CircuitState.OPEN
    
    def is_circuit_half_open(self, circuit_id: str) -> bool:
        """
        Check if circuit is half-open.
        
        Args:
            circuit_id: Circuit identifier
            
        Returns:
            True if circuit is HALF_OPEN, False otherwise
        """
        return self.get_circuit_state(circuit_id) == CircuitState.HALF_OPEN
    
    def with_retry(
        self,
        max_retries: int = 3,
        backoff_strategy: str = "exponential",
        circuit_id: Optional[str] = None,
    ):
        """
        Decorator to add retry logic to a function.
        
        Args:
            max_retries: Maximum retries
            backoff_strategy: Backoff strategy
            circuit_id: Optional circuit ID
            
        Usage:
            @retry_facade.with_retry(max_retries=3, circuit_id="my_service")
            def my_function():
                ...
        """
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                result = self.execute_with_retry(
                    func,
                    *args,
                    max_retries=max_retries,
                    backoff_strategy=backoff_strategy,
                    circuit_id=circuit_id,
                    **kwargs,
                )
                if result.success:
                    return result.result
                raise Exception(result.error)
            
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                result = await self.execute_with_retry_async(
                    func,
                    *args,
                    max_retries=max_retries,
                    backoff_strategy=backoff_strategy,
                    circuit_id=circuit_id,
                    **kwargs,
                )
                if result.success:
                    return result.result
                raise Exception(result.error)
            
            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            return wrapper
        
        return decorator


# =============================================================================
# Factory Function
# =============================================================================

def create_retry_facade(
    config: Optional[Dict[str, Any]] = None,
    event_bus: Optional[EventBus] = None,
    logger: Optional[logging.Logger] = None,
) -> RetryExecutorFacade:
    """
    Factory function to create RetryExecutorFacade.
    
    Args:
        config: Optional configuration dictionary
        event_bus: Optional EventBus instance
        logger: Optional logger instance
        
    Returns:
        Configured RetryExecutorFacade instance
    """
    facade_config = None
    if config:
        facade_config = RetryFacadeConfig(**config)
    
    return RetryExecutorFacade(
        config=facade_config,
        event_bus=event_bus,
        logger=logger,
    )


# =============================================================================
# Global Instance (Singleton Pattern)
# =============================================================================

_global_facade: Optional[RetryExecutorFacade] = None


def get_retry_facade(
    config: Optional[Dict[str, Any]] = None,
    event_bus: Optional[EventBus] = None,
) -> RetryExecutorFacade:
    """
    Get global RetryExecutorFacade instance.
    
    Creates instance on first call, returns existing instance on subsequent calls.
    
    Args:
        config: Configuration (only used on first call)
        event_bus: EventBus instance (only used on first call)
        
    Returns:
        Global RetryExecutorFacade instance
    """
    global _global_facade
    if _global_facade is None:
        _global_facade = create_retry_facade(config=config, event_bus=event_bus)
    elif event_bus and _global_facade._event_bus is None:
        _global_facade.set_event_bus(event_bus)
    return _global_facade


def reset_retry_facade() -> None:
    """Reset global facade instance (useful for testing)."""
    global _global_facade
    _global_facade = None
