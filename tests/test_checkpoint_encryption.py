"""
Tests for Checkpoint Encryption (ITEM-STOR-03).

Tests AES-256-GCM encryption for checkpoint data including:
- Key generation and derivation
- Encryption and decryption
- Error handling
- Integration with SecretStore
"""

import pytest
import os
import base64
from unittest.mock import Mock, MagicMock, patch

from src.storage.encryption import (
    CheckpointEncryption,
    EncryptionAlgorithm,
    EncryptionResult,
    DecryptionResult,
    EncryptionError,
    KeyNotFoundError,
    DecryptionError,
    encrypt_checkpoint,
    decrypt_checkpoint,
    generate_encryption_key,
    get_encryption
)


class TestEncryptionAlgorithm:
    """Tests for EncryptionAlgorithm enum."""
    
    def test_from_string_aes256gcm(self):
        """Test parsing AES-256-GCM algorithm string."""
        algo = EncryptionAlgorithm.from_string("aes-256-gcm")
        assert algo == EncryptionAlgorithm.AES_256_GCM
    
    def test_from_string_none(self):
        """Test parsing 'none' algorithm string."""
        algo = EncryptionAlgorithm.from_string("none")
        assert algo == EncryptionAlgorithm.NONE
    
    def test_from_string_unknown(self):
        """Test parsing unknown algorithm string."""
        algo = EncryptionAlgorithm.from_string("unknown-algo")
        assert algo == EncryptionAlgorithm.NONE


