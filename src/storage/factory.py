"""
Storage Backend Factory for TITAN FUSE Protocol.

ITEM-STOR-01: Factory Implementation

Provides factory functions to create storage backend instances
based on configuration.

Supported Backends:
- local: Local filesystem storage (default)
- s3: AWS S3 storage
- gcs: Google Cloud Storage

Author: TITAN FUSE Team
Version: 3.3.0
"""

from typing import Dict, Any, Optional
import logging

from src.storage.backend import StorageBackend, StorageError
from src.storage.local_backend import LocalStorageBackend


def get_storage_backend(config: Dict[str, Any] = None) -> StorageBackend:
    """
    Create a storage backend based on configuration.

    This factory function creates the appropriate storage backend
    instance based on the configuration settings.

    Config Structure:
        storage:
            backend: "local" | "s3" | "gcs"
            namespace: "default"
            local:
                base_path: "./.titan/storage"
            s3:
                bucket: "my-bucket"
                prefix: "titan"
                region: "us-east-1"
                credentials:
                    access_key: null
                    secret_key: null
            gcs:
                bucket: "my-bucket"
                prefix: "titan"
                project: "my-project"
                credentials_path: null

    Args:
        config: Configuration dictionary with storage settings

    Returns:
        StorageBackend instance

    Raises:
        StorageError: If backend creation fails

    Example:
        config = {
            'storage': {
                'backend': 's3',
                'namespace': 'production',
                's3': {
                    'bucket': 'my-checkpoints',
                    'region': 'us-west-2'
                }
            }
        }
        backend = get_storage_backend(config)
    """
    logger = logging.getLogger(__name__)

    # Default config
    storage_config = config.get('storage', {}) if config else {}
    backend_type = storage_config.get('backend', 'local').lower()
    namespace = storage_config.get('namespace', 'default')

    logger.info(f"Creating storage backend: {backend_type} (namespace: {namespace})")

    try:
        if backend_type == 'local':
            return _create_local_backend(storage_config, namespace)
        elif backend_type == 's3':
            return _create_s3_backend(storage_config, namespace)
        elif backend_type == 'gcs':
            return _create_gcs_backend(storage_config, namespace)
        else:
            raise StorageError(f"Unknown storage backend type: {backend_type}")

    except StorageError:
        raise
    except Exception as e:
        raise StorageError(f"Failed to create storage backend: {e}") from e


def _create_local_backend(config: Dict[str, Any], namespace: str) -> LocalStorageBackend:
    """Create local filesystem storage backend."""
    local_config = config.get('local', {})

    return LocalStorageBackend(
        base_path=local_config.get('base_path', './.titan/storage'),
        namespace=namespace,
        create_dirs=local_config.get('create_dirs', True)
    )


def _create_s3_backend(config: Dict[str, Any], namespace: str):
    """Create AWS S3 storage backend."""
    from src.storage.s3_backend import S3StorageBackend

    s3_config = config.get('s3', {})

    if not s3_config.get('bucket'):
        raise StorageError("S3 backend requires 'bucket' configuration")

    return S3StorageBackend(
        bucket=s3_config['bucket'],
        prefix=s3_config.get('prefix', ''),
        namespace=namespace,
        region=s3_config.get('region', 'us-east-1'),
        credentials=s3_config.get('credentials'),
        endpoint_url=s3_config.get('endpoint_url')
    )


def _create_gcs_backend(config: Dict[str, Any], namespace: str):
    """Create Google Cloud Storage backend."""
    from src.storage.gcs_backend import GCSStorageBackend

    gcs_config = config.get('gcs', {})

    if not gcs_config.get('bucket'):
        raise StorageError("GCS backend requires 'bucket' configuration")

    return GCSStorageBackend(
        bucket=gcs_config['bucket'],
        prefix=gcs_config.get('prefix', ''),
        namespace=namespace,
        project=gcs_config.get('project'),
        credentials_path=gcs_config.get('credentials_path')
    )


def get_default_storage_backend() -> StorageBackend:
    """
    Get default storage backend (local).

    Returns:
        LocalStorageBackend instance with default settings
    """
    return LocalStorageBackend(
        base_path='./.titan/storage',
        namespace='default',
        create_dirs=True
    )


def validate_storage_config(config: Dict[str, Any]) -> list:
    """
    Validate storage configuration.

    Args:
        config: Configuration dictionary

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    storage_config = config.get('storage', {})
    backend_type = storage_config.get('backend', 'local').lower()

    valid_backends = ['local', 's3', 'gcs']
    if backend_type not in valid_backends:
        errors.append(
            f"Invalid backend type '{backend_type}'. "
            f"Must be one of: {valid_backends}"
        )

    # Validate S3 config
    if backend_type == 's3':
        s3_config = storage_config.get('s3', {})
        if not s3_config.get('bucket'):
            errors.append("S3 backend requires 'storage.s3.bucket'")

    # Validate GCS config
    if backend_type == 'gcs':
        gcs_config = storage_config.get('gcs', {})
        if not gcs_config.get('bucket'):
            errors.append("GCS backend requires 'storage.gcs.bucket'")

    return errors


# Convenience aliases
create_storage_backend = get_storage_backend
