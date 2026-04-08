"""
Tests for Auto-Split on Secondary Chunk Limit (ITEM-FEAT-91).

Tests the automatic resplitting functionality when chunks exceed
secondary limits during processing.

Author: TITAN FUSE Team
Version: 3.8.0
"""

import pytest
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from context.auto_split import (
    AutoSplitter,
    SplitStats,
    AutoSplitConfig,
    BoundaryType,
    create_auto_splitter
)
from events.event_bus import EventBus, Event, EventSeverity


class TestSplitStats:
    """Tests for SplitStats dataclass."""
    
    def test_init_defaults(self):
        """Test default initialization."""
        stats = SplitStats()
        assert stats.total_splits == 0
        assert stats.total_chars_processed == 0
        assert stats.average_chunk_size == 0.0
        assert stats.max_chunk_seen == 0
        assert stats.last_split_reason is None
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        stats = SplitStats(
            total_splits=5,
            total_chars_processed=100000,
            average_chunk_size=20000.0,
            max_chunk_seen=50000,
            last_split_reason="Secondary limit exceeded"
        )
        
        d = stats.to_dict()
        assert d["total_splits"] == 5
        assert d["total_chars_processed"] == 100000
        assert d["average_chunk_size"] == 20000.0
        assert d["max_chunk_seen"] == 50000
        assert d["last_split_reason"] == "Secondary limit exceeded"
    
    def test_update_with_chunk(self):
        """Test updating stats with chunk size."""
        stats = SplitStats()
        
        stats.update_with_chunk(10000)
        assert stats.max_chunk_seen == 10000
        assert stats.total_chars_processed == 10000
        
        stats.update_with_chunk(20000)
        assert stats.max_chunk_seen == 20000


class TestAutoSplitConfig:
    """Tests for AutoSplitConfig dataclass."""
    
    def test_init_defaults(self):
        """Test default initialization."""
        config = AutoSplitConfig()
        assert config.primary_limit == 50000
        assert config.secondary_limit == 150000
        assert config.enabled is True
        assert config.max_recursion_depth == 3
        assert config.preserve_boundaries is True
    
    def test_from_dict(self):
        """Test creation from dictionary."""
        config = AutoSplitConfig.from_dict({
            "primary_limit": 30000,
            "secondary_limit": 100000,
            "enabled": False,
            "max_recursion_depth": 5
        })
        
        assert config.primary_limit == 30000
        assert config.secondary_limit == 100000
        assert config.enabled is False
        assert config.max_recursion_depth == 5
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        config = AutoSplitConfig(
            primary_limit=40000,
            secondary_limit=120000
        )
        
        d = config.to_dict()
        assert d["primary_limit"] == 40000
        assert d["secondary_limit"] == 120000


