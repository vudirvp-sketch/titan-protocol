"""
Storage Backend Base Class for TITAN FUSE Protocol.

ITEM-STOR-01: StorageBackend Abstraction

Provides a unified interface for storage operations across different backends.
Supports local filesystem, S3, and GCS through a common API.

Features:
- Namespace isolation (checkpoints/{session_id}/)
- Metadata support
- Atomic operations
- Error handling

Author: TITAN FUSE Team
Version: 3.3.0
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging
import hashlib


class StorageError(Exception):
    """Base exception for storage errors."""
    pass


class FileNotFoundError(StorageError):
    """Raised when a file is not found in storage."""
    def __init__(self, path: str):
        self.path = path
        super().__init__(f"File not found in storage: {path}")


class StorageConnectionError(StorageError):
    """Raised when there's a connection error with the storage backend."""
    def __init__(self, backend: str, message: str):
        self.backend = backend
        super().__init__(f"Storage connection error ({backend}): {message}")


class StoragePermissionError(StorageError):
    """Raised when there's a permission error with storage operations."""
    def __init__(self, path: str, operation: str):
        self.path = path
        self.operation = operation
        super().__init__(f"Permission denied for {operation} on: {path}")


@dataclass
class StorageMetadata:
    """
    Metadata for a stored object.

    Attributes:
        path: Object path
        size: Size in bytes
        content_type: MIME type if available
        last_modified: Last modification timestamp
        etag: Entity tag for versioning
        custom: Custom metadata key-value pairs
    """
    path: str
    size: int = 0
    content_type: Optional[str] = None
    last_modified: Optional[str] = None
    etag: Optional[str] = None
    custom: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'path': self.path,
            'size': self.size,
            'content_type': self.content_type,
            'last_modified': self.last_modified,
            'etag': self.etag,
            'custom': self.custom
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StorageMetadata':
        """Create from dictionary."""
        return cls(
            path=data.get('path', ''),
            size=data.get('size', 0),
            content_type=data.get('content_type'),
            last_modified=data.get('last_modified'),
            etag=data.get('etag'),
            custom=data.get('custom', {})
        )


