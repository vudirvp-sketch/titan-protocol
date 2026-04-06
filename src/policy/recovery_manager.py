"""
TITAN FUSE Protocol - Recovery Manager

Autonomous recovery loops for error handling.
Implements automatic recovery strategies.

TASK-003: Policy Engine & Autonomous Recovery Loops
"""

import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import time


class RecoveryState(Enum):
    """State of recovery process."""
    IDLE = "idle"
    DETECTED = "detected"
    ANALYZING = "analyzing"
    RECOVERING = "recovering"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"


class RecoveryAction(Enum):
    """Types of recovery actions."""
    RETRY = "retry"
    ROLLBACK = "rollback"
    RESTART_PHASE = "restart_phase"
    SKIP_CHUNK = "skip_chunk"
    REINITIALIZE = "reinitialize"
    FALLBACK = "fallback"
    MANUAL = "manual"
    ABORT = "abort"


@dataclass
class RecoveryContext:
    """
    Context for recovery operation.

    Attributes:
        session_id: Session identifier
        phase: Current phase
        chunk_id: Current chunk (if applicable)
        error: Error that triggered recovery
        retry_count: Number of retries attempted
        last_successful_state: Last known good state
        metadata: Additional context
    """
    session_id: str
    phase: int = 0
    chunk_id: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    last_successful_state: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "phase": self.phase,
            "chunk_id": self.chunk_id,
            "error": self.error,
            "retry_count": self.retry_count,
            "last_successful_state": self.last_successful_state,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }


@dataclass
class RecoveryResult:
    """
    Result of a recovery operation.

    Attributes:
        success: Whether recovery succeeded
        action: Action taken
        message: Result message
        next_action: Suggested next action
        context: Updated context
        timestamp: When result was generated
    """
    success: bool
    action: Optional[RecoveryAction] = None
    message: str = ""
    next_action: Optional[str] = None
    context: Optional[RecoveryContext] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "action": self.action.value if self.action else None,
            "message": self.message,
            "next_action": self.next_action,
            "context": self.context.to_dict() if self.context else None,
            "timestamp": self.timestamp
        }


@dataclass
class RecoveryStrategy:
    """
    A recovery strategy.

    Attributes:
        name: Strategy name
        action: Recovery action
        condition_fn: Function to check if strategy applies
        execute_fn: Function to execute recovery
        max_attempts: Maximum attempts
        priority: Strategy priority
    """
    name: str
    action: RecoveryAction
    condition_fn: Callable[[RecoveryContext], bool]
    execute_fn: Callable[[RecoveryContext], RecoveryResult]
    max_attempts: int = 3
    priority: int = 100


