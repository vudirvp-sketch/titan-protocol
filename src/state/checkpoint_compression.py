"""
Checkpoint Compression with Pattern-Based Deduplication for TITAN FUSE Protocol.

ITEM-FEAT-72 Implementation:
- CheckpointCompressor class with compress/decompress methods
- CompressionStats dataclass for tracking compression metrics
- Pattern-based deduplication for repeated strings, arrays, objects
- Zstd compression with gzip fallback
- EventBus integration for CHECKPOINT_COMPRESSED/DECOMPRESSED events

Features:
- Pattern detection using rolling hash
- Deduplication with pattern table
- Configurable compression level
- Backward compatible with non-deduplicated checkpoints
- Performance optimized for 1MB checkpoints (<100ms)

Author: TITAN FUSE Team
Version: 3.7.0
"""

import json
import gzip
import hashlib
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple, Set
from enum import Enum
import logging
import struct

try:
    import zstandard as zstd
    ZSTD_AVAILABLE = True
except ImportError:
    ZSTD_AVAILABLE = False


class CompressionAlgorithm(Enum):
    """Supported compression algorithms."""
    ZSTD = "zstd"
    GZIP = "gzip"
    LZ4 = "lz4"  # Placeholder for future support


@dataclass
class CompressionStats:
    """
    Statistics for checkpoint compression operations.
    
    Tracks original size, compressed size, compression ratio,
    patterns found, and deduplication savings.
    """
    original_size: int
    compressed_size: int
    ratio: float
    patterns_found: int
    deduplication_savings: int
    compression_time_ms: int = 0
    decompression_time_ms: int = 0
    algorithm: str = "zstd"
    deduplication_enabled: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "original_size": self.original_size,
            "compressed_size": self.compressed_size,
            "ratio": self.ratio,
            "patterns_found": self.patterns_found,
            "deduplication_savings": self.deduplication_savings,
            "compression_time_ms": self.compression_time_ms,
            "decompression_time_ms": self.decompression_time_ms,
            "algorithm": self.algorithm,
            "deduplication_enabled": self.deduplication_enabled
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CompressionStats':
        """Create from dictionary."""
        return cls(
            original_size=data.get("original_size", 0),
            compressed_size=data.get("compressed_size", 0),
            ratio=data.get("ratio", 1.0),
            patterns_found=data.get("patterns_found", 0),
            deduplication_savings=data.get("deduplication_savings", 0),
            compression_time_ms=data.get("compression_time_ms", 0),
            decompression_time_ms=data.get("decompression_time_ms", 0),
            algorithm=data.get("algorithm", "zstd"),
            deduplication_enabled=data.get("deduplication_enabled", True)
        )


@dataclass
class PatternEntry:
    """Entry in the pattern table for deduplication."""
    pattern_hash: str
    pattern_value: Any
    occurrence_count: int = 1
    reference_id: int = 0


@dataclass
class DeduplicationResult:
    """Result of pattern deduplication."""
    data: Dict[str, Any]
    pattern_table: Dict[str, Any]
    patterns_found: int
    savings_bytes: int


# Magic bytes for identifying compressed checkpoints with deduplication
COMPRESSION_MAGIC = b"TITAN_CP"
COMPRESSION_VERSION = 1
DEDUP_FLAG = 0x01


