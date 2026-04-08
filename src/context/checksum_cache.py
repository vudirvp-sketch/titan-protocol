"""
Checksum Cache for TITAN FUSE Protocol.

ITEM-SAE-006: AST Checksum System - Checksum Cache

Provides caching for semantic checksums to avoid recomputation
and enable efficient change detection.

Key Features:
- In-memory cache with TTL
- Persistent cache option
- Batch invalidation
- Integration with Context Graph

Author: TITAN FUSE Team
Version: 1.0.0
"""

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
import logging
import threading

from src.utils.timezone import now_utc, now_utc_iso
from src.context.semantic_checksum import (
    SemanticChecksum,
    SemanticChecksumResult,
    Language,
)


@dataclass
class ChecksumEntry:
    """
    A cached checksum entry.
    
    Attributes:
        file_path: Path to the file
        semantic_hash: Cached semantic hash
        content_hash: Cached content hash
        language: Detected language
        element_count: Number of semantic elements
        computed_at: When the checksum was computed
        last_modified: File modification time when computed
        file_size: File size in bytes
        metadata: Additional metadata
    """
    file_path: str
    semantic_hash: str
    content_hash: str
    language: Language
    element_count: int
    computed_at: str
    last_modified: float
    file_size: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "file_path": self.file_path,
            "semantic_hash": self.semantic_hash,
            "content_hash": self.content_hash,
            "language": self.language.value,
            "element_count": self.element_count,
            "computed_at": self.computed_at,
            "last_modified": self.last_modified,
            "file_size": self.file_size,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChecksumEntry":
        """Create from dictionary."""
        return cls(
            file_path=data["file_path"],
            semantic_hash=data["semantic_hash"],
            content_hash=data["content_hash"],
            language=Language(data["language"]),
            element_count=data["element_count"],
            computed_at=data["computed_at"],
            last_modified=data["last_modified"],
            file_size=data["file_size"],
            metadata=data.get("metadata", {}),
        )


@dataclass
class CacheStats:
    """Statistics for the checksum cache."""
    total_entries: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    invalidations: int = 0
    last_cleanup: str = ""
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0


