"""
Audit Signer for TITAN FUSE Protocol.

ITEM-ART-001 Implementation (v5.0.0):
- Configurable signing backends (HMAC, RSA, KMS)
- Ed25519 digital signatures for audit events
- Cryptographic proof of event authenticity
- Key generation and management
- Signature verification
- Key rotation support
- Fallback to HMAC if RSA/KMS unavailable

ITEM-SEC-05 Original Implementation:
- Ed25519 digital signatures for audit events
- Cryptographic proof of event authenticity
- Key generation and management
- Signature verification

Author: TITAN FUSE Team
Version: 5.0.0
"""

import os
import json
import hashlib
import hmac
import base64
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Dict, Tuple, Optional, List, Any
from datetime import datetime
from dataclasses import dataclass, field
import logging

# Try to import nacl for Ed25519
try:
    from nacl.signing import SigningKey, VerifyKey
    from nacl.exceptions import BadSignatureError
    NACL_AVAILABLE = True
except ImportError:
    NACL_AVAILABLE = False
    SigningKey = None
    VerifyKey = None
    BadSignatureError = Exception

# Try to import cryptography for RSA
try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


class SigningBackendType(Enum):
    """Available signing backend types."""
    HMAC = "hmac"
    RSA = "rsa"
    KMS = "kms"
    ED25519 = "ed25519"


class AuditSignerError(Exception):
    """Error in audit signing."""
    pass


class SigningBackend(ABC):
    """Abstract base class for signing backends."""
    
    @abstractmethod
    def sign(self, data: bytes) -> str:
        """
        Sign data and return signature.
        
        Args:
            data: Data to sign
            
        Returns:
            Signature as string (base64-encoded)
        """
        pass
    
    @abstractmethod
    def verify(self, data: bytes, signature: str) -> bool:
        """
        Verify a signature.
        
        Args:
            data: Original data
            signature: Signature to verify
            
        Returns:
            True if signature is valid
        """
        pass
    
    def get_backend_type(self) -> str:
        """Get the backend type identifier."""
        return self.__class__.__name__.replace('Backend', '').lower()
    
    def get_key_id(self) -> Optional[str]:
        """Get the public key identifier for this backend."""
        return None


class HMACBackend(SigningBackend):
    """
    HMAC-SHA256 signing backend.
    
    Simple and fast signing using a shared secret.
    Suitable for non-repudiation within trusted environments.
    """
    
    def __init__(self, secret: str = None, secret_path: str = None):
        """
        Initialize HMAC backend.
        
        Args:
            secret: Shared secret string
            secret_path: Path to file containing secret
        """
        self._logger = logging.getLogger(__name__)
        
        if secret:
            self._secret = secret.encode('utf-8')
        elif secret_path:
            secret_path = Path(secret_path)
            if secret_path.exists():
                with open(secret_path, 'r') as f:
                    self._secret = f.read().strip().encode('utf-8')
            else:
                # Generate new secret
                self._secret = os.urandom(32)
                secret_path.parent.mkdir(parents=True, exist_ok=True)
                with open(secret_path, 'w') as f:
                    f.write(base64.b64encode(self._secret).decode('ascii'))
                self._logger.info(f"[ITEM-ART-001] Generated new HMAC secret at {secret_path}")
        else:
            # Generate ephemeral secret
            self._secret = os.urandom(32)
            self._logger.warning("[ITEM-ART-001] Using ephemeral HMAC secret (not persisted)")
    
    def sign(self, data: bytes) -> str:
        """Sign data with HMAC-SHA256."""
        signature = hmac.new(self._secret, data, hashlib.sha256).digest()
        return base64.b64encode(signature).decode('ascii')
    
    def verify(self, data: bytes, signature: str) -> bool:
        """Verify HMAC signature."""
        try:
            expected = base64.b64decode(signature)
            actual = hmac.new(self._secret, data, hashlib.sha256).digest()
            return hmac.compare_digest(expected, actual)
        except Exception:
            return False
    
    def rotate_key(self, new_secret: str = None) -> str:
        """
        Rotate the signing key.
        
        Args:
            new_secret: New secret (generated if not provided)
            
        Returns:
            New secret as base64 string
        """
        if new_secret:
            self._secret = new_secret.encode('utf-8')
        else:
            self._secret = os.urandom(32)
        
        self._logger.info("[ITEM-ART-001] HMAC key rotated")
        return base64.b64encode(self._secret).decode('ascii')


