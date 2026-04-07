"""
Checkpoint Encryption Module for TITAN FUSE Protocol.

ITEM-STOR-03: Checkpoint Encryption

Provides AES-256-GCM encryption for checkpoint data at rest.
Integration with SecretStore (ITEM-SEC-03) for key management.

Features:
- AES-256-GCM authenticated encryption
- Key generation and derivation
- Integration with SecretStore for key retrieval
- Transparent encryption/decryption for checkpoints

Security:
- 256-bit keys (32 bytes)
- 96-bit nonces (12 bytes) for GCM
- Authenticated encryption with associated data (AEAD)
- Key derivation from password using PBKDF2

Author: TITAN FUSE Team
Version: 3.3.0
"""

import os
import secrets
import hashlib
import logging
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

# Try to import cryptography library
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    AESGCM = None


class EncryptionAlgorithm(Enum):
    """Supported encryption algorithms."""
    AES_256_GCM = "aes-256-gcm"
    NONE = "none"
    
    @classmethod
    def from_string(cls, value: str) -> 'EncryptionAlgorithm':
        """Parse algorithm from config string."""
        mapping = {
            'aes-256-gcm': cls.AES_256_GCM,
            'aes256gcm': cls.AES_256_GCM,
            'none': cls.NONE,
            'null': cls.NONE,
        }
        return mapping.get(value.lower(), cls.NONE)


@dataclass
class EncryptionResult:
    """Result of encryption operation."""
    success: bool
    data: bytes = b''
    nonce: bytes = b''
    algorithm: EncryptionAlgorithm = EncryptionAlgorithm.NONE
    error: str = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'success': self.success,
            'algorithm': self.algorithm.value,
            'nonce_length': len(self.nonce) if self.nonce else 0,
            'data_length': len(self.data) if self.data else 0,
            'error': self.error
        }


@dataclass
class DecryptionResult:
    """Result of decryption operation."""
    success: bool
    data: bytes = b''
    algorithm: EncryptionAlgorithm = EncryptionAlgorithm.NONE
    error: str = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'success': self.success,
            'algorithm': self.algorithm.value,
            'data_length': len(self.data) if self.data else 0,
            'error': self.error
        }


class EncryptionError(Exception):
    """Base exception for encryption errors."""
    pass


class KeyNotFoundError(EncryptionError):
    """Raised when encryption key is not found."""
    pass


class DecryptionError(EncryptionError):
    """Raised when decryption fails."""
    pass


