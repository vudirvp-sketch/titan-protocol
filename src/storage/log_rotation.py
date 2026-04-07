"""
Log Rotation for TITAN FUSE Protocol.

ITEM-STOR-04: Implements log rotation with compression and cleanup
for managing log file sizes.

Author: TITAN FUSE Team
Version: 3.4.0
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import gzip
import shutil
import logging
import os


@dataclass
class RotationConfig:
    """Log rotation configuration."""
    enabled: bool
    max_size_mb: int
    keep_count: int
    compress: bool
    max_age_days: int
    
    def to_dict(self) -> Dict:
        return {
            "enabled": self.enabled,
            "max_size_mb": self.max_size_mb,
            "keep_count": self.keep_count,
            "compress": self.compress,
            "max_age_days": self.max_age_days
        }


class LogRotator:
    """
    Manage log rotation with compression and cleanup.
    
    ITEM-STOR-04: Log rotation implementation.
    
    Provides:
    - Size-based rotation
    - Compression of old logs
    - Age-based cleanup
    - Integration with event journal
    
    Usage:
        config = {
            "enabled": True,
            "max_size_mb": 100,
            "keep_count": 10,
            "compress": True,
            "max_age_days": 30
        }
        
        rotator = LogRotator(config)
        
        # Rotate if needed
        rotator.rotate_if_needed(Path("logs/titan.log"))
        
        # Manual rotation
        rotator.rotate(Path("logs/titan.log"))
        
        # Cleanup old logs
        removed = rotator.cleanup_older_than(30)
    """
    
    DEFAULT_CONFIG = RotationConfig(
        enabled=True,
        max_size_mb=100,
        keep_count=10,
        compress=True,
        max_age_days=30
    )
    
    def __init__(self, config: Dict = None):
        """
        Initialize log rotator.
        
        Args:
            config: Rotation configuration dictionary
        """
        if config is None:
            config = {}
        
        self._config = RotationConfig(
            enabled=config.get("enabled", self.DEFAULT_CONFIG.enabled),
            max_size_mb=config.get("max_size_mb", self.DEFAULT_CONFIG.max_size_mb),
            keep_count=config.get("keep_count", self.DEFAULT_CONFIG.keep_count),
            compress=config.get("compress", self.DEFAULT_CONFIG.compress),
            max_age_days=config.get("max_age_days", self.DEFAULT_CONFIG.max_age_days)
        )
        
        self._logger = logging.getLogger(__name__)
    
    def rotate(self, log_path: str, max_size_mb: int = None, 
               keep_count: int = None) -> int:
        """
        Rotate log file.
        
        Args:
            log_path: Path to the log file
            max_size_mb: Override max size in MB
            keep_count: Override number of files to keep
            
        Returns:
            Number of rotated files
        """
        if not self._config.enabled:
            return 0
        
        path = Path(log_path)
        if not path.exists():
            return 0
        
        max_size = (max_size_mb or self._config.max_size_mb) * 1024 * 1024
        keep = keep_count or self._config.keep_count
        
        # Check size
        current_size = path.stat().st_size
        if current_size < max_size:
            return 0
        
        self._logger.info(f"Rotating log: {log_path} ({current_size / 1024 / 1024:.2f} MB)")
        
        # Rotate existing files
        rotated = self._shift_rotated_files(path, keep)
        
        # Move current to .1
        rotated_path = self._get_rotated_path(path, 1)
        shutil.move(str(path), str(rotated_path))
        
        # Compress if enabled
        if self._config.compress:
            self._compress_file(rotated_path)
        
        return rotated + 1
    
    def rotate_if_needed(self, log_path: str) -> int:
        """
        Rotate log file if it exceeds size limit.
        
        Args:
            log_path: Path to the log file
            
        Returns:
            Number of rotated files (0 if no rotation needed)
        """
        return self.rotate(log_path)
    
    def _shift_rotated_files(self, base_path: Path, keep_count: int) -> int:
        """Shift existing rotated files to make room for new one."""
        shifted = 0
        
        # Find all rotated files
        rotated_files = []
        for i in range(1, keep_count + 2):  # +2 for the new rotation
            rotated_path = self._get_rotated_path(base_path, i)
            compressed_path = Path(str(rotated_path) + ".gz")
            
            if rotated_path.exists():
                rotated_files.append((i, rotated_path, False))
            if compressed_path.exists():
                rotated_files.append((i, compressed_path, True))
        
        # Sort by index descending and shift
        rotated_files.sort(key=lambda x: x[0], reverse=True)
        
        for idx, filepath, is_compressed in rotated_files:
            if idx >= keep_count:
                # Delete files beyond keep count
                filepath.unlink()
                shifted += 1
            else:
                # Shift to next index
                new_path = self._get_rotated_path(base_path, idx + 1)
                if is_compressed:
                    new_path = Path(str(new_path) + ".gz")
                shutil.move(str(filepath), str(new_path))
        
        return shifted
    
    def _get_rotated_path(self, base_path: Path, index: int) -> Path:
        """Get path for rotated file at given index."""
        return base_path.with_suffix(f".{index}{base_path.suffix}")
    
    def _compress_file(self, filepath: Path) -> bool:
        """Compress a file using gzip."""
        try:
            compressed_path = Path(str(filepath) + ".gz")
            
            with open(filepath, 'rb') as f_in:
                with gzip.open(compressed_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # Remove original
            filepath.unlink()
            
            self._logger.debug(f"Compressed: {filepath} -> {compressed_path}")
            return True
            
        except Exception as e:
            self._logger.error(f"Compression failed for {filepath}: {e}")
            return False
    
    def compress_old_logs(self, log_path: str) -> int:
        """
        Compress all uncompressed rotated logs.
        
        Args:
            log_path: Base log path
            
        Returns:
            Number of files compressed
        """
        if not self._config.compress:
            return 0
        
        path = Path(log_path)
        compressed = 0
        
        for i in range(1, self._config.keep_count + 1):
            rotated_path = self._get_rotated_path(path, i)
            compressed_path = Path(str(rotated_path) + ".gz")
            
            if rotated_path.exists() and not compressed_path.exists():
                if self._compress_file(rotated_path):
                    compressed += 1
        
        return compressed
    
    def cleanup_older_than(self, days: int) -> int:
        """
        Remove logs older than specified days.
        
        Args:
            days: Age threshold in days
            
        Returns:
            Number of files removed
        """
        cutoff = datetime.now() - timedelta(days=days)
        removed = 0
        
        # Find log files in common directories
        log_dirs = [
            Path(".titan"),
            Path("logs"),
            Path("."),
        ]
        
        for log_dir in log_dirs:
            if not log_dir.exists():
                continue
            
            for pattern in ["*.log", "*.log.*", "*.log.*.gz", "*.jsonl", "*.jsonl.*", "*.jsonl.*.gz"]:
                for filepath in log_dir.glob(pattern):
                    try:
                        mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
                        if mtime < cutoff:
                            filepath.unlink()
                            removed += 1
                            self._logger.debug(f"Removed old log: {filepath}")
                    except Exception as e:
                        self._logger.error(f"Failed to remove {filepath}: {e}")
        
        if removed > 0:
            self._logger.info(f"Cleaned up {removed} log files older than {days} days")
        
        return removed
    
    def get_log_stats(self, log_path: str) -> Dict:
        """
        Get statistics about log files.
        
        Args:
            log_path: Base log path
            
        Returns:
            Dict with statistics
        """
        path = Path(log_path)
        stats = {
            "current_size_mb": 0,
            "total_size_mb": 0,
            "rotated_count": 0,
            "compressed_count": 0,
            "oldest_rotation": None
        }
        
        if path.exists():
            stats["current_size_mb"] = round(path.stat().st_size / 1024 / 1024, 2)
        
        total_size = stats["current_size_mb"]
        oldest_mtime = None
        
        for i in range(1, self._config.keep_count + 1):
            rotated_path = self._get_rotated_path(path, i)
            compressed_path = Path(str(rotated_path) + ".gz")
            
            if rotated_path.exists():
                stats["rotated_count"] += 1
                size_mb = rotated_path.stat().st_size / 1024 / 1024
                total_size += size_mb
                mtime = datetime.fromtimestamp(rotated_path.stat().st_mtime)
                if oldest_mtime is None or mtime < oldest_mtime:
                    oldest_mtime = mtime
            
            if compressed_path.exists():
                stats["compressed_count"] += 1
                stats["rotated_count"] += 1
                size_mb = compressed_path.stat().st_size / 1024 / 1024
                total_size += size_mb
                mtime = datetime.fromtimestamp(compressed_path.stat().st_mtime)
                if oldest_mtime is None or mtime < oldest_mtime:
                    oldest_mtime = mtime
        
        stats["total_size_mb"] = round(total_size, 2)
        stats["oldest_rotation"] = oldest_mtime.isoformat() if oldest_mtime else None
        
        return stats
    
    def get_config(self) -> RotationConfig:
        """Get current configuration."""
        return self._config
    
    def update_config(self, config: Dict) -> None:
        """Update configuration."""
        if "enabled" in config:
            self._config.enabled = config["enabled"]
        if "max_size_mb" in config:
            self._config.max_size_mb = config["max_size_mb"]
        if "keep_count" in config:
            self._config.keep_count = config["keep_count"]
        if "compress" in config:
            self._config.compress = config["compress"]
        if "max_age_days" in config:
            self._config.max_age_days = config["max_age_days"]
        
        self._logger.info(f"Log rotation config updated: {config}")


def create_log_rotator(config: Dict = None) -> LogRotator:
    """
    Factory function to create a LogRotator.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        LogRotator instance
    """
    return LogRotator(config)
