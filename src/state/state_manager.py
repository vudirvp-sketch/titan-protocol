"""
TITAN FUSE Protocol - State Manager

Manages session state, checkpoints, and context compaction.
Provides binary serialization for efficient session persistence.
"""

import json
import pickle
import hashlib
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from enum import Enum


class SessionStatus(Enum):
    INITIALIZED = "INITIALIZED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPACTING = "COMPACTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class CheckpointStatus(Enum):
    VALID = "VALID"
    PARTIAL = "PARTIAL"
    INVALID = "INVALID"
    SOURCE_CHANGED = "SOURCE_CHANGED"


@dataclass
class ChunkState:
    """State for a single chunk during processing."""
    chunk_id: str
    status: str = "PENDING"  # PENDING | IN_PROGRESS | COMPLETE | FAILED
    line_start: int = 0
    line_end: int = 0
    changes: List[Dict] = field(default_factory=list)
    checksum: Optional[str] = None
    offset: int = 0  # Line offset after modifications


@dataclass
class GateState:
    """State for a verification gate."""
    gate_id: str
    status: str = "PENDING"  # PENDING | PASS | FAIL | WARN | BLOCK
    timestamp: Optional[str] = None
    details: Dict = field(default_factory=dict)


@dataclass
class SessionState:
    """Complete session state."""
    id: str
    created_at: str
    updated_at: str
    status: str
    protocol_version: str
    source_file: Optional[str] = None
    source_checksum: Optional[str] = None
    max_tokens: int = 100000
    tokens_used: int = 0

    # Processing state
    current_phase: int = -1
    current_gate: int = 0
    chunk_cursor: Optional[str] = None
    chunks: Dict[str, ChunkState] = field(default_factory=dict)

    # Gates
    gates: Dict[str, GateState] = field(default_factory=dict)

    # Issues and gaps
    open_issues: List[str] = field(default_factory=list)
    known_gaps: List[str] = field(default_factory=list)

    # Batches
    completed_batches: List[str] = field(default_factory=list)

    # State snapshot
    state_snapshot: Dict = field(default_factory=dict)

    # Provider config
    provider: Optional[str] = None
    provider_configured: bool = False