class CheckpointEncryption:
    """
    AES-256-GCM encryption for checkpoint data.
    
    ITEM-STOR-03 Implementation:
    - encrypt(data, key) -> encrypted_data
    - decrypt(data, key) -> decrypted_data
    - generate_key() -> key
    - derive_key(password, salt) -> key
    
    Usage:
        # Generate a new key
        encryption = CheckpointEncryption()
        key = encryption.generate_key()
        
        # Encrypt data
        encrypted = encryption.encrypt(b'sensitive data', key)
        
        # Decrypt data
        decrypted = encryption.decrypt(encrypted.data, key, encrypted.nonce)
        
        # Or use with SecretStore
        from src.secrets import get_secret_store
        secret_store = get_secret_store()
        key = secret_store.get('checkpoint_key')
    """
    
    ALGORITHM = EncryptionAlgorithm.AES_256_GCM
    KEY_SIZE = 32  # 256 bits
    NONCE_SIZE = 12  # 96 bits for GCM
    SALT_SIZE = 16  # 128 bits for key derivation
    PBKDF2_ITERATIONS = 100000  # Recommended minimum
    
    def __init__(
        self,
        algorithm: EncryptionAlgorithm = EncryptionAlgorithm.AES_256_GCM,
        secret_store = None
    ):
        """
        Initialize CheckpointEncryption.
        
        Args:
            algorithm: Encryption algorithm to use
            secret_store: SecretStore instance for key retrieval
        """
        self.logger = logging.getLogger(__name__)
        self.algorithm = algorithm
        self.secret_store = secret_store
        
        if algorithm != EncryptionAlgorithm.NONE and not CRYPTO_AVAILABLE:
            self.logger.warning(
                "cryptography package not available. "
                "Install with: pip install cryptography"
            )
            self.algorithm = EncryptionAlgorithm.NONE
    
    def generate_key(self) -> bytes:
        """
        Generate a new random encryption key.
        
        Returns:
            32-byte (256-bit) encryption key
        """
        return secrets.token_bytes(self.KEY_SIZE)
    
    def derive_key(
        self,
        password: str,
        salt: bytes = None,
        iterations: int = None
    ) -> Tuple[bytes, bytes]:
        """
        Derive an encryption key from a password.
        
        Uses PBKDF2-HMAC-SHA256 for key derivation.
        
        Args:
            password: Password string
            salt: Optional salt (generated if not provided)
            iterations: Number of PBKDF2 iterations
            
        Returns:
            Tuple of (key, salt)
        """
        if not CRYPTO_AVAILABLE:
            raise EncryptionError(
                "cryptography package required for key derivation. "
                "Install with: pip install cryptography"
            )
        
        # Generate salt if not provided
        if salt is None:
            salt = secrets.token_bytes(self.SALT_SIZE)
        
        # Use default iterations if not specified
        if iterations is None:
            iterations = self.PBKDF2_ITERATIONS
        
        # Derive key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=self.KEY_SIZE,
            salt=salt,
            iterations=iterations,
            backend=default_backend()
        )
        
        key = kdf.derive(password.encode('utf-8'))
        
        return key, salt
    
    def encrypt(
        self,
        data: bytes,
        key: bytes = None,
        associated_data: bytes = None
    ) -> EncryptionResult:
        """
        Encrypt data using AES-256-GCM.
        
        Args:
            data: Data to encrypt
            key: Encryption key (32 bytes). If not provided, uses secret_store.
            associated_data: Optional authenticated associated data
            
        Returns:
            EncryptionResult with encrypted data and nonce
        """
        if self.algorithm == EncryptionAlgorithm.NONE:
            return EncryptionResult(
                success=True,
                data=data,
                algorithm=EncryptionAlgorithm.NONE
            )
        
        if not CRYPTO_AVAILABLE:
            return EncryptionResult(
                success=False,
                error="cryptography package not available"
            )
        
        try:
            # Get key from secret_store if not provided
            if key is None:
                key = self._get_key_from_store()
            
            if key is None:
                return EncryptionResult(
                    success=False,
                    error="No encryption key provided"
                )
            
            # Validate key size
            if len(key) != self.KEY_SIZE:
                return EncryptionResult(
                    success=False,
                    error=f"Invalid key size: expected {self.KEY_SIZE}, got {len(key)}"
                )
            
            # Generate random nonce
            nonce = secrets.token_bytes(self.NONCE_SIZE)
            
            # Create AESGCM cipher
            aesgcm = AESGCM(key)
            
            # Encrypt with associated data
            encrypted = aesgcm.encrypt(
                nonce,
                data,
                associated_data
            )
            
            self.logger.debug(
                f"Encrypted {len(data)} bytes to {len(encrypted)} bytes"
            )
            
            return EncryptionResult(
                success=True,
                data=encrypted,
                nonce=nonce,
                algorithm=self.algorithm
            )
            
        except Exception as e:
            self.logger.error(f"Encryption failed: {e}")
            return EncryptionResult(
                success=False,
                error=str(e)
            )
    
    def decrypt(
        self,
        data: bytes,
        key: bytes = None,
        nonce: bytes = None,
        associated_data: bytes = None
    ) -> DecryptionResult:
        """
        Decrypt data using AES-256-GCM.
        
        Args:
            data: Encrypted data
            key: Decryption key (32 bytes). If not provided, uses secret_store.
            nonce: Nonce used during encryption (12 bytes)
            associated_data: Optional authenticated associated data
            
        Returns:
            DecryptionResult with decrypted data
        """
        if self.algorithm == EncryptionAlgorithm.NONE:
            return DecryptionResult(
                success=True,
                data=data,
                algorithm=EncryptionAlgorithm.NONE
            )
        
        if not CRYPTO_AVAILABLE:
            return DecryptionResult(
                success=False,
                error="cryptography package not available"
            )
        
        try:
            # Get key from secret_store if not provided
            if key is None:
                key = self._get_key_from_store()
            
            if key is None:
                return DecryptionResult(
                    success=False,
                    error="No decryption key provided"
                )
            
            # Validate inputs
            if len(key) != self.KEY_SIZE:
                return DecryptionResult(
                    success=False,
                    error=f"Invalid key size: expected {self.KEY_SIZE}, got {len(key)}"
                )
            
            if nonce is None:
                return DecryptionResult(
                    success=False,
                    error="Nonce is required for decryption"
                )
            
            if len(nonce) != self.NONCE_SIZE:
                return DecryptionResult(
                    success=False,
                    error=f"Invalid nonce size: expected {self.NONCE_SIZE}, got {len(nonce)}"
                )
            
            # Create AESGCM cipher
            aesgcm = AESGCM(key)
            
            # Decrypt with associated data
            decrypted = aesgcm.decrypt(
                nonce,
                data,
                associated_data
            )
            
            self.logger.debug(
                f"Decrypted {len(data)} bytes to {len(decrypted)} bytes"
            )
            
            return DecryptionResult(
                success=True,
                data=decrypted,
                algorithm=self.algorithm
            )
            
        except Exception as e:
            self.logger.error(f"Decryption failed: {e}")
            return DecryptionResult(
                success=False,
                error=str(e)
            )
    
    def _get_key_from_store(self) -> Optional[bytes]:
        """
        Get encryption key from SecretStore.
        
        Returns:
            Encryption key or None if not found
        """
        if self.secret_store is None:
            return None
        
        try:
            key_b64 = self.secret_store.get('checkpoint_key')
            if key_b64:
                import base64
                return base64.b64decode(key_b64)
        except Exception as e:
            self.logger.warning(f"Failed to get key from secret store: {e}")
        
        return None
    
    def encrypt_with_nonce_prefix(
        self,
        data: bytes,
        key: bytes = None
    ) -> EncryptionResult:
        """
        Encrypt data with nonce prepended to ciphertext.
        
        This is a convenience method that stores the nonce with the
        encrypted data, making storage simpler.
        
        Format: [nonce (12 bytes)][ciphertext]
        
        Args:
            data: Data to encrypt
            key: Encryption key
            
        Returns:
            EncryptionResult with nonce+data combined
        """
        result = self.encrypt(data, key)
        
        if not result.success:
            return result
        
        # Prepend nonce to encrypted data
        combined = result.nonce + result.data
        
        return EncryptionResult(
            success=True,
            data=combined,
            nonce=result.nonce,  # Still return nonce separately
            algorithm=result.algorithm
        )
    
    def decrypt_with_nonce_prefix(
        self,
        data: bytes,
        key: bytes = None
    ) -> DecryptionResult:
        """
        Decrypt data with nonce prepended to ciphertext.
        
        Args:
            data: Encrypted data with nonce prefix
            key: Decryption key
            
        Returns:
            DecryptionResult with decrypted data
        """
        if self.algorithm == EncryptionAlgorithm.NONE:
            return DecryptionResult(
                success=True,
                data=data,
                algorithm=EncryptionAlgorithm.NONE
            )
        
        # Extract nonce and ciphertext
        if len(data) < self.NONCE_SIZE:
            return DecryptionResult(
                success=False,
                error="Data too short to contain nonce"
            )
        
        nonce = data[:self.NONCE_SIZE]
        ciphertext = data[self.NONCE_SIZE:]
        
        return self.decrypt(ciphertext, key, nonce)
    
    def is_available(self) -> bool:
        """
        Check if encryption is available.
        
        Returns:
            True if cryptography package is installed and algorithm is set
        """
        return CRYPTO_AVAILABLE and self.algorithm != EncryptionAlgorithm.NONE
    
    def get_algorithm_info(self) -> Dict[str, Any]:
        """
        Get information about the encryption algorithm.
        
        Returns:
            Dictionary with algorithm details
        """
        return {
            'algorithm': self.algorithm.value,
            'key_size': self.KEY_SIZE,
            'nonce_size': self.NONCE_SIZE,
            'salt_size': self.SALT_SIZE,
            'available': self.is_available(),
            'crypto_package': CRYPTO_AVAILABLE
        }


