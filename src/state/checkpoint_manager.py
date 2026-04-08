"""
Checkpoint Manager for TITAN FUSE Protocol.

ITEM-STOR-02: Checkpoint Session Isolation
ITEM-FEAT-74: Chunk Dependency Graph Checkpoint Integration

Provides session-isolated checkpoint management with:
- Namespace-based path isolation (checkpoints/{namespace}/{session_id}/)
- Backward compatibility via symlink (checkpoints/current)
- Atomic operations for save/load
- Multi-session support
- Chunk dependency graph persistence for recovery

Integration with:
- StorageBackend (ITEM-STOR-01) for cloud storage support
- CheckpointSerialization (ITEM-SEC-02) for safe serialization
- ChunkDependencyGraph (ITEM-FEAT-74) for partial recovery

Author: TITAN FUSE Team
Version: 4.0.0
"""

import json
import os
import shutil
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from src.utils.timezone import now_utc, now_utc_iso

# Import migration framework (ITEM-OPS-79)
from src.schema.migrations import apply_migrations, CURRENT_SCHEMA_VERSION

# Import from sibling modules
from .checkpoint_serialization import (
    SerializationFormat,
    SerializationResult,
    serialize_checkpoint,
    deserialize_checkpoint,
    serialize_checkpoint_to_storage,
    deserialize_checkpoint_from_storage
)