class StorageBackend(ABC):
    """
    Abstract base class for storage backends.

    ITEM-STOR-01 Implementation:
    - save(path: str, data: bytes) -> None
    - load(path: str) -> bytes
    - exists(path: str) -> bool
    - delete(path: str) -> None
    - list(prefix: str) -> list[str]
    - get_metadata(path: str) -> dict

    This abstraction allows TITAN to store checkpoints and state
    on local filesystem, S3, or GCS without changing application code.

    Namespace Isolation:
        All paths should use the pattern: {namespace}/{session_id}/filename
        Example: checkpoints/session-abc123/checkpoint.json

    Implementations must ensure:
        - Atomic writes (no partial writes on failure)
        - Namespace isolation between sessions
        - Proper error handling and reporting
        - Thread/process safety

    Usage:
        backend = LocalStorageBackend(base_path="./data")
        backend.save("checkpoints/session-123/data.json", b'{"key": "value"}')
        data = backend.load("checkpoints/session-123/data.json")
    """

    def __init__(self, namespace: str = "default"):
        """
        Initialize storage backend.

        Args:
            namespace: Namespace for path isolation
        """
        self.namespace = namespace
        self._logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def save(self, path: str, data: bytes, metadata: Dict[str, str] = None) -> str:
        """
        Save data to storage.

        Args:
            path: Object path (relative to namespace)
            data: Data to save as bytes
            metadata: Optional metadata to store with the object

        Returns:
            Full path where data was saved

        Raises:
            StorageError: If save fails
            StoragePermissionError: If permission denied
        """
        pass

    @abstractmethod
    def load(self, path: str) -> bytes:
        """
        Load data from storage.

        Args:
            path: Object path (relative to namespace)

        Returns:
            Data as bytes

        Raises:
            FileNotFoundError: If path doesn't exist
            StorageError: If load fails
        """
        pass

    @abstractmethod
    def exists(self, path: str) -> bool:
        """
        Check if a path exists in storage.

        Args:
            path: Object path (relative to namespace)

        Returns:
            True if exists, False otherwise
        """
        pass

    @abstractmethod
    def delete(self, path: str) -> bool:
        """
        Delete an object from storage.

        Args:
            path: Object path (relative to namespace)

        Returns:
            True if deleted, False if didn't exist

        Raises:
            StorageError: If delete fails
            StoragePermissionError: If permission denied
        """
        pass

    @abstractmethod
    def list(self, prefix: str = "") -> List[str]:
        """
        List objects with a given prefix.

        Args:
            prefix: Path prefix to filter (relative to namespace)

        Returns:
            List of object paths (relative to namespace)
        """
        pass

    @abstractmethod
    def get_metadata(self, path: str) -> StorageMetadata:
        """
        Get metadata for an object.

        Args:
            path: Object path (relative to namespace)

        Returns:
            StorageMetadata for the object

        Raises:
            FileNotFoundError: If path doesn't exist
        """
        pass

    @abstractmethod
    def copy(self, src_path: str, dst_path: str) -> str:
        """
        Copy an object within the same storage backend.

        Args:
            src_path: Source path
            dst_path: Destination path

        Returns:
            Full destination path

        Raises:
            FileNotFoundError: If source doesn't exist
            StorageError: If copy fails
        """
        pass

    # Helper methods with default implementations

    def save_json(self, path: str, data: Dict) -> str:
        """
        Save JSON data to storage.

        Args:
            path: Object path
            data: Dictionary to save as JSON

        Returns:
            Full path where data was saved
        """
        import json
        json_bytes = json.dumps(data, indent=2, default=str).encode('utf-8')
        return self.save(path, json_bytes, {'content_type': 'application/json'})

    def load_json(self, path: str) -> Dict:
        """
        Load JSON data from storage.

        Args:
            path: Object path

        Returns:
            Dictionary from JSON
        """
        import json
        data = self.load(path)
        return json.loads(data.decode('utf-8'))

    def save_text(self, path: str, text: str) -> str:
        """
        Save text data to storage.

        Args:
            path: Object path
            text: Text to save

        Returns:
            Full path where data was saved
        """
        return self.save(path, text.encode('utf-8'), {'content_type': 'text/plain'})

    def load_text(self, path: str) -> str:
        """
        Load text data from storage.

        Args:
            path: Object path

        Returns:
            Text content
        """
        data = self.load(path)
        return data.decode('utf-8')

    def get_namespace_path(self, path: str) -> str:
        """
        Get full path with namespace prefix.

        Args:
            path: Relative path

        Returns:
            Path with namespace prefix
        """
        if not self.namespace:
            return path
        return f"{self.namespace}/{path}"

    def compute_checksum(self, data: bytes) -> str:
        """
        Compute SHA-256 checksum of data.

        Args:
            data: Data to hash

        Returns:
            Hexadecimal checksum string
        """
        return hashlib.sha256(data).hexdigest()

    def health_check(self) -> Dict[str, Any]:
        """
        Check if the storage backend is healthy.

        Returns:
            Dict with 'healthy' boolean and 'message' string
        """
        try:
            # Try to list objects as a basic health check
            self.list()
            return {
                'healthy': True,
                'backend': self.__class__.__name__,
                'namespace': self.namespace,
                'message': 'Storage backend is operational'
            }
        except Exception as e:
            return {
                'healthy': False,
                'backend': self.__class__.__name__,
                'namespace': self.namespace,
                'message': str(e)
            }

    def get_stats(self) -> Dict[str, Any]:
        """
        Get storage backend statistics.

        Returns:
            Dict with backend stats
        """
        return {
            'backend_type': self.__class__.__name__,
            'namespace': self.namespace,
            'stats_available': False
        }

    # Session isolation helpers

    def get_session_path(self, session_id: str, filename: str = "") -> str:
        """
        Get path for a session's data.

        Args:
            session_id: Session identifier
            filename: Optional filename within session directory

        Returns:
            Path like: sessions/{session_id}/{filename}
        """
        if filename:
            return f"sessions/{session_id}/{filename}"
        return f"sessions/{session_id}"

    def get_checkpoint_path(self, session_id: str, filename: str = "checkpoint.json") -> str:
        """
        Get path for a session's checkpoint.

        Args:
            session_id: Session identifier
            filename: Checkpoint filename

        Returns:
            Path like: checkpoints/{session_id}/{filename}
        """
        return f"checkpoints/{session_id}/{filename}"

    def list_sessions(self) -> List[str]:
        """
        List all session IDs with data in storage.

        Returns:
            List of session IDs
        """
        session_paths = self.list("sessions/")
        sessions = set()
        for path in session_paths:
            parts = path.split('/')
            if len(parts) >= 2:
                sessions.add(parts[1])
        return list(sessions)

    def list_checkpoints(self) -> List[str]:
        """
        List all session IDs with checkpoints.

        Returns:
            List of session IDs with checkpoints
        """
        checkpoint_paths = self.list("checkpoints/")
        sessions = set()
        for path in checkpoint_paths:
            parts = path.split('/')
            if len(parts) >= 2:
                sessions.add(parts[1])
        return list(sessions)

    def delete_session(self, session_id: str) -> int:
        """
        Delete all data for a session.

        Args:
            session_id: Session identifier

        Returns:
            Number of files deleted
        """
        count = 0

        # Delete session data
        session_prefix = f"sessions/{session_id}/"
        for path in self.list(session_prefix):
            self.delete(path)
            count += 1

        # Delete checkpoints
        checkpoint_prefix = f"checkpoints/{session_id}/"
        for path in self.list(checkpoint_prefix):
            self.delete(path)
            count += 1

        return count

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(namespace='{self.namespace}')>"
