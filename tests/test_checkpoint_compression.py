"""
Tests for ITEM-FEAT-72: Checkpoint Compression with Deduplication.

Tests cover:
- CheckpointCompressor class functionality
- CompressionStats dataclass
- Pattern detection and deduplication
- Compression/decompression with zstd/gzip
- EventBus integration
- Performance requirements
- Backward compatibility

Author: TITAN FUSE Team
Version: 3.7.0
"""

import json
import time
import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path

from src.state.checkpoint_compression import (
    CheckpointCompressor,
    CompressionStats,
    CompressionAlgorithm,
    PatternEntry,
    DeduplicationResult,
    compress_checkpoint,
    decompress_checkpoint,
    estimate_compression,
    COMPRESSION_MAGIC,
    COMPRESSION_VERSION,
    ZSTD_AVAILABLE
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def basic_config():
    """Basic configuration for testing."""
    return {
        "checkpoint": {
            "compression": {
                "enabled": True,
                "algorithm": "zstd",
                "level": 3,
                "deduplication": True,
                "min_size_for_dedup": 1024,
                "pattern_min_length": 50
            }
        }
    }


@pytest.fixture
def gzip_config():
    """Configuration using gzip algorithm."""
    return {
        "checkpoint": {
            "compression": {
                "enabled": True,
                "algorithm": "gzip",
                "level": 6,
                "deduplication": True,
                "min_size_for_dedup": 1024,
                "pattern_min_length": 50
            }
        }
    }


@pytest.fixture
def no_dedup_config():
    """Configuration with deduplication disabled."""
    return {
        "checkpoint": {
            "compression": {
                "enabled": True,
                "algorithm": "zstd",
                "level": 3,
                "deduplication": False,
                "min_size_for_dedup": 1024,
                "pattern_min_length": 50
            }
        }
    }


@pytest.fixture
def disabled_config():
    """Configuration with compression disabled."""
    return {
        "checkpoint": {
            "compression": {
                "enabled": False,
                "algorithm": "zstd",
                "level": 3,
                "deduplication": True
            }
        }
    }


@pytest.fixture
def small_checkpoint():
    """Small checkpoint data (< 1024 bytes)."""
    return {
        "session_id": "test-123",
        "status": "active",
        "count": 42
    }


@pytest.fixture
def large_checkpoint_with_duplicates():
    """Large checkpoint with repeated patterns for deduplication testing."""
    # Create a large string that repeats
    large_text = "This is a repeated pattern that should be deduplicated. " * 100
    
    return {
        "session_id": "test-session-456",
        "status": "active",
        "metadata": {
            "created": "2024-01-01T00:00:00Z",
            "updated": "2024-01-02T00:00:00Z",
            "version": "3.7.0"
        },
        "chunks": [
            {
                "id": "chunk-1",
                "content": large_text,
                "status": "processed"
            },
            {
                "id": "chunk-2",
                "content": large_text,  # Duplicate
                "status": "processed"
            },
            {
                "id": "chunk-3",
                "content": large_text,  # Duplicate
                "status": "pending"
            }
        ],
        "repeated_data": large_text,  # Another duplicate
        "another_repeat": large_text,  # Another duplicate
        "analysis": {
            "findings": [
                {"type": "issue", "description": large_text},
                {"type": "issue", "description": large_text}
            ]
        }
    }


@pytest.fixture
def large_checkpoint_unique():
    """Large checkpoint with unique data (no duplicates)."""
    return {
        "session_id": "unique-session-789",
        "status": "completed",
        "data": {
            f"item_{i}": f"Unique content for item {i} with some variation {i * 100}"
            for i in range(100)
        },
        "results": [
            {
                "id": i,
                "value": f"Result value {i}: " + "x" * 100,
                "metadata": {"index": i, "hash": f"hash_{i}"}
            }
            for i in range(50)
        ]
    }


@pytest.fixture
def mock_event_bus():
    """Mock EventBus for testing event emission."""
    mock = MagicMock()
    mock.emit = MagicMock()
    return mock


# =============================================================================
# CompressionStats Tests
# =============================================================================

class TestCompressionStats:
    """Tests for CompressionStats dataclass."""
    
    def test_compression_stats_creation(self):
        """Test CompressionStats can be created with all fields."""
        stats = CompressionStats(
            original_size=10000,
            compressed_size=3000,
            ratio=0.3,
            patterns_found=5,
            deduplication_savings=2000
        )
        
        assert stats.original_size == 10000
        assert stats.compressed_size == 3000
        assert stats.ratio == 0.3
        assert stats.patterns_found == 5
        assert stats.deduplication_savings == 2000
        assert stats.algorithm == "zstd"
        assert stats.deduplication_enabled is True
    
    def test_compression_stats_to_dict(self):
        """Test CompressionStats serialization to dictionary."""
        stats = CompressionStats(
            original_size=10000,
            compressed_size=3000,
            ratio=0.3,
            patterns_found=5,
            deduplication_savings=2000,
            compression_time_ms=50,
            algorithm="gzip"
        )
        
        result = stats.to_dict()
        
        assert result["original_size"] == 10000
        assert result["compressed_size"] == 3000
        assert result["ratio"] == 0.3
        assert result["patterns_found"] == 5
        assert result["deduplication_savings"] == 2000
        assert result["compression_time_ms"] == 50
        assert result["algorithm"] == "gzip"
    
    def test_compression_stats_from_dict(self):
        """Test CompressionStats deserialization from dictionary."""
        data = {
            "original_size": 10000,
            "compressed_size": 3000,
            "ratio": 0.3,
            "patterns_found": 5,
            "deduplication_savings": 2000,
            "compression_time_ms": 50,
            "algorithm": "gzip",
            "deduplication_enabled": False
        }
        
        stats = CompressionStats.from_dict(data)
        
        assert stats.original_size == 10000
        assert stats.compressed_size == 3000
        assert stats.ratio == 0.3
        assert stats.patterns_found == 5
        assert stats.deduplication_savings == 2000
        assert stats.compression_time_ms == 50
        assert stats.algorithm == "gzip"
        assert stats.deduplication_enabled is False


# =============================================================================
# CheckpointCompressor Basic Tests
# =============================================================================

class TestCheckpointCompressorBasic:
    """Basic tests for CheckpointCompressor class."""
    
    def test_compressor_initialization(self, basic_config):
        """Test CheckpointCompressor can be initialized."""
        compressor = CheckpointCompressor(basic_config)
        
        assert compressor.enabled is True
        # Falls back to gzip if zstd not available
        if ZSTD_AVAILABLE:
            assert compressor.algorithm == CompressionAlgorithm.ZSTD
        else:
            assert compressor.algorithm == CompressionAlgorithm.GZIP
        assert compressor.level == 3
        assert compressor.deduplication_enabled is True
        assert compressor.min_size_for_dedup == 1024
        assert compressor.pattern_min_length == 50
    
    def test_compressor_initialization_no_config(self):
        """Test CheckpointCompressor with no config uses defaults."""
        compressor = CheckpointCompressor()
        
        assert compressor.enabled is True
        # Falls back to gzip if zstd not available
        if ZSTD_AVAILABLE:
            assert compressor.algorithm == CompressionAlgorithm.ZSTD
        else:
            assert compressor.algorithm == CompressionAlgorithm.GZIP
    
    def test_compressor_initialization_gzip(self, gzip_config):
        """Test CheckpointCompressor with gzip algorithm."""
        compressor = CheckpointCompressor(gzip_config)
        
        assert compressor.algorithm == CompressionAlgorithm.GZIP
    
    def test_compressor_compression_disabled(self, disabled_config):
        """Test compressor with compression disabled."""
        compressor = CheckpointCompressor(disabled_config)
        
        assert compressor.enabled is False
    
    def test_get_stats_empty(self, basic_config):
        """Test get_stats returns default stats when no operations performed."""
        compressor = CheckpointCompressor(basic_config)
        
        stats = compressor.get_stats()
        
        assert stats.original_size == 0
        assert stats.compressed_size == 0
        assert stats.ratio == 1.0
    
    def test_get_summary_stats_empty(self, basic_config):
        """Test get_summary_stats with no operations."""
        compressor = CheckpointCompressor(basic_config)
        
        summary = compressor.get_summary_stats()
        
        assert summary["total_compressions"] == 0
        assert summary["total_decompressions"] == 0


# =============================================================================
# Compression Tests
# =============================================================================

class TestCompression:
    """Tests for compression functionality."""
    
    def test_compress_small_checkpoint(self, basic_config, small_checkpoint):
        """Test compressing a small checkpoint."""
        compressor = CheckpointCompressor(basic_config)
        
        compressed = compressor.compress(small_checkpoint)
        
        assert compressed is not None
        assert isinstance(compressed, bytes)
        assert compressed[:8] == COMPRESSION_MAGIC
    
    def test_compress_large_checkpoint_with_duplicates(
        self, basic_config, large_checkpoint_with_duplicates
    ):
        """Test compressing a checkpoint with duplicate patterns."""
        compressor = CheckpointCompressor(basic_config)
        
        compressed = compressor.compress(large_checkpoint_with_duplicates)
        
        assert compressed is not None
        assert isinstance(compressed, bytes)
        
        # Check stats
        stats = compressor.get_stats()
        assert stats.patterns_found > 0
        assert stats.deduplication_savings > 0
        assert stats.ratio < 1.0
    
    def test_compress_with_gzip(self, gzip_config, large_checkpoint_with_duplicates):
        """Test compression with gzip algorithm."""
        compressor = CheckpointCompressor(gzip_config)
        
        compressed = compressor.compress(large_checkpoint_with_duplicates)
        
        assert compressed is not None
        stats = compressor.get_stats()
        assert stats.algorithm == "gzip"
    
    def test_compress_without_dedup(
        self, no_dedup_config, large_checkpoint_with_duplicates
    ):
        """Test compression with deduplication disabled."""
        compressor = CheckpointCompressor(no_dedup_config)
        
        compressed = compressor.compress(large_checkpoint_with_duplicates)
        
        assert compressed is not None
        stats = compressor.get_stats()
        assert stats.patterns_found == 0
    
    def test_compress_disabled(self, disabled_config, large_checkpoint_with_duplicates):
        """Test that disabled compression returns uncompressed data."""
        compressor = CheckpointCompressor(disabled_config)
        
        compressed = compressor.compress(large_checkpoint_with_duplicates)
        
        # Should still have header, but not compressed
        assert compressed is not None
    
    def test_compress_invalid_input(self, basic_config):
        """Test compression with invalid input."""
        compressor = CheckpointCompressor(basic_config)
        
        with pytest.raises(ValueError, match="must be a dictionary"):
            compressor.compress("not a dict")
        
        with pytest.raises(ValueError, match="must be a dictionary"):
            compressor.compress([1, 2, 3])
    
    def test_stats_tracking(self, basic_config, small_checkpoint):
        """Test that stats are tracked correctly."""
        compressor = CheckpointCompressor(basic_config)
        
        # Perform multiple compressions
        for i in range(3):
            compressor.compress(small_checkpoint)
        
        all_stats = compressor.get_all_stats()
        assert len(all_stats) == 3
        
        summary = compressor.get_summary_stats()
        assert summary["total_compressions"] == 3


# =============================================================================
# Decompression Tests
# =============================================================================

class TestDecompression:
    """Tests for decompression functionality."""
    
    def test_decompress_small_checkpoint(self, basic_config, small_checkpoint):
        """Test decompressing a small checkpoint."""
        compressor = CheckpointCompressor(basic_config)
        
        compressed = compressor.compress(small_checkpoint)
        decompressed = compressor.decompress(compressed)
        
        assert decompressed == small_checkpoint
    
    def test_decompress_large_checkpoint_with_duplicates(
        self, basic_config, large_checkpoint_with_duplicates
    ):
        """Test decompressing a checkpoint with deduplicated patterns."""
        compressor = CheckpointCompressor(basic_config)
        
        compressed = compressor.compress(large_checkpoint_with_duplicates)
        decompressed = compressor.decompress(compressed)
        
        assert decompressed == large_checkpoint_with_duplicates
    
    def test_decompress_gzip_compressed(self, gzip_config, large_checkpoint_with_duplicates):
        """Test decompressing gzip-compressed data."""
        compressor = CheckpointCompressor(gzip_config)
        
        compressed = compressor.compress(large_checkpoint_with_duplicates)
        decompressed = compressor.decompress(compressed)
        
        assert decompressed == large_checkpoint_with_duplicates
    
    def test_decompress_no_dedup(self, no_dedup_config, large_checkpoint_with_duplicates):
        """Test decompressing data that wasn't deduplicated."""
        compressor = CheckpointCompressor(no_dedup_config)
        
        compressed = compressor.compress(large_checkpoint_with_duplicates)
        decompressed = compressor.decompress(compressed)
        
        assert decompressed == large_checkpoint_with_duplicates
    
    def test_decompress_empty_data(self, basic_config):
        """Test decompression with empty data."""
        compressor = CheckpointCompressor(basic_config)
        
        with pytest.raises(ValueError, match="cannot be empty"):
            compressor.decompress(b"")
    
    def test_decompress_invalid_data(self, basic_config):
        """Test decompression with invalid data."""
        compressor = CheckpointCompressor(basic_config)
        
        with pytest.raises(ValueError):
            compressor.decompress(b"invalid data that is not valid")
    
    def test_decompression_stats(self, basic_config, small_checkpoint):
        """Test that decompression is tracked."""
        compressor = CheckpointCompressor(basic_config)
        
        compressed = compressor.compress(small_checkpoint)
        compressor.decompress(compressed)
        
        summary = compressor.get_summary_stats()
        assert summary["total_decompressions"] == 1


# =============================================================================
# Round-trip Tests
# =============================================================================

class TestRoundTrip:
    """Tests for compression/decompression round-trip integrity."""
    
    def test_round_trip_small(self, basic_config, small_checkpoint):
        """Test round-trip for small checkpoint."""
        compressor = CheckpointCompressor(basic_config)
        
        compressed = compressor.compress(small_checkpoint)
        decompressed = compressor.decompress(compressed)
        
        assert decompressed == small_checkpoint
    
    def test_round_trip_large_with_duplicates(
        self, basic_config, large_checkpoint_with_duplicates
    ):
        """Test round-trip for large checkpoint with duplicates."""
        compressor = CheckpointCompressor(basic_config)
        
        compressed = compressor.compress(large_checkpoint_with_duplicates)
        decompressed = compressor.decompress(compressed)
        
        assert decompressed == large_checkpoint_with_duplicates
    
    def test_round_trip_large_unique(self, basic_config, large_checkpoint_unique):
        """Test round-trip for large checkpoint with unique data."""
        compressor = CheckpointCompressor(basic_config)
        
        compressed = compressor.compress(large_checkpoint_unique)
        decompressed = compressor.decompress(compressed)
        
        assert decompressed == large_checkpoint_unique
    
    def test_round_trip_gzip(self, gzip_config, large_checkpoint_with_duplicates):
        """Test round-trip with gzip compression."""
        compressor = CheckpointCompressor(gzip_config)
        
        compressed = compressor.compress(large_checkpoint_with_duplicates)
        decompressed = compressor.decompress(compressed)
        
        assert decompressed == large_checkpoint_with_duplicates
    
    def test_round_trip_no_dedup(self, no_dedup_config, large_checkpoint_with_duplicates):
        """Test round-trip without deduplication."""
        compressor = CheckpointCompressor(no_dedup_config)
        
        compressed = compressor.compress(large_checkpoint_with_duplicates)
        decompressed = compressor.decompress(compressed)
        
        assert decompressed == large_checkpoint_with_duplicates
    
    def test_round_trip_complex_nested(self, basic_config):
        """Test round-trip with complex nested structures."""
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "level4": {
                            "data": "deeply nested value" * 10,
                            "array": [1, 2, 3, {"nested": "value" * 10}]
                        }
                    }
                }
            },
            "array_of_objects": [
                {"id": i, "data": "item data " * 20}
                for i in range(20)
            ]
        }
        
        compressor = CheckpointCompressor(basic_config)
        compressed = compressor.compress(data)
        decompressed = compressor.decompress(compressed)
        
        assert decompressed == data


