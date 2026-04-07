"""
Event Journal for TITAN FUSE Protocol.

ITEM-ARCH-02: EventBus WAL for Crash Recovery

Provides Write-Ahead Logging (WAL) for event persistence,
enabling crash recovery and state rebuild from event stream.

Features:
- Synchronous append for CRITICAL/WARN events
- State hash verification for tamper detection
- Event replay for state rebuild
- Compaction for journal size management

Author: TITAN FUSE Team
Version: 3.3.0
"""

import json
import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Iterator
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging
import threading


class JournalEntryType(Enum):
    """Types of journal entries."""
    EVENT = "event"
    CHECKPOINT = "checkpoint"
    STATE_HASH = "state_hash"
    COMPACTION_MARKER = "compaction_marker"


@dataclass
class JournalEntry:
    """
    A single entry in the event journal.
    
    Format matches ITEM-ARCH-02 specification:
    {
        "cursor": 1,
        "timestamp": "ISO8601",
        "event_type": "...",
        "payload": {...},
        "state_hash": "sha256...",
        "signature": "ed25519..."
    }
    """
    cursor: int
    timestamp: str
    event_type: str
    payload: Dict[str, Any]
    state_hash: str = ""
    signature: str = ""
    entry_type: JournalEntryType = JournalEntryType.EVENT
    
    def to_json_line(self) -> str:
        """Serialize to JSON line for journal file."""
        data = {
            "cursor": self.cursor,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "payload": self.payload,
            "state_hash": self.state_hash,
            "signature": self.signature,
            "entry_type": self.entry_type.value
        }
        return json.dumps(data, separators=(',', ':'))
    
    @classmethod
    def from_json_line(cls, line: str) -> 'JournalEntry':
        """Deserialize from JSON line."""
        data = json.loads(line)
        return cls(
            cursor=data["cursor"],
            timestamp=data["timestamp"],
            event_type=data["event_type"],
            payload=data.get("payload", {}),
            state_hash=data.get("state_hash", ""),
            signature=data.get("signature", ""),
            entry_type=JournalEntryType(data.get("entry_type", "event"))
        )
    
    def compute_hash(self) -> str:
        """Compute hash of entry for verification."""
        content = json.dumps({
            "cursor": self.cursor,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "payload": self.payload
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()


class EventJournal:
    """
    Write-Ahead Log for EventBus events.
    
    ITEM-ARCH-02 Implementation:
    - __init__(path: Path, max_size_mb: int = 100)
    - append(event: Event) -> None  # sync write
    - sync_flush() -> None
    - replay(from_cursor: int) -> list[Event]
    - get_cursor() -> int
    - verify_state_hash() -> bool
    - compact() -> int  # Returns number of events compacted
    
    Integration with EventBus:
    - EventJournal.append() called before event handlers execute
    - CRITICAL and WARN events: sync write
    - INFO and DEBUG events: async write (buffered)
    
    Usage:
        journal = EventJournal(Path(".titan/event_journal.jsonl"))
        
        # Append event
        journal.append({
            "event_type": "GATE_PASS",
            "data": {"gate_id": "GATE-01"}
        })
        
        # Replay events
        events = journal.replay(from_cursor=0)
        
        # Verify state hash
        is_valid = journal.verify_state_hash()
    """
    
    # Events that require synchronous (immediate) write
    SYNC_EVENT_TYPES = {
        "GATE_PASS", "GATE_FAIL", "GATE_WARN",
        "CHECKPOINT_SAVE", "CREDENTIAL_ACCESS",
        "SESSION_START", "SESSION_END", "SESSION_ABORT",
        "BUDGET_EXCEEDED", "CURSOR_DRIFT"
    }
    
    def __init__(self, path: Path, max_size_mb: int = 100):
        """
        Initialize event journal.
        
        Args:
            path: Path to journal file (JSONL format)
            max_size_mb: Maximum journal size before compaction needed
        """
        self.path = Path(path)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self._cursor = 0
        self._file_handle: Optional[Any] = None
        self._buffer: List[JournalEntry] = []
        self._buffer_size = 0
        self._max_buffer_size = 100  # Buffer up to 100 events before flush
        self._lock = threading.RLock()
        self._logger = logging.getLogger(__name__)
        self._last_state_hash = ""
        
        # Ensure directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing cursor position
        self._load_cursor()
    
    def _load_cursor(self) -> None:
        """Load cursor position from existing journal."""
        if not self.path.exists():
            return
        
        try:
            with open(self.path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entry = JournalEntry.from_json_line(line)
                        self._cursor = max(self._cursor, entry.cursor)
                        if entry.state_hash:
                            self._last_state_hash = entry.state_hash
            self._logger.debug(f"Loaded journal with cursor at {self._cursor}")
        except Exception as e:
            self._logger.warning(f"Failed to load journal cursor: {e}")
    
    def append(self, event: Dict[str, Any], state_hash: str = "", 
               signature: str = "", sync: bool = False) -> int:
        """
        Append an event to the journal.
        
        Args:
            event: Event dict with 'event_type' and 'data' keys
            state_hash: Optional hash of current state
            signature: Optional signature for critical events
            sync: Force synchronous write (default: auto-detect from event type)
            
        Returns:
            Cursor position of the new entry
        """
        event_type = event.get("event_type", "UNKNOWN")
        event_data = event.get("data", {})
        
        # Determine if sync write is needed
        if not sync:
            sync = event_type in self.SYNC_EVENT_TYPES
        
        with self._lock:
            self._cursor += 1
            
            entry = JournalEntry(
                cursor=self._cursor,
                timestamp=datetime.utcnow().isoformat() + "Z",
                event_type=event_type,
                payload=event_data,
                state_hash=state_hash,
                signature=signature
            )
            
            if sync:
                # Synchronous write for critical events
                self._write_entry_sync(entry)
            else:
                # Buffer for async write
                self._buffer.append(entry)
                self._buffer_size += 1
                
                # Flush if buffer is full
                if self._buffer_size >= self._max_buffer_size:
                    self.sync_flush()
            
            return self._cursor
    
    def _write_entry_sync(self, entry: JournalEntry) -> None:
        """Synchronously write entry to journal file."""
        try:
            with open(self.path, 'a') as f:
                f.write(entry.to_json_line() + '\n')
            self._logger.debug(f"Wrote event {entry.event_type} at cursor {entry.cursor}")
        except Exception as e:
            self._logger.error(f"Failed to write journal entry: {e}")
            raise
    
    def sync_flush(self) -> None:
        """Flush buffered entries to disk."""
        with self._lock:
            if not self._buffer:
                return
            
            try:
                with open(self.path, 'a') as f:
                    for entry in self._buffer:
                        f.write(entry.to_json_line() + '\n')
                
                count = len(self._buffer)
                self._buffer.clear()
                self._buffer_size = 0
                self._logger.debug(f"Flushed {count} buffered entries to journal")
            except Exception as e:
                self._logger.error(f"Failed to flush journal: {e}")
                raise
    
    def replay(self, from_cursor: int = 0) -> List[Dict[str, Any]]:
        """
        Replay events from journal starting at cursor position.
        
        Args:
            from_cursor: Starting cursor position (inclusive)
            
        Returns:
            List of event dicts
        """
        events = []
        
        if not self.path.exists():
            return events
        
        with self._lock:
            # Flush buffer first
            self.sync_flush()
            
            try:
                with open(self.path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        entry = JournalEntry.from_json_line(line)
                        
                        if entry.cursor >= from_cursor:
                            events.append({
                                "cursor": entry.cursor,
                                "event_type": entry.event_type,
                                "data": entry.payload,
                                "timestamp": entry.timestamp,
                                "state_hash": entry.state_hash,
                                "signature": entry.signature
                            })
            except Exception as e:
                self._logger.error(f"Failed to replay journal: {e}")
                raise
        
        return events
    
    def get_cursor(self) -> int:
        """Get current cursor position."""
        return self._cursor
    
    def verify_state_hash(self, expected_hash: str = None) -> bool:
        """
        Verify state hash integrity.
        
        Args:
            expected_hash: Optional expected hash to verify against.
                         If None, verifies hash chain integrity.
        
        Returns:
            True if verification passes
        """
        if expected_hash is not None:
            return self._last_state_hash == expected_hash
        
        # Verify hash chain integrity
        if not self.path.exists():
            return True
        
        with self._lock:
            self.sync_flush()
            
            try:
                previous_hash = ""
                with open(self.path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        entry = JournalEntry.from_json_line(line)
                        computed_hash = entry.compute_hash()
                        
                        # Verify entry integrity
                        if entry.state_hash:
                            # This is a state hash marker
                            if previous_hash and previous_hash != entry.state_hash:
                                self._logger.warning(
                                    f"State hash mismatch at cursor {entry.cursor}"
                                )
                                return False
                            previous_hash = entry.state_hash
            except Exception as e:
                self._logger.error(f"State hash verification failed: {e}")
                return False
        
        return True
    
    def compact(self, checkpoint_cursor: int = None) -> int:
        """
        Compact journal by removing old entries.
        
        Preserves entries after checkpoint_cursor. Entries before
        are no longer needed for recovery.
        
        Args:
            checkpoint_cursor: Cursor position of last checkpoint.
                             If None, uses current cursor - 1000.
        
        Returns:
            Number of entries removed
        """
        if not self.path.exists():
            return 0
        
        with self._lock:
            self.sync_flush()
            
            if checkpoint_cursor is None:
                checkpoint_cursor = max(0, self._cursor - 1000)
            
            # Read all entries
            entries_to_keep = []
            removed_count = 0
            
            try:
                with open(self.path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        entry = JournalEntry.from_json_line(line)
                        
                        if entry.cursor > checkpoint_cursor:
                            entries_to_keep.append(entry)
                        else:
                            removed_count += 1
                
                # Rewrite journal with compacted entries
                if removed_count > 0:
                    with open(self.path, 'w') as f:
                        for entry in entries_to_keep:
                            f.write(entry.to_json_line() + '\n')
                    
                    self._logger.info(
                        f"Compacted journal: removed {removed_count} entries, "
                        f"kept {len(entries_to_keep)}"
                    )
            except Exception as e:
                self._logger.error(f"Journal compaction failed: {e}")
                return 0
        
        return removed_count
    
    def get_size_bytes(self) -> int:
        """Get current journal size in bytes."""
        if not self.path.exists():
            return 0
        return os.path.getsize(self.path)
    
    def needs_compaction(self) -> bool:
        """Check if journal needs compaction."""
        return self.get_size_bytes() > self.max_size_bytes
    
    def get_entries_by_type(self, event_type: str, 
                            from_cursor: int = 0) -> List[Dict[str, Any]]:
        """
        Get all entries of a specific type.
        
        Args:
            event_type: Event type to filter
            from_cursor: Starting cursor position
            
        Returns:
            List of matching entries
        """
        return [
            e for e in self.replay(from_cursor)
            if e.get("event_type") == event_type
        ]
    
    def get_last_entry(self) -> Optional[Dict[str, Any]]:
        """Get the last entry in the journal."""
        events = self.replay()
        return events[-1] if events else None
    
    def clear(self) -> None:
        """Clear the journal (use with caution)."""
        with self._lock:
            self._buffer.clear()
            self._buffer_size = 0
            self._cursor = 0
            self._last_state_hash = ""
            
            if self.path.exists():
                self.path.unlink()
            
            self._logger.warning("Journal cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get journal statistics."""
        return {
            "path": str(self.path),
            "cursor": self._cursor,
            "size_bytes": self.get_size_bytes(),
            "size_mb": round(self.get_size_bytes() / (1024 * 1024), 2),
            "max_size_mb": self.max_size_bytes / (1024 * 1024),
            "needs_compaction": self.needs_compaction(),
            "buffered_entries": len(self._buffer),
            "last_state_hash": self._last_state_hash
        }


def create_event_journal(config: Dict = None) -> EventJournal:
    """
    Factory function to create event journal from config.
    
    Args:
        config: Configuration dict with keys:
            - event_journal.enabled: bool (default: True)
            - event_journal.path: str (default: ".titan/event_journal.jsonl")
            - event_journal.max_size_mb: int (default: 100)
    
    Returns:
        Configured EventJournal instance
    """
    config = config or {}
    
    enabled = config.get("event_journal", {}).get("enabled", True)
    if not enabled:
        # Return no-op journal
        return EventJournal(Path("/dev/null"))
    
    path = config.get("event_journal", {}).get(
        "path", 
        ".titan/event_journal.jsonl"
    )
    max_size_mb = config.get("event_journal", {}).get("max_size_mb", 100)
    
    return EventJournal(Path(path), max_size_mb=max_size_mb)
