"""
Workspace Isolation Manager for TITAN FUSE Protocol.

ITEM-SEC-122: Mandatory workspace path with runtime verification.

Implements chroot-style verification ensuring all file operations
are confined to the designated workspace directory. This prevents
unauthorized access to files outside the workspace.

Security Model:
- Workspace path is REQUIRED (not optional)
- All file access must go through check_access()
- Symlink escaping is prevented
- Path traversal attacks are blocked

Author: TITAN FUSE Team
Version: 4.1.0
"""

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, TYPE_CHECKING
from enum import Enum
import logging

if TYPE_CHECKING:
    from ..events.event_bus import EventBus


class EnforcementMode(Enum):
    """Workspace enforcement modes."""
    STRICT = "strict"           # Block all violations
    PERMISSIVE = "permissive"   # Log but allow
    DISABLED = "disabled"       # No enforcement (not recommended)


class ViolationType(Enum):
    """Types of workspace violations."""
    PATH_OUTSIDE_WORKSPACE = "path_outside_workspace"
    SYMLINK_ESCAPE = "symlink_escape"
    PATH_TRAVERSAL = "path_traversal"
    ABSOLUTE_PATH_REQUIRED = "absolute_path_required"
    WORKSPACE_NOT_SET = "workspace_not_set"


@dataclass
class Violation:
    """
    Record of a workspace violation.
    
    Attributes:
        violation_type: Type of violation
        requested_path: Path that was requested
        resolved_path: Actual resolved path
        message: Human-readable message
        timestamp: When violation occurred
    """
    violation_type: ViolationType
    requested_path: str
    resolved_path: Optional[str]
    message: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "violation_type": self.violation_type.value,
            "requested_path": self.requested_path,
            "resolved_path": self.resolved_path,
            "message": self.message,
            "timestamp": self.timestamp
        }


class WorkspaceViolationError(Exception):
    """Exception raised when workspace isolation is violated."""
    
    def __init__(self, violation: Violation):
        self.violation = violation
        super().__init__(violation.message)


@dataclass
class WorkspaceStats:
    """Statistics for workspace isolation."""
    workspace_path: Optional[str]
    enforcement_mode: str
    total_checks: int = 0
    violations: int = 0
    blocked: int = 0
    allowed: int = 0
    allowed_paths: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspace_path": self.workspace_path,
            "enforcement_mode": self.enforcement_mode,
            "total_checks": self.total_checks,
            "violations": self.violations,
            "blocked": self.blocked,
            "allowed": self.allowed,
            "allowed_paths": self.allowed_paths
        }