class RSABackend(SigningBackend):
    """
    RSA-2048 signing backend.
    
    Uses RSA-PSS with SHA-256 for signatures.
    Provides non-repudiation with public/private key pairs.
    """
    
    def __init__(self, private_key_path: str = None, public_key_path: str = None,
                 private_key: bytes = None, public_key: bytes = None):
        """
        Initialize RSA backend.
        
        Args:
            private_key_path: Path to private key PEM file
            public_key_path: Path to public key PEM file
            private_key: Private key bytes (PEM format)
            public_key: Public key bytes (PEM format)
        """
        self._logger = logging.getLogger(__name__)
        self._private_key = None
        self._public_key = None
        self._key_id = None
        
        if not CRYPTO_AVAILABLE:
            raise AuditSignerError(
                "cryptography not installed. Install with: pip install cryptography"
            )
        
        # Load from paths
        if private_key_path and Path(private_key_path).exists():
            self._load_private_key(Path(private_key_path))
            self._key_id = self._compute_key_id(Path(private_key_path))
        
        if public_key_path and Path(public_key_path).exists():
            self._load_public_key(Path(public_key_path))
        
        # Load from bytes
        if private_key:
            self._private_key = serialization.load_pem_private_key(
                private_key, password=None, backend=default_backend()
            )
            self._public_key = self._private_key.public_key()
        
        if public_key and not self._public_key:
            self._public_key = serialization.load_pem_public_key(
                public_key, backend=default_backend()
            )
    
    def _load_private_key(self, path: Path) -> None:
        """Load private key from file."""
        with open(path, 'rb') as f:
            self._private_key = serialization.load_pem_private_key(
                f.read(), password=None, backend=default_backend()
            )
            self._public_key = self._private_key.public_key()
    
    def _load_public_key(self, path: Path) -> None:
        """Load public key from file."""
        with open(path, 'rb') as f:
            self._public_key = serialization.load_pem_public_key(
                f.read(), backend=default_backend()
            )
    
    def _compute_key_id(self, path: Path) -> str:
        """Compute a key ID from the key file."""
        stat = path.stat()
        return f"rsa-{stat.st_size}-{int(stat.st_mtime)}"
    
    def sign(self, data: bytes) -> str:
        """Sign data with RSA-PSS-SHA256."""
        if not self._private_key:
            raise AuditSignerError("No private key loaded for signing")
        
        signature = self._private_key.sign(
            data,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('ascii')
    
    def verify(self, data: bytes, signature: str) -> bool:
        """Verify RSA signature."""
        if not self._public_key:
            raise AuditSignerError("No public key loaded for verification")
        
        try:
            sig_bytes = base64.b64decode(signature)
            self._public_key.verify(
                sig_bytes,
                data,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            return True
        except Exception as e:
            self._logger.debug(f"[ITEM-ART-001] RSA verification failed: {e}")
            return False
    
    def generate_keypair(self, private_key_path: str = None, 
                         public_key_path: str = None) -> Tuple[bytes, bytes]:
        """
        Generate a new RSA keypair.
        
        Args:
            private_key_path: Optional path to save private key
            public_key_path: Optional path to save public key
            
        Returns:
            Tuple of (private_key_pem, public_key_pem) bytes
        """
        # Generate 2048-bit RSA key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        public_key = private_key.public_key()
        
        # Serialize keys
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        # Save to files if paths provided
        if private_key_path:
            path = Path(private_key_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'wb') as f:
                f.write(private_pem)
            try:
                os.chmod(path, 0o600)
            except:
                pass
        
        if public_key_path:
            path = Path(public_key_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'wb') as f:
                f.write(public_pem)
        
        # Update instance
        self._private_key = private_key
        self._public_key = public_key
        
        if private_key_path:
            self._key_id = self._compute_key_id(Path(private_key_path))
        
        self._logger.info("[ITEM-ART-001] Generated new RSA keypair")
        return private_pem, public_pem
    
    def get_key_id(self) -> Optional[str]:
        """Get the key identifier."""
        return self._key_id


class KMSBackend(SigningBackend):
    """
    External Key Management Service signing backend.
    
    Supports integration with cloud KMS services (AWS KMS, GCP KMS, etc.)
    for enterprise key management.
    """
    
    def __init__(self, kms_endpoint: str = None, key_id: str = None,
                 api_key: str = None, timeout: int = 30):
        """
        Initialize KMS backend.
        
        Args:
            kms_endpoint: URL of the KMS service
            key_id: Key identifier in the KMS
            api_key: API key for authentication
            timeout: Request timeout in seconds
        """
        self._logger = logging.getLogger(__name__)
        self._endpoint = kms_endpoint
        self._key_id = key_id
        self._api_key = api_key
        self._timeout = timeout
        self._public_key = None
        
        # Check if we have enough configuration
        if kms_endpoint and key_id:
            self._available = True
            self._logger.info(f"[ITEM-ART-001] KMS backend configured for {kms_endpoint}")
        else:
            self._available = False
            self._logger.warning(
                "[ITEM-ART-001] KMS backend not fully configured. "
                "Provide kms_endpoint and key_id."
            )
    
    def is_available(self) -> bool:
        """Check if KMS is available and configured."""
        return self._available
    
    def sign(self, data: bytes) -> str:
        """Sign data via KMS API."""
        if not self._available:
            raise AuditSignerError("KMS backend not configured")
        
        # In production, this would make an HTTP request to the KMS
        # For now, we implement a placeholder that can be extended
        try:
            import urllib.request
            import urllib.error
            
            request_data = {
                'key_id': self._key_id,
                'data': base64.b64encode(data).decode('ascii')
            }
            
            req = urllib.request.Request(
                f"{self._endpoint}/sign",
                data=json.dumps(request_data).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {self._api_key}'
                },
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=self._timeout) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result['signature']
                
        except Exception as e:
            self._logger.error(f"[ITEM-ART-001] KMS signing failed: {e}")
            raise AuditSignerError(f"KMS signing failed: {e}")
    
    def verify(self, data: bytes, signature: str) -> bool:
        """Verify signature via KMS API."""
        if not self._available:
            raise AuditSignerError("KMS backend not configured")
        
        try:
            import urllib.request
            
            request_data = {
                'key_id': self._key_id,
                'data': base64.b64encode(data).decode('ascii'),
                'signature': signature
            }
            
            req = urllib.request.Request(
                f"{self._endpoint}/verify",
                data=json.dumps(request_data).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {self._api_key}'
                },
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=self._timeout) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result.get('valid', False)
                
        except Exception as e:
            self._logger.error(f"[ITEM-ART-001] KMS verification failed: {e}")
            return False
    
    def get_key_id(self) -> Optional[str]:
        """Get the KMS key identifier."""
        return self._key_id


