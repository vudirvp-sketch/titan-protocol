"""
Change Tracker for TITAN FUSE Protocol.

ITEM-SAE-007: Semantic Drift Detector - Change Tracker

Tracks file changes and their impact on context nodes.
Provides change history and impact analysis.

Key Features:
- File change recording
- Impact score calculation
- Affected node identification
- Change history management
- Integration with DriftDetector

Author: TITAN FUSE Team
Version: 1.0.0
"""

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple
import logging
import threading
import json

from src.utils.timezone import now_utc, now_utc_iso
from src.context.context_graph import ContextGraph, ContextNode
from src.context.semantic_checksum import SemanticChecksum, Language


class ChangeType(Enum):
    """Type of file change."""
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    SEMANTIC = "semantic"
    CONTENT = "content"


@dataclass
class FileChange:
    """
    Represents a change to a file.
    
    Attributes:
        file_path: Path to the changed file
        change_type: Type of change
        old_hash: Previous hash (if applicable)
        new_hash: New hash (if applicable)
        old_path: Previous path (for renames)
        timestamp: When the change was detected
        size_delta: Change in file size
        semantic_elements_added: Number of semantic elements added
        semantic_elements_removed: Number of semantic elements removed
        metadata: Additional metadata
    """
    file_path: str
    change_type: ChangeType
    old_hash: Optional[str] = None
    new_hash: Optional[str] = None
    old_path: Optional[str] = None
    timestamp: str = field(default_factory=now_utc_iso)
    size_delta: int = 0
    semantic_elements_added: int = 0
    semantic_elements_removed: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "file_path": self.file_path,
            "change_type": self.change_type.value,
            "old_hash": self.old_hash,
            "new_hash": self.new_hash,
            "old_path": self.old_path,
            "timestamp": self.timestamp,
            "size_delta": self.size_delta,
            "semantic_elements_added": self.semantic_elements_added,
            "semantic_elements_removed": self.semantic_elements_removed,
            "metadata": self.metadata,
        }


@dataclass
class ImpactScore:
    """
    Impact score for a change.
    
    Attributes:
        score: Impact score (0.0 to 1.0)
        affected_nodes: Number of affected context nodes
        severity: Severity level
        reasons: Reasons for the score
        suggested_actions: Suggested actions
    """
    score: float
    affected_nodes: int
    severity: str
    reasons: List[str] = field(default_factory=list)
    suggested_actions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "score": round(self.score, 3),
            "affected_nodes": self.affected_nodes,
            "severity": self.severity,
            "reasons": self.reasons,
            "suggested_actions": self.suggested_actions,
        }