class TestCheckpointEncryption:
    """Tests for CheckpointEncryption class."""
    
    def test_initialization_default(self):
        """Test default initialization."""
        encryption = CheckpointEncryption()
        
        if encryption.is_available():
            assert encryption.algorithm == EncryptionAlgorithm.AES_256_GCM
        else:
            assert encryption.algorithm == EncryptionAlgorithm.NONE
    
    def test_initialization_none_algorithm(self):
        """Test initialization with NONE algorithm."""
        encryption = CheckpointEncryption(algorithm=EncryptionAlgorithm.NONE)
        
        assert encryption.algorithm == EncryptionAlgorithm.NONE
        assert encryption.is_available() == False
    
    def test_generate_key(self):
        """Test key generation."""
        encryption = CheckpointEncryption()
        key = encryption.generate_key()
        
        assert len(key) == 32  # 256 bits
        assert isinstance(key, bytes)
        
        # Each key should be unique
        key2 = encryption.generate_key()
        assert key != key2
    
    def test_derive_key_with_salt(self):
        """Test key derivation with provided salt."""
        encryption = CheckpointEncryption()
        password = "test-password"
        salt = os.urandom(16)
        
        key, returned_salt = encryption.derive_key(password, salt)
        
        assert len(key) == 32
        assert returned_salt == salt
    
    def test_derive_key_without_salt(self):
        """Test key derivation with auto-generated salt."""
        encryption = CheckpointEncryption()
        password = "test-password"
        
        key, salt = encryption.derive_key(password)
        
        assert len(key) == 32
        assert len(salt) == 16
    
    def test_derive_key_deterministic(self):
        """Test that same password and salt produce same key."""
        encryption = CheckpointEncryption()
        password = "test-password"
        salt = os.urandom(16)
        
        key1, _ = encryption.derive_key(password, salt)
        key2, _ = encryption.derive_key(password, salt)
        
        assert key1 == key2
    
    def test_encrypt_decrypt_roundtrip(self):
        """Test encrypt-decrypt roundtrip."""
        encryption = CheckpointEncryption()
        
        if not encryption.is_available():
            pytest.skip("cryptography package not available")
        
        key = encryption.generate_key()
        plaintext = b"This is sensitive checkpoint data"
        
        # Encrypt
        encrypt_result = encryption.encrypt(plaintext, key)
        
        assert encrypt_result.success
        assert encrypt_result.data != plaintext
        assert len(encrypt_result.nonce) == 12
        
        # Decrypt
        decrypt_result = encryption.decrypt(
            encrypt_result.data,
            key,
            encrypt_result.nonce
        )
        
        assert decrypt_result.success
        assert decrypt_result.data == plaintext
    
    def test_encrypt_with_nonce_prefix(self):
        """Test encryption with nonce prefix."""
        encryption = CheckpointEncryption()
        
        if not encryption.is_available():
            pytest.skip("cryptography package not available")
        
        key = encryption.generate_key()
        plaintext = b"Checkpoint data with nonce prefix"
        
        # Encrypt with nonce prefix
        encrypt_result = encryption.encrypt_with_nonce_prefix(plaintext, key)
        
        assert encrypt_result.success
        assert len(encrypt_result.data) == len(plaintext) + 12 + 16  # +nonce +tag
    
    def test_decrypt_with_nonce_prefix(self):
        """Test decryption with nonce prefix."""
        encryption = CheckpointEncryption()
        
        if not encryption.is_available():
            pytest.skip("cryptography package not available")
        
        key = encryption.generate_key()
        plaintext = b"Checkpoint data for nonce prefix test"
        
        # Encrypt
        encrypt_result = encryption.encrypt_with_nonce_prefix(plaintext, key)
        
        # Decrypt
        decrypt_result = encryption.decrypt_with_nonce_prefix(
            encrypt_result.data,
            key
        )
        
        assert decrypt_result.success
        assert decrypt_result.data == plaintext
    
    def test_encrypt_none_algorithm(self):
        """Test that NONE algorithm passes data through."""
        encryption = CheckpointEncryption(algorithm=EncryptionAlgorithm.NONE)
        
        data = b"unencrypted data"
        result = encryption.encrypt(data)
        
        assert result.success
        assert result.data == data
        assert result.algorithm == EncryptionAlgorithm.NONE
    
    def test_decrypt_none_algorithm(self):
        """Test that NONE algorithm passes data through."""
        encryption = CheckpointEncryption(algorithm=EncryptionAlgorithm.NONE)
        
        data = b"unencrypted data"
        result = encryption.decrypt(data)
        
        assert result.success
        assert result.data == data
    
    def test_encrypt_no_key(self):
        """Test encryption without key."""
        encryption = CheckpointEncryption()
        
        if not encryption.is_available():
            pytest.skip("cryptography package not available")
        
        result = encryption.encrypt(b"test data", key=None)
        
        assert not result.success
        assert "No encryption key" in result.error
    
    def test_decrypt_no_key(self):
        """Test decryption without key."""
        encryption = CheckpointEncryption()
        
        if not encryption.is_available():
            pytest.skip("cryptography package not available")
        
        result = encryption.decrypt(b"test data", key=None, nonce=b"123456789012")
        
        assert not result.success
        assert "No decryption key" in result.error
    
    def test_decrypt_wrong_key(self):
        """Test decryption with wrong key."""
        encryption = CheckpointEncryption()
        
        if not encryption.is_available():
            pytest.skip("cryptography package not available")
        
        key1 = encryption.generate_key()
        key2 = encryption.generate_key()  # Different key
        
        plaintext = b"Secret data"
        
        # Encrypt with key1
        encrypt_result = encryption.encrypt(plaintext, key1)
        
        # Try to decrypt with key2
        decrypt_result = encryption.decrypt(
            encrypt_result.data,
            key2,
            encrypt_result.nonce
        )
        
        assert not decrypt_result.success
    
    def test_decrypt_missing_nonce(self):
        """Test decryption without nonce."""
        encryption = CheckpointEncryption()
        
        if not encryption.is_available():
            pytest.skip("cryptography package not available")
        
        key = encryption.generate_key()
        
        result = encryption.decrypt(b"test data", key, nonce=None)
        
        assert not result.success
        assert "Nonce is required" in result.error
    
    def test_get_algorithm_info(self):
        """Test getting algorithm info."""
        encryption = CheckpointEncryption()
        info = encryption.get_algorithm_info()
        
        assert 'algorithm' in info
        assert 'key_size' in info
        assert 'nonce_size' in info
        assert 'available' in info


class TestCheckpointEncryptionSecretStore:
    """Tests for encryption with SecretStore integration."""
    
    def test_encrypt_with_secret_store(self):
        """Test encryption using key from secret store."""
        encryption = CheckpointEncryption()
        
        if not encryption.is_available():
            pytest.skip("cryptography package not available")
        
        # Create mock secret store
        key = encryption.generate_key()
        mock_store = Mock()
        mock_store.get.return_value = base64.b64encode(key).decode('utf-8')
        
        encryption.secret_store = mock_store
        
        plaintext = b"Data encrypted with key from secret store"
        
        # Encrypt (key from secret store)
        encrypt_result = encryption.encrypt(plaintext)
        
        assert encrypt_result.success
        
        # Decrypt
        decrypt_result = encryption.decrypt(
            encrypt_result.data,
            key,
            encrypt_result.nonce
        )
        
        assert decrypt_result.success
        assert decrypt_result.data == plaintext


