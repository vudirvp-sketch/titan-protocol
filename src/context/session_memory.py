"""
ITEM_007: SessionMemory for TITAN Protocol v1.2.0.

Cross-request context persistence with migration support.

This module provides session memory that persists context between requests,
different from InteractiveSession which is for debugging sessions.

Features:
- Cross-request context persistence
- Local file storage with optional AES-256-GCM encryption
- Session management: create, read, update, delete
- Migration support with downgrade handler (1.0.0, 1.1.0, 1.2.0)
- EventBus integration for SESSION_MEMORY_UPDATED events
- History pattern detection with configurable min_occurrences

Configuration:
- max_sessions_per_user: 10
- Default TTL: 86400 seconds (24 hours)
- Pattern detection min_occurrences: 3

Author: TITAN Protocol Team
Version: 1.2.0
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, TYPE_CHECKING
from enum import Enum
import json
import logging
import uuid
import hashlib
import threading
import os

from src.utils.timezone import now_utc, now_utc_iso, from_iso8601

if TYPE_CHECKING:
    from src.events.event_bus import EventBus, Event


class SessionVersion(Enum):
    """Supported session schema versions."""
    V1_0_0 = "1.0.0"
    V1_1_0 = "1.1.0"
    V1_2_0 = "1.2.0"


@dataclass
class RequestRecord:
    """
    Record of a single request in the session history.
    
    Attributes:
        timestamp: When the request occurred
        request: The original request text
        intent: Detected intent
        profile: User profile at time of request
        skills_used: List of skill IDs that were used
        result_summary: Brief summary of the result
    """
    timestamp: str
    request: str
    intent: str = ""
    profile: str = ""
    skills_used: List[str] = field(default_factory=list)
    result_summary: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "timestamp": self.timestamp,
            "request": self.request,
            "intent": self.intent,
            "profile": self.profile,
            "skills_used": self.skills_used,
            "result_summary": self.result_summary,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RequestRecord":
        """Deserialize from dictionary."""
        return cls(
            timestamp=data.get("timestamp", now_utc_iso()),
            request=data.get("request", ""),
            intent=data.get("intent", ""),
            profile=data.get("profile", ""),
            skills_used=data.get("skills_used", []),
            result_summary=data.get("result_summary", ""),
        )


@dataclass
class Session:
    """
    Cross-request session data with migration tracking.
    
    Attributes:
        session_id: Unique identifier for this session
        profile: User profile (designer/developer/analyst/devops/researcher)
        tools: List of preferred/activated tools
        history: List of request records
        preferences: User preferences dictionary
        metadata: Additional session metadata
        version: Schema version for migration tracking
        created_at: Session creation timestamp
        updated_at: Last update timestamp
        expires_at: Optional expiration timestamp
    """
    session_id: str
    profile: Optional[str] = None
    tools: List[str] = field(default_factory=list)
    history: List[RequestRecord] = field(default_factory=list)
    preferences: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: str = "1.2.0"
    created_at: str = field(default_factory=now_utc_iso)
    updated_at: str = field(default_factory=now_utc_iso)
    expires_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "session_id": self.session_id,
            "profile": self.profile,
            "tools": self.tools,
            "history": [h.to_dict() for h in self.history],
            "preferences": self.preferences,
            "metadata": self.metadata,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        """Deserialize from dictionary."""
        history = [RequestRecord.from_dict(h) for h in data.get("history", [])]
        return cls(
            session_id=data["session_id"],
            profile=data.get("profile"),
            tools=data.get("tools", []),
            history=history,
            preferences=data.get("preferences", {}),
            metadata=data.get("metadata", {}),
            version=data.get("version", "1.0.0"),
            created_at=data.get("created_at", now_utc_iso()),
            updated_at=data.get("updated_at", now_utc_iso()),
            expires_at=data.get("expires_at"),
        )
    
    def is_expired(self) -> bool:
        """Check if session has expired."""
        if not self.expires_at:
            return False
        try:
            exp_time = from_iso8601(self.expires_at)
            return now_utc() > exp_time
        except (ValueError, TypeError):
            return False


@dataclass
class SessionMemoryConfig:
    """
    Configuration for SessionMemory.
    
    Attributes:
        storage_path: Path to session storage directory
        max_sessions_per_user: Maximum sessions allowed per user
        default_ttl_seconds: Default session TTL (24 hours)
        encryption_enabled: Whether to encrypt sessions at rest
        encryption_key: Optional encryption key (if None, generates from secret)
        backup_before_migration: Create backup before schema migration
        backup_retention_days: Days to keep migration backups
        history_max_entries: Maximum history entries per session
        pattern_min_occurrences: Minimum occurrences for pattern detection
    """
    storage_path: str = ".titan/sessions"
    max_sessions_per_user: int = 10
    default_ttl_seconds: int = 86400  # 24 hours
    encryption_enabled: bool = False
    encryption_key: Optional[bytes] = None
    backup_before_migration: bool = True
    backup_retention_days: int = 7
    history_max_entries: int = 100
    pattern_min_occurrences: int = 3
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionMemoryConfig":
        """Create config from dictionary."""
        return cls(
            storage_path=data.get("storage_path", ".titan/sessions"),
            max_sessions_per_user=data.get("max_sessions_per_user", 10),
            default_ttl_seconds=data.get("default_ttl_seconds", 86400),
            encryption_enabled=data.get("encryption_enabled", False),
            encryption_key=data.get("encryption_key"),
            backup_before_migration=data.get("backup_before_migration", True),
            backup_retention_days=data.get("backup_retention_days", 7),
            history_max_entries=data.get("history_max_entries", 100),
            pattern_min_occurrences=data.get("pattern_min_occurrences", 3),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "storage_path": self.storage_path,
            "max_sessions_per_user": self.max_sessions_per_user,
            "default_ttl_seconds": self.default_ttl_seconds,
            "encryption_enabled": self.encryption_enabled,
            "backup_before_migration": self.backup_before_migration,
            "backup_retention_days": self.backup_retention_days,
            "history_max_entries": self.history_max_entries,
            "pattern_min_occurrences": self.pattern_min_occurrences,
        }


@dataclass
class DetectedPattern:
    """
    A detected pattern from session history.
    
    Attributes:
        pattern_type: Type of pattern (intent, tool, profile, request)
        pattern_value: The detected pattern value
        occurrences: Number of times this pattern occurred
        confidence: Confidence score (0.0 to 1.0)
        first_seen: When pattern was first observed
        last_seen: When pattern was last observed
    """
    pattern_type: str
    pattern_value: str
    occurrences: int
    confidence: float
    first_seen: str
    last_seen: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "pattern_type": self.pattern_type,
            "pattern_value": self.pattern_value,
            "occurrences": self.occurrences,
            "confidence": self.confidence,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


class SessionMemory:
    """
    Cross-request context persistence with migration support.
    
    ITEM_007: Provides session memory that persists between requests.
    Different from InteractiveSession which is for debugging sessions.
    
    Features:
    - Cross-request context persistence
    - Local file storage with optional AES-256-GCM encryption
    - Session management: create, read, update, delete
    - Migration support with downgrade handler
    - EventBus integration for SESSION_MEMORY_UPDATED events
    - History pattern detection
    
    Usage:
        from src.events.event_bus import EventBus
        
        event_bus = EventBus()
        config = SessionMemoryConfig(default_ttl_seconds=86400)
        
        memory = SessionMemory(config=config, event_bus=event_bus)
        
        # Create session
        session = memory.create_session("user-123")
        
        # Update session
        memory.update_session("user-123", {"profile": "developer"})
        
        # Add request to history
        memory.add_request("user-123", "Refactor the auth module", {
            "intent": "refactor",
            "skills_used": ["ast_parse", "refactor_engine"]
        })
        
        # Detect patterns
        patterns = memory.detect_patterns("user-123")
        
        # Migrate session schema
        memory.migrate_session("user-123", "1.0.0", "1.2.0")
    """
    
    CURRENT_VERSION = "1.2.0"
    
    def __init__(
        self,
        config: Optional[SessionMemoryConfig] = None,
        event_bus: Optional["EventBus"] = None,
    ):
        """
        Initialize SessionMemory.
        
        Args:
            config: Optional configuration
            event_bus: Optional EventBus for event emission
        """
        if isinstance(config, dict):
            config = SessionMemoryConfig.from_dict(config)
        self._config = config or SessionMemoryConfig()
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.RLock()
        
        # Initialize storage
        self._storage_path = Path(self._config.storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize encryption if enabled
        self._cipher = None
        if self._config.encryption_enabled:
            self._init_encryption()
        
        # Load existing sessions
        self._load_sessions()
        
        self._logger.info(
            f"SessionMemory initialized (storage={self._config.storage_path}, "
            f"encryption={self._config.encryption_enabled})"
        )
    
    def _init_encryption(self) -> None:
        """Initialize AES-256-GCM encryption."""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            import os
            
            # Use provided key or generate from environment
            if self._config.encryption_key:
                key = self._config.encryption_key
            else:
                # Generate key from secret
                secret = os.environ.get("TITAN_SESSION_SECRET", "titan-default-secret")
                key = hashlib.sha256(secret.encode()).digest()
            
            if len(key) != 32:
                key = hashlib.sha256(key).digest()
            
            self._cipher = AESGCM(key)
            self._logger.info("AES-256-GCM encryption initialized")
            
        except ImportError:
            self._logger.warning(
                "cryptography package not available, disabling encryption"
            )
            self._config.encryption_enabled = False
    
    def _encrypt(self, data: bytes) -> bytes:
        """Encrypt data using AES-256-GCM."""
        if not self._cipher:
            return data
        
        import os
        nonce = os.urandom(12)
        encrypted = self._cipher.encrypt(nonce, data, None)
        return nonce + encrypted
    
    def _decrypt(self, data: bytes) -> bytes:
        """Decrypt data using AES-256-GCM."""
        if not self._cipher:
            return data
        
        nonce = data[:12]
        ciphertext = data[12:]
        return self._cipher.decrypt(nonce, ciphertext, None)
    
    def _load_sessions(self) -> None:
        """Load existing sessions from storage."""
        try:
            for session_file in self._storage_path.glob("*.json"):
                try:
                    if self._config.encryption_enabled:
                        with open(session_file, "rb") as f:
                            encrypted_data = f.read()
                        data = self._decrypt(encrypted_data)
                        session_dict = json.loads(data.decode("utf-8"))
                    else:
                        with open(session_file, "r") as f:
                            session_dict = json.load(f)
                    
                    session = Session.from_dict(session_dict)
                    
                    # Skip expired sessions
                    if session.is_expired():
                        self._logger.debug(f"Skipping expired session: {session.session_id}")
                        continue
                    
                    self._sessions[session.session_id] = session
                    
                except Exception as e:
                    self._logger.warning(f"Failed to load session {session_file}: {e}")
                    
            self._logger.info(f"Loaded {len(self._sessions)} sessions from storage")
            
        except Exception as e:
            self._logger.error(f"Failed to load sessions: {e}")
    
    def _save_session(self, session: Session) -> bool:
        """Save session to storage."""
        try:
            session_file = self._storage_path / f"{session.session_id}.json"
            
            if self._config.encryption_enabled:
                data = json.dumps(session.to_dict()).encode("utf-8")
                encrypted_data = self._encrypt(data)
                with open(session_file, "wb") as f:
                    f.write(encrypted_data)
            else:
                with open(session_file, "w") as f:
                    json.dump(session.to_dict(), f, indent=2)
            
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to save session {session.session_id}: {e}")
            return False
    
    def _delete_session_file(self, session_id: str) -> bool:
        """Delete session file from storage."""
        try:
            session_file = self._storage_path / f"{session_id}.json"
            if session_file.exists():
                session_file.unlink()
            return True
        except Exception as e:
            self._logger.error(f"Failed to delete session file {session_id}: {e}")
            return False
    
    def _emit_memory_updated(self, session_id: str, updates: Dict[str, Any]) -> None:
        """Emit SESSION_MEMORY_UPDATED event."""
        if not self._event_bus:
            return
        
        from src.events.event_bus import Event, EventSeverity
        
        event = Event(
            event_type="SESSION_MEMORY_UPDATED",
            data={
                "session_id": session_id,
                "updates": updates,
                "timestamp": now_utc_iso(),
            },
            severity=EventSeverity.DEBUG,
            source="SessionMemory",
        )
        self._event_bus.emit(event)
    
    def _calculate_expires_at(self, ttl_seconds: Optional[int] = None) -> str:
        """Calculate expiration timestamp."""
        from datetime import timedelta
        
        ttl = ttl_seconds or self._config.default_ttl_seconds
        expires = now_utc() + timedelta(seconds=ttl)
        return expires.isoformat().replace("+00:00", "Z")
    
    # =========================================================================
    # Session Management Operations
    # =========================================================================
    
    def create_session(
        self,
        session_id: Optional[str] = None,
        profile: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> Session:
        """
        Create a new session with default state.
        
        Args:
            session_id: Optional session ID (auto-generated if not provided)
            profile: Optional user profile
            ttl_seconds: Optional TTL override
        
        Returns:
            The created Session instance
        
        Raises:
            ValueError: If session limit exceeded
        """
        with self._lock:
            # Check session limit
            if len(self._sessions) >= self._config.max_sessions_per_user:
                # Try to evict expired sessions first
                self._evict_expired_sessions()
                
                if len(self._sessions) >= self._config.max_sessions_per_user:
                    raise ValueError(
                        f"Session limit exceeded (max: {self._config.max_sessions_per_user})"
                    )
            
            # Generate session ID if not provided
            if not session_id:
                session_id = str(uuid.uuid4())
            
            # Check for existing session
            if session_id in self._sessions:
                self._logger.warning(f"Session {session_id} already exists, returning existing")
                return self._sessions[session_id]
            
            # Create new session
            session = Session(
                session_id=session_id,
                profile=profile,
                version=self.CURRENT_VERSION,
                expires_at=self._calculate_expires_at(ttl_seconds),
            )
            
            # Save to storage and memory
            self._save_session(session)
            self._sessions[session_id] = session
            
            # Emit event
            self._emit_memory_updated(session_id, {"action": "created"})
            
            self._logger.info(f"Created session: {session_id}")
            return session
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """
        Get session by ID.
        
        Args:
            session_id: The session identifier
        
        Returns:
            Session instance or None if not found/expired
        """
        with self._lock:
            session = self._sessions.get(session_id)
            
            if not session:
                return None
            
            if session.is_expired():
                self._logger.debug(f"Session {session_id} has expired")
                self.delete_session(session_id)
                return None
            
            return session
    
    def update_session(self, session_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update session with automatic event emission.
        
        Args:
            session_id: The session identifier
            updates: Dictionary of updates to apply
        
        Returns:
            True if update was successful
        """
        with self._lock:
            session = self.get_session(session_id)
            
            if not session:
                self._logger.warning(f"Session {session_id} not found for update")
                return False
            
            # Apply updates
            if "profile" in updates:
                session.profile = updates["profile"]
            if "tools" in updates:
                session.tools = updates["tools"]
            if "preferences" in updates:
                session.preferences.update(updates["preferences"])
            if "metadata" in updates:
                session.metadata.update(updates["metadata"])
            
            # Update timestamp
            session.updated_at = now_utc_iso()
            
            # Save and emit
            self._save_session(session)
            self._emit_memory_updated(session_id, updates)
            
            self._logger.debug(f"Updated session: {session_id}")
            return True
    
    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.
        
        Args:
            session_id: The session identifier
        
        Returns:
            True if session was deleted
        """
        with self._lock:
            if session_id not in self._sessions:
                return False
            
            del self._sessions[session_id]
            self._delete_session_file(session_id)
            
            self._emit_memory_updated(session_id, {"action": "deleted"})
            
            self._logger.info(f"Deleted session: {session_id}")
            return True
    
    def _evict_expired_sessions(self) -> int:
        """Evict all expired sessions.
        
        Returns:
            Number of sessions evicted
        """
        evicted = 0
        expired_ids = [
            sid for sid, session in self._sessions.items()
            if session.is_expired()
        ]
        
        for session_id in expired_ids:
            self.delete_session(session_id)
            evicted += 1
        
        if evicted > 0:
            self._logger.info(f"Evicted {evicted} expired sessions")
        
        return evicted
    
    # =========================================================================
    # History Management
    # =========================================================================
    
    def add_request(
        self,
        session_id: str,
        request: str,
        result: Dict[str, Any],
    ) -> bool:
        """
        Add a request to session history.
        
        Args:
            session_id: The session identifier
            request: The request text
            result: Dictionary with intent, profile, skills_used, result_summary
        
        Returns:
            True if request was added successfully
        """
        with self._lock:
            session = self.get_session(session_id)
            
            if not session:
                self._logger.warning(f"Session {session_id} not found for adding request")
                return False
            
            # Create request record
            record = RequestRecord(
                timestamp=now_utc_iso(),
                request=request,
                intent=result.get("intent", ""),
                profile=result.get("profile", session.profile or ""),
                skills_used=result.get("skills_used", []),
                result_summary=result.get("result_summary", ""),
            )
            
            # Add to history
            session.history.append(record)
            
            # Trim history if needed
            if len(session.history) > self._config.history_max_entries:
                session.history = session.history[-self._config.history_max_entries:]
            
            # Update session
            session.updated_at = now_utc_iso()
            self._save_session(session)
            
            self._emit_memory_updated(session_id, {"action": "request_added"})
            
            return True
    
    def get_history_patterns(self, session_id: str) -> List[DetectedPattern]:
        """
        Get detected patterns from session history.
        
        Args:
            session_id: The session identifier
        
        Returns:
            List of DetectedPattern instances
        """
        return self.detect_patterns(session_id)
    
    def get_preferred_tools(self, session_id: str) -> List[str]:
        """
        Get preferred tools from session.
        
        Args:
            session_id: The session identifier
        
        Returns:
            List of preferred tool IDs
        """
        session = self.get_session(session_id)
        if not session:
            return []
        
        return session.tools
    
    def set_user_profile(self, session_id: str, profile: str) -> bool:
        """
        Set user profile for session.
        
        Args:
            session_id: The session identifier
            profile: Profile type (designer/developer/analyst/devops/researcher)
        
        Returns:
            True if profile was set successfully
        """
        return self.update_session(session_id, {"profile": profile})
    
    # =========================================================================
    # Pattern Detection
    # =========================================================================
    
    def detect_patterns(self, session_id: str) -> List[DetectedPattern]:
        """
        Detect patterns from session history.
        
        Analyzes request history for recurring patterns in:
        - Intent usage
        - Tool usage
        - Profile consistency
        - Request keywords
        
        Args:
            session_id: The session identifier
        
        Returns:
            List of DetectedPattern instances meeting min_occurrences threshold
        """
        with self._lock:
            session = self.get_session(session_id)
            
            if not session or not session.history:
                return []
            
            patterns: List[DetectedPattern] = []
            history = session.history
            
            # Analyze intent patterns
            intent_counts: Dict[str, List[RequestRecord]] = {}
            for record in history:
                if record.intent:
                    if record.intent not in intent_counts:
                        intent_counts[record.intent] = []
                    intent_counts[record.intent].append(record)
            
            for intent, records in intent_counts.items():
                if len(records) >= self._config.pattern_min_occurrences:
                    patterns.append(DetectedPattern(
                        pattern_type="intent",
                        pattern_value=intent,
                        occurrences=len(records),
                        confidence=min(1.0, len(records) / len(history)),
                        first_seen=records[0].timestamp,
                        last_seen=records[-1].timestamp,
                    ))
            
            # Analyze tool patterns
            tool_counts: Dict[str, List[RequestRecord]] = {}
            for record in history:
                for tool in record.skills_used:
                    if tool not in tool_counts:
                        tool_counts[tool] = []
                    tool_counts[tool].append(record)
            
            for tool, records in tool_counts.items():
                if len(records) >= self._config.pattern_min_occurrences:
                    patterns.append(DetectedPattern(
                        pattern_type="tool",
                        pattern_value=tool,
                        occurrences=len(records),
                        confidence=min(1.0, len(records) / len(history)),
                        first_seen=records[0].timestamp,
                        last_seen=records[-1].timestamp,
                    ))
            
            # Analyze request keyword patterns
            keyword_counts: Dict[str, int] = {}
            for record in history:
                words = record.request.lower().split()
                for word in words:
                    if len(word) > 3:  # Skip short words
                        keyword_counts[word] = keyword_counts.get(word, 0) + 1
            
            for keyword, count in keyword_counts.items():
                if count >= self._config.pattern_min_occurrences:
                    # Find first and last occurrence
                    first_seen = history[0].timestamp
                    last_seen = history[-1].timestamp
                    for record in history:
                        if keyword in record.request.lower():
                            first_seen = record.timestamp
                            break
                    for record in reversed(history):
                        if keyword in record.request.lower():
                            last_seen = record.timestamp
                            break
                    
                    patterns.append(DetectedPattern(
                        pattern_type="keyword",
                        pattern_value=keyword,
                        occurrences=count,
                        confidence=min(1.0, count / len(history)),
                        first_seen=first_seen,
                        last_seen=last_seen,
                    ))
            
            self._logger.debug(
                f"Detected {len(patterns)} patterns in session {session_id}"
            )
            
            return patterns
    
    # =========================================================================
    # Migration Support
    # =========================================================================
    
    def migrate_session(
        self,
        session_id: str,
        from_version: str,
        to_version: str,
    ) -> bool:
        """
        Migrate session schema version.
        
        Supports migration paths:
        - 1.0.0 -> 1.1.0
        - 1.1.0 -> 1.2.0
        - 1.0.0 -> 1.2.0 (multi-step)
        
        Args:
            session_id: The session identifier
            from_version: Current schema version
            to_version: Target schema version
        
        Returns:
            True if migration was successful
        """
        with self._lock:
            session = self.get_session(session_id)
            
            if not session:
                self._logger.warning(f"Session {session_id} not found for migration")
                return False
            
            # Create backup before migration
            if self._config.backup_before_migration:
                self._create_migration_backup(session)
            
            # Determine migration path
            migration_path = self._get_migration_path(from_version, to_version)
            
            if not migration_path:
                self._logger.warning(
                    f"No migration path from {from_version} to {to_version}"
                )
                return False
            
            try:
                # Execute migration steps
                for step_from, step_to in migration_path:
                    self._apply_migration(session, step_from, step_to)
                
                # Update version
                session.version = to_version
                session.updated_at = now_utc_iso()
                self._save_session(session)
                
                self._emit_memory_updated(session_id, {
                    "action": "migrated",
                    "from_version": from_version,
                    "to_version": to_version,
                })
                
                self._logger.info(
                    f"Migrated session {session_id} from {from_version} to {to_version}"
                )
                
                return True
                
            except Exception as e:
                self._logger.error(f"Migration failed for {session_id}: {e}")
                return False
    
    def downgrade_session(
        self,
        session_id: str,
        from_version: str,
        to_version: str,
    ) -> bool:
        """
        Downgrade session schema version for rollback support.
        
        Supports downgrade paths:
        - 1.2.0 -> 1.1.0
        - 1.1.0 -> 1.0.0
        - 1.2.0 -> 1.0.0 (multi-step)
        
        Args:
            session_id: The session identifier
            from_version: Current schema version
            to_version: Target schema version
        
        Returns:
            True if downgrade was successful
        """
        with self._lock:
            session = self.get_session(session_id)
            
            if not session:
                self._logger.warning(f"Session {session_id} not found for downgrade")
                return False
            
            # Create backup before downgrade
            if self._config.backup_before_migration:
                self._create_migration_backup(session)
            
            # Determine downgrade path
            downgrade_path = self._get_downgrade_path(from_version, to_version)
            
            if not downgrade_path:
                self._logger.warning(
                    f"No downgrade path from {from_version} to {to_version}"
                )
                return False
            
            try:
                # Execute downgrade steps
                for step_from, step_to in downgrade_path:
                    self._apply_downgrade(session, step_from, step_to)
                
                # Update version
                session.version = to_version
                session.updated_at = now_utc_iso()
                self._save_session(session)
                
                self._emit_memory_updated(session_id, {
                    "action": "downgraded",
                    "from_version": from_version,
                    "to_version": to_version,
                })
                
                self._logger.info(
                    f"Downgraded session {session_id} from {from_version} to {to_version}"
                )
                
                return True
                
            except Exception as e:
                self._logger.error(f"Downgrade failed for {session_id}: {e}")
                return False
    
    def _get_migration_path(
        self,
        from_version: str,
        to_version: str,
    ) -> List[tuple]:
        """Get migration path as list of (from, to) tuples."""
        # Direct migrations
        migrations = {
            ("1.0.0", "1.1.0"): [("1.0.0", "1.1.0")],
            ("1.1.0", "1.2.0"): [("1.1.0", "1.2.0")],
            ("1.0.0", "1.2.0"): [("1.0.0", "1.1.0"), ("1.1.0", "1.2.0")],
        }
        
        return migrations.get((from_version, to_version), [])
    
    def _get_downgrade_path(
        self,
        from_version: str,
        to_version: str,
    ) -> List[tuple]:
        """Get downgrade path as list of (from, to) tuples."""
        # Direct downgrades
        downgrades = {
            ("1.2.0", "1.1.0"): [("1.2.0", "1.1.0")],
            ("1.1.0", "1.0.0"): [("1.1.0", "1.0.0")],
            ("1.2.0", "1.0.0"): [("1.2.0", "1.1.0"), ("1.1.0", "1.0.0")],
        }
        
        return downgrades.get((from_version, to_version), [])
    
    def _apply_migration(
        self,
        session: Session,
        from_version: str,
        to_version: str,
    ) -> None:
        """Apply a single migration step."""
        if (from_version, to_version) == ("1.0.0", "1.1.0"):
            # 1.0.0 -> 1.1.0: Add preferences field
            if not hasattr(session, "preferences"):
                session.preferences = {}
        
        elif (from_version, to_version) == ("1.1.0", "1.2.0"):
            # 1.1.0 -> 1.2.0: Add metadata field and tools field
            if not hasattr(session, "metadata"):
                session.metadata = {}
            if not hasattr(session, "tools"):
                session.tools = []
    
    def _apply_downgrade(
        self,
        session: Session,
        from_version: str,
        to_version: str,
    ) -> None:
        """Apply a single downgrade step."""
        if (from_version, to_version) == ("1.2.0", "1.1.0"):
            # 1.2.0 -> 1.1.0: Remove tools field, keep metadata
            # Store tools in metadata for recovery
            if hasattr(session, "tools") and session.tools:
                session.metadata["_legacy_tools"] = session.tools
            session.tools = []
        
        elif (from_version, to_version) == ("1.1.0", "1.0.0"):
            # 1.1.0 -> 1.0.0: Remove preferences field
            # Store preferences in metadata for recovery
            if hasattr(session, "preferences") and session.preferences:
                session.metadata["_legacy_preferences"] = session.preferences
            session.preferences = {}
    
    def _create_migration_backup(self, session: Session) -> None:
        """Create backup before migration."""
        try:
            backup_dir = self._storage_path / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = now_utc().strftime("%Y%m%d_%H%M%S")
            backup_file = backup_dir / f"{session.session_id}_{timestamp}.json"
            
            with open(backup_file, "w") as f:
                json.dump(session.to_dict(), f, indent=2)
            
            self._logger.debug(f"Created migration backup: {backup_file}")
            
            # Clean old backups
            self._clean_old_backups(backup_dir)
            
        except Exception as e:
            self._logger.warning(f"Failed to create migration backup: {e}")
    
    def _clean_old_backups(self, backup_dir: Path) -> None:
        """Clean backups older than retention period."""
        from datetime import timedelta
        
        retention = timedelta(days=self._config.backup_retention_days)
        cutoff = now_utc() - retention
        
        for backup_file in backup_dir.glob("*.json"):
            try:
                # Parse timestamp from filename
                parts = backup_file.stem.split("_")
                if len(parts) >= 3:
                    file_date = datetime.strptime(
                        f"{parts[-2]}_{parts[-1]}",
                        "%Y%m%d_%H%M%S"
                    ).replace(tzinfo=timezone.utc)
                    
                    if file_date < cutoff:
                        backup_file.unlink()
                        self._logger.debug(f"Deleted old backup: {backup_file}")
                        
            except (ValueError, IndexError) as e:
                self._logger.debug(f"Skipping backup cleanup for {backup_file}: {e}")
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def clear_session(self, session_id: str) -> bool:
        """
        Clear session data but keep the session itself.
        
        Args:
            session_id: The session identifier
        
        Returns:
            True if session was cleared
        """
        with self._lock:
            session = self.get_session(session_id)
            
            if not session:
                return False
            
            session.history.clear()
            session.preferences.clear()
            session.metadata.clear()
            session.tools.clear()
            session.updated_at = now_utc_iso()
            
            self._save_session(session)
            self._emit_memory_updated(session_id, {"action": "cleared"})
            
            return True
    
    def list_sessions(self) -> List[str]:
        """
        List all active session IDs.
        
        Returns:
            List of session IDs
        """
        with self._lock:
            # Filter out expired
            return [
                sid for sid, session in self._sessions.items()
                if not session.is_expired()
            ]
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get session memory statistics.
        
        Returns:
            Dictionary with statistics
        """
        with self._lock:
            total_history = sum(len(s.history) for s in self._sessions.values())
            
            profile_counts: Dict[str, int] = {}
            for session in self._sessions.values():
                if session.profile:
                    profile_counts[session.profile] = profile_counts.get(session.profile, 0) + 1
            
            return {
                "total_sessions": len(self._sessions),
                "max_sessions": self._config.max_sessions_per_user,
                "total_history_entries": total_history,
                "profile_distribution": profile_counts,
                "encryption_enabled": self._config.encryption_enabled,
                "storage_path": str(self._storage_path),
                "current_version": self.CURRENT_VERSION,
            }


def create_session_memory(
    config: Optional[Dict[str, Any]] = None,
    event_bus: Optional["EventBus"] = None,
) -> SessionMemory:
    """
    Factory function to create SessionMemory.
    
    Args:
        config: Optional configuration dictionary
        event_bus: Optional EventBus for event emission
    
    Returns:
        SessionMemory instance
    """
    cfg = SessionMemoryConfig.from_dict(config) if config else None
    return SessionMemory(config=cfg, event_bus=event_bus)