def encrypt_checkpoint(
    data: bytes,
    key: bytes = None,
    secret_store = None,
    algorithm: str = "aes-256-gcm"
) -> EncryptionResult:
    """
    Convenience function to encrypt checkpoint data.
    
    Args:
        data: Checkpoint data to encrypt
        key: Encryption key (optional, uses secret_store if not provided)
        secret_store: SecretStore instance for key retrieval
        algorithm: Encryption algorithm string
        
    Returns:
        EncryptionResult with encrypted data
    """
    algo = EncryptionAlgorithm.from_string(algorithm)
    encryption = CheckpointEncryption(algorithm=algo, secret_store=secret_store)
    return encryption.encrypt_with_nonce_prefix(data, key)


def decrypt_checkpoint(
    data: bytes,
    key: bytes = None,
    secret_store = None,
    algorithm: str = "aes-256-gcm"
) -> DecryptionResult:
    """
    Convenience function to decrypt checkpoint data.
    
    Args:
        data: Encrypted checkpoint data
        key: Decryption key (optional, uses secret_store if not provided)
        secret_store: SecretStore instance for key retrieval
        algorithm: Encryption algorithm string
        
    Returns:
        DecryptionResult with decrypted data
    """
    algo = EncryptionAlgorithm.from_string(algorithm)
    encryption = CheckpointEncryption(algorithm=algo, secret_store=secret_store)
    return encryption.decrypt_with_nonce_prefix(data, key)


def generate_encryption_key() -> bytes:
    """
    Generate a new encryption key for checkpoint encryption.
    
    Returns:
        32-byte encryption key
    """
    return secrets.token_bytes(CheckpointEncryption.KEY_SIZE)


def get_encryption(config: Dict = None, secret_store = None) -> CheckpointEncryption:
    """
    Factory function to create CheckpointEncryption instance.
    
    Args:
        config: Configuration dictionary
        secret_store: SecretStore instance
        
    Returns:
        Configured CheckpointEncryption instance
    """
    config = config or {}
    checkpoint_config = config.get('checkpoint', {})
    
    algorithm_str = checkpoint_config.get('encryption', 'none')
    algorithm = EncryptionAlgorithm.from_string(algorithm_str)
    
    return CheckpointEncryption(
        algorithm=algorithm,
        secret_store=secret_store
    )