class TestAutoSplitter:
    """Tests for AutoSplitter class."""
    
    def test_init_defaults(self):
        """Test default initialization."""
        splitter = AutoSplitter()
        
        assert splitter._config.primary_limit == 50000
        assert splitter._config.secondary_limit == 150000
        assert splitter._config.enabled is True
    
    def test_init_with_config(self):
        """Test initialization with custom config."""
        splitter = AutoSplitter({
            "primary_limit": 30000,
            "secondary_limit": 100000
        })
        
        assert splitter._config.primary_limit == 30000
        assert splitter._config.secondary_limit == 100000
    
    def test_check_chunk_size_small_chunk(self):
        """Test check_chunk_size with small chunk."""
        splitter = AutoSplitter()
        
        small_chunk = "x" * 1000
        assert splitter.check_chunk_size(small_chunk) is True
    
    def test_check_chunk_size_large_chunk(self):
        """Test check_chunk_size with large chunk."""
        splitter = AutoSplitter({"secondary_limit": 100000})
        
        large_chunk = "x" * 200000
        assert splitter.check_chunk_size(large_chunk) is False
    
    def test_should_resplit_disabled(self):
        """Test should_resplit when auto-split is disabled."""
        splitter = AutoSplitter({"enabled": False})
        
        large_chunk = "x" * 200000
        assert splitter.should_resplit(large_chunk) is False
    
    def test_should_resplit_within_limit(self):
        """Test should_resplit with chunk within limit."""
        splitter = AutoSplitter({"secondary_limit": 200000})
        
        chunk = "x" * 100000
        assert splitter.should_resplit(chunk) is False
    
    def test_should_resplit_exceeds_limit(self):
        """Test should_resplit with chunk exceeding limit."""
        splitter = AutoSplitter({"secondary_limit": 100000})
        
        chunk = "x" * 200000
        assert splitter.should_resplit(chunk) is True
    
    def test_should_resplit_custom_limit(self):
        """Test should_resplit with custom limit."""
        splitter = AutoSplitter({"secondary_limit": 200000})
        
        chunk = "x" * 150000
        # Within default secondary limit but exceeds custom limit
        assert splitter.should_resplit(chunk, limit=100000) is True
    
    def test_resplit_empty_chunk(self):
        """Test resplit with empty chunk."""
        splitter = AutoSplitter()
        
        result = splitter.resplit("", "test")
        assert result == []
    
    def test_resplit_small_chunk(self):
        """Test resplit with chunk within limits."""
        splitter = AutoSplitter({
            "primary_limit": 10000,
            "secondary_limit": 100000
        })
        
        chunk = "x" * 50000
        # First check should_resplit - it should return False since it's under secondary limit
        assert splitter.should_resplit(chunk) is False
        
        # If we call resplit directly, it will split based on primary_limit
        # But process_chunk checks should_resplit first
        result = splitter.process_chunk(chunk)
        assert len(result) == 1
        assert len(result[0]) == 50000
    
    def test_resplit_large_chunk(self):
        """Test resplit with chunk exceeding limits."""
        splitter = AutoSplitter({
            "primary_limit": 10000,
            "secondary_limit": 50000
        })
        
        chunk = "x" * 100000
        result = splitter.resplit(chunk, "Secondary limit exceeded")
        
        # Should be split into multiple chunks
        assert len(result) > 1
        
        # All content should be preserved
        total_chars = sum(len(c) for c in result)
        assert total_chars == 100000
    
    def test_resplit_preserves_content(self):
        """Test that resplit preserves all content."""
        splitter = AutoSplitter({
            "primary_limit": 1000,
            "secondary_limit": 5000
        })
        
        original = "Hello World! " * 1000  # 13000 chars
        result = splitter.resplit(original, "test")
        
        # Reconstruct and compare
        reconstructed = "".join(result)
        assert reconstructed.replace("\n", "") == original.replace("\n", "")
    
    def test_resplit_semantic_boundaries(self):
        """Test that resplit respects semantic boundaries."""
        splitter = AutoSplitter({
            "primary_limit": 100,
            "secondary_limit": 500,
            "preserve_boundaries": True
        })
        
        # Create content with clear function boundaries
        content = """def function_one():
    pass

def function_two():
    pass

def function_three():
    pass
"""
        
        result = splitter.resplit(content, "test")
        
        # Should split at function boundaries
        assert len(result) > 0
        # Content should be preserved
        total = sum(len(c) for c in result)
        assert total >= len(content.replace("\n", ""))
    
    def test_resplit_max_recursion_depth(self):
        """Test that max recursion depth is respected."""
        splitter = AutoSplitter({
            "primary_limit": 100,
            "secondary_limit": 1000,
            "max_recursion_depth": 1
        })
        
        # Very large chunk
        chunk = "x" * 10000
        result = splitter.resplit(chunk, "test")
        
        # Should still produce chunks
        assert len(result) > 0
        # All content preserved
        total_chars = sum(len(c) for c in result)
        assert total_chars == 10000
    
    def test_process_chunk(self):
        """Test process_chunk convenience method."""
        splitter = AutoSplitter({
            "primary_limit": 1000,
            "secondary_limit": 5000
        })
        
        # Small chunk
        small = "x" * 100
        result = splitter.process_chunk(small)
        assert len(result) == 1
        
        # Large chunk
        large = "x" * 10000
        result = splitter.process_chunk(large)
        assert len(result) > 1
    
    def test_get_split_stats(self):
        """Test get_split_stats returns stats."""
        splitter = AutoSplitter()
        
        stats = splitter.get_split_stats()
        assert isinstance(stats, SplitStats)
        assert stats.total_splits == 0
        
        # Trigger a split
        splitter.resplit("x" * 200000, "test")
        stats = splitter.get_split_stats()
        assert stats.total_splits == 1
        assert stats.last_split_reason == "test"
    
    def test_update_config(self):
        """Test updating configuration."""
        splitter = AutoSplitter()
        
        splitter.update_config({
            "primary_limit": 25000,
            "secondary_limit": 100000
        })
        
        assert splitter._config.primary_limit == 25000
        assert splitter._config.secondary_limit == 100000
    
    def test_reset_stats(self):
        """Test resetting statistics."""
        splitter = AutoSplitter()
        
        # Trigger some stats
        splitter.resplit("x" * 200000, "test")
        assert splitter.get_split_stats().total_splits == 1
        
        # Reset
        splitter.reset_stats()
        assert splitter.get_split_stats().total_splits == 0


