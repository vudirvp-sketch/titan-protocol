"""
Approval Loop for TITAN FUSE Protocol.

ITEM-ARCH-07: Release-on-Wait Pattern for Deadlock Prevention

Implements a pattern where locks are released during human approval
waits to prevent deadlocks, with cursor validation on resume.

Features:
- Review checkpoint emission before wait
- Lock release during wait period
- Cursor drift detection on resume
- Lock re-acquisition with validation
- Force resume option for emergencies

Author: TITAN FUSE Team
Version: 3.3.0
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
import logging
import threading


class ApprovalStatus(Enum):
    """Status of approval request."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    CURSOR_DRIFT = "cursor_drift"
    ERROR = "error"


@dataclass
class ApprovalRequest:
    """Represents an approval request."""
    request_id: str
    description: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    state_snapshot: Dict[str, Any] = field(default_factory=dict)
    cursor_hash: str = ""
    status: ApprovalStatus = ApprovalStatus.PENDING
    response: Optional[str] = None
    responder: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "description": self.description,
            "created_at": self.created_at,
            "state_snapshot": self.state_snapshot,
            "cursor_hash": self.cursor_hash,
            "status": self.status.value,
            "response": self.response,
            "responder": self.responder
        }


class CursorDriftError(Exception):
    """Raised when cursor drift is detected during approval wait."""
    
    def __init__(self, expected_hash: str, actual_hash: str, message: str = None):
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        self.message = message or (
            f"[gap: external_modification_during_wait] "
            f"Cursor hash mismatch: expected {expected_hash[:16]}..., "
            f"got {actual_hash[:16]}..."
        )
        super().__init__(self.message)


