"""
Tests for Storage Backend - ITEM-STOR-01

Tests for the storage backend abstraction and implementations:
- LocalStorageBackend
- S3StorageBackend (mock)
- GCSStorageBackend (mock)
- Factory functions

Author: TITAN FUSE Team
Version: 3.3.0
"""

import pytest
import tempfile
import shutil
import os
import json
from pathlib import Path

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
    validate_storage_config
)


class TestStorageMetadata:
    """Tests for StorageMetadata dataclass."""

    def test_metadata_creation(self):
        """Test creating storage metadata."""
        meta = StorageMetadata(
            path="test/file.json",
            size=1024,
            content_type="application/json",
            last_modified="2026-01-01T00:00:00Z",
            etag="abc123",
            custom={"key": "value"}
        )

        assert meta.path == "test/file.json"
        assert meta.size == 1024
        assert meta.content_type == "application/json"
        assert meta.etag == "abc123"
        assert meta.custom["key"] == "value"

    def test_metadata_to_dict(self):
        """Test converting metadata to dictionary."""
        meta = StorageMetadata(
            path="test/file.json",
            size=1024,
            custom={"key": "value"}
        )

        result = meta.to_dict()

        assert result["path"] == "test/file.json"
        assert result["size"] == 1024
        assert result["custom"]["key"] == "value"

    def test_metadata_from_dict(self):
        """Test creating metadata from dictionary."""
        data = {
            "path": "test/file.json",
            "size": 2048,
            "content_type": "text/plain",
            "custom": {"foo": "bar"}
        }

        meta = StorageMetadata.from_dict(data)

        assert meta.path == "test/file.json"
        assert meta.size == 2048
        assert meta.content_type == "text/plain"
        assert meta.custom["foo"] == "bar"


