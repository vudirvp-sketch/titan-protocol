"""
etcd-based Lock Backend for TITAN FUSE Protocol.

ITEM-ARCH-03: Distributed Locking with TTL

etcd-based distributed locking with leases support.
Suitable for Kubernetes and cloud-native deployments.

Features:
- etcd lease for TTL support
- Atomic compare-and-swap for lock acquisition
- Automatic lock expiration via lease
- Safe release with owner verification

Author: TITAN FUSE Team
Version: 3.3.0
"""

import json
import time
from datetime import datetime
from typing import Dict, Optional, Any
import logging
import uuid
import os

from .backend import LockBackend, Lock, LockStatus


class EtcdLockBackend(LockBackend):
    """
    etcd-based lock backend with TTL support.
    
    ITEM-ARCH-03 Implementation:
    - Uses etcd leases for TTL
    - Atomic lock acquisition via transaction
    - Safe release via compare-and-delete
    - Automatic lock expiration
    
    Requires etcd3 client library.
    
    Usage:
        backend = EtcdLockBackend(
            host="localhost",
            port=2379
        )
        
        # Acquire lock
        lock = backend.acquire("my_resource", ttl_seconds=300)
        
        # Release lock
        backend.release(lock)
    """
    
    def __init__(self, host: str = "localhost", port: int = 2379,
                 key_prefix: str = "/titan/lock/",
                 etcd_client: Any = None):
        """
        Initialize etcd lock backend.
        
        Args:
            host: etcd host
            port: etcd port
            key_prefix: Prefix for lock keys
            etcd_client: Optional existing etcd client
        """
        self._logger = logging.getLogger(__name__)
        self.key_prefix = key_prefix
        self._etcd = None
        self._leases = {}  # Track active leases
        
        if etcd_client:
            self._etcd = etcd_client
        else:
            try:
                import etcd3
                self._etcd = etcd3.client(host=host, port=port)
                # Test connection
                self._etcd.status()
                self._logger.info(f"Connected to etcd at {host}:{port}")
            except ImportError:
                self._logger.error(
                    "etcd3 package not installed. "
                    "Install with: pip install etcd3"
                )
                raise
            except Exception as e:
                self._logger.error(f"Failed to connect to etcd: {e}")
                raise
    
    def _get_lock_key(self, resource: str) -> str:
        """Get etcd key for a resource."""
        return f"{self.key_prefix}{resource}"
    
    def _encode_lock_value(self, lock: Lock) -> str:
        """Encode lock data as JSON string for etcd value."""
        return json.dumps({
            "lock_id": lock.lock_id,
            "owner": lock.owner,
            "resource": lock.resource,
            "acquired_at": lock.acquired_at,
            "ttl_seconds": lock.ttl_seconds
        })
    
    def _decode_lock_value(self, value: bytes) -> Optional[Dict]:
        """Decode lock data from etcd value."""
        if not value:
            return None
        try:
            if isinstance(value, bytes):
                value = value.decode('utf-8')
            return json.loads(value)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
    
    def acquire(self, resource: str, ttl_seconds: int, owner: str = None) -> Optional[Lock]:
        """
        Attempt to acquire a lock on a resource.
        
        Uses etcd lease for TTL and transaction for atomic acquire.
        
        Args:
            resource: Resource identifier to lock
            ttl_seconds: Time-to-live in seconds
            owner: Optional owner identifier
            
        Returns:
            Lock if acquired, None if resource already locked
        """
        lock_key = self._get_lock_key(resource)
        owner = owner or f"process-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        
        lock = Lock(
            resource=resource,
            owner=owner,
            ttl_seconds=ttl_seconds
        )
        
        lock_value = self._encode_lock_value(lock)
        
        try:
            # Create lease for TTL
            lease = self._etcd.lease(ttl_seconds)
            
            # Use transaction for atomic acquire
            # If key doesn't exist, set it with lease
            txn_result = self._etcd.transaction(
                compare=[
                    self._etcd.transactions.version(lock_key) == 0
                ],
                success=[
                    self._etcd.transactions.put(lock_key, lock_value, lease=lease)
                ],
                failure=[]
            )
            
            if txn_result.get("succeeded", False):
                # Store lease for later release/extend
                self._leases[lock.lock_id] = lease
                
                self._logger.info(
                    f"Acquired etcd lock on {resource} "
                    f"(owner={owner}, ttl={ttl_seconds}s)"
                )
                return lock
            else:
                # Lock already exists
                lease.revoke()  # Clean up unused lease
                self._logger.debug(f"Resource {resource} already locked")
                return None
                
        except Exception as e:
            self._logger.error(f"Failed to acquire etcd lock: {e}")
            return None
    
    def release(self, lock: Lock) -> bool:
        """
        Release a lock with owner verification.
        
        Args:
            lock: Lock to release
            
        Returns:
            True if released, False if lock not found or owner mismatch
        """
        lock_key = self._get_lock_key(lock.resource)
        
        try:
            # Get current value
            value, metadata = self._etcd.get(lock_key)
            
            if not value:
                self._logger.warning(f"Lock not found for {lock.resource}")
                return False
            
            lock_data = self._decode_lock_value(value)
            
            # Verify owner
            if lock_data.get("lock_id") != lock.lock_id:
                self._logger.warning(
                    f"Lock ID mismatch for {lock.resource}"
                )
                return False
            
            # Delete with transaction (compare-and-delete)
            txn_result = self._etcd.transaction(
                compare=[
                    self._etcd.transactions.value(lock_key) == value
                ],
                success=[
                    self._etcd.transactions.delete(lock_key)
                ],
                failure=[]
            )
            
            if txn_result.get("succeeded", False):
                # Revoke lease if tracked
                if lock.lock_id in self._leases:
                    try:
                        self._leases[lock.lock_id].revoke()
                    except Exception:
                        pass
                    del self._leases[lock.lock_id]
                
                self._logger.info(f"Released etcd lock on {lock.resource}")
                return True
            else:
                self._logger.warning(
                    f"Failed to release etcd lock on {lock.resource}: "
                    "concurrent modification"
                )
                return False
                
        except Exception as e:
            self._logger.error(f"Failed to release etcd lock: {e}")
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
            # Get current value
            value, metadata = self._etcd.get(lock_key)
            
            if not value:
                self._logger.warning(f"Lock not found for {lock.resource}")
                return False
            
            lock_data = self._decode_lock_value(value)
            
            # Verify lock ID
            if lock_data.get("lock_id") != lock.lock_id:
                self._logger.warning(
                    f"Lock ID mismatch for {lock.resource}"
                )
                return False
            
            # Get existing lease or create new one
            if lock.lock_id in self._leases:
                lease = self._leases[lock.lock_id]
                # Refresh lease TTL
                lease.refresh(ttl_seconds)
            else:
                # Create new lease and update key
                lease = self._etcd.lease(ttl_seconds)
                lock_value = self._encode_lock_value(lock)
                self._etcd.put(lock_key, lock_value, lease=lease)
                self._leases[lock.lock_id] = lease
            
            self._logger.info(
                f"Extended etcd lock on {lock.resource} (new ttl={ttl_seconds}s)"
            )
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to extend etcd lock: {e}")
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
        value, _ = self._etcd.get(lock_key)
        return value is not None
    
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
            value, metadata = self._etcd.get(lock_key)
            
            if value:
                lock_data = self._decode_lock_value(value)
                if lock_data:
                    # Get lease TTL if available
                    lease_id = metadata.lease_id if hasattr(metadata, 'lease_id') else None
                    if lease_id:
                        lease_info = self._etcd.get_lease_info(lease_id)
                        if lease_info:
                            lock_data["ttl_seconds"] = lease_info.TTL
                    
                    lock_data["resource"] = resource
                    return Lock.from_dict(lock_data)
            
            return None
        except Exception as e:
            self._logger.error(f"Failed to get etcd lock: {e}")
            return None
    
    def cleanup_stale(self) -> int:
        """
        Clean up expired/stale locks.
        
        Note: etcd automatically handles lease expiration, so this
        method returns 0 and is mainly for API compatibility.
        
        Returns:
            0 (etcd handles TTL automatically)
        """
        # etcd auto-expires leases, so no manual cleanup needed
        return 0
    
    def list_locks(self) -> list:
        """
        List all locks.
        
        Returns:
            List of Lock objects
        """
        locks = []
        
        try:
            # Get all keys with prefix
            for value, metadata in self._etcd.get_prefix(self.key_prefix):
                lock_data = self._decode_lock_value(value)
                if lock_data:
                    resource = metadata.key.decode('utf-8')[len(self.key_prefix):]
                    lock_data["resource"] = resource
                    locks.append(Lock.from_dict(lock_data))
        except Exception as e:
            self._logger.error(f"Failed to list etcd locks: {e}")
        
        return locks
    
    def get_stats(self) -> Dict[str, Any]:
        """Get lock backend statistics."""
        try:
            status = self._etcd.status()
            locks = self.list_locks()
            
            return {
                "backend_type": "EtcdLockBackend",
                "etcd_version": status.version,
                "cluster_id": status.cluster_id,
                "active_locks": len(locks),
                "key_prefix": self.key_prefix,
                "stats_available": True
            }
        except Exception as e:
            return {
                "backend_type": "EtcdLockBackend",
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
            result = self._etcd.delete(lock_key)
            if result:
                self._logger.warning(f"Force released etcd lock on {resource}")
                return True
            return False
        except Exception as e:
            self._logger.error(f"Failed to force release: {e}")
            return False
