"""
S3 Storage Backend for TITAN FUSE Protocol.

ITEM-STOR-01: S3StorageBackend Implementation

Provides storage operations on AWS S3.
Implements the StorageBackend interface for cloud storage.

Features:
- AWS S3 integration via boto3
- Namespace isolation via key prefix
- Metadata support via S3 metadata
- Multipart upload for large files
- Automatic retry on transient errors

Dependencies:
    pip install boto3

Author: TITAN FUSE Team
Version: 3.3.0
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
import hashlib

from src.storage.backend import (
    StorageBackend,
    StorageMetadata,
    StorageError,
    FileNotFoundError,
    StoragePermissionError,
    StorageConnectionError
)


class S3StorageBackend(StorageBackend):
    """
    AWS S3 storage backend.

    This backend stores files in AWS S3 with support for:
    - Namespace isolation via key prefix
    - Metadata storage via S3 object metadata
    - Multipart upload for large files
    - Automatic retry on transient errors

    Key Format:
        s3://{bucket}/{prefix}/{namespace}/{path}

    Usage:
        backend = S3StorageBackend(
            bucket="my-titan-checkpoints",
            prefix="titan",
            region="us-east-1"
        )
        backend.save("checkpoints/session-123/checkpoint.json", data)
        data = backend.load("checkpoints/session-123/checkpoint.json")
    """

    # Maximum size for single-part upload (5MB - 5GB uses multipart)
    MULTIPART_THRESHOLD = 5 * 1024 * 1024  # 5 MB
    MULTIPART_CHUNKSIZE = 10 * 1024 * 1024  # 10 MB

    def __init__(self,
                 bucket: str,
                 prefix: str = "",
                 namespace: str = "default",
                 region: str = "us-east-1",
                 credentials: Dict[str, str] = None,
                 endpoint_url: str = None):
        """
        Initialize S3 storage backend.

        Args:
            bucket: S3 bucket name
            prefix: Key prefix for all objects
            namespace: Namespace for path isolation
            region: AWS region
            credentials: Optional dict with 'access_key' and 'secret_key'
            endpoint_url: Optional custom endpoint (for S3-compatible services)
        """
        super().__init__(namespace=namespace)

        self.bucket = bucket
        self.prefix = prefix.rstrip('/') if prefix else ""
        self.region = region
        self.credentials = credentials or {}
        self.endpoint_url = endpoint_url

        self._client = None
        self._logger = logging.getLogger(__name__)

    def _get_client(self):
        """Get or create S3 client (lazy initialization)."""
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config

                # Configure retry strategy
                config = Config(
                    retries={
                        'max_attempts': 3,
                        'mode': 'standard'
                    }
                )

                session_kwargs = {'region_name': self.region}

                if self.credentials:
                    session_kwargs.update({
                        'aws_access_key_id': self.credentials.get('access_key'),
                        'aws_secret_access_key': self.credentials.get('secret_key'),
                        'aws_session_token': self.credentials.get('session_token')
                    })

                if self.endpoint_url:
                    session_kwargs['endpoint_url'] = self.endpoint_url

                self._client = boto3.client('s3', config=config, **session_kwargs)

            except ImportError:
                raise StorageError(
                    "boto3 is required for S3 backend. "
                    "Install with: pip install boto3"
                )
            except Exception as e:
                raise StorageConnectionError("s3", str(e))

        return self._client

    def _get_s3_key(self, path: str) -> str:
        """Get full S3 key from relative path."""
        parts = []
        if self.prefix:
            parts.append(self.prefix)
        if self.namespace:
            parts.append(self.namespace)
        parts.append(path)

        return '/'.join(parts)

    def save(self, path: str, data: bytes, metadata: Dict[str, str] = None) -> str:
        """
        Save data to S3.

        Args:
            path: Relative path within namespace
            data: Data to save as bytes
            metadata: Optional metadata dictionary

        Returns:
            S3 URI where data was saved

        Raises:
            StorageError: If save fails
            StoragePermissionError: If permission denied
        """
        client = self._get_client()
        key = self._get_s3_key(path)

        # Prepare S3 metadata
        s3_metadata = {
            'created_at': datetime.utcnow().isoformat() + 'Z',
            'checksum': self.compute_checksum(data)
        }
        if metadata:
            # S3 metadata keys must be strings
            s3_metadata.update({str(k): str(v) for k, v in metadata.items()})

        try:
            # Use multipart upload for large files
            if len(data) > self.MULTIPART_THRESHOLD:
                self._multipart_upload(key, data, s3_metadata)
            else:
                client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=data,
                    Metadata=s3_metadata,
                    ContentType=self._guess_content_type(path)
                )

            self._logger.debug(f"Saved {len(data)} bytes to s3://{self.bucket}/{key}")
            return f"s3://{self.bucket}/{key}"

        except client.exceptions.ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code in ['AccessDenied', '403']:
                raise StoragePermissionError(path, "save") from e
            raise StorageError(f"S3 save failed: {e}") from e
        except Exception as e:
            raise StorageConnectionError("s3", str(e)) from e

    def _multipart_upload(self, key: str, data: bytes, metadata: Dict[str, str]) -> None:
        """Perform multipart upload for large files."""
        client = self._get_client()

        try:
            # Initiate multipart upload
            upload = client.create_multipart_upload(
                Bucket=self.bucket,
                Key=key,
                Metadata=metadata,
                ContentType=self._guess_content_type(key)
            )
            upload_id = upload['UploadId']

            parts = []
            part_number = 1
            offset = 0

            try:
                while offset < len(data):
                    chunk = data[offset:offset + self.MULTIPART_CHUNKSIZE]

                    response = client.upload_part(
                        Bucket=self.bucket,
                        Key=key,
                        PartNumber=part_number,
                        UploadId=upload_id,
                        Body=chunk
                    )

                    parts.append({
                        'PartNumber': part_number,
                        'ETag': response['ETag']
                    })

                    offset += self.MULTIPART_CHUNKSIZE
                    part_number += 1

                # Complete multipart upload
                client.complete_multipart_upload(
                    Bucket=self.bucket,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={'Parts': parts}
                )

            except Exception as e:
                # Abort multipart upload on failure
                try:
                    client.abort_multipart_upload(
                        Bucket=self.bucket,
                        Key=key,
                        UploadId=upload_id
                    )
                except:
                    pass
                raise e

        except Exception as e:
            raise StorageError(f"S3 multipart upload failed: {e}") from e

    def load(self, path: str) -> bytes:
        """
        Load data from S3.

        Args:
            path: Relative path within namespace

        Returns:
            Data as bytes

        Raises:
            FileNotFoundError: If path doesn't exist
            StorageError: If load fails
        """
        client = self._get_client()
        key = self._get_s3_key(path)

        try:
            response = client.get_object(Bucket=self.bucket, Key=key)
            data = response['Body'].read()

            self._logger.debug(f"Loaded {len(data)} bytes from s3://{self.bucket}/{key}")
            return data

        except client.exceptions.NoSuchKey:
            raise FileNotFoundError(path)
        except client.exceptions.ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'NoSuchKey':
                raise FileNotFoundError(path) from e
            if error_code in ['AccessDenied', '403']:
                raise StoragePermissionError(path, "load") from e
            raise StorageError(f"S3 load failed: {e}") from e
        except Exception as e:
            raise StorageConnectionError("s3", str(e)) from e

    def exists(self, path: str) -> bool:
        """
        Check if an object exists in S3.

        Args:
            path: Relative path within namespace

        Returns:
            True if exists, False otherwise
        """
        client = self._get_client()
        key = self._get_s3_key(path)

        try:
            client.head_object(Bucket=self.bucket, Key=key)
            return True
        except client.exceptions.ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code in ['404', 'NoSuchKey']:
                return False
            raise StorageError(f"S3 exists check failed: {e}") from e

    def delete(self, path: str) -> bool:
        """
        Delete an object from S3.

        Args:
            path: Relative path within namespace

        Returns:
            True if deleted, False if didn't exist

        Raises:
            StorageError: If delete fails
            StoragePermissionError: If permission denied
        """
        client = self._get_client()
        key = self._get_s3_key(path)

        try:
            # Check if exists first
            if not self.exists(path):
                return False

            client.delete_object(Bucket=self.bucket, Key=key)
            self._logger.debug(f"Deleted s3://{self.bucket}/{key}")
            return True

        except client.exceptions.ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code in ['AccessDenied', '403']:
                raise StoragePermissionError(path, "delete") from e
            raise StorageError(f"S3 delete failed: {e}") from e

    def list(self, prefix: str = "") -> List[str]:
        """
        List objects with a given prefix.

        Args:
            prefix: Path prefix to filter

        Returns:
            List of relative paths
        """
        client = self._get_client()

        # Build full prefix
        full_prefix = self._get_s3_key(prefix) if prefix else self._get_s3_key("")

        results = []

        try:
            paginator = client.get_paginator('list_objects_v2')

            for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
                for obj in page.get('Contents', []):
                    key = obj['Key']

                    # Remove prefix and namespace to get relative path
                    rel_path = key

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

        except client.exceptions.ClientError as e:
            raise StorageError(f"S3 list failed: {e}") from e

    def get_metadata(self, path: str) -> StorageMetadata:
        """
        Get metadata for an S3 object.

        Args:
            path: Relative path within namespace

        Returns:
            StorageMetadata for the object

        Raises:
            FileNotFoundError: If path doesn't exist
        """
        client = self._get_client()
        key = self._get_s3_key(path)

        try:
            response = client.head_object(Bucket=self.bucket, Key=key)

            return StorageMetadata(
                path=path,
                size=response.get('ContentLength', 0),
                content_type=response.get('ContentType'),
                last_modified=response.get('LastModified').isoformat() if response.get('LastModified') else None,
                etag=response.get('ETag', '').strip('"'),
                custom=response.get('Metadata', {})
            )

        except client.exceptions.ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code in ['404', 'NoSuchKey']:
                raise FileNotFoundError(path) from e
            raise StorageError(f"S3 get_metadata failed: {e}") from e

    def copy(self, src_path: str, dst_path: str) -> str:
        """
        Copy an object within S3.

        Args:
            src_path: Source relative path
            dst_path: Destination relative path

        Returns:
            S3 URI of destination

        Raises:
            FileNotFoundError: If source doesn't exist
            StorageError: If copy fails
        """
        client = self._get_client()
        src_key = self._get_s3_key(src_path)
        dst_key = self._get_s3_key(dst_path)

        try:
            # Check source exists
            if not self.exists(src_path):
                raise FileNotFoundError(src_path)

            # Copy object
            client.copy_object(
                Bucket=self.bucket,
                Key=dst_key,
                CopySource={'Bucket': self.bucket, 'Key': src_key}
            )

            self._logger.debug(f"Copied s3://{self.bucket}/{src_key} to s3://{self.bucket}/{dst_key}")
            return f"s3://{self.bucket}/{dst_key}"

        except client.exceptions.ClientError as e:
            raise StorageError(f"S3 copy failed: {e}") from e

    def _guess_content_type(self, path: str) -> str:
        """Guess content type from file extension."""
        import mimetypes

        mime_type, _ = mimetypes.guess_type(path)
        return mime_type or 'application/octet-stream'

    def get_stats(self) -> Dict[str, Any]:
        """
        Get S3 storage statistics.

        Returns:
            Dict with S3 stats
        """
        try:
            client = self._get_client()

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
                'backend_type': 'S3StorageBackend',
                'namespace': self.namespace,
                'bucket': self.bucket,
                'prefix': self.prefix,
                'region': self.region,
                'object_count': object_count,
                'total_size_bytes': total_size,
                'total_size_human': self._human_readable_size(total_size),
                'stats_available': True
            }
        except Exception as e:
            return {
                'backend_type': 'S3StorageBackend',
                'namespace': self.namespace,
                'bucket': self.bucket,
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
        Check if S3 backend is healthy.

        Returns:
            Dict with health status
        """
        try:
            client = self._get_client()

            # Try to head the bucket
            client.head_bucket(Bucket=self.bucket)

            return {
                'healthy': True,
                'backend': 'S3StorageBackend',
                'namespace': self.namespace,
                'bucket': self.bucket,
                'message': 'S3 backend is operational'
            }
        except Exception as e:
            return {
                'healthy': False,
                'backend': 'S3StorageBackend',
                'namespace': self.namespace,
                'bucket': self.bucket,
                'message': str(e)
            }

    def __repr__(self) -> str:
        return f"<S3StorageBackend(bucket='{self.bucket}', prefix='{self.prefix}', namespace='{self.namespace}')>"
