"""
Recovery Manager for TITAN FUSE Protocol.

ITEM-ARCH-02: EventBus WAL for Crash Recovery

Provides crash recovery functionality by replaying events
from the event journal and rebuilding session state.

Features:
- Recovery from event journal after crash
- Checkpoint consistency validation
- State rebuild from event stream
- Cursor drift detection

Author: TITAN FUSE Team
Version: 3.3.0
"""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

from .event_journal import EventJournal, JournalEntry


class RecoveryStatus(Enum):
    """Status of recovery operation."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    NO_RECOVERY_NEEDED = "no_recovery_needed"


@dataclass
class RecoveryResult:
    """Result of a recovery operation."""
    status: RecoveryStatus
    message: str
    recovered_cursor: int = 0
    events_replayed: int = 0
    checkpoint_valid: bool = True
    gaps: List[str] = None
    state: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.gaps is None:
            self.gaps = []
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "message": self.message,
            "recovered_cursor": self.recovered_cursor,
            "events_replayed": self.events_replayed,
            "checkpoint_valid": self.checkpoint_valid,
            "gaps": self.gaps,
            "state": self.state
        }


class RecoveryManager:
    """
    Manager for crash recovery operations.
    
    ITEM-ARCH-02 Implementation:
    - recover_from_journal(journal_path: Path) -> SessionState
    - validate_checkpoint_consistency(checkpoint: dict, journal: EventJournal) -> bool
    - rebuild_state_from_events(events: list[Event]) -> SessionState
    
    Recovery Logic (from ITEM-ARCH-02 step 05):
    On session start:
        1. Check for existing journal
        2. If journal exists, replay events
        3. Compare final state with checkpoint
        4. If mismatch, emit GAP_TAG and offer recovery
    
    Usage:
        manager = RecoveryManager()
        
        # Attempt recovery
        result = manager.recover_from_journal(
            journal_path=Path(".titan/event_journal.jsonl"),
            checkpoint_path=Path("checkpoints/checkpoint.json")
        )
        
        if result.status == RecoveryStatus.SUCCESS:
            session = result.state
    """
    
    # Events that modify state and should be replayed
    STATE_MODIFYING_EVENTS = {
        "GATE_PASS", "GATE_FAIL", "GATE_WARN",
        "CURSOR_UPDATED", "CHUNK_COMPLETE", "ISSUE_FOUND", "ISSUE_FIXED",
        "BUDGET_WARNING", "BUDGET_EXCEEDED",
        "SESSION_START", "SESSION_END", "SESSION_ABORT",
        "PHASE_START", "PHASE_COMPLETE",
        "CHECKPOINT_SAVE"
    }
    
    def __init__(self, config: Dict = None):
        """
        Initialize recovery manager.
        
        Args:
            config: Configuration dict
        """
        self.config = config or {}
        self._logger = logging.getLogger(__name__)
    
    def recover_from_journal(
        self,
        journal_path: Path,
        checkpoint_path: Path = None,
        from_cursor: int = 0
    ) -> RecoveryResult:
        """
        Recover session state from event journal.
        
        Args:
            journal_path: Path to event journal file
            checkpoint_path: Optional path to checkpoint file for validation
            from_cursor: Starting cursor position for replay
            
        Returns:
            RecoveryResult with recovered state
        """
        journal_path = Path(journal_path)
        
        # Check if journal exists
        if not journal_path.exists():
            return RecoveryResult(
                status=RecoveryStatus.NO_RECOVERY_NEEDED,
                message="No journal file found - clean start"
            )
        
        try:
            # Load journal
            journal = EventJournal(journal_path)
            
            # Get checkpoint if available
            checkpoint = None
            if checkpoint_path and checkpoint_path.exists():
                checkpoint = self._load_checkpoint(checkpoint_path)
            
            # Determine starting cursor
            start_cursor = from_cursor
            if checkpoint:
                checkpoint_cursor = checkpoint.get("cursor", 0)
                start_cursor = max(start_cursor, checkpoint_cursor)
            
            # Replay events from journal
            events = journal.replay(from_cursor=start_cursor)
            
            if not events:
                return RecoveryResult(
                    status=RecoveryStatus.NO_RECOVERY_NEEDED,
                    message="No events to replay"
                )
            
            # Rebuild state from events
            state = self.rebuild_state_from_events(events, checkpoint)
            
            # Validate against checkpoint if available
            checkpoint_valid = True
            gaps = []
            
            if checkpoint:
                checkpoint_valid, gaps = self.validate_checkpoint_consistency(
                    checkpoint, journal, state
                )
            
            # Determine recovery status
            if checkpoint_valid:
                status = RecoveryStatus.SUCCESS
                message = f"Successfully recovered {len(events)} events"
            else:
                status = RecoveryStatus.PARTIAL
                message = f"Recovered with {len(gaps)} inconsistencies"
            
            return RecoveryResult(
                status=status,
                message=message,
                recovered_cursor=journal.get_cursor(),
                events_replayed=len(events),
                checkpoint_valid=checkpoint_valid,
                gaps=gaps,
                state=state
            )
            
        except Exception as e:
            self._logger.error(f"Recovery failed: {e}")
            return RecoveryResult(
                status=RecoveryStatus.FAILED,
                message=f"Recovery failed: {str(e)}",
                gaps=[f"[gap: recovery_failed: {str(e)}]"]
            )
    
    def validate_checkpoint_consistency(
        self,
        checkpoint: Dict[str, Any],
        journal: EventJournal,
        rebuilt_state: Dict[str, Any] = None
    ) -> Tuple[bool, List[str]]:
        """
        Validate checkpoint consistency with event journal.
        
        Args:
            checkpoint: Checkpoint dictionary
            journal: EventJournal instance
            rebuilt_state: Optional pre-rebuilt state
            
        Returns:
            Tuple of (is_valid, list of gaps)
        """
        gaps = []
        is_valid = True
        
        # Compare cursor positions
        checkpoint_cursor = checkpoint.get("cursor", checkpoint.get("chunk_cursor"))
        journal_cursor = journal.get_cursor()
        
        # Get checkpoint timestamp
        checkpoint_time = checkpoint.get("saved_at") or checkpoint.get("updated_at")
        
        # Rebuild state if not provided
        if rebuilt_state is None:
            events = journal.replay()
            rebuilt_state = self.rebuild_state_from_events(events)
        
        # Compare state hashes if available
        checkpoint_hash = checkpoint.get("state_hash") or checkpoint.get("cursor_hash")
        if checkpoint_hash:
            # Get last state hash from journal
            last_entry = journal.get_last_entry()
            if last_entry and last_entry.get("state_hash"):
                if last_entry["state_hash"] != checkpoint_hash:
                    gaps.append("[gap: state_hash_mismatch]")
                    is_valid = False
        
        # Compare gate states
        checkpoint_gates = checkpoint.get("gates", {})
        rebuilt_gates = rebuilt_state.get("gates", {})
        
        for gate_id, gate_state in checkpoint_gates.items():
            rebuilt_gate = rebuilt_gates.get(gate_id, {})
            if gate_state.get("status") != rebuilt_gate.get("status"):
                gaps.append(f"[gap: gate_{gate_id}_mismatch]")
                is_valid = False
        
        # Compare token usage
        checkpoint_tokens = checkpoint.get("tokens_used", 0)
        rebuilt_tokens = rebuilt_state.get("tokens_used", 0)
        
        if checkpoint_tokens != rebuilt_tokens:
            gaps.append(f"[gap: token_count_mismatch: checkpoint={checkpoint_tokens}, journal={rebuilt_tokens}]")
            # This is a warning, not a hard failure
            self._logger.warning(
                f"Token count mismatch: checkpoint={checkpoint_tokens}, journal={rebuilt_tokens}"
            )
        
        return is_valid, gaps
    
    def rebuild_state_from_events(
        self,
        events: List[Dict[str, Any]],
        initial_state: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Rebuild session state from event stream.
        
        This method replays state-modifying events to reconstruct
        the session state at any point in time.
        
        Args:
            events: List of event dicts from journal
            initial_state: Optional initial state to build upon
            
        Returns:
            Reconstructed session state dictionary
        """
        # Start with initial state or default
        state = initial_state.copy() if initial_state else self._get_default_state()
        
        for event in events:
            event_type = event.get("event_type")
            event_data = event.get("data", {})
            
            # Only process state-modifying events
            if event_type not in self.STATE_MODIFYING_EVENTS:
                continue
            
            # Apply event to state
            self._apply_event(state, event_type, event_data, event)
        
        return state
    
    def _get_default_state(self) -> Dict[str, Any]:
        """Get default session state."""
        return {
            "session_id": None,
            "protocol_version": "3.3.0",
            "state": "INIT",
            "source_file": None,
            "current_phase": 0,
            "chunk_cursor": None,
            "chunks_total": 0,
            "chunks_completed": 0,
            "gates": {
                "GATE-00": {"status": "PENDING"},
                "GATE-01": {"status": "PENDING"},
                "GATE-02": {"status": "PENDING"},
                "GATE-03": {"status": "PENDING"},
                "GATE-04": {"status": "PENDING"},
                "GATE-05": {"status": "PENDING"}
            },
            "tokens_used": 0,
            "issues": [],
            "issues_by_severity": {
                "SEV-1": [], "SEV-2": [], "SEV-3": [], "SEV-4": []
            },
            "gaps": [],
            "updated_at": datetime.utcnow().isoformat() + "Z"
        }
    
    def _apply_event(
        self,
        state: Dict[str, Any],
        event_type: str,
        event_data: Dict[str, Any],
        full_event: Dict[str, Any]
    ) -> None:
        """
        Apply an event to state (mutates state in place).
        
        Args:
            state: State dict to modify
            event_type: Type of event
            event_data: Event payload
            full_event: Full event dict with metadata
        """
        if event_type == "GATE_PASS":
            gate_id = event_data.get("gate_id", "GATE-00")
            if "gates" in state and gate_id in state["gates"]:
                state["gates"][gate_id] = {
                    "status": "PASS",
                    "timestamp": full_event.get("timestamp"),
                    "details": event_data
                }
        
        elif event_type == "GATE_FAIL":
            gate_id = event_data.get("gate_id", "GATE-00")
            if "gates" in state and gate_id in state["gates"]:
                state["gates"][gate_id] = {
                    "status": "FAIL",
                    "timestamp": full_event.get("timestamp"),
                    "reason": event_data.get("reason", "Unknown"),
                    "details": event_data
                }
        
        elif event_type == "GATE_WARN":
            gate_id = event_data.get("gate_id", "GATE-00")
            if "gates" in state and gate_id in state["gates"]:
                state["gates"][gate_id] = {
                    "status": "WARN",
                    "timestamp": full_event.get("timestamp"),
                    "reason": event_data.get("reason", ""),
                    "details": event_data
                }
        
        elif event_type == "CURSOR_UPDATED":
            state["chunk_cursor"] = event_data.get("cursor")
            state["cursor_hash"] = event_data.get("cursor_hash")
        
        elif event_type == "CHUNK_COMPLETE":
            state["chunks_completed"] = state.get("chunks_completed", 0) + 1
        
        elif event_type == "ISSUE_FOUND":
            issue = event_data
            state.setdefault("issues", []).append(issue)
            
            severity = issue.get("severity", "SEV-4")
            state.setdefault("issues_by_severity", {}).setdefault(severity, []).append(
                issue.get("id", str(len(state["issues"])))
            )
        
        elif event_type == "ISSUE_FIXED":
            issue_id = event_data.get("issue_id")
            if issue_id and "issues" in state:
                state["issues"] = [
                    i for i in state["issues"] 
                    if i.get("id") != issue_id
                ]
        
        elif event_type == "BUDGET_WARNING":
            state["budget_warning"] = True
            state["tokens_used"] = event_data.get("tokens_used", state.get("tokens_used", 0))
        
        elif event_type == "BUDGET_EXCEEDED":
            state["budget_exceeded"] = True
            state["tokens_used"] = event_data.get("tokens_used", state.get("tokens_used", 0))
        
        elif event_type == "SESSION_START":
            state["session_id"] = event_data.get("session_id")
            state["state"] = "RUNNING"
            state["source_file"] = event_data.get("source_file")
        
        elif event_type == "SESSION_END":
            state["state"] = "COMPLETED"
        
        elif event_type == "SESSION_ABORT":
            state["state"] = "ABORTED"
            state["abort_reason"] = event_data.get("reason")
        
        elif event_type == "PHASE_START":
            state["current_phase"] = event_data.get("phase", state.get("current_phase", 0))
        
        elif event_type == "PHASE_COMPLETE":
            state["current_phase"] = event_data.get("phase", state.get("current_phase", 0))
        
        elif event_type == "CHECKPOINT_SAVE":
            state["last_checkpoint"] = full_event.get("timestamp")
            state["cursor"] = full_event.get("cursor")
        
        # Update timestamp
        state["updated_at"] = full_event.get("timestamp", datetime.utcnow().isoformat() + "Z")
    
    def _load_checkpoint(self, checkpoint_path: Path) -> Optional[Dict[str, Any]]:
        """Load checkpoint from file."""
        try:
            with open(checkpoint_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            self._logger.error(f"Failed to load checkpoint: {e}")
            return None
    
    def get_recovery_info(self, journal_path: Path) -> Dict[str, Any]:
        """
        Get information about potential recovery.
        
        Args:
            journal_path: Path to journal file
            
        Returns:
            Dict with recovery information
        """
        journal_path = Path(journal_path)
        
        if not journal_path.exists():
            return {
                "can_recover": False,
                "reason": "No journal file found"
            }
        
        try:
            journal = EventJournal(journal_path)
            events = journal.replay()
            
            # Get last few events
            recent_events = events[-10:] if len(events) > 10 else events
            
            # Check for incomplete session
            last_event = events[-1] if events else None
            session_complete = False
            
            if last_event:
                session_complete = last_event.get("event_type") in {
                    "SESSION_END", "SESSION_ABORT"
                }
            
            return {
                "can_recover": not session_complete,
                "journal_size": journal.get_size_bytes(),
                "total_events": len(events),
                "cursor": journal.get_cursor(),
                "recent_events": [e.get("event_type") for e in recent_events],
                "last_event_type": last_event.get("event_type") if last_event else None,
                "last_event_time": last_event.get("timestamp") if last_event else None
            }
        except Exception as e:
            return {
                "can_recover": False,
                "reason": str(e)
            }
    
    def attempt_recovery(
        self,
        journal_path: Path,
        checkpoint_path: Path = None,
        force: bool = False
    ) -> RecoveryResult:
        """
        Attempt recovery with optional force flag.
        
        Args:
            journal_path: Path to journal file
            checkpoint_path: Optional checkpoint path
            force: If True, recover even if session appears complete
            
        Returns:
            RecoveryResult
        """
        # Get recovery info first
        info = self.get_recovery_info(journal_path)
        
        if not info.get("can_recover") and not force:
            return RecoveryResult(
                status=RecoveryStatus.NO_RECOVERY_NEEDED,
                message="Session appears complete. Use force=True to recover anyway."
            )
        
        return self.recover_from_journal(journal_path, checkpoint_path)


def get_recovery_manager(config: Dict = None) -> RecoveryManager:
    """Factory function to get recovery manager."""
    return RecoveryManager(config)
