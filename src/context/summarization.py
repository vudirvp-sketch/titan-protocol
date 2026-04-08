"""
Recursive Summarization for TITAN FUSE Protocol.

ITEM-SAE-008: EXEC Stage Pruning - Recursive Summarization

Implements recursive summarization that prunes completed EXEC stages
while preserving essential information for long sessions.

Key Features:
- Stage summarization with compression
- Rollback point preservation
- Memory optimization for long sessions
- Compression ratio tracking

Benefits:
- Reduces memory consumption in long sessions
- Maintains essential context
- Preserves rollback capability
- Improves performance

Author: TITAN FUSE Team
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Union
import hashlib
import json
import logging
import threading

from src.utils.timezone import now_utc, now_utc_iso


class StageType(Enum):
    """Type of execution stage."""
    INIT = "INIT"
    DISCOVERY = "DISCOVERY"
    ANALYSIS = "ANALYSIS"
    PLANNING = "PLANNING"
    EXEC = "EXEC"
    DELIVERY = "DELIVERY"


class StageStatus(Enum):
    """Status of an execution stage."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class GateResult:
    """Result of a gate check."""
    gate_name: str
    passed: bool
    timestamp: str = field(default_factory=now_utc_iso)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_name": self.gate_name,
            "passed": self.passed,
            "timestamp": self.timestamp,
        }


@dataclass
class ExecutionStage:
    """
    Represents an execution stage in a session.
    
    Attributes:
        stage_id: Unique identifier for the stage
        stage_type: Type of the stage
        status: Current status
        start_time: When the stage started
        end_time: When the stage ended
        files_processed: List of files processed
        patches_applied: List of patches applied
        gates_passed: Gates that were passed
        errors_encountered: Errors that occurred
        tokens_used: Total tokens consumed
        metrics: Additional metrics
        parent_stage_id: Parent stage ID for nested stages
        rollback_point: Checkpoint ID for rollback
    """
    stage_id: str
    stage_type: StageType
    status: StageStatus = StageStatus.PENDING
    start_time: str = field(default_factory=now_utc_iso)
    end_time: Optional[str] = None
    files_processed: List[str] = field(default_factory=list)
    patches_applied: List[str] = field(default_factory=list)
    gates_passed: List[GateResult] = field(default_factory=list)
    errors_encountered: List[str] = field(default_factory=list)
    tokens_used: int = 0
    metrics: Dict[str, Any] = field(default_factory=dict)
    parent_stage_id: Optional[str] = None
    rollback_point: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "stage_id": self.stage_id,
            "stage_type": self.stage_type.value,
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "files_processed": self.files_processed,
            "patches_applied": self.patches_applied,
            "gates_passed": [g.to_dict() for g in self.gates_passed],
            "errors_encountered": self.errors_encountered,
            "tokens_used": self.tokens_used,
            "metrics": self.metrics,
            "parent_stage_id": self.parent_stage_id,
            "rollback_point": self.rollback_point,
        }
    
    @property
    def is_completed(self) -> bool:
        """Check if stage is completed."""
        return self.status == StageStatus.COMPLETED
    
    @property
    def can_prune(self) -> bool:
        """Check if stage can be pruned."""
        return self.status in (StageStatus.COMPLETED, StageStatus.FAILED, StageStatus.ROLLED_BACK)


@dataclass
class StageSummary:
    """
    Summarized version of an execution stage.
    
    Contains essential information preserved after pruning.
    """
    stage_id: str
    stage_type: StageType
    status: StageStatus
    start_time: str
    end_time: Optional[str]
    files_count: int
    patches_count: int
    gates_passed_count: int
    errors_count: int
    tokens_used: int
    key_decisions: List[str]
    rollback_point: Optional[str]
    summary_hash: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "stage_id": self.stage_id,
            "stage_type": self.stage_type.value,
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "files_count": self.files_count,
            "patches_count": self.patches_count,
            "gates_passed_count": self.gates_passed_count,
            "errors_count": self.errors_count,
            "tokens_used": self.tokens_used,
            "key_decisions": self.key_decisions,
            "rollback_point": self.rollback_point,
            "summary_hash": self.summary_hash,
        }
    
    def compute_hash(self) -> str:
        """Compute hash of the summary."""
        content = json.dumps(self.to_dict(), sort_keys=True)
        self.summary_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        return self.summary_hash


