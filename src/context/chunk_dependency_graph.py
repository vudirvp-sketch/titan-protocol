"""
Chunk Dependency Graph for Recovery for TITAN FUSE Protocol.

ITEM-FEAT-74: Intelligent partial recovery using dependency tracking.

This module provides a dependency graph for chunks, enabling:
- Tracking chunk processing status
- Determining which chunks can be processed in parallel
- Computing recovery sets when a chunk fails
- Checkpoint integration for persistence

Author: TITAN FUSE Team
Version: 4.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Set, Optional, Any, TYPE_CHECKING
import logging
import json

if TYPE_CHECKING:
    from ..events.event_bus import EventBus, Event


def _utc_now_iso() -> str:
    """Get current UTC time as ISO format string."""
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


class ChunkStatus(Enum):
    """
    Status of a chunk in the dependency graph.
    
    States:
        PENDING: Not yet processed, dependencies may or may not be satisfied
        READY: All dependencies satisfied, ready to process
        IN_PROGRESS: Currently being processed
        COMPLETED: Successfully processed
        FAILED: Processing failed
        SKIPPED: Skipped due to dependency failure
    """
    PENDING = "pending"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    
    def is_terminal(self) -> bool:
        """Check if this is a terminal state (no further transitions)."""
        return self in (ChunkStatus.COMPLETED, ChunkStatus.FAILED, ChunkStatus.SKIPPED)
    
    def is_processable(self) -> bool:
        """Check if the chunk can be processed (ready or in progress for retry)."""
        return self in (ChunkStatus.READY, ChunkStatus.FAILED)


@dataclass
class ChunkNode:
    """
    Node in the chunk dependency graph.
    
    Represents a single chunk with its dependencies, status, and metadata.
    """
    chunk_id: str
    dependencies: Set[str] = field(default_factory=set)
    status: ChunkStatus = ChunkStatus.PENDING
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "chunk_id": self.chunk_id,
            "dependencies": list(self.dependencies),
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChunkNode':
        """Create from dictionary."""
        return cls(
            chunk_id=data.get("chunk_id", ""),
            dependencies=set(data.get("dependencies", [])),
            status=ChunkStatus(data.get("status", "pending")),
            created_at=data.get("created_at", _utc_now_iso()),
            updated_at=data.get("updated_at", _utc_now_iso()),
            error_message=data.get("error_message"),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            metadata=data.get("metadata", {})
        )
    
    def update_status(self, new_status: ChunkStatus, error: str = None) -> None:
        """Update the chunk status."""
        self.status = new_status
        self.updated_at = _utc_now_iso()
        if error:
            self.error_message = error


@dataclass
class DependencyGraphStats:
    """Statistics about the dependency graph."""
    total_chunks: int = 0
    pending_count: int = 0
    ready_count: int = 0
    in_progress_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_chunks": self.total_chunks,
            "pending_count": self.pending_count,
            "ready_count": self.ready_count,
            "in_progress_count": self.in_progress_count,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count
        }


class ChunkDependencyGraph:
    """
    Dependency graph for tracking chunk processing status and relationships.
    
    ITEM-FEAT-74 Implementation:
    - Add chunks with their dependencies
    - Query dependencies and dependents
    - Determine which chunks can be processed
    - Compute parallel processing sets
    - Support partial recovery when chunks fail
    
    Features:
    - Thread-safe operations (when used with external locking)
    - Checkpoint serialization support
    - Event emission for status changes
    - Efficient dependency traversal
    
    Usage:
        graph = ChunkDependencyGraph()
        
        # Add chunks with dependencies
        graph.add_chunk("chunk_1", [])
        graph.add_chunk("chunk_2", ["chunk_1"])
        graph.add_chunk("chunk_3", ["chunk_1"])
        
        # Get chunks that can be processed in parallel
        parallel = graph.get_parallel_chunks(set())
        # Returns: ["chunk_1"]
        
        # Mark a chunk as completed
        graph.update_status("chunk_1", ChunkStatus.COMPLETED)
        
        # Now chunk_2 and chunk_3 are ready
        parallel = graph.get_parallel_chunks({"chunk_1"})
        # Returns: ["chunk_2", "chunk_3"]
    """
    
    def __init__(self, event_bus: 'EventBus' = None):
        """
        Initialize the chunk dependency graph.
        
        Args:
            event_bus: Optional EventBus for emitting status change events
        """
        self._chunks: Dict[str, ChunkNode] = {}
        self._dependents: Dict[str, Set[str]] = {}  # Reverse mapping: chunk -> who depends on it
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)
        
        self._logger.info("ChunkDependencyGraph initialized")
    
    def add_chunk(
        self, 
        chunk_id: str, 
        dependencies: List[str],
        metadata: Dict[str, Any] = None,
        max_retries: int = 3
    ) -> None:
        """
        Add a chunk to the dependency graph.
        
        Args:
            chunk_id: Unique identifier for the chunk
            dependencies: List of chunk IDs this chunk depends on
            metadata: Optional metadata for the chunk
            max_retries: Maximum retry count for this chunk
        """
        if chunk_id in self._chunks:
            self._logger.warning(f"Chunk {chunk_id} already exists, updating dependencies")
        
        # Create the chunk node
        node = ChunkNode(
            chunk_id=chunk_id,
            dependencies=set(dependencies),
            metadata=metadata or {},
            max_retries=max_retries
        )
        
        self._chunks[chunk_id] = node
        
        # Update reverse mapping (dependents)
        for dep in dependencies:
            if dep not in self._dependents:
                self._dependents[dep] = set()
            self._dependents[dep].add(chunk_id)
        
        self._logger.debug(f"Added chunk {chunk_id} with dependencies: {dependencies}")
        
        # Emit event if event bus is available
        self._emit_event("CHUNK_ADDED", {
            "chunk_id": chunk_id,
            "dependencies": dependencies
        })
    
    def get_dependencies(self, chunk_id: str) -> List[str]:
        """
        Get the dependencies of a chunk.
        
        Args:
            chunk_id: The chunk ID to query
            
        Returns:
            List of chunk IDs that this chunk depends on
        """
        if chunk_id not in self._chunks:
            self._logger.warning(f"Chunk {chunk_id} not found")
            return []
        
        return list(self._chunks[chunk_id].dependencies)
    
    def get_dependents(self, chunk_id: str) -> List[str]:
        """
        Get the chunks that depend on a given chunk.
        
        Args:
            chunk_id: The chunk ID to query
            
        Returns:
            List of chunk IDs that depend on this chunk
        """
        return list(self._dependents.get(chunk_id, set()))
    
    def can_process(self, chunk_id: str, completed: Set[str]) -> bool:
        """
        Check if a chunk can be processed given a set of completed chunks.
        
        A chunk can be processed if:
        1. All its dependencies are in the completed set
        2. The chunk exists in the graph
        3. The chunk is in a processable state (PENDING, READY, or FAILED)
        
        Args:
            chunk_id: The chunk ID to check
            completed: Set of chunk IDs that have been completed
            
        Returns:
            True if the chunk can be processed
        """
        if chunk_id not in self._chunks:
            self._logger.warning(f"Chunk {chunk_id} not found")
            return False
        
        node = self._chunks[chunk_id]
        
        # Check if the chunk is in a processable state
        if not node.status.is_processable() and node.status != ChunkStatus.PENDING:
            return False
        
        # Check if all dependencies are completed
        for dep in node.dependencies:
            if dep not in completed:
                return False
        
        return True
    
    def get_parallel_chunks(self, completed: Set[str]) -> List[str]:
        """
        Get chunks that can be processed in parallel given completed chunks.
        
        Returns all chunks where:
        1. All dependencies are satisfied
        2. The chunk is not already completed
        3. The chunk is in a processable state
        
        Args:
            completed: Set of chunk IDs that have been completed
            
        Returns:
            List of chunk IDs that can be processed in parallel
        """
        parallel = []
        
        for chunk_id, node in self._chunks.items():
            # Skip if already completed
            if chunk_id in completed:
                continue
            
            # Skip if in a terminal state other than FAILED (for retry)
            if node.status.is_terminal() and node.status != ChunkStatus.FAILED:
                continue
            
            # Check if all dependencies are satisfied
            if node.dependencies.issubset(completed):
                parallel.append(chunk_id)
        
        return parallel
    
    def get_recovery_chunks(self, failed_chunk: str) -> List[str]:
        """
        Get chunks that need reprocessing after a chunk fails.
        
        When a chunk fails, all chunks that transitively depend on it
        need to be reprocessed. This method computes that set.
        
        Args:
            failed_chunk: The chunk ID that failed
            
        Returns:
            List of chunk IDs that need reprocessing (including the failed chunk)
        """
        if failed_chunk not in self._chunks:
            self._logger.warning(f"Failed chunk {failed_chunk} not found in graph")
            return []
        
        recovery_set = set()
        to_process = [failed_chunk]
        
        while to_process:
            current = to_process.pop()
            
            if current in recovery_set:
                continue
            
            recovery_set.add(current)
            
            # Add all dependents to the queue
            for dependent in self._dependents.get(current, set()):
                if dependent not in recovery_set:
                    to_process.append(dependent)
        
        result = list(recovery_set)
        
        self._logger.info(
            f"Recovery set for {failed_chunk}: {len(result)} chunks need reprocessing"
        )
        
        self._emit_event("RECOVERY_COMPUTED", {
            "failed_chunk": failed_chunk,
            "recovery_chunks": result
        })
        
        return result
    
    def update_status(
        self, 
        chunk_id: str, 
        status: ChunkStatus, 
        error_message: str = None
    ) -> bool:
        """
        Update the status of a chunk.
        
        Args:
            chunk_id: The chunk ID to update
            status: The new status
            error_message: Optional error message (for FAILED status)
            
        Returns:
            True if update was successful
        """
        if chunk_id not in self._chunks:
            self._logger.warning(f"Cannot update status: chunk {chunk_id} not found")
            return False
        
        node = self._chunks[chunk_id]
        old_status = node.status
        
        # Handle retry count for failures
        if status == ChunkStatus.FAILED:
            node.retry_count += 1
            if node.retry_count >= node.max_retries:
                self._logger.warning(
                    f"Chunk {chunk_id} exceeded max retries ({node.max_retries})"
                )
        
        node.update_status(status, error_message)
        
        self._logger.debug(
            f"Updated chunk {chunk_id} status: {old_status.value} -> {status.value}"
        )
        
        self._emit_event("CHUNK_STATUS_CHANGED", {
            "chunk_id": chunk_id,
            "old_status": old_status.value,
            "new_status": status.value,
            "error_message": error_message
        })
        
        # If chunk failed or was skipped, mark dependent chunks
        if status in (ChunkStatus.FAILED, ChunkStatus.SKIPPED):
            self._mark_dependents_as_skipped(chunk_id)
        
        return True
    
    def _mark_dependents_as_skipped(self, chunk_id: str) -> None:
        """
        Mark all dependents of a failed/skipped chunk as skipped.
        
        Args:
            chunk_id: The chunk ID that failed or was skipped
        """
        for dependent in self._dependents.get(chunk_id, set()):
            if dependent in self._chunks:
                node = self._chunks[dependent]
                if not node.status.is_terminal():
                    node.update_status(
                        ChunkStatus.SKIPPED,
                        f"Dependency {chunk_id} failed"
                    )
                    self._logger.info(
                        f"Skipped chunk {dependent} due to failed dependency {chunk_id}"
                    )
                    # Recursively mark dependents
                    self._mark_dependents_as_skipped(dependent)
    
    def get_chunk_status(self, chunk_id: str) -> Optional[ChunkStatus]:
        """
        Get the status of a chunk.
        
        Args:
            chunk_id: The chunk ID to query
            
        Returns:
            ChunkStatus or None if chunk not found
        """
        if chunk_id not in self._chunks:
            return None
        return self._chunks[chunk_id].status
    
    def get_chunk_node(self, chunk_id: str) -> Optional[ChunkNode]:
        """
        Get the full chunk node.
        
        Args:
            chunk_id: The chunk ID to query
            
        Returns:
            ChunkNode or None if chunk not found
        """
        return self._chunks.get(chunk_id)
    
    def get_all_chunks(self) -> List[str]:
        """
        Get all chunk IDs in the graph.
        
        Returns:
            List of all chunk IDs
        """
        return list(self._chunks.keys())
    
    def get_stats(self) -> DependencyGraphStats:
        """
        Get statistics about the dependency graph.
        
        Returns:
            DependencyGraphStats with counts by status
        """
        stats = DependencyGraphStats(total_chunks=len(self._chunks))
        
        for node in self._chunks.values():
            if node.status == ChunkStatus.PENDING:
                stats.pending_count += 1
            elif node.status == ChunkStatus.READY:
                stats.ready_count += 1
            elif node.status == ChunkStatus.IN_PROGRESS:
                stats.in_progress_count += 1
            elif node.status == ChunkStatus.COMPLETED:
                stats.completed_count += 1
            elif node.status == ChunkStatus.FAILED:
                stats.failed_count += 1
            elif node.status == ChunkStatus.SKIPPED:
                stats.skipped_count += 1
        
        return stats
    
    def is_complete(self) -> bool:
        """
        Check if all chunks are in a terminal state.
        
        Returns:
            True if all chunks are completed, failed, or skipped
        """
        for node in self._chunks.values():
            if not node.status.is_terminal():
                return False
        return True
    
    def get_completion_percentage(self) -> float:
        """
        Get the percentage of chunks that are completed.
        
        Returns:
            Percentage (0.0 to 100.0)
        """
        if not self._chunks:
            return 0.0
        
        completed = sum(
            1 for node in self._chunks.values() 
            if node.status == ChunkStatus.COMPLETED
        )
        return (completed / len(self._chunks)) * 100.0
    
    def get_ready_chunks(self) -> List[str]:
        """
        Get all chunks that are ready to process (status == READY).
        
        Returns:
            List of chunk IDs with READY status
        """
        return [
            chunk_id for chunk_id, node in self._chunks.items()
            if node.status == ChunkStatus.READY
        ]
    
    def update_ready_status(self) -> int:
        """
        Update status of PENDING chunks to READY if dependencies are satisfied.
        
        Returns:
            Number of chunks updated to READY
        """
        completed = {
            chunk_id for chunk_id, node in self._chunks.items()
            if node.status == ChunkStatus.COMPLETED
        }
        
        updated_count = 0
        for chunk_id, node in self._chunks.items():
            if node.status == ChunkStatus.PENDING:
                if node.dependencies.issubset(completed):
                    node.update_status(ChunkStatus.READY)
                    updated_count += 1
        
        if updated_count > 0:
            self._logger.info(f"Updated {updated_count} chunks to READY status")
        
        return updated_count
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the graph to a dictionary for checkpointing.
        
        Returns:
            Dictionary representation of the graph
        """
        return {
            "version": "4.0.0",
            "chunks": {
                chunk_id: node.to_dict() 
                for chunk_id, node in self._chunks.items()
            },
            "stats": self.get_stats().to_dict()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], event_bus: 'EventBus' = None) -> 'ChunkDependencyGraph':
        """
        Deserialize a graph from a dictionary.
        
        Args:
            data: Dictionary representation of the graph
            event_bus: Optional EventBus for events
            
        Returns:
            ChunkDependencyGraph instance
        """
        graph = cls(event_bus=event_bus)
        
        chunks_data = data.get("chunks", {})
        for chunk_id, node_data in chunks_data.items():
            node = ChunkNode.from_dict(node_data)
            graph._chunks[chunk_id] = node
            
            # Rebuild reverse mapping
            for dep in node.dependencies:
                if dep not in graph._dependents:
                    graph._dependents[dep] = set()
                graph._dependents[dep].add(chunk_id)
        
        graph._logger.info(
            f"Loaded dependency graph with {len(graph._chunks)} chunks"
        )
        
        return graph
    
    def to_json(self) -> str:
        """
        Serialize the graph to JSON string.
        
        Returns:
            JSON string representation
        """
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_json(cls, json_str: str, event_bus: 'EventBus' = None) -> 'ChunkDependencyGraph':
        """
        Deserialize a graph from JSON string.
        
        Args:
            json_str: JSON string representation
            event_bus: Optional EventBus for events
            
        Returns:
            ChunkDependencyGraph instance
        """
        data = json.loads(json_str)
        return cls.from_dict(data, event_bus)
    
    def clear(self) -> None:
        """Clear all chunks from the graph."""
        self._chunks.clear()
        self._dependents.clear()
        self._logger.info("Cleared dependency graph")
    
    def remove_chunk(self, chunk_id: str) -> bool:
        """
        Remove a chunk from the graph.
        
        Note: This may leave orphaned dependencies if other chunks
        depend on this chunk.
        
        Args:
            chunk_id: The chunk ID to remove
            
        Returns:
            True if chunk was removed
        """
        if chunk_id not in self._chunks:
            return False
        
        # Remove from chunks
        del self._chunks[chunk_id]
        
        # Remove from dependents mapping
        if chunk_id in self._dependents:
            del self._dependents[chunk_id]
        
        # Remove from reverse dependencies
        for deps in self._dependents.values():
            deps.discard(chunk_id)
        
        self._logger.info(f"Removed chunk {chunk_id} from graph")
        return True
    
    def _emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Emit an event via the EventBus.
        
        Args:
            event_type: Type of event
            data: Event data
        """
        if not self._event_bus:
            return
        
        try:
            from ..events.event_bus import Event, EventSeverity
            
            event = Event(
                event_type=event_type,
                data=data,
                severity=EventSeverity.INFO,
                source="ChunkDependencyGraph"
            )
            self._event_bus.emit(event)
        except ImportError:
            try:
                from events.event_bus import Event, EventSeverity
                
                event = Event(
                    event_type=event_type,
                    data=data,
                    severity=EventSeverity.INFO,
                    source="ChunkDependencyGraph"
                )
                self._event_bus.emit(event)
            except Exception as e:
                self._logger.warning(f"Failed to emit event: {e}")
        except Exception as e:
            self._logger.warning(f"Failed to emit event: {e}")
    
    def get_critical_path(self) -> List[str]:
        """
        Get the critical path through the dependency graph.
        
        The critical path is the longest path from a root (no dependencies)
        to a leaf (no dependents). This represents the minimum time
        to complete all chunks if processed sequentially.
        
        Returns:
            List of chunk IDs on the critical path
        """
        if not self._chunks:
            return []
        
        # Find root chunks (no dependencies)
        roots = [
            chunk_id for chunk_id, node in self._chunks.items()
            if not node.dependencies
        ]
        
        if not roots:
            # All chunks have dependencies - there may be a cycle
            self._logger.warning("No root chunks found - possible cycle in graph")
            return []
        
        # DFS to find longest path
        memo: Dict[str, List[str]] = {}
        
        def longest_path(chunk_id: str) -> List[str]:
            if chunk_id in memo:
                return memo[chunk_id]
            
            dependents = self._dependents.get(chunk_id, set())
            
            if not dependents:
                memo[chunk_id] = [chunk_id]
                return memo[chunk_id]
            
            best_path = [chunk_id]
            for dep in dependents:
                path = [chunk_id] + longest_path(dep)
                if len(path) > len(best_path):
                    best_path = path
            
            memo[chunk_id] = best_path
            return best_path
        
        # Find longest path from all roots
        critical_path = []
        for root in roots:
            path = longest_path(root)
            if len(path) > len(critical_path):
                critical_path = path
        
        return critical_path
    
    def get_processing_order(self) -> List[str]:
        """
        Get a valid processing order for all chunks.
        
        Uses topological sort to produce an order where dependencies
        are processed before the chunks that depend on them.
        
        Returns:
            List of chunk IDs in a valid processing order
        """
        result = []
        visited = set()
        temp_mark = set()
        
        def visit(chunk_id: str) -> bool:
            if chunk_id in temp_mark:
                self._logger.warning(f"Cycle detected at chunk {chunk_id}")
                return False
            
            if chunk_id in visited:
                return True
            
            temp_mark.add(chunk_id)
            
            for dep in self._chunks.get(chunk_id, ChunkNode(chunk_id)).dependencies:
                if dep in self._chunks:
                    if not visit(dep):
                        return False
            
            temp_mark.remove(chunk_id)
            visited.add(chunk_id)
            result.append(chunk_id)
            return True
        
        for chunk_id in self._chunks:
            if chunk_id not in visited:
                if not visit(chunk_id):
                    self._logger.warning("Could not compute processing order due to cycle")
                    return []
        
        return result
    
    def __len__(self) -> int:
        """Return the number of chunks in the graph."""
        return len(self._chunks)
    
    def __contains__(self, chunk_id: str) -> bool:
        """Check if a chunk exists in the graph."""
        return chunk_id in self._chunks
    
    def __repr__(self) -> str:
        """String representation of the graph."""
        stats = self.get_stats()
        return (
            f"<ChunkDependencyGraph("
            f"chunks={stats.total_chunks}, "
            f"completed={stats.completed_count}, "
            f"pending={stats.pending_count}, "
            f"failed={stats.failed_count})>"
        )


def create_dependency_graph(event_bus: 'EventBus' = None) -> ChunkDependencyGraph:
    """
    Factory function to create a ChunkDependencyGraph.
    
    Args:
        event_bus: Optional EventBus for events
        
    Returns:
        ChunkDependencyGraph instance
    """
    return ChunkDependencyGraph(event_bus=event_bus)
