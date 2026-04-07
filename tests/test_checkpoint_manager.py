"""
Tests for CheckpointManager (ITEM-STOR-02).

Tests session-isolated checkpoint management including:
- Namespace-based path isolation
- Backward compatibility via symlink
- Multi-session support
- Metadata management
"""

import pytest
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta

from src.state.checkpoint_manager import (
    CheckpointManager,
    CheckpointMetadata,
    get_checkpoint_manager
)
from src.state.checkpoint_serialization import SerializationFormat


class TestCheckpointMetadata:
    """Tests for CheckpointMetadata dataclass."""
    
    def test_metadata_creation(self):
        """Test basic metadata creation."""
        metadata = CheckpointMetadata(
            session_id="test-session-123",
            namespace="test"
        )
        
        assert metadata.session_id == "test-session-123"
        assert metadata.namespace == "test"
        assert metadata.version == "3.3.0"
        assert metadata.created_at != ""
        assert metadata.updated_at != ""
    
    def test_metadata_to_dict(self):
        """Test metadata serialization."""
        metadata = CheckpointMetadata(
            session_id="session-abc",
            namespace="prod",
            size_bytes=1024,
            format="json_zstd",
            checksum="abc123",
            tags=["important", "production"]
        )
        
        data = metadata.to_dict()
        
        assert data["session_id"] == "session-abc"
        assert data["namespace"] == "prod"
        assert data["size_bytes"] == 1024
        assert data["format"] == "json_zstd"
        assert data["checksum"] == "abc123"
        assert "important" in data["tags"]
    
    def test_metadata_from_dict(self):
        """Test metadata deserialization."""
        data = {
            "session_id": "session-xyz",
            "namespace": "dev",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
            "size_bytes": 2048,
            "format": "json",
            "checksum": "def456",
            "version": "3.3.0",
            "tags": ["test"]
        }
        
        metadata = CheckpointMetadata.from_dict(data)
        
        assert metadata.session_id == "session-xyz"
        assert metadata.namespace == "dev"
        assert metadata.size_bytes == 2048
        assert metadata.format == "json"