class StateManager:
    """
    Manages TITAN session state with support for:
    - Session creation and initialization
    - Checkpoint save/restore (JSON and binary)
    - Context compaction
    - Chunk-level state tracking
    """

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.sessions_dir = repo_root / "sessions"
        self.checkpoints_dir = repo_root / "checkpoints"
        self.current_session: Optional[SessionState] = None

        # Ensure directories exist
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

        # Load current session if exists
        self._load_current_session()

    def _load_current_session(self) -> None:
        """Load the most recent active session."""
        session_file = self.sessions_dir / "current.json"
        if session_file.exists():
            try:
                with open(session_file) as f:
                    data = json.load(f)
                self.current_session = self._dict_to_session(data)
            except Exception:
                self.current_session = None

    def _session_to_dict(self, session: SessionState) -> Dict:
        """Convert SessionState to dictionary for serialization."""
        data = asdict(session)
        # Convert nested dataclasses
        data["chunks"] = {k: asdict(v) for k, v in session.chunks.items()}
        data["gates"] = {k: asdict(v) for k, v in session.gates.items()}
        return data

    def _dict_to_session(self, data: Dict) -> SessionState:
        """Convert dictionary to SessionState."""
        # Convert chunks
        chunks = {}
        for k, v in data.get("chunks", {}).items():
            chunks[k] = ChunkState(**v)

        # Convert gates
        gates = {}
        for k, v in data.get("gates", {}).items():
            gates[k] = GateState(**v)

        # Create session
        data["chunks"] = chunks
        data["gates"] = gates

        return SessionState(**data)

    def create_session(self,
                       session_id: Optional[str] = None,
                       max_tokens: int = 100000,
                       input_files: Optional[List[str]] = None) -> Dict:
        """
        Create a new TITAN session.

        Args:
            session_id: Optional session identifier
            max_tokens: Maximum tokens for the session
            input_files: List of input file paths

        Returns:
            Session dictionary
        """
        now = datetime.utcnow().isoformat() + "Z"

        session = SessionState(
            id=session_id or str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
            status=SessionStatus.INITIALIZED.value,
            protocol_version="3.2.0",
            max_tokens=max_tokens
        )

        # Initialize gates
        for i in range(6):
            gate_id = f"GATE-{i:02d}"
            session.gates[gate_id] = GateState(gate_id=gate_id)

        # Set source file if provided
        if input_files:
            session.source_file = input_files[0] if len(input_files) == 1 else None
            if session.source_file and Path(session.source_file).exists():
                session.source_checksum = self._compute_checksum(session.source_file)

        # Save as current session
        self.current_session = session
        self._save_current_session()

        return self._session_to_dict(session)

    def get_current_session(self) -> Optional[Dict]:
        """Get the current session as dictionary."""
        if self.current_session:
            return self._session_to_dict(self.current_session)
        return None

    def _save_current_session(self) -> None:
        """Save current session to disk."""
        if not self.current_session:
            return

        session_file = self.sessions_dir / "current.json"
        with open(session_file, "w") as f:
            json.dump(self._session_to_dict(self.current_session), f, indent=2)

    def update_session(self, updates: Dict) -> None:
        """Update session state with new values."""
        if not self.current_session:
            return

        for key, value in updates.items():
            if hasattr(self.current_session, key):
                setattr(self.current_session, key, value)

        self.current_session.updated_at = datetime.utcnow().isoformat() + "Z"
        self._save_current_session()

    def advance_gate(self, gate_id: str, status: str, details: Dict = None) -> None:
        """Advance a gate to a new status."""
        if not self.current_session:
            return

        if gate_id in self.current_session.gates:
            gate = self.current_session.gates[gate_id]
            gate.status = status
            gate.timestamp = datetime.utcnow().isoformat() + "Z"
            gate.details = details or {}

            # Update current gate pointer
            if status in ("PASS", "WARN"):
                gate_num = int(gate_id.split("-")[1])
                self.current_session.current_gate = max(
                    self.current_session.current_gate,
                    gate_num + 1
                )

            self._save_current_session()

    def update_chunk(self, chunk_id: str, **kwargs) -> None:
        """Update chunk state."""
        if not self.current_session:
            return

        if chunk_id not in self.current_session.chunks:
            self.current_session.chunks[chunk_id] = ChunkState(chunk_id=chunk_id)

        chunk = self.current_session.chunks[chunk_id]
        for key, value in kwargs.items():
            if hasattr(chunk, key):
                setattr(chunk, key, value)

        self._save_current_session()

    def add_completed_batch(self, batch_id: str) -> None:
        """Record a completed batch."""
        if not self.current_session:
            return

        if batch_id not in self.current_session.completed_batches:
            self.current_session.completed_batches.append(batch_id)
            self._save_current_session()

    def add_issue(self, issue_id: str) -> None:
        """Add an open issue."""
        if not self.current_session:
            return

        if issue_id not in self.current_session.open_issues:
            self.current_session.open_issues.append(issue_id)
            self._save_current_session()

    def close_issue(self, issue_id: str) -> None:
        """Close an issue."""
        if not self.current_session:
            return

        if issue_id in self.current_session.open_issues:
            self.current_session.open_issues.remove(issue_id)
            self._save_current_session()

    def add_gap(self, gap: str) -> None:
        """Record a known gap."""
        if not self.current_session:
            return

        if gap not in self.current_session.known_gaps:
            self.current_session.known_gaps.append(gap)
            self._save_current_session()

    def increment_token_usage(self, tokens: int) -> bool:
        """
        Increment token usage counter.

        Returns:
            True if within budget, False if exceeded
        """
        if not self.current_session:
            return True

        self.current_session.tokens_used += tokens
        self._save_current_session()

        return self.current_session.tokens_used < self.current_session.max_tokens

    # =========================================================================
    # CHECKPOINT MANAGEMENT
    # =========================================================================

    def save_checkpoint(self,
                        checkpoint_path: Optional[str] = None,
                        binary: bool = False) -> Dict:
        """
        Save session checkpoint.

        Args:
            checkpoint_path: Optional custom path
            binary: Use binary serialization (pickle) instead of JSON

        Returns:
            Checkpoint info dictionary
        """
        if not self.current_session:
            return {"success": False, "error": "No active session"}

        checkpoint_file = Path(checkpoint_path) if checkpoint_path else \
                          self.checkpoints_dir / "checkpoint.json"

        if binary:
            checkpoint_file = checkpoint_file.with_suffix(".bin")

        try:
            if binary:
                with open(checkpoint_file, "wb") as f:
                    pickle.dump(self.current_session, f)
            else:
                with open(checkpoint_file, "w") as f:
                    json.dump(self._session_to_dict(self.current_session), f, indent=2)

            return {
                "success": True,
                "checkpoint_path": str(checkpoint_file),
                "format": "binary" if binary else "json",
                "session_id": self.current_session.id
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def resume_from_checkpoint(self, checkpoint_path: str) -> Dict:
        """
        Resume session from checkpoint.

        Args:
            checkpoint_path: Path to checkpoint file

        Returns:
            Resume result dictionary
        """
        checkpoint_file = Path(checkpoint_path)

        if not checkpoint_file.exists():
            return {"success": False, "error": "Checkpoint file not found"}

        try:
            # Detect format and load
            if checkpoint_file.suffix == ".bin":
                with open(checkpoint_file, "rb") as f:
                    session = pickle.load(f)
            else:
                with open(checkpoint_file) as f:
                    data = json.load(f)
                session = self._dict_to_session(data)

            # Validate source checksum if present
            if session.source_file and session.source_checksum:
                current_checksum = self._compute_checksum(session.source_file)
                if current_checksum != session.source_checksum:
                    # Source file changed - attempt partial recovery
                    return {
                        "success": False,
                        "status": "SOURCE_CHANGED",
                        "error": "Source file has been modified since checkpoint",
                        "session_id": session.id,
                        "recoverable_chunks": self._find_recoverable_chunks(session)
                    }

            # Set as current session
            self.current_session = session
            self.current_session.status = SessionStatus.RUNNING.value
            self._save_current_session()

            return {
                "success": True,
                "status": "RESUMED",
                "session_id": session.id,
                "gates_passed": [g for g, s in session.gates.items() if s.status == "PASS"],
                "completed_batches": session.completed_batches,
                "chunk_cursor": session.chunk_cursor,
                "open_issues": session.open_issues
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _find_recoverable_chunks(self, session: SessionState) -> List[str]:
        """Find chunks that can be recovered after source change."""
        recoverable = []

        if not session.source_file:
            return recoverable

        try:
            # Read current source
            with open(session.source_file) as f:
                current_lines = f.readlines()

            # Check each chunk's checksum
            for chunk_id, chunk_state in session.chunks.items():
                if chunk_state.status == "COMPLETE" and chunk_state.checksum:
                    # Verify chunk content hasn't changed
                    chunk_lines = current_lines[chunk_state.line_start:chunk_state.line_end]
                    chunk_content = "".join(chunk_lines)
                    current_chunk_checksum = hashlib.sha256(
                        chunk_content.encode()
                    ).hexdigest()[:16]

                    if current_chunk_checksum == chunk_state.checksum:
                        recoverable.append(chunk_id)
        except Exception:
            pass

        return recoverable

    def _compute_checksum(self, file_path: str) -> str:
        """Compute SHA-256 checksum of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for block in iter(lambda: f.read(65536), b""):
                sha256.update(block)
        return sha256.hexdigest()

    # =========================================================================
    # CONTEXT COMPACTION
    # =========================================================================

    def compact_context(self, strategy: str = "auto") -> Dict:
        """
        Compact session context to reduce memory/token usage.

        Strategies:
            - auto: Compact based on token threshold
            - aggressive: Compact all completed chunks
            - minimal: Only compact old completed batches

        Args:
            strategy: Compaction strategy

        Returns:
            Compaction result dictionary
        """
        if not self.current_session:
            return {"success": False, "error": "No active session"}

        if strategy == "auto":
            # Compact when token usage > 70%
            if self.current_session.tokens_used < self.current_session.max_tokens * 0.7:
                return {"success": True, "action": "skipped", "reason": "Below threshold"}

        compacted = []
        old_status = self.current_session.status
        self.current_session.status = SessionStatus.COMPACTING.value

        try:
            # Summarize completed chunks
            for chunk_id, chunk_state in list(self.current_session.chunks.items()):
                if chunk_state.status == "COMPLETE":
                    # Replace detailed changes with summary
                    if len(chunk_state.changes) > 5:
                        summary = {
                            "summary": True,
                            "total_changes": len(chunk_state.changes),
                            "first": chunk_state.changes[0] if chunk_state.changes else None,
                            "last": chunk_state.changes[-1] if chunk_state.changes else None
                        }
                        chunk_state.changes = [summary]
                        compacted.append(chunk_id)

            # Clear old state snapshots (keep last 5)
            if "history" in self.current_session.state_snapshot:
                history = self.current_session.state_snapshot["history"]
                if len(history) > 5:
                    self.current_session.state_snapshot["history"] = history[-5:]

            self.current_session.status = old_status
            self._save_current_session()

            return {
                "success": True,
                "strategy": strategy,
                "compacted_chunks": compacted,
                "tokens_saved_estimate": len(compacted) * 500  # Rough estimate
            }

        except Exception as e:
            self.current_session.status = old_status
            return {"success": False, "error": str(e)}

    # =========================================================================
    # PROVIDER CONFIGURATION
    # =========================================================================

    def configure_provider(self, provider: str, api_key: Optional[str]) -> Dict:
        """
        Configure LLM provider.

        Args:
            provider: Provider name
            api_key: API key (stored securely)

        Returns:
            Configuration result
        """
        if not self.current_session:
            # Create session if none exists
            self.create_session()

        # In production, this would use secure key storage
        # For now, just mark as configured
        self.current_session.provider = provider
        self.current_session.provider_configured = bool(api_key)
        self._save_current_session()

        return {
            "success": True,
            "provider": provider,
            "message": f"Provider {provider} configured successfully"
        }

    # =========================================================================
    # ARTIFACT EXPORT
    # =========================================================================

    def export_artifacts(self,
                        session: Dict,
                        output_path: Path,
                        format: str = "json") -> Dict:
        """
        Export session artifacts.

        Args:
            session: Session dictionary
            output_path: Output directory
            format: Export format (json, markdown, html)

        Returns:
            Export result with list of created files
        """
        artifacts = []

        try:
            # Always export CHANGE_LOG
            if format in ("json", "all"):
                change_log = output_path / "CHANGE_LOG.json"
                with open(change_log, "w") as f:
                    json.dump({
                        "session_id": session.get("id"),
                        "changes": [
                            c for chunk in session.get("chunks", {}).values()
                            for c in chunk.get("changes", [])
                        ]
                    }, f, indent=2)
                artifacts.append(str(change_log))

            if format in ("markdown", "all"):
                change_log_md = output_path / "CHANGE_LOG.md"
                with open(change_log_md, "w") as f:
                    f.write(f"# CHANGE_LOG\n\n")
                    f.write(f"Session: {session.get('id', 'unknown')}\n\n")

                    for chunk_id, chunk in session.get("chunks", {}).items():
                        for change in chunk.get("changes", []):
                            f.write(f"- [{chunk_id}] {change}\n")

                artifacts.append(str(change_log_md))

            # Export metrics
            metrics_file = output_path / "metrics.json"
            with open(metrics_file, "w") as f:
                json.dump({
                    "session": {
                        "id": session.get("id"),
                        "duration": None,  # Would calculate from timestamps
                        "status": session.get("status")
                    },
                    "processing": {
                        "chunks_total": len(session.get("chunks", {})),
                        "chunks_complete": sum(
                            1 for c in session.get("chunks", {}).values()
                            if c.get("status") == "COMPLETE"
                        ),
                        "issues_found": len(session.get("open_issues", [])),
                        "gaps": len(session.get("known_gaps", []))
                    },
                    "gates": {
                        g: s.get("status")
                        for g, s in session.get("gates", {}).items()
                    }
                }, f, indent=2)
            artifacts.append(str(metrics_file))

            return {"success": True, "artifacts": artifacts}

        except Exception as e:
            return {"success": False, "error": str(e), "artifacts": artifacts}