# =============================================================================
# Compression Ratio Tests
# =============================================================================

class TestCompressionRatio:
    """Tests for compression ratio requirements."""
    
    def test_compression_ratio_with_duplicates(
        self, basic_config, large_checkpoint_with_duplicates
    ):
        """Test that compression with dedup achieves >30% reduction."""
        compressor = CheckpointCompressor(basic_config)
        
        compressed = compressor.compress(large_checkpoint_with_duplicates)
        stats = compressor.get_stats()
        
        # Validation criteria: >30% reduction with dedup
        assert stats.ratio < 0.70, f"Compression ratio {stats.ratio} should be < 0.70"
        assert stats.patterns_found > 0
    
    def test_compression_ratio_unique_data(self, basic_config, large_checkpoint_unique):
        """Test compression ratio on unique data."""
        compressor = CheckpointCompressor(basic_config)
        
        compressed = compressor.compress(large_checkpoint_unique)
        stats = compressor.get_stats()
        
        # Even without dedup, zstd should compress JSON reasonably
        # JSON typically compresses to ~30-40% of original
        assert stats.ratio < 0.8, f"Compression ratio {stats.ratio} should be reasonable"
    
    def test_estimate_compression_ratio(self, basic_config, large_checkpoint_with_duplicates):
        """Test estimate_compression_ratio provides reasonable estimate."""
        compressor = CheckpointCompressor(basic_config)
        
        estimated = compressor.estimate_compression_ratio(large_checkpoint_with_duplicates)
        actual_compressed = compressor.compress(large_checkpoint_with_duplicates)
        actual_stats = compressor.get_stats()
        
        # Estimate should be in reasonable range
        # Allow some variance since estimate doesn't do full compression
        assert 0.0 < estimated < 1.0
        # The estimate should be in the ballpark
        assert abs(estimated - actual_stats.ratio) < 0.5