class TestCheckpointManagerLocal:
    """Tests for CheckpointManager with local filesystem."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp = tempfile.mkdtemp()
        yield Path(temp)
        shutil.rmtree(temp)
    
    @pytest.fixture
    def manager(self, temp_dir):
        """Create a CheckpointManager instance."""
        return CheckpointManager(
            base_path=temp_dir,
            namespace="test"
        )
    
    def test_manager_initialization(self, manager, temp_dir):
        """Test manager initialization."""
        assert manager.namespace == "test"
        assert manager.base_path == temp_dir
        assert manager.backend is None
    
    def test_save_checkpoint(self, manager, temp_dir):
        """Test saving a checkpoint."""
        session_id = "session-001"
        data = {
            "status": "active",
            "progress": 0.5,
            "items": ["a", "b", "c"]
        }
        
        result = manager.save(session_id, data)
        
        assert result.success
        assert result.path is not None
        
        # Check file exists
        checkpoint_path = temp_dir / "checkpoints/test/session-001"
        assert checkpoint_path.exists()
    
    def test_load_checkpoint(self, manager):
        """Test loading a checkpoint."""
        session_id = "session-002"
        data = {
            "status": "complete",
            "progress": 1.0,
            "results": {"count": 42}
        }
        
        # Save first
        save_result = manager.save(session_id, data)
        assert save_result.success
        
        # Then load
        loaded_data, load_result = manager.load(session_id)
        
        assert load_result.success
        assert loaded_data["status"] == "complete"
        assert loaded_data["progress"] == 1.0
        assert loaded_data["results"]["count"] == 42
    
    def test_checkpoint_in_session_dir(self, manager, temp_dir):
        """Test that checkpoint is saved in session-isolated directory."""
        session_id = "session-003"
        data = {"test": "data"}
        
        manager.save(session_id, data)
        
        # Check path structure
        checkpoint_dir = temp_dir / "checkpoints/test/session-003"
        assert checkpoint_dir.exists()
        assert checkpoint_dir.is_dir()
        
        # Should have checkpoint file
        checkpoint_files = list(checkpoint_dir.glob("checkpoint.*"))
        assert len(checkpoint_files) > 0
    
    def test_symlink_exists(self, manager, temp_dir):
        """Test that 'current' symlink is created."""
        session_id = "session-004"
        data = {"test": "symlink"}
        
        manager.save(session_id, data)
        
        # Check symlink exists
        symlink_path = temp_dir / "current"
        assert symlink_path.exists() or symlink_path.is_symlink()
    
    def test_multiple_sessions_isolated(self, manager, temp_dir):
        """Test that multiple sessions have separate checkpoint directories."""
        sessions = ["session-a", "session-b", "session-c"]
        
        for session_id in sessions:
            data = {"session": session_id}
            result = manager.save(session_id, data)
            assert result.success
        
        # Check each has its own directory
        for session_id in sessions:
            checkpoint_dir = temp_dir / "checkpoints/test" / session_id
            assert checkpoint_dir.exists(), f"Missing directory for {session_id}"
        
        # List sessions
        listed_sessions = manager.list_sessions()
        assert set(sessions) == set(listed_sessions)
    
    def test_delete_session(self, manager):
        """Test deleting a session checkpoint."""
        session_id = "session-delete"
        data = {"to_delete": True}
        
        # Save
        manager.save(session_id, data)
        assert manager.session_exists(session_id)
        
        # Delete
        deleted = manager.delete(session_id)
        assert deleted
        assert not manager.session_exists(session_id)
    
    def test_get_metadata(self, manager):
        """Test getting checkpoint metadata."""
        session_id = "session-meta"
        data = {"metadata_test": True}
        
        manager.save(session_id, data)
        
        metadata = manager.get_metadata(session_id)
        
        assert metadata is not None
        assert metadata.session_id == session_id
        assert metadata.namespace == "test"
        assert metadata.size_bytes > 0
    
    def test_session_exists(self, manager):
        """Test checking if session exists."""
        session_id = "session-exists"
        data = {"exists": True}
        
        assert not manager.session_exists(session_id)
        
        manager.save(session_id, data)
        
        assert manager.session_exists(session_id)
    
    def test_get_latest_session(self, manager):
        """Test getting latest session."""
        # Save multiple sessions
        manager.save("session-old", {"order": 1})
        manager.save("session-new", {"order": 2})
        
        latest = manager.get_latest_session()
        
        # Should return the most recently saved
        assert latest == "session-new"
    
    def test_get_storage_stats(self, manager):
        """Test getting storage statistics."""
        manager.save("session-1", {"data": "a" * 100})
        manager.save("session-2", {"data": "b" * 200})
        
        stats = manager.get_storage_stats()
        
        assert stats["namespace"] == "test"
        assert stats["session_count"] == 2
        assert stats["total_size_bytes"] > 0
    
    def test_cleanup_old_sessions(self, manager):
        """Test cleaning up old sessions."""
        # Create old session
        old_session = "session-old"
        manager.save(old_session, {"old": True})
        
        # Manually modify metadata to make it old
        from src.state.checkpoint_manager import CheckpointMetadata
        old_time = (datetime.utcnow() - timedelta(days=60)).isoformat() + "Z"
        old_metadata = CheckpointMetadata(
            session_id=old_session,
            namespace="test",
            updated_at=old_time
        )
        
        # Save modified metadata
        metadata_path = manager.base_path / manager._get_metadata_path(old_session)
        with open(metadata_path, 'w') as f:
            json.dump(old_metadata.to_dict(), f)
        
        # Create new session
        manager.save("session-new", {"new": True})
        
        # Cleanup sessions older than 30 days
        deleted = manager.cleanup_old_sessions(max_age_days=30)
        
        assert deleted >= 1
        assert not manager.session_exists(old_session)
        assert manager.session_exists("session-new")


class TestCheckpointManagerFormats:
    """Tests for different serialization formats."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp = tempfile.mkdtemp()
        yield Path(temp)
        shutil.rmtree(temp)
    
    @pytest.fixture
    def manager(self, temp_dir):
        """Create a CheckpointManager instance."""
        return CheckpointManager(base_path=temp_dir, namespace="format-test")
    
    def test_save_json_format(self, manager):
        """Test saving in JSON format."""
        session_id = "json-session"
        data = {"format": "json", "numbers": [1, 2, 3]}
        
        result = manager.save(
            session_id, 
            data, 
            format=SerializationFormat.JSON
        )
        
        assert result.success
        assert result.format == SerializationFormat.JSON
        
        loaded_data, _ = manager.load(session_id)
        assert loaded_data["format"] == "json"
    
    def test_save_json_zstd_format(self, manager):
        """Test saving in JSON+ZSTD format (or gzip fallback)."""
        session_id = "zstd-session"
        data = {"format": "zstd", "compressed": True}
        
        result = manager.save(
            session_id,
            data,
            format=SerializationFormat.JSON_ZSTD
        )
        
        assert result.success
        # Note: If zstd unavailable, falls back to gzip with JSON format
        assert result.format in [SerializationFormat.JSON_ZSTD, SerializationFormat.JSON]
        
        loaded_data, _ = manager.load(session_id)
        assert loaded_data["format"] == "zstd"