class WorkspaceIsolationManager:
    """
    ITEM-SEC-122: Enforce workspace isolation for file operations.
    
    This manager ensures that all file operations are confined to
    a designated workspace directory, preventing unauthorized access
    to files outside the workspace.
    
    Security Features:
    - Mandatory workspace path configuration
    - Path traversal attack prevention
    - Symlink escape detection
    - Audit logging of all violations
    
    Usage:
        manager = WorkspaceIsolationManager(config)
        manager.set_workspace("/workspace/session-123")
        
        # Before any file operation
        if manager.check_access("/workspace/session-123/file.txt"):
            # Safe to proceed
            with open(path, 'r') as f:
                content = f.read()
        else:
            # Access denied
            raise WorkspaceViolationError(...)
    """
    
    # Dangerous path patterns
    PATH_TRAVERSAL_PATTERNS = [
        r'\.\.',           # Parent directory
        r'\.\./',          # Parent directory with slash
        r'/\.\.',          # Root relative parent
        r'\\\.\.',         # Windows parent
    ]
    
    def __init__(self, config: Dict = None, event_bus: 'EventBus' = None):
        """
        Initialize the workspace isolation manager.
        
        Args:
            config: Configuration dictionary from config.yaml
            event_bus: Optional EventBus for emitting events
        """
        self._config = config or {}
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)
        
        # Workspace configuration
        security_config = self._config.get("security", {})
        self._workspace_path: Optional[Path] = None
        self._enforcement_mode = EnforcementMode(
            security_config.get("workspace_enforcement", "strict")
        )
        self._allow_symlinks = security_config.get("allowed_symlinks", False)
        self._sandbox_to_workspace = security_config.get("sandbox_to_workspace", True)
        
        # Additional allowed paths (read-only)
        self._allowed_paths: Set[Path] = set()
        
        # Statistics
        self._stats = WorkspaceStats(
            workspace_path=None,
            enforcement_mode=self._enforcement_mode.value
        )
        
        # Violation log
        self._violations: List[Violation] = []
        self._max_violations = 1000
    
    def set_event_bus(self, event_bus: 'EventBus') -> None:
        """Set the EventBus for emitting events."""
        self._event_bus = event_bus
        self._logger.info("EventBus attached to WorkspaceIsolationManager")
    
    def set_workspace(self, path: str) -> None:
        """
        Set the workspace path.
        
        ITEM-SEC-122: This is REQUIRED before any file operations.
        
        Args:
            path: Absolute path to workspace directory
            
        Raises:
            ValueError: If path is not absolute
        """
        workspace = Path(path)
        
        if not workspace.is_absolute():
            raise ValueError(
                f"Workspace path must be absolute: {path}"
            )
        
        # Create workspace if it doesn't exist
        workspace.mkdir(parents=True, exist_ok=True)
        
        # Resolve to canonical path
        self._workspace_path = workspace.resolve()
        self._stats.workspace_path = str(self._workspace_path)
        
        self._logger.info(f"Workspace set to: {self._workspace_path}")
    
    def add_allowed_path(self, path: str, read_only: bool = True) -> None:
        """
        Add an additional allowed path (outside workspace).
        
        Use sparingly - this creates an exception to workspace isolation.
        
        Args:
            path: Absolute path to allow
            read_only: Whether this path is read-only (always True for now)
        """
        allowed = Path(path).resolve()
        self._allowed_paths.add(allowed)
        self._stats.allowed_paths.append(str(allowed))
        self._logger.warning(
            f"Added allowed path outside workspace: {allowed} (read_only={read_only})"
        )
    
    def get_allowed_paths(self) -> List[str]:
        """Get list of allowed paths including workspace."""
        paths = [str(self._workspace_path)] if self._workspace_path else []
        paths.extend(str(p) for p in self._allowed_paths)
        return paths
    
    def verify_path(self, path: str) -> bool:
        """
        Verify that a path is within allowed boundaries.
        
        This is a quick check without resolving symlinks.
        
        Args:
            path: Path to verify
            
        Returns:
            True if path is within workspace or allowed paths
        """
        if self._workspace_path is None:
            return False
        
        try:
            target = Path(path)
            
            # Check for path traversal patterns
            if self._has_path_traversal(str(path)):
                return False
            
            # Resolve the path (handles .., ., symlinks)
            if target.exists():
                resolved = target.resolve()
            else:
                # For non-existent paths, resolve parent and append
                resolved = target.parent.resolve() / target.name
            
            # Check if within workspace
            try:
                resolved.relative_to(self._workspace_path)
                return True
            except ValueError:
                pass
            
            # Check if in allowed paths
            for allowed in self._allowed_paths:
                try:
                    resolved.relative_to(allowed)
                    return True
                except ValueError:
                    continue
            
            return False
            
        except Exception as e:
            self._logger.error(f"Path verification error: {e}")
            return False
    
    def check_access(self, requested_path: str) -> bool:
        """
        Check if access to a path is allowed.
        
        This is the main entry point for access control. All file
        operations should call this before proceeding.
        
        Args:
            requested_path: Path being accessed
            
        Returns:
            True if access is allowed, False otherwise
            
        Raises:
            WorkspaceViolationError: If enforcement is STRICT and access is denied
        """
        self._stats.total_checks += 1
        
        # Check if workspace is set
        if self._workspace_path is None:
            violation = Violation(
                violation_type=ViolationType.WORKSPACE_NOT_SET,
                requested_path=requested_path,
                resolved_path=None,
                message="Workspace path not configured. Call set_workspace() first."
            )
            return self._handle_violation(violation)
        
        try:
            target = Path(requested_path)
            
            # Must be absolute path
            if not target.is_absolute():
                violation = Violation(
                    violation_type=ViolationType.ABSOLUTE_PATH_REQUIRED,
                    requested_path=requested_path,
                    resolved_path=None,
                    message=f"Absolute path required: {requested_path}"
                )
                return self._handle_violation(violation)
            
            # Check for path traversal
            if self._has_path_traversal(requested_path):
                violation = Violation(
                    violation_type=ViolationType.PATH_TRAVERSAL,
                    requested_path=requested_path,
                    resolved_path=None,
                    message=f"Path traversal detected: {requested_path}"
                )
                return self._handle_violation(violation)
            
            # Resolve the path
            if target.exists():
                resolved = target.resolve()
                
                # Check for symlink escape
                if not self._allow_symlinks and self._is_symlink_escape(target):
                    violation = Violation(
                        violation_type=ViolationType.SYMLINK_ESCAPE,
                        requested_path=requested_path,
                        resolved_path=str(resolved),
                        message=f"Symlink escape detected: {requested_path} -> {resolved}"
                    )
                    return self._handle_violation(violation)
            else:
                # For non-existent paths, resolve parent
                parent = target.parent
                if parent.exists():
                    resolved_parent = parent.resolve()
                    resolved = resolved_parent / target.name
                else:
                    resolved = target
            
            # Check if within workspace
            try:
                resolved.relative_to(self._workspace_path)
                self._stats.allowed += 1
                return True
            except ValueError:
                pass
            
            # Check allowed paths
            for allowed in self._allowed_paths:
                try:
                    resolved.relative_to(allowed)
                    self._stats.allowed += 1
                    return True
                except ValueError:
                    continue
            
            # Path is outside workspace
            violation = Violation(
                violation_type=ViolationType.PATH_OUTSIDE_WORKSPACE,
                requested_path=requested_path,
                resolved_path=str(resolved),
                message=f"Path outside workspace: {requested_path}"
            )
            return self._handle_violation(violation)
            
        except WorkspaceViolationError:
            # Re-raise violation errors in strict mode
            raise
        except Exception as e:
            self._logger.error(f"Access check error: {e}")
            return False
    
    def _has_path_traversal(self, path: str) -> bool:
        """Check for path traversal patterns."""
        for pattern in self.PATH_TRAVERSAL_PATTERNS:
            if re.search(pattern, path):
                return True
        return False
    
    def _is_symlink_escape(self, path: Path) -> bool:
        """Check if path contains symlinks that escape workspace."""
        if self._workspace_path is None:
            return False
        
        try:
            # Check each component of the path
            parts = []
            current = path
            
            while current != current.parent:
                if current.is_symlink():
                    # Resolve the symlink
                    link_target = current.resolve()
                    
                    # Check if target is within workspace
                    try:
                        link_target.relative_to(self._workspace_path)
                    except ValueError:
                        # Symlink points outside workspace
                        return True
                
                parts.append(current.name)
                current = current.parent
            
            return False
            
        except Exception:
            return True  # Safer to assume escape on error
    
    def _handle_violation(self, violation: Violation) -> bool:
        """Handle a workspace violation based on enforcement mode."""
        self._stats.violations += 1
        self._record_violation(violation)
        
        # Emit event
        if self._event_bus:
            try:
                from ..events.event_bus import Event, EventSeverity
                event = Event(
                    event_type="WORKSPACE_VIOLATION",
                    data=violation.to_dict(),
                    severity=EventSeverity.WARN if self._enforcement_mode != EnforcementMode.STRICT else EventSeverity.CRITICAL,
                    source="WorkspaceIsolationManager"
                )
                self._event_bus.emit(event)
            except Exception as e:
                self._logger.error(f"Failed to emit violation event: {e}")
        
        # Handle based on enforcement mode
        if self._enforcement_mode == EnforcementMode.STRICT:
            self._stats.blocked += 1
            self._logger.error(f"Workspace violation (BLOCKED): {violation.message}")
            # Raise exception in strict mode
            raise WorkspaceViolationError(violation)
        
        elif self._enforcement_mode == EnforcementMode.PERMISSIVE:
            self._logger.warning(f"Workspace violation (ALLOWED): {violation.message}")
            self._stats.allowed += 1
            return True
        
        else:  # DISABLED
            self._logger.debug(f"Workspace violation (IGNORED): {violation.message}")
            self._stats.allowed += 1
            return True
    
    def _record_violation(self, violation: Violation) -> None:
        """Record a violation in the log."""
        self._violations.append(violation)
        
        # Trim log if too large
        if len(self._violations) > self._max_violations:
            self._violations = self._violations[-self._max_violations:]
    
    def get_violations(self, limit: int = 100) -> List[Violation]:
        """Get recent violations."""
        return self._violations[-limit:]
    
    def get_stats(self) -> WorkspaceStats:
        """Get workspace isolation statistics."""
        return self._stats
    
    def clear_violations(self) -> None:
        """Clear violation log."""
        self._violations.clear()
    
    def reset(self) -> None:
        """Reset the manager to initial state."""
        self._workspace_path = None
        self._allowed_paths.clear()
        self._violations.clear()
        self._stats = WorkspaceStats(
            workspace_path=None,
            enforcement_mode=self._enforcement_mode.value
        )


