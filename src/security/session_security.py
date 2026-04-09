"""
TITAN FUSE Protocol - Session Security

ITEM_017: SessionSecurity for TITAN Protocol v1.2.0

Provides secure session management capabilities.
Implements session ID generation, validation, and optional encryption.

Key Features:
- Secure session ID generation (UUID4 with high entropy)
- Session ID validation
- Optional AES-256-GCM encryption for session data
- Key rotation support
- IP binding option (disabled by default for privacy)

Integration Points:
- SessionMemory: Uses SessionSecurity for secure session handling
- EventBus: Emits SESSION_SECURITY_ALERT events
- UniversalRouter: Validates session IDs for requests

Author: TITAN FUSE Team
Version: 1.2.0
"""

import os
import uuid
import hashlib
import hmac
import json
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
import logging
import base64

from src.events.event_bus import Event, EventSeverity, EventBus
from src.utils.timezone import now_utc_iso


class SessionSecurityLevel(Enum):
    """
    Security level for session handling.
    
    Levels:
    - STANDARD: Basic security, no encryption
    - ENHANCED: Additional validation and integrity checks
    - ENCRYPTED: Full encryption at rest
    """
    STANDARD = "standard"
    ENHANCED = "enhanced"
    ENCRYPTED = "encrypted"


@dataclass
class SessionSecurityConfig:
    """
    Configuration for SessionSecurity.
    
    Attributes:
        security_level: Security level for sessions
        session_id_format: Format for session IDs (uuid4, uuid4_hashed, random_hex)
        entropy_bits: Minimum entropy bits for session IDs
        encryption_enabled: Enable encryption at rest
        encryption_algorithm: Encryption algorithm (AES-256-GCM recommended)
        key_rotation_days: Days between key rotations
        ip_binding_enabled: Enable IP binding for sessions (privacy concern)
        session_expiry_check: Enable session expiry validation
        max_session_age_hours: Maximum session age in hours
        enable_events: Enable event emission
    """
    security_level: SessionSecurityLevel = SessionSecurityLevel.STANDARD
    session_id_format: str = "uuid4"  # uuid4, uuid4_hashed, random_hex
    entropy_bits: int = 122  # UUID4 provides ~122 bits of entropy
    encryption_enabled: bool = False
    encryption_algorithm: str = "AES-256-GCM"
    key_rotation_days: int = 30
    ip_binding_enabled: bool = False  # Privacy concern - disabled by default
    session_expiry_check: bool = True
    max_session_age_hours: int = 168  # 7 days
    enable_events: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "security_level": self.security_level.value,
            "session_id_format": self.session_id_format,
            "entropy_bits": self.entropy_bits,
            "encryption_enabled": self.encryption_enabled,
            "encryption_algorithm": self.encryption_algorithm,
            "key_rotation_days": self.key_rotation_days,
            "ip_binding_enabled": self.ip_binding_enabled,
            "session_expiry_check": self.session_expiry_check,
            "max_session_age_hours": self.max_session_age_hours,
            "enable_events": self.enable_events,
        }


@dataclass
class SessionSecurityStats:
    """
    Statistics for session security operations.
    
    Attributes:
        sessions_created: Total sessions created
        sessions_validated: Total validations performed
        sessions_rejected: Sessions rejected due to security
        encryptions_performed: Number of encryptions
        decryptions_performed: Number of decryptions
        key_rotations: Number of key rotations
        ip_binding_violations: IP binding violations detected
    """
    sessions_created: int = 0
    sessions_validated: int = 0
    sessions_rejected: int = 0
    encryptions_performed: int = 0
    decryptions_performed: int = 0
    key_rotations: int = 0
    ip_binding_violations: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "sessions_created": self.sessions_created,
            "sessions_validated": self.sessions_validated,
            "sessions_rejected": self.sessions_rejected,
            "encryptions_performed": self.encryptions_performed,
            "decryptions_performed": self.decryptions_performed,
            "key_rotations": self.key_rotations,
            "ip_binding_violations": self.ip_binding_violations,
        }


class SessionSecurityError(Exception):
    """Exception raised for session security violations."""
    
    def __init__(self, message: str, session_id: Optional[str] = None, reason: str = ""):
        self.session_id = session_id
        self.reason = reason
        self.message = message
        super().__init__(self.message)