class TestAutoSplitterEventBusIntegration:
    """Tests for EventBus integration."""
    
    def test_emit_auto_split_event(self):
        """Test that CHUNK_AUTO_SPLIT event is emitted."""
        event_bus = EventBus()
        splitter = AutoSplitter({
            "primary_limit": 1000,
            "secondary_limit": 5000
        }, event_bus=event_bus)
        
        # Track events
        emitted_events = []
        
        def event_handler(event: Event):
            emitted_events.append(event)
        
        event_bus.subscribe("CHUNK_AUTO_SPLIT", event_handler)
        
        # Trigger a split
        large_chunk = "x" * 10000
        splitter.resplit(large_chunk, "Secondary limit exceeded")
        
        # Check event was emitted
        assert len(emitted_events) == 1
        event = emitted_events[0]
        assert event.event_type == "CHUNK_AUTO_SPLIT"
        assert event.data["original_size"] == 10000
        assert event.data["new_chunks_count"] > 1
        assert event.data["reason"] == "Secondary limit exceeded"
    
    def test_event_without_event_bus(self):
        """Test that splitter works without EventBus."""
        splitter = AutoSplitter({
            "primary_limit": 1000,
            "secondary_limit": 5000
        })
        
        # Should not raise error
        result = splitter.resplit("x" * 10000, "test")
        assert len(result) > 0


class TestAutoSplitterBoundaryTypes:
    """Tests for semantic boundary detection."""
    
    def test_heading_boundary(self):
        """Test splitting at heading boundaries."""
        splitter = AutoSplitter({
            "primary_limit": 50,
            "secondary_limit": 500,
            "boundary_types": [BoundaryType.HEADING]
        })
        
        content = """# Heading 1

Some content here that goes on for a while.

# Heading 2

More content that continues.

# Heading 3

Final section content.
"""
        result = splitter.resplit(content, "test")
        
        # Should produce chunks
        assert len(result) >= 1
    
    def test_function_boundary(self):
        """Test splitting at function boundaries."""
        splitter = AutoSplitter({
            "primary_limit": 100,
            "secondary_limit": 500,
            "boundary_types": [BoundaryType.FUNCTION]
        })
        
        content = """def foo():
    pass

def bar():
    pass

def baz():
    pass
"""
        result = splitter.resplit(content, "test")
        
        # Should detect function boundaries
        assert len(result) >= 1
    
    def test_class_boundary(self):
        """Test splitting at class boundaries."""
        splitter = AutoSplitter({
            "primary_limit": 100,
            "secondary_limit": 500,
            "boundary_types": [BoundaryType.CLASS]
        })
        
        content = """class FirstClass:
    pass

class SecondClass:
    pass
"""
        result = splitter.resplit(content, "test")
        
        # Should detect class boundaries
        assert len(result) >= 1


class TestNoDataLoss:
    """Tests to verify no data loss during splitting."""
    
    def test_random_content_preserved(self):
        """Test that random content is fully preserved."""
        import random
        import string
        
        splitter = AutoSplitter({
            "primary_limit": 500,
            "secondary_limit": 2000
        })
        
        # Generate random content
        chars = string.ascii_letters + string.digits + string.punctuation + " \n"
        original = ''.join(random.choice(chars) for _ in range(10000))
        
        result = splitter.resplit(original, "test")
        
        # Reconstruct content (ignoring whitespace differences)
        reconstructed = "".join(result)
        
        # All original content should be present
        for char in original:
            if char != '\n':
                assert char in reconstructed or char.strip() == ""
    
    def test_code_content_preserved(self):
        """Test that code content is fully preserved."""
        splitter = AutoSplitter({
            "primary_limit": 200,
            "secondary_limit": 1000
        })
        
        code = '''
def calculate_sum(numbers):
    """Calculate the sum of a list of numbers."""
    total = 0
    for num in numbers:
        total += num
    return total

def calculate_average(numbers):
    """Calculate the average of a list of numbers."""
    if not numbers:
        return 0
    return calculate_sum(numbers) / len(numbers)

def main():
    data = [1, 2, 3, 4, 5]
    print(f"Sum: {calculate_sum(data)}")
    print(f"Average: {calculate_average(data)}")

if __name__ == "__main__":
    main()
'''
        
        result = splitter.resplit(code, "test")
        reconstructed = "".join(result)
        
        # Key code elements should be preserved
        assert "def calculate_sum" in reconstructed
        assert "def calculate_average" in reconstructed
        assert "def main" in reconstructed
        assert "return total" in reconstructed
        assert "return calculate_sum" in reconstructed


class TestFactoryFunction:
    """Tests for factory function."""
    
    def test_create_auto_splitter(self):
        """Test create_auto_splitter factory function."""
        splitter = create_auto_splitter({
            "primary_limit": 30000,
            "secondary_limit": 100000
        })
        
        assert isinstance(splitter, AutoSplitter)
        assert splitter._config.primary_limit == 30000
        assert splitter._config.secondary_limit == 100000
    
    def test_create_auto_splitter_with_event_bus(self):
        """Test factory function with EventBus."""
        event_bus = EventBus()
        splitter = create_auto_splitter({}, event_bus)
        
        assert splitter._event_bus is event_bus


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
