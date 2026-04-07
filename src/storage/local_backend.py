"""
Local Storage Backend for TITAN FUSE Protocol.

ITEM-STOR-01: LocalStorageBackend Implementation

Provides storage operations on the local filesystem.
Implements atomic writes and namespace isolation.

Features:
- Atomic writes via temp file + rename
- Namespace isolation via directory structure
- Metadata storage in companion .meta files
- Automatic directory creation

Author: TITAN FUSE Team
Version: 3.3.0
"""

import os
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import json
import logging

from src.storage.backend import (
    StorageBackend,
    StorageMetadata,
    StorageError,
    FileNotFoundError,
    StoragePermissionError,
    StorageConnectionError
)


class LocalStorageBackend(StorageBackend):
    """
    Local filesystem storage backend.

    This backend stores files on the local filesystem with support for:
    - Atomic writes (write to temp, then rename)
    - Metadata storage in companion .meta files
    - Namespace isolation via directory structure
    - Automatic directory creation

    Directory Structure:
        {base_path}/
        ├── {namespace}/
        │   ├── sessions/
        │   │   └── {session_id}/
        │   │       └── ...
        │   └── checkpoints/
        │       └── {session_id}/
        │           ├── checkpoint.json
        │           └── checkpoint.json.meta

    Usage:
        backend = LocalStorageBackend(base_path="./data")
        backend.save("checkpoints/session-123/checkpoint.json", data)
        data = backend.load("checkpoints/session-123/checkpoint.json")
    """

    def __init__(self, base_path: str = "./.titan/storage",
                 namespace: str = "default",
                 create_dirs: bool = True):
        """
        Initialize local storage backend.

        Args:
            base_path: Base directory for all storage
            namespace: Namespace for path isolation
            create_dirs: Whether to create directories automatically
        """
        super().__init__(namespace=namespace)

        self.base_path = Path(base_path).resolve()
        self.create_dirs = create_dirs

        # Full path includes namespace
        self._full_base_path = self.base_path / self.namespace if self.namespace else self.base_path

        if self.create_dirs:
            self._ensure_directory(self._full_base_path)

        self._logger = logging.getLogger(__name__)

    def _ensure_directory(self, path: Path) -> None:
        """Ensure a directory exists."""
        try:
            path.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise StoragePermissionError(str(path), "create_directory") from e
        except OSError as e:
            raise StorageConnectionError("local", str(e)) from e

    def _get_full_path(self, path: str) -> Path:
        """Get full filesystem path from relative path."""
        # Normalize path to prevent directory traversal
        normalized = os.path.normpath(path)
        if normalized.startswith('..') or os.path.isabs(normalized):
            raise StorageError(f"Invalid path: {path}")

        return self._full_base_path / normalized

    def _get_meta_path(self, path: Path) -> Path:
        """Get metadata file path for a data file."""
        return path.with_suffix(path.suffix + '.meta')

    def save(self, path: str, data: bytes, metadata: Dict[str, str] = None) -> str:
        """
        Save data to local filesystem with atomic write.

        Uses temp file + rename for atomic operation.

        Args:
            path: Relative path within namespace
            data: Data to save as bytes
            metadata: Optional metadata dictionary

        Returns:
            Full path where data was saved

        Raises:
            StorageError: If save fails
            StoragePermissionError: If permission denied
        """
        full_path = self._get_full_path(path)

        try:
            # Ensure parent directory exists
            if self.create_dirs:
                self._ensure_directory(full_path.parent)

            # Write to temp file first (atomic)
            temp_fd = None
            temp_path = None
            try:
                # Create temp file in same directory for atomic rename
                temp_fd, temp_path = tempfile.mkstemp(
                    dir=full_path.parent,
                    prefix='.tmp_',
                    suffix=full_path.suffix
                )

                # Write data
                os.write(temp_fd, data)
                os.close(temp_fd)
                temp_fd = None

                # Atomic rename
                os.replace(temp_path, str(full_path))
                temp_path = None

            finally:
                # Cleanup temp file if still exists
                if temp_fd is not None:
                    try:
                        os.close(temp_fd)
                    except:
                        pass
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except:
                        pass

            # Save metadata
            if metadata:
                self._save_metadata(full_path, metadata)

            self._logger.debug(f"Saved {len(data)} bytes to {full_path}")
            return str(full_path)

        except PermissionError as e:
            raise StoragePermissionError(path, "save") from e
        except OSError as e:
            raise StorageConnectionError("local", str(e)) from e

    def _save_metadata(self, data_path: Path, metadata: Dict[str, str]) -> None:
        """Save metadata to companion .meta file."""
        meta_path = self._get_meta_path(data_path)

        meta_data = {
            'path': str(data_path.relative_to(self._full_base_path)),
            'size': data_path.stat().st_size if data_path.exists() else 0,
            'last_modified': datetime.utcnow().isoformat() + 'Z',
            'etag': self.compute_checksum(data_path.read_bytes()) if data_path.exists() else '',
            'custom': metadata
        }

        # Atomic write for metadata too
        temp_fd, temp_path = tempfile.mkstemp(
            dir=data_path.parent,
            prefix='.tmp_meta_',
            suffix='.meta'
        )
        try:
            os.write(temp_fd, json.dumps(meta_data, indent=2).encode('utf-8'))
            os.close(temp_fd)
            os.replace(temp_path, str(meta_path))
        finally:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass

    def load(self, path: str) -> bytes:
        """
        Load data from local filesystem.

        Args:
            path: Relative path within namespace

        Returns:
            Data as bytes

        Raises:
            FileNotFoundError: If path doesn't exist
            StorageError: If load fails
        """
        full_path = self._get_full_path(path)

        if not full_path.exists():
            raise FileNotFoundError(path)

        try:
            data = full_path.read_bytes()
            self._logger.debug(f"Loaded {len(data)} bytes from {full_path}")
            return data

        except PermissionError as e:
            raise StoragePermissionError(path, "load") from e
        except OSError as e:
            raise StorageConnectionError("local", str(e)) from e

    def exists(self, path: str) -> bool:
        """
        Check if a path exists.

        Args:
            path: Relative path within namespace

        Returns:
            True if exists, False otherwise
        """
        full_path = self._get_full_path(path)
        return full_path.exists()

    def delete(self, path: str) -> bool:
        """
        Delete a file from local filesystem.

        Args:
            path: Relative path within namespace

        Returns:
            True if deleted, False if didn't exist

        Raises:
            StorageError: If delete fails
            StoragePermissionError: If permission denied
        """
        full_path = self._get_full_path(path)
        meta_path = self._get_meta_path(full_path)

        if not full_path.exists():
            return False

        try:
            # Delete main file
            full_path.unlink()

            # Delete metadata file if exists
            if meta_path.exists():
                meta_path.unlink()

            self._logger.debug(f"Deleted {full_path}")
            return True

        except PermissionError as e:
            raise StoragePermissionError(path, "delete") from e
        except OSError as e:
            raise StorageConnectionError("local", str(e)) from e

    def list(self, prefix: str = "") -> List[str]:
        """
        List files with a given prefix.

        Args:
            prefix: Path prefix to filter

        Returns:
            List of relative paths
        """
        base = self._get_full_path(prefix) if prefix else self._full_base_path

        if not base.exists():
            return []

        results = []

        try:
            if base.is_file():
                # Single file
                return [str(base.relative_to(self._full_base_path))]

            # Directory listing
            for item in base.rglob('*'):
                if item.is_file() and not item.name.endswith('.meta'):
                    rel_path = str(item.relative_to(self._full_base_path))
                    results.append(rel_path)

            return sorted(results)

        except PermissionError as e:
            raise StoragePermissionError(prefix, "list") from e
        except OSError as e:
            raise StorageConnectionError("local", str(e)) from e

    def get_metadata(self, path: str) -> StorageMetadata:
        """
        Get metadata for a file.

        Args:
            path: Relative path within namespace

        Returns:
            StorageMetadata for the file

        Raises:
            FileNotFoundError: If path doesn't exist
        """
        full_path = self._get_full_path(path)

        if not full_path.exists():
            raise FileNotFoundError(path)

        # Check for companion metadata file
        meta_path = self._get_meta_path(full_path)

        if meta_path.exists():
            try:
                meta_data = json.loads(meta_path.read_text('utf-8'))
                return StorageMetadata.from_dict(meta_data)
            except (json.JSONDecodeError, KeyError):
                pass  # Fall through to compute from file

        # Compute metadata from file
        stat = full_path.stat()

        return StorageMetadata(
            path=path,
            size=stat.st_size,
            content_type=self._guess_content_type(full_path),
            last_modified=datetime.utcfromtimestamp(stat.st_mtime).isoformat() + 'Z',
            etag=self.compute_checksum(full_path.read_bytes()),
            custom={}
        )

    def copy(self, src_path: str, dst_path: str) -> str:
        """
        Copy a file within local filesystem.

        Args:
            src_path: Source relative path
            dst_path: Destination relative path

        Returns:
            Full destination path

        Raises:
            FileNotFoundError: If source doesn't exist
            StorageError: If copy fails
        """
        src_full = self._get_full_path(src_path)
        dst_full = self._get_full_path(dst_path)

        if not src_full.exists():
            raise FileNotFoundError(src_path)

        try:
            # Ensure destination directory exists
            if self.create_dirs:
                self._ensure_directory(dst_full.parent)

            # Copy file
            shutil.copy2(src_full, dst_full)

            # Copy metadata if exists
            src_meta = self._get_meta_path(src_full)
            dst_meta = self._get_meta_path(dst_full)
            if src_meta.exists():
                shutil.copy2(src_meta, dst_meta)

            self._logger.debug(f"Copied {src_full} to {dst_full}")
            return str(dst_full)

        except PermissionError as e:
            raise StoragePermissionError(dst_path, "copy") from e
        except OSError as e:
            raise StorageConnectionError("local", str(e)) from e

    def _guess_content_type(self, path: Path) -> Optional[str]:
        """Guess content type from file extension."""
        import mimetypes

        mime_type, _ = mimetypes.guess_type(str(path))
        return mime_type

    def get_stats(self) -> Dict[str, Any]:
        """
        Get storage backend statistics.

        Returns:
            Dict with backend stats
        """
        try:
            total_size = 0
            file_count = 0

            for item in self._full_base_path.rglob('*'):
                if item.is_file() and not item.name.endswith('.meta'):
                    total_size += item.stat().st_size
                    file_count += 1

            return {
                'backend_type': 'LocalStorageBackend',
                'namespace': self.namespace,
                'base_path': str(self.base_path),
                'full_path': str(self._full_base_path),
                'file_count': file_count,
                'total_size_bytes': total_size,
                'total_size_human': self._human_readable_size(total_size),
                'stats_available': True
            }
        except Exception as e:
            return {
                'backend_type': 'LocalStorageBackend',
                'namespace': self.namespace,
                'base_path': str(self.base_path),
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

    def cleanup_empty_dirs(self) -> int:
        """
        Remove empty directories from storage.

        Returns:
            Number of directories removed
        """
        count = 0
        try:
            for item in sorted(self._full_base_path.rglob('*'), reverse=True):
                if item.is_dir() and not any(item.iterdir()):
                    item.rmdir()
                    count += 1
                    self._logger.debug(f"Removed empty directory: {item}")
        except Exception as e:
            self._logger.warning(f"Error cleaning up empty dirs: {e}")

        return count

    def __repr__(self) -> str:
        return f"<LocalStorageBackend(base_path='{self.base_path}', namespace='{self.namespace}')>"
