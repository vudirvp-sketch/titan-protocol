"""
Tests for Workspace Isolation Manager (ITEM-SEC-122).
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch

from src.security.workspace_isolation import (
    WorkspaceIsolationManager,
    WorkspaceViolationError,
    EnforcementMode,
    ViolationType,
    Violation,
    create_workspace_manager
)


class TestEnforcementMode:
    """Tests for EnforcementMode enum."""
    
    def test_mode_values(self):
        """Test that all mode values exist."""
        assert EnforcementMode.STRICT.value == "strict"
        assert EnforcementMode.PERMISSIVE.value == "permissive"
        assert EnforcementMode.DISABLED.value == "disabled"


class TestViolationType:
    """Tests for ViolationType enum."""
    
    def test_violation_types(self):
        """Test that all violation types exist."""
        assert ViolationType.PATH_OUTSIDE_WORKSPACE.value == "path_outside_workspace"
        assert ViolationType.SYMLINK_ESCAPE.value == "symlink_escape"
        assert ViolationType.PATH_TRAVERSAL.value == "path_traversal"
        assert ViolationType.ABSOLUTE_PATH_REQUIRED.value == "absolute_path_required"
        assert ViolationType.WORKSPACE_NOT_SET.value == "workspace_not_set"


class TestViolation:
    """Tests for Violation dataclass."""
    
    def test_violation_creation(self):
        """Test creating a violation."""
        violation = Violation(
            violation_type=ViolationType.PATH_TRAVERSAL,
            requested_path="../../../etc/passwd",
            resolved_path="/etc/passwd",
            message="Path traversal detected"
        )
        
        assert violation.violation_type == ViolationType.PATH_TRAVERSAL
        assert violation.requested_path == "../../../etc/passwd"
        assert violation.message == "Path traversal detected"
    
    def test_violation_to_dict(self):
        """Test converting violation to dictionary."""
        violation = Violation(
            violation_type=ViolationType.PATH_OUTSIDE_WORKSPACE,
            requested_path="/outside/file.txt",
            resolved_path="/outside/file.txt",
            message="Path outside workspace"
        )
        
        data = violation.to_dict()
        
        assert data["violation_type"] == "path_outside_workspace"
        assert data["requested_path"] == "/outside/file.txt"
        assert "timestamp" in data


class TestWorkspaceViolationError:
    """Tests for WorkspaceViolationError exception."""
    
    def test_exception_creation(self):
        """Test creating the exception."""
        violation = Violation(
            violation_type=ViolationType.PATH_OUTSIDE_WORKSPACE,
            requested_path="/outside",
            resolved_path="/outside",
            message="Outside workspace"
        )
        
        error = WorkspaceViolationError(violation)
        
        assert error.violation == violation
        assert str(error) == "Outside workspace"


class TestWorkspaceIsolationManager:
    """Tests for WorkspaceIsolationManager class."""
    
    def test_initialization(self):
        """Test manager initialization."""
        manager = WorkspaceIsolationManager()
        
        assert manager._workspace_path is None
        assert manager._enforcement_mode == EnforcementMode.STRICT
    
    def test_initialization_with_config(self):
        """Test manager initialization with config."""
        config = {
            "security": {
                "workspace_enforcement": "permissive"
            }
        }
        
        manager = WorkspaceIsolationManager(config)
        
        assert manager._enforcement_mode == EnforcementMode.PERMISSIVE
    
    def test_set_workspace(self):
        """Test setting the workspace path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = WorkspaceIsolationManager()
            manager.set_workspace(tmpdir)
            
            assert manager._workspace_path is not None
            assert str(manager._workspace_path) == str(Path(tmpdir).resolve())
    
    def test_set_workspace_relative_path_raises(self):
        """Test that relative path raises error."""
        manager = WorkspaceIsolationManager()
        
        with pytest.raises(ValueError) as exc_info:
            manager.set_workspace("relative/path")
        
        assert "absolute" in str(exc_info.value).lower()
    
    def test_check_access_within_workspace(self):
        """Test access check within workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = WorkspaceIsolationManager()
            manager.set_workspace(tmpdir)
            
            # Create a file in workspace
            test_file = Path(tmpdir) / "test.txt"
            test_file.touch()
            
            assert manager.check_access(str(test_file)) is True
    
    def test_check_access_outside_workspace_strict(self):
        """Test access check outside workspace in strict mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = WorkspaceIsolationManager()  # strict by default
            manager.set_workspace(tmpdir)
            
            with pytest.raises(WorkspaceViolationError):
                manager.check_access("/etc/passwd")
    
    def test_check_access_outside_workspace_permissive(self):
        """Test access check outside workspace in permissive mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"security": {"workspace_enforcement": "permissive"}}
            manager = WorkspaceIsolationManager(config)
            manager.set_workspace(tmpdir)
            
            # Should not raise, just return True with warning
            result = manager.check_access("/etc/passwd")
            assert result is True
    
    def test_check_access_path_traversal(self):
        """Test that path traversal is detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = WorkspaceIsolationManager()
            manager.set_workspace(tmpdir)
            
            with pytest.raises(WorkspaceViolationError) as exc_info:
                manager.check_access(f"{tmpdir}/../../../etc/passwd")
            
            assert exc_info.value.violation.violation_type == ViolationType.PATH_TRAVERSAL
    
    def test_check_access_no_workspace(self):
        """Test access check without workspace set."""
        manager = WorkspaceIsolationManager()
        
        with pytest.raises(WorkspaceViolationError) as exc_info:
            manager.check_access("/some/path")
        
        assert exc_info.value.violation.violation_type == ViolationType.WORKSPACE_NOT_SET
    
    def test_verify_path(self):
        """Test verify_path method."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = WorkspaceIsolationManager()
            manager.set_workspace(tmpdir)
            
            # Path within workspace
            assert manager.verify_path(f"{tmpdir}/file.txt") is True
            
            # Path outside workspace
            assert manager.verify_path("/etc/passwd") is False
    
    def test_add_allowed_path(self):
        """Test adding an allowed path."""
        with tempfile.TemporaryDirectory() as tmpdir1:
            with tempfile.TemporaryDirectory() as tmpdir2:
                manager = WorkspaceIsolationManager()
                manager.set_workspace(tmpdir1)
                
                # Access to tmpdir2 should be blocked
                with pytest.raises(WorkspaceViolationError):
                    manager.check_access(f"{tmpdir2}/file.txt")
                
                # Add tmpdir2 as allowed
                manager.add_allowed_path(tmpdir2)
                
                # Now access should be allowed
                assert manager.check_access(f"{tmpdir2}/file.txt") is True
    
    def test_get_allowed_paths(self):
        """Test getting allowed paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = WorkspaceIsolationManager()
            manager.set_workspace(tmpdir)
            manager.add_allowed_path("/allowed1")
            manager.add_allowed_path("/allowed2")
            
            paths = manager.get_allowed_paths()
            
            assert str(manager._workspace_path) in paths
            assert "/allowed1" in paths
            assert "/allowed2" in paths
    
    def test_get_violations(self):
        """Test getting violation log."""
        config = {"security": {"workspace_enforcement": "permissive"}}
        manager = WorkspaceIsolationManager(config)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            manager.set_workspace(tmpdir)
            
            # Trigger some violations
            manager.check_access("/outside1")
            manager.check_access("/outside2")
            
            violations = manager.get_violations()
            
            assert len(violations) == 2
    
    def test_get_stats(self):
        """Test getting statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = WorkspaceIsolationManager()
            manager.set_workspace(tmpdir)
            
            stats = manager.get_stats()
            
            assert stats.workspace_path == str(manager._workspace_path)
            assert stats.enforcement_mode == "strict"
    
    def test_clear_violations(self):
        """Test clearing violation log."""
        config = {"security": {"workspace_enforcement": "permissive"}}
        manager = WorkspaceIsolationManager(config)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            manager.set_workspace(tmpdir)
            manager.check_access("/outside")
            
            assert len(manager._violations) == 1
            
            manager.clear_violations()
            
            assert len(manager._violations) == 0
    
    def test_reset(self):
        """Test resetting manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = WorkspaceIsolationManager()
            manager.set_workspace(tmpdir)
            manager.add_allowed_path("/allowed")
            
            manager.reset()
            
            assert manager._workspace_path is None
            assert len(manager._allowed_paths) == 0
    
    def test_set_event_bus(self):
        """Test setting event bus."""
        manager = WorkspaceIsolationManager()
        mock_bus = Mock()
        
        manager.set_event_bus(mock_bus)
        
        assert manager._event_bus == mock_bus


class TestFactoryFunction:
    """Tests for factory function."""
    
    def test_create_workspace_manager_default(self):
        """Test creating manager with defaults."""
        manager = create_workspace_manager()
        
        assert isinstance(manager, WorkspaceIsolationManager)
    
    def test_create_workspace_manager_with_config(self):
        """Test creating manager with config."""
        config = {"security": {"workspace_enforcement": "disabled"}}
        manager = create_workspace_manager(config)
        
        assert manager._enforcement_mode == EnforcementMode.DISABLED
    
    def test_create_workspace_manager_with_event_bus(self):
        """Test creating manager with event bus."""
        mock_bus = Mock()
        manager = create_workspace_manager(event_bus=mock_bus)
        
        assert manager._event_bus == mock_bus
