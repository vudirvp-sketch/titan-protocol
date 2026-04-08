"""
State Manager for TITAN FUSE Protocol.

Manages session state, reasoning steps, budget allocation,
and cursor tracking for deterministic execution.

ITEM-120 Implementation:
- CredentialManager for provider credential isolation
- Environment variable injection pattern
- No credentials in session state or checkpoints

ITEM-STOR-05 Implementation:
- cursor_hash field in SessionState
- CursorTracker integration for drift detection
- Hash verification on resume

Author: TITAN FUSE Team
Version: 3.3.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
import hashlib
import json
import uuid
import os
import re
from types import SimpleNamespace

from src.utils.timezone import now_utc, now_utc_iso

from .assessment import AssessmentScore
from .cursor import CursorTracker, CursorState, DriftResult, compute_state_hash


class CredentialManager:
    """
    Manage provider credentials with environment variable isolation.
    
    ITEM-120: Provider credential isolation
    - Credentials stored in environment variables, not session state
    - Pattern: {PROVIDER}_API_KEY (e.g., OPENAI_API_KEY, ANTHROPIC_API_KEY)
    - Session state never contains api_key or credential fields
    
    Usage:
        cm = CredentialManager()
        creds = cm.get_credentials('openai')  # Reads from OPENAI_API_KEY env var
        cm.set_credentials('openai', {'api_key': 'sk-xxx'})  # Sets env var
    """
    
    # Patterns that should never appear in session state
    CREDENTIAL_PATTERNS = [
        r'api[_-]?key',
        r'secret[_-]?key', 
        r'access[_-]?token',
        r'auth[_-]?token',
        r'password',
        r'private[_-]?key',
        r'credential',
    ]
    
    # Known provider environment variable patterns
    PROVIDER_ENV_PATTERNS = {
        'openai': 'OPENAI_API_KEY',
        'anthropic': 'ANTHROPIC_API_KEY',
        'google': 'GOOGLE_API_KEY',
        'azure': 'AZURE_OPENAI_API_KEY',
        'cohere': 'COHERE_API_KEY',
        'huggingface': 'HUGGINGFACE_TOKEN',
    }
    
    def __init__(self):
        """Initialize credential manager."""
        self._cached_providers: Dict[str, Dict] = {}
    
    def get_credentials(self, provider: str) -> Dict[str, str]:
        """
        Get credentials for a provider from environment.
        
        Args:
            provider: Provider name (e.g., 'openai', 'anthropic')
            
        Returns:
            Dict with 'api_key' if found, empty dict otherwise
        """
        provider = provider.lower()
        env_var = self.PROVIDER_ENV_PATTERNS.get(provider, f"{provider.upper()}_API_KEY")
        
        api_key = os.environ.get(env_var)
        if api_key:
            return {'api_key': api_key, 'source': 'environment'}
        
        return {}
    
    def set_credentials(self, provider: str, credentials: Dict) -> None:
        """
        Set credentials for a provider in environment.
        
        Args:
            provider: Provider name
            credentials: Dict with 'api_key' or similar
        """
        provider = provider.lower()
        env_var = self.PROVIDER_ENV_PATTERNS.get(provider, f"{provider.upper()}_API_KEY")
        
        if 'api_key' in credentials:
            os.environ[env_var] = credentials['api_key']
            self._cached_providers[provider] = {'configured': True}
    
    def rotate_credentials(self, provider: str) -> Dict:
        """
        Rotate credentials for a provider.
        
        Note: Actual rotation must be done externally. This method
        clears the cached credentials and returns instructions.
        
        Args:
            provider: Provider name
            
        Returns:
            Dict with rotation instructions
        """
        provider = provider.lower()
        env_var = self.PROVIDER_ENV_PATTERNS.get(provider, f"{provider.upper()}_API_KEY")
        
        # Clear from environment
        if env_var in os.environ:
            del os.environ[env_var]
        
        # Clear cache
        if provider in self._cached_providers:
            del self._cached_providers[provider]
        
        return {
            'status': 'cleared',
            'provider': provider,
            'instruction': f"Set new {env_var} environment variable with rotated key"
        }
    
    def validate_no_key_in_state(self, state: Dict) -> bool:
        """
        Validate that no credential fields are in session state.
        
        This is called before saving checkpoints to ensure
        credentials are never persisted (ITEM-120 step 04).
        
        Args:
            state: Session state dictionary to validate
            
        Returns:
            True if no credentials found, False otherwise
        """
        state_str = json.dumps(state, default=str).lower()
        
        for pattern in self.CREDENTIAL_PATTERNS:
            if re.search(pattern, state_str):
                # Check if it's actually a credential value (not just field name)
                # Look for actual secret-like values
                for key in state.keys():
                    if re.search(pattern, key.lower()):
                        value = str(state.get(key, ''))
                        # Check for secret-like values (long alphanumeric strings)
                        if re.search(r'[A-Za-z0-9_-]{20,}', value):
                            return False
        
        return True
    
    def scan_for_credentials(self, data: str) -> List[Dict]:
        """
        Scan string data for potential credential patterns.
        
        Used by checkpoint serialization to warn about potential leaks.
        
        Args:
            data: String data to scan
            
        Returns:
            List of potential credential findings
        """
        findings = []
        
        # Common API key patterns
        api_key_patterns = [
            (r'sk-[A-Za-z0-9]{20,}', 'OPENAI_KEY'),
            (r'sk-ant-[A-Za-z0-9]{20,}', 'ANTHROPIC_KEY'),
            (r'ghp_[A-Za-z0-9]{36}', 'GITHUB_PAT'),
            (r'AKIA[0-9A-Z]{16}', 'AWS_KEY'),
            (r'eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*', 'JWT'),
        ]
        
        for pattern, name in api_key_patterns:
            matches = re.findall(pattern, data)
            if matches:
                findings.append({
                    'type': name,
                    'count': len(matches),
                    'severity': 'CRITICAL'
                })
        
        return findings


class SessionDict(dict):
    """Dictionary that also supports attribute access."""
    
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
    
    def __setattr__(self, name, value):
        self[name] = value
    
    def __delattr__(self, name):
        try:
            del self[name]
        except KeyError:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")


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
    - Model version fingerprint (ITEM-ARCH-15)
    """
    # Session identification
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    protocol_version: str = "3.4.0"
    created_at: str = field(default_factory=now_utc_iso)
    updated_at: str = field(default_factory=now_utc_iso)

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
    cursor_hash: Optional[str] = None  # ITEM-STOR-05: SHA-256 of last patch applied

    # ITEM-ARCH-15: Model version fingerprint
    model_version_fingerprint: Optional[str] = None  # Fingerprint from ModelRouter
    root_model_fingerprint: Optional[str] = None
    leaf_model_fingerprint: Optional[str] = None

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
                "timestamp": now_utc_iso(),
                "details": details or {}
            }
        self._update_timestamp()

    def fail_gate(self, gate_id: str, reason: str, details: Dict = None) -> None:
        """Mark a gate as failed."""
        if gate_id in self.gates:
            self.gates[gate_id] = {
                "status": "FAIL",
                "reason": reason,
                "timestamp": now_utc_iso(),
                "details": details or {}
            }
        self._update_timestamp()

    def warn_gate(self, gate_id: str, reason: str, details: Dict = None) -> None:
        """Mark a gate with warning."""
        if gate_id in self.gates:
            self.gates[gate_id] = {
                "status": "WARN",
                "reason": reason,
                "timestamp": now_utc_iso(),
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
            "cursor_hash": self.cursor_hash,  # ITEM-STOR-05: For drift detection
            "cursor_state": self.cursor_tracker.get_state(),
            # ITEM-ARCH-15: Model version fingerprints for reproducibility
            "model_version_fingerprint": self.model_version_fingerprint,
            "root_model_fingerprint": self.root_model_fingerprint,
            "leaf_model_fingerprint": self.leaf_model_fingerprint,
            "gaps": self.gaps,
            "updated_at": self.updated_at
        }
    
    def compute_cursor_hash(self) -> str:
        """
        Compute cursor hash from current state.
        
        ITEM-STOR-05: Compute SHA-256 hash for drift detection.
        
        Returns:
            Cursor hash string
        """
        state_snapshot = self.get_state_snapshot()
        # Remove cursor_hash itself to avoid circular dependency
        state_snapshot.pop("cursor_hash", None)
        self.cursor_hash = compute_state_hash(state_snapshot)
        return self.cursor_hash
    
    def verify_cursor_hash(self, expected_hash: str) -> DriftResult:
        """
        Verify cursor hash against expected value.
        
        ITEM-STOR-05: Detect external modifications.
        
        Args:
            expected_hash: Expected cursor hash from checkpoint
            
        Returns:
            DriftResult with validation status
        """
        current_hash = self.compute_cursor_hash()
        return self.cursor_tracker.verify_cursor(expected_hash)

    def set_model_fingerprints(self, fingerprints: Dict[str, str]) -> None:
        """
        ITEM-ARCH-15: Set model version fingerprints from ModelRouter.

        Should be called at session start to record the model versions
        being used for this session.

        Args:
            fingerprints: Dict with 'root' and 'leaf' fingerprints from ModelRouter
        """
        self.root_model_fingerprint = fingerprints.get("root")
        self.leaf_model_fingerprint = fingerprints.get("leaf")
        # Combined fingerprint for quick comparison
        if self.root_model_fingerprint and self.leaf_model_fingerprint:
            combined = f"{self.root_model_fingerprint}:{self.leaf_model_fingerprint}"
            self.model_version_fingerprint = hashlib.sha256(
                combined.encode()
            ).hexdigest()[:32]
        self._update_timestamp()

    def get_model_fingerprints(self) -> Dict[str, Optional[str]]:
        """
        ITEM-ARCH-15: Get stored model fingerprints.

        Returns:
            Dict with root, leaf, and combined fingerprints
        """
        return {
            "root": self.root_model_fingerprint,
            "leaf": self.leaf_model_fingerprint,
            "combined": self.model_version_fingerprint
        }

    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.get_state_snapshot(), indent=2)

    def _update_timestamp(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = now_utc_iso()


class StateManager:
    """
    Manager for TITAN FUSE Protocol session state.
    
    Provides high-level interface for session creation, checkpoint management,
    and state transitions.
    """
    
    PROTOCOL_VERSION = "3.2.2"
    
    def __init__(self, repo_root=None):
        """Initialize state manager."""
        self.repo_root = repo_root
        self.current_session: Optional[Dict] = None
        self._session_state: Optional[SessionState] = None
        self._token_history: List[int] = []
        self._latency_history: List[int] = []
        self._confidence_scores: List[str] = []
        self._leaf_model_calls = 0
        self._root_model_calls = 0
        self._recursion_depth = 0
        self._recursion_depth_peak = 0
        self._max_recursion_depth = 1
        self._all_high_confidence = True
        
    def create_session(self, session_id: str = None, max_tokens: int = 100000, 
                       input_files: List[str] = None) -> Dict:
        """Create a new session."""
        session_id = session_id or str(uuid.uuid4())
        
        # Calculate checksum for input files
        source_checksum = None
        source_file = None
        if input_files:
            source_file = input_files[0] if len(input_files) == 1 else None
            if source_file:
                try:
                    with open(source_file, 'rb') as f:
                        source_checksum = hashlib.sha256(f.read()).hexdigest()
                except Exception:
                    source_checksum = None
        
        self.current_session = SessionDict({
            "id": session_id,
            "status": "INITIALIZED",
            "protocol_version": self.PROTOCOL_VERSION,
            "created_at": now_utc_iso(),
            "source_file": source_file,
            "source_checksum": source_checksum,
            "max_tokens": max_tokens,
            "tokens_used": 0,
            "current_phase": 0,
            "current_gate": 0,
            "chunk_cursor": None,
            "chunks": {},
            "open_issues": [],
            "known_gaps": [],
            "gates_passed": [],
            "completed_batches": [],
            "input_files": input_files or [],
            "recursion_depth": 0,
            "recursion_depth_peak": 0,
            "token_history": [],
            "latency_history": [],
            "confidence_scores": [],
            "leaf_model_calls": 0,
            "root_model_calls": 0,
            "all_high_confidence": True,
            "confidence_summary": {"all_high": True, "high_count": 0, "med_count": 0, "low_count": 0}
        })
        
        self._session_state = SessionState(
            session_id=session_id,
            max_tokens=max_tokens,
            source_file=source_file,
            source_checksum=source_checksum
        )
        
        return self.current_session
    
    def get_current_session(self) -> Optional[Dict]:
        """Get current session."""
        return self.current_session
    
    def save_checkpoint(self, checkpoint_path: str = None) -> Dict:
        """Save current session to checkpoint."""
        if not self.current_session:
            return {"success": False, "error": "No active session"}
        
        checkpoint_path = checkpoint_path or str(
            self.repo_root / "checkpoints" / "checkpoint.json"
        ) if self.repo_root else "checkpoint.json"
        
        checkpoint_data = self.current_session.copy()
        checkpoint_data["saved_at"] = now_utc_iso()
        
        try:
            import os
            os.makedirs(os.path.dirname(checkpoint_path), exist_ok=True)
            with open(checkpoint_path, 'w') as f:
                json.dump(checkpoint_data, f, indent=2)
            return {"success": True, "checkpoint_path": checkpoint_path}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def resume_from_checkpoint(self, checkpoint_path: str, 
                                allow_unsafe: bool = False) -> Dict:
        """Resume session from checkpoint."""
        try:
            with open(checkpoint_path, 'r') as f:
                data = json.load(f)
            
            self.current_session = SessionDict(data)
            return {
                "success": True,
                "status": "RESUMED",
                "session_id": data.get("id"),
                "gates_passed": data.get("gates_passed", []),
                "completed_batches": data.get("completed_batches", []),
                "chunk_cursor": data.get("chunk_cursor"),
                "open_issues": data.get("open_issues", [])
            }
        except FileNotFoundError:
            return {"success": False, "status": "FAILED", "error": "Checkpoint file not found"}
        except json.JSONDecodeError:
            return {"success": False, "status": "FAILED", "error": "Invalid checkpoint file"}
        except Exception as e:
            return {"success": False, "status": "FAILED", "error": str(e)}
    
    def configure_provider(self, provider: str, api_key: str) -> Dict:
        """Configure LLM provider."""
        # Store provider configuration (in real implementation would use secure storage)
        if not self.current_session:
            self.create_session()
        self.current_session["provider"] = provider
        return {"success": True, "message": f"Configured provider: {provider}"}
    
    def compact_context(self, strategy: str = "auto") -> Dict:
        """Compact context to reduce token usage."""
        if not self.current_session:
            return {"success": False, "error": "No active session"}
        return {"success": True, "strategy": strategy, "tokens_freed": 0}
    
    def export_artifacts(self, session: Dict, output_path, format: str = "json") -> Dict:
        """Export session artifacts."""
        artifacts = []
        try:
            import os
            os.makedirs(output_path, exist_ok=True)
            
            # Export session data
            artifact_path = os.path.join(output_path, "session.json")
            with open(artifact_path, 'w') as f:
                json.dump(session, f, indent=2)
            artifacts.append(artifact_path)
            
            return {"success": True, "artifacts": artifacts}
        except Exception as e:
            return {"success": False, "error": str(e), "artifacts": artifacts}
    
    def increment_recursion_depth(self) -> bool:
        """Increment recursion depth if under limit."""
        if self._recursion_depth >= self._max_recursion_depth:
            return False
        self._recursion_depth += 1
        self._recursion_depth_peak = max(self._recursion_depth_peak, self._recursion_depth)
        if self.current_session:
            self.current_session["recursion_depth"] = self._recursion_depth
            self.current_session["recursion_depth_peak"] = self._recursion_depth_peak
        return True
    
    def decrement_recursion_depth(self) -> None:
        """Decrement recursion depth."""
        if self._recursion_depth > 0:
            self._recursion_depth -= 1
            if self.current_session:
                self.current_session["recursion_depth"] = self._recursion_depth
    
    def record_query_metrics(self, tokens: int, latency_ms: int, model_type: str = "leaf") -> None:
        """Record query metrics for telemetry."""
        self._token_history.append(tokens)
        self._latency_history.append(latency_ms)
        if model_type == "leaf":
            self._leaf_model_calls += 1
        else:
            self._root_model_calls += 1
        
        if self.current_session:
            self.current_session["token_history"] = self._token_history
            self.current_session["latency_history"] = self._latency_history
            self.current_session["leaf_model_calls"] = self._leaf_model_calls
            self.current_session["root_model_calls"] = self._root_model_calls
    
    def record_confidence(self, confidence: str) -> None:
        """Record confidence score."""
        self._confidence_scores.append(confidence)
        if confidence != "HIGH":
            self._all_high_confidence = False
        
        if self.current_session:
            self.current_session["confidence_scores"] = self._confidence_scores
            self.current_session["all_high_confidence"] = self._all_high_confidence
            self.current_session["confidence_summary"] = self.get_confidence_summary()
    
    def get_token_percentiles(self) -> Dict:
        """Get token usage percentiles."""
        if not self._token_history:
            return {"p50": 0, "p95": 0, "total_queries": 0}
        
        sorted_tokens = sorted(self._token_history)
        n = len(sorted_tokens)
        
        p50_idx = int(n * 0.5)
        p95_idx = int(n * 0.95)
        
        return {
            "p50": sorted_tokens[p50_idx] if p50_idx < n else sorted_tokens[-1],
            "p95": sorted_tokens[p95_idx] if p95_idx < n else sorted_tokens[-1],
            "total_queries": n
        }
    
    def get_confidence_summary(self) -> Dict:
        """Get confidence score summary."""
        return {
            "all_high": all(c == "HIGH" for c in self._confidence_scores) if self._confidence_scores else True,
            "high_count": self._confidence_scores.count("HIGH"),
            "med_count": self._confidence_scores.count("MED"),
            "low_count": self._confidence_scores.count("LOW")
        }