class ChecksumCache:
    """
    Cache for semantic checksums.
    
    Provides efficient caching to avoid recomputing checksums
    for unchanged files.
    
    Cache invalidation strategies:
    - File modification time check
    - TTL-based expiration
    - Manual invalidation
    - Content hash comparison
    
    Usage:
        cache = ChecksumCache()
        
        # Get cached checksum (computes if not cached)
        entry = cache.get("src/main.py")
        
        # Update cache after file change
        cache.update("src/main.py", result)
        
        # Invalidate specific file
        cache.invalidate("src/main.py")
        
        # Get all stale entries
        stale = cache.get_all_stale()
    """
    
    def __init__(
        self,
        ttl_hours: float = 24.0,
        max_entries: int = 10000,
        check_mtime: bool = True,
        persistent_path: Optional[str] = None,
    ):
        """
        Initialize the ChecksumCache.
        
        Args:
            ttl_hours: Time-to-live in hours for cache entries
            max_entries: Maximum number of entries
            check_mtime: Whether to check file modification time
            persistent_path: Path for persistent cache storage
        """
        self._ttl_hours = ttl_hours
        self._max_entries = max_entries
        self._check_mtime = check_mtime
        self._persistent_path = persistent_path
        
        self._cache: Dict[str, ChecksumEntry] = {}
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)
        self._stats = CacheStats()
        
        self._checksummer = SemanticChecksum()
        
        # Load persistent cache if available
        if persistent_path:
            self._load_persistent()
    
    # =========================================================================
    # Cache Operations
    # =========================================================================
    
    def get(self, file_path: str) -> Optional[ChecksumEntry]:
        """
        Get cached checksum for a file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Cached ChecksumEntry, or None if not cached/stale
        """
        with self._lock:
            entry = self._cache.get(file_path)
            
            if entry is None:
                self._stats.cache_misses += 1
                return None
            
            # Check if entry is stale
            if self._is_stale(entry):
                self._stats.cache_misses += 1
                del self._cache[file_path]
                return None
            
            self._stats.cache_hits += 1
            return entry
    
    def get_or_compute(
        self,
        file_path: str,
        force: bool = False
    ) -> ChecksumEntry:
        """
        Get cached checksum or compute if not cached.
        
        Args:
            file_path: Path to the file
            force: Force recomputation
            
        Returns:
            ChecksumEntry (cached or newly computed)
        """
        if not force:
            cached = self.get(file_path)
            if cached:
                return cached
        
        # Compute new checksum
        result = self._checksummer.compute_file_hash(file_path)
        
        # Create cache entry
        entry = self._create_entry(file_path, result)
        
        # Update cache
        self.update(file_path, entry)
        
        return entry
    
    def update(
        self,
        file_path: str,
        result: SemanticChecksumResult
    ) -> ChecksumEntry:
        """
        Update cache with new checksum result.
        
        Args:
            file_path: Path to the file
            result: SemanticChecksumResult to cache
            
        Returns:
            The created ChecksumEntry
        """
        entry = self._create_entry(file_path, result)
        
        with self._lock:
            self._cache[file_path] = entry
            self._stats.total_entries = len(self._cache)
            
            # Check max entries
            if len(self._cache) > self._max_entries:
                self._evict_oldest()
        
        # Persist if configured
        if self._persistent_path:
            self._save_persistent()
        
        return entry
    
    def invalidate(self, file_path: str) -> bool:
        """
        Invalidate cache entry for a file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            True if entry was invalidated
        """
        with self._lock:
            if file_path in self._cache:
                del self._cache[file_path]
                self._stats.invalidations += 1
                self._stats.total_entries = len(self._cache)
                return True
            return False
    
    def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all entries matching a pattern.
        
        Args:
            pattern: Glob pattern to match
            
        Returns:
            Number of entries invalidated
        """
        import fnmatch
        
        count = 0
        with self._lock:
            keys_to_remove = [
                k for k in self._cache.keys()
                if fnmatch.fnmatch(k, pattern)
            ]
            
            for key in keys_to_remove:
                del self._cache[key]
                count += 1
            
            self._stats.invalidations += count
            self._stats.total_entries = len(self._cache)
        
        return count
    
    def clear(self) -> int:
        """
        Clear all cache entries.
        
        Returns:
            Number of entries cleared
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._stats.total_entries = 0
        return count
    
    # =========================================================================
    # Query Operations
    # =========================================================================
    
    def get_all_stale(self) -> List[str]:
        """
        Get all file paths with stale cache entries.
        
        Returns:
            List of file paths that need recomputation
        """
        stale = []
        
        with self._lock:
            for file_path, entry in self._cache.items():
                if self._is_stale(entry):
                    stale.append(file_path)
        
        return stale
    
    def get_files_by_language(self, language: Language) -> List[str]:
        """Get all cached files of a specific language."""
        with self._lock:
            return [
                fp for fp, entry in self._cache.items()
                if entry.language == language
            ]
    
    def get_files_with_semantic_hash(self, semantic_hash: str) -> List[str]:
        """Get all files with a specific semantic hash."""
        with self._lock:
            return [
                fp for fp, entry in self._cache.items()
                if entry.semantic_hash == semantic_hash
            ]
    
    def find_duplicates(self) -> Dict[str, List[str]]:
        """
        Find files with duplicate semantic hashes.
        
        Returns:
            Dict mapping semantic hash to list of file paths
        """
        hash_to_files: Dict[str, List[str]] = {}
        
        with self._lock:
            for file_path, entry in self._cache.items():
                if entry.semantic_hash not in hash_to_files:
                    hash_to_files[entry.semantic_hash] = []
                hash_to_files[entry.semantic_hash].append(file_path)
        
        # Return only hashes with multiple files
        return {
            h: files for h, files in hash_to_files.items()
            if len(files) > 1
        }
    
    # =========================================================================
    # Statistics
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            return {
                "total_entries": self._stats.total_entries,
                "cache_hits": self._stats.cache_hits,
                "cache_misses": self._stats.cache_misses,
                "hit_rate": round(self._stats.hit_rate, 3),
                "invalidations": self._stats.invalidations,
                "ttl_hours": self._ttl_hours,
                "max_entries": self._max_entries,
            }
    
    # =========================================================================
    # Internal Methods
    # =========================================================================
    
    def _create_entry(
        self,
        file_path: str,
        result: SemanticChecksumResult
    ) -> ChecksumEntry:
        """Create a ChecksumEntry from result."""
        # Get file stats
        try:
            stat = os.stat(file_path)
            last_modified = stat.st_mtime
            file_size = stat.st_size
        except OSError:
            last_modified = 0
            file_size = 0
        
        return ChecksumEntry(
            file_path=file_path,
            semantic_hash=result.semantic_hash,
            content_hash=result.content_hash,
            language=result.language,
            element_count=result.element_count,
            computed_at=now_utc_iso(),
            last_modified=last_modified,
            file_size=file_size,
            metadata={"parse_errors": result.parse_errors},
        )
    
    def _is_stale(self, entry: ChecksumEntry) -> bool:
        """Check if a cache entry is stale."""
        # Check TTL
        try:
            computed = datetime.fromisoformat(entry.computed_at)
            if now_utc() - computed > timedelta(hours=self._ttl_hours):
                return True
        except (ValueError, TypeError):
            pass
        
        # Check file modification time
        if self._check_mtime:
            try:
                current_mtime = os.path.getmtime(entry.file_path)
                if current_mtime > entry.last_modified:
                    return True
            except OSError:
                # File doesn't exist
                return True
        
        return False
    
    def _evict_oldest(self) -> int:
        """Evict oldest entries to make room."""
        if len(self._cache) <= self._max_entries:
            return 0
        
        # Sort by computed_at
        sorted_entries = sorted(
            self._cache.items(),
            key=lambda x: x[1].computed_at
        )
        
        # Remove oldest
        to_remove = len(self._cache) - self._max_entries
        for file_path, _ in sorted_entries[:to_remove]:
            del self._cache[file_path]
        
        return to_remove
    
    def _load_persistent(self) -> None:
        """Load cache from persistent storage."""
        if not self._persistent_path:
            return
        
        try:
            path = Path(self._persistent_path)
            if not path.exists():
                return
            
            with open(path, "r") as f:
                data = json.load(f)
            
            for entry_data in data.get("entries", []):
                try:
                    entry = ChecksumEntry.from_dict(entry_data)
                    self._cache[entry.file_path] = entry
                except (KeyError, ValueError) as e:
                    self._logger.warning(f"Failed to load cache entry: {e}")
            
            self._stats.total_entries = len(self._cache)
            self._logger.info(f"Loaded {len(self._cache)} entries from cache")
            
        except Exception as e:
            self._logger.error(f"Failed to load cache: {e}")
    
    def _save_persistent(self) -> None:
        """Save cache to persistent storage."""
        if not self._persistent_path:
            return
        
        try:
            path = Path(self._persistent_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "version": "1.0",
                "entries": [e.to_dict() for e in self._cache.values()],
                "stats": self.get_stats(),
            }
            
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            
        except Exception as e:
            self._logger.error(f"Failed to save cache: {e}")


# =============================================================================
# Module-level convenience
# =============================================================================

_default_cache: Optional[ChecksumCache] = None


def get_checksum_cache(**kwargs) -> ChecksumCache:
    """Get or create default ChecksumCache instance."""
    global _default_cache
    
    if _default_cache is None:
        _default_cache = ChecksumCache(**kwargs)
    
    return _default_cache
