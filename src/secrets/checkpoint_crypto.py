"""
Checkpoint Cryptography for TITAN FUSE Protocol.

ITEM-SEC-03 Implementation:
- AES-256-GCM encryption for checkpoints
- Key derivation from passphrase or key file
- Secure key storage integration

Author: TITAN FUSE Team
Version: 3.3.0
"""

import os
import json
import hashlib
import secrets as crypto_secrets
from pathlib import Path
from typing import Dict, Tuple, Optional
from datetime import datetime
import logging
import base64

# Try to import cryptography
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    AESGCM = None


class CheckpointCryptoError(Exception):
    """Error in checkpoint cryptography."""
    pass


class CheckpointCrypto:
    """
    AES-256-GCM encryption for checkpoint files.
    
    Features:
    - AES-256-GCM authenticated encryption
    - Key derivation from passphrase (PBKDF2)
    - Random nonce for each encryption
    - Integrity verification built-in
    
    Usage:
        crypto = CheckpointCrypto()
        
        # Generate key from passphrase
        key = crypto.derive_key("my-passphrase", salt)
        
        # Encrypt
        encrypted = crypto.encrypt(data, key)
        
        # Decrypt
        decrypted = crypto.decrypt(encrypted, key)
        
        # Or use convenience methods
        crypto.encrypt_file(input_path, output_path, key)
        crypto.decrypt_file(input_path, output_path, key)
    """
    
    KEY_SIZE = 32  # 256 bits
    NONCE_SIZE = 12  # 96 bits (recommended for GCM)
    SALT_SIZE = 16  # 128 bits
    ITERATIONS = 100000  # PBKDF2 iterations
    
    def __init__(self, config: Dict = None):
        """
        Initialize checkpoint crypto.
        
        Args:
            config: Configuration dictionary
        """
        if not CRYPTO_AVAILABLE:
            raise ImportError(
                "cryptography package not installed. "
                "Install with: pip install cryptography"
            )
        
        self.config = config or {}
        self._logger = logging.getLogger(__name__)
    
    def derive_key(self, passphrase: str, salt: bytes = None) -> Tuple[bytes, bytes]:
        """
        Derive encryption key from passphrase.
        
        Uses PBKDF2-HMAC-SHA256 for key derivation.
        
        Args:
            passphrase: User passphrase
            salt: Salt bytes (generates new if not provided)
            
        Returns:
            Tuple of (key, salt)
        """
        if salt is None:
            salt = crypto_secrets.token_bytes(self.SALT_SIZE)
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=self.KEY_SIZE,
            salt=salt,
            iterations=self.ITERATIONS,
            backend=default_backend()
        )
        
        key = kdf.derive(passphrase.encode('utf-8'))
        
        return key, salt
    
    def generate_key(self) -> bytes:
        """
        Generate a random encryption key.
        
        Returns:
            Random 256-bit key
        """
        return crypto_secrets.token_bytes(self.KEY_SIZE)
    
    def encrypt(self, data: bytes, key: bytes) -> bytes:
        """
        Encrypt data with AES-256-GCM.
        
        Args:
            data: Plaintext data
            key: 256-bit encryption key
            
        Returns:
            Encrypted data with nonce prepended
        """
        if len(key) != self.KEY_SIZE:
            raise CheckpointCryptoError(f"Key must be {self.KEY_SIZE} bytes")
        
        # Generate random nonce
        nonce = crypto_secrets.token_bytes(self.NONCE_SIZE)
        
        # Encrypt
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, data, None)
        
        # Prepend nonce to ciphertext
        return nonce + ciphertext
    
    def decrypt(self, data: bytes, key: bytes) -> bytes:
        """
        Decrypt data with AES-256-GCM.
        
        Args:
            data: Encrypted data (nonce + ciphertext)
            key: 256-bit encryption key
            
        Returns:
            Plaintext data
            
        Raises:
            CheckpointCryptoError: If decryption fails
        """
        if len(key) != self.KEY_SIZE:
            raise CheckpointCryptoError(f"Key must be {self.KEY_SIZE} bytes")
        
        if len(data) < self.NONCE_SIZE + 1:
            raise CheckpointCryptoError("Data too short")
        
        # Extract nonce and ciphertext
        nonce = data[:self.NONCE_SIZE]
        ciphertext = data[self.NONCE_SIZE:]
        
        try:
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext
        except Exception as e:
            raise CheckpointCryptoError(f"Decryption failed: {e}")
    
    def encrypt_dict(self, data: Dict, key: bytes) -> bytes:
        """
        Encrypt a dictionary.
        
        Args:
            data: Dictionary to encrypt
            key: Encryption key
            
        Returns:
            Encrypted bytes
        """
        json_bytes = json.dumps(data, default=str).encode('utf-8')
        return self.encrypt(json_bytes, key)
    
    def decrypt_dict(self, data: bytes, key: bytes) -> Dict:
        """
        Decrypt to a dictionary.
        
        Args:
            data: Encrypted bytes
            key: Encryption key
            
        Returns:
            Decrypted dictionary
        """
        json_bytes = self.decrypt(data, key)
        return json.loads(json_bytes.decode('utf-8'))
    
    def encrypt_file(self, input_path: Path, output_path: Path, key: bytes) -> Dict:
        """
        Encrypt a file.
        
        Args:
            input_path: Path to plaintext file
            output_path: Path for encrypted output
            key: Encryption key
            
        Returns:
            Metadata dictionary
        """
        # Read input
        with open(input_path, 'rb') as f:
            plaintext = f.read()
        
        # Encrypt
        ciphertext = self.encrypt(plaintext, key)
        
        # Write output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'wb') as f:
            f.write(ciphertext)
        
        return {
            'input_size': len(plaintext),
            'output_size': len(ciphertext),
            'algorithm': 'AES-256-GCM',
            'encrypted_at': datetime.utcnow().isoformat() + 'Z'
        }
    
    def decrypt_file(self, input_path: Path, output_path: Path, key: bytes) -> Dict:
        """
        Decrypt a file.
        
        Args:
            input_path: Path to encrypted file
            output_path: Path for decrypted output
            key: Encryption key
            
        Returns:
            Metadata dictionary
        """
        # Read input
        with open(input_path, 'rb') as f:
            ciphertext = f.read()
        
        # Decrypt
        plaintext = self.decrypt(ciphertext, key)
        
        # Write output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'wb') as f:
            f.write(plaintext)
        
        return {
            'input_size': len(ciphertext),
            'output_size': len(plaintext),
            'algorithm': 'AES-256-GCM',
            'decrypted_at': datetime.utcnow().isoformat() + 'Z'
        }
    
    def key_to_string(self, key: bytes) -> str:
        """Convert key to base64 string for storage."""
        return base64.b64encode(key).decode('ascii')
    
    def key_from_string(self, key_string: str) -> bytes:
        """Convert base64 string back to key."""
        return base64.b64decode(key_string.encode('ascii'))
    
    def save_key(self, key: bytes, path: Path, passphrase: str = None) -> None:
        """
        Save key to file.
        
        If passphrase provided, key is encrypted before saving.
        
        Args:
            key: Encryption key
            path: Output path
            passphrase: Optional passphrase to encrypt the key
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        
        if passphrase:
            # Derive wrapping key
            salt = crypto_secrets.token_bytes(self.SALT_SIZE)
            wrapping_key, _ = self.derive_key(passphrase, salt)
            
            # Encrypt the key
            encrypted_key = self.encrypt(key, wrapping_key)
            
            # Save salt + encrypted key
            with open(path, 'wb') as f:
                f.write(salt + encrypted_key)
        else:
            # Save plaintext key (WARNING: not secure!)
            self._logger.warning("Saving key without encryption is not secure!")
            with open(path, 'w') as f:
                f.write(self.key_to_string(key))
    
    def load_key(self, path: Path, passphrase: str = None) -> bytes:
        """
        Load key from file.
        
        Args:
            path: Key file path
            passphrase: Passphrase if key is encrypted
            
        Returns:
            Encryption key
        """
        with open(path, 'rb') as f:
            data = f.read()
        
        if passphrase:
            # Extract salt and encrypted key
            salt = data[:self.SALT_SIZE]
            encrypted_key = data[self.SALT_SIZE:]
            
            # Derive wrapping key
            wrapping_key, _ = self.derive_key(passphrase, salt)
            
            # Decrypt the key
            return self.decrypt(encrypted_key, wrapping_key)
        else:
            # Plaintext key
            return self.key_from_string(data.decode('ascii'))


def encrypt_checkpoint(data: Dict, key: bytes = None, passphrase: str = None) -> bytes:
    """
    Convenience function to encrypt checkpoint data.
    
    Args:
        data: Checkpoint dictionary
        key: Encryption key (derived from passphrase if not provided)
        passphrase: Passphrase to derive key
        
    Returns:
        Encrypted checkpoint bytes
    """
    crypto = CheckpointCrypto()
    
    if key is None:
        if passphrase is None:
            raise CheckpointCryptoError("Either key or passphrase required")
        key, _ = crypto.derive_key(passphrase)
    
    return crypto.encrypt_dict(data, key)


def decrypt_checkpoint(data: bytes, key: bytes = None, passphrase: str = None, 
                       salt: bytes = None) -> Dict:
    """
    Convenience function to decrypt checkpoint data.
    
    Args:
        data: Encrypted checkpoint bytes
        key: Encryption key (derived from passphrase if not provided)
        passphrase: Passphrase to derive key
        salt: Salt for key derivation
        
    Returns:
        Decrypted checkpoint dictionary
    """
    crypto = CheckpointCrypto()
    
    if key is None:
        if passphrase is None:
            raise CheckpointCryptoError("Either key or passphrase required")
        key, _ = crypto.derive_key(passphrase, salt)
    
    return crypto.decrypt_dict(data, key)