# =============================================================================
# Performance Tests
# =============================================================================

class TestPerformance:
    """Tests for performance requirements."""
    
    def test_compression_performance_1mb(self, basic_config):
        """Test compression of 1MB checkpoint is <100ms."""
        # Generate ~1MB of checkpoint data
        large_data = {
            "data": ["x" * 1000 for _ in range(1000)],  # ~1MB
            "metadata": {"size": "large"}
        }
        
        compressor = CheckpointCompressor(basic_config)
        
        start = time.time()
        compressed = compressor.compress(large_data)
        compression_time = (time.time() - start) * 1000  # ms
        
        # Validation criteria: <100ms for 1MB
        assert compression_time < 100, f"Compression took {compression_time}ms, should be <100ms"
        
        stats = compressor.get_stats()
        assert stats.compression_time_ms < 100
    
    def test_decompression_performance_1mb(self, basic_config):
        """Test decompression of 1MB checkpoint is <100ms."""
        # Generate ~1MB of checkpoint data
        large_data = {
            "data": ["x" * 1000 for _ in range(1000)],  # ~1MB
            "metadata": {"size": "large"}
        }
        
        compressor = CheckpointCompressor(basic_config)
        compressed = compressor.compress(large_data)
        
        start = time.time()
        decompressed = compressor.decompress(compressed)
        decompression_time = (time.time() - start) * 1000  # ms
        
        # Validation criteria: <100ms for 1MB
        assert decompression_time < 100, f"Decompression took {decompression_time}ms, should be <100ms"
        
        assert decompressed == large_data
    
    def test_compression_with_many_patterns(self, basic_config):
        """Test compression performance with many duplicate patterns."""
        # Create data with many duplicate patterns
        pattern = "This is a test pattern that will be repeated. " * 10
        data = {
            f"item_{i}": pattern
            for i in range(100)
        }
        
        compressor = CheckpointCompressor(basic_config)
        
        start = time.time()
        compressed = compressor.compress(data)
        compression_time = (time.time() - start) * 1000
        
        # Should still be fast even with pattern detection
        assert compression_time < 200, f"Compression with patterns took {compression_time}ms"
        
        stats = compressor.get_stats()
        assert stats.patterns_found > 0


