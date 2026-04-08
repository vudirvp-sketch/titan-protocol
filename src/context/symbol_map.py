"""
Memory-bounded symbol map with LRU eviction for TITAN Protocol.

ITEM-OBS-04: Symbol Map OOM Protection

Prevents unbounded growth of SYMBOL_MAP with large codebases by implementing
memory limits and LRU (Least Recently Used) eviction policies.

Features:
- Configurable memory limits (max entries, max memory MB)
- LRU/LFU/FIFO eviction policies
- Namespace qualification (file::symbol) to prevent collisions
- Access tracking (count and timestamp)
- EventBus integration for eviction events

Author: TITAN FUSE Team
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional, TYPE_CHECKING
import logging
import sys

if TYPE_CHECKING:
    from ..events.event_bus import EventBus


class EvictionPolicy(Enum):
    """Eviction policy for symbol map entries."""
    LRU = "lru"  # Least Recently Used - evict oldest access time
    LFU = "lfu"  # Least Frequently Used - evict lowest access count
    FIFO = "fifo"  # First In First Out - evict oldest entry


@dataclass
class SymbolEntry:
    """
    Entry in the symbol map with access tracking.

    Attributes:
        file: Source file path
        symbol: Symbol name
        namespace: Unique identifier as "file::symbol"
        metadata: Additional symbol metadata
        last_accessed: Timestamp of last access
        access_count: Number of times accessed
        size_bytes: Estimated memory size in bytes
        created_at: Timestamp when entry was created
    """
    file: str
    symbol: str
    namespace: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_accessed: datetime = field(default_factory=datetime.utcnow)
    access_count: int = 0
    size_bytes: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)

    def touch(self) -> None:
        """Update access time and increment access count."""
        self.last_accessed = datetime.utcnow()
        self.access_count += 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "file": self.file,
            "symbol": self.symbol,
            "namespace": self.namespace,
            "metadata": self.metadata,
            "last_accessed": self.last_accessed.isoformat() + "Z",
            "access_count": self.access_count,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at.isoformat() + "Z"
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SymbolEntry':
        """Create from dictionary."""
        return cls(
            file=data["file"],
            symbol=data["symbol"],
            namespace=data["namespace"],
            metadata=data.get("metadata", {}),
            last_accessed=datetime.fromisoformat(data["last_accessed"].rstrip("Z")),
            access_count=data.get("access_count", 0),
            size_bytes=data.get("size_bytes", 0),
            created_at=datetime.fromisoformat(data["created_at"].rstrip("Z"))
        )


class BoundedSymbolMap:
    """
    Memory-bounded symbol map with LRU eviction.

    ITEM-OBS-04: Prevents OOM errors by enforcing memory limits and
    evicting least recently used entries when limits are approached.

    Features:
    - Configurable max entries and memory limits
    - Multiple eviction policies (LRU, LFU, FIFO)
    - Namespace qualification to prevent collisions
    - EventBus integration for eviction events
    - Access tracking for intelligent eviction

    Usage:
        config = {
            "max_entries": 100000,
            "max_memory_mb": 500,
            "eviction_batch_size": 1000,
            "eviction_policy": "lru"
        }
        symbol_map = BoundedSymbolMap(config, event_bus)

        # Add a symbol
        symbol_map.add_symbol("src/main.py", "main", {"type": "function"})

        # Lookup symbols
        entries = symbol_map.lookup("main")

        # Get all symbols in a file
        file_entries = symbol_map.get_file_symbols("src/main.py")

        # Manual eviction
        evicted_count = symbol_map.evict_lru(100)
    """

    # Default configuration
    DEFAULT_MAX_ENTRIES = 100000
    DEFAULT_MAX_MEMORY_MB = 500
    DEFAULT_EVICTION_BATCH_SIZE = 1000
    DEFAULT_EVICTION_POLICY = EvictionPolicy.LRU
    OVERFLOW_THRESHOLD = 0.9  # 90% of limit triggers warning

    def __init__(self, config: Dict[str, Any] = None, event_bus: 'EventBus' = None):
        """
        Initialize the bounded symbol map.

        Args:
            config: Configuration dictionary with keys:
                - max_entries: Maximum number of entries (default: 100000)
                - max_memory_mb: Maximum memory in MB (default: 500)
                - eviction_batch_size: Number of entries to evict at once (default: 1000)
                - eviction_policy: "lru", "lfu", or "fifo" (default: "lru")
                - namespace_qualification: Enable namespace qualification (default: True)
            event_bus: Optional EventBus for emitting eviction events
        """
        self._config = config or {}
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

        # Configuration
        self._max_entries = self._config.get("max_entries", self.DEFAULT_MAX_ENTRIES)
        self._max_memory_bytes = self._config.get("max_memory_mb", self.DEFAULT_MAX_MEMORY_MB) * 1024 * 1024
        self._eviction_batch_size = self._config.get("eviction_batch_size", self.DEFAULT_EVICTION_BATCH_SIZE)
        self._namespace_qualification = self._config.get("namespace_qualification", True)

        # Parse eviction policy
        policy_str = self._config.get("eviction_policy", "lru").lower()
        self._eviction_policy = self._parse_eviction_policy(policy_str)

        # Storage: namespace -> SymbolEntry
        self._entries: Dict[str, SymbolEntry] = {}

        # Index: symbol -> List of namespaces (for collision handling)
        self._symbol_index: Dict[str, List[str]] = {}

        # Index: file -> List of namespaces
        self._file_index: Dict[str, List[str]] = {}

        # Statistics
        self._total_evictions = 0
        self._overflow_warnings_emitted = 0

        self._logger.info(
            f"BoundedSymbolMap initialized: max_entries={self._max_entries}, "
            f"max_memory_mb={self._max_memory_bytes // (1024 * 1024)}, "
            f"policy={self._eviction_policy.value}"
        )

    def _parse_eviction_policy(self, policy_str: str) -> EvictionPolicy:
        """Parse eviction policy string."""
        policy_map = {
            "lru": EvictionPolicy.LRU,
            "lfu": EvictionPolicy.LFU,
            "fifo": EvictionPolicy.FIFO
        }
        if policy_str not in policy_map:
            self._logger.warning(
                f"Unknown eviction policy '{policy_str}', defaulting to LRU"
            )
            return EvictionPolicy.LRU
        return policy_map[policy_str]

    def _estimate_size(self, metadata: Dict[str, Any]) -> int:
        """
        Estimate memory size of an entry in bytes.

        Args:
            metadata: Metadata dictionary to estimate

        Returns:
            Estimated size in bytes
        """
        # Base size for SymbolEntry structure
        base_size = 200  # Approximate base size

        # Estimate metadata size
        try:
            metadata_size = sys.getsizeof(metadata)
            for key, value in metadata.items():
                metadata_size += sys.getsizeof(key)
                if isinstance(value, str):
                    metadata_size += len(value.encode('utf-8'))
                elif isinstance(value, (list, dict)):
                    metadata_size += sys.getsizeof(value)
        except Exception:
            # Fallback estimation
            metadata_size = 100

        return base_size + metadata_size

    def _create_namespace(self, file: str, symbol: str) -> str:
        """
        Create unique namespace for file::symbol.

        Args:
            file: File path
            symbol: Symbol name

        Returns:
            Unique namespace string
        """
        if self._namespace_qualification:
            return f"{file}::{symbol}"
        return symbol  # Fall back to symbol only if qualification disabled

    def _check_limits(self) -> bool:
        """
        Check if limits are approaching and trigger eviction if needed.

        Returns:
            True if within limits, False if eviction was triggered
        """
        entry_ratio = len(self._entries) / self._max_entries
        memory_ratio = self.get_memory_usage() / self._max_memory_bytes
        max_ratio = max(entry_ratio, memory_ratio)

        # Check for overflow warning
        if max_ratio >= self.OVERFLOW_THRESHOLD:
            self._emit_overflow_warning(max_ratio)

        # Trigger eviction if over limits
        if len(self._entries) >= self._max_entries or self.get_memory_usage() >= self._max_memory_bytes:
            self._logger.info(
                f"Limit reached: entries={len(self._entries)}/{self._max_entries}, "
                f"memory={self.get_memory_usage()}/{self._max_memory_bytes} bytes. "
                f"Triggering eviction."
            )
            self.evict_lru(self._eviction_batch_size)
            return False

        return True

    def _emit_overflow_warning(self, ratio: float) -> None:
        """Emit SYMBOL_MAP_OVERFLOW warning event."""
        if self._event_bus:
            from ..events.event_bus import Event, EventSeverity

            self._overflow_warnings_emitted += 1
            event = Event(
                event_type="SYMBOL_MAP_OVERFLOW",
                data={
                    "ratio": ratio,
                    "entries_count": len(self._entries),
                    "max_entries": self._max_entries,
                    "memory_bytes": self.get_memory_usage(),
                    "max_memory_bytes": self._max_memory_bytes,
                    "warning_count": self._overflow_warnings_emitted
                },
                severity=EventSeverity.WARN,
                source="BoundedSymbolMap"
            )
            self._event_bus.emit(event)
            self._logger.warning(
                f"Symbol map approaching limits: {ratio * 100:.1f}% capacity"
            )

    def _emit_eviction_event(self, entries: List[SymbolEntry]) -> None:
        """Emit SYMBOL_EVICTED event for evicted entries."""
        if self._event_bus:
            from ..events.event_bus import Event, EventSeverity

            event = Event(
                event_type="SYMBOL_EVICTED",
                data={
                    "count": len(entries),
                    "evicted_namespaces": [e.namespace for e in entries],
                    "policy": self._eviction_policy.value,
                    "total_evictions": self._total_evictions
                },
                severity=EventSeverity.INFO,
                source="BoundedSymbolMap"
            )
            self._event_bus.emit(event)

    def add_symbol(self, file: str, symbol: str, metadata: Dict[str, Any] = None) -> None:
        """
        Add a symbol to the map.

        Args:
            file: Source file path
            symbol: Symbol name
            metadata: Optional metadata dictionary
        """
        # Check limits before adding
        self._check_limits()

        namespace = self._create_namespace(file, symbol)
        metadata = metadata or {}
        size_bytes = self._estimate_size(metadata)

        # Check if entry already exists
        if namespace in self._entries:
            # Update existing entry
            entry = self._entries[namespace]
            entry.metadata.update(metadata)
            entry.size_bytes = size_bytes
            entry.touch()
            self._logger.debug(f"Updated existing symbol: {namespace}")
            return

        # Create new entry
        entry = SymbolEntry(
            file=file,
            symbol=symbol,
            namespace=namespace,
            metadata=metadata,
            size_bytes=size_bytes
        )

        # Add to main storage
        self._entries[namespace] = entry

        # Update symbol index
        if symbol not in self._symbol_index:
            self._symbol_index[symbol] = []
        self._symbol_index[symbol].append(namespace)

        # Update file index
        if file not in self._file_index:
            self._file_index[file] = []
        self._file_index[file].append(namespace)

        self._logger.debug(f"Added symbol: {namespace}")

    def lookup(self, symbol: str) -> List[SymbolEntry]:
        """
        Look up symbols by name.

        Args:
            symbol: Symbol name to look up

        Returns:
            List of matching SymbolEntry objects
        """
        namespaces = self._symbol_index.get(symbol, [])
        entries = []

        for namespace in namespaces:
            if namespace in self._entries:
                entry = self._entries[namespace]
                entry.touch()  # Update access tracking
                entries.append(entry)

        self._logger.debug(
            f"Lookup '{symbol}': found {len(entries)} entries"
        )
        return entries

    def get_file_symbols(self, file: str) -> List[SymbolEntry]:
        """
        Get all symbols for a file.

        Args:
            file: File path

        Returns:
            List of SymbolEntry objects for the file
        """
        namespaces = self._file_index.get(file, [])
        entries = []

        for namespace in namespaces:
            if namespace in self._entries:
                entry = self._entries[namespace]
                entry.touch()  # Update access tracking
                entries.append(entry)

        self._logger.debug(
            f"Get file symbols '{file}': found {len(entries)} entries"
        )
        return entries

    def evict_lru(self, count: int) -> int:
        """
        Evict least recently used entries.

        Uses the configured eviction policy (LRU, LFU, or FIFO).

        Args:
            count: Number of entries to evict

        Returns:
            Actual number of entries evicted
        """
        if not self._entries:
            return 0

        # Sort entries based on eviction policy
        if self._eviction_policy == EvictionPolicy.LRU:
            # Sort by (access_count, last_accessed) - lowest first
            sorted_entries = sorted(
                self._entries.values(),
                key=lambda e: (e.access_count, e.last_accessed)
            )
        elif self._eviction_policy == EvictionPolicy.LFU:
            # Sort by access_count only
            sorted_entries = sorted(
                self._entries.values(),
                key=lambda e: e.access_count
            )
        else:  # FIFO
            # Sort by created_at
            sorted_entries = sorted(
                self._entries.values(),
                key=lambda e: e.created_at
            )

        # Evict the specified count
        to_evict = sorted_entries[:count]
        evicted_count = 0

        for entry in to_evict:
            namespace = entry.namespace

            # Remove from main storage
            if namespace in self._entries:
                del self._entries[namespace]
                evicted_count += 1

            # Remove from symbol index
            if entry.symbol in self._symbol_index:
                try:
                    self._symbol_index[entry.symbol].remove(namespace)
                    if not self._symbol_index[entry.symbol]:
                        del self._symbol_index[entry.symbol]
                except ValueError:
                    pass

            # Remove from file index
            if entry.file in self._file_index:
                try:
                    self._file_index[entry.file].remove(namespace)
                    if not self._file_index[entry.file]:
                        del self._file_index[entry.file]
                except ValueError:
                    pass

        self._total_evictions += evicted_count

        # Emit eviction event
        if evicted_count > 0:
            self._emit_eviction_event(to_evict[:evicted_count])
            self._logger.info(
                f"Evicted {evicted_count} entries using {self._eviction_policy.value} policy. "
                f"Total evictions: {self._total_evictions}"
            )

        return evicted_count

    def get_memory_usage(self) -> int:
        """
        Get current memory usage in bytes.

        Returns:
            Total estimated memory usage in bytes
        """
        return sum(entry.size_bytes for entry in self._entries.values())

    def clear(self) -> None:
        """Clear all entries from the symbol map."""
        count = len(self._entries)
        self._entries.clear()
        self._symbol_index.clear()
        self._file_index.clear()
        self._logger.info(f"Cleared symbol map: {count} entries removed")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the symbol map.

        Returns:
            Dictionary with statistics
        """
        return {
            "entries_count": len(self._entries),
            "max_entries": self._max_entries,
            "memory_bytes": self.get_memory_usage(),
            "max_memory_bytes": self._max_memory_bytes,
            "memory_mb": round(self.get_memory_usage() / (1024 * 1024), 2),
            "max_memory_mb": self._max_memory_bytes // (1024 * 1024),
            "unique_symbols": len(self._symbol_index),
            "files_indexed": len(self._file_index),
            "total_evictions": self._total_evictions,
            "overflow_warnings": self._overflow_warnings_emitted,
            "eviction_policy": self._eviction_policy.value,
            "namespace_qualification": self._namespace_qualification,
            "utilization": round(len(self._entries) / self._max_entries * 100, 2) if self._max_entries > 0 else 0
        }

    def get_entry(self, file: str, symbol: str) -> Optional[SymbolEntry]:
        """
        Get a specific entry by file and symbol.

        Args:
            file: File path
            symbol: Symbol name

        Returns:
            SymbolEntry if found, None otherwise
        """
        namespace = self._create_namespace(file, symbol)
        entry = self._entries.get(namespace)
        if entry:
            entry.touch()
        return entry

    def remove_symbol(self, file: str, symbol: str) -> bool:
        """
        Remove a specific symbol from the map.

        Args:
            file: File path
            symbol: Symbol name

        Returns:
            True if removed, False if not found
        """
        namespace = self._create_namespace(file, symbol)

        if namespace not in self._entries:
            return False

        entry = self._entries[namespace]

        # Remove from main storage
        del self._entries[namespace]

        # Remove from symbol index
        if entry.symbol in self._symbol_index:
            try:
                self._symbol_index[entry.symbol].remove(namespace)
                if not self._symbol_index[entry.symbol]:
                    del self._symbol_index[entry.symbol]
            except ValueError:
                pass

        # Remove from file index
        if entry.file in self._file_index:
            try:
                self._file_index[entry.file].remove(namespace)
                if not self._file_index[entry.file]:
                    del self._file_index[entry.file]
            except ValueError:
                pass

        self._logger.debug(f"Removed symbol: {namespace}")
        return True

    def set_event_bus(self, event_bus: 'EventBus') -> None:
        """
        Set the event bus for emitting events.

        Args:
            event_bus: EventBus instance
        """
        self._event_bus = event_bus
        self._logger.info("EventBus attached to BoundedSymbolMap")


# Global symbol map instance (singleton pattern)
_symbol_map_instance: Optional[BoundedSymbolMap] = None


def get_symbol_map(config: Dict[str, Any] = None, event_bus: 'EventBus' = None) -> BoundedSymbolMap:
    """
    Get the global symbol map instance.

    Args:
        config: Configuration (only used on first call)
        event_bus: EventBus (only used on first call)

    Returns:
        Global BoundedSymbolMap instance
    """
    global _symbol_map_instance

    if _symbol_map_instance is None:
        _symbol_map_instance = BoundedSymbolMap(config, event_bus)

    return _symbol_map_instance


def reset_symbol_map() -> None:
    """Reset the global symbol map instance."""
    global _symbol_map_instance

    if _symbol_map_instance is not None:
        _symbol_map_instance.clear()
    _symbol_map_instance = None