class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    def test_generate_encryption_key(self):
        """Test generate_encryption_key function."""
        key = generate_encryption_key()
        
        assert len(key) == 32
        assert isinstance(key, bytes)
    
    def test_encrypt_decrypt_checkpoint(self):
        """Test encrypt_checkpoint and decrypt_checkpoint functions."""
        encryption = CheckpointEncryption()
        
        if not encryption.is_available():
            pytest.skip("cryptography package not available")
        
        key = encryption.generate_key()
        data = b"Checkpoint data for convenience functions"
        
        # Encrypt
        encrypt_result = encrypt_checkpoint(data, key)
        
        assert encrypt_result.success
        
        # Decrypt
        decrypt_result = decrypt_checkpoint(encrypt_result.data, key)
        
        assert decrypt_result.success
        assert decrypt_result.data == data
    
    def test_get_encryption_factory(self):
        """Test get_encryption factory function."""
        config = {
            'checkpoint': {
                'encryption': 'aes-256-gcm'
            }
        }
        
        encryption = get_encryption(config)
        
        assert isinstance(encryption, CheckpointEncryption)
    
    def test_get_encryption_none(self):
        """Test get_encryption with none algorithm."""
        config = {
            'checkpoint': {
                'encryption': 'none'
            }
        }
        
        encryption = get_encryption(config)
        
        assert encryption.algorithm == EncryptionAlgorithm.NONE


class TestEncryptionResults:
    """Tests for result dataclasses."""
    
    def test_encryption_result_to_dict(self):
        """Test EncryptionResult serialization."""
        result = EncryptionResult(
            success=True,
            data=b"encrypted",
            nonce=b"123456789012",
            algorithm=EncryptionAlgorithm.AES_256_GCM
        )
        
        d = result.to_dict()
        
        assert d['success'] == True
        assert d['algorithm'] == 'aes-256-gcm'
        assert d['nonce_length'] == 12
        assert d['data_length'] == 9
    
    def test_decryption_result_to_dict(self):
        """Test DecryptionResult serialization."""
        result = DecryptionResult(
            success=True,
            data=b"decrypted data",
            algorithm=EncryptionAlgorithm.AES_256_GCM
        )
        
        d = result.to_dict()
        
        assert d['success'] == True
        assert d['algorithm'] == 'aes-256-gcm'
        assert d['data_length'] == 14


class TestEncryptionErrors:
    """Tests for encryption error classes."""
    
    def test_encryption_error(self):
        """Test EncryptionError exception."""
        with pytest.raises(EncryptionError):
            raise EncryptionError("Test error")
    
    def test_key_not_found_error(self):
        """Test KeyNotFoundError exception."""
        with pytest.raises(KeyNotFoundError):
            raise KeyNotFoundError("Key not found")
    
    def test_decryption_error(self):
        """Test DecryptionError exception."""
        with pytest.raises(DecryptionError):
            raise DecryptionError("Decryption failed")


class TestEncryptionWithAssociatedData:
    """Tests for AEAD (Associated Authenticated Data)."""
    
    def test_encrypt_with_associated_data(self):
        """Test encryption with associated data."""
        encryption = CheckpointEncryption()
        
        if not encryption.is_available():
            pytest.skip("cryptography package not available")
        
        key = encryption.generate_key()
        plaintext = b"Sensitive data"
        aad = b"metadata: session-123"
        
        # Encrypt with AAD
        encrypt_result = encryption.encrypt(plaintext, key, aad)
        
        assert encrypt_result.success
        
        # Decrypt with same AAD
        decrypt_result = encryption.decrypt(
            encrypt_result.data,
            key,
            encrypt_result.nonce,
            aad
        )
        
        assert decrypt_result.success
        assert decrypt_result.data == plaintext
    
    def test_decrypt_with_wrong_aad(self):
        """Test that decryption fails with wrong AAD."""
        encryption = CheckpointEncryption()
        
        if not encryption.is_available():
            pytest.skip("cryptography package not available")
        
        key = encryption.generate_key()
        plaintext = b"Sensitive data"
        aad = b"metadata: session-123"
        
        # Encrypt with AAD
        encrypt_result = encryption.encrypt(plaintext, key, aad)
        
        # Try to decrypt with different AAD
        decrypt_result = encryption.decrypt(
            encrypt_result.data,
            key,
            encrypt_result.nonce,
            b"wrong-aad"
        )
        
        assert not decrypt_result.success


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
