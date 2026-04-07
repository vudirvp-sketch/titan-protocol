"""
Lock Backend Factory for TITAN FUSE Protocol.

ITEM-ARCH-03: Distributed Locking with TTL

Factory functions for creating lock backends based on configuration.

Author: TITAN FUSE Team
Version: 3.3.0
"""

from typing import Dict, Any, Optional
from pathlib import Path
import logging

from .backend import LockBackend
from .file_lock import FileLockBackend


def create_lock_backend(config: Dict[str, Any] = None) -> LockBackend:
    """
    Create a lock backend based on configuration.
    
    Args:
        config: Configuration dict with keys:
            - locks.backend: "file" | "redis" | "etcd" (default: "file")
            - locks.lock_dir: Path for file backend (default: ".titan/locks")
            - locks.redis.host: Redis host (default: "localhost")
            - locks.redis.port: Redis port (default: 6379)
            - locks.redis.db: Redis database (default: 0)
            - locks.redis.password: Redis password (optional)
            - locks.etcd.host: etcd host (default: "localhost")
            - locks.etcd.port: etcd port (default: 2379)
    
    Returns:
        Configured LockBackend instance
    """
    config = config or {}
    locks_config = config.get("locks", {})
    backend_type = locks_config.get("backend", "file")
    
    logger = logging.getLogger(__name__)
    
    if backend_type == "file":
        lock_dir = locks_config.get("lock_dir", ".titan/locks")
        logger.info(f"Creating FileLockBackend at {lock_dir}")
        return FileLockBackend(Path(lock_dir))
    
    elif backend_type == "redis":
        redis_config = locks_config.get("redis", {})
        return _create_redis_backend(redis_config, logger)
    
    elif backend_type == "etcd":
        etcd_config = locks_config.get("etcd", {})
        return _create_etcd_backend(etcd_config, logger)
    
    else:
        logger.warning(f"Unknown lock backend: {backend_type}, using file")
        return FileLockBackend()


def _create_redis_backend(config: Dict[str, Any], logger) -> LockBackend:
    """Create Redis lock backend."""
    try:
        from .redis_lock import RedisLockBackend
        
        return RedisLockBackend(
            host=config.get("host", "localhost"),
            port=config.get("port", 6379),
            db=config.get("db", 0),
            password=config.get("password"),
            key_prefix=config.get("key_prefix", "titan:lock:")
        )
    except ImportError:
        logger.error(
            "Redis backend requested but redis package not installed. "
            "Install with: pip install redis. Falling back to file backend."
        )
        return FileLockBackend()
    except Exception as e:
        logger.error(f"Failed to create Redis backend: {e}. Falling back to file backend.")
        return FileLockBackend()


def _create_etcd_backend(config: Dict[str, Any], logger) -> LockBackend:
    """Create etcd lock backend."""
    try:
        from .etcd_lock import EtcdLockBackend
        
        return EtcdLockBackend(
            host=config.get("host", "localhost"),
            port=config.get("port", 2379),
            key_prefix=config.get("key_prefix", "/titan/lock/")
        )
    except ImportError:
        logger.error(
            "etcd backend requested but etcd3 package not installed. "
            "Install with: pip install etcd3. Falling back to file backend."
        )
        return FileLockBackend()
    except Exception as e:
        logger.error(f"Failed to create etcd backend: {e}. Falling back to file backend.")
        return FileLockBackend()


def get_lock_backend(config: Dict[str, Any] = None) -> LockBackend:
    """
    Get or create a lock backend (singleton pattern).
    
    This function caches the backend instance for reuse.
    
    Args:
        config: Configuration dict (used on first call only)
    
    Returns:
        LockBackend instance
    """
    global _lock_backend_instance
    
    if _lock_backend_instance is None:
        _lock_backend_instance = create_lock_backend(config)
    
    return _lock_backend_instance


# Global singleton instance
_lock_backend_instance: Optional[LockBackend] = None


def reset_lock_backend() -> None:
    """
    Reset the global lock backend instance.
    
    Useful for testing or reconfiguration.
    """
    global _lock_backend_instance
    _lock_backend_instance = None
