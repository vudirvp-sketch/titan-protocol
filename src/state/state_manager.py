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
    
    # FIX 05: Policy retry state for checkpoint persistence
    policy_retry_state: Dict[str, Dict] = field(default_factory=dict)
    
    # FIX 04: Policy manifest hash for validation on resume
    policy_manifest_hash: Optional[str] = None
    
    # FIX 06: Budget state for policy context
    budget_state: str = "NORMAL"  # NORMAL | BUDGET_WARNING | BUDGET_EXCEEDED
    
    # NEW in v3.2: Recursion control
    recursion_depth: int = 0
    max_recursion_depth: int = 1
    recursion_depth_peak: int = 0
    
    # NEW in v3.2: Token telemetry for p50/p95
    token_history: List[int] = field(default_factory=list)
    latency_history: List[int] = field(default_factory=list)  # in milliseconds
    
    # NEW in v3.2: Model routing tracking
    root_model_calls: int = 0
    leaf_model_calls: int = 0
    root_model_tokens: int = 0
    leaf_model_tokens: int = 0
    
    # NEW in v3.2: Confidence tracking
    confidence_scores: List[str] = field(default_factory=list)
    all_high_confidence: bool = True
    
    # NEW in v3.2.1: Mode selection
    mode: str = "direct"  # direct | auto | manual | preset | hybrid
    preset_name: Optional[str] = None
    mode_config_source: str = "default"
    
    # NEW in v3.2.1: Intent classification (for AUTO mode)
    intent_classification: Optional[str] = None  # analysis | generation | debugging | research | multimodal
    intent_confidence: float = 0.0
    intent_hash: Optional[str] = None
    secondary_intents: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    domain_volatility: str = "medium"  # low | medium | high
    
    # NEW in v3.2.1: Extended gates (GATE-INTENT, GATE-PLAN, GATE-SKILL, GATE-SECURITY, GATE-EXEC)
    # Gates are now initialized with GATE-INTENT through GATE-EXEC
    gate_intents_passed: List[str] = field(default_factory=list)
    
    # NEW in v3.2.1: Anomaly detection baseline
    baseline_p50_tokens: float = 0.0
    baseline_p95_tokens: float = 0.0
    baseline_sessions_count: int = 0
    anomaly_detected: bool = False


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
            protocol_version="3.2.2",
            max_tokens=max_tokens
        )

        # Initialize standard gates (GATE-00 through GATE-05)
        for i in range(6):
            gate_id = f"GATE-{i:02d}"
            session.gates[gate_id] = GateState(gate_id=gate_id)
        
        # NEW in v3.2.1: Initialize extended gates
        extended_gates = ["GATE-INTENT", "GATE-PLAN", "GATE-SKILL", "GATE-SECURITY", "GATE-EXEC"]
        for gate_id in extended_gates:
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
    
    # =========================================================================
    # FIX 05: Policy retry state management
    # =========================================================================
    
    def update_retry_state(self, context_key: str, retry_count: int, 
                          policy_name: str = "") -> None:
        """
        FIX 05: Update retry state for a context key.
        
        This MUST be called after every retry attempt to ensure
        the retry count is persisted to checkpoint.
        """
        if not self.current_session:
            return
        
        self.current_session.policy_retry_state[context_key] = {
            "retry_count": retry_count,
            "last_policy_triggered": policy_name,
            "last_retry_timestamp": datetime.utcnow().isoformat() + "Z"
        }
        self._save_current_session()
    
    def get_retry_count(self, context_key: str) -> int:
        """FIX 05: Get retry count for a context key."""
        if not self.current_session:
            return 0
        
        state = self.current_session.policy_retry_state.get(context_key, {})
        return state.get("retry_count", 0)
    
    def reset_retry_state(self, context_key: str) -> None:
        """FIX 05: Reset retry state for a context key."""
        if not self.current_session:
            return
        
        if context_key in self.current_session.policy_retry_state:
            del self.current_session.policy_retry_state[context_key]
            self._save_current_session()
    
    # =========================================================================
    # FIX 04: Policy manifest hash validation
    # =========================================================================
    
    def set_policy_manifest_hash(self, manifest_hash: str) -> None:
        """FIX 04: Store policy manifest hash in session."""
        if not self.current_session:
            return
        
        self.current_session.policy_manifest_hash = manifest_hash
        self._save_current_session()
    
    def validate_policy_manifest(self, current_hash: str) -> Dict:
        """
        FIX 04: Validate that policy manifest hasn't changed since checkpoint.
        
        Returns dict with validation result.
        """
        if not self.current_session:
            return {"valid": True, "warning": None}
        
        stored_hash = self.current_session.policy_manifest_hash
        if stored_hash and stored_hash != current_hash:
            return {
                "valid": False,
                "warning": "Policy manifest has changed since last checkpoint. "
                           "Some policies may behave differently. "
                           "Acknowledge to continue or restore manifest."
            }
        
        return {"valid": True, "warning": None}
    
    # =========================================================================
    # FIX 06: Budget state for policy context
    # =========================================================================
    
    def get_budget_state(self) -> str:
        """FIX 06: Get current budget state for policy context."""
        if not self.current_session:
            return "NORMAL"
        return self.current_session.budget_state
    
    def get_policy_context(self) -> Dict:
        """
        FIX 06: Build context dict for policy evaluation.
        
        Includes budget state and tokens remaining.
        """
        if not self.current_session:
            return {"budget_state": "NORMAL", "tokens_remaining": 100000}
        
        return {
            "budget_state": self.current_session.budget_state,
            "tokens_remaining": self.current_session.max_tokens - self.current_session.tokens_used,
            "tokens_used": self.current_session.tokens_used,
            "max_tokens": self.current_session.max_tokens
        }

    # =========================================================================
    # NEW in v3.2: RECURSION CONTROL
    # =========================================================================

    def increment_recursion_depth(self) -> bool:
        """
        Increment recursion depth.
        
        Returns:
            True if within limit, False if limit reached
        """
        if not self.current_session:
            return False
        
        if self.current_session.recursion_depth >= self.current_session.max_recursion_depth:
            return False
        
        self.current_session.recursion_depth += 1
        
        # Track peak
        if self.current_session.recursion_depth > self.current_session.recursion_depth_peak:
            self.current_session.recursion_depth_peak = self.current_session.recursion_depth
        
        self._save_current_session()
        return True
    
    def decrement_recursion_depth(self) -> None:
        """Decrement recursion depth."""
        if not self.current_session:
            return
        
        if self.current_session.recursion_depth > 0:
            self.current_session.recursion_depth -= 1
            self._save_current_session()
    
    def check_recursion_limit(self) -> Dict:
        """
        Check if recursion limit is reached.
        
        Returns:
            Dict with status and details
        """
        if not self.current_session:
            return {"allowed": False, "reason": "No active session"}
        
        if self.current_session.recursion_depth >= self.current_session.max_recursion_depth:
            return {
                "allowed": False,
                "reason": "recursion_limit_reached",
                "current_depth": self.current_session.recursion_depth,
                "max_depth": self.current_session.max_recursion_depth,
                "message": "[gap: recursion_limit_reached — flatten or defer]"
            }
        
        return {
            "allowed": True,
            "current_depth": self.current_session.recursion_depth,
            "max_depth": self.current_session.max_recursion_depth
        }

    # =========================================================================
    # NEW in v3.2: TOKEN AND LATENCY TELEMETRY
    # =========================================================================

    def record_query_metrics(self, 
                            tokens: int, 
                            latency_ms: int,
                            model_type: str = "leaf") -> None:
        """
        Record token and latency metrics for a query.
        
        Args:
            tokens: Tokens used in this query
            latency_ms: Latency in milliseconds
            model_type: "root" or "leaf" for model routing
        """
        if not self.current_session:
            return
        
        # Record token history for p50/p95 calculation
        self.current_session.token_history.append(tokens)
        self.current_session.latency_history.append(latency_ms)
        
        # Track model-specific usage
        if model_type == "root":
            self.current_session.root_model_calls += 1
            self.current_session.root_model_tokens += tokens
        else:
            self.current_session.leaf_model_calls += 1
            self.current_session.leaf_model_tokens += tokens
        
        self._save_current_session()
    
    def get_token_percentiles(self) -> Dict:
        """
        Calculate p50 and p95 percentiles for token distribution.
        
        Returns:
            Dict with p50, p95, and other statistics
        """
        if not self.current_session or not self.current_session.token_history:
            return {
                "p50": 0,
                "p95": 0,
                "total_queries": 0,
                "total_tokens": 0,
                "min": 0,
                "max": 0
            }
        
        import statistics
        
        tokens = sorted(self.current_session.token_history)
        n = len(tokens)
        
        return {
            "p50": int(statistics.median(tokens)),
            "p95": int(tokens[int(n * 0.95)] if n >= 20 else tokens[-1]),
            "total_queries": n,
            "total_tokens": sum(tokens),
            "min": tokens[0],
            "max": tokens[-1],
            "mean": int(statistics.mean(tokens))
        }
    
    def get_latency_percentiles(self) -> Dict:
        """
        Calculate p50 and p95 percentiles for latency distribution.
        
        Returns:
            Dict with latency statistics
        """
        if not self.current_session or not self.current_session.latency_history:
            return {
                "p50_ms": 0,
                "p95_ms": 0,
                "total_queries": 0
            }
        
        import statistics
        
        latencies = sorted(self.current_session.latency_history)
        n = len(latencies)
        
        return {
            "p50_ms": int(statistics.median(latencies)),
            "p95_ms": int(latencies[int(n * 0.95)] if n >= 20 else latencies[-1]),
            "total_queries": n,
            "mean_ms": int(statistics.mean(latencies))
        }

    # =========================================================================
    # NEW in v3.2: CONFIDENCE TRACKING
    # =========================================================================

    def record_confidence(self, confidence: str) -> None:
        """
        Record confidence score from a query result.
        
        Args:
            confidence: LOW | MED | HIGH
        """
        if not self.current_session:
            return
        
        self.current_session.confidence_scores.append(confidence)
        
        # Track if all are HIGH
        if confidence != "HIGH":
            self.current_session.all_high_confidence = False
        
        self._save_current_session()
    
    def get_confidence_summary(self) -> Dict:
        """
        Get confidence summary for the session.
        
        Returns:
            Dict with confidence statistics
        """
        if not self.current_session:
            return {"all_high": False, "total": 0}
        
        scores = self.current_session.confidence_scores
        
        return {
            "all_high": self.current_session.all_high_confidence,
            "total": len(scores),
            "high_count": scores.count("HIGH"),
            "med_count": scores.count("MED"),
            "low_count": scores.count("LOW")
        }

    # =========================================================================
    # NEW in v3.2: MODEL ROUTING SUMMARY
    # =========================================================================

    def get_model_routing_summary(self) -> Dict:
        """
        Get model routing summary for the session.
        
        Returns:
            Dict with model usage statistics
        """
        if not self.current_session:
            return {"root_calls": 0, "leaf_calls": 0}
        
        return {
            "root_model_calls": self.current_session.root_model_calls,
            "leaf_model_calls": self.current_session.leaf_model_calls,
            "root_model_tokens": self.current_session.root_model_tokens,
            "leaf_model_tokens": self.current_session.leaf_model_tokens,
            "total_tokens": (self.current_session.root_model_tokens + 
                           self.current_session.leaf_model_tokens)
        }

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
        
        # FIX 06: Update budget state based on usage
        usage_pct = self.current_session.tokens_used / self.current_session.max_tokens
        if usage_pct >= 1.0:
            self.current_session.budget_state = "BUDGET_EXCEEDED"
        elif usage_pct >= 0.9:
            self.current_session.budget_state = "BUDGET_WARNING"
        else:
            self.current_session.budget_state = "NORMAL"
        
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

    def resume_from_checkpoint(self, checkpoint_path: str, allow_unsafe: bool = False) -> Dict:
        """
        Resume session from checkpoint.

        Args:
            checkpoint_path: Path to checkpoint file
            allow_unsafe: Allow loading pickle checkpoints (UNSAFE)

        Returns:
            Resume result dictionary
        """
        checkpoint_file = Path(checkpoint_path)

        if not checkpoint_file.exists():
            return {"success": False, "error": "Checkpoint file not found"}

        try:
            # Detect format and load
            if checkpoint_file.suffix == ".bin" or checkpoint_file.suffix == ".pkl":
                if not allow_unsafe:
                    return {
                        "success": False,
                        "error": "[gap: unsafe_checkpoint] Pickle checkpoints require --unsafe flag. Use JSON checkpoints for safety."
                    }
                with open(checkpoint_file, "rb") as f:
                    session = pickle.load(f)
            elif checkpoint_file.suffix == ".gz":
                import gzip
                with gzip.open(checkpoint_file, 'rt') as f:
                    data = json.load(f)
                session = self._dict_to_session(data)
            elif checkpoint_file.suffix == ".zst":
                try:
                    import zstandard as zstd
                    dctx = zstd.ZstdDecompressor()
                    with open(checkpoint_file, 'rb') as f:
                        decompressed = dctx.decompress(f.read())
                    data = json.loads(decompressed)
                    session = self._dict_to_session(data)
                except ImportError:
                    return {"success": False, "error": "zstandard package required for .zst files"}
            else:
                with open(checkpoint_file) as f:
                    data = json.load(f)
                session = self._dict_to_session(data)

            # NEW v3.2.2: Apply schema migrations if needed
            session_dict = self._session_to_dict(session)
            loaded_version = session_dict.get("protocol_version", "3.2.0")
            if loaded_version != "3.2.2":
                try:
                    from schema.migrations import apply_migrations
                    session_dict = apply_migrations(session_dict)
                    session = self._dict_to_session(session_dict)
                except ImportError:
                    pass  # Migrations not available, continue

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
                "open_issues": session.open_issues,
                # FIX 05: Include policy retry state for core to restore
                "policy_retry_state": session.policy_retry_state,
                # FIX 04: Include manifest hash warning if applicable
                "policy_manifest_hash": session.policy_manifest_hash,
                # FIX 06: Include budget state
                "budget_state": session.budget_state
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

    # =========================================================================
    # NEW in v3.2.1: ANOMALY DETECTION
    # =========================================================================

    def update_baseline(self, p50: float, p95: float) -> None:
        """
        Update anomaly detection baseline with new session metrics.
        
        Baseline is established after first N successful sessions.
        Handles the edge case where first sessions may fail.
        
        Args:
            p50: p50 token count from completed session
            p95: p95 token count from completed session
        """
        if not self.current_session:
            return
        
        # Increment baseline sessions count
        self.current_session.baseline_sessions_count += 1
        
        # Update running average (exponential moving average)
        alpha = 0.3  # Weight for new values
        if self.current_session.baseline_p50_tokens == 0:
            # First baseline value
            self.current_session.baseline_p50_tokens = p50
            self.current_session.baseline_p95_tokens = p95
        else:
            # Update with EMA
            self.current_session.baseline_p50_tokens = (
                alpha * p50 + (1 - alpha) * self.current_session.baseline_p50_tokens
            )
            self.current_session.baseline_p95_tokens = (
                alpha * p95 + (1 - alpha) * self.current_session.baseline_p95_tokens
            )
        
        self._save_current_session()
    
    def check_anomaly(self, current_p95: float, threshold_multiplier: float = 3.0) -> Dict:
        """
        Check if current metrics indicate an anomaly.
        
        FIX for spec bug: Only check after baseline is established.
        If baseline_sessions_count < required_minimum, skip check.
        
        Args:
            current_p95: Current p95 token count
            threshold_multiplier: Multiplier for anomaly threshold
            
        Returns:
            Dict with anomaly detection result
        """
        if not self.current_session:
            return {"anomaly": False, "reason": "No active session"}
        
        # Require at least 3 sessions for baseline (fix for "what if first 10 fail")
        MIN_BASELINE_SESSIONS = 3
        if self.current_session.baseline_sessions_count < MIN_BASELINE_SESSIONS:
            return {
                "anomaly": False,
                "reason": f"Baseline not established ({self.current_session.baseline_sessions_count}/{MIN_BASELINE_SESSIONS} sessions)"
            }
        
        # Check if p95 exceeds threshold
        threshold = self.current_session.baseline_p95_tokens * threshold_multiplier
        
        if current_p95 > threshold:
            self.current_session.anomaly_detected = True
            self._save_current_session()
            
            return {
                "anomaly": True,
                "current_p95": current_p95,
                "threshold": threshold,
                "baseline_p95": self.current_session.baseline_p95_tokens,
                "multiplier": threshold_multiplier,
                "action": "warn"  # or "suspend" based on config
            }
        
        return {
            "anomaly": False,
            "current_p95": current_p95,
            "threshold": threshold,
            "baseline_p95": self.current_session.baseline_p95_tokens
        }

    # =========================================================================
    # NEW in v3.2.1: INTENT CLASSIFICATION MANAGEMENT
    # =========================================================================

    def set_intent_classification(self, 
                                  classification: str,
                                  confidence: float,
                                  intent_hash: str,
                                  secondary_intents: List[str] = None,
                                  success_criteria: List[str] = None,
                                  domain_volatility: str = "medium") -> None:
        """
        Set intent classification for the session (AUTO mode).
        
        Args:
            classification: Primary intent classification
            confidence: Confidence score (0.0-1.0)
            intent_hash: Hash of intent for caching
            secondary_intents: List of secondary intents
            success_criteria: List of extracted success criteria
            domain_volatility: Domain volatility level
        """
        if not self.current_session:
            return
        
        self.current_session.intent_classification = classification
        self.current_session.intent_confidence = confidence
        self.current_session.intent_hash = intent_hash
        self.current_session.secondary_intents = secondary_intents or []
        self.current_session.success_criteria = success_criteria or []
        self.current_session.domain_volatility = domain_volatility
        
        self._save_current_session()

    def get_intent_summary(self) -> Dict:
        """Get intent classification summary for the session."""
        if not self.current_session:
            return {"classification": None}
        
        return {
            "classification": self.current_session.intent_classification,
            "confidence": self.current_session.intent_confidence,
            "intent_hash": self.current_session.intent_hash,
            "secondary_intents": self.current_session.secondary_intents,
            "success_criteria": self.current_session.success_criteria,
            "domain_volatility": self.current_session.domain_volatility
        }