class RecoveryManager:
    """
    Manager for autonomous recovery loops.

    Features:
    - Error detection
    - Strategy selection
    - Recovery execution
    - Verification
    - Escalation

    Usage:
        manager = RecoveryManager()

        # Register strategies
        manager.register_strategy(RecoveryStrategy(
            name="retry_on_timeout",
            action=RecoveryAction.RETRY,
            condition_fn=lambda ctx: "timeout" in str(ctx.error).lower(),
            execute_fn=lambda ctx: retry_operation(ctx),
            max_attempts=3
        ))

        # Start recovery
        context = RecoveryContext(
            session_id="abc123",
            error="Operation timed out"
        )
        result = manager.recover(context)
    """

    def __init__(self, max_recovery_attempts: int = 5):
        self.max_recovery_attempts = max_recovery_attempts
        self._strategies: Dict[str, RecoveryStrategy] = {}
        self._recovery_history: List[Dict[str, Any]] = []
        self._state = RecoveryState.IDLE
        self._current_context: Optional[RecoveryContext] = None

    @property
    def state(self) -> RecoveryState:
        """Get current recovery state."""
        return self._state

    def register_strategy(self, strategy: RecoveryStrategy) -> None:
        """Register a recovery strategy."""
        self._strategies[strategy.name] = strategy

    def unregister_strategy(self, name: str) -> bool:
        """Unregister a strategy."""
        if name in self._strategies:
            del self._strategies[name]
            return True
        return False

    def get_strategy(self, name: str) -> Optional[RecoveryStrategy]:
        """Get a strategy by name."""
        return self._strategies.get(name)

    def list_strategies(self) -> List[RecoveryStrategy]:
        """List all strategies sorted by priority."""
        return sorted(
            self._strategies.values(),
            key=lambda s: s.priority,
            reverse=True
        )

    def select_strategy(self, context: RecoveryContext) -> Optional[RecoveryStrategy]:
        """
        Select the best strategy for a context.

        Args:
            context: Recovery context

        Returns:
            Selected strategy or None
        """
        for strategy in self.list_strategies():
            try:
                if strategy.condition_fn(context):
                    return strategy
            except Exception:
                continue

        return None

    def recover(self, context: RecoveryContext) -> RecoveryResult:
        """
        Execute recovery process.

        Args:
            context: Recovery context

        Returns:
            Recovery result
        """
        self._state = RecoveryState.DETECTED
        self._current_context = context

        # Record recovery attempt
        self._record_attempt(context)

        # Check max attempts
        if context.retry_count >= self.max_recovery_attempts:
            return self._escalate(context, "Max recovery attempts exceeded")

        # Select strategy
        self._state = RecoveryState.ANALYZING
        strategy = self.select_strategy(context)

        if not strategy:
            return self._escalate(context, "No applicable recovery strategy")

        # Check strategy max attempts
        if context.retry_count >= strategy.max_attempts:
            return self._escalate(context, f"Strategy '{strategy.name}' max attempts exceeded")

        # Execute recovery
        self._state = RecoveryState.RECOVERING
        try:
            result = strategy.execute_fn(context)

            if result.success:
                self._state = RecoveryState.COMPLETED
            else:
                self._state = RecoveryState.FAILED

            return result

        except Exception as e:
            self._state = RecoveryState.FAILED
            return RecoveryResult(
                success=False,
                action=strategy.action,
                message=f"Recovery execution failed: {e}",
                context=context
            )

    def _escalate(self, context: RecoveryContext,
                  reason: str) -> RecoveryResult:
        """Escalate recovery to manual intervention."""
        self._state = RecoveryState.ESCALATED

        return RecoveryResult(
            success=False,
            action=RecoveryAction.MANUAL,
            message=f"Recovery escalated: {reason}",
            next_action="manual_intervention_required",
            context=context
        )

    def _record_attempt(self, context: RecoveryContext) -> None:
        """Record a recovery attempt."""
        self._recovery_history.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": context.session_id,
            "phase": context.phase,
            "chunk_id": context.chunk_id,
            "error": context.error,
            "retry_count": context.retry_count
        })

    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recovery history."""
        return self._recovery_history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get recovery statistics."""
        total = len(self._recovery_history)
        return {
            "total_attempts": total,
            "current_state": self._state.value,
            "strategies_registered": len(self._strategies),
            "recent_attempts": len(self._recovery_history[-10:])
        }

    def reset(self) -> None:
        """Reset recovery state."""
        self._state = RecoveryState.IDLE
        self._current_context = None


# Global recovery manager
_global_manager: Optional[RecoveryManager] = None


def get_recovery_manager() -> RecoveryManager:
    """Get the global recovery manager."""
    global _global_manager
    if _global_manager is None:
        _global_manager = RecoveryManager()
    return _global_manager


def start_recovery(context: RecoveryContext) -> RecoveryResult:
    """Start recovery process."""
    return get_recovery_manager().recover(context)


def execute_recovery(action: RecoveryAction,
                     context: RecoveryContext) -> RecoveryResult:
    """Execute a specific recovery action."""
    manager = get_recovery_manager()
    strategy = manager.get_strategy(action.value)

    if strategy:
        return strategy.execute_fn(context)

    return RecoveryResult(
        success=False,
        message=f"No strategy found for action: {action.value}"
    )
