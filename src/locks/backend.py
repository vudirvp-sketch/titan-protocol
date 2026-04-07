"""
Lock Backend Base for TITAN FUSE Protocol.

ITEM-ARCH-03: Distributed Locking with TTL

Defines the abstract interface for lock backends with TTL support.

Features:
- Acquire with TTL (auto-expiration)
- Release with verification
- Extend TTL
- Stale lock cleanup
- Owner identification

Author: TITAN FUSE Team
Version: 3.3.0
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Any
import uuid
import time


class LockStatus(Enum):
    """Status of a lock."""
    ACQUIRED = "acquired"
    RELEASED = "released"
    EXPIRED = "expired"
    FAILED = "failed"
    EXTENDED = "extended"


@dataclass
class Lock:
    """
    Represents a distributed lock.
    
    Attributes:
        resource: Resource identifier being locked
        owner: Unique identifier of lock owner
        ttl_seconds: Time-to-live in seconds
        acquired_at: Timestamp when lock was acquired
        expires_at: Timestamp when lock will expire
        lock_id: Unique identifier for this lock instance
        metadata: Additional lock metadata
    """
    resource: str
    owner: str
    ttl_seconds: int
    acquired_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    expires_at: Optional[str] = None
    lock_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.expires_at is None:
            # Calculate expiry time
            acquired = datetime.fromisoformat(self.acquired_at.replace('Z', '+00:00'))
            expires = acquired.timestamp() + self.ttl_seconds
            self.expires_at = datetime.utcfromtimestamp(expires).isoformat() + "Z"
    
    def is_expired(self) -> bool:
        """Check if lock has expired."""
        if not self.expires_at:
            return False
        expires = datetime.fromisoformat(self.expires_at.replace('Z', '+00:00'))
        return datetime.utcnow() > expires.replace(tzinfo=None)
    
    def remaining_ttl(self) -> int:
        """Get remaining TTL in seconds."""
        if not self.expires_at:
            return 0
        expires = datetime.fromisoformat(self.expires_at.replace('Z', '+00:00'))
        remaining = (expires.replace(tzinfo=None) - datetime.utcnow()).total_seconds()
        return max(0, int(remaining))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "lock_id": self.lock_id,
            "resource": self.resource,
            "owner": self.owner,
            "ttl_seconds": self.ttl_seconds,
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
            "metadata": self.metadata,
            "is_expired": self.is_expired(),
            "remaining_ttl": self.remaining_ttl()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Lock':
        """Create from dictionary."""
        return cls(
            lock_id=data.get("lock_id", str(uuid.uuid4())),
            resource=data["resource"],
            owner=data["owner"],
            ttl_seconds=data["ttl_seconds"],
            acquired_at=data.get("acquired_at", datetime.utcnow().isoformat() + "Z"),
            expires_at=data.get("expires_at"),
            metadata=data.get("metadata", {})
        )


class LockBackend(ABC):
    """
    Abstract base class for lock backends.
    
    ITEM-ARCH-03 Implementation:
    - acquire(resource: str, ttl_seconds: int, owner: str) -> Lock
    - release(lock: Lock) -> None
    - extend(lock: Lock, ttl_seconds: int) -> bool
    - is_locked(resource: str) -> bool
    - cleanup_stale() -> int
    
    Implementations must ensure:
    - TTL is strictly enforced (locks auto-expire)
    - Owner verification on release/extend
    - Thread/process safety
    - Crash recovery (no permanent stale locks)
    """
    
    @abstractmethod
    def acquire(self, resource: str, ttl_seconds: int, owner: str = None) -> Optional[Lock]:
        """
        Attempt to acquire a lock on a resource.
        
        Args:
            resource: Resource identifier to lock
            ttl_seconds: Time-to-live in seconds (lock auto-expires)
            owner: Optional owner identifier (auto-generated if None)
            
        Returns:
            Lock if acquired, None if resource already locked
        """
        pass
    
    @abstractmethod
    def release(self, lock: Lock) -> bool:
        """
        Release a lock.
        
        Must verify that the lock owner matches before releasing.
        
        Args:
            lock: Lock to release
            
        Returns:
            True if released, False if lock not found or owner mismatch
        """
        pass
    
    @abstractmethod
    def extend(self, lock: Lock, ttl_seconds: int) -> bool:
        """
        Extend the TTL of an existing lock.
        
        Must verify that the lock owner matches before extending.
        
        Args:
            lock: Lock to extend
            ttl_seconds: New TTL in seconds (from now, not from original expiry)
            
        Returns:
            True if extended, False if lock not found or owner mismatch
        """
        pass
    
    @abstractmethod
    def is_locked(self, resource: str) -> bool:
        """
        Check if a resource is currently locked.
        
        Args:
            resource: Resource identifier to check
            
        Returns:
            True if locked, False otherwise
        """
        pass
    
    @abstractmethod
    def get_lock(self, resource: str) -> Optional[Lock]:
        """
        Get the current lock on a resource.
        
        Args:
            resource: Resource identifier
            
        Returns:
            Lock if exists, None otherwise
        """
        pass
    
    @abstractmethod
    def cleanup_stale(self) -> int:
        """
        Clean up expired/stale locks.
        
        Returns:
            Number of locks cleaned up
        """
        pass
    
    def try_acquire(self, resource: str, ttl_seconds: int, 
                    owner: str = None, max_retries: int = 3,
                    retry_delay_ms: int = 100) -> Optional[Lock]:
        """
        Try to acquire a lock with retries.
        
        Args:
            resource: Resource to lock
            ttl_seconds: Lock TTL
            owner: Owner identifier
            max_retries: Maximum retry attempts
            retry_delay_ms: Delay between retries in milliseconds
            
        Returns:
            Lock if acquired, None if failed after retries
        """
        for attempt in range(max_retries):
            lock = self.acquire(resource, ttl_seconds, owner)
            if lock:
                return lock
            
            if attempt < max_retries - 1:
                time.sleep(retry_delay_ms / 1000.0)
        
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get lock backend statistics.
        
        Returns:
            Dict with backend stats
        """
        return {
            "backend_type": self.__class__.__name__,
            "stats_available": False
        }