# =============================================================================
# EventBus Integration Tests
# =============================================================================

class TestEventBusIntegration:
    """Tests for EventBus integration."""
    
    def test_emit_compressed_event(self, basic_config, small_checkpoint, mock_event_bus):
        """Test that CHECKPOINT_COMPRESSED event is emitted."""
        compressor = CheckpointCompressor(basic_config, event_bus=mock_event_bus)
        
        compressor.compress(small_checkpoint)
        
        # Event should be emitted
        mock_event_bus.emit.assert_called_once()
        event = mock_event_bus.emit.call_args[0][0]
        assert event.event_type == "CHECKPOINT_COMPRESSED"
        assert "original_size" in event.data
        assert "compressed_size" in event.data
    
    def test_emit_decompressed_event(self, basic_config, small_checkpoint, mock_event_bus):
        """Test that CHECKPOINT_DECOMPRESSED event is emitted."""
        compressor = CheckpointCompressor(basic_config, event_bus=mock_event_bus)
        
        compressed = compressor.compress(small_checkpoint)
        mock_event_bus.reset_mock()
        
        compressor.decompress(compressed)
        
        # Event should be emitted
        mock_event_bus.emit.assert_called_once()
        event = mock_event_bus.emit.call_args[0][0]
        assert event.event_type == "CHECKPOINT_DECOMPRESSED"
    
    def test_no_event_bus(self, basic_config, small_checkpoint):
        """Test compression works without EventBus."""
        compressor = CheckpointCompressor(basic_config, event_bus=None)
        
        # Should not raise
        compressed = compressor.compress(small_checkpoint)
        decompressed = compressor.decompress(compressed)
        
        assert decompressed == small_checkpoint
    
    def test_event_bus_failure_handled(self, basic_config, small_checkpoint):
        """Test that EventBus failures are handled gracefully."""
        failing_bus = MagicMock()
        failing_bus.emit.side_effect = Exception("EventBus failure")
        
        compressor = CheckpointCompressor(basic_config, event_bus=failing_bus)
        
        # Should not raise despite EventBus failure
        compressed = compressor.compress(small_checkpoint)
        assert compressed is not None


