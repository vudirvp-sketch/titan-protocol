"""
Interactive Session for TITAN Protocol v4.0.0.

ITEM-PROD-02: Core debugging session management.

Provides step-by-step execution control, breakpoint management,
state inspection/modification, and rollback support.

Integration:
- EventBus: Subscribe to events for breakpoints and pausing
- StateManager: Inspect and modify session state
- CheckpointManager: Rollback to previous states

Author: TITAN FUSE Team
Version: 4.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable, Set, TYPE_CHECKING
import logging
import json
import threading
import queue
import time

if TYPE_CHECKING:
    from ..events.event_bus import EventBus, Event
    from ..state.state_manager import StateManager, SessionState
    from ..state.checkpoint_manager import CheckpointManager


class SessionStatus(Enum):
    """Status of an interactive session."""
    INITIALIZED = "initialized"
    RUNNING = "running"
    PAUSED = "paused"
    STEP_MODE = "step_mode"
    BREAKPOINT_HIT = "breakpoint_hit"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class Breakpoint:
    """
    Breakpoint definition for interactive debugging.
    
    Attributes:
        event: Event type that triggers this breakpoint
        condition: Optional condition (not yet implemented)
        hit_count: Number of times this breakpoint was hit
        enabled: Whether breakpoint is active
        created_at: When breakpoint was created
    """
    event: str
    condition: Optional[str] = None
    hit_count: int = 0
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize breakpoint to dictionary."""
        return {
            "event": self.event,
            "condition": self.condition,
            "hit_count": self.hit_count,
            "enabled": self.enabled,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Breakpoint":
        """Deserialize breakpoint from dictionary."""
        return cls(
            event=data["event"],
            condition=data.get("condition"),
            hit_count=data.get("hit_count", 0),
            enabled=data.get("enabled", True),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
        )


@dataclass
class SessionConfig:
    """
    Configuration for interactive session.
    
    Attributes:
        enabled: Whether interactive mode is enabled
        prompt: REPL prompt string
        history_file: Path to command history file
        auto_pause_on: Event types that automatically pause execution
        max_history: Maximum number of history entries
        step_timeout_ms: Timeout for step operations in milliseconds
    """
    enabled: bool = False
    prompt: str = "titan> "
    history_file: str = ".titan/repl_history"
    auto_pause_on: List[str] = field(default_factory=lambda: ["GATE_FAIL", "CLARITY_LOW"])
    max_history: int = 1000
    step_timeout_ms: int = 30000
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionConfig":
        """Create config from dictionary."""
        return cls(
            enabled=data.get("enabled", False),
            prompt=data.get("prompt", "titan> "),
            history_file=data.get("history_file", ".titan/repl_history"),
            auto_pause_on=data.get("auto_pause_on", ["GATE_FAIL", "CLARITY_LOW"]),
            max_history=data.get("max_history", 1000),
            step_timeout_ms=data.get("step_timeout_ms", 30000),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize config to dictionary."""
        return {
            "enabled": self.enabled,
            "prompt": self.prompt,
            "history_file": self.history_file,
            "auto_pause_on": self.auto_pause_on,
            "max_history": self.max_history,
            "step_timeout_ms": self.step_timeout_ms,
        }


@dataclass
class SessionStep:
    """
    Record of a single step in the session.
    
    Attributes:
        step_number: Sequential step number
        event: Event that was processed (if any)
        state_snapshot: Snapshot of state after step
        timestamp: When step occurred
    """
    step_number: int
    event: Optional[Dict[str, Any]] = None
    state_snapshot: Optional[Dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize step to dictionary."""
        return {
            "step_number": self.step_number,
            "event": self.event,
            "state_snapshot": self.state_snapshot,
            "timestamp": self.timestamp,
        }


class InteractiveSession:
    """
    Interactive debugging session for TITAN Protocol.
    
    ITEM-PROD-02: Provides REPL-like debugging interface with:
    - Step-by-step execution control
    - Breakpoint management
    - State inspection and modification
    - Rollback support
    
    Usage:
        session = InteractiveSession(
            event_bus=event_bus,
            state_manager=state_manager,
            checkpoint_manager=checkpoint_manager,
            config=SessionConfig(enabled=True)
        )
        
        # Add breakpoints
        session.add_breakpoint("GATE_FAIL")
        session.add_breakpoint("BUDGET_EXCEEDED")
        
        # Start session
        session.start()
        
        # Step through execution
        session.step()
        
        # Inspect state
        value = session.inspect("gates.GATE-00.status")
        
        # Modify state
        session.modify("gates.GATE-00.status", "PASS")
        
        # Continue until next breakpoint
        session.continue_execution()
    """
    
    def __init__(
        self,
        event_bus: "EventBus" = None,
        state_manager: "StateManager" = None,
        checkpoint_manager: "CheckpointManager" = None,
        config: SessionConfig = None,
    ):
        """
        Initialize interactive session.
        
        Args:
            event_bus: EventBus for event subscription
            state_manager: StateManager for state access
            checkpoint_manager: CheckpointManager for rollback
            config: Session configuration
        """
        self.logger = logging.getLogger(__name__)
        self.event_bus = event_bus
        self.state_manager = state_manager
        self.checkpoint_manager = checkpoint_manager
        self.config = config or SessionConfig()
        
        # Session state
        self._status = SessionStatus.INITIALIZED
        self._step_count = 0
        self._breakpoints: Dict[str, Breakpoint] = {}
        self._step_history: List[SessionStep] = []
        self._current_event: Optional["Event"] = None
        
        # Threading for async control
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default
        self._step_queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        
        # Callbacks
        self._on_breakpoint_hit: Optional[Callable[[Breakpoint, "Event"], None]] = None
        self._on_pause: Optional[Callable[[], None]] = None
        self._on_resume: Optional[Callable[[], None]] = None
        
        self.logger.info(f"InteractiveSession initialized (enabled={self.config.enabled})")
    
    @property
    def status(self) -> SessionStatus:
        """Get current session status."""
        return self._status
    
    @property
    def step_count(self) -> int:
        """Get current step count."""
        return self._step_count
    
    @property
    def is_paused(self) -> bool:
        """Check if session is paused."""
        return not self._pause_event.is_set()
    
    def start(self) -> None:
        """
        Start the interactive session.
        
        Subscribes to all events for monitoring and enables
        breakpoint handling.
        """
        if not self.config.enabled:
            self.logger.warning("Interactive mode is disabled in config")
            return
        
        with self._lock:
            if self._status == SessionStatus.RUNNING:
                self.logger.warning("Session already running")
                return
            
            self._status = SessionStatus.RUNNING
            self._step_count = 0
            self._step_history.clear()
            
            # Subscribe to all events for breakpoint checking
            if self.event_bus:
                self.event_bus.subscribe("*", self._on_event, priority=1000)
                
                # Also subscribe to auto-pause events
                for event_type in self.config.auto_pause_on:
                    self.add_breakpoint(event_type)
            
            self.logger.info("Interactive session started")
    
    def stop(self) -> None:
        """
        Stop the interactive session.
        
        Unsubscribes from events and cleans up.
        """
        with self._lock:
            if self._status == SessionStatus.COMPLETED:
                return
            
            self._status = SessionStatus.COMPLETED
            
            # Unsubscribe from events
            if self.event_bus:
                self.event_bus.unsubscribe("*", self._on_event)
            
            # Resume if paused
            self._pause_event.set()
            
            self.logger.info("Interactive session stopped")
    
    def step(self) -> None:
        """
        Execute a single step.
        
        If paused, allows one event to be processed.
        If in step mode, processes next event.
        """
        if self._status not in (SessionStatus.RUNNING, SessionStatus.PAUSED, 
                                 SessionStatus.BREAKPOINT_HIT, SessionStatus.STEP_MODE):
            self.logger.warning(f"Cannot step in status: {self._status}")
            return
        
        with self._lock:
            self._status = SessionStatus.STEP_MODE
            self._step_count += 1
            
            # Record step
            step_record = SessionStep(
                step_number=self._step_count,
                event=self._current_event.to_dict() if self._current_event else None,
                state_snapshot=self._get_state_snapshot(),
            )
            self._step_history.append(step_record)
            
            # Trim history if needed
            if len(self._step_history) > self.config.max_history:
                self._step_history = self._step_history[-self.config.max_history:]
            
            self.logger.debug(f"Step {self._step_count} completed")
            
            # Allow one event to proceed
            self._pause_event.set()
            time.sleep(0.01)  # Small delay to let event process
            self._pause_event.clear()
    
    def continue_execution(self) -> None:
        """
        Continue execution until next breakpoint or completion.
        
        Resumes normal execution flow.
        """
        if self._status not in (SessionStatus.PAUSED, SessionStatus.BREAKPOINT_HIT,
                                 SessionStatus.STEP_MODE):
            self.logger.warning(f"Cannot continue in status: {self._status}")
            return
        
        with self._lock:
            self._status = SessionStatus.RUNNING
            self._pause_event.set()
            
            if self._on_resume:
                self._on_resume()
            
            self.logger.info("Execution continued")
    
    def pause(self) -> None:
        """
        Pause execution.
        
        Stops event processing until step() or continue_execution() is called.
        """
        if self._status != SessionStatus.RUNNING:
            self.logger.warning(f"Cannot pause in status: {self._status}")
            return
        
        with self._lock:
            self._status = SessionStatus.PAUSED
            self._pause_event.clear()
            
            if self._on_pause:
                self._on_pause()
            
            self.logger.info("Execution paused")
    
    def inspect(self, path: str) -> Any:
        """
        Inspect a value in session state.
        
        Supports dot notation for nested access:
        - "gates" -> state.gates
        - "gates.GATE-00" -> state.gates["GATE-00"]
        - "gates.GATE-00.status" -> state.gates["GATE-00"]["status"]
        
        Args:
            path: Dot-separated path to value
            
        Returns:
            Value at path, or None if not found
        """
        if not self.state_manager:
            self.logger.warning("No state manager available")
            return None
        
        # Get current session state
        session_state = self.state_manager.get_current_session()
        if not session_state:
            self.logger.warning("No active session")
            return None
        
        # Navigate path
        parts = path.split(".")
        current = session_state
        
        for part in parts:
            if isinstance(current, dict):
                if part in current:
                    current = current[part]
                else:
                    self.logger.debug(f"Path not found: {path} (missing: {part})")
                    return None
            elif hasattr(current, part):
                current = getattr(current, part)
            else:
                self.logger.debug(f"Path not found: {path} (cannot access: {part})")
                return None
        
        self.logger.debug(f"Inspected {path}: {type(current).__name__}")
        return current
    
    def modify(self, path: str, value: Any) -> None:
        """
        Modify a value in session state.
        
        Supports dot notation for nested access.
        Creates intermediate dictionaries as needed.
        
        Args:
            path: Dot-separated path to value
            value: New value to set
        """
        if not self.state_manager:
            self.logger.warning("No state manager available")
            return
        
        # Get current session state
        session_state = self.state_manager.get_current_session()
        if not session_state:
            self.logger.warning("No active session")
            return
        
        # Navigate to parent and set value
        parts = path.split(".")
        current = session_state
        
        # Navigate to parent
        for part in parts[:-1]:
            if isinstance(current, dict):
                if part not in current:
                    current[part] = {}
                current = current[part]
            elif hasattr(current, part):
                current = getattr(current, part)
            else:
                self.logger.warning(f"Cannot modify path: {path}")
                return
        
        # Set final value
        final_key = parts[-1]
        if isinstance(current, dict):
            current[final_key] = value
        else:
            setattr(current, final_key, value)
        
        self.logger.info(f"Modified {path} = {value}")
    
    def add_breakpoint(self, event: str, condition: str = None) -> Breakpoint:
        """
        Add a breakpoint for an event type.
        
        When the specified event is emitted, execution will pause.
        
        Args:
            event: Event type to break on
            condition: Optional condition (not yet implemented)
            
        Returns:
            Created Breakpoint instance
        """
        bp = Breakpoint(event=event, condition=condition)
        self._breakpoints[bp.event] = bp
        self.logger.info(f"Added breakpoint for event: {event}")
        return bp
    
    def remove_breakpoint(self, event: str) -> bool:
        """
        Remove a breakpoint.
        
        Args:
            event: Event type of breakpoint to remove
            
        Returns:
            True if breakpoint was removed
        """
        if event in self._breakpoints:
            del self._breakpoints[event]
            self.logger.info(f"Removed breakpoint for event: {event}")
            return True
        return False
    
    def get_breakpoints(self) -> List[Breakpoint]:
        """
        Get all breakpoints.
        
        Returns:
            List of Breakpoint instances
        """
        return list(self._breakpoints.values())
    
    def enable_breakpoint(self, event: str) -> bool:
        """
        Enable a breakpoint.
        
        Args:
            event: Event type of breakpoint
            
        Returns:
            True if breakpoint was found and enabled
        """
        if event in self._breakpoints:
            self._breakpoints[event].enabled = True
            return True
        return False
    
    def disable_breakpoint(self, event: str) -> bool:
        """
        Disable a breakpoint.
        
        Args:
            event: Event type of breakpoint
            
        Returns:
            True if breakpoint was found and disabled
        """
        if event in self._breakpoints:
            self._breakpoints[event].enabled = False
            return True
        return False
    
    def rollback(self, step: int) -> bool:
        """
        Rollback to a previous step.
        
        Uses checkpoint manager to restore state from a previous step.
        
        Args:
            step: Step number to rollback to
            
        Returns:
            True if rollback was successful
        """
        if not self.checkpoint_manager:
            self.logger.warning("No checkpoint manager available")
            return False
        
        # Find the step in history
        step_record = None
        for s in self._step_history:
            if s.step_number == step:
                step_record = s
                break
        
        if not step_record:
            self.logger.warning(f"Step {step} not found in history")
            return False
        
        if not step_record.state_snapshot:
            self.logger.warning(f"No state snapshot for step {step}")
            return False
        
        # Restore state
        try:
            # If we have a session_id in the snapshot, load from checkpoint
            session_id = step_record.state_snapshot.get("session_id")
            if session_id and self.checkpoint_manager.session_exists(session_id):
                data, result = self.checkpoint_manager.load(session_id)
                if result.success:
                    self.logger.info(f"Rolled back to step {step}")
                    return True
            
            # Otherwise, manually restore state snapshot
            if self.state_manager:
                self.state_manager.current_session = step_record.state_snapshot.copy()
                self._step_count = step
                self.logger.info(f"Rolled back to step {step} (manual)")
                return True
            
        except Exception as e:
            self.logger.error(f"Rollback failed: {e}")
        
        return False
    
    def get_step_history(self, limit: int = 100) -> List[SessionStep]:
        """
        Get step history.
        
        Args:
            limit: Maximum number of steps to return
            
        Returns:
            List of SessionStep records
        """
        return self._step_history[-limit:]
    
    def get_status_info(self) -> Dict[str, Any]:
        """
        Get comprehensive session status information.
        
        Returns:
            Dictionary with status details
        """
        return {
            "status": self._status.value,
            "step_count": self._step_count,
            "is_paused": self.is_paused,
            "breakpoints": [bp.to_dict() for bp in self._breakpoints.values()],
            "history_count": len(self._step_history),
            "config": self.config.to_dict(),
            "current_event": self._current_event.to_dict() if self._current_event else None,
        }
    
    def _on_event(self, event: "Event") -> None:
        """
        Handle incoming events for breakpoint checking.
        
        Called by EventBus for all events. Checks breakpoints
        and pauses if matched.
        
        Args:
            event: Event from EventBus
        """
        self._current_event = event
        
        # Check breakpoints
        if event.event_type in self._breakpoints:
            bp = self._breakpoints[event.event_type]
            if bp.enabled:
                bp.hit_count += 1
                self._handle_breakpoint(bp, event)
        
        # Check auto-pause events
        elif event.event_type in self.config.auto_pause_on:
            self._handle_auto_pause(event)
    
    def _handle_breakpoint(self, breakpoint: Breakpoint, event: "Event") -> None:
        """
        Handle breakpoint hit.
        
        Pauses execution and notifies callback if set.
        
        Args:
            breakpoint: Breakpoint that was hit
            event: Event that triggered breakpoint
        """
        self.logger.info(f"Breakpoint hit: {breakpoint.event}")
        
        with self._lock:
            self._status = SessionStatus.BREAKPOINT_HIT
            self._pause_event.clear()
        
        # Record step
        self._step_count += 1
        step_record = SessionStep(
            step_number=self._step_count,
            event=event.to_dict(),
            state_snapshot=self._get_state_snapshot(),
        )
        self._step_history.append(step_record)
        
        # Notify callback
        if self._on_breakpoint_hit:
            self._on_breakpoint_hit(breakpoint, event)
    
    def _handle_auto_pause(self, event: "Event") -> None:
        """
        Handle auto-pause event.
        
        Args:
            event: Event that triggered auto-pause
        """
        self.logger.info(f"Auto-pause on event: {event.event_type}")
        self.pause()
        
        # Record step
        self._step_count += 1
        step_record = SessionStep(
            step_number=self._step_count,
            event=event.to_dict(),
            state_snapshot=self._get_state_snapshot(),
        )
        self._step_history.append(step_record)
    
    def _get_state_snapshot(self) -> Optional[Dict[str, Any]]:
        """Get current state snapshot."""
        if self.state_manager:
            session = self.state_manager.get_current_session()
            if session:
                # Return a copy to avoid modification
                return session.copy() if isinstance(session, dict) else dict(session)
        return None
    
    def set_callbacks(
        self,
        on_breakpoint_hit: Callable[[Breakpoint, "Event"], None] = None,
        on_pause: Callable[[], None] = None,
        on_resume: Callable[[], None] = None,
    ) -> None:
        """
        Set callback functions for session events.
        
        Args:
            on_breakpoint_hit: Called when breakpoint is hit
            on_pause: Called when execution is paused
            on_resume: Called when execution is resumed
        """
        self._on_breakpoint_hit = on_breakpoint_hit
        self._on_pause = on_pause
        self._on_resume = on_resume
    
    def save_history(self, path: str = None) -> bool:
        """
        Save command history to file.
        
        Args:
            path: Optional path override
            
        Returns:
            True if saved successfully
        """
        path = path or self.config.history_file
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w') as f:
                json.dump({
                    "steps": [s.to_dict() for s in self._step_history],
                    "breakpoints": [bp.to_dict() for bp in self._breakpoints.values()],
                    "saved_at": datetime.utcnow().isoformat() + "Z",
                }, f, indent=2)
            return True
        except Exception as e:
            self.logger.error(f"Failed to save history: {e}")
            return False
    
    def load_history(self, path: str = None) -> bool:
        """
        Load command history from file.
        
        Args:
            path: Optional path override
            
        Returns:
            True if loaded successfully
        """
        path = path or self.config.history_file
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            
            self._step_history = [
                SessionStep(**s) for s in data.get("steps", [])
            ]
            self._breakpoints = {
                bp["event"]: Breakpoint.from_dict(bp)
                for bp in data.get("breakpoints", [])
            }
            return True
        except FileNotFoundError:
            return False
        except Exception as e:
            self.logger.error(f"Failed to load history: {e}")
            return False
    
    def __repr__(self) -> str:
        return (
            f"<InteractiveSession(status={self._status.value}, "
            f"step_count={self._step_count}, breakpoints={len(self._breakpoints)})>"
        )