class ChangeTracker:
    """
    Tracks file changes and their impact on context.
    
    Records file changes, computes impact scores, and identifies
    affected context nodes.
    
    Usage:
        tracker = ChangeTracker(context_graph)
        
        # Record a change
        tracker.record_change(change)
        
        # Get changes since a time
        changes = tracker.get_changes_since(timestamp)
        
        # Compute impact
        impact = tracker.compute_impact(change)
        
        # Get affected nodes
        nodes = tracker.get_affected_nodes(change)
    """
    
    def __init__(
        self,
        context_graph: Optional[ContextGraph] = None,
        max_history: int = 10000,
        persist_path: Optional[str] = None,
    ):
        """
        Initialize the ChangeTracker.
        
        Args:
            context_graph: Context graph to track
            max_history: Maximum number of changes to retain
            persist_path: Path for persistent storage
        """
        self._graph = context_graph
        self._max_history = max_history
        self._persist_path = persist_path
        
        self._changes: List[FileChange] = []
        self._file_index: Dict[str, List[int]] = {}  # file_path -> change indices
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)
        
        self._checksummer = SemanticChecksum()
        
        # Impact weights
        self._impact_weights = {
            ChangeType.DELETED: 1.0,
            ChangeType.SEMANTIC: 0.8,
            ChangeType.MODIFIED: 0.5,
            ChangeType.CREATED: 0.3,
            ChangeType.RENAMED: 0.2,
            ChangeType.CONTENT: 0.1,
        }
        
        # Load persisted changes
        if persist_path:
            self._load_persisted()
    
    def set_context_graph(self, graph: ContextGraph) -> None:
        """Set the context graph to track."""
        self._graph = graph
    
    # =========================================================================
    # Change Recording
    # =========================================================================
    
    def record_change(
        self,
        file_path: str,
        change_type: ChangeType,
        old_content: Optional[str] = None,
        new_content: Optional[str] = None,
        old_path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> FileChange:
        """
        Record a file change.
        
        Args:
            file_path: Path to the changed file
            change_type: Type of change
            old_content: Previous content (if available)
            new_content: Current content (if available)
            old_path: Previous path (for renames)
            metadata: Additional metadata
            
        Returns:
            Recorded FileChange
        """
        change = FileChange(
            file_path=file_path,
            change_type=change_type,
            old_path=old_path,
            metadata=metadata or {},
        )
        
        # Compute hashes
        if old_content:
            change.old_hash = hashlib.sha256(old_content.encode()).hexdigest()[:32]
        
        if new_content:
            change.new_hash = hashlib.sha256(new_content.encode()).hexdigest()[:32]
        
        # Compute semantic changes
        if old_content and new_content:
            language = self._checksummer.detect_language(file_path)
            
            if language != Language.UNKNOWN:
                old_result = self._checksummer.compute_ast_hash(old_content, language)
                new_result = self._checksummer.compute_ast_hash(new_content, language)
                
                change.semantic_elements_added = max(
                    0, new_result.element_count - old_result.element_count
                )
                change.semantic_elements_removed = max(
                    0, old_result.element_count - new_result.element_count
                )
                
                # Upgrade to semantic change if hashes differ
                if old_result.semantic_hash != new_result.semantic_hash:
                    change.change_type = ChangeType.SEMANTIC
                    change.metadata["semantic_change"] = True
        
        # Compute size delta
        try:
            if os.path.exists(file_path):
                change.size_delta = os.path.getsize(file_path)
                if old_content:
                    change.size_delta -= len(old_content.encode())
        except OSError:
            pass
        
        # Store the change
        with self._lock:
            self._changes.append(change)
            change_idx = len(self._changes) - 1
            
            if file_path not in self._file_index:
                self._file_index[file_path] = []
            self._file_index[file_path].append(change_idx)
            
            # Trim history if needed
            if len(self._changes) > self._max_history:
                self._trim_history()
        
        # Persist if configured
        if self._persist_path:
            self._persist()
        
        self._logger.debug(
            f"Recorded change: {file_path} ({change_type.value})"
        )
        
        return change
    
    def record_file_event(
        self,
        file_path: str,
        event_type: str,
        old_path: Optional[str] = None
    ) -> Optional[FileChange]:
        """
        Record a file system event.
        
        Args:
            file_path: Path to the file
            event_type: Event type (created, modified, deleted, moved)
            old_path: Previous path (for moved events)
            
        Returns:
            Recorded FileChange, or None if event type unknown
        """
        # Map event type to ChangeType
        type_map = {
            "created": ChangeType.CREATED,
            "modified": ChangeType.MODIFIED,
            "deleted": ChangeType.DELETED,
            "moved": ChangeType.RENAMED,
        }
        
        change_type = type_map.get(event_type)
        if not change_type:
            return None
        
        return self.record_change(
            file_path=file_path,
            change_type=change_type,
            old_path=old_path,
        )
    
    # =========================================================================
    # Query Operations
    # =========================================================================
    
    def get_changes_since(
        self,
        timestamp: datetime,
        limit: int = 1000
    ) -> List[FileChange]:
        """
        Get all changes since a timestamp.
        
        Args:
            timestamp: Starting timestamp
            limit: Maximum number of changes to return
            
        Returns:
            List of FileChange objects
        """
        result = []
        
        with self._lock:
            # Iterate in reverse to get most recent first
            for change in reversed(self._changes):
                try:
                    change_time = datetime.fromisoformat(change.timestamp)
                    if change_time >= timestamp:
                        result.append(change)
                    else:
                        break  # Changes are ordered by time
                except (ValueError, TypeError):
                    continue
                
                if len(result) >= limit:
                    break
        
        return result
    
    def get_file_history(
        self,
        file_path: str,
        limit: int = 100
    ) -> List[FileChange]:
        """
        Get change history for a specific file.
        
        Args:
            file_path: Path to the file
            limit: Maximum number of changes to return
            
        Returns:
            List of FileChange objects
        """
        with self._lock:
            indices = self._file_index.get(file_path, [])
            
            changes = [
                self._changes[i] for i in reversed(indices[-limit:])
                if i < len(self._changes)
            ]
        
        return changes
    
    def get_all_changes(self, limit: int = 1000) -> List[FileChange]:
        """Get all recent changes."""
        with self._lock:
            return list(self._changes[-limit:])
    
    # =========================================================================
    # Impact Analysis
    # =========================================================================
    
    def compute_impact(self, change: FileChange) -> ImpactScore:
        """
        Compute impact score for a change.
        
        Args:
            change: FileChange to analyze
            
        Returns:
            ImpactScore with analysis
        """
        # Base impact from change type
        base_score = self._impact_weights.get(change.change_type, 0.5)
        
        reasons = []
        suggested_actions = []
        
        # Adjust for semantic changes
        if change.change_type == ChangeType.SEMANTIC:
            base_score = min(1.0, base_score + 0.2)
            reasons.append("Semantic structure changed")
            suggested_actions.append("Refresh context for affected nodes")
        
        # Adjust for element changes
        if change.semantic_elements_added > 0:
            element_factor = min(0.2, change.semantic_elements_added * 0.02)
            base_score = min(1.0, base_score + element_factor)
            reasons.append(f"{change.semantic_elements_added} elements added")
        
        if change.semantic_elements_removed > 0:
            element_factor = min(0.3, change.semantic_elements_removed * 0.03)
            base_score = min(1.0, base_score + element_factor)
            reasons.append(f"{change.semantic_elements_removed} elements removed")
        
        # Count affected nodes
        affected_nodes = len(self.get_affected_nodes(change))
        
        # Determine severity
        if base_score >= 0.8:
            severity = "critical"
            suggested_actions.append("Immediate context refresh required")
        elif base_score >= 0.5:
            severity = "high"
            suggested_actions.append("Context refresh recommended")
        elif base_score >= 0.3:
            severity = "medium"
            suggested_actions.append("Consider refreshing context")
        else:
            severity = "low"
        
        return ImpactScore(
            score=base_score,
            affected_nodes=affected_nodes,
            severity=severity,
            reasons=reasons,
            suggested_actions=suggested_actions,
        )
    
    def get_affected_nodes(self, change: FileChange) -> List[str]:
        """
        Get context nodes affected by a change.
        
        Args:
            change: FileChange to analyze
            
        Returns:
            List of affected node IDs
        """
        if not self._graph:
            return []
        
        affected = []
        
        # Direct match
        for node in self._graph.get_all_nodes():
            if node.location == change.file_path:
                affected.append(node.id)
        
        # Check dependencies (edges)
        for node_id in affected[:]:  # Copy to avoid modification during iteration
            neighbors = self._graph.get_neighbors(node_id)
            for neighbor_id in neighbors:
                if neighbor_id not in affected:
                    affected.append(neighbor_id)
        
        return affected
    
    # =========================================================================
    # Statistics and Reporting
    # =========================================================================
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get change tracking statistics."""
        with self._lock:
            # Count by type
            type_counts: Dict[str, int] = {}
            for change in self._changes:
                type_name = change.change_type.value
                type_counts[type_name] = type_counts.get(type_name, 0) + 1
            
            # Most changed files
            file_change_counts = sorted(
                [(fp, len(indices)) for fp, indices in self._file_index.items()],
                key=lambda x: x[1],
                reverse=True
            )[:10]
            
            return {
                "total_changes": len(self._changes),
                "tracked_files": len(self._file_index),
                "change_types": type_counts,
                "most_changed_files": file_change_counts,
            }
    
    def generate_report(
        self,
        since: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Generate a comprehensive change report.
        
        Args:
            since: Starting timestamp (defaults to 24 hours ago)
            
        Returns:
            Dict with report data
        """
        since = since or (now_utc() - timedelta(hours=24))
        
        changes = self.get_changes_since(since)
        
        # Analyze changes
        semantic_changes = [
            c for c in changes
            if c.change_type == ChangeType.SEMANTIC
        ]
        
        high_impact_changes = [
            c for c in changes
            if self.compute_impact(c).score >= 0.5
        ]
        
        # Aggregate impact
        total_impact = sum(self.compute_impact(c).score for c in changes)
        avg_impact = total_impact / len(changes) if changes else 0.0
        
        return {
            "period_start": since.isoformat(),
            "period_end": now_utc_iso(),
            "total_changes": len(changes),
            "semantic_changes": len(semantic_changes),
            "high_impact_changes": len(high_impact_changes),
            "average_impact": round(avg_impact, 3),
            "changes": [c.to_dict() for c in changes[:50]],  # Limit output
            "generated_at": now_utc_iso(),
        }
    
    # =========================================================================
    # Internal Methods
    # =========================================================================
    
    def _trim_history(self) -> None:
        """Trim change history to max size."""
        if len(self._changes) <= self._max_history:
            return
        
        # Remove oldest changes
        to_remove = len(self._changes) - self._max_history
        self._changes = self._changes[to_remove:]
        
        # Rebuild index
        self._file_index.clear()
        for i, change in enumerate(self._changes):
            if change.file_path not in self._file_index:
                self._file_index[change.file_path] = []
            self._file_index[change.file_path].append(i)
    
    def _persist(self) -> None:
        """Persist changes to storage."""
        if not self._persist_path:
            return
        
        try:
            path = Path(self._persist_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "version": "1.0",
                "changes": [c.to_dict() for c in self._changes[-self._max_history:]],
            }
            
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            self._logger.error(f"Failed to persist changes: {e}")
    
    def _load_persisted(self) -> None:
        """Load persisted changes from storage."""
        if not self._persist_path:
            return
        
        try:
            path = Path(self._persist_path)
            if not path.exists():
                return
            
            with open(path, "r") as f:
                data = json.load(f)
            
            for change_data in data.get("changes", []):
                try:
                    change = FileChange(
                        file_path=change_data["file_path"],
                        change_type=ChangeType(change_data["change_type"]),
                        old_hash=change_data.get("old_hash"),
                        new_hash=change_data.get("new_hash"),
                        old_path=change_data.get("old_path"),
                        timestamp=change_data["timestamp"],
                        size_delta=change_data.get("size_delta", 0),
                        semantic_elements_added=change_data.get("semantic_elements_added", 0),
                        semantic_elements_removed=change_data.get("semantic_elements_removed", 0),
                        metadata=change_data.get("metadata", {}),
                    )
                    self._changes.append(change)
                except (KeyError, ValueError) as e:
                    self._logger.warning(f"Failed to load change: {e}")
            
            # Rebuild index
            self._file_index.clear()
            for i, change in enumerate(self._changes):
                if change.file_path not in self._file_index:
                    self._file_index[change.file_path] = []
                self._file_index[change.file_path].append(i)
            
            self._logger.info(f"Loaded {len(self._changes)} persisted changes")
            
        except Exception as e:
            self._logger.error(f"Failed to load persisted changes: {e}")


# =============================================================================
# Module-level convenience
# =============================================================================

_default_tracker: Optional[ChangeTracker] = None


def get_change_tracker(context_graph: Optional[ContextGraph] = None) -> ChangeTracker:
    """Get or create default ChangeTracker instance."""
    global _default_tracker
    
    if _default_tracker is None:
        _default_tracker = ChangeTracker(context_graph=context_graph)
    elif context_graph is not None:
        _default_tracker.set_context_graph(context_graph)
    
    return _default_tracker