@dataclass
class CompressedSummary:
    """
    Compressed version of a stage summary.
    
    Uses compression to minimize memory footprint.
    """
    compressed_data: bytes
    original_size: int
    compressed_size: int
    compression_ratio: float
    summary_hash: str
    created_at: str = field(default_factory=now_utc_iso)
    
    @property
    def compression_savings(self) -> int:
        """Calculate bytes saved by compression."""
        return self.original_size - self.compressed_size


class RecursiveSummarizer:
    """
    Implements recursive summarization for execution stages.
    
    Prunes completed EXEC stages while preserving essential information,
    reducing memory consumption in long sessions.
    
    Usage:
        summarizer = RecursiveSummarizer()
        
        # Summarize a stage
        summary = summarizer.summarize_stage(stage)
        
        # Prune completed stages
        pruned = summarizer.prune_completed_stages(stages)
        
        # Compress summary
        compressed = summarizer.compress_summary(summary)
        
        # Reconstruct summary
        summary = summarizer.reconstruct_summary(compressed)
    """
    
    def __init__(
        self,
        max_stages_to_retain: int = 3,
        summary_compression_ratio: float = 0.2,
        preserve_rollback_points: bool = True,
    ):
        """
        Initialize the RecursiveSummarizer.
        
        Args:
            max_stages_to_retain: Maximum full stages to keep
            summary_compression_ratio: Target compression ratio
            preserve_rollback_points: Always preserve rollback data
        """
        self._max_stages = max_stages_to_retain
        self._compression_ratio = summary_compression_ratio
        self._preserve_rollback = preserve_rollback_points
        
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)
        
        # Statistics
        self._stats = {
            "stages_summarized": 0,
            "stages_pruned": 0,
            "bytes_saved": 0,
        }
    
    # =========================================================================
    # Summarization
    # =========================================================================
    
    def summarize_stage(self, stage: ExecutionStage) -> StageSummary:
        """
        Create a summary of an execution stage.
        
        Args:
            stage: ExecutionStage to summarize
            
        Returns:
            StageSummary with essential information
        """
        # Extract key decisions
        key_decisions = self._extract_key_decisions(stage)
        
        summary = StageSummary(
            stage_id=stage.stage_id,
            stage_type=stage.stage_type,
            status=stage.status,
            start_time=stage.start_time,
            end_time=stage.end_time,
            files_count=len(stage.files_processed),
            patches_count=len(stage.patches_applied),
            gates_passed_count=len([g for g in stage.gates_passed if g.passed]),
            errors_count=len(stage.errors_encountered),
            tokens_used=stage.tokens_used,
            key_decisions=key_decisions,
            rollback_point=stage.rollback_point,
        )
        
        summary.compute_hash()
        
        self._stats["stages_summarized"] += 1
        
        return summary
    
    def _extract_key_decisions(self, stage: ExecutionStage) -> List[str]:
        """Extract key decisions from a stage."""
        decisions = []
        
        # Extract from metrics
        if "decisions" in stage.metrics:
            decisions.extend(stage.metrics["decisions"][:5])  # Limit to 5
        
        # Infer from patches
        if stage.patches_applied:
            decisions.append(f"Applied {len(stage.patches_applied)} patches")
        
        # Note significant gates
        critical_gates = ["GATE-04", "GATE-05"]
        for gate in stage.gates_passed:
            if any(cg in gate.gate_name for cg in critical_gates):
                decisions.append(f"Passed {gate.gate_name}")
        
        # Note errors if any
        if stage.errors_encountered:
            decisions.append(f"Encountered {len(stage.errors_encountered)} errors")
        
        return decisions[:10]  # Limit total decisions
    
    # =========================================================================
    # Pruning
    # =========================================================================
    
    def prune_completed_stages(
        self,
        stages: List[ExecutionStage]
    ) -> List[Union[ExecutionStage, StageSummary]]:
        """
        Prune completed stages, keeping only the most recent.
        
        Args:
            stages: List of execution stages
            
        Returns:
            List with pruned stages (mix of full stages and summaries)
        """
        if len(stages) <= self._max_stages:
            return stages
        
        # Separate completed and active stages
        completed = [s for s in stages if s.can_prune]
        active = [s for s in stages if not s.can_prune]
        
        # Keep the most recent completed stages as full stages
        recent_completed = completed[-self._max_stages:] if len(completed) > self._max_stages else completed
        old_completed = completed[:-self._max_stages] if len(completed) > self._max_stages else []
        
        # Summarize old completed stages
        summaries = [self.summarize_stage(s) for s in old_completed]
        
        self._stats["stages_pruned"] += len(summaries)
        
        self._logger.info(
            f"Pruned {len(summaries)} stages, retained {len(recent_completed)} full stages"
        )
        
        # Return combined list
        result = list(summaries) + recent_completed + active
        
        return result
    
    def get_retention_priority(self, stage: ExecutionStage) -> float:
        """
        Calculate retention priority for a stage.
        
        Higher priority stages are kept longer.
        
        Args:
            stage: ExecutionStage to evaluate
            
        Returns:
            Priority score (0.0 to 1.0)
        """
        priority = 0.5  # Base priority
        
        # Active stages have highest priority
        if not stage.can_prune:
            return 1.0
        
        # Stages with rollback points
        if stage.rollback_point and self._preserve_rollback:
            priority += 0.2
        
        # Stages with errors (for debugging)
        if stage.errors_encountered:
            priority += 0.1
        
        # Recent stages
        if stage.end_time:
            try:
                end_dt = datetime.fromisoformat(stage.end_time)
                age_hours = (now_utc() - end_dt).total_seconds() / 3600
                if age_hours < 1:
                    priority += 0.2
                elif age_hours < 6:
                    priority += 0.1
            except (ValueError, TypeError):
                pass
        
        # Large token usage stages
        if stage.tokens_used > 10000:
            priority += 0.1
        
        return min(1.0, priority)
    
    # =========================================================================
    # Compression
    # =========================================================================
    
    def compress_summary(self, summary: StageSummary) -> CompressedSummary:
        """
        Compress a stage summary.
        
        Args:
            summary: StageSummary to compress
            
        Returns:
            CompressedSummary
        """
        import gzip
        
        # Serialize to JSON
        data = json.dumps(summary.to_dict()).encode()
        original_size = len(data)
        
        # Compress
        compressed = gzip.compress(data)
        compressed_size = len(compressed)
        
        ratio = compressed_size / original_size if original_size > 0 else 1.0
        
        self._stats["bytes_saved"] += (original_size - compressed_size)
        
        return CompressedSummary(
            compressed_data=compressed,
            original_size=original_size,
            compressed_size=compressed_size,
            compression_ratio=ratio,
            summary_hash=summary.summary_hash,
        )
    
    def reconstruct_summary(self, compressed: CompressedSummary) -> StageSummary:
        """
        Reconstruct a summary from compressed form.
        
        Args:
            compressed: CompressedSummary to decompress
            
        Returns:
            StageSummary
        """
        import gzip
        
        # Decompress
        data = gzip.decompress(compressed.compressed_data)
        summary_dict = json.loads(data)
        
        return StageSummary(
            stage_id=summary_dict["stage_id"],
            stage_type=StageType(summary_dict["stage_type"]),
            status=StageStatus(summary_dict["status"]),
            start_time=summary_dict["start_time"],
            end_time=summary_dict.get("end_time"),
            files_count=summary_dict["files_count"],
            patches_count=summary_dict["patches_count"],
            gates_passed_count=summary_dict["gates_passed_count"],
            errors_count=summary_dict["errors_count"],
            tokens_used=summary_dict["tokens_used"],
            key_decisions=summary_dict.get("key_decisions", []),
            rollback_point=summary_dict.get("rollback_point"),
            summary_hash=summary_dict.get("summary_hash", ""),
        )
    
    # =========================================================================
    # Statistics
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get summarization statistics."""
        return {
            **self._stats,
            "max_stages_retained": self._max_stages,
            "compression_target": self._compression_ratio,
        }


# =============================================================================
# Module-level convenience
# =============================================================================

_default_summarizer: Optional[RecursiveSummarizer] = None


def get_summarizer(**kwargs) -> RecursiveSummarizer:
    """Get or create default RecursiveSummarizer instance."""
    global _default_summarizer
    
    if _default_summarizer is None:
        _default_summarizer = RecursiveSummarizer(**kwargs)
    
    return _default_summarizer
