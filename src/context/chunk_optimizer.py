"""
Chunk Size Optimizer for TITAN FUSE Protocol.

ITEM-CONFLICT-C: Implements bidirectional chunk size optimization
that can both shrink and grow chunks based on file size.

Author: TITAN FUSE Team
Version: 3.4.0
"""

from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging


class OptimizationDirection(Enum):
    """Direction of chunk size optimization."""
    SHRINK = "shrink"
    GROW = "grow"
    NONE = "none"


@dataclass
class ChunkConfig:
    """Chunk size configuration."""
    min_chunk_size: int
    max_chunk_size: int
    shrink_threshold: int
    grow_threshold: int
    default_chunk_size: int
    
    def to_dict(self) -> Dict:
        return {
            "min_chunk_size": self.min_chunk_size,
            "max_chunk_size": self.max_chunk_size,
            "shrink_threshold": self.shrink_threshold,
            "grow_threshold": self.grow_threshold,
            "default_chunk_size": self.default_chunk_size
        }


class ChunkOptimizer:
    """
    Bidirectional chunk size optimizer.
    
    ITEM-CONFLICT-C: Chunk size bidirectional optimization.
    
    Optimizes chunk size based on file characteristics:
    - Large files (> shrink_threshold): Reduce chunk size for better processing
    - Small files (< grow_threshold): Increase chunk size for efficiency
    - Medium files: Use default chunk size
    
    This ensures efficient processing for all file sizes, unlike
    one-directional optimization that only shrinks chunks.
    
    Usage:
        config = {
            "min_chunk_size": 1000,
            "max_chunk_size": 50000,
            "shrink_threshold": 30000,
            "grow_threshold": 5000,
            "default_chunk_size": 1500
        }
        
        optimizer = ChunkOptimizer(config)
        
        # Optimize for a file
        optimal_size = optimizer.optimize(
            current_size=1500,
            file_size=2500,  # Small file
            line_count=100
        )
        # Returns 3000 (doubled for efficiency)
    """
    
    DEFAULT_CONFIG = ChunkConfig(
        min_chunk_size=1000,
        max_chunk_size=50000,
        shrink_threshold=30000,
        grow_threshold=5000,
        default_chunk_size=1500
    )
    
    def __init__(self, config: Dict = None):
        """
        Initialize chunk optimizer.
        
        Args:
            config: Chunking configuration dictionary
        """
        if config is None:
            self._config = self.DEFAULT_CONFIG
        else:
            self._config = ChunkConfig(
                min_chunk_size=config.get("min_chunk_size", self.DEFAULT_CONFIG.min_chunk_size),
                max_chunk_size=config.get("max_chunk_size", self.DEFAULT_CONFIG.max_chunk_size),
                shrink_threshold=config.get("shrink_threshold", self.DEFAULT_CONFIG.shrink_threshold),
                grow_threshold=config.get("grow_threshold", self.DEFAULT_CONFIG.grow_threshold),
                default_chunk_size=config.get("default_chunk_size", self.DEFAULT_CONFIG.default_chunk_size)
            )
        
        self._logger = logging.getLogger(__name__)
        
        self._logger.info(
            f"ChunkOptimizer initialized: "
            f"min={self._config.min_chunk_size}, "
            f"max={self._config.max_chunk_size}, "
            f"shrink_threshold={self._config.shrink_threshold}, "
            f"grow_threshold={self._config.grow_threshold}"
        )
    
    def optimize(self, current_size: int, file_size: int, 
                 line_count: int = 0) -> int:
        """
        Calculate optimal chunk size for a file.
        
        Args:
            current_size: Current chunk size
            file_size: Size of the file in bytes
            line_count: Number of lines in the file (optional)
            
        Returns:
            Optimal chunk size
        """
        direction, optimal_size = self._calculate_optimal_size(
            current_size, file_size, line_count
        )
        
        if direction != OptimizationDirection.NONE:
            self._logger.info(
                f"Chunk optimization: {direction.value} "
                f"(file_size={file_size}, {current_size} -> {optimal_size})"
            )
        
        return optimal_size
    
    def _calculate_optimal_size(
        self, current_size: int, file_size: int, line_count: int
    ) -> Tuple[OptimizationDirection, int]:
        """
        Calculate optimal size and direction.
        
        Returns:
            Tuple of (direction, optimal_size)
        """
        # Large files: shrink chunks
        if file_size > self._config.shrink_threshold:
            new_size = max(
                self._config.min_chunk_size,
                current_size // 2
            )
            return OptimizationDirection.SHRINK, new_size
        
        # Small files: grow chunks
        if file_size < self._config.grow_threshold:
            new_size = min(
                self._config.max_chunk_size,
                current_size * 2
            )
            return OptimizationDirection.GROW, new_size
        
        # Medium files: no change
        return OptimizationDirection.NONE, current_size
    
    def get_optimization_info(self, file_size: int, line_count: int = 0) -> Dict:
        """
        Get detailed optimization information for a file.
        
        Args:
            file_size: Size of the file in bytes
            line_count: Number of lines in the file
            
        Returns:
            Dict with optimization details
        """
        current = self._config.default_chunk_size
        direction, optimal = self._calculate_optimal_size(
            current, file_size, line_count
        )
        
        return {
            "file_size": file_size,
            "line_count": line_count,
            "current_chunk_size": current,
            "optimal_chunk_size": optimal,
            "direction": direction.value,
            "min_chunk_size": self._config.min_chunk_size,
            "max_chunk_size": self._config.max_chunk_size,
            "shrink_threshold": self._config.shrink_threshold,
            "grow_threshold": self._config.grow_threshold
        }
    
    def get_config(self) -> ChunkConfig:
        """Get current configuration."""
        return self._config
    
    def update_config(self, config: Dict) -> None:
        """Update configuration."""
        if "min_chunk_size" in config:
            self._config.min_chunk_size = config["min_chunk_size"]
        if "max_chunk_size" in config:
            self._config.max_chunk_size = config["max_chunk_size"]
        if "shrink_threshold" in config:
            self._config.shrink_threshold = config["shrink_threshold"]
        if "grow_threshold" in config:
            self._config.grow_threshold = config["grow_threshold"]
        if "default_chunk_size" in config:
            self._config.default_chunk_size = config["default_chunk_size"]
        
        self._logger.info(f"Config updated: {config}")
    
    def should_optimize(self, file_size: int) -> bool:
        """
        Check if a file would benefit from optimization.
        
        Args:
            file_size: Size of the file
            
        Returns:
            True if optimization would change chunk size
        """
        return (
            file_size > self._config.shrink_threshold or
            file_size < self._config.grow_threshold
        )
    
    def get_expected_chunk_count(self, file_size: int, content_size: int = 0) -> int:
        """
        Estimate number of chunks for a file.
        
        Args:
            file_size: Size of the file in bytes
            content_size: Size of actual content (if different from file_size)
            
        Returns:
            Estimated number of chunks
        """
        size = content_size or file_size
        chunk_size = self.optimize(self._config.default_chunk_size, file_size)
        return max(1, size // chunk_size + (1 if size % chunk_size else 0))
    
    def get_stats(self) -> Dict:
        """Get optimizer statistics."""
        return {
            "config": self._config.to_dict(),
            "effective_range": {
                "min": self._config.min_chunk_size,
                "max": self._config.max_chunk_size,
                "ratio": self._config.max_chunk_size / self._config.min_chunk_size
            }
        }


def create_chunk_optimizer(config: Dict = None) -> ChunkOptimizer:
    """
    Factory function to create a ChunkOptimizer.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        ChunkOptimizer instance
    """
    return ChunkOptimizer(config)
