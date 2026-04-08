"""
Tests for ITEM-OBS-04: Symbol Map OOM Protection

Tests for BoundedSymbolMap with LRU eviction and namespace qualification.

Author: TITAN FUSE Team
Version: 1.0.0
"""

import pytest
from datetime import datetime, timedelta
import time

from src.context.symbol_map import (
    BoundedSymbolMap,
    SymbolEntry,
    EvictionPolicy,
    get_symbol_map,
    reset_symbol_map
)
from src.events.event_bus import EventBus, Event, EventSeverity


class TestSymbolEntry:
    """Tests for SymbolEntry dataclass."""

    def test_symbol_entry_creation(self):
        """Test basic SymbolEntry creation."""
        entry = SymbolEntry(
            file="src/main.py",
            symbol="main",
            namespace="src/main.py::main",
            metadata={"type": "function", "line": 10}
        )

        assert entry.file == "src/main.py"
        assert entry.symbol == "main"
        assert entry.namespace == "src/main.py::main"
        assert entry.metadata["type"] == "function"
        assert entry.access_count == 0
        assert entry.size_bytes == 0

    def test_symbol_entry_touch(self):
        """Test that touch updates access time and count."""
        entry = SymbolEntry(
            file="test.py",
            symbol="foo",
            namespace="test.py::foo"
        )

        original_time = entry.last_accessed
        original_count = entry.access_count

        # Small delay to ensure time difference
        time.sleep(0.01)
        entry.touch()

        assert entry.access_count == original_count + 1
        assert entry.last_accessed > original_time

    def test_symbol_entry_to_dict(self):
        """Test serialization to dictionary."""
        entry = SymbolEntry(
            file="app.py",
            symbol="App",
            namespace="app.py::App",
            metadata={"type": "class"},
            access_count=5,
            size_bytes=100
        )

        data = entry.to_dict()

        assert data["file"] == "app.py"
        assert data["symbol"] == "App"
        assert data["namespace"] == "app.py::App"
        assert data["access_count"] == 5
        assert data["size_bytes"] == 100

    def test_symbol_entry_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "file": "lib.py",
            "symbol": "helper",
            "namespace": "lib.py::helper",
            "metadata": {"exported": True},
            "last_accessed": "2024-01-15T10:30:00Z",
            "access_count": 3,
            "size_bytes": 50,
            "created_at": "2024-01-15T09:00:00Z"
        }

        entry = SymbolEntry.from_dict(data)

        assert entry.file == "lib.py"
        assert entry.symbol == "helper"
        assert entry.access_count == 3
        assert entry.size_bytes == 50


