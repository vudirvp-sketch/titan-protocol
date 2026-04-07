"""
Audit Signer for TITAN FUSE Protocol.

ITEM-SEC-05 Implementation:
- Ed25519 digital signatures for audit events
- Cryptographic proof of event authenticity
- Key generation and management
- Signature verification

Author: TITAN FUSE Team
Version: 3.3.0
"""

import os
import json
import hashlib
from pathlib import Path
from typing import Dict, Tuple, Optional
from datetime import datetime
import logging
import base64

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


class AuditSignerError(Exception):
    """Error in audit signing."""
    pass


class AuditSigner:
    """
    Ed25519-based signer for audit events.
    
    Provides cryptographic signatures for critical audit events,
    ensuring tamper-evidence and authenticity verification.
    
    Features:
    - Ed25519 digital signatures
    - Key generation and persistence
    - Event signing and verification
    - Public key export for verification
    
    Requirements:
        pip install pynacl
    
    Usage:
        signer = AuditSigner()
        
        # Generate or load key
        signer.generate_keypair()
        # or
        signer.load_keypair(key_path)
        
        # Sign event
        signature = signer.sign(event_data)
        
        # Verify signature
        is_valid = signer.verify(event_data, signature, public_key)
    """
    
    KEY_SIZE = 32  # Ed25519 key size
    SIGNATURE_SIZE = 64  # Ed25519 signature size
    
    def __init__(self, config: Dict = None):
        """
        Initialize audit signer.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        self._logger = logging.getLogger(__name__)
        self._signing_key: Optional[SigningKey] = None
        self._verify_key: Optional[VerifyKey] = None
    
    def generate_keypair(self) -> Tuple[bytes, bytes]:
        """
        Generate a new Ed25519 keypair.
        
        Returns:
            Tuple of (private_key, public_key) bytes
        """
        if not NACL_AVAILABLE:
            raise AuditSignerError(
                "pynacl not installed. Install with: pip install pynacl"
            )
        
        # Generate random signing key
        self._signing_key = SigningKey.generate()
        self._verify_key = self._signing_key.verify_key
        
        # Encode keys
        private_key = bytes(self._signing_key)
        public_key = bytes(self._verify_key)
        
        self._logger.info("Generated new Ed25519 keypair")
        
        return private_key, public_key
    
    def load_keypair(self, key_path: Path, passphrase: str = None) -> None:
        """
        Load keypair from file.
        
        Args:
            key_path: Path to key file
            passphrase: Optional passphrase for encrypted key
        """
        if not NACL_AVAILABLE:
            raise AuditSignerError(
                "pynacl not installed. Install with: pip install pynacl"
            )
        
        if not key_path.exists():
            raise AuditSignerError(f"Key file not found: {key_path}")
        
        try:
            with open(key_path, 'rb') as f:
                key_data = f.read()
            
            # Check if encrypted
            if passphrase:
                # Decrypt with passphrase (simplified - use proper encryption in production)
                import hashlib
                key = hashlib.sha256(passphrase.encode()).digest()
                # XOR decryption (simplified)
                key_data = bytes(a ^ b for a, b in zip(key_data, key * (len(key_data) // 32 + 1)))
            
            # Load signing key
            self._signing_key = SigningKey(key_data[:self.KEY_SIZE])
            self._verify_key = self._signing_key.verify_key
            
            self._logger.info(f"Loaded keypair from {key_path}")
            
        except Exception as e:
            raise AuditSignerError(f"Failed to load keypair: {e}")
    
    def save_keypair(self, key_path: Path, passphrase: str = None) -> None:
        """
        Save keypair to file.
        
        Args:
            key_path: Path to save key file
            passphrase: Optional passphrase to encrypt key
        """
        if self._signing_key is None:
            raise AuditSignerError("No keypair loaded")
        
        try:
            key_data = bytes(self._signing_key)
            
            # Encrypt if passphrase provided
            if passphrase:
                import hashlib
                key = hashlib.sha256(passphrase.encode()).digest()
                # XOR encryption (simplified - use proper encryption in production)
                key_data = bytes(a ^ b for a, b in zip(key_data, key * (len(key_data) // 32 + 1)))
            
            key_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Set restrictive permissions
            with open(key_path, 'wb') as f:
                f.write(key_data)
            
            try:
                os.chmod(key_path, 0o600)  # Owner read/write only
            except:
                pass
            
            self._logger.info(f"Saved keypair to {key_path}")
            
        except Exception as e:
            raise AuditSignerError(f"Failed to save keypair: {e}")
    
    def sign(self, data: bytes) -> str:
        """
        Sign data with Ed25519.
        
        Args:
            data: Data to sign
            
        Returns:
            Base64-encoded signature
        """
        if not NACL_AVAILABLE:
            raise AuditSignerError("pynacl not installed")
        
        if self._signing_key is None:
            raise AuditSignerError("No signing key loaded")
        
        # Sign the data
        signed = self._signing_key.sign(data)
        signature = signed.signature
        
        # Return base64 encoded
        return base64.b64encode(signature).decode('ascii')
    
    def sign_dict(self, data: Dict) -> str:
        """
        Sign a dictionary.
        
        Args:
            data: Dictionary to sign
            
        Returns:
            Base64-encoded signature
        """
        # Canonical JSON serialization
        json_bytes = json.dumps(data, sort_keys=True, default=str).encode('utf-8')
        return self.sign(json_bytes)
    
    def verify(self, data: bytes, signature: str, public_key: bytes = None) -> bool:
        """
        Verify a signature.
        
        Args:
            data: Original data
            signature: Base64-encoded signature
            public_key: Public key bytes (uses loaded key if not provided)
            
        Returns:
            True if signature is valid
        """
        if not NACL_AVAILABLE:
            raise AuditSignerError("pynacl not installed")
        
        try:
            # Decode signature
            sig_bytes = base64.b64decode(signature)
            
            # Get verify key
            if public_key:
                verify_key = VerifyKey(public_key)
            elif self._verify_key:
                verify_key = self._verify_key
            else:
                raise AuditSignerError("No public key available")
            
            # Verify
            verify_key.verify(data, sig_bytes)
            return True
            
        except BadSignatureError:
            return False
        except Exception as e:
            self._logger.error(f"Signature verification error: {e}")
            return False
    
    def verify_dict(self, data: Dict, signature: str, public_key: bytes = None) -> bool:
        """
        Verify a dictionary signature.
        
        Args:
            data: Dictionary that was signed
            signature: Base64-encoded signature
            public_key: Public key bytes
            
        Returns:
            True if signature is valid
        """
        # Canonical JSON serialization
        json_bytes = json.dumps(data, sort_keys=True, default=str).encode('utf-8')
        return self.verify(json_bytes, signature, public_key)
    
    def get_public_key(self) -> Optional[bytes]:
        """
        Get the public key bytes.
        
        Returns:
            Public key bytes or None if not loaded
        """
        if self._verify_key:
            return bytes(self._verify_key)
        return None
    
    def get_public_key_hex(self) -> Optional[str]:
        """
        Get the public key as hex string.
        
        Returns:
            Hex-encoded public key or None
        """
        pk = self.get_public_key()
        if pk:
            return pk.hex()
        return None
    
    def is_loaded(self) -> bool:
        """Check if a keypair is loaded."""
        return self._signing_key is not None
    
    @staticmethod
    def is_available() -> bool:
        """Check if Ed25519 signing is available."""
        return NACL_AVAILABLE


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
        if not signer.is_loaded():
            signer.generate_keypair()
    
    # Create copy
    signed_event = event.copy()
    
    # Sign
    signature = signer.sign_dict(event)
    signed_event['signature'] = signature
    signed_event['signed_at'] = datetime.utcnow().isoformat() + 'Z'
    
    return signed_event


def verify_audit_event(event: Dict, public_key: bytes = None) -> bool:
    """
    Verify an audit event signature.
    
    Args:
        event: Event dictionary with signature
        public_key: Public key for verification
        
    Returns:
        True if signature is valid
    """
    signature = event.get('signature')
    if not signature:
        return False
    
    # Create event copy without signature
    event_copy = {k: v for k, v in event.items() if k not in ('signature', 'signed_at')}
    
    signer = AuditSigner()
    return signer.verify_dict(event_copy, signature, public_key)


def create_audit_signer(config: Dict = None) -> AuditSigner:
    """
    Factory function to create configured audit signer.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Configured AuditSigner instance
    """
    signer = AuditSigner(config)
    
    # Check for key path in config
    key_path = config.get('audit', {}).get('signing_key_path')
    
    if key_path:
        key_path = Path(key_path)
        
        if key_path.exists():
            signer.load_keypair(key_path)
        else:
            # Generate new keypair
            signer.generate_keypair()
            signer.save_keypair(key_path)
            signer._logger.info(f"Generated new audit signing key: {key_path}")
    
    return signer
