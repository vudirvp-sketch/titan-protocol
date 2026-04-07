"""
Redis-based Lock Backend for TITAN FUSE Protocol.

ITEM-ARCH-03: Distributed Locking with TTL

Redis-based distributed locking with SET NX EX pattern.
Suitable for multi-node deployments.

Features:
- Atomic acquire with SET NX EX
- Automatic TTL via Redis EXPIRE
- Safe release with Lua script (owner verification)
- Lock extension support

Author: TITAN FUSE Team
Version: 3.3.0
"""

import json
import time
from datetime import datetime
from typing import Dict, Optional, Any
import logging
import uuid

from .backend import LockBackend, Lock, LockStatus


# Lua script for safe lock release (owner verification)
RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

# Lua script for lock extension
EXTEND_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("expire", KEYS[1], ARGV[2])
else
    return 0
end
"""


class RedisLockBackend(LockBackend):
    """
    Redis-based lock backend with TTL support.
    
    ITEM-ARCH-03 Implementation:
    - Uses SET NX EX for atomic lock acquisition
    - TTL enforced via Redis key expiration
    - Safe release via Lua script with owner verification
    - Lock extension via Lua script
    
    Requires Redis 2.6.12+ for SET NX EX support.
    
    Usage:
        backend = RedisLockBackend(
            host="localhost",
            port=6379,
            db=0
        )
        
        # Acquire lock
        lock = backend.acquire("my_resource", ttl_seconds=300)
        
        # Release lock
        backend.release(lock)
    """
    
    def __init__(self, host: str = "localhost", port: int = 6379,
                 db: int = 0, password: str = None, 
                 key_prefix: str = "titan:lock:",
                 redis_client: Any = None):
        """
        Initialize Redis lock backend.
        
        Args:
            host: Redis host
            port: Redis port
            db: Redis database number
            password: Redis password
            key_prefix: Prefix for lock keys
            redis_client: Optional existing Redis client
        """
        self._logger = logging.getLogger(__name__)
        self.key_prefix = key_prefix
        self._redis = None
        self._release_sha = None
        self._extend_sha = None
        
        if redis_client:
            self._redis = redis_client
        else:
            try:
                import redis
                self._redis = redis.Redis(
                    host=host,
                    port=port,
                    db=db,
                    password=password,
                    decode_responses=True
                )
                # Test connection
                self._redis.ping()
                self._logger.info(f"Connected to Redis at {host}:{port}")
            except ImportError:
                self._logger.error(
                    "Redis package not installed. "
                    "Install with: pip install redis"
                )
                raise
            except Exception as e:
                self._logger.error(f"Failed to connect to Redis: {e}")
                raise
        
        # Register Lua scripts
        self._register_scripts()
    
    def _register_scripts(self):
        """Register Lua scripts for atomic operations."""
        try:
            self._release_sha = self._redis.script_load(RELEASE_SCRIPT)
            self._extend_sha = self._redis.script_load(EXTEND_SCRIPT)
        except Exception as e:
            self._logger.warning(f"Failed to register Lua scripts: {e}")
    
    def _get_lock_key(self, resource: str) -> str:
        """Get Redis key for a resource."""
        return f"{self.key_prefix}{resource}"
    
    def _encode_lock_value(self, lock: Lock) -> str:
        """Encode lock data as JSON string for Redis value."""
        return json.dumps({
            "lock_id": lock.lock_id,
            "owner": lock.owner,
            "resource": lock.resource,
            "acquired_at": lock.acquired_at,
            "ttl_seconds": lock.ttl_seconds
        })
    
    def _decode_lock_value(self, value: str, resource: str) -> Optional[Dict]:
        """Decode lock data from Redis value."""
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    
    def acquire(self, resource: str, ttl_seconds: int, owner: str = None) -> Optional[Lock]:
        """
        Attempt to acquire a lock on a resource.
        
        Uses SET NX EX for atomic lock acquisition:
        - NX: Only set if key doesn't exist
        - EX: Set expiration time
        
        Args:
            resource: Resource identifier to lock
            ttl_seconds: Time-to-live in seconds
            owner: Optional owner identifier
            
        Returns:
            Lock if acquired, None if resource already locked
        """
        import os
        
        lock_key = self._get_lock_key(resource)
        owner = owner or f"process-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        
        lock = Lock(
            resource=resource,
            owner=owner,
            ttl_seconds=ttl_seconds
        )
        
        lock_value = self._encode_lock_value(lock)
        
        try:
            # SET NX EX - atomic acquire with TTL
            acquired = self._redis.set(
                lock_key,
                lock_value,
                nx=True,  # Only if not exists
                ex=ttl_seconds  # Expiration in seconds
            )
            
            if acquired:
                self._logger.info(
                    f"Acquired Redis lock on {resource} "
                    f"(owner={owner}, ttl={ttl_seconds}s)"
                )
                return lock
            else:
                self._logger.debug(f"Resource {resource} already locked")
                return None
                
        except Exception as e:
            self._logger.error(f"Failed to acquire Redis lock: {e}")
            return None
    
    def release(self, lock: Lock) -> bool:
        """
        Release a lock using Lua script for atomic owner verification.
        
        Args:
            lock: Lock to release
            
        Returns:
            True if released, False if lock not found or owner mismatch
        """
        lock_key = self._get_lock_key(lock.resource)
        
        try:
            # Use Lua script for safe release
            if self._release_sha:
                result = self._redis.evalsha(
                    self._release_sha,
                    1,  # Number of keys
                    lock_key,
                    self._encode_lock_value(lock)
                )
                released = result == 1
            else:
                # Fallback: get, verify, delete (not atomic)
                current = self._redis.get(lock_key)
                if current:
                    lock_data = self._decode_lock_value(current, lock.resource)
                    if lock_data and lock_data.get("lock_id") == lock.lock_id:
                        released = self._redis.delete(lock_key) == 1
                    else:
                        released = False
                else:
                    released = False
            
            if released:
                self._logger.info(f"Released Redis lock on {lock.resource}")
            else:
                self._logger.warning(
                    f"Failed to release Redis lock on {lock.resource}: "
                    "not found or owner mismatch"
                )
            
            return released
            
        except Exception as e:
            self._logger.error(f"Failed to release Redis lock: {e}")
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
        lock_key = self._get_lock_key(lock.resource)
        
        try:
            # Use Lua script for safe extend
            if self._extend_sha:
                result = self._redis.evalsha(
                    self._extend_sha,
                    1,  # Number of keys
                    lock_key,
                    self._encode_lock_value(lock),
                    ttl_seconds
                )
                extended = result == 1
            else:
                # Fallback: get, verify, expire (not atomic)
                current = self._redis.get(lock_key)
                if current:
                    lock_data = self._decode_lock_value(current, lock.resource)
                    if lock_data and lock_data.get("lock_id") == lock.lock_id:
                        extended = self._redis.expire(lock_key, ttl_seconds)
                    else:
                        extended = False
                else:
                    extended = False
            
            if extended:
                self._logger.info(
                    f"Extended Redis lock on {lock.resource} (new ttl={ttl_seconds}s)"
                )
            
            return extended
            
        except Exception as e:
            self._logger.error(f"Failed to extend Redis lock: {e}")
            return False
    
    def is_locked(self, resource: str) -> bool:
        """
        Check if a resource is currently locked.
        
        Args:
            resource: Resource identifier to check
            
        Returns:
            True if locked, False otherwise
        """
        lock_key = self._get_lock_key(resource)
        return self._redis.exists(lock_key) == 1
    
    def get_lock(self, resource: str) -> Optional[Lock]:
        """
        Get the current lock on a resource.
        
        Args:
            resource: Resource identifier
            
        Returns:
            Lock if exists, None otherwise
        """
        lock_key = self._get_lock_key(resource)
        
        try:
            value = self._redis.get(lock_key)
            if value:
                lock_data = self._decode_lock_value(value, resource)
                if lock_data:
                    # Get TTL from Redis
                    ttl = self._redis.ttl(lock_key)
                    lock_data["ttl_seconds"] = max(0, ttl)
                    return Lock.from_dict(lock_data)
            return None
        except Exception as e:
            self._logger.error(f"Failed to get Redis lock: {e}")
            return None
    
    def cleanup_stale(self) -> int:
        """
        Clean up expired/stale locks.
        
        Note: Redis automatically handles TTL expiration, so this
        method returns 0 and is mainly for API compatibility.
        
        Returns:
            0 (Redis handles TTL automatically)
        """
        # Redis auto-expires keys, so no manual cleanup needed
        return 0
    
    def list_locks(self, pattern: str = "*") -> list:
        """
        List all locks matching a pattern.
        
        Args:
            pattern: Pattern to match (default: all locks)
            
        Returns:
            List of Lock objects
        """
        locks = []
        
        try:
            keys = self._redis.keys(f"{self.key_prefix}{pattern}")
            
            for key in keys:
                value = self._redis.get(key)
                if value:
                    lock_data = self._decode_lock_value(value, "")
                    if lock_data:
                        resource = key[len(self.key_prefix):]
                        ttl = self._redis.ttl(key)
                        lock_data["resource"] = resource
                        lock_data["ttl_seconds"] = max(0, ttl)
                        locks.append(Lock.from_dict(lock_data))
        except Exception as e:
            self._logger.error(f"Failed to list Redis locks: {e}")
        
        return locks
    
    def get_stats(self) -> Dict[str, Any]:
        """Get lock backend statistics."""
        try:
            info = self._redis.info()
            locks = self.list_locks()
            
            return {
                "backend_type": "RedisLockBackend",
                "redis_version": info.get("redis_version"),
                "connected_clients": info.get("connected_clients"),
                "used_memory_human": info.get("used_memory_human"),
                "active_locks": len(locks),
                "key_prefix": self.key_prefix,
                "stats_available": True
            }
        except Exception as e:
            return {
                "backend_type": "RedisLockBackend",
                "error": str(e),
                "stats_available": False
            }
    
    def force_release(self, resource: str) -> bool:
        """
        Force release a lock regardless of owner.
        
        WARNING: Use with caution.
        
        Args:
            resource: Resource to unlock
            
        Returns:
            True if released, False otherwise
        """
        lock_key = self._get_lock_key(resource)
        
        try:
            result = self._redis.delete(lock_key)
            if result == 1:
                self._logger.warning(f"Force released Redis lock on {resource}")
                return True
            return False
        except Exception as e:
            self._logger.error(f"Failed to force release: {e}")
            return False