class TestBoundedSymbolMap:
    """Tests for BoundedSymbolMap class."""

    def test_basic_creation(self):
        """Test basic BoundedSymbolMap creation."""
        symbol_map = BoundedSymbolMap()

        assert symbol_map.get_stats()["entries_count"] == 0
        assert symbol_map.get_memory_usage() == 0

    def test_add_symbol(self):
        """Test adding symbols to the map."""
        symbol_map = BoundedSymbolMap()

        symbol_map.add_symbol("main.py", "main", {"type": "function"})
        symbol_map.add_symbol("utils.py", "helper", {"type": "function"})

        stats = symbol_map.get_stats()
        assert stats["entries_count"] == 2
        assert stats["unique_symbols"] == 2
        assert stats["files_indexed"] == 2

    def test_lookup_symbol(self):
        """Test symbol lookup."""
        symbol_map = BoundedSymbolMap()

        symbol_map.add_symbol("main.py", "process", {"type": "function"})
        symbol_map.add_symbol("utils.py", "process", {"type": "function"})

        entries = symbol_map.lookup("process")

        assert len(entries) == 2
        # Both should have same symbol but different files
        symbols = [e.symbol for e in entries]
        assert all(s == "process" for s in symbols)

    def test_get_file_symbols(self):
        """Test getting all symbols for a file."""
        symbol_map = BoundedSymbolMap()

        symbol_map.add_symbol("app.py", "App", {"type": "class"})
        symbol_map.add_symbol("app.py", "main", {"type": "function"})
        symbol_map.add_symbol("other.py", "other", {"type": "function"})

        entries = symbol_map.get_file_symbols("app.py")

        assert len(entries) == 2
        assert all(e.file == "app.py" for e in entries)

    def test_namespace_collision_prevention(self):
        """Test that namespace qualification prevents collisions."""
        symbol_map = BoundedSymbolMap()

        # Add same symbol from different files
        symbol_map.add_symbol("module1.py", "process", {"type": "function", "version": 1})
        symbol_map.add_symbol("module2.py", "process", {"type": "function", "version": 2})

        # Both should exist
        entries = symbol_map.lookup("process")
        assert len(entries) == 2

        # Each should have correct metadata
        module1_entry = symbol_map.get_entry("module1.py", "process")
        module2_entry = symbol_map.get_entry("module2.py", "process")

        assert module1_entry is not None
        assert module2_entry is not None
        assert module1_entry.metadata["version"] == 1
        assert module2_entry.metadata["version"] == 2

    def test_access_tracking(self):
        """Test that access count and time are tracked correctly."""
        symbol_map = BoundedSymbolMap()

        symbol_map.add_symbol("test.py", "func", {"type": "function"})

        # Initial state - get_entry also touches, so count is 1
        entry = symbol_map.get_entry("test.py", "func")
        initial_count = entry.access_count
        initial_time = entry.last_accessed

        # Access via lookup (this will touch the entry)
        time.sleep(0.01)
        entries = symbol_map.lookup("func")
        count_after_lookup = entries[0].access_count

        # Access count should increase by 1 from lookup
        assert count_after_lookup == initial_count + 1
        assert entries[0].last_accessed > initial_time

        # Access via get_file_symbols (this will also touch)
        time.sleep(0.01)
        file_entries = symbol_map.get_file_symbols("test.py")
        count_after_file_lookup = file_entries[0].access_count

        # Should increase by another 1
        assert count_after_file_lookup == count_after_lookup + 1

    def test_memory_bounded_limits(self):
        """Test that memory limits are enforced."""
        config = {
            "max_entries": 10,
            "max_memory_mb": 1,  # Very small to trigger eviction
            "eviction_batch_size": 3
        }
        symbol_map = BoundedSymbolMap(config)

        # Add more entries than limit
        for i in range(20):
            symbol_map.add_symbol(f"file{i}.py", f"symbol{i}", {"type": "function"})

        # Should have evicted some entries
        stats = symbol_map.get_stats()
        assert stats["entries_count"] <= 10  # Should not exceed max_entries
        assert stats["total_evictions"] > 0  # Should have evicted some

    def test_lru_eviction_order(self):
        """Test that LRU eviction removes least used entries first."""
        config = {
            "max_entries": 5,
            "eviction_batch_size": 2,
            "eviction_policy": "lru"
        }
        symbol_map = BoundedSymbolMap(config)

        # Add entries
        for i in range(5):
            symbol_map.add_symbol(f"file{i}.py", f"symbol{i}", {"type": "function"})

        # Access some entries to make them "recently used"
        symbol_map.lookup("symbol0")  # access_count = 1
        symbol_map.lookup("symbol1")  # access_count = 1
        symbol_map.lookup("symbol0")  # access_count = 2

        # Add more entries to trigger eviction
        symbol_map.add_symbol("file5.py", "symbol5", {})
        symbol_map.add_symbol("file6.py", "symbol6", {})

        # Least accessed entries should have been evicted
        # symbol2, symbol3, symbol4 were never accessed
        stats = symbol_map.get_stats()
        assert stats["total_evictions"] >= 2

    def test_lfu_eviction_policy(self):
        """Test LFU eviction policy."""
        config = {
            "max_entries": 5,
            "eviction_batch_size": 2,
            "eviction_policy": "lfu"
        }
        symbol_map = BoundedSymbolMap(config)

        # Add entries
        for i in range(5):
            symbol_map.add_symbol(f"file{i}.py", f"symbol{i}", {})

        # Access some entries more frequently
        for _ in range(5):
            symbol_map.lookup("symbol0")
        for _ in range(3):
            symbol_map.lookup("symbol1")

        # Trigger eviction
        symbol_map.add_symbol("file5.py", "symbol5", {})
        symbol_map.add_symbol("file6.py", "symbol6", {})

        stats = symbol_map.get_stats()
        assert stats["total_evictions"] >= 2

    def test_fifo_eviction_policy(self):
        """Test FIFO eviction policy."""
        config = {
            "max_entries": 5,
            "eviction_batch_size": 2,
            "eviction_policy": "fifo"
        }
        symbol_map = BoundedSymbolMap(config)

        # Add entries
        for i in range(5):
            symbol_map.add_symbol(f"file{i}.py", f"symbol{i}", {})

        # Even if we access older entries, FIFO should evict oldest
        symbol_map.lookup("symbol0")  # Make it frequently accessed
        symbol_map.lookup("symbol0")

        # Trigger eviction
        symbol_map.add_symbol("file5.py", "symbol5", {})

        stats = symbol_map.get_stats()
        assert stats["total_evictions"] >= 2

    def test_evict_lru_manual(self):
        """Test manual eviction."""
        symbol_map = BoundedSymbolMap()

        # Add 10 entries
        for i in range(10):
            symbol_map.add_symbol(f"file{i}.py", f"symbol{i}", {})

        # Evict 5
        evicted = symbol_map.evict_lru(5)

        assert evicted == 5
        assert symbol_map.get_stats()["entries_count"] == 5

    def test_clear(self):
        """Test clearing the symbol map."""
        symbol_map = BoundedSymbolMap()

        for i in range(10):
            symbol_map.add_symbol(f"file{i}.py", f"symbol{i}", {})

        assert symbol_map.get_stats()["entries_count"] == 10

        symbol_map.clear()

        assert symbol_map.get_stats()["entries_count"] == 0
        assert symbol_map.get_memory_usage() == 0

    def test_remove_symbol(self):
        """Test removing a specific symbol."""
        symbol_map = BoundedSymbolMap()

        symbol_map.add_symbol("test.py", "func1", {})
        symbol_map.add_symbol("test.py", "func2", {})

        result = symbol_map.remove_symbol("test.py", "func1")

        assert result is True
        assert len(symbol_map.lookup("func1")) == 0
        assert len(symbol_map.lookup("func2")) == 1

        # Try removing non-existent
        result = symbol_map.remove_symbol("nonexistent.py", "func")
        assert result is False

    def test_get_stats(self):
        """Test statistics retrieval."""
        config = {
            "max_entries": 100,
            "max_memory_mb": 10,
            "eviction_policy": "lru"
        }
        symbol_map = BoundedSymbolMap(config)

        for i in range(10):
            symbol_map.add_symbol(f"file{i}.py", f"symbol{i}", {})

        stats = symbol_map.get_stats()

        assert stats["entries_count"] == 10
        assert stats["max_entries"] == 100
        assert stats["memory_bytes"] > 0  # Memory should be tracked
        assert stats["max_memory_mb"] == 10
        assert stats["unique_symbols"] == 10
        assert stats["files_indexed"] == 10
        assert stats["eviction_policy"] == "lru"
        assert stats["namespace_qualification"] is True
        assert 0 <= stats["utilization"] <= 100

    def test_eviction_under_pressure(self):
        """Test behavior under memory pressure."""
        config = {
            "max_entries": 100,
            "max_memory_mb": 0.001,  # Very small memory limit
            "eviction_batch_size": 10
        }
        symbol_map = BoundedSymbolMap(config)

        # Add many entries to create pressure
        for i in range(200):
            # Add larger metadata to consume memory faster
            metadata = {"data": "x" * 100, "index": i}
            symbol_map.add_symbol(f"file{i}.py", f"symbol{i}", metadata)

        stats = symbol_map.get_stats()
        # Should have triggered evictions
        assert stats["total_evictions"] > 0