# =============================================================================
# Backward Compatibility Tests
# =============================================================================

class TestBackwardCompatibility:
    """Tests for backward compatibility."""
    
    def test_decompress_plain_json(self, basic_config, small_checkpoint):
        """Test decompression of plain JSON (no header)."""
        compressor = CheckpointCompressor(basic_config)
        
        # Create plain JSON without header
        plain_json = json.dumps(small_checkpoint).encode('utf-8')
        
        # Should be able to decompress
        decompressed = compressor.decompress(plain_json)
        assert decompressed == small_checkpoint
    
    def test_decompress_without_dedup_header(self, basic_config, small_checkpoint):
        """Test decompression of compressed data without dedup flag."""
        compressor = CheckpointCompressor(basic_config)
        
        # Compress with dedup disabled
        config_no_dedup = {
            "checkpoint": {
                "compression": {
                    "enabled": True,
                    "algorithm": "zstd",
                    "level": 3,
                    "deduplication": False,
                    "min_size_for_dedup": 1024
                }
            }
        }
        compressor_no_dedup = CheckpointCompressor(config_no_dedup)
        compressed = compressor_no_dedup.compress(small_checkpoint)
        
        # Should be able to decompress with different compressor
        decompressed = compressor.decompress(compressed)
        assert decompressed == small_checkpoint
    
    def test_different_compressor_instances(self, basic_config, large_checkpoint_with_duplicates):
        """Test that data compressed with one instance can be decompressed by another."""
        compressor1 = CheckpointCompressor(basic_config)
        compressor2 = CheckpointCompressor(basic_config)
        
        compressed = compressor1.compress(large_checkpoint_with_duplicates)
        decompressed = compressor2.decompress(compressed)
        
        assert decompressed == large_checkpoint_with_duplicates


