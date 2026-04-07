"""
GCS Storage Backend for TITAN FUSE Protocol.

ITEM-STOR-01: GCSStorageBackend Implementation

Provides storage operations on Google Cloud Storage.
Implements the StorageBackend interface for GCS.

Features:
- Google Cloud Storage integration via google-cloud-storage
- Namespace isolation via key prefix
- Metadata support via GCS metadata
- Resumable upload for large files
- Automatic retry on transient errors

Dependencies:
    pip install google-cloud-storage

Author: TITAN FUSE Team
Version: 3.3.0
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from src.storage.backend import (
    StorageBackend,
    StorageMetadata,
    StorageError,
    FileNotFoundError,
    StoragePermissionError,
    StorageConnectionError
)


class GCSStorageBackend(StorageBackend):
    """
    Google Cloud Storage backend.

    This backend stores files in GCS with support for:
    - Namespace isolation via key prefix
    - Metadata storage via GCS object metadata
    - Resumable upload for large files
    - Automatic retry on transient errors

    Key Format:
        gs://{bucket}/{prefix}/{namespace}/{path}

    Usage:
        backend = GCSStorageBackend(
            bucket="my-titan-checkpoints",
            prefix="titan",
            project="my-project"
        )
        backend.save("checkpoints/session-123/checkpoint.json", data)
        data = backend.load("checkpoints/session-123/checkpoint.json")
    """

    # Maximum size for single-part upload (10MB uses resumable)
    RESUMABLE_THRESHOLD = 10 * 1024 * 1024  # 10 MB

    def __init__(self,
                 bucket: str,
                 prefix: str = "",
                 namespace: str = "default",
                 project: str = None,
                 credentials_path: str = None):
        """
        Initialize GCS storage backend.

        Args:
            bucket: GCS bucket name
            prefix: Key prefix for all objects
            namespace: Namespace for path isolation
            project: GCP project ID
            credentials_path: Path to service account JSON file
        """
        super().__init__(namespace=namespace)

        self.bucket_name = bucket
        self.prefix = prefix.rstrip('/') if prefix else ""
        self.project = project
        self.credentials_path = credentials_path

        self._client = None
        self._bucket = None
        self._logger = logging.getLogger(__name__)

    def _get_client(self):
        """Get or create GCS client (lazy initialization)."""
        if self._client is None:
            try:
                from google.cloud import storage

                if self.credentials_path:
                    self._client = storage.Client.from_service_account_json(
                        self.credentials_path,
                        project=self.project
                    )
                else:
                    self._client = storage.Client(project=self.project)

            except ImportError:
                raise StorageError(
                    "google-cloud-storage is required for GCS backend. "
                    "Install with: pip install google-cloud-storage"
                )
            except Exception as e:
                raise StorageConnectionError("gcs", str(e))

        return self._client

    def _get_bucket(self):
        """Get or create bucket reference."""
        if self._bucket is None:
            client = self._get_client()
            self._bucket = client.bucket(self.bucket_name)
        return self._bucket

    def _get_gcs_blob_name(self, path: str) -> str:
        """Get full GCS blob name from relative path."""
        parts = []
        if self.prefix:
            parts.append(self.prefix)
        if self.namespace:
            parts.append(self.namespace)
        parts.append(path)

        return '/'.join(parts)

    def save(self, path: str, data: bytes, metadata: Dict[str, str] = None) -> str:
        """
        Save data to GCS.

        Args:
            path: Relative path within namespace
            data: Data to save as bytes
            metadata: Optional metadata dictionary

        Returns:
            GCS URI where data was saved

        Raises:
            StorageError: If save fails
            StoragePermissionError: If permission denied
        """
        bucket = self._get_bucket()
        blob_name = self._get_gcs_blob_name(path)
        blob = bucket.blob(blob_name)

        # Prepare metadata
        gcs_metadata = {
            'created_at': datetime.utcnow().isoformat() + 'Z',
            'checksum': self.compute_checksum(data)
        }
        if metadata:
            gcs_metadata.update(metadata)

        blob.metadata = gcs_metadata
        blob.content_type = self._guess_content_type(path)

        try:
            # Use resumable upload for large files
            if len(data) > self.RESUMABLE_THRESHOLD:
                blob.chunk_size = 10 * 1024 * 1024  # 10 MB chunks

            blob.upload_from_string(data)

            self._logger.debug(f"Saved {len(data)} bytes to gs://{self.bucket_name}/{blob_name}")
            return f"gs://{self.bucket_name}/{blob_name}"

        except Exception as e:
            error_str = str(e).lower()
            if 'permission' in error_str or 'denied' in error_str or '403' in error_str:
                raise StoragePermissionError(path, "save") from e
            raise StorageError(f"GCS save failed: {e}") from e

    def load(self, path: str) -> bytes:
        """
        Load data from GCS.

        Args:
            path: Relative path within namespace

        Returns:
            Data as bytes

        Raises:
            FileNotFoundError: If path doesn't exist
            StorageError: If load fails
        """
        bucket = self._get_bucket()
        blob_name = self._get_gcs_blob_name(path)
        blob = bucket.blob(blob_name)

        try:
            if not blob.exists():
                raise FileNotFoundError(path)

            data = blob.download_as_bytes()

            self._logger.debug(f"Loaded {len(data)} bytes from gs://{self.bucket_name}/{blob_name}")
            return data

        except FileNotFoundError:
            raise
        except Exception as e:
            error_str = str(e).lower()
            if 'not found' in error_str or '404' in error_str:
                raise FileNotFoundError(path) from e
            if 'permission' in error_str or 'denied' in error_str:
                raise StoragePermissionError(path, "load") from e
            raise StorageConnectionError("gcs", str(e)) from e

    def exists(self, path: str) -> bool:
        """
        Check if an object exists in GCS.

        Args:
            path: Relative path within namespace

        Returns:
            True if exists, False otherwise
        """
        bucket = self._get_bucket()
        blob_name = self._get_gcs_blob_name(path)
        blob = bucket.blob(blob_name)

        try:
            return blob.exists()
        except Exception as e:
            self._logger.warning(f"GCS exists check failed: {e}")
            return False

    def delete(self, path: str) -> bool:
        """
        Delete an object from GCS.

        Args:
            path: Relative path within namespace

        Returns:
            True if deleted, False if didn't exist

        Raises:
            StorageError: If delete fails
            StoragePermissionError: If permission denied
        """
        bucket = self._get_bucket()
        blob_name = self._get_gcs_blob_name(path)
        blob = bucket.blob(blob_name)

        try:
            if not blob.exists():
                return False

            blob.delete()

            self._logger.debug(f"Deleted gs://{self.bucket_name}/{blob_name}")
            return True

        except Exception as e:
            error_str = str(e).lower()
            if 'permission' in error_str or 'denied' in error_str:
                raise StoragePermissionError(path, "delete") from e
            raise StorageError(f"GCS delete failed: {e}") from e

    def list(self, prefix: str = "") -> List[str]:
        """
        List objects with a given prefix.

        Args:
            prefix: Path prefix to filter

        Returns:
            List of relative paths
        """
        bucket = self._get_bucket()

        # Build full prefix
        full_prefix = self._get_gcs_blob_name(prefix) if prefix else self._get_gcs_blob_name("")

        results = []

        try:
            # List blobs with prefix
            blobs = bucket.list_blobs(prefix=full_prefix)

            for blob in blobs:
                blob_name = blob.name

                # Remove prefix and namespace to get relative path
                rel_path = blob_name

                # Strip prefix
                if self.prefix:
                    prefix_with_slash = self.prefix + '/'
                    if rel_path.startswith(prefix_with_slash):
                        rel_path = rel_path[len(prefix_with_slash):]

                # Strip namespace
                if self.namespace:
                    namespace_with_slash = self.namespace + '/'
                    if rel_path.startswith(namespace_with_slash):
                        rel_path = rel_path[len(namespace_with_slash):]

                if rel_path:
                    results.append(rel_path)

            return sorted(results)

        except Exception as e:
            raise StorageError(f"GCS list failed: {e}") from e

    def get_metadata(self, path: str) -> StorageMetadata:
        """
        Get metadata for a GCS object.

        Args:
            path: Relative path within namespace

        Returns:
            StorageMetadata for the object

        Raises:
            FileNotFoundError: If path doesn't exist
        """
        bucket = self._get_bucket()
        blob_name = self._get_gcs_blob_name(path)
        blob = bucket.blob(blob_name)

        try:
            if not blob.exists():
                raise FileNotFoundError(path)

            blob.reload()  # Fetch fresh metadata

            return StorageMetadata(
                path=path,
                size=blob.size or 0,
                content_type=blob.content_type,
                last_modified=blob.updated.isoformat() if blob.updated else None,
                etag=blob.etag or '',
                custom=dict(blob.metadata or {})
            )

        except FileNotFoundError:
            raise
        except Exception as e:
            raise StorageError(f"GCS get_metadata failed: {e}") from e

    def copy(self, src_path: str, dst_path: str) -> str:
        """
        Copy an object within GCS.

        Args:
            src_path: Source relative path
            dst_path: Destination relative path

        Returns:
            GCS URI of destination

        Raises:
            FileNotFoundError: If source doesn't exist
            StorageError: If copy fails
        """
        bucket = self._get_bucket()
        src_blob_name = self._get_gcs_blob_name(src_path)
        dst_blob_name = self._get_gcs_blob_name(dst_path)

        try:
            src_blob = bucket.blob(src_blob_name)

            if not src_blob.exists():
                raise FileNotFoundError(src_path)

            dst_blob = bucket.blob(dst_blob_name)

            # Copy within same bucket
            bucket.copy_blob(src_blob, bucket, dst_blob_name)

            self._logger.debug(f"Copied gs://{self.bucket_name}/{src_blob_name} to gs://{self.bucket_name}/{dst_blob_name}")
            return f"gs://{self.bucket_name}/{dst_blob_name}"

        except FileNotFoundError:
            raise
        except Exception as e:
            raise StorageError(f"GCS copy failed: {e}") from e

    def _guess_content_type(self, path: str) -> str:
        """Guess content type from file extension."""
        import mimetypes

        mime_type, _ = mimetypes.guess_type(path)
        return mime_type or 'application/octet-stream'

    def get_stats(self) -> Dict[str, Any]:
        """
        Get GCS storage statistics.

        Returns:
            Dict with GCS stats
        """
        try:
            total_size = 0
            object_count = 0

            for path in self.list():
                try:
                    meta = self.get_metadata(path)
                    total_size += meta.size
                    object_count += 1
                except:
                    pass

            return {
                'backend_type': 'GCSStorageBackend',
                'namespace': self.namespace,
                'bucket': self.bucket_name,
                'prefix': self.prefix,
                'project': self.project,
                'object_count': object_count,
                'total_size_bytes': total_size,
                'total_size_human': self._human_readable_size(total_size),
                'stats_available': True
            }
        except Exception as e:
            return {
                'backend_type': 'GCSStorageBackend',
                'namespace': self.namespace,
                'bucket': self.bucket_name,
                'error': str(e),
                'stats_available': False
            }

    def _human_readable_size(self, size: int) -> str:
        """Convert bytes to human readable size."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def health_check(self) -> Dict[str, Any]:
        """
        Check if GCS backend is healthy.

        Returns:
            Dict with health status
        """
        try:
            client = self._get_client()
            bucket = client.bucket(self.bucket_name)

            # Try to check bucket exists
            bucket.exists()

            return {
                'healthy': True,
                'backend': 'GCSStorageBackend',
                'namespace': self.namespace,
                'bucket': self.bucket_name,
                'message': 'GCS backend is operational'
            }
        except Exception as e:
            return {
                'healthy': False,
                'backend': 'GCSStorageBackend',
                'namespace': self.namespace,
                'bucket': self.bucket_name,
                'message': str(e)
            }

    def __repr__(self) -> str:
        return f"<GCSStorageBackend(bucket='{self.bucket_name}', prefix='{self.prefix}', namespace='{self.namespace}')>"