class TestEventBusIntegration:
    """Tests for EventBus integration."""

    def test_overflow_event_emitted(self):
        """Test that SYMBOL_MAP_OVERFLOW event is emitted."""
        event_bus = EventBus()
        config = {
            "max_entries": 10,
            "eviction_batch_size": 2
        }
        symbol_map = BoundedSymbolMap(config, event_bus)

        # Track events
        overflow_events = []
        def capture_event(event: Event):
            if event.event_type == "SYMBOL_MAP_OVERFLOW":
                overflow_events.append(event)

        event_bus.subscribe("SYMBOL_MAP_OVERFLOW", capture_event)

        # Add entries to trigger overflow warning (90% threshold)
        for i in range(10):
            symbol_map.add_symbol(f"file{i}.py", f"symbol{i}", {})

        # Should have emitted overflow warning
        assert len(overflow_events) >= 1
        assert overflow_events[0].severity == EventSeverity.WARN

    def test_eviction_event_emitted(self):
        """Test that SYMBOL_EVICTED event is emitted."""
        event_bus = EventBus()
        config = {
            "max_entries": 5,
            "eviction_batch_size": 2
        }
        symbol_map = BoundedSymbolMap(config, event_bus)

        # Track events
        evicted_events = []
        def capture_event(event: Event):
            if event.event_type == "SYMBOL_EVICTED":
                evicted_events.append(event)

        event_bus.subscribe("SYMBOL_EVICTED", capture_event)

        # Add entries and trigger eviction
        for i in range(10):
            symbol_map.add_symbol(f"file{i}.py", f"symbol{i}", {})

        # Should have emitted eviction events
        assert len(evicted_events) >= 1
        assert evicted_events[0].severity == EventSeverity.INFO
        assert "count" in evicted_events[0].data
        assert "policy" in evicted_events[0].data


