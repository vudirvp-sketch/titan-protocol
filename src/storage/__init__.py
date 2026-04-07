"""
Storage Module for TITAN FUSE Protocol.

ITEM-STOR-01: StorageBackend Abstraction

This module provides a unified storage abstraction layer that supports
multiple backends (local filesystem, S3, GCS) for checkpoint and state storage.

Key Components:
- StorageBackend: Abstract base class for storage operations
- LocalStorageBackend: Local filesystem storage
- S3StorageBackend: AWS S3 storage
- GCSStorageBackend: Google Cloud Storage
- get_storage_backend(): Factory function to create backends

Usage:
    from src.storage import get_storage_backend

    backend = get_storage_backend(config)
    backend.save("checkpoints/session-123/checkpoint.json", data)
    data = backend.load("checkpoints/session-123/checkpoint.json")

Author: TITAN FUSE Team
Version: 3.3.0
"""

from src.storage.backend import (
    StorageBackend,
    StorageMetadata,
    StorageError,
    FileNotFoundError,
    StorageConnectionError,
    StoragePermissionError
)
from src.storage.local_backend import LocalStorageBackend
from src.storage.factory import (
    get_storage_backend,
    get_default_storage_backend,
    validate_storage_config,
    create_storage_backend
)

# Lazy imports for cloud backends (optional dependencies)
def get_s3_backend(*args, **kwargs):
    """Get S3 backend (lazy import)."""
    from src.storage.s3_backend import S3StorageBackend
    return S3StorageBackend(*args, **kwargs)

def get_gcs_backend(*args, **kwargs):
    """Get GCS backend (lazy import)."""
    from src.storage.gcs_backend import GCSStorageBackend
    return GCSStorageBackend(*args, **kwargs)


__all__ = [
    # Base classes
    'StorageBackend',
    'StorageMetadata',
    'StorageError',
    'FileNotFoundError',
    'StorageConnectionError',
    'StoragePermissionError',

    # Backends
    'LocalStorageBackend',
    'get_s3_backend',
    'get_gcs_backend',

    # Factory
    'get_storage_backend',
    'get_default_storage_backend',
    'validate_storage_config',
    'create_storage_backend',
]