# =============================================================================
# Pattern Detection Tests
# =============================================================================

class TestPatternDetection:
    """Tests for pattern detection functionality."""
    
    def test_find_string_patterns(self, basic_config):
        """Test detection of repeated strings."""
        compressor = CheckpointCompressor(basic_config)
        
        data = {
            "field1": "a" * 100,
            "field2": "a" * 100,  # Duplicate
            "field3": "a" * 100   # Duplicate
        }
        
        patterns = compressor._find_patterns(data)
        
        # Should find the repeated pattern
        duplicate_patterns = [p for p in patterns.values() if p.occurrence_count > 1]
        assert len(duplicate_patterns) > 0
    
    def test_find_array_patterns(self, basic_config):
        """Test detection of repeated arrays."""
        compressor = CheckpointCompressor(basic_config)
        
        repeated_array = [1, 2, 3, 4, 5] * 20  # Make it large enough
        
        data = {
            "arr1": repeated_array,
            "arr2": repeated_array,  # Duplicate
        }
        
        patterns = compressor._find_patterns(data)
        duplicate_patterns = [p for p in patterns.values() if p.occurrence_count > 1]
        assert len(duplicate_patterns) > 0
    
    def test_find_object_patterns(self, basic_config):
        """Test detection of repeated objects."""
        compressor = CheckpointCompressor(basic_config)
        
        repeated_obj = {
            "name": "test",
            "value": "x" * 100,
            "nested": {"deep": "value" * 20}
        }
        
        data = {
            "obj1": repeated_obj,
            "obj2": repeated_obj,  # Duplicate
            "obj3": repeated_obj   # Duplicate
        }
        
        patterns = compressor._find_patterns(data)
        duplicate_patterns = [p for p in patterns.values() if p.occurrence_count > 1]
        assert len(duplicate_patterns) > 0
    
    def test_no_patterns_in_small_data(self, basic_config):
        """Test that small patterns below threshold are not detected."""
        config = {
            "checkpoint": {
                "compression": {
                    "pattern_min_length": 100  # Higher threshold
                }
            }
        }
        compressor = CheckpointCompressor(config)
        
        data = {
            "field1": "small",
            "field2": "small"
        }
        
        patterns = compressor._find_patterns(data)
        # "small" is below pattern_min_length
        assert len(patterns) == 0
    
    def test_deduplicate_creates_pattern_table(self, basic_config):
        """Test that deduplication creates a pattern table."""
        compressor = CheckpointCompressor(basic_config)
        
        data = {
            "field1": "x" * 100,
            "field2": "x" * 100,
            "field3": "x" * 100
        }
        
        result = compressor._deduplicate(data)
        
        assert result.patterns_found > 0
        assert len(result.pattern_table) > 0
        assert result.savings_bytes > 0