class ApprovalLoop:
    """
    Approval loop with lock release pattern.
    
    ITEM-ARCH-07 Implementation:
    
    Pattern:
    1. Emit REVIEW_CHECKPOINT event with state snapshot
    2. Release all held locks
    3. Wait for human input/response
    4. Validate cursor_hash (detect drift from external modifications)
    5. Re-acquire locks with cursor validation
    6. Return response or raise CursorDriftError
    
    This pattern prevents deadlocks when waiting for human approval
    while detecting if external modifications occurred during the wait.
    
    Usage:
        loop = ApprovalLoop(
            lock_backend=lock_backend,
            event_bus=event_bus,
            agent_id="agent-001"
        )
        
        # Register held locks
        loop.register_lock("resource_a", lock_a)
        loop.register_lock("resource_b", lock_b)
        
        # Wait for approval
        try:
            response = await loop.wait_for_approval(
                description="Please review changes",
                state_snapshot=current_state,
                timeout_seconds=300
            )
            print(f"Got response: {response}")
        except CursorDriftError as e:
            print(f"External modification detected: {e}")
    """
    
    def __init__(
        self,
        lock_backend: Any = None,
        event_bus: Any = None,
        agent_id: str = None,
        config: Dict[str, Any] = None
    ):
        """
        Initialize approval loop.
        
        Args:
            lock_backend: Lock backend for releasing/acquiring locks
            event_bus: Event bus for emitting events
            agent_id: Identifier for this agent
            config: Configuration dictionary
        """
        self.lock_backend = lock_backend
        self.event_bus = event_bus
        self.agent_id = agent_id or f"agent-{threading.current_thread().ident}"
        self.config = config or {}
        
        self._held_locks: Dict[str, Any] = {}  # resource -> Lock
        self._required_resources: List[str] = []
        self._lock_ttl = self.config.get("approval", {}).get("lock_ttl_seconds", 300)
        
        self._logger = logging.getLogger(__name__)
        self._last_cursor_hash = ""
        self._approval_callback: Optional[Callable] = None
    
    def register_lock(self, resource: str, lock: Any) -> None:
        """
        Register a held lock for release during wait.
        
        Args:
            resource: Resource identifier
            lock: Lock object
        """
        self._held_locks[resource] = lock
        self._required_resources.append(resource)
        self._logger.debug(f"Registered lock for resource: {resource}")
    
    def unregister_lock(self, resource: str) -> None:
        """Unregister a lock."""
        if resource in self._held_locks:
            del self._held_locks[resource]
        if resource in self._required_resources:
            self._required_resources.remove(resource)
    
    def compute_cursor_hash(self, state: Dict[str, Any]) -> str:
        """
        Compute cursor hash from state.
        
        This hash is used to detect external modifications
        during the approval wait period.
        
        Args:
            state: Current state dictionary
            
        Returns:
            SHA-256 hash of state
        """
        # Create deterministic hash of state
        state_str = json.dumps(state, sort_keys=True, default=str)
        return hashlib.sha256(state_str.encode()).hexdigest()
    
    def emit_review_checkpoint(self, state_snapshot: Dict[str, Any]) -> str:
        """
        Emit REVIEW_CHECKPOINT event with state snapshot.
        
        Args:
            state_snapshot: Current state to checkpoint
            
        Returns:
            Cursor hash for validation
        """
        cursor_hash = self.compute_cursor_hash(state_snapshot)
        self._last_cursor_hash = cursor_hash
        
        if self.event_bus:
            # Import Event class if available
            try:
                from ..events.event_bus import Event, EventSeverity
                event = Event(
                    event_type="REVIEW_CHECKPOINT",
                    data={
                        "agent_id": self.agent_id,
                        "state_snapshot": state_snapshot,
                        "cursor_hash": cursor_hash,
                        "held_resources": list(self._held_locks.keys())
                    },
                    severity=EventSeverity.WARN,
                    source=self.agent_id
                )
                self.event_bus.emit(event)
            except ImportError:
                # Fallback to simple emit
                self.event_bus.emit_simple(
                    "REVIEW_CHECKPOINT",
                    {
                        "agent_id": self.agent_id,
                        "cursor_hash": cursor_hash
                    }
                )
        
        self._logger.info(
            f"Emitted REVIEW_CHECKPOINT (cursor_hash={cursor_hash[:16]}...)"
        )
        
        return cursor_hash
    
    def release_all_locks(self) -> int:
        """
        Release all held locks.
        
        Returns:
            Number of locks released
        """
        released_count = 0
        
        for resource, lock in self._held_locks.items():
            try:
                if self.lock_backend:
                    self.lock_backend.release(lock)
                released_count += 1
                self._logger.debug(f"Released lock on: {resource}")
            except Exception as e:
                self._logger.warning(f"Failed to release lock on {resource}: {e}")
        
        # Clear held locks but keep required_resources for re-acquisition
        self._held_locks.clear()
        
        self._logger.info(f"Released {released_count} locks for approval wait")
        return released_count
    
    def reacquire_locks(self, timeout_seconds: int = 30) -> int:
        """
        Re-acquire all required locks after approval.
        
        Args:
            timeout_seconds: Timeout for acquiring each lock
            
        Returns:
            Number of locks re-acquired
        """
        acquired_count = 0
        
        for resource in self._required_resources:
            try:
                if self.lock_backend:
                    lock = self.lock_backend.try_acquire(
                        resource=resource,
                        ttl_seconds=self._lock_ttl,
                        owner=self.agent_id,
                        max_retries=3,
                        retry_delay_ms=100
                    )
                    if lock:
                        self._held_locks[resource] = lock
                        acquired_count += 1
                        self._logger.debug(f"Re-acquired lock on: {resource}")
                    else:
                        self._logger.error(f"Failed to re-acquire lock on: {resource}")
            except Exception as e:
                self._logger.error(f"Error re-acquiring lock on {resource}: {e}")
        
        self._logger.info(
            f"Re-acquired {acquired_count}/{len(self._required_resources)} locks"
        )
        return acquired_count
    
    def validate_cursor(self, current_state: Dict[str, Any]) -> bool:
        """
        Validate cursor hash to detect drift.
        
        Args:
            current_state: Current state to validate
            
        Returns:
            True if cursor matches, False if drift detected
        """
        current_hash = self.compute_cursor_hash(current_state)
        
        if current_hash != self._last_cursor_hash:
            # Emit CURSOR_DRIFT event
            if self.event_bus:
                try:
                    from ..events.event_bus import Event, EventSeverity
                    event = Event(
                        event_type="CURSOR_DRIFT",
                        data={
                            "expected_hash": self._last_cursor_hash,
                            "actual_hash": current_hash,
                            "agent_id": self.agent_id
                        },
                        severity=EventSeverity.WARN,
                        source=self.agent_id
                    )
                    self.event_bus.emit(event)
                except ImportError:
                    self.event_bus.emit_simple(
                        "CURSOR_DRIFT",
                        {
                            "expected_hash": self._last_cursor_hash,
                            "actual_hash": current_hash
                        }
                    )
            
            self._logger.warning(
                f"[gap: external_modification_during_wait] "
                f"Cursor drift detected: expected {self._last_cursor_hash[:16]}..., "
                f"got {current_hash[:16]}..."
            )
            return False
        
        return True
    
    async def wait_for_approval(
        self,
        description: str,
        state_snapshot: Dict[str, Any],
        timeout_seconds: int = 300,
        force_resume: bool = False,
        get_input: Callable[[], Any] = None
    ) -> Any:
        """
        Wait for human approval with lock release pattern.
        
        Args:
            description: Description of what needs approval
            state_snapshot: Current state snapshot
            timeout_seconds: Maximum wait time
            force_resume: If True, skip cursor validation (security risk)
            get_input: Optional async function to get input
            
        Returns:
            Approval response
            
        Raises:
            CursorDriftError: If cursor drift detected and force_resume=False
            TimeoutError: If timeout exceeded
        """
        # Step 1: Emit REVIEW_CHECKPOINT
        cursor_hash = self.emit_review_checkpoint(state_snapshot)
        
        # Step 2: Release all locks
        self.release_all_locks()
        
        # Create approval request
        request = ApprovalRequest(
            request_id=f"approval-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            description=description,
            state_snapshot=state_snapshot,
            cursor_hash=cursor_hash
        )
        
        self._logger.info(
            f"Waiting for approval (request_id={request.request_id}, "
            f"timeout={timeout_seconds}s)"
        )
        
        try:
            # Step 3: Wait for human input
            if get_input:
                # Use provided input function
                response = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, get_input),
                    timeout=timeout_seconds
                )
            elif self._approval_callback:
                # Use registered callback
                response = await asyncio.wait_for(
                    self._approval_callback(request),
                    timeout=timeout_seconds
                )
            else:
                # Simulated wait (in real implementation, would be interactive)
                self._logger.info("Waiting for approval input...")
                await asyncio.sleep(min(5, timeout_seconds))
                response = "APPROVED"  # Simulated response
            
            request.status = ApprovalStatus.APPROVED
            request.response = str(response)
            
        except asyncio.TimeoutError:
            request.status = ApprovalStatus.TIMEOUT
            self._logger.warning(f"Approval request timed out after {timeout_seconds}s")
            raise TimeoutError(f"Approval request timed out after {timeout_seconds}s")
        
        except Exception as e:
            request.status = ApprovalStatus.ERROR
            self._logger.error(f"Error during approval wait: {e}")
            raise
        
        finally:
            # Step 4 & 5: Validate cursor and re-acquire locks
            if not force_resume:
                # Validate cursor hash
                current_hash = self.compute_cursor_hash(state_snapshot)
                if current_hash != cursor_hash:
                    # Cursor drift detected
                    request.status = ApprovalStatus.CURSOR_DRIFT
                    
                    # Still try to re-acquire locks
                    self.reacquire_locks()
                    
                    raise CursorDriftError(
                        expected_hash=cursor_hash,
                        actual_hash=current_hash
                    )
            
            # Re-acquire locks
            self.reacquire_locks()
        
        self._logger.info(f"Approval received: {response}")
        return response
    
    def set_approval_callback(self, callback: Callable) -> None:
        """
        Set callback for approval input.
        
        Args:
            callback: Async callable that takes ApprovalRequest and returns response
        """
        self._approval_callback = callback
    
    def get_held_locks(self) -> Dict[str, Any]:
        """Get currently held locks."""
        return self._held_locks.copy()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get approval loop statistics."""
        return {
            "agent_id": self.agent_id,
            "held_locks": len(self._held_locks),
            "required_resources": len(self._required_resources),
            "lock_ttl": self._lock_ttl,
            "last_cursor_hash": self._last_cursor_hash[:16] + "..." if self._last_cursor_hash else None
        }


def create_approval_loop(
    lock_backend: Any = None,
    event_bus: Any = None,
    config: Dict[str, Any] = None
) -> ApprovalLoop:
    """
    Factory function to create approval loop.
    
    Args:
        lock_backend: Lock backend instance
        event_bus: Event bus instance
        config: Configuration dictionary
        
    Returns:
        Configured ApprovalLoop instance
    """
    return ApprovalLoop(
        lock_backend=lock_backend,
        event_bus=event_bus,
        config=config
    )