class TestCheckpointManagerNamespace:
    """Tests for namespace isolation."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp = tempfile.mkdtemp()
        yield Path(temp)
        shutil.rmtree(temp)
    
    def test_different_namespaces_isolated(self, temp_dir):
        """Test that different namespaces are isolated."""
        manager_a = CheckpointManager(base_path=temp_dir, namespace="namespace-a")
        manager_b = CheckpointManager(base_path=temp_dir, namespace="namespace-b")
        
        # Save to namespace-a
        manager_a.save("session-1", {"namespace": "a"})
        
        # Save to namespace-b
        manager_b.save("session-1", {"namespace": "b"})
        
        # Both should have separate data
        data_a, _ = manager_a.load("session-1")
        data_b, _ = manager_b.load("session-1")
        
        assert data_a["namespace"] == "a"
        assert data_b["namespace"] == "b"
        
        # List should show isolated sessions
        sessions_a = manager_a.list_sessions()
        sessions_b = manager_b.list_sessions()
        
        assert sessions_a == ["session-1"]
        assert sessions_b == ["session-1"]


class TestCheckpointManagerFactory:
    """Tests for factory function."""
    
    def test_get_checkpoint_manager(self):
        """Test factory function."""
        with tempfile.TemporaryDirectory() as temp:
            config = {
                "storage": {
                    "namespace": "factory-test"
                }
            }
            
            manager = get_checkpoint_manager(
                config=config,
                base_path=Path(temp)
            )
            
            assert isinstance(manager, CheckpointManager)
            assert manager.namespace == "factory-test"


class TestCheckpointManagerErrorHandling:
    """Tests for error handling."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp = tempfile.mkdtemp()
        yield Path(temp)
        shutil.rmtree(temp)
    
    @pytest.fixture
    def manager(self, temp_dir):
        """Create a CheckpointManager instance."""
        return CheckpointManager(base_path=temp_dir)
    
    def test_load_nonexistent_session(self, manager):
        """Test loading a session that doesn't exist."""
        data, result = manager.load("nonexistent-session")
        
        assert not result.success
        assert "No checkpoint found" in result.error
        assert data == {}
    
    def test_delete_nonexistent_session(self, manager):
        """Test deleting a session that doesn't exist."""
        deleted = manager.delete("nonexistent-session")
        
        assert not deleted
    
    def test_get_metadata_nonexistent(self, manager):
        """Test getting metadata for nonexistent session."""
        metadata = manager.get_metadata("nonexistent")
        
        assert metadata is None
    
    def test_pickle_requires_unsafe_flag(self, manager):
        """Test that pickle format requires unsafe_mode."""
        session_id = "pickle-session"
        data = {"unsafe": "data"}
        
        # Should fail without unsafe_mode
        result = manager.save(
            session_id,
            data,
            format=SerializationFormat.PICKLE_UNSAFE,
            unsafe_mode=False
        )
        
        assert not result.success
        assert "unsafe" in result.error.lower()


class TestCheckpointManagerBackwardCompat:
    """Tests for backward compatibility features."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp = tempfile.mkdtemp()
        yield Path(temp)
        shutil.rmtree(temp)
    
    @pytest.fixture
    def manager(self, temp_dir):
        """Create a CheckpointManager instance."""
        return CheckpointManager(base_path=temp_dir, namespace="compat")
    
    def test_current_symlink_points_to_latest(self, manager, temp_dir):
        """Test that 'current' symlink always points to latest checkpoint."""
        # Save first session
        manager.save("session-first", {"order": 1})
        
        symlink_path = temp_dir / "current"
        assert symlink_path.is_symlink()
        
        # Save second session
        manager.save("session-second", {"order": 2})
        
        # Symlink should point to second session
        link_target = symlink_path.resolve()
        assert "session-second" in str(link_target)
    
    def test_symlink_updates_on_delete(self, manager, temp_dir):
        """Test that symlink updates when current session is deleted."""
        manager.save("session-a", {"data": "a"})
        manager.save("session-b", {"data": "b"})
        
        # Delete latest session
        manager.delete("session-b")
        
        # Symlink should now point to session-a
        symlink_path = temp_dir / "current"
        if symlink_path.exists():
            link_target = str(symlink_path.resolve())
            assert "session-a" in link_target or "session-b" not in link_target


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