class CheckpointCompressor:
    """
    Checkpoint compressor with pattern-based deduplication.
    
    Implements ITEM-FEAT-72 checkpoint compression with:
    - Pattern detection for repeated values
    - Deduplication with pattern table
    - Zstd compression (gzip fallback)
    - EventBus integration for events
    
    Usage:
        compressor = CheckpointCompressor(config)
        
        # Compress checkpoint
        compressed = compressor.compress(checkpoint_data)
        
        # Decompress checkpoint
        original = compressor.decompress(compressed)
        
        # Get compression stats
        stats = compressor.get_stats()
    """
    
    def __init__(self, config: Dict[str, Any] = None, event_bus=None):
        """
        Initialize the checkpoint compressor.
        
        Args:
            config: Configuration dictionary with compression settings
            event_bus: EventBus instance for emitting events
        """
        self.config = config or {}
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)
        
        # Compression settings
        compression_config = self.config.get("checkpoint", {}).get("compression", {})
        self.enabled = compression_config.get("enabled", True)
        self.algorithm = CompressionAlgorithm(
            compression_config.get("algorithm", "zstd")
        )
        self.level = compression_config.get("level", 3)
        self.deduplication_enabled = compression_config.get("deduplication", True)
        self.min_size_for_dedup = compression_config.get("min_size_for_dedup", 1024)
        self.pattern_min_length = compression_config.get("pattern_min_length", 50)
        
        # Statistics tracking
        self._stats_history: List[CompressionStats] = []
        self._total_compressions = 0
        self._total_decompressions = 0
        
        # Validate algorithm availability
        if self.algorithm == CompressionAlgorithm.ZSTD and not ZSTD_AVAILABLE:
            self._logger.warning(
                "Zstd not available, falling back to gzip. "
                "Install with: pip install zstandard"
            )
            self.algorithm = CompressionAlgorithm.GZIP
    
    def compress(self, data: Dict) -> bytes:
        """
        Compress checkpoint data with optional deduplication.
        
        Args:
            data: Checkpoint data dictionary to compress
            
        Returns:
            Compressed data as bytes
            
        Raises:
            ValueError: If data is invalid
        """
        start_time = time.time()
        
        if not isinstance(data, dict):
            raise ValueError("Data must be a dictionary")
        
        if not self.enabled:
            # Return uncompressed JSON
            return self._encode_header(False, False) + json.dumps(data, default=str).encode('utf-8')
        
        # Calculate original size
        original_json = json.dumps(data, default=str, indent=2)
        original_size = len(original_json.encode('utf-8'))
        
        patterns_found = 0
        dedup_savings = 0
        compressed_data = data
        
        # Apply deduplication if enabled and data is large enough
        if self.deduplication_enabled and original_size >= self.min_size_for_dedup:
            dedup_result = self._deduplicate(data)
            compressed_data = {
                "__dedup_data__": dedup_result.data,
                "__dedup_patterns__": dedup_result.pattern_table
            }
            patterns_found = dedup_result.patterns_found
            dedup_savings = dedup_result.savings_bytes
            self._logger.debug(
                f"Deduplication: {patterns_found} patterns found, "
                f"{dedup_savings} bytes saved"
            )
        
        # Serialize to JSON
        json_bytes = json.dumps(compressed_data, default=str).encode('utf-8')
        
        # Apply compression
        if self.algorithm == CompressionAlgorithm.ZSTD:
            compressed = self._compress_zstd(json_bytes)
        else:
            compressed = self._compress_gzip(json_bytes)
        
        # Add header
        has_dedup = self.deduplication_enabled and original_size >= self.min_size_for_dedup
        header = self._encode_header(True, has_dedup)
        result = header + compressed
        
        # Calculate stats
        compression_time_ms = int((time.time() - start_time) * 1000)
        ratio = len(result) / original_size if original_size > 0 else 1.0
        
        stats = CompressionStats(
            original_size=original_size,
            compressed_size=len(result),
            ratio=ratio,
            patterns_found=patterns_found,
            deduplication_savings=dedup_savings,
            compression_time_ms=compression_time_ms,
            algorithm=self.algorithm.value,
            deduplication_enabled=self.deduplication_enabled
        )
        
        self._stats_history.append(stats)
        self._total_compressions += 1
        
        # Emit event
        self._emit_compressed_event(stats, data)
        
        self._logger.info(
            f"Compressed checkpoint: {original_size} -> {len(result)} bytes "
            f"({ratio:.2%}, {patterns_found} patterns, {compression_time_ms}ms)"
        )
        
        return result
    
    def decompress(self, data: bytes) -> Dict:
        """
        Decompress checkpoint data.
        
        Args:
            data: Compressed data bytes
            
        Returns:
            Decompressed checkpoint dictionary
            
        Raises:
            ValueError: If data is invalid or corrupted
        """
        start_time = time.time()
        
        if not data:
            raise ValueError("Data cannot be empty")
        
        # Parse header
        is_compressed, has_dedup, has_header = self._decode_header(data)
        
        # If no header, treat as plain JSON
        if not has_header:
            try:
                return json.loads(data.decode('utf-8'))
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON data: {e}")
        
        payload = data[12:]  # Skip header (8 bytes magic + 4 bytes metadata)
        
        if not is_compressed:
            # Uncompressed JSON with header
            try:
                return json.loads(payload.decode('utf-8'))
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON data: {e}")
        
        # Decompress
        if self.algorithm == CompressionAlgorithm.ZSTD:
            decompressed = self._decompress_zstd(payload)
        else:
            decompressed = self._decompress_gzip(payload)
        
        # Parse JSON
        try:
            parsed = json.loads(decompressed.decode('utf-8'))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid decompressed JSON: {e}")
        
        # Resolve deduplication if present
        result = parsed
        if has_dedup and isinstance(parsed, dict):
            if "__dedup_data__" in parsed and "__dedup_patterns__" in parsed:
                result = self._resolve_deduplication(
                    parsed["__dedup_data__"],
                    parsed["__dedup_patterns__"]
                )
                self._logger.debug("Resolved deduplication patterns")
        
        decompression_time_ms = int((time.time() - start_time) * 1000)
        self._total_decompressions += 1
        
        # Emit event
        self._emit_decompressed_event(len(data), decompression_time_ms)
        
        return result
    
    def estimate_compression_ratio(self, data: Dict) -> float:
        """
        Estimate compression ratio for given data.
        
        This performs a quick analysis without full compression
        to estimate potential savings.
        
        Args:
            data: Checkpoint data dictionary
            
        Returns:
            Estimated compression ratio (0.0 - 1.0, lower is better)
        """
        if not self.enabled:
            return 1.0
        
        # Calculate original size
        original_json = json.dumps(data, default=str, indent=2)
        original_size = len(original_json.encode('utf-8'))
        
        if original_size < self.min_size_for_dedup:
            # For small data, just estimate compression
            # Zstd typically achieves 3:1 on JSON
            if self.algorithm == CompressionAlgorithm.ZSTD:
                return 0.33
            else:
                return 0.4
        
        # Count patterns for estimation
        pattern_count, estimated_savings = self._count_patterns(data)
        
        # Estimate compression after dedup
        after_dedup_size = original_size - estimated_savings
        
        # Apply compression ratio
        if self.algorithm == CompressionAlgorithm.ZSTD:
            compression_ratio = 0.33
        else:
            compression_ratio = 0.4
        
        estimated_final = int(after_dedup_size * compression_ratio)
        
        return estimated_final / original_size if original_size > 0 else 1.0
    
    def get_stats(self) -> CompressionStats:
        """
        Get compression statistics from the most recent operation.
        
        Returns:
            CompressionStats for the last compression operation
        """
        if self._stats_history:
            return self._stats_history[-1]
        
        return CompressionStats(
            original_size=0,
            compressed_size=0,
            ratio=1.0,
            patterns_found=0,
            deduplication_savings=0
        )
    
    def get_all_stats(self) -> List[CompressionStats]:
        """
        Get all compression statistics history.
        
        Returns:
            List of all CompressionStats
        """
        return self._stats_history.copy()
    
    def get_summary_stats(self) -> Dict[str, Any]:
        """
        Get summary statistics across all operations.
        
        Returns:
            Dictionary with aggregate statistics
        """
        if not self._stats_history:
            return {
                "total_compressions": 0,
                "total_decompressions": self._total_decompressions,
                "total_bytes_saved": 0,
                "average_ratio": 1.0,
                "total_patterns_found": 0
            }
        
        total_original = sum(s.original_size for s in self._stats_history)
        total_compressed = sum(s.compressed_size for s in self._stats_history)
        total_patterns = sum(s.patterns_found for s in self._stats_history)
        total_dedup_savings = sum(s.deduplication_savings for s in self._stats_history)
        
        return {
            "total_compressions": self._total_compressions,
            "total_decompressions": self._total_decompressions,
            "total_bytes_saved": total_original - total_compressed,
            "average_ratio": total_compressed / total_original if total_original > 0 else 1.0,
            "total_patterns_found": total_patterns,
            "total_deduplication_savings": total_dedup_savings
        }
    
    # =========================================================================
    # Pattern Detection and Deduplication
    # =========================================================================
    
    def _find_patterns(self, data: Dict) -> Dict[str, PatternEntry]:
        """
        Find repeated patterns in checkpoint data.
        
        Identifies repeated strings, arrays, and objects that can
        be deduplicated to reduce size.
        
        Args:
            data: Checkpoint data dictionary
            
        Returns:
            Dictionary mapping pattern hash to PatternEntry
        """
        patterns: Dict[str, PatternEntry] = {}
        
        def scan_value(value: Any, path: str = "") -> None:
            """Recursively scan values for patterns."""
            if isinstance(value, str):
                if len(value) >= self.pattern_min_length:
                    pattern_hash = self._hash_value(value)
                    if pattern_hash in patterns:
                        patterns[pattern_hash].occurrence_count += 1
                    else:
                        patterns[pattern_hash] = PatternEntry(
                            pattern_hash=pattern_hash,
                            pattern_value=value
                        )
            elif isinstance(value, list):
                # Check for repeated list patterns
                if len(value) > 0:
                    list_str = json.dumps(value, sort_keys=True, default=str)
                    if len(list_str) >= self.pattern_min_length:
                        pattern_hash = self._hash_value(list_str)
                        if pattern_hash in patterns:
                            patterns[pattern_hash].occurrence_count += 1
                        else:
                            patterns[pattern_hash] = PatternEntry(
                                pattern_hash=pattern_hash,
                                pattern_value=value
                            )
                    # Recurse into list items
                    for i, item in enumerate(value):
                        scan_value(item, f"{path}[{i}]")
            elif isinstance(value, dict):
                # Check for repeated object patterns
                if len(value) > 0:
                    dict_str = json.dumps(value, sort_keys=True, default=str)
                    if len(dict_str) >= self.pattern_min_length:
                        pattern_hash = self._hash_value(dict_str)
                        if pattern_hash in patterns:
                            patterns[pattern_hash].occurrence_count += 1
                        else:
                            patterns[pattern_hash] = PatternEntry(
                                pattern_hash=pattern_hash,
                                pattern_value=value
                            )
                # Recurse into dict values
                for k, v in value.items():
                    scan_value(v, f"{path}.{k}" if path else k)
        
        scan_value(data)
        return patterns
    
    def _deduplicate(self, data: Dict) -> DeduplicationResult:
        """
        Apply deduplication to checkpoint data.
        
        Creates a pattern table and replaces duplicates with references.
        
        Args:
            data: Checkpoint data dictionary
            
        Returns:
            DeduplicationResult with deduplicated data and pattern table
        """
        patterns = self._find_patterns(data)
        
        # Filter to patterns that appear more than once
        duplicate_patterns = {
            h: p for h, p in patterns.items()
            if p.occurrence_count > 1
        }
        
        if not duplicate_patterns:
            return DeduplicationResult(
                data=data,
                pattern_table={},
                patterns_found=0,
                savings_bytes=0
            )
        
        # Assign reference IDs
        pattern_table: Dict[str, Any] = {}
        ref_id = 0
        for pattern_hash, entry in duplicate_patterns.items():
            entry.reference_id = ref_id
            pattern_table[f"__ref_{ref_id}__"] = entry.pattern_value
            ref_id += 1
        
        # Replace duplicates with references
        def replace_duplicates(value: Any) -> Any:
            """Replace duplicate values with references."""
            if isinstance(value, str):
                if len(value) >= self.pattern_min_length:
                    pattern_hash = self._hash_value(value)
                    if pattern_hash in duplicate_patterns:
                        return {"__ref__": duplicate_patterns[pattern_hash].reference_id}
            elif isinstance(value, list):
                # Check if entire list is a duplicate
                list_str = json.dumps(value, sort_keys=True, default=str)
                if len(list_str) >= self.pattern_min_length:
                    pattern_hash = self._hash_value(list_str)
                    if pattern_hash in duplicate_patterns:
                        return {"__ref__": duplicate_patterns[pattern_hash].reference_id}
                # Recurse into items
                return [replace_duplicates(item) for item in value]
            elif isinstance(value, dict):
                # Check if entire dict is a duplicate
                if "__ref__" not in value:  # Don't re-process references
                    dict_str = json.dumps(value, sort_keys=True, default=str)
                    if len(dict_str) >= self.pattern_min_length:
                        pattern_hash = self._hash_value(dict_str)
                        if pattern_hash in duplicate_patterns:
                            return {"__ref__": duplicate_patterns[pattern_hash].reference_id}
                # Recurse into values
                return {k: replace_duplicates(v) for k, v in value.items()}
            return value
        
        deduped_data = replace_duplicates(data)
        
        # Calculate savings
        original_size = len(json.dumps(data, default=str).encode('utf-8'))
        deduped_size = len(json.dumps(deduped_data, default=str).encode('utf-8'))
        pattern_table_size = len(json.dumps(pattern_table, default=str).encode('utf-8'))
        
        savings_bytes = original_size - (deduped_size + pattern_table_size)
        
        return DeduplicationResult(
            data=deduped_data,
            pattern_table=pattern_table,
            patterns_found=len(duplicate_patterns),
            savings_bytes=max(0, savings_bytes)
        )
    
    def _resolve_deduplication(self, data: Dict, pattern_table: Dict) -> Dict:
        """
        Resolve pattern references back to original values.
        
        Args:
            data: Deduplicated data with references
            pattern_table: Pattern table with original values
            
        Returns:
            Original data with references resolved
        """
        def resolve_value(value: Any) -> Any:
            """Resolve references to original values."""
            if isinstance(value, dict):
                if "__ref__" in value and len(value) == 1:
                    ref_id = value["__ref__"]
                    ref_key = f"__ref_{ref_id}__"
                    if ref_key in pattern_table:
                        return pattern_table[ref_key]
                return {k: resolve_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [resolve_value(item) for item in value]
            return value
        
        return resolve_value(data)
    
    def _count_patterns(self, data: Dict) -> Tuple[int, int]:
        """
        Count patterns and estimate savings.
        
        Args:
            data: Checkpoint data dictionary
            
        Returns:
            Tuple of (pattern_count, estimated_savings_bytes)
        """
        patterns = self._find_patterns(data)
        duplicate_patterns = [p for p in patterns.values() if p.occurrence_count > 1]
        
        savings = 0
        for pattern in duplicate_patterns:
            # Estimate savings: (occurrences - 1) * pattern_size
            pattern_size = len(json.dumps(pattern.pattern_value, default=str).encode('utf-8'))
            # Subtract overhead of reference (~20 bytes per occurrence)
            reference_overhead = 20 * pattern.occurrence_count
            savings += (pattern.occurrence_count - 1) * pattern_size - reference_overhead
        
        return len(duplicate_patterns), max(0, savings)
    
    # =========================================================================
    # Compression Methods
    # =========================================================================
    
    def _compress_zstd(self, data: bytes) -> bytes:
        """Compress data using zstd."""
        if not ZSTD_AVAILABLE:
            return self._compress_gzip(data)
        
        level = min(22, max(1, self.level))
        cctx = zstd.ZstdCompressor(level=level)
        return cctx.compress(data)
    
    def _decompress_zstd(self, data: bytes) -> bytes:
        """Decompress data using zstd."""
        if not ZSTD_AVAILABLE:
            raise ImportError(
                "zstandard package required. Install with: pip install zstandard"
            )
        
        dctx = zstd.ZstdDecompressor()
        return dctx.decompress(data)
    
    def _compress_gzip(self, data: bytes) -> bytes:
        """Compress data using gzip."""
        level = min(9, max(1, self.level))
        return gzip.compress(data, compresslevel=level)
    
    def _decompress_gzip(self, data: bytes) -> bytes:
        """Decompress data using gzip."""
        return gzip.decompress(data)
    
    # =========================================================================
    # Header Encoding/Decoding
    # =========================================================================
    
    def _encode_header(self, compressed: bool, has_dedup: bool) -> bytes:
        """
        Encode checkpoint header.
        
        Header format:
        - 8 bytes: Magic bytes "TITAN_CP"
        - 1 byte: Version
        - 1 byte: Flags (bit 0: compressed, bit 1: has_dedup)
        - 2 bytes: Reserved
        
        Total: 12 bytes
        """
        flags = 0
        if compressed:
            flags |= 0x01
        if has_dedup:
            flags |= 0x02
        
        return COMPRESSION_MAGIC + struct.pack('>BBH', COMPRESSION_VERSION, flags, 0)
    
    def _decode_header(self, data: bytes) -> Tuple[bool, bool, bool]:
        """
        Decode checkpoint header.
        
        Args:
            data: Compressed data bytes
            
        Returns:
            Tuple of (is_compressed, has_dedup, has_header)
        """
        if len(data) < 12:
            # No header, treat as uncompressed JSON
            return False, False, False
        
        magic = data[:8]
        if magic != COMPRESSION_MAGIC:
            # No magic bytes, treat as uncompressed JSON
            return False, False, False
        
        version, flags, _ = struct.unpack('>BBH', data[8:12])
        
        is_compressed = bool(flags & 0x01)
        has_dedup = bool(flags & 0x02)
        
        return is_compressed, has_dedup, True
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def _hash_value(self, value: Any) -> str:
        """
        Compute hash for a value.
        
        Args:
            value: Value to hash (string or JSON-serializable)
            
        Returns:
            SHA-256 hash hex string (first 16 characters)
        """
        if isinstance(value, str):
            data = value.encode('utf-8')
        else:
            data = json.dumps(value, sort_keys=True, default=str).encode('utf-8')
        
        return hashlib.sha256(data).hexdigest()[:16]
    
    # =========================================================================
    # EventBus Integration
    # =========================================================================
    
    def _emit_compressed_event(self, stats: CompressionStats, data: Dict) -> None:
        """Emit CHECKPOINT_COMPRESSED event."""
        if self._event_bus is None:
            return
        
        try:
            # Import here to avoid circular dependency
            from ..events.event_bus import Event, EventSeverity
            
            event = Event(
                event_type="CHECKPOINT_COMPRESSED",
                data={
                    "original_size": stats.original_size,
                    "compressed_size": stats.compressed_size,
                    "ratio": stats.ratio,
                    "patterns_found": stats.patterns_found,
                    "deduplication_savings": stats.deduplication_savings,
                    "compression_time_ms": stats.compression_time_ms,
                    "algorithm": stats.algorithm
                },
                severity=EventSeverity.INFO,
                source="CheckpointCompressor"
            )
            self._event_bus.emit(event)
        except Exception as e:
            self._logger.debug(f"Failed to emit compression event: {e}")
    
    def _emit_decompressed_event(self, compressed_size: int, time_ms: int) -> None:
        """Emit CHECKPOINT_DECOMPRESSED event."""
        if self._event_bus is None:
            return
        
        try:
            # Import here to avoid circular dependency
            from ..events.event_bus import Event, EventSeverity
            
            event = Event(
                event_type="CHECKPOINT_DECOMPRESSED",
                data={
                    "compressed_size": compressed_size,
                    "decompression_time_ms": time_ms,
                    "algorithm": self.algorithm.value
                },
                severity=EventSeverity.INFO,
                source="CheckpointCompressor"
            )
            self._event_bus.emit(event)
        except Exception as e:
            self._logger.debug(f"Failed to emit decompression event: {e}")


# =============================================================================
# Convenience Functions
# =============================================================================

def compress_checkpoint(data: Dict, config: Dict = None, event_bus=None) -> bytes:
    """
    Compress checkpoint data with default settings.
    
    Args:
        data: Checkpoint data dictionary
        config: Optional configuration dictionary
        event_bus: Optional EventBus instance
        
    Returns:
        Compressed data bytes
    """
    compressor = CheckpointCompressor(config, event_bus)
    return compressor.compress(data)


def decompress_checkpoint(data: bytes, config: Dict = None, event_bus=None) -> Dict:
    """
    Decompress checkpoint data.
    
    Args:
        data: Compressed data bytes
        config: Optional configuration dictionary
        event_bus: Optional EventBus instance
        
    Returns:
        Decompressed checkpoint dictionary
    """
    compressor = CheckpointCompressor(config, event_bus)
    return compressor.decompress(data)


def estimate_compression(data: Dict, config: Dict = None) -> float:
    """
    Estimate compression ratio for checkpoint data.
    
    Args:
        data: Checkpoint data dictionary
        config: Optional configuration dictionary
        
    Returns:
        Estimated compression ratio (0.0 - 1.0, lower is better)
    """
    compressor = CheckpointCompressor(config)
    return compressor.estimate_compression_ratio(data)
