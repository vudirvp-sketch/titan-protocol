"""
Distributed Locking Module for TITAN FUSE Protocol.

ITEM-ARCH-03: Distributed Locking with TTL

Provides distributed locking mechanisms with TTL-based expiration
for preventing deadlocks during crashes.

Backends:
- FileLockBackend: Local file-based locking with TTL via timestamp
- RedisLockBackend: Redis-based distributed locking with SET NX EX
- EtcdLockBackend: etcd-based distributed locking with leases

Author: TITAN FUSE Team
Version: 3.3.0
"""

from .backend import LockBackend, Lock, LockStatus
from .file_lock import FileLockBackend
from .factory import get_lock_backend, create_lock_backend

__all__ = [
    'LockBackend',
    'Lock',
    'LockStatus',
    'FileLockBackend',
    'get_lock_backend',
    'create_lock_backend',
]