class SessionSecurity:
    """
    Secure session management.
    
    Provides session ID generation, validation, and optional encryption
    for session data at rest.
    
    Usage:
        security = SessionSecurity(
            config=SessionSecurityConfig(encryption_enabled=True),
            event_bus=event_bus
        )
        
        # Generate session ID
        session_id = security.generate_session_id()
        
        # Validate session ID
        if security.validate_session_id(session_id):
            # Session ID is valid
            pass
        
        # Encrypt session data (if enabled)
        encrypted = security.encrypt_session_data({"user": "data"})
        
        # Decrypt session data
        decrypted = security.decrypt_session_data(encrypted)
        
        # Rotate encryption keys
        security.rotate_keys()
    
    Attributes:
        config: SessionSecurityConfig instance
        event_bus: Optional EventBus for security alerts
    """
    
    def __init__(
        self,
        config: Optional[SessionSecurityConfig] = None,
        event_bus: Optional[EventBus] = None,
        encryption_key: Optional[bytes] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize SessionSecurity.
        
        Args:
            config: Configuration options
            event_bus: EventBus for emitting security alerts
            encryption_key: Optional encryption key (generated if not provided)
            logger: Optional logger instance
        """
        self._config = config or SessionSecurityConfig()
        self._event_bus = event_bus
        self._logger = logger or logging.getLogger(__name__)
        
        # Encryption key management
        self._encryption_key = encryption_key
        self._key_created_at: Optional[float] = None
        self._previous_key: Optional[bytes] = None  # For key rotation
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Statistics
        self._stats = SessionSecurityStats()
        
        # Initialize encryption if enabled
        if self._config.encryption_enabled:
            self._initialize_encryption()
    
    def _initialize_encryption(self) -> None:
        """Initialize encryption key if not provided."""
        if self._encryption_key is None:
            self._encryption_key = self._generate_encryption_key()
            self._key_created_at = time.time()
            self._logger.info("Generated new encryption key for session security")
    
    def _generate_encryption_key(self) -> bytes:
        """Generate a new encryption key."""
        # Generate 32 bytes (256 bits) for AES-256
        return os.urandom(32)
    
    def generate_session_id(self) -> str:
        """
        Generate a secure session ID.
        
        Returns:
            Secure session ID string
        """
        with self._lock:
            self._stats.sessions_created += 1
            
            if self._config.session_id_format == "uuid4":
                # Standard UUID4 format
                return str(uuid.uuid4())
            
            elif self._config.session_id_format == "uuid4_hashed":
                # Hashed UUID4 for additional security
                raw_uuid = uuid.uuid4()
                return hashlib.sha256(str(raw_uuid).encode()).hexdigest()
            
            elif self._config.session_id_format == "random_hex":
                # Random hex string with specified entropy
                bytes_needed = self._config.entropy_bits // 8
                return os.urandom(bytes_needed).hex()
            
            else:
                # Default to UUID4
                return str(uuid.uuid4())
    
    def validate_session_id(self, session_id: str) -> bool:
        """
        Validate a session ID.
        
        Args:
            session_id: Session ID to validate
            
        Returns:
            True if valid, False otherwise
        """
        with self._lock:
            self._stats.sessions_validated += 1
            
            if not session_id:
                self._stats.sessions_rejected += 1
                return False
            
            # Check format based on configured format
            if self._config.session_id_format == "uuid4":
                # Validate UUID4 format
                try:
                    parsed = uuid.UUID(session_id)
                    if parsed.version != 4:
                        self._stats.sessions_rejected += 1
                        self._emit_security_alert("invalid_session_version", session_id)
                        return False
                except ValueError:
                    self._stats.sessions_rejected += 1
                    self._emit_security_alert("invalid_session_format", session_id)
                    return False
            
            elif self._config.session_id_format == "uuid4_hashed":
                # Validate hex string (64 chars for SHA256)
                if len(session_id) != 64 or not all(c in '0123456789abcdef' for c in session_id.lower()):
                    self._stats.sessions_rejected += 1
                    self._emit_security_alert("invalid_hashed_session", session_id)
                    return False
            
            elif self._config.session_id_format == "random_hex":
                # Validate hex string with expected length
                expected_len = self._config.entropy_bits // 4
                if len(session_id) != expected_len or not all(c in '0123456789abcdef' for c in session_id.lower()):
                    self._stats.sessions_rejected += 1
                    self._emit_security_alert("invalid_random_session", session_id)
                    return False
            
            # Additional validation for enhanced security
            if self._config.security_level in (SessionSecurityLevel.ENHANCED, SessionSecurityLevel.ENCRYPTED):
                # Check for potential injection patterns
                if self._contains_suspicious_patterns(session_id):
                    self._stats.sessions_rejected += 1
                    self._emit_security_alert("suspicious_session_pattern", session_id)
                    return False
            
            return True
    
    def _contains_suspicious_patterns(self, session_id: str) -> bool:
        """Check for suspicious patterns in session ID."""
        suspicious_patterns = [
            '<', '>', '{', '}', '"', "'",  # Potential injection
            '..', '/', '\\',  # Path traversal
            '\x00', '\n', '\r',  # Control characters
        ]
        return any(pattern in session_id for pattern in suspicious_patterns)
    
    def encrypt_session_data(self, data: Dict[str, Any]) -> str:
        """
        Encrypt session data.
        
        Uses AES-256-GCM for authenticated encryption.
        
        Args:
            data: Session data to encrypt
            
        Returns:
            Base64-encoded encrypted data
            
        Raises:
            SessionSecurityError: If encryption fails or not enabled
        """
        if not self._config.encryption_enabled:
            raise SessionSecurityError("Encryption not enabled in configuration")
        
        with self._lock:
            try:
                # Import cryptography library (lazy import)
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                
                # Serialize data
                plaintext = json.dumps(data).encode('utf-8')
                
                # Generate nonce (12 bytes for GCM)
                nonce = os.urandom(12)
                
                # Encrypt
                aesgcm = AESGCM(self._encryption_key)
                ciphertext = aesgcm.encrypt(nonce, plaintext, None)
                
                # Combine nonce + ciphertext and encode
                encrypted = nonce + ciphertext
                encoded = base64.b64encode(encrypted).decode('utf-8')
                
                self._stats.encryptions_performed += 1
                
                return encoded
                
            except ImportError:
                # Fallback to simple encoding if cryptography not available
                self._logger.warning(
                    "cryptography library not available, using basic encoding"
                )
                return self._simple_encode(data)
            
            except Exception as e:
                self._logger.error(f"Encryption failed: {e}")
                raise SessionSecurityError(f"Encryption failed: {e}")
    
    def decrypt_session_data(self, encrypted_data: str) -> Dict[str, Any]:
        """
        Decrypt session data.
        
        Args:
            encrypted_data: Base64-encoded encrypted data
            
        Returns:
            Decrypted session data
            
        Raises:
            SessionSecurityError: If decryption fails or not enabled
        """
        if not self._config.encryption_enabled:
            raise SessionSecurityError("Encryption not enabled in configuration")
        
        with self._lock:
            try:
                # Import cryptography library (lazy import)
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                
                # Decode
                encrypted = base64.b64decode(encrypted_data.encode('utf-8'))
                
                # Extract nonce and ciphertext
                nonce = encrypted[:12]
                ciphertext = encrypted[12:]
                
                # Try current key first
                try:
                    aesgcm = AESGCM(self._encryption_key)
                    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
                except Exception:
                    # Try previous key (for key rotation)
                    if self._previous_key:
                        aesgcm = AESGCM(self._previous_key)
                        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
                    else:
                        raise
                
                # Deserialize
                data = json.loads(plaintext.decode('utf-8'))
                
                self._stats.decryptions_performed += 1
                
                return data
                
            except ImportError:
                # Fallback to simple decoding
                return self._simple_decode(encrypted_data)
            
            except Exception as e:
                self._logger.error(f"Decryption failed: {e}")
                raise SessionSecurityError(f"Decryption failed: {e}")
    
    def _simple_encode(self, data: Dict[str, Any]) -> str:
        """Simple encoding fallback when cryptography not available."""
        json_str = json.dumps(data)
        encoded = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
        return f"SIMPLE:{encoded}"
    
    def _simple_decode(self, encoded_data: str) -> Dict[str, Any]:
        """Simple decoding fallback when cryptography not available."""
        if encoded_data.startswith("SIMPLE:"):
            encoded = encoded_data[7:]
            json_str = base64.b64decode(encoded.encode('utf-8')).decode('utf-8')
            return json.loads(json_str)
        raise SessionSecurityError("Invalid encoding format")
    
    def rotate_keys(self) -> bool:
        """
        Rotate encryption keys.
        
        Generates a new key and stores the old key for decryption
        of existing sessions.
        
        Returns:
            True if rotation successful, False if encryption not enabled
        """
        if not self._config.encryption_enabled:
            return False
        
        with self._lock:
            # Store current key as previous
            self._previous_key = self._encryption_key
            
            # Generate new key
            self._encryption_key = self._generate_encryption_key()
            self._key_created_at = time.time()
            
            self._stats.key_rotations += 1
            
            self._logger.info("Encryption key rotated successfully")
            
            if self._config.enable_events and self._event_bus:
                event = Event(
                    event_type="SESSION_KEY_ROTATION",
                    data={
                        "timestamp": now_utc_iso(),
                        "previous_key_retained": self._previous_key is not None,
                    },
                    severity=EventSeverity.INFO,
                    source="SessionSecurity",
                )
                self._event_bus.emit(event)
            
            return True
    
    def should_rotate_key(self) -> bool:
        """
        Check if key rotation is due.
        
        Returns:
            True if rotation is due based on configured rotation period
        """
        if not self._config.encryption_enabled:
            return False
        
        if self._key_created_at is None:
            return True
        
        age_days = (time.time() - self._key_created_at) / (24 * 3600)
        return age_days >= self._config.key_rotation_days
    
    def create_session_hash(
        self,
        session_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> str:
        """
        Create a session binding hash.
        
        Creates a hash that can be used to verify session integrity.
        Optionally includes IP address for binding.
        
        Args:
            session_id: Session ID
            ip_address: Optional IP address for binding
            user_agent: Optional user agent for binding
            
        Returns:
            Session binding hash
        """
        data = session_id
        
        if self._config.ip_binding_enabled and ip_address:
            data += f":{ip_address}"
        
        if user_agent:
            data += f":{hashlib.sha256(user_agent.encode()).hexdigest()[:16]}"
        
        return hashlib.sha256(data.encode()).hexdigest()
    
    def validate_session_binding(
        self,
        session_id: str,
        stored_hash: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> bool:
        """
        Validate session binding.
        
        Args:
            session_id: Session ID
            stored_hash: Previously stored binding hash
            ip_address: Current IP address
            user_agent: Current user agent
            
        Returns:
            True if binding is valid, False otherwise
        """
        expected_hash = self.create_session_hash(session_id, ip_address, user_agent)
        
        if not hmac.compare_digest(expected_hash, stored_hash):
            if self._config.ip_binding_enabled:
                self._stats.ip_binding_violations += 1
                self._emit_security_alert("session_binding_violation", session_id)
            return False
        
        return True
    
    def get_session_expiry_time(self, created_at: str) -> Optional[str]:
        """
        Calculate session expiry time.
        
        Args:
            created_at: ISO format creation timestamp
            
        Returns:
            ISO format expiry timestamp or None if expiry check disabled
        """
        if not self._config.session_expiry_check:
            return None
        
        try:
            created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            expiry = created.timestamp() + (self._config.max_session_age_hours * 3600)
            return datetime.utcfromtimestamp(expiry).isoformat() + 'Z'
        except Exception:
            return None
    
    def is_session_expired(self, created_at: str) -> bool:
        """
        Check if session is expired.
        
        Args:
            created_at: ISO format creation timestamp
            
        Returns:
            True if session is expired, False otherwise
        """
        if not self._config.session_expiry_check:
            return False
        
        try:
            created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            age_hours = (datetime.now(created.tzinfo) - created).total_seconds() / 3600
            return age_hours > self._config.max_session_age_hours
        except Exception:
            return True
    
    def _emit_security_alert(self, alert_type: str, session_id: str) -> None:
        """Emit security alert event."""
        if not self._config.enable_events or not self._event_bus:
            return
        
        event = Event(
            event_type="SESSION_SECURITY_ALERT",
            data={
                "alert_type": alert_type,
                "session_id": session_id[:8] + "..." if len(session_id) > 8 else session_id,
                "timestamp": now_utc_iso(),
            },
            severity=EventSeverity.WARN,
            source="SessionSecurity",
        )
        self._event_bus.emit(event)
    
    def get_stats(self) -> SessionSecurityStats:
        """Get security statistics."""
        with self._lock:
            return self._stats
    
    def reset_stats(self) -> None:
        """Reset statistics."""
        with self._lock:
            self._stats = SessionSecurityStats()
    
    def set_event_bus(self, event_bus: EventBus) -> None:
        """Set EventBus for emitting events."""
        self._event_bus = event_bus
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        with self._lock:
            return {
                "config": self._config.to_dict(),
                "stats": self._stats.to_dict(),
                "encryption_enabled": self._config.encryption_enabled,
                "key_age_days": (time.time() - self._key_created_at) / (24 * 3600) if self._key_created_at else None,
            }


# Global instance
_global_session_security: Optional[SessionSecurity] = None


def get_session_security(
    config: Optional[Dict[str, Any]] = None,
    event_bus: Optional[EventBus] = None,
) -> SessionSecurity:
    """
    Get global SessionSecurity instance.
    
    Creates instance on first call, returns existing on subsequent calls.
    
    Args:
        config: Configuration dictionary (only used on first call)
        event_bus: EventBus instance (only used on first call)
        
    Returns:
        Global SessionSecurity instance
    """
    global _global_session_security
    if _global_session_security is None:
        security_config = None
        if config:
            security_config = SessionSecurityConfig(**config)
        _global_session_security = SessionSecurity(
            config=security_config,
            event_bus=event_bus,
        )
    return _global_session_security


def reset_session_security() -> None:
    """Reset global SessionSecurity instance."""
    global _global_session_security
    _global_session_security = None
