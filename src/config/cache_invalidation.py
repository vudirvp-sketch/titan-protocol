"""
Manifest Cache Invalidation for TITAN FUSE Protocol.

ITEM-CFG-05: Provides atomic cache invalidation for manifest files
to prevent stale cache causing false gap detection.

Author: TITAN FUSE Team
Version: 3.4.0
"""

from typing import Dict, Optional, Set, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import threading
import logging
import hashlib
import json


@dataclass
class CacheEntry:
    """A cached manifest entry."""
    path: str
    content_hash: str
    cached_data: Dict
    timestamp: str
    access_count: int = 0
    last_access: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "path": self.path,
            "content_hash": self.content_hash,
            "timestamp": self.timestamp,
            "access_count": self.access_count,
            "last_access": self.last_access
        }


class ManifestCacheManager:
    """
    Manage manifest cache with atomic invalidation.
    
    ITEM-CFG-05: Cache invalidation system.
    
    Provides:
    - In-memory caching of manifest data
    - Atomic invalidation on file changes
    - TTL for idle entries
    - File watcher integration
    
    Key features:
    - Atomic invalidation prevents race conditions
    - TTL only applies in idle mode (not during active operations)
    - Integration with file watcher for automatic invalidation
    
    Usage:
        manager = ManifestCacheManager(ttl_seconds=300)
        
        # Cache a manifest
        manager.cache(".titan/manifest.json", manifest_data)
        
        # Get cached data
        data = manager.get_cached(".titan/manifest.json")
        
        # Invalidate on file write
        manager.on_file_write(".titan/manifest.json")
        
        # Invalidate all
        manager.invalidate_all()
    """
    
    DEFAULT_TTL_SECONDS = 300
    TITAN_DIR_PREFIX = ".titan/"
    
    def __init__(self, ttl_seconds: int = None, max_entries: int = 100):
        """
        Initialize cache manager.
        
        Args:
            ttl_seconds: TTL for idle cache entries (default 300)
            max_entries: Maximum number of cached entries
        """
        self._cache: Dict[str, CacheEntry] = {}
        self._ttl_seconds = ttl_seconds or self.DEFAULT_TTL_SECONDS
        self._max_entries = max_entries
        self._lock = threading.RLock()
        self._active_operations = 0
        self._logger = logging.getLogger(__name__)
        
        # File write callbacks
        self._on_invalidate_callbacks: List[Callable[[str], None]] = []
    
    def cache(self, path: str, data: Dict) -> None:
        """
        Cache manifest data.
        
        Args:
            path: Path to the manifest file
            data: Manifest data to cache
        """
        with self._lock:
            content_hash = self._compute_hash(data)
            
            entry = CacheEntry(
                path=path,
                content_hash=content_hash,
                cached_data=data,
                timestamp=datetime.utcnow().isoformat() + "Z",
                access_count=0,
                last_access=""
            )
            
            self._cache[path] = entry
            self._logger.debug(f"Cached manifest: {path}")
            
            # Cleanup if over limit
            self._cleanup_if_needed()
    
    def get_cached(self, path: str) -> Optional[Dict]:
        """
        Get cached manifest data.
        
        Args:
            path: Path to the manifest file
            
        Returns:
            Cached data or None if not cached/expired
        """
        with self._lock:
            entry = self._cache.get(path)
            
            if entry is None:
                return None
            
            # Check TTL (only if not in active operation)
            if self._active_operations == 0 and self._is_expired(entry):
                self._logger.debug(f"Cache entry expired: {path}")
                del self._cache[path]
                return None
            
            # Update access stats
            entry.access_count += 1
            entry.last_access = datetime.utcnow().isoformat() + "Z"
            
            return entry.cached_data
    
    def invalidate(self, path: str) -> bool:
        """
        Invalidate a specific cache entry.
        
        Atomic operation - no race condition with readers.
        
        Args:
            path: Path to invalidate
            
        Returns:
            True if entry was invalidated
        """
        with self._lock:
            if path in self._cache:
                del self._cache[path]
                self._logger.info(f"Cache invalidated: {path}")
                
                # Call callbacks
                for callback in self._on_invalidate_callbacks:
                    try:
                        callback(path)
                    except Exception as e:
                        self._logger.error(f"Callback error: {e}")
                
                return True
            return False
    
    def invalidate_all(self) -> int:
        """
        Invalidate all cache entries.
        
        Returns:
            Number of entries invalidated
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._logger.info(f"All cache invalidated: {count} entries")
            return count
    
    def on_file_write(self, path: str) -> bool:
        """
        Handle file write event (hook callback).
        
        ITEM-CFG-05: Called by file watcher on write events.
        
        Args:
            path: Path to the written file
            
        Returns:
            True if cache was invalidated
        """
        # Only invalidate .titan/ files
        if not path.startswith(self.TITAN_DIR_PREFIX):
            return False
        
        self._logger.debug(f"File write detected: {path}")
        return self.invalidate(path)
    
    def begin_operation(self) -> None:
        """
        Mark beginning of an active operation.
        
        During active operations, TTL is not applied to prevent
        premature expiration of needed cache entries.
        """
        with self._lock:
            self._active_operations += 1
    
    def end_operation(self) -> None:
        """Mark end of an active operation."""
        with self._lock:
            self._active_operations = max(0, self._active_operations - 1)
    
    def add_invalidate_callback(self, callback: Callable[[str], None]) -> None:
        """
        Add a callback to be called on cache invalidation.
        
        Args:
            callback: Function to call with path as argument
        """
        self._on_invalidate_callbacks.append(callback)
    
    def remove_invalidate_callback(self, callback: Callable[[str], None]) -> bool:
        """Remove an invalidation callback."""
        if callback in self._on_invalidate_callbacks:
            self._on_invalidate_callbacks.remove(callback)
            return True
        return False
    
    def is_cached(self, path: str) -> bool:
        """Check if path is cached."""
        with self._lock:
            return path in self._cache
    
    def get_entry_info(self, path: str) -> Optional[Dict]:
        """Get cache entry info without returning data."""
        with self._lock:
            entry = self._cache.get(path)
            if entry:
                return entry.to_dict()
            return None
    
    def get_content_hash(self, path: str) -> Optional[str]:
        """Get cached content hash for a path."""
        with self._lock:
            entry = self._cache.get(path)
            if entry:
                return entry.content_hash
            return None
    
    def validate_hash(self, path: str, current_data: Dict) -> bool:
        """
        Check if cached data matches current data.
        
        Args:
            path: Cache path
            current_data: Current data to compare
            
        Returns:
            True if hashes match
        """
        with self._lock:
            cached_hash = self.get_content_hash(path)
            if cached_hash is None:
                return False
            
            current_hash = self._compute_hash(current_data)
            return cached_hash == current_hash
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired entries.
        
        Returns:
            Number of entries removed
        """
        with self._lock:
            if self._active_operations > 0:
                return 0
            
            expired = [
                path for path, entry in self._cache.items()
                if self._is_expired(entry)
            ]
            
            for path in expired:
                del self._cache[path]
            
            if expired:
                self._logger.info(f"Cleaned up {len(expired)} expired entries")
            
            return len(expired)
    
    def _is_expired(self, entry: CacheEntry) -> bool:
        """Check if a cache entry is expired."""
        try:
            entry_time = datetime.fromisoformat(
                entry.timestamp.replace('Z', '+00:00')
            )
            age_seconds = (
                datetime.utcnow() - entry_time.replace(tzinfo=None)
            ).total_seconds()
            return age_seconds > self._ttl_seconds
        except Exception:
            return False
    
    def _compute_hash(self, data: Dict) -> str:
        """Compute hash of data for change detection."""
        content = json.dumps(data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _cleanup_if_needed(self) -> None:
        """Remove old entries if over limit."""
        while len(self._cache) > self._max_entries:
            # Remove oldest entry
            oldest_path = min(
                self._cache.keys(),
                key=lambda p: self._cache[p].timestamp
            )
            del self._cache[oldest_path]
            self._logger.debug(f"Removed oldest cache entry: {oldest_path}")
    
    def get_stats(self) -> Dict:
        """Get cache statistics."""
        with self._lock:
            total_access = sum(e.access_count for e in self._cache.values())
            
            return {
                "entry_count": len(self._cache),
                "max_entries": self._max_entries,
                "ttl_seconds": self._ttl_seconds,
                "active_operations": self._active_operations,
                "total_access_count": total_access,
                "cached_paths": list(self._cache.keys())
            }
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            self._logger.info("Cache cleared")


# Global cache manager instance
_global_cache: Optional[ManifestCacheManager] = None


def get_cache_manager(ttl_seconds: int = None) -> ManifestCacheManager:
    """
    Get the global cache manager instance.
    
    Args:
        ttl_seconds: TTL for cache entries (only used on first call)
        
    Returns:
        ManifestCacheManager singleton
    """
    global _global_cache
    if _global_cache is None:
        _global_cache = ManifestCacheManager(ttl_seconds=ttl_seconds)
    return _global_cache