# =============================================================================
# Convenience Function Tests
# =============================================================================

class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""
    
    def test_compress_checkpoint_function(self, large_checkpoint_with_duplicates):
        """Test compress_checkpoint convenience function."""
        compressed = compress_checkpoint(large_checkpoint_with_duplicates)
        
        assert compressed is not None
        assert isinstance(compressed, bytes)
    
    def test_decompress_checkpoint_function(self, large_checkpoint_with_duplicates):
        """Test decompress_checkpoint convenience function."""
        compressed = compress_checkpoint(large_checkpoint_with_duplicates)
        decompressed = decompress_checkpoint(compressed)
        
        assert decompressed == large_checkpoint_with_duplicates
    
    def test_estimate_compression_function(self, large_checkpoint_with_duplicates):
        """Test estimate_compression convenience function."""
        ratio = estimate_compression(large_checkpoint_with_duplicates)
        
        assert 0.0 < ratio < 1.0


# =============================================================================
# Edge Cases Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""
    
    def test_empty_dict(self, basic_config):
        """Test compression of empty dictionary."""
        compressor = CheckpointCompressor(basic_config)
        
        compressed = compressor.compress({})
        decompressed = compressor.decompress(compressed)
        
        assert decompressed == {}
    
    def test_dict_with_none_values(self, basic_config):
        """Test compression of dictionary with None values."""
        compressor = CheckpointCompressor(basic_config)
        
        data = {"field": None, "another": None}
        compressed = compressor.compress(data)
        decompressed = compressor.decompress(compressed)
        
        assert decompressed == data
    
    def test_dict_with_special_characters(self, basic_config):
        """Test compression of dictionary with special characters."""
        compressor = CheckpointCompressor(basic_config)
        
        data = {
            "unicode": "你好世界 🌍",
            "escape": "line1\nline2\ttab",
            "quotes": 'He said "hello"'
        }
        compressed = compressor.compress(data)
        decompressed = compressor.decompress(compressed)
        
        assert decompressed == data
    
    def test_deeply_nested_structure(self, basic_config):
        """Test compression of deeply nested structure."""
        compressor = CheckpointCompressor(basic_config)
        
        # Create deeply nested structure
        data = {"level": 0}
        current = data
        for i in range(1, 100):
            current["nested"] = {"level": i}
            current = current["nested"]
        
        compressed = compressor.compress(data)
        decompressed = compressor.decompress(compressed)
        
        assert decompressed == data
    
    def test_large_strings(self, basic_config):
        """Test compression with large string values."""
        compressor = CheckpointCompressor(basic_config)
        
        data = {
            "large_string": "x" * 100000,
            "another_large": "y" * 100000
        }
        
        compressed = compressor.compress(data)
        decompressed = compressor.decompress(compressed)
        
        assert decompressed == data
        stats = compressor.get_stats()
        assert stats.ratio < 0.1  # Should compress very well


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
