"""
Auto-Split on Secondary Chunk Limit for TITAN FUSE Protocol.

ITEM-FEAT-91: Automatic resplitting when chunks exceed limits during processing.

This module provides automatic chunk splitting functionality when chunks
exceed secondary limits mid-processing, preventing failures and ensuring
processing continues smoothly.

Author: TITAN FUSE Team
Version: 3.8.0
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, TYPE_CHECKING
import logging
import re

if TYPE_CHECKING:
    from ..events.event_bus import EventBus, Event


@dataclass
class SplitStats:
    """
    Statistics for auto-splitting operations.
    
    Tracks metrics about splitting operations for monitoring and optimization.
    """
    total_splits: int = 0
    total_chars_processed: int = 0
    average_chunk_size: float = 0.0
    max_chunk_seen: int = 0
    last_split_reason: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_splits": self.total_splits,
            "total_chars_processed": self.total_chars_processed,
            "average_chunk_size": self.average_chunk_size,
            "max_chunk_seen": self.max_chunk_seen,
            "last_split_reason": self.last_split_reason
        }
    
    def update_with_chunk(self, chunk_size: int) -> None:
        """Update stats with a new chunk size observation."""
        if chunk_size > self.max_chunk_seen:
            self.max_chunk_seen = chunk_size
        
        # Update rolling average
        total_chars = self.average_chunk_size * (self.total_splits if self.total_splits > 0 else 1)
        self.total_chars_processed += chunk_size
        count = self.total_splits + 1 if self.total_splits > 0 else 1
        self.average_chunk_size = total_chars / count if count > 0 else 0.0


class BoundaryType:
    """Types of semantic boundaries for splitting."""
    HEADING = "heading"
    FUNCTION = "function"
    CLASS = "class"
    PARAGRAPH = "paragraph"
    SECTION = "section"
    CODE_BLOCK = "code_block"


# Default boundary patterns for semantic splitting
DEFAULT_BOUNDARY_PATTERNS = {
    BoundaryType.HEADING: [
        r'^#{1,6}\s+.+$',           # Markdown headings
        r'^={3,}$',                  # Underline headings (===)
        r'^-{3,}$',                  # Underline headings (---)
    ],
    BoundaryType.FUNCTION: [
        r'^def\s+\w+\s*\([^)]*\)\s*:',           # Python function
        r'^function\s+\w+\s*\([^)]*\)\s*\{',     # JavaScript function
        r'^async\s+function\s+\w+\s*\([^)]*\)',  # Async JS function
        r'^const\s+\w+\s*=\s*\([^)]*\)\s*=>',    # Arrow function
        r'^func\s+\w+\s*\([^)]*\)',              # Go function
        r'^fn\s+\w+\s*\([^)]*\)',                # Rust function
        r'^public\s+\w+\s+\w+\s*\([^)]*\)',      # Java/C# method
        r'^private\s+\w+\s+\w+\s*\([^)]*\)',     # Private method
    ],
    BoundaryType.CLASS: [
        r'^class\s+\w+[\s(:{]',        # Python/JS class
        r'^public\s+class\s+\w+',      # Java/C# class
        r'^struct\s+\w+\s*\{',         # C/C++/Rust struct
        r'^interface\s+\w+\s*\{',      # Interface
    ],
    BoundaryType.PARAGRAPH: [
        r'\n\s*\n',  # Empty line between paragraphs
    ],
    BoundaryType.CODE_BLOCK: [
        r'^```\w*$',      # Markdown code block start/end
        r'^\s*```',       # Indented code block
    ],
}


@dataclass
class AutoSplitConfig:
    """Configuration for auto-splitting."""
    primary_limit: int = 50000          # Primary chunk size limit (chars)
    secondary_limit: int = 150000       # Force resplit above this (chars)
    enabled: bool = True
    max_recursion_depth: int = 3
    preserve_boundaries: bool = True
    boundary_types: List[str] = field(default_factory=lambda: [
        BoundaryType.HEADING,
        BoundaryType.FUNCTION,
        BoundaryType.CLASS,
        BoundaryType.PARAGRAPH
    ])
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "primary_limit": self.primary_limit,
            "secondary_limit": self.secondary_limit,
            "enabled": self.enabled,
            "max_recursion_depth": self.max_recursion_depth,
            "preserve_boundaries": self.preserve_boundaries,
            "boundary_types": self.boundary_types
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AutoSplitConfig':
        """Create config from dictionary."""
        return cls(
            primary_limit=data.get("primary_limit", 50000),
            secondary_limit=data.get("secondary_limit", 150000),
            enabled=data.get("enabled", True),
            max_recursion_depth=data.get("max_recursion_depth", 3),
            preserve_boundaries=data.get("preserve_boundaries", True),
            boundary_types=data.get("boundary_types", [
                BoundaryType.HEADING,
                BoundaryType.FUNCTION,
                BoundaryType.CLASS,
                BoundaryType.PARAGRAPH
            ])
        )


class AutoSplitter:
    """
    Automatic chunk splitter for handling oversized chunks.
    
    ITEM-FEAT-91: Provides automatic resplitting when chunks exceed
    secondary limits during processing.
    
    Features:
    - Character count check against configurable limits
    - Estimated token count validation (char_count // 4)
    - Semantic boundary detection for smart splitting
    - Recursive splitting for very large chunks
    - Zero data loss - all content preserved
    - EventBus integration for CHUNK_AUTO_SPLIT events
    
    Usage:
        config = {
            "primary_limit": 50000,
            "secondary_limit": 150000,
            "enabled": True
        }
        
        splitter = AutoSplitter(config, event_bus)
        
        if splitter.should_resplit(chunk, secondary_limit):
            sub_chunks = splitter.resplit(chunk, "Secondary limit exceeded")
    """
    
    def __init__(self, config: Dict[str, Any] = None, event_bus: 'EventBus' = None):
        """
        Initialize auto-splitter.
        
        Args:
            config: Configuration dictionary with auto-split settings
            event_bus: Optional EventBus for emitting CHUNK_AUTO_SPLIT events
        """
        self._config = AutoSplitConfig.from_dict(config or {})
        self._event_bus = event_bus
        self._stats = SplitStats()
        self._logger = logging.getLogger(__name__)
        
        # Compile boundary patterns for efficiency
        self._compiled_patterns: Dict[str, List[re.Pattern]] = {}
        for boundary_type in self._config.boundary_types:
            patterns = DEFAULT_BOUNDARY_PATTERNS.get(boundary_type, [])
            self._compiled_patterns[boundary_type] = [
                re.compile(p, re.MULTILINE) for p in patterns
            ]
        
        self._logger.info(
            f"AutoSplitter initialized: "
            f"primary_limit={self._config.primary_limit}, "
            f"secondary_limit={self._config.secondary_limit}, "
            f"enabled={self._config.enabled}"
        )
    
    def check_chunk_size(self, chunk: str) -> bool:
        """
        Check if chunk is within acceptable size limits.
        
        Args:
            chunk: The chunk to check
            
        Returns:
            True if chunk is within limits, False if it needs splitting
        """
        if not chunk:
            return True
        
        char_count = len(chunk)
        
        # Update stats
        self._stats.update_with_chunk(char_count)
        
        # Check against secondary limit
        if char_count > self._config.secondary_limit:
            self._logger.warning(
                f"Chunk size ({char_count}) exceeds secondary limit "
                f"({self._config.secondary_limit})"
            )
            return False
        
        return True
    
    def should_resplit(self, chunk: str, limit: int = None) -> bool:
        """
        Determine if a chunk needs resplitting.
        
        Checks both character count and estimated token count.
        
        Args:
            chunk: The chunk to check
            limit: Optional custom limit (uses secondary_limit if not provided)
            
        Returns:
            True if chunk should be resplit
        """
        if not self._config.enabled:
            return False
        
        if not chunk:
            return False
        
        char_count = len(chunk)
        effective_limit = limit or self._config.secondary_limit
        
        # Character count check
        if char_count > effective_limit:
            self._logger.info(
                f"Resplit needed: char_count ({char_count}) > limit ({effective_limit})"
            )
            return True
        
        # Estimated token count check (rough approximation: 1 token ≈ 4 chars)
        estimated_tokens = char_count // 4
        estimated_token_limit = effective_limit // 4
        
        if estimated_tokens > estimated_token_limit:
            self._logger.info(
                f"Resplit needed: estimated_tokens ({estimated_tokens}) > "
                f"limit ({estimated_token_limit})"
            )
            return True
        
        return False
    
    def resplit(self, chunk: str, reason: str, depth: int = 0) -> List[str]:
        """
        Resplit an oversized chunk into smaller sub-chunks.
        
        Attempts to split at semantic boundaries first, then falls back
        to size-based splitting if needed.
        
        Args:
            chunk: The chunk to resplit
            reason: Reason for resplitting (for logging and events)
            depth: Current recursion depth (for safety limit)
            
        Returns:
            List of sub-chunks that fit within limits
        """
        if not chunk:
            return []
        
        # Safety check for recursion depth
        if depth > self._config.max_recursion_depth:
            self._logger.warning(
                f"Max recursion depth ({self._config.max_recursion_depth}) reached, "
                f"forcing size-based split"
            )
            return self._force_split(chunk)
        
        # Update stats
        self._stats.total_splits += 1
        self._stats.last_split_reason = reason
        
        original_size = len(chunk)
        self._logger.info(
            f"Resplitting chunk: original_size={original_size}, reason={reason}, depth={depth}"
        )
        
        # Try semantic boundary splitting first
        if self._config.preserve_boundaries:
            sub_chunks = self._semantic_split(chunk)
            if sub_chunks and len(sub_chunks) > 1:
                # Validate all sub-chunks are within limits
                valid_chunks = []
                needs_further_split = False
                
                for sub in sub_chunks:
                    if self.should_resplit(sub):
                        needs_further_split = True
                        # Recursive split for oversized sub-chunks
                        sub_sub_chunks = self.resplit(sub, reason, depth + 1)
                        valid_chunks.extend(sub_sub_chunks)
                    else:
                        valid_chunks.append(sub)
                
                if valid_chunks and not needs_further_split:
                    self._emit_auto_split_event(original_size, len(valid_chunks), reason)
                    return valid_chunks
                
                if valid_chunks:
                    self._emit_auto_split_event(original_size, len(valid_chunks), reason)
                    return valid_chunks
        
        # Fallback to size-based splitting
        sub_chunks = self._size_based_split(chunk)
        self._emit_auto_split_event(original_size, len(sub_chunks), reason)
        
        return sub_chunks
    
    def _semantic_split(self, chunk: str) -> List[str]:
        """
        Split chunk at semantic boundaries.
        
        Finds the best boundary points and creates sub-chunks that
        preserve semantic meaning.
        
        Args:
            chunk: The chunk to split
            
        Returns:
            List of sub-chunks split at semantic boundaries
        """
        if not chunk:
            return []
        
        # Find all boundary positions
        boundaries: List[tuple] = []  # (position, boundary_type)
        
        for boundary_type, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                for match in pattern.finditer(chunk):
                    boundaries.append((match.start(), boundary_type))
        
        # Sort boundaries by position
        boundaries.sort(key=lambda x: x[0])
        
        if not boundaries:
            # No semantic boundaries found
            return [chunk] if chunk else []
        
        # Calculate target chunk size
        target_size = self._config.primary_limit
        
        # Create sub-chunks at boundaries
        sub_chunks = []
        current_start = 0
        
        for pos, boundary_type in boundaries:
            chunk_size = pos - current_start
            
            if chunk_size >= target_size:
                # Create chunk up to this boundary
                if pos > current_start:
                    sub_chunk = chunk[current_start:pos].strip()
                    if sub_chunk:
                        sub_chunks.append(sub_chunk)
                    current_start = pos
        
        # Add remaining content
        if current_start < len(chunk):
            remaining = chunk[current_start:].strip()
            if remaining:
                sub_chunks.append(remaining)
        
        # If no valid chunks were created, return original
        if not sub_chunks:
            return [chunk]
        
        return sub_chunks
    
    def _size_based_split(self, chunk: str) -> List[str]:
        """
        Split chunk by size without considering semantics.
        
        This is a fallback when semantic splitting fails or
        is disabled.
        
        Args:
            chunk: The chunk to split
            
        Returns:
            List of size-based sub-chunks
        """
        if not chunk:
            return []
        
        target_size = self._config.primary_limit
        sub_chunks = []
        
        # Try to split at newlines when possible
        lines = chunk.split('\n')
        
        # If no newlines, fall back to fixed-size split
        if len(lines) <= 1:
            for i in range(0, len(chunk), target_size):
                sub_chunks.append(chunk[i:i + target_size])
            return sub_chunks if sub_chunks else [chunk]
        
        current_chunk = []
        current_size = 0
        
        for line in lines:
            line_size = len(line) + 1  # +1 for newline
            
            if current_size + line_size > target_size and current_chunk:
                # Save current chunk
                sub_chunks.append('\n'.join(current_chunk))
                current_chunk = []
                current_size = 0
            
            current_chunk.append(line)
            current_size += line_size
        
        # Add remaining content
        if current_chunk:
            sub_chunks.append('\n'.join(current_chunk))
        
        return sub_chunks if sub_chunks else [chunk]
    
    def _force_split(self, chunk: str) -> List[str]:
        """
        Force split a chunk into fixed-size pieces.
        
        Used as last resort when recursive depth is exceeded.
        
        Args:
            chunk: The chunk to split
            
        Returns:
            List of fixed-size sub-chunks
        """
        if not chunk:
            return []
        
        target_size = self._config.primary_limit
        sub_chunks = []
        
        for i in range(0, len(chunk), target_size):
            sub_chunks.append(chunk[i:i + target_size])
        
        return sub_chunks
    
    def _emit_auto_split_event(
        self, original_size: int, new_chunks_count: int, reason: str
    ) -> None:
        """
        Emit CHUNK_AUTO_SPLIT event via EventBus.
        
        Args:
            original_size: Size of the original chunk
            new_chunks_count: Number of sub-chunks created
            reason: Reason for the split
        """
        if not self._event_bus:
            return
        
        try:
            # Use direct import to avoid relative import issues
            from events.event_bus import Event, EventSeverity
            
            event = Event(
                event_type="CHUNK_AUTO_SPLIT",
                data={
                    "original_size": original_size,
                    "new_chunks_count": new_chunks_count,
                    "reason": reason,
                    "config": self._config.to_dict(),
                    "stats": self._stats.to_dict()
                },
                severity=EventSeverity.WARN,
                source="AutoSplitter"
            )
            self._event_bus.emit(event)
        except ImportError:
            # Try relative import as fallback
            try:
                from ..events.event_bus import Event, EventSeverity
                
                event = Event(
                    event_type="CHUNK_AUTO_SPLIT",
                    data={
                        "original_size": original_size,
                        "new_chunks_count": new_chunks_count,
                        "reason": reason,
                        "config": self._config.to_dict(),
                        "stats": self._stats.to_dict()
                    },
                    severity=EventSeverity.WARN,
                    source="AutoSplitter"
                )
                self._event_bus.emit(event)
            except Exception as e:
                self._logger.warning(f"Failed to emit CHUNK_AUTO_SPLIT event: {e}")
        except Exception as e:
            self._logger.warning(f"Failed to emit CHUNK_AUTO_SPLIT event: {e}")
    
    def get_split_stats(self) -> SplitStats:
        """
        Get statistics about splitting operations.
        
        Returns:
            SplitStats with current statistics
        """
        return self._stats
    
    def get_config(self) -> AutoSplitConfig:
        """Get current configuration."""
        return self._config
    
    def update_config(self, config: Dict[str, Any]) -> None:
        """
        Update configuration.
        
        Args:
            config: Dictionary with new configuration values
        """
        if "primary_limit" in config:
            self._config.primary_limit = config["primary_limit"]
        if "secondary_limit" in config:
            self._config.secondary_limit = config["secondary_limit"]
        if "enabled" in config:
            self._config.enabled = config["enabled"]
        if "max_recursion_depth" in config:
            self._config.max_recursion_depth = config["max_recursion_depth"]
        if "preserve_boundaries" in config:
            self._config.preserve_boundaries = config["preserve_boundaries"]
        if "boundary_types" in config:
            self._config.boundary_types = config["boundary_types"]
        
        # Recompile patterns if boundary types changed
        if "boundary_types" in config:
            self._compiled_patterns.clear()
            for boundary_type in self._config.boundary_types:
                patterns = DEFAULT_BOUNDARY_PATTERNS.get(boundary_type, [])
                self._compiled_patterns[boundary_type] = [
                    re.compile(p, re.MULTILINE) for p in patterns
                ]
        
        self._logger.info(f"AutoSplitter config updated: {config}")
    
    def process_chunk(self, chunk: str) -> List[str]:
        """
        Process a chunk with automatic splitting if needed.
        
        This is a convenience method that combines check and resplit.
        
        Args:
            chunk: The chunk to process
            
        Returns:
            List of sub-chunks (original chunk if no split needed)
        """
        if not chunk:
            return []
        
        if not self._config.enabled:
            return [chunk]
        
        if not self.should_resplit(chunk):
            return [chunk]
        
        return self.resplit(chunk, "Secondary limit exceeded")
    
    def reset_stats(self) -> None:
        """Reset statistics to initial state."""
        self._stats = SplitStats()


def create_auto_splitter(
    config: Dict[str, Any] = None, 
    event_bus: 'EventBus' = None
) -> AutoSplitter:
    """
    Factory function to create an AutoSplitter.
    
    Args:
        config: Configuration dictionary
        event_bus: Optional EventBus for events
        
    Returns:
        AutoSplitter instance
    """
    return AutoSplitter(config, event_bus)