@dataclass
class CheckpointMetadata:
    """
    Metadata for a checkpoint session.
    
    Attributes:
        session_id: Unique session identifier
        namespace: Namespace for isolation
        created_at: Creation timestamp
        updated_at: Last update timestamp
        size_bytes: Total checkpoint size
        format: Serialization format used
        checksum: SHA-256 checksum
        version: Checkpoint format version
        tags: Optional tags for categorization
    """
    session_id: str
    namespace: str = "default"
    created_at: str = ""
    updated_at: str = ""
    size_bytes: int = 0
    format: str = "json_zstd"
    checksum: str = ""
    version: str = "3.3.0"
    tags: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = now_utc_iso()
        if not self.updated_at:
            self.updated_at = self.created_at
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "session_id": self.session_id,
            "namespace": self.namespace,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "size_bytes": self.size_bytes,
            "format": self.format,
            "checksum": self.checksum,
            "version": self.version,
            "tags": self.tags
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CheckpointMetadata':
        """Create from dictionary."""
        return cls(
            session_id=data.get("session_id", ""),
            namespace=data.get("namespace", "default"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            size_bytes=data.get("size_bytes", 0),
            format=data.get("format", "json_zstd"),
            checksum=data.get("checksum", ""),
            version=data.get("version", "3.3.0"),
            tags=data.get("tags", [])
        )


class CheckpointManager:
    """
    Session-isolated checkpoint manager.
    
    ITEM-STOR-02 Implementation:
    - Namespace-based path isolation
    - Backward compatibility via symlink
    - Multi-session support
    - Integration with StorageBackend
    
    Path Structure:
        checkpoints/
        ├── {namespace}/
        │   ├── {session_id}/
        │   │   ├── checkpoint.json (or .json.zst)
        │   │   └── metadata.json
        │   └── ...
        └── current -> {namespace}/{latest_session}/checkpoint.json
    
    Usage:
        # Using local filesystem (default)
        manager = CheckpointManager()
        manager.save("session-123", checkpoint_data)
        data = manager.load("session-123")
        
        # Using StorageBackend for cloud storage
        from src.storage import get_storage_backend
        backend = get_storage_backend(config)
        manager = CheckpointManager(backend=backend)
        manager.save("session-123", checkpoint_data)
    """
    
    DEFAULT_CHECKPOINT_DIR = "checkpoints"
    DEFAULT_NAMESPACE = "default"
    CURRENT_SYMLINK = "current"
    
    def __init__(
        self,
        backend=None,  # StorageBackend instance (optional)
        namespace: str = None,
        base_path: Path = None,
        config: Dict = None
    ):
        """
        Initialize CheckpointManager.
        
        Args:
            backend: StorageBackend instance for cloud storage (optional)
            namespace: Namespace for session isolation (default: from config)
            base_path: Base path for local storage (default: checkpoints/)
            config: Configuration dictionary
        """
        self.logger = logging.getLogger(__name__)
        
        # Get configuration
        config = config or {}
        storage_config = config.get("storage", {})
        
        # Set namespace
        self.namespace = namespace or storage_config.get("namespace", self.DEFAULT_NAMESPACE)
        
        # Set backend
        self.backend = backend
        
        # Set base path for local storage
        if base_path:
            self.base_path = Path(base_path)
        else:
            local_config = storage_config.get("local", {})
            self.base_path = Path(local_config.get("base_path", self.DEFAULT_CHECKPOINT_DIR))
        
        # Create base directory if needed
        if not self.backend:
            self.base_path.mkdir(parents=True, exist_ok=True)
        
        # Track latest session for symlink
        self._latest_session: Optional[str] = None
        
        self.logger.info(
            f"CheckpointManager initialized: namespace={self.namespace}, "
            f"backend={self.backend.__class__.__name__ if self.backend else 'local'}"
        )
    
    def _get_session_path(self, session_id: str) -> str:
        """
        Get path for a session's checkpoint directory.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Path like: checkpoints/{namespace}/{session_id}/
        """
        return f"{self.DEFAULT_CHECKPOINT_DIR}/{self.namespace}/{session_id}"
    
    def _get_checkpoint_path(self, session_id: str, filename: str = "checkpoint.json") -> str:
        """
        Get path for a session's checkpoint file.
        
        Args:
            session_id: Session identifier
            filename: Checkpoint filename
            
        Returns:
            Path like: checkpoints/{namespace}/{session_id}/checkpoint.json
        """
        return f"{self._get_session_path(session_id)}/{filename}"
    
    def _get_metadata_path(self, session_id: str) -> str:
        """
        Get path for a session's metadata file.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Path like: checkpoints/{namespace}/{session_id}/metadata.json
        """
        return f"{self._get_session_path(session_id)}/metadata.json"
    
    def save(
        self,
        session_id: str,
        data: Dict[str, Any],
        format: SerializationFormat = SerializationFormat.JSON_ZSTD,
        metadata: Dict[str, str] = None,
        unsafe_mode: bool = False
    ) -> SerializationResult:
        """
        Save checkpoint data for a session.
        
        Creates session-isolated directory structure and saves checkpoint
        with metadata. Updates the 'current' symlink for backward compatibility.
        
        Args:
            session_id: Unique session identifier
            data: Checkpoint data dictionary
            format: Serialization format (default: JSON_ZSTD)
            metadata: Optional additional metadata
            unsafe_mode: Allow unsafe pickle serialization
            
        Returns:
            SerializationResult with success status and metadata
            
        Example:
            manager = CheckpointManager()
            result = manager.save(
                "session-abc123",
                {"state": "active", "progress": 0.5}
            )
            if result.success:
                print(f"Saved to: {result.path}")
        """
        self.logger.info(f"Saving checkpoint for session: {session_id}")
        
        # Prepare checkpoint data
        checkpoint_data = data.copy()
        
        # Add manager metadata
        checkpoint_data['_checkpoint_manager'] = {
            'session_id': session_id,
            'namespace': self.namespace,
            'saved_at': now_utc_iso(),
            'version': '3.3.0'
        }
        
        # Determine file extension
        ext = format.file_extension if format != SerializationFormat.JSON_ZSTD else ".json.zst"
        filename = f"checkpoint{ext}"
        checkpoint_path = self._get_checkpoint_path(session_id, filename)
        
        try:
            if self.backend:
                # Use StorageBackend
                result = serialize_checkpoint_to_storage(
                    checkpoint_data,
                    self.backend,
                    checkpoint_path,
                    format=format,
                    unsafe_mode=unsafe_mode,
                    metadata=metadata
                )
            else:
                # Use local filesystem
                local_path = self.base_path / checkpoint_path
                local_path.parent.mkdir(parents=True, exist_ok=True)
                result = serialize_checkpoint(
                    checkpoint_data,
                    local_path,
                    format=format,
                    unsafe_mode=unsafe_mode
                )
            
            if not result.success:
                self.logger.error(f"Failed to save checkpoint: {result.error}")
                return result
            
            # Save metadata
            self._save_checkpoint_metadata(
                session_id,
                result,
                metadata
            )
            
            # Update symlink
            self._update_current_symlink(session_id)
            
            # Track as latest session
            self._latest_session = session_id
            
            self.logger.info(
                f"Checkpoint saved: session={session_id}, "
                f"size={result.size_bytes}, checksum={result.checksum}"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Checkpoint save failed: {e}")
            return SerializationResult(
                success=False,
                format=format,
                error=str(e)
            )
    
    def _save_checkpoint_metadata(
        self,
        session_id: str,
        result: SerializationResult,
        extra_metadata: Dict[str, str] = None
    ) -> None:
        """Save metadata file for a checkpoint."""
        metadata = CheckpointMetadata(
            session_id=session_id,
            namespace=self.namespace,
            size_bytes=result.size_bytes,
            format=result.format.value if result.format else "unknown",
            checksum=result.checksum or ""
        )
        
        metadata_dict = metadata.to_dict()
        if extra_metadata:
            metadata_dict["extra"] = extra_metadata
        
        metadata_path = self._get_metadata_path(session_id)
        
        try:
            if self.backend:
                # Use StorageBackend
                self.backend.save(
                    metadata_path,
                    json.dumps(metadata_dict, indent=2).encode('utf-8'),
                    {'content_type': 'application/json'}
                )
            else:
                # Use local filesystem
                local_path = self.base_path / metadata_path
                local_path.parent.mkdir(parents=True, exist_ok=True)
                with open(local_path, 'w') as f:
                    json.dump(metadata_dict, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to save metadata: {e}")
    
    def _update_current_symlink(self, session_id: str) -> None:
        """
        Update the 'current' symlink to point to the latest checkpoint.
        
        This provides backward compatibility for code that expects
        checkpoints/current to point to the latest checkpoint.
        
        Only works with local filesystem backend.
        """
        if self.backend:
            # Symlinks not supported for cloud storage
            self.logger.debug("Skipping symlink for cloud storage backend")
            return
        
        try:
            symlink_path = self.base_path / self.CURRENT_SYMLINK
            target_path = self._get_checkpoint_path(session_id)
            
            # Remove existing symlink
            if symlink_path.is_symlink() or symlink_path.exists():
                symlink_path.unlink()
            
            # Create new symlink
            symlink_path.symlink_to(target_path)
            
            self.logger.debug(f"Updated symlink: {symlink_path} -> {target_path}")
            
        except Exception as e:
            self.logger.warning(f"Failed to update symlink: {e}")
    
    def load(
        self,
        session_id: str,
        unsafe_mode: bool = False
    ) -> tuple:
        """
        Load checkpoint data for a session.
        
        Args:
            session_id: Session identifier
            unsafe_mode: Allow loading pickle checkpoints
            
        Returns:
            Tuple of (data: Dict, result: SerializationResult)
            
        Raises:
            FileNotFoundError: If checkpoint doesn't exist
        """
        self.logger.info(f"Loading checkpoint for session: {session_id}")
        
        # Try different formats (most specific first)
        formats_to_try = [
            ("checkpoint.json.zst", SerializationFormat.JSON_ZSTD),
            ("checkpoint.json.gz", SerializationFormat.JSON),  # gzip fallback
            ("checkpoint.json", SerializationFormat.JSON),
            ("checkpoint.pkl", SerializationFormat.PICKLE_UNSAFE),
        ]
        
        last_error = None
        
        for filename, format in formats_to_try:
            checkpoint_path = self._get_checkpoint_path(session_id, filename)
            
            try:
                if self.backend:
                    # Use StorageBackend
                    if not self.backend.exists(checkpoint_path):
                        continue
                    
                    data, result = deserialize_checkpoint_from_storage(
                        self.backend,
                        checkpoint_path,
                        format=format,
                        unsafe_mode=unsafe_mode
                    )
                else:
                    # Use local filesystem
                    local_path = self.base_path / checkpoint_path
                    if not local_path.exists():
                        continue
                    
                    data, result = deserialize_checkpoint(
                        path=local_path,
                        format=format,
                        unsafe_mode=unsafe_mode
                    )
                
                if result.success:
                    # ITEM-OPS-79: Auto-migrate checkpoint if version mismatch
                    checkpoint_version = data.get("protocol_version", "unknown")
                    if checkpoint_version != CURRENT_SCHEMA_VERSION:
                        self.logger.info(
                            f"Migrating checkpoint from {checkpoint_version} to {CURRENT_SCHEMA_VERSION}"
                        )
                        data = apply_migrations(data)
                        self.logger.info(
                            f"Migration complete: now at version {data.get('protocol_version')}"
                        )
                    
                    self.logger.info(
                        f"Checkpoint loaded: session={session_id}, "
                        f"format={result.format.value if result.format else 'unknown'}, "
                        f"version={data.get('protocol_version', 'unknown')}"
                    )
                    return data, result
                    
            except Exception as e:
                last_error = e
                self.logger.debug(f"Failed to load {filename}: {e}")
                continue
        
        # No checkpoint found
        error_msg = f"No checkpoint found for session: {session_id}"
        if last_error:
            error_msg += f" (last error: {last_error})"
        
        self.logger.error(error_msg)
        return {}, SerializationResult(
            success=False,
            error=error_msg
        )
    
    def list_sessions(self) -> List[str]:
        """
        List all session IDs with checkpoints in this namespace.
        
        Returns:
            List of session IDs
        """
        sessions = []
        
        try:
            if self.backend:
                # Use StorageBackend
                prefix = f"{self.DEFAULT_CHECKPOINT_DIR}/{self.namespace}/"
                paths = self.backend.list(prefix)
                
                for path in paths:
                    # Extract session_id from path
                    parts = path.replace(prefix, "").split("/")
                    if parts:
                        session_id = parts[0]
                        if session_id and session_id not in sessions:
                            sessions.append(session_id)
            else:
                # Use local filesystem
                namespace_path = self.base_path / self.DEFAULT_CHECKPOINT_DIR / self.namespace
                
                if namespace_path.exists():
                    for item in namespace_path.iterdir():
                        if item.is_dir():
                            # Check if it has a checkpoint file
                            has_checkpoint = any(
                                item.glob("checkpoint.*")
                            )
                            if has_checkpoint:
                                sessions.append(item.name)
            
            sessions.sort()
            self.logger.debug(f"Found {len(sessions)} sessions in namespace {self.namespace}")
            
        except Exception as e:
            self.logger.error(f"Failed to list sessions: {e}")
        
        return sessions
    
    def delete(self, session_id: str) -> bool:
        """
        Delete a session's checkpoint.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if deleted, False if not found
        """
        self.logger.info(f"Deleting checkpoint for session: {session_id}")
        
        session_path = self._get_session_path(session_id)
        deleted = False
        
        try:
            if self.backend:
                # Use StorageBackend - delete all files in session directory
                files = self.backend.list(session_path)
                for file_path in files:
                    self.backend.delete(file_path)
                deleted = len(files) > 0
            else:
                # Use local filesystem
                local_path = self.base_path / session_path
                if local_path.exists():
                    shutil.rmtree(local_path)
                    deleted = True
            
            if deleted:
                self.logger.info(f"Deleted checkpoint: session={session_id}")
                
                # Update symlink if this was the latest session
                if self._latest_session == session_id:
                    self._latest_session = None
                    # Point symlink to next available session
                    sessions = self.list_sessions()
                    if sessions:
                        self._update_current_symlink(sessions[-1])
                    elif not self.backend:
                        # Remove symlink if no sessions left
                        symlink_path = self.base_path / self.CURRENT_SYMLINK
                        if symlink_path.exists() or symlink_path.is_symlink():
                            symlink_path.unlink()
            
            return deleted
            
        except Exception as e:
            self.logger.error(f"Failed to delete checkpoint: {e}")
            return False
    
    def get_metadata(self, session_id: str) -> Optional[CheckpointMetadata]:
        """
        Get metadata for a session's checkpoint.
        
        Args:
            session_id: Session identifier
            
        Returns:
            CheckpointMetadata or None if not found
        """
        metadata_path = self._get_metadata_path(session_id)
        
        try:
            if self.backend:
                if not self.backend.exists(metadata_path):
                    return None
                
                data = self.backend.load(metadata_path)
                metadata_dict = json.loads(data.decode('utf-8'))
            else:
                local_path = self.base_path / metadata_path
                if not local_path.exists():
                    return None
                
                with open(local_path, 'r') as f:
                    metadata_dict = json.load(f)
            
            return CheckpointMetadata.from_dict(metadata_dict)
            
        except Exception as e:
            self.logger.warning(f"Failed to load metadata: {e}")
            return None
    
    def get_latest_session(self) -> Optional[str]:
        """
        Get the most recently saved session ID.
        
        Returns:
            Session ID of latest checkpoint, or None if no checkpoints
        """
        if self._latest_session:
            return self._latest_session
        
        # Find latest by metadata timestamp
        sessions = self.list_sessions()
        if not sessions:
            return None
        
        latest_session = None
        latest_time = None
        
        for session_id in sessions:
            metadata = self.get_metadata(session_id)
            if metadata:
                updated_at = metadata.updated_at
                if latest_time is None or updated_at > latest_time:
                    latest_time = updated_at
                    latest_session = session_id
        
        return latest_session or sessions[-1]
    
    def session_exists(self, session_id: str) -> bool:
        """
        Check if a session has a checkpoint.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if checkpoint exists
        """
        # Check for any checkpoint file (including gzip fallback)
        formats_to_check = [
            "checkpoint.json.zst",
            "checkpoint.json.gz",
            "checkpoint.json",
            "checkpoint.pkl"
        ]
        
        for filename in formats_to_check:
            checkpoint_path = self._get_checkpoint_path(session_id, filename)
            
            if self.backend:
                if self.backend.exists(checkpoint_path):
                    return True
            else:
                local_path = self.base_path / checkpoint_path
                if local_path.exists():
                    return True
        
        # Also check if session directory exists with any checkpoint file
        if not self.backend:
            session_dir = self.base_path / self._get_session_path(session_id)
            if session_dir.exists():
                checkpoint_files = list(session_dir.glob("checkpoint.*"))
                return len(checkpoint_files) > 0
        
        return False
    
    def cleanup_old_sessions(self, max_age_days: int = 30) -> int:
        """
        Delete checkpoints older than max_age_days.
        
        Args:
            max_age_days: Maximum age in days
            
        Returns:
            Number of sessions deleted
        """
        from datetime import timedelta
        
        deleted_count = 0
        cutoff = now_utc() - timedelta(days=max_age_days)
        cutoff_str = cutoff.isoformat() + "Z"
        
        sessions = self.list_sessions()
        
        for session_id in sessions:
            metadata = self.get_metadata(session_id)
            if metadata and metadata.updated_at < cutoff_str:
                if self.delete(session_id):
                    deleted_count += 1
                    self.logger.info(f"Cleaned up old session: {session_id}")
        
        self.logger.info(f"Cleanup complete: {deleted_count} sessions deleted")
        return deleted_count
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Get statistics about checkpoint storage.
        
        Returns:
            Dictionary with storage statistics
        """
        sessions = self.list_sessions()
        total_size = 0
        
        for session_id in sessions:
            metadata = self.get_metadata(session_id)
            if metadata:
                total_size += metadata.size_bytes
        
        return {
            "namespace": self.namespace,
            "session_count": len(sessions),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "backend_type": self.backend.__class__.__name__ if self.backend else "local",
            "latest_session": self.get_latest_session()
        }
    
    def __repr__(self) -> str:
        return (
            f"<CheckpointManager(namespace='{self.namespace}', "
            f"backend={self.backend.__class__.__name__ if self.backend else 'local'})>"
        )
    
    # === Chunk Dependency Graph Integration (ITEM-FEAT-74) ===
    
    def _get_chunk_graph_path(self, session_id: str) -> str:
        """
        Get path for a session's chunk dependency graph.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Path like: checkpoints/{namespace}/{session_id}/chunk_graph.json
        """
        return f"{self._get_session_path(session_id)}/chunk_graph.json"
    
    def save_chunk_graph(
        self,
        session_id: str,
        graph: 'ChunkDependencyGraph'
    ) -> bool:
        """
        Save a chunk dependency graph for a session.
        
        ITEM-FEAT-74: Persists the chunk dependency graph to enable
        intelligent partial recovery after failures.
        
        Args:
            session_id: Session identifier
            graph: ChunkDependencyGraph instance to save
            
        Returns:
            True if saved successfully
            
        Example:
            from context.chunk_dependency_graph import ChunkDependencyGraph
            
            manager = CheckpointManager()
            graph = ChunkDependencyGraph()
            graph.add_chunk("chunk_1", [])
            
            # Save the graph
            manager.save_chunk_graph("session-123", graph)
        """
        self.logger.info(f"Saving chunk dependency graph for session: {session_id}")
        
        graph_path = self._get_chunk_graph_path(session_id)
        
        try:
            # Serialize the graph
            graph_data = graph.to_dict()
            graph_json = json.dumps(graph_data, indent=2)
            
            if self.backend:
                # Use StorageBackend
                self.backend.save(
                    graph_path,
                    graph_json.encode('utf-8'),
                    {'content_type': 'application/json'}
                )
            else:
                # Use local filesystem
                local_path = self.base_path / graph_path
                local_path.parent.mkdir(parents=True, exist_ok=True)
                with open(local_path, 'w') as f:
                    f.write(graph_json)
            
            self.logger.info(
                f"Chunk dependency graph saved: session={session_id}, "
                f"chunks={len(graph)}"
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to save chunk dependency graph: {e}")
            return False
    
    def load_chunk_graph(
        self,
        session_id: str,
        event_bus: 'EventBus' = None
    ) -> Optional['ChunkDependencyGraph']:
        """
        Load a chunk dependency graph for a session.
        
        ITEM-FEAT-74: Restores the chunk dependency graph to enable
        intelligent partial recovery after failures.
        
        Args:
            session_id: Session identifier
            event_bus: Optional EventBus for the restored graph
            
        Returns:
            ChunkDependencyGraph instance or None if not found
            
        Example:
            manager = CheckpointManager()
            graph = manager.load_chunk_graph("session-123")
            
            if graph:
                # Get chunks that need reprocessing
                recovery_set = graph.get_recovery_chunks("failed_chunk_id")
        """
        self.logger.info(f"Loading chunk dependency graph for session: {session_id}")
        
        graph_path = self._get_chunk_graph_path(session_id)
        
        try:
            if self.backend:
                # Use StorageBackend
                if not self.backend.exists(graph_path):
                    self.logger.debug(f"No chunk graph found for session: {session_id}")
                    return None
                
                data = self.backend.load(graph_path)
                graph_json = data.decode('utf-8')
            else:
                # Use local filesystem
                local_path = self.base_path / graph_path
                if not local_path.exists():
                    self.logger.debug(f"No chunk graph found for session: {session_id}")
                    return None
                
                with open(local_path, 'r') as f:
                    graph_json = f.read()
            
            # Import here to avoid circular imports
            from context.chunk_dependency_graph import ChunkDependencyGraph
            
            # Deserialize the graph
            graph_data = json.loads(graph_json)
            graph = ChunkDependencyGraph.from_dict(graph_data, event_bus=event_bus)
            
            self.logger.info(
                f"Chunk dependency graph loaded: session={session_id}, "
                f"chunks={len(graph)}"
            )
            
            return graph
            
        except Exception as e:
            self.logger.error(f"Failed to load chunk dependency graph: {e}")
            return None
    
    def save_checkpoint_with_graph(
        self,
        session_id: str,
        data: Dict[str, Any],
        graph: 'ChunkDependencyGraph',
        format: SerializationFormat = SerializationFormat.JSON_ZSTD,
        metadata: Dict[str, str] = None,
        unsafe_mode: bool = False
    ) -> tuple:
        """
        Save checkpoint data with chunk dependency graph.
        
        ITEM-FEAT-74: Convenience method to save both checkpoint data
        and the chunk dependency graph in one call.
        
        Args:
            session_id: Unique session identifier
            data: Checkpoint data dictionary
            graph: ChunkDependencyGraph instance
            format: Serialization format (default: JSON_ZSTD)
            metadata: Optional additional metadata
            unsafe_mode: Allow unsafe pickle serialization
            
        Returns:
            Tuple of (SerializationResult, bool) where bool indicates
            if the graph was saved successfully
            
        Example:
            manager = CheckpointManager()
            graph = ChunkDependencyGraph()
            # ... populate graph ...
            
            result, graph_saved = manager.save_checkpoint_with_graph(
                "session-123",
                {"state": "processing"},
                graph
            )
        """
        # Save the main checkpoint
        result = self.save(
            session_id,
            data,
            format=format,
            metadata=metadata,
            unsafe_mode=unsafe_mode
        )
        
        if not result.success:
            return result, False
        
        # Save the chunk graph
        graph_saved = self.save_chunk_graph(session_id, graph)
        
        return result, graph_saved
    
    def load_checkpoint_with_graph(
        self,
        session_id: str,
        event_bus: 'EventBus' = None,
        unsafe_mode: bool = False
    ) -> tuple:
        """
        Load checkpoint data with chunk dependency graph.
        
        ITEM-FEAT-74: Convenience method to load both checkpoint data
        and the chunk dependency graph in one call.
        
        Args:
            session_id: Session identifier
            event_bus: Optional EventBus for the restored graph
            unsafe_mode: Allow loading pickle checkpoints
            
        Returns:
            Tuple of (data: Dict, graph: ChunkDependencyGraph or None, result: SerializationResult)
            
        Example:
            manager = CheckpointManager()
            data, graph, result = manager.load_checkpoint_with_graph("session-123")
            
            if result.success and graph:
                # Resume processing with graph
                pass
        """
        # Load the main checkpoint
        data, result = self.load(session_id, unsafe_mode=unsafe_mode)
        
        if not result.success:
            return data, None, result
        
        # Load the chunk graph
        graph = self.load_chunk_graph(session_id, event_bus=event_bus)
        
        return data, graph, result
    
    def graph_exists(self, session_id: str) -> bool:
        """
        Check if a chunk dependency graph exists for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if graph exists
        """
        graph_path = self._get_chunk_graph_path(session_id)
        
        if self.backend:
            return self.backend.exists(graph_path)
        else:
            local_path = self.base_path / graph_path
            return local_path.exists()


# Factory function for convenience
def get_checkpoint_manager(
    config: Dict = None,
    backend = None,
    namespace: str = None,
    base_path: Path = None
) -> CheckpointManager:
    """
    Create a CheckpointManager instance.
    
    Args:
        config: Configuration dictionary
        backend: StorageBackend instance (optional)
        namespace: Namespace override (optional)
        base_path: Base path for local storage (optional)
        
    Returns:
        Configured CheckpointManager instance
    """
    return CheckpointManager(
        backend=backend,
        namespace=namespace,
        config=config,
        base_path=base_path
    )
