"""
State Manager for TITAN FUSE Protocol.

Manages session state, reasoning steps, budget allocation,
and cursor tracking for deterministic execution.

Author: TITAN FUSE Team
Version: 3.2.3
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
import hashlib
import json
import uuid

from .assessment import AssessmentScore


class EvidenceType(Enum):
    """Type of evidence in a reasoning step."""
    FACT = "FACT"          # Verified information
    OPINION = "OPINION"    # Subjective assessment
    CODE = "CODE"          # Code snippet
    WARNING = "WARNING"    # Caution note
    STEP = "STEP"          # Procedure step
    EXAMPLE = "EXAMPLE"    # Illustrative example
    GAP = "GAP"            # Missing information


@dataclass
class ReasoningStep:
    """
    A single step in the reasoning process.

    Tracks the content, evidence type, confidence, and source reference
    for each reasoning step, enabling transparent and auditable reasoning.
    """
    content: str
    evidence_type: EvidenceType = EvidenceType.FACT
    confidence: float = 1.0
    source_ref: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "content": self.content,
            "evidence_type": self.evidence_type.value,
            "confidence": self.confidence,
            "source_ref": self.source_ref
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'ReasoningStep':
        """Create from dictionary."""
        return cls(
            content=data["content"],
            evidence_type=EvidenceType(data.get("evidence_type", "FACT")),
            confidence=data.get("confidence", 1.0),
            source_ref=data.get("source_ref")
        )

    def __str__(self) -> str:
        """Human-readable representation."""
        evidence_marker = {
            EvidenceType.FACT: "✓",
            EvidenceType.OPINION: "?",
            EvidenceType.CODE: "⟨⟩",
            EvidenceType.WARNING: "⚠",
            EvidenceType.STEP: "→",
            EvidenceType.EXAMPLE: "※",
            EvidenceType.GAP: "∅"
        }.get(self.evidence_type, "•")
        return f"{evidence_marker} {self.content[:50]}..."


@dataclass
class BudgetAllocation:
    """Token budget allocation per severity level."""
    sev_1_ratio: float = 0.30  # 30% reserved for SEV-1
    sev_2_ratio: float = 0.25  # 25% reserved for SEV-2
    sev_3_4_ratio: float = 0.45  # 45% pool for SEV-3/4

    def to_dict(self) -> Dict:
        return {
            "sev_1_ratio": self.sev_1_ratio,
            "sev_2_ratio": self.sev_2_ratio,
            "sev_3_4_ratio": self.sev_3_4_ratio
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'BudgetAllocation':
        return cls(
            sev_1_ratio=data.get("sev_1_ratio", 0.30),
            sev_2_ratio=data.get("sev_2_ratio", 0.25),
            sev_3_4_ratio=data.get("sev_3_4_ratio", 0.45)
        )


class BudgetManager:
    """Manage per-severity token budget allocation."""

    def __init__(self, max_tokens: int, allocation: BudgetAllocation = None):
        self.max_tokens = max_tokens
        self.allocation = allocation or BudgetAllocation()
        self._sev_tokens_used: Dict[str, int] = {
            "SEV-1": 0,
            "SEV-2": 0,
            "SEV-3": 0,
            "SEV-4": 0
        }
        self._total_used = 0

    def get_reserved_budget(self, severity: str) -> int:
        """Get total reserved budget for severity level."""
        if severity == "SEV-1":
            return int(self.max_tokens * self.allocation.sev_1_ratio)
        elif severity == "SEV-2":
            return int(self.max_tokens * self.allocation.sev_2_ratio)
        else:  # SEV-3 or SEV-4
            return int(self.max_tokens * self.allocation.sev_3_4_ratio)

    def get_available_budget(self, severity: str) -> int:
        """Get remaining budget for severity level."""
        reserved = self.get_reserved_budget(severity)
        used = self._sev_tokens_used.get(severity, 0)
        return max(0, reserved - used)

    def allocate_tokens(self, severity: str, tokens: int) -> Dict:
        """Allocate tokens for a severity level operation."""
        available = self.get_available_budget(severity)

        if tokens > available:
            return {
                "success": False,
                "allocated": 0,
                "requested": tokens,
                "available": available,
                "severity": severity,
                "error": f"Insufficient budget for {severity}: {tokens} > {available}"
            }

        self._sev_tokens_used[severity] += tokens
        self._total_used += tokens

        return {
            "success": True,
            "allocated": tokens,
            "severity": severity,
            "remaining": self.get_available_budget(severity)
        }

    def get_status(self) -> Dict:
        """Get budget status for all severity levels."""
        return {
            "max_tokens": self.max_tokens,
            "total_used": self._total_used,
            "total_remaining": self.max_tokens - self._total_used,
            "allocation": self.allocation.to_dict(),
            "per_severity": {
                sev: {
                    "reserved": self.get_reserved_budget(sev),
                    "used": used,
                    "available": self.get_available_budget(sev)
                }
                for sev, used in self._sev_tokens_used.items()
            }
        }

    def can_afford(self, severity: str, tokens: int) -> bool:
        """Check if operation is affordable within budget."""
        return tokens <= self.get_available_budget(severity)


class CursorTracker:
    """Track cursor position with hash verification."""

    def __init__(self):
        self.cursor_hash: Optional[str] = None
        self.last_patch_hash: Optional[str] = None
        self._patch_history: List[str] = []
        self._current_line: int = 0
        self._current_chunk: Optional[str] = None
        self._offset_delta: int = 0

    def update_cursor_hash(self, patch_content: str) -> str:
        """Update cursor hash after patch application."""
        combined = f"{self.last_patch_hash or 'init'}:{patch_content}"
        self.cursor_hash = hashlib.sha256(combined.encode()).hexdigest()[:32]
        self.last_patch_hash = self.cursor_hash
        self._patch_history.append(self.cursor_hash)
        return self.cursor_hash

    def verify_cursor_hash(self, expected_hash: str) -> Dict:
        """Verify cursor hash on resume."""
        if self.cursor_hash != expected_hash:
            return {
                "valid": False,
                "gap": "[gap: cursor_drift_detected]",
                "expected": expected_hash,
                "actual": self.cursor_hash,
                "patch_count": len(self._patch_history)
            }
        return {"valid": True}

    def update_position(self, line: int = None, chunk: str = None, offset: int = None) -> None:
        """Update cursor position."""
        if line is not None:
            self._current_line = line
        if chunk is not None:
            self._current_chunk = chunk
        if offset is not None:
            self._offset_delta = offset

    def get_state(self) -> Dict:
        """Get cursor state for checkpoint."""
        return {
            "cursor_hash": self.cursor_hash,
            "last_patch_hash": self.last_patch_hash,
            "patch_count": len(self._patch_history),
            "current_line": self._current_line,
            "current_chunk": self._current_chunk,
            "offset_delta": self._offset_delta
        }

    def restore_state(self, state: Dict) -> None:
        """Restore cursor state from checkpoint."""
        self.cursor_hash = state.get("cursor_hash")
        self.last_patch_hash = state.get("last_patch_hash")
        self._current_line = state.get("current_line", 0)
        self._current_chunk = state.get("current_chunk")
        self._offset_delta = state.get("offset_delta", 0)


@dataclass
class SessionState:
    """
    Complete session state for TITAN FUSE Protocol.

    Tracks all aspects of a processing session including:
    - Session identification and timing
    - Processing state (chunks, issues, gates)
    - Budget and token management
    - Assessment scores
    - Cursor tracking
    """
    # Session identification
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    protocol_version: str = "3.2.3"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    # Processing state
    state: str = "INIT"
    source_file: Optional[str] = None
    source_checksum: Optional[str] = None
    current_phase: int = 0
    chunk_cursor: Optional[str] = None

    # Chunk management
    chunks: Dict[str, Dict] = field(default_factory=dict)
    chunks_total: int = 0
    chunks_completed: int = 0

    # Issue tracking
    issues: List[Dict] = field(default_factory=list)
    issues_by_severity: Dict[str, List[str]] = field(default_factory=lambda: {
        "SEV-1": [], "SEV-2": [], "SEV-3": [], "SEV-4": []
    })

    # Gate tracking
    gates: Dict[str, Dict] = field(default_factory=lambda: {
        "GATE-00": {"status": "PENDING"},
        "GATE-01": {"status": "PENDING"},
        "GATE-02": {"status": "PENDING"},
        "GATE-03": {"status": "PENDING"},
        "GATE-04": {"status": "PENDING"},
        "GATE-05": {"status": "PENDING"}
    })

    # Budget management
    max_tokens: int = 100000
    tokens_used: int = 0
    budget_manager: Optional[BudgetManager] = None

    # Assessment
    assessment_score: Optional[AssessmentScore] = None
    volatility: str = "V2"
    confidence: float = 0.8

    # Cursor tracking
    cursor_tracker: CursorTracker = field(default_factory=CursorTracker)

    # Reasoning steps
    reasoning_steps: List[ReasoningStep] = field(default_factory=list)

    # Gaps
    gaps: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Initialize budget manager."""
        if self.budget_manager is None:
            self.budget_manager = BudgetManager(self.max_tokens)

    def update_assessment(self) -> AssessmentScore:
        """Update assessment score based on current state."""
        self.assessment_score = AssessmentScore.calculate(self.volatility, self.confidence)
        return self.assessment_score

    def add_reasoning_step(self, content: str, evidence_type: EvidenceType = EvidenceType.FACT,
                          confidence: float = 1.0, source_ref: str = None) -> ReasoningStep:
        """Add a reasoning step."""
        step = ReasoningStep(
            content=content,
            evidence_type=evidence_type,
            confidence=confidence,
            source_ref=source_ref
        )
        self.reasoning_steps.append(step)
        return step

    def add_gap(self, gap: str) -> None:
        """Add a gap marker."""
        self.gaps.append(gap)
        self.add_reasoning_step(
            content=gap,
            evidence_type=EvidenceType.GAP,
            confidence=0.0
        )

    def pass_gate(self, gate_id: str, details: Dict = None) -> None:
        """Mark a gate as passed."""
        if gate_id in self.gates:
            self.gates[gate_id] = {
                "status": "PASS",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "details": details or {}
            }
        self._update_timestamp()

    def fail_gate(self, gate_id: str, reason: str, details: Dict = None) -> None:
        """Mark a gate as failed."""
        if gate_id in self.gates:
            self.gates[gate_id] = {
                "status": "FAIL",
                "reason": reason,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "details": details or {}
            }
        self._update_timestamp()

    def warn_gate(self, gate_id: str, reason: str, details: Dict = None) -> None:
        """Mark a gate with warning."""
        if gate_id in self.gates:
            self.gates[gate_id] = {
                "status": "WARN",
                "reason": reason,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "details": details or {}
            }
        self._update_timestamp()

    def allocate_tokens(self, severity: str, tokens: int) -> Dict:
        """Allocate tokens for operation."""
        result = self.budget_manager.allocate_tokens(severity, tokens)
        if result["success"]:
            self.tokens_used += tokens
            self._update_timestamp()
        return result

    def get_state_snapshot(self) -> Dict:
        """Get snapshot for checkpoint."""
        return {
            "session_id": self.session_id,
            "protocol_version": self.protocol_version,
            "state": self.state,
            "source_file": self.source_file,
            "source_checksum": self.source_checksum,
            "current_phase": self.current_phase,
            "chunk_cursor": self.chunk_cursor,
            "chunks_total": self.chunks_total,
            "chunks_completed": self.chunks_completed,
            "gates": self.gates,
            "tokens_used": self.tokens_used,
            "budget_status": self.budget_manager.get_status() if self.budget_manager else None,
            "assessment_score": self.assessment_score.to_dict() if self.assessment_score else None,
            "cursor_state": self.cursor_tracker.get_state(),
            "gaps": self.gaps,
            "updated_at": self.updated_at
        }

    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.get_state_snapshot(), indent=2)

    def _update_timestamp(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.utcnow().isoformat() + "Z"