class Ed25519Backend(SigningBackend):
    """
    Ed25519 signing backend using PyNaCl.
    
    Provides high-performance digital signatures with small key sizes.
    This is the original signing method from ITEM-SEC-05.
    """
    
    KEY_SIZE = 32  # Ed25519 key size
    SIGNATURE_SIZE = 64  # Ed25519 signature size
    
    def __init__(self, key_path: str = None, passphrase: str = None):
        """
        Initialize Ed25519 backend.
        
        Args:
            key_path: Path to key file
            passphrase: Optional passphrase for encrypted key
        """
        self._logger = logging.getLogger(__name__)
        self._signing_key = None
        self._verify_key = None
        
        if not NACL_AVAILABLE:
            raise AuditSignerError(
                "pynacl not installed. Install with: pip install pynacl"
            )
        
        if key_path and Path(key_path).exists():
            self.load_keypair(Path(key_path), passphrase)
    
    def generate_keypair(self) -> Tuple[bytes, bytes]:
        """
        Generate a new Ed25519 keypair.
        
        Returns:
            Tuple of (private_key, public_key) bytes
        """
        self._signing_key = SigningKey.generate()
        self._verify_key = self._signing_key.verify_key
        
        private_key = bytes(self._signing_key)
        public_key = bytes(self._verify_key)
        
        self._logger.info("[ITEM-ART-001] Generated new Ed25519 keypair")
        return private_key, public_key
    
    def load_keypair(self, key_path: Path, passphrase: str = None) -> None:
        """Load keypair from file."""
        with open(key_path, 'rb') as f:
            key_data = f.read()
        
        if passphrase:
            key = hashlib.sha256(passphrase.encode()).digest()
            key_data = bytes(a ^ b for a, b in zip(key_data, key * (len(key_data) // 32 + 1)))
        
        self._signing_key = SigningKey(key_data[:self.KEY_SIZE])
        self._verify_key = self._signing_key.verify_key
        self._logger.info(f"[ITEM-ART-001] Loaded Ed25519 keypair from {key_path}")
    
    def save_keypair(self, key_path: Path, passphrase: str = None) -> None:
        """Save keypair to file."""
        if self._signing_key is None:
            raise AuditSignerError("No keypair loaded")
        
        key_data = bytes(self._signing_key)
        
        if passphrase:
            key = hashlib.sha256(passphrase.encode()).digest()
            key_data = bytes(a ^ b for a, b in zip(key_data, key * (len(key_data) // 32 + 1)))
        
        key_path.parent.mkdir(parents=True, exist_ok=True)
        with open(key_path, 'wb') as f:
            f.write(key_data)
        
        try:
            os.chmod(key_path, 0o600)
        except:
            pass
        
        self._logger.info(f"[ITEM-ART-001] Saved Ed25519 keypair to {key_path}")
    
    def sign(self, data: bytes) -> str:
        """Sign data with Ed25519."""
        if self._signing_key is None:
            raise AuditSignerError("No signing key loaded")
        
        signed = self._signing_key.sign(data)
        return base64.b64encode(signed.signature).decode('ascii')
    
    def verify(self, data: bytes, signature: str) -> bool:
        """Verify Ed25519 signature."""
        if self._verify_key is None:
            raise AuditSignerError("No verify key loaded")
        
        try:
            sig_bytes = base64.b64decode(signature)
            self._verify_key.verify(data, sig_bytes)
            return True
        except BadSignatureError:
            return False
        except Exception as e:
            self._logger.debug(f"[ITEM-ART-001] Ed25519 verification failed: {e}")
            return False
    
    def get_public_key(self) -> Optional[bytes]:
        """Get the public key bytes."""
        if self._verify_key:
            return bytes(self._verify_key)
        return None
    
    def get_key_id(self) -> Optional[str]:
        """Get public key as hex string for identification."""
        pk = self.get_public_key()
        if pk:
            return f"ed25519-{pk.hex()[:16]}"
        return None


# ============================================================================
# Data Structures for Audit Trail
# ============================================================================

@dataclass
class AuditEventV2:
    """
    Enhanced audit event for ITEM-ART-001.
    
    Version 2 adds session tracking and checksum support.
    """
    event_id: str
    event_type: str
    timestamp: str
    session_id: str
    data: Dict[str, Any]
    previous_hash: str = ""
    event_hash: str = ""
    signature: str = ""
    
    def compute_hash(self) -> str:
        """Compute SHA-256 hash of event."""
        content = json.dumps({
            'event_id': self.event_id,
            'event_type': self.event_type,
            'timestamp': self.timestamp,
            'session_id': self.session_id,
            'data': self.data,
            'previous_hash': self.previous_hash
        }, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'event_id': self.event_id,
            'event_type': self.event_type,
            'timestamp': self.timestamp,
            'session_id': self.session_id,
            'data': self.data,
            'previous_hash': self.previous_hash,
            'event_hash': self.event_hash,
            'signature': self.signature
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'AuditEventV2':
        """Create from dictionary."""
        return cls(
            event_id=data['event_id'],
            event_type=data['event_type'],
            timestamp=data['timestamp'],
            session_id=data.get('session_id', ''),
            data=data['data'],
            previous_hash=data.get('previous_hash', ''),
            event_hash=data.get('event_hash', ''),
            signature=data.get('signature', '')
        )


@dataclass
class AuditTrailV2:
    """
    Enhanced audit trail for ITEM-ART-001.
    
    Includes checksum and session tracking.
    """
    trail_id: str
    session_id: str
    events: List[AuditEventV2] = field(default_factory=list)
    created_at: str = ""
    checksum: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat() + "Z"
        if not self.trail_id:
            import uuid
            self.trail_id = f"trail-{uuid.uuid4().hex[:12]}"
    
    def add_event(self, event: AuditEventV2) -> None:
        """Add an event to the trail."""
        if self.events:
            event.previous_hash = self.events[-1].event_hash
        event.event_hash = event.compute_hash()
        self.events.append(event)
        self.checksum = self._compute_checksum()
    
    def _compute_checksum(self) -> str:
        """Compute checksum of all events."""
        if not self.events:
            return ""
        content = json.dumps([e.event_hash for e in self.events], sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'trail_id': self.trail_id,
            'session_id': self.session_id,
            'events': [e.to_dict() for e in self.events],
            'created_at': self.created_at,
            'checksum': self.checksum
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'AuditTrailV2':
        """Create from dictionary."""
        events = [AuditEventV2.from_dict(e) for e in data.get('events', [])]
        return cls(
            trail_id=data['trail_id'],
            session_id=data['session_id'],
            events=events,
            created_at=data.get('created_at', ''),
            checksum=data.get('checksum', '')
        )


@dataclass
class SignedTrail:
    """
    Signed audit trail for ITEM-ART-001.
    
    Contains the trail and its cryptographic signature.
    """
    trail: AuditTrailV2
    signature: str
    signed_at: str
    backend_type: str
    public_key_id: Optional[str] = None
    
    def __post_init__(self):
        if not self.signed_at:
            self.signed_at = datetime.utcnow().isoformat() + "Z"
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            'trail': self.trail.to_dict(),
            'signature': self.signature,
            'signed_at': self.signed_at,
            'backend_type': self.backend_type,
            'public_key_id': self.public_key_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SignedTrail':
        """Create from dictionary."""
        return cls(
            trail=AuditTrailV2.from_dict(data['trail']),
            signature=data['signature'],
            signed_at=data['signed_at'],
            backend_type=data['backend_type'],
            public_key_id=data.get('public_key_id')
        )


# ============================================================================
# Main AuditSigner Class
# ============================================================================

class AuditSigner:
    """
    Configurable audit signer with multiple backend support.
    
    ITEM-ART-001: Supports HMAC, RSA, Ed25519, and KMS backends.
    Falls back to HMAC if preferred backend is unavailable.
    
    Features:
    - Configurable signing backends
    - Automatic fallback
    - Key rotation support
    - Trail signing and verification
    - Public key export for verification
    
    Usage:
        # With HMAC (simplest)
        signer = AuditSigner(backend_type='hmac', secret='my-secret')
        
        # With RSA
        signer = AuditSigner(backend_type='rsa', 
                           private_key_path='.titan/audit_private.pem',
                           public_key_path='.titan/audit_public.pem')
        
        # Sign a trail
        signed_trail = signer.sign_trail(trail)
        
        # Verify a trail
        is_valid = signer.verify_trail(signed_trail)
    """
    
    # Events that require cryptographic signatures
    CRITICAL_EVENTS = [
        'GATE_PASS',
        'GATE_FAIL',
        'CHECKPOINT_SAVE',
        'CREDENTIAL_ACCESS',
        'SESSION_ABORT',
        'BUDGET_EXCEEDED'
    ]
    
    def __init__(self, config: Dict = None, backend_type: str = None, **kwargs):
        """
        Initialize audit signer.
        
        Args:
            config: Configuration dictionary (from config.yaml)
            backend_type: Override backend type ('hmac', 'rsa', 'kms', 'ed25519')
            **kwargs: Additional arguments passed to backend constructor
        """
        self.config = config or {}
        self._logger = logging.getLogger(__name__)
        self._backend: Optional[SigningBackend] = None
        self._fallback_backend: Optional[SigningBackend] = None
        
        # Determine backend type
        audit_config = self.config.get('audit', {})
        if backend_type:
            backend_name = backend_type
        else:
            backend_name = audit_config.get('backend', 'hmac')
        
        # Initialize the primary backend
        self._init_backend(backend_name, kwargs)
        
        # Initialize fallback (always HMAC for reliability)
        if backend_name != 'hmac':
            self._init_fallback_backend()
    
    def _init_backend(self, backend_type: str, kwargs: Dict) -> None:
        """Initialize the primary signing backend."""
        audit_config = self.config.get('audit', {})
        
        try:
            if backend_type == 'hmac':
                secret = kwargs.get('secret') or audit_config.get('hmac', {}).get('secret')
                secret_path = audit_config.get('hmac', {}).get('secret_path', '.titan/hmac_secret')
                self._backend = HMACBackend(secret=secret, secret_path=secret_path)
                self._logger.info(f"[ITEM-ART-001] Initialized HMAC backend")
                
            elif backend_type == 'rsa':
                rsa_config = audit_config.get('rsa', {})
                private_path = rsa_config.get('private_key_path', '.titan/audit_private.pem')
                public_path = rsa_config.get('public_key_path', '.titan/audit_public.pem')
                
                # Check if keys exist, generate if not
                if not Path(private_path).exists():
                    self._logger.info(f"[ITEM-ART-001] RSA keys not found, generating new keypair")
                    rsa_backend = RSABackend()
                    rsa_backend.generate_keypair(private_path, public_path)
                    self._backend = rsa_backend
                else:
                    self._backend = RSABackend(
                        private_key_path=private_path,
                        public_key_path=public_path
                    )
                self._logger.info(f"[ITEM-ART-001] Initialized RSA backend")
                
            elif backend_type == 'kms':
                kms_config = audit_config.get('kms', {})
                self._backend = KMSBackend(
                    kms_endpoint=kms_config.get('endpoint'),
                    key_id=kms_config.get('key_id'),
                    api_key=kms_config.get('api_key')
                )
                if not self._backend.is_available():
                    self._logger.warning(
                        "[ITEM-ART-001] KMS backend not available, will use fallback"
                    )
                else:
                    self._logger.info("[ITEM-ART-001] Initialized KMS backend")
                    
            elif backend_type == 'ed25519':
                key_path = audit_config.get('signing_key_path', '.titan/audit_key')
                passphrase = kwargs.get('passphrase')
                
                ed_backend = Ed25519Backend()
                if Path(key_path).exists():
                    ed_backend.load_keypair(Path(key_path), passphrase)
                else:
                    ed_backend.generate_keypair()
                    ed_backend.save_keypair(Path(key_path), passphrase)
                self._backend = ed_backend
                self._logger.info("[ITEM-ART-001] Initialized Ed25519 backend")
                
            else:
                raise AuditSignerError(f"Unknown backend type: {backend_type}")
                
        except AuditSignerError:
            raise
        except Exception as e:
            self._logger.error(f"[ITEM-ART-001] Failed to initialize {backend_type} backend: {e}")
            self._backend = None
    
    def _init_fallback_backend(self) -> None:
        """Initialize HMAC fallback backend."""
        try:
            self._fallback_backend = HMACBackend(
                secret_path='.titan/hmac_fallback_secret'
            )
            self._logger.info("[ITEM-ART-001] Initialized HMAC fallback backend")
        except Exception as e:
            self._logger.warning(f"[ITEM-ART-001] Failed to initialize fallback: {e}")
    
    def _get_backend(self) -> SigningBackend:
        """Get the active backend, falling back if necessary."""
        if self._backend:
            return self._backend
        if self._fallback_backend:
            self._logger.warning("[ITEM-ART-001] Using fallback backend")
            return self._fallback_backend
        # Last resort: create ephemeral HMAC
        self._fallback_backend = HMACBackend()
        return self._fallback_backend
    
    def sign(self, data: bytes) -> str:
        """Sign data using the configured backend."""
        return self._get_backend().sign(data)
    
    def sign_dict(self, data: Dict) -> str:
        """Sign a dictionary using canonical JSON serialization."""
        json_bytes = json.dumps(data, sort_keys=True, default=str).encode('utf-8')
        return self.sign(json_bytes)
    
    def verify(self, data: bytes, signature: str, backend_type: str = None) -> bool:
        """
        Verify a signature.
        
        Args:
            data: Original data
            signature: Signature to verify
            backend_type: Specific backend to use (uses primary if not specified)
            
        Returns:
            True if signature is valid
        """
        backend = self._get_backend()
        return backend.verify(data, signature)
    
    def verify_dict(self, data: Dict, signature: str) -> bool:
        """Verify a dictionary signature."""
        json_bytes = json.dumps(data, sort_keys=True, default=str).encode('utf-8')
        return self.verify(json_bytes, signature)
    
    def sign_trail(self, trail: AuditTrailV2) -> SignedTrail:
        """
        Sign an audit trail.
        
        Args:
            trail: AuditTrailV2 to sign
            
        Returns:
            SignedTrail with signature
        """
        backend = self._get_backend()
        
        # Serialize trail for signing
        trail_data = json.dumps(trail.to_dict(), sort_keys=True, default=str).encode('utf-8')
        
        # Sign
        signature = backend.sign(trail_data)
        
        # Get key ID if available
        key_id = backend.get_key_id() if hasattr(backend, 'get_key_id') else None
        
        signed_trail = SignedTrail(
            trail=trail,
            signature=signature,
            signed_at=datetime.utcnow().isoformat() + "Z",
            backend_type=backend.get_backend_type(),
            public_key_id=key_id
        )
        
        self._logger.info(
            f"[ITEM-ART-001] Signed trail {trail.trail_id} with {backend.get_backend_type()} backend"
        )
        
        return signed_trail
    
    def verify_trail(self, signed: SignedTrail) -> bool:
        """
        Verify a signed audit trail.
        
        Args:
            signed: SignedTrail to verify
            
        Returns:
            True if signature is valid
        """
        backend = self._get_backend()
        
        # Serialize trail for verification
        trail_data = json.dumps(signed.trail.to_dict(), sort_keys=True, default=str).encode('utf-8')
        
        return backend.verify(trail_data, signed.signature)
    
    def rotate_key(self) -> Dict[str, Any]:
        """
        Rotate the signing key.
        
        Returns:
            Dictionary with rotation details
        """
        backend = self._get_backend()
        
        if isinstance(backend, HMACBackend):
            new_secret = backend.rotate_key()
            self._logger.info("[ITEM-ART-001] Key rotation completed for HMAC backend")
            return {
                'backend': 'hmac',
                'new_key_id': None,
                'rotated_at': datetime.utcnow().isoformat() + "Z"
            }
        elif isinstance(backend, RSABackend):
            # Generate new keypair
            private_path = self.config.get('audit', {}).get('rsa', {}).get(
                'private_key_path', '.titan/audit_private.pem'
            )
            public_path = self.config.get('audit', {}).get('rsa', {}).get(
                'public_key_path', '.titan/audit_public.pem'
            )
            backend.generate_keypair(private_path, public_path)
            self._logger.info("[ITEM-ART-001] Key rotation completed for RSA backend")
            return {
                'backend': 'rsa',
                'new_key_id': backend.get_key_id(),
                'rotated_at': datetime.utcnow().isoformat() + "Z"
            }
        elif isinstance(backend, Ed25519Backend):
            backend.generate_keypair()
            key_path = self.config.get('audit', {}).get('signing_key_path', '.titan/audit_key')
            if key_path:
                backend.save_keypair(Path(key_path))
            self._logger.info("[ITEM-ART-001] Key rotation completed for Ed25519 backend")
            return {
                'backend': 'ed25519',
                'new_key_id': backend.get_key_id(),
                'rotated_at': datetime.utcnow().isoformat() + "Z"
            }
        else:
            self._logger.warning("[ITEM-ART-001] Key rotation not supported for current backend")
            return {
                'backend': backend.get_backend_type(),
                'supported': False
            }
    
    def get_backend_type(self) -> str:
        """Get the current backend type."""
        return self._get_backend().get_backend_type()
    
    def get_public_key_id(self) -> Optional[str]:
        """Get the public key identifier for verification."""
        backend = self._get_backend()
        if hasattr(backend, 'get_key_id'):
            return backend.get_key_id()
        return None
    
    def is_critical_event(self, event_type: str) -> bool:
        """Check if an event type requires signing."""
        return event_type in self.CRITICAL_EVENTS
    
    @staticmethod
    def is_available() -> bool:
        """Check if signing is available."""
        return True  # HMAC is always available


# ============================================================================
# Factory and Utility Functions
# ============================================================================

def create_audit_signer(config: Dict = None, backend_type: str = None) -> AuditSigner:
    """
    Factory function to create a configured audit signer.
    
    Args:
        config: Configuration dictionary
        backend_type: Override backend type
        
    Returns:
        Configured AuditSigner instance
    """
    return AuditSigner(config=config, backend_type=backend_type)


def sign_audit_event(event: Dict, signer: AuditSigner = None) -> Dict:
    """
    Sign an audit event.
    
    Args:
        event: Event dictionary
        signer: AuditSigner instance (creates new if not provided)
        
    Returns:
        Event with signature added
    """
    if signer is None:
        signer = AuditSigner()
    
    signed_event = event.copy()
    signature = signer.sign_dict(event)
    signed_event['signature'] = signature
    signed_event['signed_at'] = datetime.utcnow().isoformat() + 'Z'
    signed_event['backend_type'] = signer.get_backend_type()
    
    return signed_event


def verify_audit_event(event: Dict, signer: AuditSigner = None) -> bool:
    """
    Verify an audit event signature.
    
    Args:
        event: Event dictionary with signature
        signer: AuditSigner instance
        
    Returns:
        True if signature is valid
    """
    signature = event.get('signature')
    if not signature:
        return False
    
    # Create event copy without signature fields
    event_copy = {k: v for k, v in event.items() 
                  if k not in ('signature', 'signed_at', 'backend_type')}
    
    if signer is None:
        signer = AuditSigner()
    
    return signer.verify_dict(event_copy, signature)


def generate_audit_trail(session_id: str, events: List[Dict], 
                         signer: AuditSigner = None) -> AuditTrailV2:
    """
    Generate an audit trail from events.
    
    Args:
        session_id: Session identifier
        events: List of event dictionaries
        signer: Optional signer for critical events
        
    Returns:
        AuditTrailV2 instance
    """
    import uuid
    
    trail = AuditTrailV2(
        trail_id=f"trail-{uuid.uuid4().hex[:12]}",
        session_id=session_id
    )
    
    for event_data in events:
        event = AuditEventV2(
            event_id=event_data.get('event_id', f"evt-{uuid.uuid4().hex[:8]}"),
            event_type=event_data.get('type', 'UNKNOWN'),
            timestamp=event_data.get('timestamp', datetime.utcnow().isoformat() + "Z"),
            session_id=session_id,
            data=event_data.get('data', {})
        )
        trail.add_event(event)
    
    return trail


def write_signed_trail(signed_trail: SignedTrail, path: str) -> None:
    """
    Write a signed trail to a file.
    
    Args:
        signed_trail: SignedTrail to write
        path: File path
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, 'w') as f:
        json.dump(signed_trail.to_dict(), f, indent=2, default=str)


def read_signed_trail(path: str) -> SignedTrail:
    """
    Read a signed trail from a file.
    
    Args:
        path: File path
        
    Returns:
        SignedTrail instance
    """
    with open(path, 'r') as f:
        data = json.load(f)
    
    return SignedTrail.from_dict(data)