class TestLocalStorageBackend:
    """Tests for LocalStorageBackend."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp = tempfile.mkdtemp()
        yield temp
        shutil.rmtree(temp, ignore_errors=True)

    @pytest.fixture
    def backend(self, temp_dir):
        """Create a LocalStorageBackend instance."""
        return LocalStorageBackend(
            base_path=temp_dir,
            namespace="test",
            create_dirs=True
        )

    def test_backend_creation(self, backend, temp_dir):
        """Test backend is created correctly."""
        assert backend.namespace == "test"
        assert str(backend.base_path) == temp_dir

    def test_save_and_load(self, backend):
        """Test saving and loading data."""
        data = b'{"key": "value"}'
        path = "checkpoints/session-123/checkpoint.json"

        # Save
        saved_path = backend.save(path, data)
        assert saved_path.endswith(path)

        # Load
        loaded_data = backend.load(path)
        assert loaded_data == data

    def test_exists(self, backend):
        """Test exists check."""
        path = "test/file.txt"

        assert not backend.exists(path)

        backend.save(path, b"test data")

        assert backend.exists(path)

    def test_delete(self, backend):
        """Test delete operation."""
        path = "test/delete_me.txt"

        backend.save(path, b"delete me")

        assert backend.exists(path)

        result = backend.delete(path)

        assert result is True
        assert not backend.exists(path)

    def test_delete_nonexistent(self, backend):
        """Test deleting non-existent file."""
        result = backend.delete("nonexistent.txt")
        assert result is False

    def test_list(self, backend):
        """Test listing files."""
        # Create some files
        backend.save("dir1/file1.txt", b"data1")
        backend.save("dir1/file2.txt", b"data2")
        backend.save("dir2/file3.txt", b"data3")

        # List all
        all_files = backend.list()
        assert len(all_files) == 3

        # List with prefix
        dir1_files = backend.list("dir1/")
        assert len(dir1_files) == 2

    def test_get_metadata(self, backend):
        """Test getting metadata."""
        data = b'{"test": "data"}'
        path = "test/metadata.json"

        backend.save(path, data, {"custom_key": "custom_value"})

        meta = backend.get_metadata(path)

        assert meta.path == path
        assert meta.size == len(data)
        assert meta.custom.get("custom_key") == "custom_value"

    def test_copy(self, backend):
        """Test copy operation."""
        src = "source/file.txt"
        dst = "destination/file.txt"

        backend.save(src, b"source data")

        result = backend.copy(src, dst)

        assert backend.exists(dst)
        assert backend.load(dst) == b"source data"

    def test_save_json(self, backend):
        """Test saving JSON data."""
        data = {"key": "value", "number": 42}
        path = "test/data.json"

        backend.save_json(path, data)

        loaded = backend.load_json(path)
        assert loaded["key"] == "value"
        assert loaded["number"] == 42

    def test_save_text(self, backend):
        """Test saving text data."""
        text = "Hello, World!"
        path = "test/hello.txt"

        backend.save_text(path, text)

        loaded = backend.load_text(path)
        assert loaded == text

    def test_file_not_found(self, backend):
        """Test FileNotFoundError on missing file."""
        with pytest.raises(FileNotFoundError):
            backend.load("nonexistent/file.txt")

    def test_namespace_isolation(self, temp_dir):
        """Test namespace isolation."""
        backend1 = LocalStorageBackend(base_path=temp_dir, namespace="ns1")
        backend2 = LocalStorageBackend(base_path=temp_dir, namespace="ns2")

        backend1.save("file.txt", b"namespace 1")
        backend2.save("file.txt", b"namespace 2")

        assert backend1.load("file.txt") == b"namespace 1"
        assert backend2.load("file.txt") == b"namespace 2"

    def test_session_paths(self, backend):
        """Test session path helpers."""
        session_path = backend.get_session_path("session-123")
        assert session_path == "sessions/session-123"

        checkpoint_path = backend.get_checkpoint_path("session-123")
        assert checkpoint_path == "checkpoints/session-123/checkpoint.json"

    def test_health_check(self, backend):
        """Test health check."""
        result = backend.health_check()

        assert result["healthy"] is True
        assert result["backend"] == "LocalStorageBackend"

    def test_get_stats(self, backend):
        """Test getting storage statistics."""
        backend.save("file1.txt", b"data1")
        backend.save("file2.txt", b"data2")

        stats = backend.get_stats()

        assert stats["backend_type"] == "LocalStorageBackend"
        assert stats["file_count"] == 2
        assert stats["total_size_bytes"] == 10  # "data1" + "data2"

    def test_delete_session(self, backend):
        """Test deleting all session data."""
        session_id = "session-delete-test"

        backend.save(f"sessions/{session_id}/data.txt", b"session data")
        backend.save(f"checkpoints/{session_id}/checkpoint.json", b"{}")

        count = backend.delete_session(session_id)

        assert count == 2
        assert not backend.exists(f"sessions/{session_id}/data.txt")

    def test_checksum_computation(self, backend):
        """Test checksum computation."""
        data = b"test data"
        checksum = backend.compute_checksum(data)

        # Should be SHA-256 hex string
        assert len(checksum) == 64
        assert all(c in '0123456789abcdef' for c in checksum)

    def test_atomic_write(self, backend):
        """Test that writes are atomic (temp file + rename)."""
        path = "test/atomic.txt"
        data = b"atomic data"

        # Save should complete without leaving temp files
        backend.save(path, data)

        # Verify no temp files exist
        dir_path = Path(backend._get_full_path(path)).parent
        temp_files = list(dir_path.glob(".tmp_*"))
        assert len(temp_files) == 0


class TestFactory:
    """Tests for storage backend factory."""

    def test_create_local_backend(self):
        """Test creating local backend via factory."""
        config = {
            "storage": {
                "backend": "local",
                "namespace": "factory-test",
                "local": {
                    "base_path": tempfile.mkdtemp()
                }
            }
        }

        backend = get_storage_backend(config)

        assert isinstance(backend, LocalStorageBackend)
        assert backend.namespace == "factory-test"

    def test_create_default_backend(self):
        """Test creating default backend."""
        backend = get_default_storage_backend()

        assert isinstance(backend, LocalStorageBackend)
        assert backend.namespace == "default"

    def test_invalid_backend_type(self):
        """Test error on invalid backend type."""
        config = {
            "storage": {
                "backend": "invalid"
            }
        }

        with pytest.raises(StorageError):
            get_storage_backend(config)

    def test_validate_config_valid(self):
        """Test config validation with valid config."""
        config = {
            "storage": {
                "backend": "local"
            }
        }

        errors = validate_storage_config(config)
        assert len(errors) == 0

    def test_validate_config_invalid_backend(self):
        """Test config validation with invalid backend."""
        config = {
            "storage": {
                "backend": "unknown"
            }
        }

        errors = validate_storage_config(config)
        assert len(errors) > 0

    def test_validate_config_s3_missing_bucket(self):
        """Test config validation for S3 without bucket."""
        config = {
            "storage": {
                "backend": "s3",
                "s3": {}
            }
        }

        errors = validate_storage_config(config)
        assert any("bucket" in e.lower() for e in errors)

    def test_validate_config_gcs_missing_bucket(self):
        """Test config validation for GCS without bucket."""
        config = {
            "storage": {
                "backend": "gcs",
                "gcs": {}
            }
        }

        errors = validate_storage_config(config)
        assert any("bucket" in e.lower() for e in errors)


class TestStorageErrors:
    """Tests for storage error classes."""

    def test_file_not_found_error(self):
        """Test FileNotFoundError."""
        error = FileNotFoundError("path/to/file.txt")

        assert error.path == "path/to/file.txt"
        assert "not found" in str(error).lower()

    def test_storage_connection_error(self):
        """Test StorageConnectionError."""
        error = StorageConnectionError("s3", "Connection timeout")

        assert error.backend == "s3"
        assert "timeout" in str(error).lower()

    def test_storage_permission_error(self):
        """Test StoragePermissionError."""
        error = StoragePermissionError("/path/to/file", "save")

        assert error.path == "/path/to/file"
        assert error.operation == "save"


class TestS3BackendMock:
    """
    Mock tests for S3 backend.

    These tests verify S3 backend logic without actual AWS connection.
    """

    def test_s3_key_construction(self):
        """Test S3 key construction."""
        from src.storage.s3_backend import S3StorageBackend

        # Mock client to avoid AWS connection
        backend = S3StorageBackend.__new__(S3StorageBackend)
        backend.bucket = "test-bucket"
        backend.prefix = "titan"
        backend.namespace = "production"
        backend._client = None

        key = backend._get_s3_key("checkpoints/session-123/checkpoint.json")

        assert key == "titan/production/checkpoints/session-123/checkpoint.json"

    def test_s3_key_without_prefix(self):
        """Test S3 key construction without prefix."""
        from src.storage.s3_backend import S3StorageBackend

        backend = S3StorageBackend.__new__(S3StorageBackend)
        backend.bucket = "test-bucket"
        backend.prefix = ""
        backend.namespace = "default"
        backend._client = None

        key = backend._get_s3_key("file.txt")

        assert key == "default/file.txt"


class TestGCSBackendMock:
    """
    Mock tests for GCS backend.

    These tests verify GCS backend logic without actual GCP connection.
    """

    def test_gcs_blob_name_construction(self):
        """Test GCS blob name construction."""
        from src.storage.gcs_backend import GCSStorageBackend

        backend = GCSStorageBackend.__new__(GCSStorageBackend)
        backend.bucket_name = "test-bucket"
        backend.prefix = "titan"
        backend.namespace = "production"
        backend._client = None

        blob_name = backend._get_gcs_blob_name("checkpoints/session.json")

        assert blob_name == "titan/production/checkpoints/session.json"


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
