"""
Cursor tracking module for TITAN FUSE Protocol.

ITEM-STOR-05: Cursor Hash for Drift Detection

Provides cursor position tracking with SHA-256 hash verification
for detecting external modifications during human wait periods.

Features:
- Cursor hash computation from state
- Patch-based hash updates
- Drift detection on resume
- EventBus integration for CURSOR_DRIFT events

Author: TITAN FUSE Team
Version: 3.3.0
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..events.event_bus import EventBus, EventSeverity


@dataclass
class CursorState:
    """
    Immutable snapshot of cursor state.
    
    Used for checkpoint storage and state comparison.
    """
    cursor_hash: str
    last_patch_hash: Optional[str] = None
    patch_count: int = 0
    current_line: int = 0
    current_chunk: Optional[str] = None
    offset_delta: int = 0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "cursor_hash": self.cursor_hash,
            "last_patch_hash": self.last_patch_hash,
            "patch_count": self.patch_count,
            "current_line": self.current_line,
            "current_chunk": self.current_chunk,
            "offset_delta": self.offset_delta,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'CursorState':
        """Create from dictionary."""
        return cls(
            cursor_hash=data.get("cursor_hash", ""),
            last_patch_hash=data.get("last_patch_hash"),
            patch_count=data.get("patch_count", 0),
            current_line=data.get("current_line", 0),
            current_chunk=data.get("current_chunk"),
            offset_delta=data.get("offset_delta", 0),
            timestamp=data.get("timestamp", datetime.utcnow().isoformat() + "Z")
        )


@dataclass
class DriftResult:
    """
    Result of cursor drift detection.
    """
    valid: bool
    expected_hash: Optional[str] = None
    actual_hash: Optional[str] = None
    gap_tag: Optional[str] = None
    patch_count: int = 0
    drift_details: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        result = {
            "valid": self.valid,
            "expected_hash": self.expected_hash,
            "actual_hash": self.actual_hash,
            "gap_tag": self.gap_tag,
            "gap": self.gap_tag,  # Alias for backward compatibility
            "patch_count": self.patch_count,
            "drift_details": self.drift_details
        }
        return result


class CursorTracker:
    """
    Track cursor position with SHA-256 hash verification.
    
    ITEM-STOR-05 Implementation:
    - compute_hash(): SHA-256 of state dictionary
    - update_cursor(): Update hash after patch application
    - verify_cursor(): Detect external modifications
    
    Usage:
        tracker = CursorTracker()
        
        # Compute hash from state
        state_hash = tracker.compute_hash(session_state)
        
        # Update after patch
        tracker.update_cursor("PATCH_APPLIED", {"file": "test.py", "lines_added": 5})
        
        # Verify on resume
        result = tracker.verify_cursor(expected_hash)
        if not result.valid:
            # Emit CURSOR_DRIFT event
            event_bus.emit_simple("CURSOR_DRIFT", result.to_dict(), EventSeverity.WARN)
    """

    # Gap tag for drift detection
    DRIFT_GAP_TAG = "[gap: cursor_drift_detected]"
    EXTERNAL_MODIFICATION_TAG = "[gap: external_modification_during_wait]"
    
    def __init__(self, event_bus: 'EventBus' = None):
        """
        Initialize cursor tracker.
        
        Args:
            event_bus: Optional EventBus for emitting drift events
        """
        self.cursor_hash: Optional[str] = None
        self.last_patch_hash: Optional[str] = None
        self._patch_history: List[str] = []
        self._current_line: int = 0
        self._current_chunk: Optional[str] = None
        self._offset_delta: int = 0
        self._event_bus = event_bus
        self._operation_history: List[Dict] = []
    
    def compute_hash(self, state: Dict) -> str:
        """
        Compute SHA-256 hash from state dictionary.
        
        This creates a deterministic hash from the state,
        enabling detection of external modifications.
        
        Args:
            state: State dictionary to hash
            
        Returns:
            First 32 characters of SHA-256 hash
        """
        # Create canonical JSON representation
        # Sort keys for determinism
        state_json = json.dumps(state, sort_keys=True, default=str)
        state_bytes = state_json.encode('utf-8')
        
        # Compute SHA-256
        full_hash = hashlib.sha256(state_bytes).hexdigest()
        
        # Store and return truncated hash
        self.cursor_hash = full_hash[:32]
        return self.cursor_hash
    
    def compute_hash_from_fields(self, **fields) -> str:
        """
        Compute hash from specific fields.
        
        Useful for partial state verification.
        
        Args:
            **fields: Key-value pairs to include in hash
            
        Returns:
            First 32 characters of SHA-256 hash
        """
        state_json = json.dumps(fields, sort_keys=True, default=str)
        return hashlib.sha256(state_json.encode('utf-8')).hexdigest()[:32]
    
    def update_cursor(self, operation: str, changes: Dict, 
                      state: Dict = None) -> str:
        """
        Update cursor after patch application.
        
        Records the operation and computes new hash.
        
        Args:
            operation: Operation type (e.g., "PATCH_APPLIED", "FILE_MODIFIED")
            changes: Dictionary of changes made
            state: Optional full state for hash computation
            
        Returns:
            New cursor hash
        """
        # Record operation
        operation_record = {
            "operation": operation,
            "changes": changes,
            "previous_hash": self.cursor_hash,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        # Compute new hash
        if state:
            new_hash = self.compute_hash(state)
        else:
            # Hash from operation + changes
            combined = f"{self.last_patch_hash or 'init'}:{operation}:{json.dumps(changes, sort_keys=True)}"
            new_hash = hashlib.sha256(combined.encode()).hexdigest()[:32]
            self.cursor_hash = new_hash
        
        self.last_patch_hash = self.cursor_hash
        self._patch_history.append(self.cursor_hash)
        
        # Record in history
        operation_record["new_hash"] = self.cursor_hash
        self._operation_history.append(operation_record)
        
        return self.cursor_hash
    
    def update_cursor_hash(self, patch_content: str) -> str:
        """
        Update cursor hash after patch application.
        
        Legacy method for backward compatibility.
        
        Args:
            patch_content: Content of the patch applied
            
        Returns:
            New cursor hash
        """
        combined = f"{self.last_patch_hash or 'init'}:{patch_content}"
        self.cursor_hash = hashlib.sha256(combined.encode()).hexdigest()[:32]
        self.last_patch_hash = self.cursor_hash
        self._patch_history.append(self.cursor_hash)
        return self.cursor_hash
    
    def verify_cursor(self, expected_hash: str, 
                      emit_event: bool = True) -> DriftResult:
        """
        Verify cursor hash on resume.
        
        Detects if state was modified externally during wait period.
        
        Args:
            expected_hash: Expected cursor hash
            emit_event: Whether to emit CURSOR_DRIFT event on mismatch
            
        Returns:
            DriftResult with validation status
        """
        if self.cursor_hash != expected_hash:
            result = DriftResult(
                valid=False,
                expected_hash=expected_hash,
                actual_hash=self.cursor_hash,
                gap_tag=self.DRIFT_GAP_TAG,
                patch_count=len(self._patch_history),
                drift_details={
                    "message": "Cursor hash mismatch detected",
                    "possible_cause": "External modification during wait period",
                    "patches_applied": len(self._patch_history),
                    "last_patch_hash": self.last_patch_hash
                }
            )
            
            # Emit CURSOR_DRIFT event if EventBus available
            if emit_event and self._event_bus:
                from ..events.event_bus import EventSeverity
                self._event_bus.emit_simple(
                    "CURSOR_DRIFT",
                    result.to_dict(),
                    EventSeverity.WARN
                )
            
            return result
        
        return DriftResult(
            valid=True,
            expected_hash=expected_hash,
            actual_hash=self.cursor_hash,
            patch_count=len(self._patch_history)
        )
    
    def verify_cursor_hash(self, expected_hash: str) -> Dict:
        """
        Verify cursor hash on resume.
        
        Legacy method for backward compatibility.
        
        Args:
            expected_hash: Expected cursor hash
            
        Returns:
            Dictionary with validation result
        """
        result = self.verify_cursor(expected_hash, emit_event=True)
        return result.to_dict()
    
    def update_position(self, line: int = None, chunk: str = None, 
                        offset: int = None) -> None:
        """
        Update cursor position.
        
        Args:
            line: Current line number
            chunk: Current chunk identifier
            offset: Offset delta for position adjustment
        """
        if line is not None:
            self._current_line = line
        if chunk is not None:
            self._current_chunk = chunk
        if offset is not None:
            self._offset_delta = offset
    
    def get_state(self) -> Dict:
        """
        Get cursor state for checkpoint.
        
        Returns:
            Dictionary representation of cursor state
        """
        return CursorState(
            cursor_hash=self.cursor_hash or "",
            last_patch_hash=self.last_patch_hash,
            patch_count=len(self._patch_history),
            current_line=self._current_line,
            current_chunk=self._current_chunk,
            offset_delta=self._offset_delta
        ).to_dict()
    
    def restore_state(self, state: Dict) -> None:
        """
        Restore cursor state from checkpoint.
        
        Args:
            state: Dictionary with cursor state
        """
        if isinstance(state, CursorState):
            state = state.to_dict()
        
        self.cursor_hash = state.get("cursor_hash")
        self.last_patch_hash = state.get("last_patch_hash")
        self._current_line = state.get("current_line", 0)
        self._current_chunk = state.get("current_chunk")
        self._offset_delta = state.get("offset_delta", 0)
    
    def set_event_bus(self, event_bus: 'EventBus') -> None:
        """
        Set the EventBus for drift event emission.
        
        Args:
            event_bus: EventBus instance
        """
        self._event_bus = event_bus
    
    def get_patch_history(self) -> List[str]:
        """
        Get history of patch hashes.
        
        Returns:
            List of cursor hashes from patches
        """
        return self._patch_history.copy()
    
    def get_operation_history(self) -> List[Dict]:
        """
        Get history of operations.
        
        Returns:
            List of operation records
        """
        return self._operation_history.copy()
    
    def reset(self) -> None:
        """
        Reset cursor tracker to initial state.
        """
        self.cursor_hash = None
        self.last_patch_hash = None
        self._patch_history.clear()
        self._current_line = 0
        self._current_chunk = None
        self._offset_delta = 0
        self._operation_history.clear()
    
    def validate_cursor_on_resume(self, checkpoint_hash: str, 
                                   current_state: Dict) -> DriftResult:
        """
        Validate cursor on session resume.
        
        Compares checkpoint hash with computed hash from current state.
        
        Args:
            checkpoint_hash: Hash stored in checkpoint
            current_state: Current session state
            
        Returns:
            DriftResult with validation status
        """
        # Compute hash from current state
        current_hash = self.compute_hash(current_state)
        
        # Compare with checkpoint hash
        if current_hash != checkpoint_hash:
            result = DriftResult(
                valid=False,
                expected_hash=checkpoint_hash,
                actual_hash=current_hash,
                gap_tag=self.EXTERNAL_MODIFICATION_TAG,
                drift_details={
                    "message": "State was modified externally",
                    "checkpoint_hash": checkpoint_hash,
                    "computed_hash": current_hash
                }
            )
            
            # Emit event
            if self._event_bus:
                from ..events.event_bus import EventSeverity
                self._event_bus.emit_simple(
                    "CURSOR_DRIFT",
                    result.to_dict(),
                    EventSeverity.WARN
                )
            
            return result
        
        return DriftResult(
            valid=True,
            expected_hash=checkpoint_hash,
            actual_hash=current_hash
        )


# Convenience functions

def compute_state_hash(state: Dict) -> str:
    """
    Compute SHA-256 hash from state dictionary.
    
    Convenience function for one-off hash computation.
    
    Args:
        state: State dictionary
        
    Returns:
        First 32 characters of SHA-256 hash
    """
    state_json = json.dumps(state, sort_keys=True, default=str)
    return hashlib.sha256(state_json.encode('utf-8')).hexdigest()[:32]


def verify_state_integrity(state: Dict, expected_hash: str) -> DriftResult:
    """
    Verify state integrity against expected hash.
    
    Convenience function for one-off verification.
    
    Args:
        state: State dictionary
        expected_hash: Expected hash value
        
    Returns:
        DriftResult with validation status
    """
    actual_hash = compute_state_hash(state)
    
    return DriftResult(
        valid=actual_hash == expected_hash,
        expected_hash=expected_hash,
        actual_hash=actual_hash,
        gap_tag=CursorTracker.DRIFT_GAP_TAG if actual_hash != expected_hash else None
    )
