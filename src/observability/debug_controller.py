"""
TITAN FUSE Protocol - Debug Controller

Debug mode with reasoning locks and step-through capability.
Provides fine-grained control over execution for debugging.

TASK-002: Advanced Observability & Transparency Layer
"""

import json
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable, Set
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import time


class DebugMode(Enum):
    """Debug mode levels."""
    DISABLED = "disabled"
    NORMAL = "normal"       # Log all steps
    STEP = "step"           # Step through each operation
    BREAKPOINT = "breakpoint"  # Stop at breakpoints


class DebugLockType(Enum):
    """Types of debug locks."""
    STEP = "step"
    BREAKPOINT = "breakpoint"
    GATE = "gate"
    ERROR = "error"
    MANUAL = "manual"


@dataclass
class DebugLock:
    """
    A lock that pauses execution for debugging.

    Attributes:
        lock_id: Unique lock identifier
        lock_type: Type of lock
        reason: Reason for the lock
        created_at: When the lock was created
        released_at: When the lock was released
        metadata: Additional metadata
    """
    lock_id: str = field(default_factory=lambda: str(id(object()))[-8:])
    lock_type: DebugLockType = DebugLockType.MANUAL
    reason: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    released_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    _event: threading.Event = field(default_factory=threading.Event, repr=False)

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait for the lock to be released."""
        return self._event.wait(timeout)

    def release(self) -> None:
        """Release the lock."""
        self.released_at = datetime.utcnow().isoformat() + "Z"
        self._event.set()

    def is_released(self) -> bool:
        """Check if lock is released."""
        return self._event.is_set()


@dataclass
class Breakpoint:
    """
    A breakpoint for debugging.

    Attributes:
        name: Breakpoint name
        condition: Optional condition for triggering
        on_step_types: Step types that trigger this breakpoint
        on_phase: Phases that trigger this breakpoint
        on_gate: Gates that trigger this breakpoint
        enabled: Whether breakpoint is enabled
        hit_count: Number of times hit
    """
    name: str
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    on_step_types: Set[str] = field(default_factory=set)
    on_phase: Set[int] = field(default_factory=set)
    on_gate: Set[str] = field(default_factory=set)
    enabled: bool = True
    hit_count: int = 0
    max_hits: Optional[int] = None

    def should_trigger(self, context: Dict[str, Any]) -> bool:
        """Check if breakpoint should trigger."""
        if not self.enabled:
            return False

        if self.max_hits and self.hit_count >= self.max_hits:
            return False

        # Check step type
        step_type = context.get("step_type")
        if self.on_step_types and step_type not in self.on_step_types:
            return False

        # Check phase
        phase = context.get("phase")
        if self.on_phase and phase not in self.on_phase:
            return False

        # Check gate
        gate = context.get("gate")
        if self.on_gate and gate not in self.on_gate:
            return False

        # Check condition
        if self.condition and not self.condition(context):
            return False

        return True

    def hit(self) -> None:
        """Record a hit."""
        self.hit_count += 1


class DebugController:
    """
    Controller for debug mode.

    Features:
    - Step-through execution
    - Breakpoints
    - Execution locks
    - Debug logging
    - State inspection

    Usage:
        controller = DebugController()

        # Enable debug mode
        controller.enable(DebugMode.STEP)

        # Set breakpoints
        controller.set_breakpoint(Breakpoint(
            name="before_gate_04",
            on_phase={4}
        ))

        # In execution code:
        if controller.should_pause(context):
            lock = controller.create_lock(DebugLockType.BREAKPOINT)
            lock.wait()  # Blocks until released

        # Release all locks to continue
        controller.release_all()
    """

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path
        self._mode = DebugMode.DISABLED
        self._breakpoints: Dict[str, Breakpoint] = {}
        self._active_locks: Dict[str, DebugLock] = {}
        self._lock_history: List[DebugLock] = []
        self._step_count = 0
        self._lock = threading.Lock()
        self._on_lock_created: Optional[Callable[[DebugLock], None]] = None
        self._on_lock_released: Optional[Callable[[DebugLock], None]] = None

    @property
    def mode(self) -> DebugMode:
        """Get current debug mode."""
        return self._mode

    def is_enabled(self) -> bool:
        """Check if debug mode is enabled."""
        return self._mode != DebugMode.DISABLED

    def enable(self, mode: DebugMode = DebugMode.NORMAL) -> None:
        """Enable debug mode."""
        self._mode = mode
        self._log(f"Debug mode enabled: {mode.value}")

    def disable(self) -> None:
        """Disable debug mode."""
        self._mode = DebugMode.DISABLED
        self.release_all()
        self._log("Debug mode disabled")

    def set_breakpoint(self, breakpoint: Breakpoint) -> None:
        """Set a breakpoint."""
        with self._lock:
            self._breakpoints[breakpoint.name] = breakpoint
        self._log(f"Breakpoint set: {breakpoint.name}")

    def remove_breakpoint(self, name: str) -> bool:
        """Remove a breakpoint."""
        with self._lock:
            if name in self._breakpoints:
                del self._breakpoints[name]
                self._log(f"Breakpoint removed: {name}")
                return True
        return False

    def get_breakpoint(self, name: str) -> Optional[Breakpoint]:
        """Get a breakpoint by name."""
        return self._breakpoints.get(name)

    def list_breakpoints(self) -> List[Breakpoint]:
        """List all breakpoints."""
        return list(self._breakpoints.values())

    def should_pause(self, context: Dict[str, Any]) -> bool:
        """
        Check if execution should pause.

        Args:
            context: Current execution context

        Returns:
            True if execution should pause
        """
        if self._mode == DebugMode.DISABLED:
            return False

        if self._mode == DebugMode.STEP:
            return True

        if self._mode == DebugMode.BREAKPOINT:
            with self._lock:
                for bp in self._breakpoints.values():
                    if bp.should_trigger(context):
                        bp.hit()
                        return True

        return False

    def create_lock(self, lock_type: DebugLockType,
                    reason: str = "",
                    metadata: Optional[Dict[str, Any]] = None) -> DebugLock:
        """
        Create a debug lock.

        Args:
            lock_type: Type of lock
            reason: Reason for the lock
            metadata: Additional metadata

        Returns:
            The created lock
        """
        lock = DebugLock(
            lock_type=lock_type,
            reason=reason,
            metadata=metadata or {}
        )

        with self._lock:
            self._active_locks[lock.lock_id] = lock

        self._log(f"Lock created: {lock.lock_id} ({lock_type.value}) - {reason}")

        if self._on_lock_created:
            try:
                self._on_lock_created(lock)
            except Exception as e:
                self._log(f"Lock callback error: {e}")

        return lock

    def release_lock(self, lock_id: str) -> bool:
        """Release a specific lock."""
        with self._lock:
            lock = self._active_locks.get(lock_id)
            if lock:
                lock.release()
                self._lock_history.append(lock)
                del self._active_locks[lock_id]
                self._log(f"Lock released: {lock_id}")

                if self._on_lock_released:
                    try:
                        self._on_lock_released(lock)
                    except Exception as e:
                        self._log(f"Lock callback error: {e}")

                return True
        return False

    def release_all(self) -> int:
        """Release all active locks."""
        count = 0
        with self._lock:
            for lock in self._active_locks.values():
                lock.release()
                self._lock_history.append(lock)
                count += 1
            self._active_locks.clear()

        if count > 0:
            self._log(f"Released {count} locks")

        return count

    def get_active_locks(self) -> List[DebugLock]:
        """Get all active locks."""
        with self._lock:
            return list(self._active_locks.values())

    def get_lock_history(self, limit: int = 100) -> List[DebugLock]:
        """Get lock history."""
        with self._lock:
            return self._lock_history[-limit:]

    def step(self) -> None:
        """Advance one step in STEP mode."""
        self._step_count += 1
        self.release_all()

    def get_state(self) -> Dict[str, Any]:
        """Get current debug state."""
        with self._lock:
            return {
                "mode": self._mode.value,
                "enabled": self.is_enabled(),
                "step_count": self._step_count,
                "active_locks": len(self._active_locks),
                "breakpoints": len(self._breakpoints),
                "lock_history_count": len(self._lock_history)
            }

    def on_lock_created(self, callback: Callable[[DebugLock], None]) -> None:
        """Set callback for lock creation."""
        self._on_lock_created = callback

    def on_lock_released(self, callback: Callable[[DebugLock], None]) -> None:
        """Set callback for lock release."""
        self._on_lock_released = callback

    def _log(self, message: str) -> None:
        """Log a debug message."""
        timestamp = datetime.utcnow().isoformat() + "Z"
        log_entry = f"[{timestamp}] {message}"

        if self.log_path:
            try:
                with open(self.log_path, "a") as f:
                    f.write(log_entry + "\n")
            except Exception:
                pass


# Global debug controller
_global_controller: Optional[DebugController] = None


def get_debug_controller() -> DebugController:
    """Get the global debug controller."""
    global _global_controller
    if _global_controller is None:
        _global_controller = DebugController()
    return _global_controller


def enable_debug(mode: DebugMode = DebugMode.NORMAL) -> None:
    """Enable debug mode globally."""
    get_debug_controller().enable(mode)


def disable_debug() -> None:
    """Disable debug mode globally."""
    get_debug_controller().disable()


def set_breakpoint(breakpoint: Breakpoint) -> None:
    """Set a breakpoint globally."""
    get_debug_controller().set_breakpoint(breakpoint)


def step_through() -> None:
    """Step through in STEP mode."""
    get_debug_controller().step()
