"""
File-based Lock Backend for TITAN FUSE Protocol.

ITEM-ARCH-03: Distributed Locking with TTL

Local file-based locking with TTL via timestamp.
Suitable for single-node deployments and testing.

Features:
- File-based lock storage
- TTL via timestamp comparison
- Automatic stale lock cleanup
- Cross-process safety via file locking

Author: TITAN FUSE Team
Version: 3.3.0
"""

import json
import os
import time
import fcntl
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any
import logging
import threading

from .backend import LockBackend, Lock, LockStatus


class FileLockBackend(LockBackend):
    """
    File-based lock backend with TTL support.
    
    ITEM-ARCH-03 Implementation:
    - Locks stored as JSON files in a directory
    - TTL enforced via expires_at timestamp
    - File locking (fcntl) for cross-process safety
    - Stale lock cleanup removes expired lock files
    
    Lock file format:
    {
        "lock_id": "uuid",
        "resource": "resource_name",
        "owner": "owner_id",
        "ttl_seconds": 300,
        "acquired_at": "ISO8601",
        "expires_at": "ISO8601",
        "metadata": {}
    }
    
    Usage:
        backend = FileLockBackend(Path(".titan/locks"))
        
        # Acquire lock
        lock = backend.acquire("my_resource", ttl_seconds=300)
        
        # Check if locked
        if backend.is_locked("my_resource"):
            print("Resource is locked")
        
        # Release lock
        backend.release(lock)
    """
    
    def __init__(self, lock_dir: Path = None):
        """
        Initialize file lock backend.
        
        Args:
            lock_dir: Directory to store lock files (default: .titan/locks)
        """
        self.lock_dir = Path(lock_dir) if lock_dir else Path(".titan/locks")
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(__name__)
        self._local_lock = threading.RLock()  # For thread safety
    
    def _get_lock_path(self, resource: str) -> Path:
        """Get lock file path for a resource."""
        # Sanitize resource name for filesystem
        safe_name = resource.replace("/", "_").replace("\\", "_")
        return self.lock_dir / f"{safe_name}.lock"
    
    def _read_lock_file(self, path: Path) -> Optional[Dict]:
        """Read lock file contents."""
        if not path.exists():
            return None
        
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self._logger.warning(f"Failed to read lock file {path}: {e}")
            return None
    
    def _write_lock_file(self, path: Path, lock_data: Dict) -> bool:
        """Write lock file contents with exclusive lock."""
        try:
            with open(path, 'w') as f:
                # Acquire exclusive lock
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(lock_data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            return True
        except IOError as e:
            self._logger.error(f"Failed to write lock file {path}: {e}")
            return False
    
    def _is_lock_valid(self, lock_data: Dict) -> bool:
        """Check if lock data represents a valid (non-expired) lock."""
        if not lock_data:
            return False
        
        expires_at = lock_data.get("expires_at")
        if not expires_at:
            return False
        
        try:
            expires = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            return datetime.utcnow() < expires.replace(tzinfo=None)
        except (ValueError, TypeError):
            return False
    
    def acquire(self, resource: str, ttl_seconds: int, owner: str = None) -> Optional[Lock]:
        """
        Attempt to acquire a lock on a resource.
        
        Args:
            resource: Resource identifier to lock
            ttl_seconds: Time-to-live in seconds
            owner: Optional owner identifier
            
        Returns:
            Lock if acquired, None if resource already locked
        """
        with self._local_lock:
            lock_path = self._get_lock_path(resource)
            
            # Check for existing lock
            existing = self._read_lock_file(lock_path)
            if existing and self._is_lock_valid(existing):
                self._logger.debug(
                    f"Resource {resource} already locked by {existing.get('owner')}"
                )
                return None
            
            # Clean up expired lock if exists
            if existing and not self._is_lock_valid(existing):
                self._logger.debug(f"Cleaning up expired lock for {resource}")
            
            # Create new lock
            owner = owner or f"process-{os.getpid()}"
            lock = Lock(
                resource=resource,
                owner=owner,
                ttl_seconds=ttl_seconds
            )
            
            # Write lock file
            if self._write_lock_file(lock_path, lock.to_dict()):
                self._logger.info(
                    f"Acquired lock on {resource} (owner={owner}, ttl={ttl_seconds}s)"
                )
                return lock
            
            return None
    
    def release(self, lock: Lock) -> bool:
        """
        Release a lock.
        
        Args:
            lock: Lock to release
            
        Returns:
            True if released, False if lock not found or owner mismatch
        """
        with self._local_lock:
            lock_path = self._get_lock_path(lock.resource)
            
            # Verify lock exists and owner matches
            existing = self._read_lock_file(lock_path)
            if not existing:
                self._logger.warning(f"Lock not found for {lock.resource}")
                return False
            
            if existing.get("owner") != lock.owner:
                self._logger.warning(
                    f"Owner mismatch for {lock.resource}: "
                    f"expected {lock.owner}, got {existing.get('owner')}"
                )
                return False
            
            # Verify lock_id matches
            if existing.get("lock_id") != lock.lock_id:
                self._logger.warning(
                    f"Lock ID mismatch for {lock.resource}: "
                    f"expected {lock.lock_id}, got {existing.get('lock_id')}"
                )
                return False
            
            # Remove lock file
            try:
                lock_path.unlink()
                self._logger.info(f"Released lock on {lock.resource}")
                return True
            except IOError as e:
                self._logger.error(f"Failed to remove lock file: {e}")
                return False
    
    def extend(self, lock: Lock, ttl_seconds: int) -> bool:
        """
        Extend the TTL of an existing lock.
        
        Args:
            lock: Lock to extend
            ttl_seconds: New TTL in seconds
            
        Returns:
            True if extended, False if lock not found or owner mismatch
        """
        with self._local_lock:
            lock_path = self._get_lock_path(lock.resource)
            
            # Verify lock exists and owner matches
            existing = self._read_lock_file(lock_path)
            if not existing:
                self._logger.warning(f"Lock not found for {lock.resource}")
                return False
            
            if existing.get("owner") != lock.owner:
                self._logger.warning(
                    f"Owner mismatch for {lock.resource}"
                )
                return False
            
            # Update TTL
            lock_data = Lock.from_dict(existing)
            lock_data.ttl_seconds = ttl_seconds
            lock_data.expires_at = None  # Recalculate
            lock_data.__post_init__()  # Recalculate expires_at
            
            # Write updated lock file
            if self._write_lock_file(lock_path, lock_data.to_dict()):
                self._logger.info(
                    f"Extended lock on {lock.resource} (new ttl={ttl_seconds}s)"
                )
                return True
            
            return False
    
    def is_locked(self, resource: str) -> bool:
        """
        Check if a resource is currently locked.
        
        Args:
            resource: Resource identifier to check
            
        Returns:
            True if locked, False otherwise
        """
        with self._local_lock:
            lock_path = self._get_lock_path(resource)
            existing = self._read_lock_file(lock_path)
            return self._is_lock_valid(existing) if existing else False
    
    def get_lock(self, resource: str) -> Optional[Lock]:
        """
        Get the current lock on a resource.
        
        Args:
            resource: Resource identifier
            
        Returns:
            Lock if exists and valid, None otherwise
        """
        with self._local_lock:
            lock_path = self._get_lock_path(resource)
            existing = self._read_lock_file(lock_path)
            
            if existing and self._is_lock_valid(existing):
                return Lock.from_dict(existing)
            
            return None
    
    def cleanup_stale(self) -> int:
        """
        Clean up expired/stale locks.
        
        Returns:
            Number of locks cleaned up
        """
        cleaned = 0
        
        with self._local_lock:
            for lock_file in self.lock_dir.glob("*.lock"):
                lock_data = self._read_lock_file(lock_file)
                
                if not lock_data or not self._is_lock_valid(lock_data):
                    try:
                        lock_file.unlink()
                        cleaned += 1
                        self._logger.debug(f"Cleaned up stale lock: {lock_file}")
                    except IOError as e:
                        self._logger.warning(f"Failed to clean up {lock_file}: {e}")
        
        if cleaned > 0:
            self._logger.info(f"Cleaned up {cleaned} stale locks")
        
        return cleaned
    
    def list_locks(self) -> list:
        """
        List all current locks.
        
        Returns:
            List of Lock objects
        """
        locks = []
        
        with self._local_lock:
            for lock_file in self.lock_dir.glob("*.lock"):
                lock_data = self._read_lock_file(lock_file)
                
                if lock_data and self._is_lock_valid(lock_data):
                    locks.append(Lock.from_dict(lock_data))
        
        return locks
    
    def get_stats(self) -> Dict[str, Any]:
        """Get lock backend statistics."""
        locks = self.list_locks()
        
        return {
            "backend_type": "FileLockBackend",
            "lock_dir": str(self.lock_dir),
            "active_locks": len(locks),
            "locks_by_owner": self._count_by_owner(locks),
            "stats_available": True
        }
    
    def _count_by_owner(self, locks: list) -> Dict[str, int]:
        """Count locks by owner."""
        counts = {}
        for lock in locks:
            owner = lock.owner
            counts[owner] = counts.get(owner, 0) + 1
        return counts
    
    def force_release(self, resource: str) -> bool:
        """
        Force release a lock regardless of owner.
        
        WARNING: Use with caution. This should only be used
        in administrative scenarios.
        
        Args:
            resource: Resource to unlock
            
        Returns:
            True if released, False otherwise
        """
        with self._local_lock:
            lock_path = self._get_lock_path(resource)
            
            if not lock_path.exists():
                return False
            
            try:
                lock_path.unlink()
                self._logger.warning(f"Force released lock on {resource}")
                return True
            except IOError as e:
                self._logger.error(f"Failed to force release: {e}")
                return False