# =============================================================================
# PAT-38: Workspace Checkpoint with Diff Tracking (ITEM-B007)
# =============================================================================

import difflib


@dataclass
class WorkspaceCheckpoint:
    """Checkpoint with source_diff tracking for PAT-38 pattern.
    
    Captures a snapshot of the workspace state and provides diff
    computation between snapshots to track changes within isolated
    workspaces. Addresses ISSUE-018 diff tracking requirement.
    """
    workspace_root: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    snapshot: Dict[str, str] = field(default_factory=dict)
    source_diff: Optional[Dict[str, str]] = None

    def capture_snapshot(self) -> Dict[str, str]:
        """Capture current workspace file contents as a snapshot.
        
        Returns:
            Dictionary mapping relative file paths to their contents.
        """
        root = Path(self.workspace_root)
        snapshot = {}
        if root.exists() and root.is_dir():
            for file_path in root.rglob("*"):
                if file_path.is_file():
                    try:
                        rel = str(file_path.relative_to(root))
                        snapshot[rel] = file_path.read_text(errors="replace")
                    except (OSError, PermissionError):
                        continue
        self.snapshot = snapshot
        return snapshot

    def compute_diff(self, before: str, after: str, file_path: str = "") -> str:
        """Compute unified diff between before and after states.
        
        Args:
            before: Content before change.
            after: Content after change.
            file_path: File path label for diff header.
            
        Returns:
            Unified diff string.
        """
        before_lines = before.splitlines(keepends=True)
        after_lines = after.splitlines(keepends=True)
        diff = difflib.unified_diff(
            before_lines, after_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        )
        return "".join(diff)

    def capture_diff(self, before_snapshot: Dict[str, str]) -> Dict[str, str]:
        """Capture diff between before_snapshot and current workspace state.
        
        Args:
            before_snapshot: Previous snapshot to compare against.
            
        Returns:
            Dictionary mapping file paths to their unified diffs.
        """
        root = Path(self.workspace_root)
        diffs = {}
        all_paths = set(before_snapshot.keys())

        # Check current files
        if root.exists() and root.is_dir():
            for file_path in root.rglob("*"):
                if file_path.is_file():
                    try:
                        rel = str(file_path.relative_to(root))
                        all_paths.add(rel)
                    except (OSError, ValueError):
                        continue

        for rel_path in all_paths:
            current = root / rel_path
            before_content = before_snapshot.get(rel_path)
            if current.exists() and current.is_file():
                try:
                    after_content = current.read_text(errors="replace")
                except (OSError, PermissionError):
                    continue
                if before_content is None:
                    diffs[rel_path] = f"ADDED: {rel_path}"
                elif after_content != before_content:
                    diffs[rel_path] = self.compute_diff(before_content, after_content, rel_path)
            elif before_content is not None:
                diffs[rel_path] = f"DELETED: {rel_path}"
        self.source_diff = diffs
        return diffs


def create_workspace_manager(config: Dict = None, event_bus: 'EventBus' = None) -> WorkspaceIsolationManager:
    """
    Factory function to create a WorkspaceIsolationManager.
    
    Args:
        config: Configuration dictionary
        event_bus: Optional EventBus for events
        
    Returns:
        Configured WorkspaceIsolationManager instance
    """
    return WorkspaceIsolationManager(config, event_bus)