class TestGlobalSymbolMap:
    """Tests for global symbol map functions."""

    def test_get_symbol_map_singleton(self):
        """Test that get_symbol_map returns a singleton."""
        reset_symbol_map()

        map1 = get_symbol_map()
        map2 = get_symbol_map()

        assert map1 is map2

    def test_reset_symbol_map(self):
        """Test that reset_symbol_map clears the instance."""
        # Get and populate
        symbol_map = get_symbol_map()
        symbol_map.add_symbol("test.py", "func", {})

        assert symbol_map.get_stats()["entries_count"] == 1

        # Reset
        reset_symbol_map()

        # Get new instance
        symbol_map = get_symbol_map()
        assert symbol_map.get_stats()["entries_count"] == 0


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_lookup(self):
        """Test lookup for non-existent symbol."""
        symbol_map = BoundedSymbolMap()

        entries = symbol_map.lookup("nonexistent")

        assert entries == []

    def test_empty_file_symbols(self):
        """Test getting symbols for non-existent file."""
        symbol_map = BoundedSymbolMap()

        entries = symbol_map.get_file_symbols("nonexistent.py")

        assert entries == []

    def test_evict_more_than_exists(self):
        """Test evicting more entries than exist."""
        symbol_map = BoundedSymbolMap()

        for i in range(5):
            symbol_map.add_symbol(f"file{i}.py", f"symbol{i}", {})

        evicted = symbol_map.evict_lru(100)

        assert evicted == 5
        assert symbol_map.get_stats()["entries_count"] == 0

    def test_update_existing_entry(self):
        """Test updating an existing entry."""
        symbol_map = BoundedSymbolMap()

        symbol_map.add_symbol("test.py", "func", {"version": 1})
        symbol_map.add_symbol("test.py", "func", {"version": 2, "extra": True})

        entries = symbol_map.lookup("func")
        assert len(entries) == 1
        assert entries[0].metadata["version"] == 2
        assert entries[0].metadata["extra"] is True
        assert entries[0].access_count >= 1  # Should have been touched

    def test_namespace_qualification_disabled(self):
        """Test behavior with namespace qualification disabled."""
        config = {"namespace_qualification": False}
        symbol_map = BoundedSymbolMap(config)

        # Without qualification, same symbol in different files will collide
        symbol_map.add_symbol("file1.py", "func", {"source": "file1"})
        symbol_map.add_symbol("file2.py", "func", {"source": "file2"})

        entries = symbol_map.lookup("func")
        # Should only have one entry (the second one overwrote the first)
        assert len(entries) == 1
        assert entries[0].metadata["source"] == "file2"

    def test_large_metadata(self):
        """Test handling of large metadata."""
        symbol_map = BoundedSymbolMap()

        # Add entry with large metadata
        large_data = "x" * 10000
        symbol_map.add_symbol("big.py", "big_symbol", {"data": large_data})

        entries = symbol_map.lookup("big_symbol")
        assert len(entries) == 1
        assert len(entries[0].metadata["data"]) == 10000

    def test_concurrent_access_tracking(self):
        """Test that concurrent accesses are tracked correctly."""
        symbol_map = BoundedSymbolMap()

        symbol_map.add_symbol("test.py", "func", {})

        # Multiple accesses
        for _ in range(10):
            symbol_map.lookup("func")

        entry = symbol_map.get_entry("test.py", "func")
        # 10 lookups + 1 add_symbol touch + 1 get_entry touch
        assert entry.access_count >= 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
